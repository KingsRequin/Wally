#!/usr/bin/env python3
"""Audit des logs de conversation (JSONL) produits par ConversationLogger.

Scanne les fichiers ``logs/conversations/{platform}/{channel}/{YYYY-MM-DD}.jsonl``,
regroupe les events par ``trace_id`` (= cycle de vie d'un message) et remonte
automatiquement les anomalies comportementales de Wally :

  • réponse en double      → un trace avec >1 event ``message_out``
  • intention sans action  → un ``message_out`` qui promet une action mais 0 ``tool_called``
  • réponse vide           → ``message_out`` au contenu vide
  • réponse de secours     → ``raw_reply`` == fallback (LLM en échec)
  • latence anormale       → ``llm_call.latency_ms`` au-dessus du seuil

Trois journaux s'ajoutent au même format et ont leur propre vue :

  • ``overlay/bulles``  → ce que l'overlay a dit, et surtout ce qu'il a REFUSÉ
                          de dire (``--overlay``)
  • ``voice/{salon}``   → les demandes vocales, outils et latences (``--voice``)
  • ``reception``       → ce qui a bougé dans la minute suivant chaque prise de
                          parole (compté dans les deux vues ci-dessus)

Usage :
    python3 scripts/audit_traces.py                          # tout, aujourd'hui inclus
    python3 scripts/audit_traces.py --platform discord
    python3 scripts/audit_traces.py --channel général --date 2026-06-23
    python3 scripts/audit_traces.py --trace 134256...        # dump complet d'un trace
    python3 scripts/audit_traces.py --slow-ms 8000           # seuil latence
    python3 scripts/audit_traces.py --overlay                # bulles publiées vs refusées
    python3 scripts/audit_traces.py --voice                  # demandes vocales + latences
    python3 scripts/audit_traces.py --silences               # pourquoi il s'est tu
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Paris")
except Exception:  # pragma: no cover
    _TZ = None

# Tournures qui annoncent une action — sert à repérer les "je vais faire ça" suivis de rien.
_INTENT_RE = re.compile(
    r"\b(je vais|j'?ai (?:créé|ajouté|noté|programmé|lancé|fait)|je (?:te |vous )?"
    r"(?:le |la |les )?(?:rappelle|note|ajoute|programme|enregistre|cherche)|"
    r"c'?est (?:noté|fait)|je m'?en (?:occupe|charge)|laisse-moi)\b",
    re.IGNORECASE,
)
_FALLBACK_HINTS = ("désolé", "j'ai eu un souci", "réessaie")


def _iter_files(root: Path, platform: str | None, channel: str | None, date: str | None):
    pattern = f"{platform or '*'}/{'**' if not channel else f'*{channel}*'}/*.jsonl"
    for path in sorted(root.glob(pattern)):
        if date and date not in path.name:
            continue
        yield path


def _load(path: Path) -> list[dict]:
    events = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"  ⚠️  {path}:{i} ligne JSON illisible — ignorée")
    return events


def _group_by_trace(events: list[dict]) -> dict[str, list[dict]]:
    traces: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        traces[ev.get("trace_id", "?")].append(ev)
    return traces


def _of_type(trace: list[dict], t: str) -> list[dict]:
    return [e for e in trace if e.get("type") == t]


def audit(root: Path, platform, channel, date, slow_ms: int) -> None:
    files = list(_iter_files(root, platform, channel, date))
    if not files:
        print(f"Aucun fichier de log sous {root} (filtres: platform={platform} channel={channel} date={date})")
        return

    all_events: list[dict] = []
    for path in files:
        rel = path.relative_to(root)
        all_events.extend({**e, "_file": str(rel)} for e in _load(path))

    traces = _group_by_trace(all_events)
    n_in = len(_of_type(all_events, "message_in"))
    n_out = len(_of_type(all_events, "message_out"))
    latencies = [e["latency_ms"] for e in _of_type(all_events, "llm_call") if isinstance(e.get("latency_ms"), int)]

    print(f"\n{'='*70}")
    print(f"AUDIT — {len(files)} fichier(s), {len(all_events)} events, {len(traces)} traces")
    print(f"  messages entrants : {n_in}   |   réponses de Wally : {n_out}")
    if latencies:
        latencies.sort()
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        print(f"  latence LLM : moy {sum(latencies)//len(latencies)}ms   médiane {latencies[len(latencies)//2]}ms   p95 {p95}ms")
    print(f"{'='*70}\n")

    doublons, intentions, vides, fallbacks, lents = [], [], [], [], []
    for tid, trace in traces.items():
        outs = _of_type(trace, "message_out")
        tools = _of_type(trace, "tool_called")
        if len(outs) > 1:
            doublons.append((tid, trace, outs))
        for out in outs:
            content = (out.get("content") or "").strip()
            if not content:
                vides.append((tid, out))
            elif _INTENT_RE.search(content) and not tools:
                intentions.append((tid, out))
        for call in _of_type(trace, "llm_call"):
            reply = (call.get("raw_reply") or "").lower()
            if any(h in reply for h in _FALLBACK_HINTS) and len(reply) < 120:
                fallbacks.append((tid, call))
            if isinstance(call.get("latency_ms"), int) and call["latency_ms"] >= slow_ms:
                lents.append((tid, call))

    def _channel_of(trace):
        return trace[0].get("_file", "?")

    def _report(title, items, fmt):
        print(f"### {title} — {len(items)}")
        for item in items[:25]:
            print(fmt(item))
        if len(items) > 25:
            print(f"  … (+{len(items) - 25} autres)")
        print()

    _report(
        "🔴 RÉPONSES EN DOUBLE", doublons,
        lambda x: f"  trace {x[0]} [{_channel_of(x[1])}] — {len(x[2])} envois : "
                  + " || ".join(repr((o.get('content') or '')[:60]) for o in x[2]),
    )
    _report(
        "🟠 INTENTION ANNONCÉE SANS ACTION (tool)", intentions,
        lambda x: f"  trace {x[0]} — {repr((x[1].get('content') or '')[:90])}",
    )
    _report(
        "🟡 RÉPONSES VIDES", vides,
        lambda x: f"  trace {x[0]} — message_out vide",
    )
    _report(
        "🟤 RÉPONSES DE SECOURS (LLM en échec)", fallbacks,
        lambda x: f"  trace {x[0]} — {repr((x[1].get('raw_reply') or '')[:90])}",
    )
    _report(
        f"🐌 LATENCE ≥ {slow_ms}ms", lents,
        lambda x: f"  trace {x[0]} — {x[1].get('latency_ms')}ms (modèle {x[1].get('model')})",
    )

    if not any([doublons, intentions, vides, fallbacks, lents]):
        print("✅ Aucune anomalie détectée sur ce périmètre.\n")


def audit_cognitive(root: Path, date: str | None) -> None:
    """Analyse le flux cognitif (cerveau) loggé sous ``cognitive/brain/*.jsonl``.

    Ces events n'ont PAS de ``trace_id`` (ils ne passent donc pas par l'audit
    par trace) : compteur par type, SPEAK réellement envoyés, SPEAK supprimés
    (avec leur raison) et nombre de THINK ignorés (repos anti-rumination).
    """
    files = sorted((root / "cognitive" / "brain").glob("*.jsonl"))
    if date:
        files = [p for p in files if date in p.name]

    if not files:
        print(f"### 🧠 FLUX COGNITIF")
        print("  (aucun flux cognitif)\n")
        return

    events: list[dict] = []
    for path in files:
        events.extend(_load(path))

    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        counts[ev.get("type", "?")] += 1

    speaks = _of_type(events, "speak")
    suppressed = _of_type(events, "speak_suppressed")
    n_skipped = len(_of_type(events, "think_skipped"))

    def _trunc(s, n=80):
        s = (s or "").replace("\n", " ").strip()
        return s[:n]

    print(f"\n{'='*70}")
    print(f"AUDIT FLUX COGNITIF — {len(files)} fichier(s), {len(events)} events")
    print(f"{'='*70}\n")

    ordered = ["attn", "think", "decide", "speak", "act", "evolve",
               "speak_suppressed", "think_skipped"]
    print("### 🧠 COMPTEUR PAR TYPE")
    for t in ordered:
        if counts.get(t):
            print(f"  {t:<18} {counts[t]}")
    for t in sorted(counts):
        if t not in ordered:
            print(f"  {t:<18} {counts[t]}")
    print()

    print(f"### 🗣️  SPEAK ENVOYÉS — {len(speaks)}")
    for ev in speaks[:25]:
        chan = ev.get("channel", "?")
        text = ev.get("detail") or ev.get("text") or ev.get("message") or ""
        print(f"  [{chan}] {repr(_trunc(text))}")
    if len(speaks) > 25:
        print(f"  … (+{len(speaks) - 25} autres)")
    print()

    print(f"### 🤐 SPEAK SUPPRIMÉS — {len(suppressed)}")
    for ev in suppressed[:25]:
        chan = ev.get("channel", "?")
        reason = ev.get("reason", "?")
        msg = _trunc(ev.get("message") or "")
        print(f"  [{chan}] raison={reason} — {repr(msg)}")
    if len(suppressed) > 25:
        print(f"  … (+{len(suppressed) - 25} autres)")
    print()

    print(f"### 😴 THINK IGNORÉS (anti-rumination) — {n_skipped}\n")

    # Actions décidées qui n'ont rien produit : le trou de 20 % (66 décidées,
    # 56 journalisées) est désormais nommé, action par action et motif par motif.
    rejets = _of_type(events, "act_rejected")
    acts = _of_type(events, "act")
    print(f"### 🕳️  ACTIONS SANS EFFET — {len(rejets)} "
          f"(sur {len(acts) + len(rejets)} décidées)")
    par_motif: dict[str, int] = defaultdict(int)
    for ev in rejets:
        par_motif[f"{ev.get('act_name', '?')} — {ev.get('reason', '?')}"] += 1
    for cle, n in sorted(par_motif.items(), key=lambda x: -x[1])[:20]:
        print(f"  {cle:<60} {n}")
    print()

    # Chaîne pensée → action : ce que le journal ne permettait pas de relire.
    pensees = {ev.get("thought_id"): ev for ev in _of_type(events, "think")
               if ev.get("thought_id")}
    enfants: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        tid = ev.get("thought_id")
        if tid and ev.get("type") != "think":
            enfants[tid].append(ev)
    fertiles = [(tid, kids) for tid, kids in enfants.items() if len(kids) > 1]
    print(f"### 🔗 PENSÉES → ACTIONS — {len(pensees)} pensées identifiées, "
          f"{len(fertiles)} en ont produit plusieurs")
    for tid, kids in fertiles[-10:]:
        pensee = pensees.get(tid, {})
        emo = pensee.get("emotion") or {}
        dom = max(emo.items(), key=lambda x: x[1])[0] if emo else "?"
        print(f"  [{dom}] {_trunc(pensee.get('text') or '(pensée absente du jour)', 70)}")
        for kid in kids:
            detail = kid.get("detail") or kid.get("reason") or kid.get("message") or ""
            print(f"      └─ {kid.get('type')}: {_trunc(detail, 60)}")
    print()

    # Cycle de vie des goals : advance vs fulfill → repère ceux qui tournent en rond.
    goal_adv: dict[str, int] = defaultdict(int)
    goal_done: set[str] = set()
    for ev in _of_type(events, "act"):
        d = ev.get("detail") or ""
        m = re.search(r"#(\d+)", d)
        gid = m.group(1) if m else None
        if d.startswith("advance_goal") and gid:
            goal_adv[gid] += 1
        elif d.startswith("fulfill_goal") and gid:
            goal_done.add(gid)
    looping = sorted(
        ((g, n) for g, n in goal_adv.items() if g not in goal_done and n >= 3),
        key=lambda x: -x[1],
    )
    print(f"### 🎯 GOALS — {len(goal_adv)} avancés, {len(goal_done)} clôturés")
    if looping:
        print("  🔁 tournent sans clôture (≥3 advance, 0 fulfill) :")
        for g, n in looping[:15]:
            print(f"     #{g} — {n} advances, jamais fulfill")
    print()

    dms = _of_type(events, "dm")
    dm_supp = _of_type(events, "dm_suppressed")
    print(f"### ✉️  DM CRÉATEUR — {len(dms)} envoyés, {len(dm_supp)} supprimés")
    for ev in dms[:15]:
        print(f"  → {repr(_trunc(ev.get('message') or ''))}")
    for ev in dm_supp[:15]:
        print(f"  ⊘ supprimé ({ev.get('reason', '?')}) — {repr(_trunc(ev.get('message') or ''))}")
    print()


def _percentiles(values: list[int]) -> str:
    """« moy 1234ms médiane 900ms p95 4200ms », ou "" si rien à mesurer."""
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return ""
    p95 = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
    return (f"moy {int(sum(vals) / len(vals))}ms   "
            f"médiane {int(vals[len(vals) // 2])}ms   p95 {int(p95)}ms")


def _load_dir(root: Path, *parts: str, date: str | None = None) -> list[dict]:
    """Tous les events d'un sous-dossier du journal (``overlay/bulles``…)."""
    base = root.joinpath(*parts)
    files = sorted(base.glob("**/*.jsonl")) if base.exists() else []
    if date:
        files = [p for p in files if date in p.name]
    events: list[dict] = []
    for path in files:
        events.extend(_load(path))
    return events


