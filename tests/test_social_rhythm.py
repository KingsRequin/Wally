from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from bot.intelligence.social_rhythm import SocialRhythm, PRIOR

PARIS = ZoneInfo("Europe/Paris")


def _dt(day, hour):
    # 2026-06-01 = lundi (semaine)
    return datetime(2026, 6, day, hour, 0, tzinfo=PARIS)


def test_cold_start_is_neutral():
    sr = SocialRhythm()
    assert sr.receptivity(_dt(1, 3)) == pytest.approx(PRIOR, abs=1e-9)


def test_learns_night_dip():
    sr = SocialRhythm(alpha=0.5, n_conf=3)
    # 6 jours : beaucoup de messages à 14h, zéro la nuit (3h).
    for day in range(1, 7):
        for _ in range(20):
            sr.record_incoming(_dt(day, 14))
        # parole spontanée nocturne toujours ignorée, diurne toujours répondue
        sr.record_spontaneous_outcome(False, _dt(day, 3))
        sr.record_spontaneous_outcome(True, _dt(day, 14))
    night = sr.receptivity(_dt(8, 3))   # 2026-06-08 = lundi
    day = sr.receptivity(_dt(8, 14))
    assert day > 0.6
    assert night < 0.2
    assert night < day


def test_weekend_distinct_from_weekday():
    sr = SocialRhythm(alpha=0.5, n_conf=2)
    # weekday 20h vide, weekend 20h chargé → réceptivités différentes au même créneau horaire
    for day in (6, 7, 13, 14):      # samedis/dimanches de juin 2026
        for _ in range(20):
            sr.record_incoming(_dt(day, 20))
    wknd = sr.receptivity(_dt(20, 20))   # samedi
    week = sr.receptivity(_dt(22, 20))   # lundi
    assert wknd > week


def test_engagement_pushes_receptivity_over_time():
    sr = SocialRhythm(alpha=0.5, n_conf=2)
    for day in range(1, 5):
        sr.record_incoming(_dt(day, 10))
        sr.record_spontaneous_outcome(True, _dt(day, 10))
    high = sr.receptivity(_dt(8, 10))
    for day in range(1, 5):
        sr.record_incoming(_dt(day, 10))
        sr.record_spontaneous_outcome(False, _dt(day, 10))
    low = sr.receptivity(_dt(8, 10))
    assert low < high
