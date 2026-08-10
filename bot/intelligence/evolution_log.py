from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class EvolutionEntry:
    timestamp: str   # ISO UTC
    section: str     # "SOUL" | "EMOTIONS" | "WEEKDAYS" | "COMPOSITES"
    before_len: int
    after_len: int
    reason: str


class EvolutionLog:
    def __init__(self, log_path: str | Path = "data/evolution_log.jsonl") -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: EvolutionEntry) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def entries_today(self, section: str) -> list[EvolutionEntry]:
        # MÊME base que l'écriture : `persona_manager` estampille en UTC
        # (`datetime.now(timezone.utc)`), alors que `date.today()` rend la date
        # LOCALE — Europe/Paris dans le conteneur. Une évolution écrite à 00 h 30
        # Paris porte « …T22:30Z » la veille : elle n'était comptée ni ce
        # jour-là ni le lendemain, et les deux garde-fous (`max_change_percent`,
        # `max_evolutions_per_day`) étaient aveugles de 00 h à 02 h — précisément
        # la plage creuse où la boucle cognitive vagabonde.
        today = datetime.now(timezone.utc).date().isoformat()
        if not self._path.exists():
            return []
        entries: list[EvolutionEntry] = []
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("section") == section and data.get("timestamp", "").startswith(today):
                        entries.append(EvolutionEntry(**data))
                except (json.JSONDecodeError, TypeError, KeyError):
                    continue
        return entries

    def count_today(self, section: str) -> int:
        return len(self.entries_today(section))

    def change_percent_today(self, section: str) -> float:
        """Cumul |after_len - before_len| / before_len pour aujourd'hui."""
        total = 0.0
        for e in self.entries_today(section):
            if e.before_len > 0:
                total += abs(e.after_len - e.before_len) / e.before_len
        return total