def audit_overlay(root: Path, date: str | None, limit: int = 25) -> None:
    """Ce que l'overlay a dit — et surtout ce qu'il a refusé de dire.

    L'overlay est la surface la plus vue d'un live. Le taux de refus et le
    contenu des refus sont l'information : un filtre qui jette le mordant et
    garde le fade ne se voit qu'en lisant les deux colonnes côte à côte.
    """
    events = _load_dir(root, "overlay", "bulles", date=date)
    print(f"\n{'='*70}")
    print(f"AUDIT OVERLAY — {len(events)} events")
    print(f"{'='*70}\n")
    if not events:
        print("  (aucune bulle journalisée)\n")
        return

    bulles = _of_type(events, "overlay_bubble")
    refus = _of_type(events, "overlay_rejected")
    total = len(bulles) + len(refus)
    taux = f"{100 * len(refus) / total:.0f}%" if total else "—"
    print(f"### 💬 BULLES — {len(bulles)} publiées, {len(refus)} refusées ({taux} de refus)")

    par_source: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for ev in bulles:
        par_source[ev.get("source", "?")][0] += 1
    for ev in refus:
        par_source[ev.get("source", "?")][1] += 1
    for src, (pub, ref) in sorted(par_source.items(), key=lambda x: -sum(x[1])):
        print(f"  {src:<22} {pub:>4} publiées   {ref:>4} refusées")

    lat = _percentiles([e.get("condense_ms") for e in bulles if e.get("condense_ms")])
    if lat:
        print(f"  condensation : {lat}")

    budget: dict[str, int] = defaultdict(int)
    for ev in events:
        for raison, n in (ev.get("budget_ignores") or {}).items():
            budget[raison] += int(n or 0)
    if budget:
        print("  écartés par le budget, avant tout appel LLM :")
        for raison, n in sorted(budget.items(), key=lambda x: -x[1]):
            print(f"     {raison:<38} {n}")
    print()

    motifs: dict[str, int] = defaultdict(int)
    for ev in refus:
        motifs[str(ev.get("motif", "?"))] += 1
    print("### 🚫 MOTIFS DE REFUS")
    for motif, n in sorted(motifs.items(), key=lambda x: -x[1]):
        print(f"  {motif:<50} {n}")
    print()

    print(f"### ✍️  TEXTES ÉCARTÉS (les {limit} derniers)")
    for ev in refus[-limit:]:
        candidat = _trunc_line(ev.get("candidat") or "—", 70)
        print(f"  [{ev.get('source', '?')}] {ev.get('motif', '?')}")
        print(f"      entrée   : {_trunc_line(ev.get('entree') or '', 90)}")
        print(f"      candidat : {candidat}")
    print()

    print(f"### 📺 BULLES PUBLIÉES (les {limit} dernières)")
    for ev in bulles[-limit:]:
        emo = ev.get("emotion") or {}
        dom = max(emo.items(), key=lambda x: x[1])[0] if emo else "?"
        print(f"  [{ev.get('source', '?')}/{dom}] {_trunc_line(ev.get('texte') or '', 90)}")
    print()

    _report_reception(_of_type(events, "reception"), "l'overlay")


