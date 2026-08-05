"""Cadence freinée par le ressassement.

Mesuré en prod : ~57 % des pensées étaient jetées, chacune APRÈS deux appels LLM
(le raisonnement puis le juge de progression). La cadence n'écoutait que l'ennui,
qui pousse en sens inverse — une journée creuse accélérait le rythme alors qu'elle
offre le moins de matière.
"""
import time

from bot.intelligence.cognitive_loop import (
    TICK_ACTIVE,
    TICK_IDLE,
    TICK_MODERATE,
    CognitiveLoop,
)


def _loop() -> CognitiveLoop:
    return CognitiveLoop(None, None, None)


def _fill(loop: CognitiveLoop, skipped: int, kept: int) -> None:
    for _ in range(skipped):
        loop._rumination_window.append(True)
    for _ in range(kept):
        loop._rumination_window.append(False)


# ── taux ──

def test_rate_zero_sur_fenetre_vide():
    assert _loop()._rumination_rate() == 0.0


def test_rate_reflete_la_proportion_jetee():
    loop = _loop()
    _fill(loop, skipped=3, kept=1)
    assert loop._rumination_rate() == 0.75


# ── facteur de ralentissement ──

def test_pas_de_frein_quand_les_pensees_vivent():
    loop = _loop()
    _fill(loop, skipped=0, kept=6)
    assert loop._rumination_slowdown() == 1.0


def test_frein_maximal_quand_tout_ressasse():
    loop = _loop()
    _fill(loop, skipped=8, kept=0)
    assert loop._rumination_slowdown() == 4.0


def test_frein_negligeable_sur_un_ressassement_faible():
    """Quelques pensées jetées sont normales : ça ne doit pas endormir la boucle."""
    loop = _loop()
    _fill(loop, skipped=1, kept=7)
    assert loop._rumination_slowdown() < 1.1


# ── effet sur le tick ──

def test_reactivite_intacte_quand_on_s_adresse_a_lui():
    """Le frein ne doit JAMAIS coûter en réactivité : quelqu'un lui parle."""
    loop = _loop()
    loop._last_relevant_activity_ts = time.monotonic()
    _fill(loop, skipped=12, kept=0)
    assert loop._tick_interval() == TICK_ACTIVE


def test_tick_modere_allonge_par_le_ressassement():
    calme, ressasse = _loop(), _loop()
    for loop in (calme, ressasse):
        loop._last_relevant_activity_ts = time.monotonic() - 1200  # 20 min → modéré
    _fill(calme, skipped=0, kept=8)
    _fill(ressasse, skipped=8, kept=0)
    assert calme._tick_interval() == TICK_MODERATE
    assert ressasse._tick_interval() > TICK_MODERATE * 3


def test_plancher_idle_recule_aussi():
    """Quand rien de neuf ne sort, même 5 min est trop court."""
    loop = _loop()
    loop._last_relevant_activity_ts = 0.0
    _fill(loop, skipped=12, kept=0)
    assert min(loop._tick_interval() for _ in range(30)) > TICK_IDLE
