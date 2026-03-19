# tests/test_account_linker.py
"""Tests pour account_linker : normalisation, score, et analyse."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.account_linker import _normalize, score, analyze_all, analyze_new_user


# --- Tests de normalisation ---

def test_normalize_lowercase():
    assert _normalize("KingsRequin") == "kingsrequin"

def test_normalize_ttv_suffix():
    assert _normalize("kingsrequin_TTV") == "kingsrequin"

def test_normalize_ttv_without_underscore():
    assert _normalize("kingsrequinttv") == "kingsrequin"

def test_normalize_separators():
    assert _normalize("kings_requin") == "kingsrequin"
    assert _normalize("kings-requin") == "kingsrequin"
    assert _normalize("kings.requin") == "kingsrequin"

def test_normalize_trailing_digits():
    assert _normalize("kingsrequin123") == "kingsrequin"

def test_normalize_combined():
    assert _normalize("KingsRequin_TTV123") == "kingsrequin"


# --- Tests de score ---

def test_score_identical():
    assert score("kingsrequin", "kingsrequin") == pytest.approx(1.0, abs=0.001)

def test_score_similar():
    s = score("kingsrequin_ttv", "KingsRequin")
    assert s > 0.9, f"Expected > 0.9, got {s}"

def test_score_different():
    s = score("alice", "bob")
    assert s < 0.75

def test_score_empty_after_normalize():
    """Un ID purement numérique (Discord) se normalise en chaîne vide → score 0."""
    s = score("521849789797761035", "kingsrequin")
    assert s == 0.0


# --- Helpers pour les mocks get_platform_users (format dict) ---

def _discord_users(*names):
    """Crée des mocks Discord users avec username."""
    return [
        {"raw_id": str(i), "username": name, "full_id": f"discord:{i}"}
        for i, name in enumerate(names, start=100)
    ]

def _twitch_users(*names):
    """Crée des mocks Twitch users (raw_id numérique, username = nom)."""
    return [
        {"raw_id": str(i), "username": name, "full_id": f"twitch:{i}"}
        for i, name in enumerate(names, start=200)
    ]


# --- Tests d'analyze_all ---

@pytest.mark.asyncio
async def test_analyze_all_creates_proposals():
    """analyze_all crée une proposition quand score >= threshold."""
    db = MagicMock()
    db.get_platform_users = AsyncMock(side_effect=lambda p:
        _discord_users("KingsRequin") if p == "discord" else _twitch_users("kingsrequin_ttv")
    )
    db.upsert_link_proposal = AsyncMock()

    count = await analyze_all(db, threshold=0.75)
    assert count >= 1
    db.upsert_link_proposal.assert_called()
    call_args = db.upsert_link_proposal.call_args_list[0]
    assert call_args[0][0].startswith("discord:")
    assert call_args[0][1].startswith("twitch:")

@pytest.mark.asyncio
async def test_analyze_all_no_proposal_below_threshold():
    """analyze_all ne crée pas de proposition si score < threshold."""
    db = MagicMock()
    db.get_platform_users = AsyncMock(side_effect=lambda p:
        _discord_users("alice") if p == "discord" else _twitch_users("zzztotallydifferent")
    )
    db.upsert_link_proposal = AsyncMock()

    count = await analyze_all(db, threshold=0.75)
    assert count == 0
    db.upsert_link_proposal.assert_not_called()

@pytest.mark.asyncio
async def test_analyze_all_skips_discord_without_username():
    """analyze_all ignore les Discord users sans username (ID numérique inutile)."""
    db = MagicMock()
    db.get_platform_users = AsyncMock(side_effect=lambda p:
        [{"raw_id": "521849789797761035", "username": None, "full_id": "discord:521849789797761035"}]
        if p == "discord" else _twitch_users("kingsrequin")
    )
    db.upsert_link_proposal = AsyncMock()

    count = await analyze_all(db, threshold=0.75)
    assert count == 0
    db.upsert_link_proposal.assert_not_called()


# --- Tests d'analyze_new_user ---

@pytest.mark.asyncio
async def test_analyze_new_discord_user():
    """analyze_new_user pour un discord user compare son username contre Twitch."""
    db = MagicMock()
    db.get_platform_users = AsyncMock(side_effect=lambda p:
        _discord_users("KingsRequin") if p == "discord" else _twitch_users("kingsrequin_ttv")
    )
    db.upsert_link_proposal = AsyncMock()

    await analyze_new_user(db, "discord:100", threshold=0.75)
    db.upsert_link_proposal.assert_called()

@pytest.mark.asyncio
async def test_analyze_new_twitch_user():
    """analyze_new_user pour un twitch user compare contre Discord usernames."""
    db = MagicMock()
    twitch_users = _twitch_users("kingsrequin_ttv")
    db.get_platform_users = AsyncMock(side_effect=lambda p:
        twitch_users if p == "twitch" else _discord_users("KingsRequin")
    )
    db.upsert_link_proposal = AsyncMock()

    await analyze_new_user(db, twitch_users[0]["full_id"], threshold=0.75)
    db.upsert_link_proposal.assert_called()