def audit_voice(root: Path, date: str | None, limit: int = 25) -> None:
    """Les demandes vocales : ce qui a été demandé, fait, répondu, et en combien
    de temps depuis la FIN DE LA PHRASE."""
    events = _load_dir(root, "voice", date=date)
    print(f"\n{'='*70}")
    print(f"AUDIT VOCAL — {len(events)} events")
    print(f"{'='*70}\n")
    if not events:
        print("  (aucune demande vocale journalisée)\n")
        return

    outs = _of_type(events, "message_out")
    ins = _of_type(events, "message_in")
    tools = _of_type(events, "tool_called")
    muets = [e for e in _of_type(events, "gate_decision")
             if e.get("decision") == "silence"]
    quasi = _of_type(events, "voice_near_miss")
    print(f"### 🎙️  DEMANDES — {len(ins)} entendues, {len(outs)} publiées, "
          f"{len(muets)} restées sans réponse")

    for etape, label in (("stt_ms", "transcription"), ("decide_ms", "décision"),
                         ("llm_ms", "génération"), ("publish_ms", "publication"),
                         ("total_ms", "TOTAL fin de phrase → chat")):
        mesure = _percentiles([e.get(etape) for e in outs if e.get(etape) is not None])
        if mesure:
            print(f"  {label:<28} {mesure}")
    print()

    if quasi:
        print(f"### 🎯 QUASI-DÉCLENCHEMENTS — {len(quasi)}")
        par_regle: dict[str, int] = defaultdict(int)
        for ev in quasi:
            par_regle[f"{ev.get('word', '?')} ≁ {ev.get('name', '?')} "
                      f"({ev.get('rule', '?')})"] += 1
        for cle, n in sorted(par_regle.items(), key=lambda x: -x[1])[:20]:
            print(f"  {cle:<50} {n}")
        print()

    if muets:
        print(f"### 🤐 DEMANDES SANS RÉPONSE — {len(muets)}")
        par_motif: dict[str, int] = defaultdict(int)
        for ev in muets:
            par_motif[str(ev.get("reason", "?"))] += 1
        for motif, n in sorted(par_motif.items(), key=lambda x: -x[1]):
            print(f"  {motif:<50} {n}")
        print()

    # Les traces sans `message_in` (quasi-déclenchements, silences) ont déjà
    # leur section : les remontrer ici en « incomplet » n'apprendrait rien.
    echanges = [t for t in _group_by_trace(events).values()
                if any(e.get("type") == "message_in" for e in t)]
    print(f"### 🔧 ÉCHANGES (les {limit} derniers sur {len(echanges)})")
    for trace in echanges[-limit:]:
        entree = next(e for e in trace if e.get("type") == "message_in")
        sortie = next((e for e in trace if e.get("type") == "message_out"), None)
        resultats = {e.get("tool"): e for e in trace if e.get("type") == "tool_result"}
        print(f"  [{entree.get('author', '?')}] "
              f"{_trunc_line(entree.get('content') or '', 90)}")
        for call in (e for e in trace if e.get("type") == "tool_called"):
            res = resultats.get(call.get("tool"), {})
            issue = res.get("error") or res.get("result") or "(sans résultat)"
            print(f"      🔧 {call.get('tool')} → {_trunc_line(str(issue), 70)}")
        if sortie is None:
            muet = next((e for e in trace if e.get("type") == "gate_decision"), {})
            print(f"      ⊘ rien publié — {muet.get('reason', 'sans motif')}")
            continue
        print(f"      → {_trunc_line(sortie.get('content') or '', 90)} "
              f"[{sortie.get('total_ms', '?')}ms]")
    print()

    print(f"### 🔧 OUTILS APPELÉS — {len(tools)}")
    par_outil: dict[str, int] = defaultdict(int)
    for ev in tools:
        par_outil[str(ev.get("tool", "?"))] += 1
    for outil, n in sorted(par_outil.items(), key=lambda x: -x[1]):
        print(f"  {outil:<30} {n}")
    print()


