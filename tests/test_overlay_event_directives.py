"""Chaque événement du live a son propre cadrage.

Phase 2 de docs/plans/2026-08-08-overlay-evenements-types.md. La phase 1 a fait
voyager le type ; ici il sert enfin à rédiger.

Avant : un prompt unique énumérait « un raid, un abonnement, des bits, un
changement de jeu », ce qui sommait le modèle de choisir une catégorie même
quand aucune ne s'appliquait — et ses trois exemples littéraux ressortaient mot
pour mot, 30 fois par jour.
"""
from unittest.mock import MagicMock

import pytest

from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrator(directives=None):
    n = OverlayNarrator.__new__(OverlayNarrator)
    n._feed = MagicMock()
    n._live = lambda: True
    n._may_react = lambda: True
    n._mark_spoken = lambda: None
    n._is_repeat = lambda text: False
    n._remember_bubble = lambda text: None
    n._recent_bubbles = __import__("collections").deque(maxlen=8)
    persona = MagicMock()
    persona.event_directives = directives if directives is not None else {}
    n._persona = persona
    return n


async def _capture(n, description, **kw):
    seen = {}

    async def _condense(text, system=None, **_):
        seen["system"] = system
        seen["text"] = text
        return "une réplique"

    n._condense = _condense
    await n.on_stream_event(description, **kw)
    return seen


@pytest.mark.asyncio
async def test_le_registre_du_type_est_injecte():
    n = _narrator({"raid": "Registre de l'accueil oblique."})
    seen = await _capture(n, "raid de bob avec 30 spectateurs", kind="raid")

    assert "Registre de l'accueil oblique." in seen["system"]


@pytest.mark.asyncio
async def test_un_autre_type_recoit_un_autre_registre():
    """C'est tout l'objet du découpage : un raid et une fin de live n'appellent
    pas le même ton."""
    n = _narrator({"raid": "AAA", "live_end": "BBB"})
    seen = await _capture(n, "Azrael a terminé son live.", kind="live_end")

    assert "BBB" in seen["system"]
    assert "AAA" not in seen["system"]


@pytest.mark.asyncio
async def test_un_type_sans_section_retombe_sur_le_socle():
    """Repli : jamais pire que le comportement d'avant."""
    n = _narrator({"raid": "AAA"})
    seen = await _capture(n, "quelque chose", kind="inconnu")

    assert "AAA" not in seen["system"]
    assert seen["system"]  # le socle reste


@pytest.mark.asyncio
async def test_sans_persona_le_socle_suffit():
    n = _narrator()
    n._persona = None
    seen = await _capture(n, "raid de bob", kind="raid")

    assert seen["system"]


@pytest.mark.asyncio
async def test_un_persona_qui_leve_ne_casse_pas_la_reaction():
    n = _narrator()
    broken = MagicMock()
    type(broken).event_directives = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("persona HS"))
    )
    n._persona = broken
    seen = await _capture(n, "raid de bob", kind="raid")

    assert seen["system"]  # la bulle sort quand même


# ── l'avatar s'emballe sur le TYPE, plus sur le texte ──

@pytest.mark.asyncio
async def test_lavatar_sagite_sur_un_vrai_raid():
    n = _narrator()
    await _capture(n, "raid de bob avec 30 spectateurs", kind="raid")

    assert any(c.args and c.args[0] == "stream_event"
               for c in n._feed.react.call_args_list)


@pytest.mark.asyncio
async def test_lavatar_ne_sagite_pas_sur_un_changement_de_titre():
    """`_STRONG_EVENT_HINTS` cherchait « raid » dans le TEXTE : un titre de
    stream contenant le mot suffisait à le déclencher."""
    n = _narrator()
    await _capture(n, "Azrael a changé le titre : « raid de sub aujourd'hui »",
                   kind="title_change")

    assert not any(c.args and c.args[0] == "stream_event"
                   for c in n._feed.react.call_args_list)


# ── le socle ne doit plus énumérer ni donner de phrases toutes faites ──

def test_le_socle_nenumere_plus_les_types():
    from bot.intelligence.overlay_narrator import _EVENT_SYSTEM

    bas = _EVENT_SYSTEM.lower()
    assert "du monde débarque" not in bas       # l'exemple recopié 30 fois
    assert "encore un qui va le regretter" not in bas


def test_le_fichier_de_registres_couvre_les_types_qui_parlent():
    """`audience` est émis en notify=False : il ne produit jamais de bulle, donc
    pas de section — une directive morte induirait en erreur."""
    from bot.intelligence.persona import PersonaService

    directives = PersonaService()._parse_sections("EVENTS.md")

    attendus = {"raid", "follow_wave", "sub", "gift_sub", "bits",
                "live_start", "live_end", "game_change", "title_change"}
    assert attendus <= set(directives)
    assert "audience" not in directives


def test_les_registres_ne_donnent_pas_de_replique_toute_faite():
    """Le motif « situation → réplique » de l'ancien prompt est ce qui produisait
    le perroquet : la réplique proposée ressortait mot pour mot. Les
    contre-exemples (« ne dis jamais bienvenue ») sont légitimes, eux."""
    import re
    from pathlib import Path

    texte = Path("bot/persona/EVENTS.md").read_text(encoding="utf-8")

    assert not re.search(r"→\s*«", texte), (
        "une réplique donnée en exemple finira recopiée telle quelle"
    )
