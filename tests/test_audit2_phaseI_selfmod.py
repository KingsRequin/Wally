# tests/test_audit2_phaseI_selfmod.py
"""Phase I du second audit : auto-modification et rythme social.

A2-backfill — `backfill_from_logs` rejoué à CHAQUE boot par-dessus l'état
              persisté : `days = 4225` pour 49 jours de logs réels.
A2-conf     — `receptivity()` certifiait un signal d'engagement jamais observé.
A2-roll     — un seul pas d'EMA quel que soit le nombre de jours écoulés.
A2-tz       — garde-fou d'évolution persona aveugle de 00 h à 02 h (Paris/UTC).
A2-guard    — SpeakGuard fail-open sur le format que son prompt réclame.
A2-act      — JSON d'un `[ACT]` malformé avalé sans log.
A2-cap      — `find_similar` perdait `capability` et départageait au hasard.
"""
import inspect
from datetime import datetime, timezone

import pytest
from unittest.mock import MagicMock

from bot.intelligence.social_rhythm import SocialRhythm


# ────────────────────────────── A2-backfill ──────────────────────────────
def test_le_prechauffage_ne_rejoue_pas_par_dessus_l_etat_charge(tmp_path):
    sr = SocialRhythm.__new__(SocialRhythm)
    sr._bins = {"wk:12": {"avg": 3.0, "count": 0.0, "days": 40, "eng": 0.5, "eng_obs": 0}}
    assert sr.backfill_from_logs(str(tmp_path)) == 0


def test_le_prechauffage_agit_sur_un_etat_vierge(tmp_path):
    sr = SocialRhythm.__new__(SocialRhythm)
    sr._bins = {}
    # Pas de dossier `discord/` → 0, mais la garde des bins n'a pas court-circuité.
    src = inspect.getsource(SocialRhythm.backfill_from_logs)
    assert "if self._bins:" in src
    assert sr.backfill_from_logs(str(tmp_path)) == 0


# ────────────────────────────── A2-conf ──────────────────────────────
def _rythme(days=100, eng_obs=0, eng=0.5, avg=1.0):
    sr = SocialRhythm.__new__(SocialRhythm)
    sr._tz = timezone.utc
    sr._n_conf = 10
    sr._bins = {}
    for h in range(24):
        sr._bins[f"wk:{h:02d}"] = {
            "avg": avg, "count": 0.0, "days": days, "eng": eng, "eng_obs": eng_obs,
        }
    return sr


def test_un_engagement_jamais_observe_nest_pas_certifie():
    """`days` élevé + `eng_obs` nul : l'engagement doit rester au prior."""
    from bot.intelligence.social_rhythm import PRIOR

    quand = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    # eng = 1.0 mais jamais observé → ne doit pas tirer la réceptivité vers 1.0
    sr = _rythme(days=1000, eng_obs=0, eng=1.0)
    r = sr.receptivity(quand)
    sr_ref = _rythme(days=1000, eng_obs=0, eng=PRIOR)
    assert r == pytest.approx(sr_ref.receptivity(quand), abs=1e-9)


def test_un_engagement_reellement_observe_compte():
    quand = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    faible = _rythme(days=1000, eng_obs=0, eng=1.0).receptivity(quand)
    fort = _rythme(days=1000, eng_obs=1000, eng=1.0).receptivity(quand)
    assert fort > faible


# ────────────────────────────── A2-roll ──────────────────────────────
def test_une_absence_de_plusieurs_jours_replie_autant_de_fois():
    src = inspect.getsource(SocialRhythm.record_incoming)
    assert "_date.fromisoformat(day)" in src
    assert "for _ in range(max(1, min(manques, 30))):" in src


# ────────────────────────────── A2-tz ──────────────────────────────
def test_le_garde_fou_d_evolution_compte_dans_le_meme_fuseau_que_l_ecriture():
    from bot.intelligence import evolution_log, persona_manager

    lecture = inspect.getsource(evolution_log.EvolutionLog.entries_today)
    assert "today = datetime.now(timezone.utc).date().isoformat()" in lecture
    # La ligne de CODE, pas le commentaire qui la documente.
    assert "today = date.today().isoformat()" not in lecture
    # L'écriture, elle, était déjà en UTC — c'est la lecture qui divergeait.
    assert "datetime.now(timezone.utc)" in inspect.getsource(persona_manager)


# ────────────────────────────── A2-guard ──────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", [
    "TAIS-TOI — inutile",
    "`TAIS-TOI — inutile`",          # le format montré par son propre prompt
    "**TAIS-TOI** — inutile",
    "  tais-toi — inutile",
])
async def test_le_garde_bloque_quelle_que_soit_la_mise_en_forme(verdict):
    from bot.intelligence.speak_guard import SpeakGuard

    g = SpeakGuard.__new__(SpeakGuard)
    g._llm = MagicMock()
    g._llm.complete = MagicMock(return_value=verdict)

    async def _complete(*a, **k):
        return verdict

    g._llm.complete = _complete
    g._system = "sys"
    g.enabled = True

    passe, _ = await g.worth_sending("un message", "contexte")
    assert passe is False, f"verdict de blocage retourné en autorisation : {verdict!r}"


@pytest.mark.asyncio
async def test_un_feu_vert_passe_toujours():
    from bot.intelligence.speak_guard import SpeakGuard

    g = SpeakGuard.__new__(SpeakGuard)
    g._system = "sys"
    g.enabled = True
    g._llm = MagicMock()

    async def _complete(*a, **k):
        return "ENVOIE — ça apporte quelque chose"

    g._llm.complete = _complete
    passe, _ = await g.worth_sending("un message", "contexte")
    assert passe is True


# ────────────────────────────── A2-act ──────────────────────────────
def test_un_act_illisible_est_ignore_et_journalise():
    from bot.intelligence.meta_agent import parse_decisions

    decisions = parse_decisions('[ACT create_memory {cassé}]')
    assert not any(d.action == "ACT" for d in decisions), "action dispatchée sans arguments"


def test_un_act_valide_passe_toujours():
    from bot.intelligence.meta_agent import parse_decisions

    decisions = parse_decisions('[ACT create_memory {"content": "un fait"}]')
    actes = [d for d in decisions if d.action == "ACT"]
    assert len(actes) == 1
    assert actes[0].act_args == {"content": "un fait"}


# ────────────────────────────── A2-cap ──────────────────────────────
def test_la_recherche_de_doublon_rend_la_capacite_et_departage_stablement():
    from bot.intelligence import upgrade_registry

    src = inspect.getsource(upgrade_registry.UpgradeRegistry.find_similar)
    assert "decided_at, capability" in src
    assert "ORDER BY id DESC" in src
    assert "capability=r[\"capability\"]" in src
    assert "if score >= best_score:" not in src