def _trunc_line(value, n: int = 80) -> str:
    return " ".join(str(value or "").split())[:n]


def _report_reception(receptions: list[dict], quoi: str) -> None:
    """Le seul retour spectateur mesurable : ce qui a bougé dans la minute."""
    if not receptions:
        return
    muets = [r for r in receptions if not r.get("replies")]
    delais = [r["first_delay_s"] for r in receptions
              if isinstance(r.get("first_delay_s"), (int, float))]
    total = sum(int(r.get("replies") or 0) for r in receptions)
    print(f"### 👀 RÉCEPTION ({quoi}) — {len(receptions)} prises de parole")
    print(f"  {len(muets)} sans le moindre message dans la minute "
          f"({100 * len(muets) / len(receptions):.0f}%)")
    print(f"  {total} messages au total, "
          f"{total / len(receptions):.1f} en moyenne par prise de parole")
    if delais:
        delais.sort()
        print(f"  premier message : médiane {delais[len(delais)//2]:.1f}s")
    print()


def audit_silences(root: Path, date: str | None) -> None:
    """Pourquoi Wally s'est tu — la moitié invisible de son comportement."""
    events: list[dict] = []
    for plat in ("discord", "twitch", "voice"):
        events.extend(_load_dir(root, plat, date=date))
    gates = _of_type(events, "gate_decision")
    print(f"\n{'='*70}")
    print(f"AUDIT DES SILENCES — {len(gates)} décisions de réponse")
    print(f"{'='*70}\n")
    if not gates:
        print("  (aucune décision journalisée)\n")
        return
    par_decision: dict[str, int] = defaultdict(int)
    for ev in gates:
        par_decision[str(ev.get("decision", "?"))] += 1
    print("### ⚖️  DÉCISIONS")
    for dec, n in sorted(par_decision.items(), key=lambda x: -x[1]):
        print(f"  {dec:<20} {n}")
    print()
    muets = [e for e in gates
             if str(e.get("decision")) not in ("respond", "spontaneous")]
    par_motif: dict[str, int] = defaultdict(int)
    for ev in muets:
        par_motif[str(ev.get("reason") or "(motif absent)")] += 1
    print(f"### 🤐 MOTIFS DE SILENCE — {len(muets)}")
    for motif, n in sorted(par_motif.items(), key=lambda x: -x[1])[:25]:
        print(f"  {motif:<50} {n}")
    print()


