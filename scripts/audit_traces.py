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
from pathlib import Path

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


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit des logs de conversation Wally")
    ap.add_argument("--root", default="logs/conversations", help="dossier racine des logs")
    ap.add_argument("--platform", help="discord | twitch")
    ap.add_argument("--channel", help="filtre sous-chaîne sur le nom de canal")
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--trace", help="dump complet d'un trace_id précis")
    ap.add_argument("--slow-ms", type=int, default=8000, help="seuil de latence anormale (ms)")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"Dossier introuvable : {root}")
        return
    if args.trace:
        dump_trace(root, args.trace)
    else:
        audit(root, args.platform, args.channel, args.date, args.slow_ms)


if __name__ == "__main__":
    main()
