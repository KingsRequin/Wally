"""Le journal quotidien travaille en Europe/Paris, pas à l'heure de la machine.

Ce serveur tourne en UTC. Sans fuseau explicite, APScheduler prend celui du
process : `journal_time: '21:00'` déclenchait le journal à 21 h UTC, soit 23 h
en France — deux heures après l'heure voulue, une en hiver.

Et `date.today()` suit la même horloge machine, alors que
`get_twitch_visits_for_date` découpe ses journées en Europe/Paris : entre 22 h
UTC et minuit, le journal aurait demandé les visites de la veille.
"""
from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import bot.intelligence.journal as journal_mod
from bot.intelligence.journal import DailyJournal

# Deux fuseaux séparés de 25 h : leurs dates civiles diffèrent à TOUT instant.
# C'est ce qui rend le test déterministe, là où comparer à UTC ne le serait
# que quelques heures par jour.
_EST = ZoneInfo("Pacific/Kiritimati")   # UTC+14
_OUEST = ZoneInfo("Pacific/Niue")       # UTC−11


def _journal(journal_time="21:00"):
    config = MagicMock()
    config.bot.journal_time = journal_time
    return DailyJournal(config, MagicMock(), MagicMock(), MagicMock(), MagicMock())


# ── la date du jour ───────────────────────────────────────────────────────


def test_la_date_du_jour_suit_le_fuseau_configure(monkeypatch):
    """`date.today()` rendrait la même valeur dans les deux cas."""
    monkeypatch.setattr(journal_mod, "_TZ_JOURNAL", _EST)
    est = DailyJournal._today_date()
    monkeypatch.setattr(journal_mod, "_TZ_JOURNAL", _OUEST)
    ouest = DailyJournal._today_date()
    assert est != ouest, "la date du journal ne dépend pas du fuseau configuré"


def test_la_date_du_jour_est_bien_celle_de_paris():
    attendu = datetime.now(ZoneInfo("Europe/Paris")).date()
    assert DailyJournal._today_date() == attendu


def test_la_date_affichee_suit_le_meme_fuseau(monkeypatch):
    """Le journal daté du 7 alors qu'on est le 8 à Paris n'aurait aucun sens."""
    monkeypatch.setattr(journal_mod, "_TZ_JOURNAL", _EST)
    assert DailyJournal._today() == datetime.now(_EST).strftime("%d/%m/%Y")


def test_la_date_du_jour_reste_une_date():
    """`effective_date` est ensuite formatée et passée à la base."""
    assert isinstance(DailyJournal._today_date(), date)


# ── l'heure de déclenchement ──────────────────────────────────────────────


def test_les_jobs_du_journal_sont_planifies_en_heure_de_paris():
    """Sans fuseau, APScheduler prend celui du process — UTC ici, d'où un
    journal parti à 23 h française au lieu de 21 h."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    _journal("21:00").start(scheduler=scheduler)
    job = scheduler.get_job("daily_journal")
    assert job is not None
    assert str(job.trigger.timezone) == "Europe/Paris"
    assert job.trigger.fields[job.trigger.FIELD_NAMES.index("hour")].expressions[0].first == 21


def test_tous_les_travaux_du_soir_partagent_ce_fuseau():
    """Nettoyage mémoire, consolidation et modélisation sont accrochés au même
    horaire : un seul décalé suffirait à les désynchroniser."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    j = _journal("21:00")
    j._consolidator = MagicMock()
    j._user_modeler = MagicMock()
    j.start(scheduler=scheduler)
    attendus = ("daily_journal", "memory_cleanup",
                "memory_consolidation", "user_model_refresh")
    for job_id in attendus:
        job = scheduler.get_job(job_id)
        assert job is not None, f"{job_id} n'est pas planifié"
        assert str(job.trigger.timezone) == "Europe/Paris", job_id


def test_le_scheduler_partage_porte_aussi_le_fuseau():
    """C'est CELUI-LÀ qui tourne en production : `journal.start()` reçoit le
    scheduler de `bootstrap`, pas celui qu'il crée pour lui-même. Corriger
    seulement le second n'aurait rien changé au live."""
    from bot.bootstrap import make_scheduler

    assert str(make_scheduler().timezone) == "Europe/Paris"


@pytest.mark.parametrize("journal_time,heure", [("21:00", 21), (1260, 21), ("07:30", 7)])
def test_l_heure_configuree_est_respectee(journal_time, heure):
    """`21:00` sans guillemets est lu par YAML comme un entier sexagésimal."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    _journal(journal_time).start(scheduler=scheduler)
    job = scheduler.get_job("daily_journal")
    idx = job.trigger.FIELD_NAMES.index("hour")
    assert job.trigger.fields[idx].expressions[0].first == heure
