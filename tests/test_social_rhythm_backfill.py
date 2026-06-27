import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from bot.intelligence.social_rhythm import SocialRhythm

PARIS = ZoneInfo("Europe/Paris")


def _write_log(root, channel, day, hours):
    d = root / "discord" / channel
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{day}.jsonl"
    with f.open("w") as fh:
        for h in hours:
            ts = datetime(2026, 6, int(day[-2:]), h, tzinfo=PARIS).timestamp()
            fh.write(json.dumps({"ts": ts, "type": "message_in", "content": "x"}) + "\n")


def test_backfill_warms_ambient(tmp_path):
    logs = tmp_path / "logs" / "conversations"
    # 14h très actif sur plusieurs jours, 3h jamais
    for day in ("2026-06-01", "2026-06-02", "2026-06-03"):
        _write_log(logs, "123", day, [14] * 10)
    sr = SocialRhythm(alpha=0.5, n_conf=2)
    n = sr.backfill_from_logs(str(logs))
    assert n == 30
    assert sr.receptivity(datetime(2026, 6, 8, 14, tzinfo=PARIS)) > \
           sr.receptivity(datetime(2026, 6, 8, 3, tzinfo=PARIS))


def test_backfill_missing_dir_is_safe(tmp_path):
    sr = SocialRhythm()
    assert sr.backfill_from_logs(str(tmp_path / "nope")) == 0
