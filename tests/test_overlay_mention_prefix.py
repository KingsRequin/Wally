# tests/test_overlay_mention_prefix.py
"""Interpeller Wally ne doit pas annuler ce qu'on lui dit.

Vécu le 2026-08-07 sur le chat d'Azraël : deux parties de pendu lancées, et
AUCUNE lettre prise en compte. Les gens écrivaient « @WallyTeBully d » — le
réflexe naturel pour répondre à un bot — et le compteur, qui exige « une lettre
seule », voyait quinze caractères.

Le sondage et le chifoumi partagent la même racine : ils lisent le texte brut.
"""
from unittest.mock import AsyncMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrateur():
    return OverlayNarrator(OverlayFeed(), AsyncMock(), lambda: True)


# ── le pendu ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_lettre_precedee_d_une_mention_compte():
    n = _narrateur()
    n.start_hangman("fuse", "une légende")
    await n.on_chat_message("kingsrequin", "@WallyTeBully f")
    assert "f" in n._hangman["found"]


@pytest.mark.asyncio
async def test_une_lettre_seule_compte_toujours():
    n = _narrateur()
    n.start_hangman("fuse", "une légende")
    await n.on_chat_message("kingsrequin", "f")
    assert "f" in n._hangman["found"]


@pytest.mark.asyncio
async def test_une_mauvaise_lettre_avec_mention_compte_aussi():
    n = _narrateur()
    n.start_hangman("fuse", "une légende")
    await n.on_chat_message("kingsrequin", "@WallyTeBully z")
    assert "z" in n._hangman["missed"]


@pytest.mark.asyncio
async def test_une_phrase_adressee_ne_propose_toujours_pas_de_lettre():
    """La garde d'origine tient : sinon chaque message du chat jouerait."""
    n = _narrateur()
    n.start_hangman("fuse", "une légende")
    await n.on_chat_message("kingsrequin", "@WallyTeBully tu fais quoi")
    assert not n._hangman["found"] and not n._hangman["missed"]


# ── le sondage ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_un_vote_precede_d_une_mention_compte():
    n = _narrateur()
    n.start_poll("chocolat ?", ["oui", "non"], seconds=60)
    await n.on_chat_message("kingsrequin", "@WallyTeBully 2")
    assert n._poll["votes"].get("kingsrequin") == 1


@pytest.mark.asyncio
async def test_j_ai_2_chats_ne_vote_toujours_pas():
    n = _narrateur()
    n.start_poll("chocolat ?", ["oui", "non"], seconds=60)
    await n.on_chat_message("kingsrequin", "j'ai 2 chats")
    assert not n._poll["votes"]


# Le chifoumi ne lit plus le chat : il se tranche à l'instant où on le demande,
# sans vote. Ses deux cas de mention sont partis avec le comptage.