def dump_trace(root: Path, trace_id: str) -> None:
    """Affiche tous les events d'un trace_id donné, dans l'ordre chronologique."""
    found = []
    for path in root.glob("**/*.jsonl"):
        for ev in _load(path):
            if ev.get("trace_id") == trace_id:
                found.append(ev)
    if not found:
        print(f"Aucun event pour trace_id={trace_id}")
        return
    found.sort(key=lambda e: e.get("ts", 0))
    print(f"\n=== TRACE {trace_id} — {len(found)} events ===\n")
    for ev in found:
        ts = ev.pop("ts", 0)
        etype = ev.pop("type", "?")
        ev.pop("trace_id", None)
        print(f"[{ts:.2f}] {etype}")
        for k, v in ev.items():
            s = json.dumps(v, ensure_ascii=False)
            print(f"      {k}: {s[:300]}")
        print()


def _hhmmss(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, _TZ) if _TZ else datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S")


def _timeline_summary(ev: dict) -> str:
    """Résumé court d'un event pour la vue chronologique."""
    t = ev.get("type", "?")
    if t in ("message_in", "message_out"):
        who = ev.get("author", "?")
        content = " ".join((ev.get("content") or "").split())
        kind = f"({ev['kind']})" if ev.get("kind") else ""
        arrow = "← IN " if t == "message_in" else "→ OUT"
        rep = " [reply]" if str(ev.get("is_reply")) == "True" else ""
        return f"{arrow}{kind}{rep} {who}: {content[:120]}"
    if t in ("think", "attn", "decide", "act"):
        body = " ".join(
            (ev.get("text") or ev.get("detail") or ev.get("content_snippet") or "").split()
        )
        tgt = ev.get("target")
        tg = f"[{tgt}] " if tgt and tgt != "—" else ""
        return f"{t.upper():7}{tg}{body[:120]}"
    if t == "gate_decision":
        motif = f" — {ev['reason']}" if ev.get("reason") else ""
        return f"gate → {ev.get('decision')} (spontaneous={ev.get('spontaneous')}){motif}"
    if t == "speak_suppressed":
        return f"SPEAK supprimé — {ev.get('reason')}"
    if t == "overlay_bubble":
        return f"💬 [{ev.get('source')}] {_trunc_line(ev.get('texte'), 110)}"
    if t == "overlay_rejected":
        return (f"🚫 [{ev.get('source')}] {ev.get('motif')} — "
                f"{_trunc_line(ev.get('candidat') or ev.get('entree'), 80)}")
    if t == "voice_near_miss":
        return (f"🎯 quasi « {ev.get('word')} » ≁ « {ev.get('name')} » "
                f"({ev.get('rule')})")
    if t == "reception":
        return (f"👀 réception — {ev.get('replies')} message(s) dans la minute "
                f"({', '.join(ev.get('authors') or []) or 'personne'})")
    if t == "act_rejected":
        return f"🕳️  ACT {ev.get('act_name')} sans effet — {ev.get('reason')}"
    extra = {k: v for k, v in ev.items() if k not in ("ts", "type", "trace_id")}
    return f"{t}: {json.dumps(extra, ensure_ascii=False)[:120]}"


