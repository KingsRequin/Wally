from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.social_rhythm import SocialRhythm

PARIS = ZoneInfo("Europe/Paris")


@pytest.mark.asyncio
async def test_persist_then_load_roundtrip(tmp_path):
    db_path = str(tmp_path / "t.db")
    await create_v2_tables(db_path)
    sr = SocialRhythm(alpha=0.5, n_conf=2)
    for day in range(1, 5):
        for _ in range(10):
            sr.record_incoming(datetime(2026, 6, day, 14, tzinfo=PARIS))
        sr.record_spontaneous_outcome(True, datetime(2026, 6, day, 14, tzinfo=PARIS))
    # force un rollover final pour replier le dernier jour
    sr.record_incoming(datetime(2026, 6, 6, 14, tzinfo=PARIS))
    await sr.persist(db_path)

    sr2 = SocialRhythm(alpha=0.5, n_conf=2)
    await sr2.load(db_path)
    probe = datetime(2026, 6, 8, 14, tzinfo=PARIS)
    assert sr2.receptivity(probe) == pytest.approx(sr.receptivity(probe), abs=1e-9)
