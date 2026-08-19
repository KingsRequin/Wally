"""Tests for fluid directive transitions and secondary emotion injection.

Les valeurs sont dérivées de `SEUIL_HAUT` plutôt qu'écrites en dur : ces tests
vérifient le MÉCANISME de transition (zone mixte de ±0.05 autour d'une
frontière), pas l'emplacement de la frontière. Écrits en dur (0.55 « mid »,
0.68 « mid_high »), ils rougissaient dès qu'on déplaçait le palier haut — un
recalibrage mesuré ressemblait alors à une régression.
"""
import pytest
from bot.intelligence.prompts import SEUIL_HAUT, _get_tier_fluid, PromptBuilder


def test_tier_below_threshold_returns_none():
    assert _get_tier_fluid(0.15) is None


def test_tier_low_pure():
    result = _get_tier_fluid(0.3)
    assert result == ("low", 1.0)


def test_tier_mid_pure():
    result = _get_tier_fluid(SEUIL_HAUT - 0.1)
    assert result == ("mid", 1.0)


def test_tier_high_pure():
    result = _get_tier_fluid(0.85)
    assert result == ("high", 1.0)


def test_tier_transition_low_to_mid():
    result = _get_tier_fluid(0.38)
    assert result is not None
    tier, blend = result
    assert tier == "low_mid"
    assert 0.0 < blend < 1.0


def test_tier_transition_mid_to_high():
    result = _get_tier_fluid(SEUIL_HAUT - 0.02)
    assert result is not None
    tier, blend = result
    assert tier == "mid_high"
    assert 0.0 < blend < 1.0


def test_prompt_builder_uses_secondary_over_atomic():
    builder = PromptBuilder()
    emotion_state = {"anger": 0.5, "boredom": 0.5, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0}
    directives = {"anger_mid": "colere mid", "boredom_mid": "ennui mid"}
    secondary_directives = {
        "frustration_mid": "FRUSTRATION directive",
        "frustration_low": "frustration low",
    }
    secondaries = [("frustration", 0.5)]
    result = builder.build_system_prompt(
        emotion_state,
        emotion_directives=directives,
        secondary_directives=secondary_directives,
        active_secondaries=secondaries,
    )
    assert "FRUSTRATION directive" in result
    assert "colere mid" not in result


def test_prompt_builder_fallback_to_atomic_without_secondaries():
    builder = PromptBuilder()
    emotion_state = {"anger": 0.5, "boredom": 0.1, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0}
    directives = {"anger_mid": "colere mid directive"}
    result = builder.build_system_prompt(
        emotion_state,
        emotion_directives=directives,
        active_secondaries=[],
    )
    assert "colere mid directive" in result