# Events de cognition PURE (sans effet visible) — condensés en « réflexion » en
# mode --compact. Tout le reste (messages, gate, act concret, DM, émotions…) reste
# affiché : on veut voir QUE quelque chose s'est passé, sans le pavé de monologue.
_INTERNAL_TYPES = {"think", "attn", "decide", "think_skipped"}


def timeline(root: Path, date: str | None, channel: str | None,
             compact: bool = False) -> None:
    """Vue chronologique UNIFIÉE : entrelace tous les canaux + le flux cognitif
    (brain) triés par horodatage absolu. Indispensable pour suivre une séquence
    qui traverse réactif et cognitif (ex: un message spontané du cerveau qui
    répond à une question déjà traitée en réactif).

    `compact` : regroupe les rafales de cognition pure (think/attn/decide)
    consécutives en une seule ligne « 💭 réflexion ×N » — la chronologie reste
    lisible tout en montrant qu'il y a eu de l'activité."""
    if not date:
        now = datetime.now(_TZ) if _TZ else datetime.now()
        date = now.strftime("%Y-%m-%d")

    rows: list[tuple[float, str, dict]] = []
    for path in root.glob("**/*.jsonl"):
        if date not in path.name:
            continue
        source = "/".join(path.relative_to(root).parts[:-1])
        is_brain = "brain" in source
        # Avec --channel : ce canal + le cerveau (pour voir les deux entrelacés).
        if channel and channel.lower() not in source.lower() and not is_brain:
            continue
        for ev in _load(path):
            rows.append((ev.get("ts", 0.0), source, ev))

    rows.sort(key=lambda r: r[0])
    scope = channel if channel else "tous canaux"
    print(f"\n=== TIMELINE {date} — {len(rows)} events ({scope} + 🧠 brain) ===\n")

    # État de regroupement des réflexions (mode compact).
    run_count = 0
    run_start = ""

    def _flush_run() -> None:
        nonlocal run_count, run_start
        if run_count:
            suffix = f" ({run_start})" if run_count == 1 else f" ×{run_count} (depuis {run_start})"
            print(f"[{run_start}] {'🧠 brain':30.30} 💭 réflexion{suffix}")
            run_count = 0

    for ts, source, ev in rows:
        if compact and ev.get("type") in _INTERNAL_TYPES:
            if run_count == 0:
                run_start = _hhmmss(ts)
            run_count += 1
            continue
        _flush_run()
        label = "🧠 brain" if "brain" in source else source
        print(f"[{_hhmmss(ts)}] {label:30.30} {_timeline_summary(ev)}")
    _flush_run()


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit des logs de conversation Wally")
    ap.add_argument("--root", default="logs/conversations", help="dossier racine des logs")
    ap.add_argument("--platform", help="discord | twitch")
    ap.add_argument("--channel", help="filtre sous-chaîne sur le nom de canal")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--trace", help="dump complet d'un trace_id précis")
    ap.add_argument("--slow-ms", type=int, default=8000, help="seuil de latence anormale (ms)")
    ap.add_argument("--cognitive-only", action="store_true", help="n'analyse QUE le flux cognitif")
    ap.add_argument("--overlay", action="store_true",
                    help="n'analyse QUE les bulles d'overlay (publiées ET refusées)")
    ap.add_argument("--voice", action="store_true",
                    help="n'analyse QUE les demandes vocales (outils, latences)")
    ap.add_argument("--silences", action="store_true",
                    help="n'analyse QUE les décisions de NE PAS répondre, par motif")
    ap.add_argument("--timeline", action="store_true",
                    help="vue chronologique unifiée (tous canaux + brain entrelacés par ts)")
    ap.add_argument("--compact", action="store_true",
                    help="(avec --timeline) condense les rafales de réflexion interne en « 💭 réflexion ×N »")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"Dossier introuvable : {root}")
        return
    if args.timeline:
        timeline(root, args.date, args.channel, compact=args.compact)
    elif args.trace:
        dump_trace(root, args.trace)
    elif args.cognitive_only:
        audit_cognitive(root, args.date)
    elif args.overlay:
        audit_overlay(root, args.date)
    elif args.voice:
        audit_voice(root, args.date)
    elif args.silences:
        audit_silences(root, args.date)
    else:
        # Tout, par défaut : un journal que personne ne pense à ouvrir ne sert à
        # rien, et personne ne retient une liste de drapeaux.
        audit(root, args.platform, args.channel, args.date, args.slow_ms)
        audit_cognitive(root, args.date)
        audit_overlay(root, args.date)
        audit_voice(root, args.date)
        audit_silences(root, args.date)


if __name__ == "__main__":
    main()
