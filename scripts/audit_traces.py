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

Usage :
    python3 scripts/audit_traces.py                          # tout, aujourd'hui inclus
    python3 scripts/audit_traces.py --platform discord
    python3 scripts/audit_traces.py --channel général --date 2026-06-23
    python3 scripts/audit_traces.py --trace 134256...        # dump complet d'un trace
    python3 scripts/audit_traces.py --slow-ms 8000           # seuil latence
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
        return f"gate → {ev.get('decision')} (spontaneous={ev.get('spontaneous')})"
    if t == "speak_suppressed":
        return f"SPEAK supprimé — {ev.get('reason')}"
    extra = {k: v for k, v in ev.items() if k not in ("ts", "type", "trace_id")}
    return f"{t}: {json.dumps(extra, ensure_ascii=False)[:120]}"


def timeline(root: Path, date: str | None, channel: str | None) -> None:
    """Vue chronologique UNIFIÉE : entrelace tous les canaux + le flux cognitif
    (brain) triés par horodatage absolu. Indispensable pour suivre une séquence
    qui traverse réactif et cognitif (ex: un message spontané du cerveau qui
    répond à une question déjà traitée en réactif)."""
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
    for ts, source, ev in rows:
        label = "🧠 brain" if "brain" in source else source
        print(f"[{_hhmmss(ts)}] {label:30.30} {_timeline_summary(ev)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit des logs de conversation Wally")
    ap.add_argument("--root", default="logs/conversations", help="dossier racine des logs")
    ap.add_argument("--platform", help="discord | twitch")
    ap.add_argument("--channel", help="filtre sous-chaîne sur le nom de canal")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--trace", help="dump complet d'un trace_id précis")
    ap.add_argument("--slow-ms", type=int, default=8000, help="seuil de latence anormale (ms)")
    ap.add_argument("--cognitive-only", action="store_true", help="n'analyse QUE le flux cognitif")
    ap.add_argument("--timeline", action="store_true",
                    help="vue chronologique unifiée (tous canaux + brain entrelacés par ts)")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"Dossier introuvable : {root}")
        return
    if args.timeline:
        timeline(root, args.date, args.channel)
    elif args.trace:
        dump_trace(root, args.trace)
    elif args.cognitive_only:
        audit_cognitive(root, args.date)
    else:
        audit(root, args.platform, args.channel, args.date, args.slow_ms)
        audit_cognitive(root, args.date)


if __name__ == "__main__":
    main()
