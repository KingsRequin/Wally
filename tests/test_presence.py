# tests/test_presence.py
"""Tests pour PresenceService (perception lecture seule de la présence Discord)."""
from datetime import datetime, timedelta, timezone

import discord
import pytest
from unittest.mock import MagicMock

from bot.discord.presence import PresenceService


def _make_activity(activity_type, name):
    act = MagicMock()
    act.__class__ = discord.Activity  # pas Spotify/CustomActivity
    act.type = activity_type
    act.name = name
    return act


def _make_member(status="online", activities=(), display_name="Bob", bot=False):
    member = MagicMock()
    member.status = MagicMock()
    member.status.__str__ = lambda self: status
    member.activities = list(activities)
    member.display_name = display_name
    member.bot = bot
    return member


def _make_roster_client(members):
    client = MagicMock()
    guild = MagicMock()
    guild.members = list(members)
    client.get_guild = MagicMock(return_value=guild)
    return client


def _make_client(member=None, guild_present=True):
    client = MagicMock()
    guild = MagicMock() if guild_present else None
    if guild is not None:
        guild.get_member = MagicMock(return_value=member)
    client.get_guild = MagicMock(return_value=guild)
    return client


def test_disabled_without_guild_id(monkeypatch):
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    svc = PresenceService(MagicMock())
    assert svc.enabled is False
    assert svc.get("123") is None
    assert svc.describe("123", "Bob") is None


def test_enabled_with_explicit_guild_id():
    svc = PresenceService(MagicMock(), guild_id=42)
    assert svc.enabled is True


def test_get_returns_status_and_activities():
    member = _make_member(
        status="online",
        activities=[_make_activity(discord.ActivityType.playing, "Valorant")],
    )
    svc = PresenceService(_make_client(member), guild_id=42)
    snap = svc.get("610")
    assert snap == {"status": "online", "activities": ["joue à Valorant"]}


def test_get_none_when_member_not_cached():
    svc = PresenceService(_make_client(member=None), guild_id=42)
    assert svc.get("610") is None


def test_get_none_when_guild_not_in_cache():
    svc = PresenceService(_make_client(guild_present=False), guild_id=42)
    assert svc.get("610") is None


def test_describe_online_playing():
    member = _make_member(
        status="online",
        activities=[_make_activity(discord.ActivityType.playing, "Valorant")],
    )
    svc = PresenceService(_make_client(member), guild_id=42)
    assert svc.describe("610", "Cluth") == "Cluth est en ligne — joue à Valorant."


def test_describe_offline_no_activity_returns_none():
    member = _make_member(status="offline", activities=[])
    svc = PresenceService(_make_client(member), guild_id=42)
    assert svc.describe("610", "Cluth") is None


def test_describe_idle_no_activity():
    member = _make_member(status="idle", activities=[])
    svc = PresenceService(_make_client(member), guild_id=42)
    assert svc.describe("610", "Bob") == "Bob est inactif."


def test_describe_dnd_with_multiple_activities():
    member = _make_member(
        status="dnd",
        activities=[
            _make_activity(discord.ActivityType.playing, "Apex"),
            _make_activity(discord.ActivityType.listening, "lofi"),
        ],
    )
    svc = PresenceService(_make_client(member), guild_id=42)
    assert (
        svc.describe("610", "Az")
        == "Az est ne pas déranger — joue à Apex, écoute lofi."
    )


def test_custom_status_described():
    act = MagicMock()
    act.__class__ = discord.CustomActivity
    act.name = "en pause clope"
    act.created_at = None  # Discord n'a pas fourni de timestamp → pas de suffixe
    member = _make_member(status="online", activities=[act])
    svc = PresenceService(_make_client(member), guild_id=42)
    assert svc.describe("610", "Bob") == "Bob est en ligne — statut perso : « en pause clope »."


def test_custom_status_with_since_hours():
    act = MagicMock()
    act.__class__ = discord.CustomActivity
    act.name = "en pause clope"
    act.created_at = discord.utils.utcnow() - timedelta(hours=3, minutes=5)
    member = _make_member(status="online", activities=[act])
    svc = PresenceService(_make_client(member), guild_id=42)
    assert (
        svc.describe("610", "Bob")
        == "Bob est en ligne — statut perso : « en pause clope » (depuis 3 h)."
    )


# --- _format_since : formatage de la durée « depuis … » ---

@pytest.mark.parametrize(
    "delta,expected",
    [
        (timedelta(seconds=10), "à l'instant"),
        (timedelta(minutes=5), "depuis 5 min"),
        (timedelta(minutes=59), "depuis 59 min"),
        (timedelta(hours=1), "depuis 1 h"),
        (timedelta(hours=23, minutes=30), "depuis 23 h"),
        (timedelta(days=1), "depuis 1 j"),
        (timedelta(days=92), "depuis 92 j"),
    ],
)
def test_format_since_thresholds(delta, expected):
    now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
    assert PresenceService._format_since(now - delta, now=now) == expected


def test_format_since_none_when_no_timestamp():
    assert PresenceService._format_since(None) is None


def test_format_since_none_on_non_datetime():
    # Un MagicMock (ou toute valeur non-datetime) ne doit jamais planter.
    assert PresenceService._format_since(MagicMock()) is None


def test_format_since_none_on_future_timestamp():
    now = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
    assert PresenceService._format_since(now + timedelta(hours=1), now=now) is None


def test_spotify_activity_described():
    act = MagicMock()
    act.__class__ = discord.Spotify
    act.title = "Strobe"
    act.artist = "deadmau5"
    member = _make_member(status="online", activities=[act])
    svc = PresenceService(_make_client(member), guild_id=42)
    assert svc.describe("610", "Bob") == "Bob est en ligne — écoute Strobe — deadmau5."


def test_unknown_activity_ignored():
    member = _make_member(
        status="online",
        activities=[_make_activity(None, "")],  # name vide → ignoré
    )
    svc = PresenceService(_make_client(member), guild_id=42)
    assert svc.describe("610", "Bob") == "Bob est en ligne."


# --- roster() : présence de tous les membres visibles du serveur principal ---

def test_roster_empty_without_guild_id(monkeypatch):
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    svc = PresenceService(MagicMock())
    assert svc.roster() == []


def test_roster_empty_when_guild_not_cached():
    client = MagicMock()
    client.get_guild = MagicMock(return_value=None)
    svc = PresenceService(client, guild_id=42)
    assert svc.roster() == []


def test_roster_excludes_offline_and_bots():
    members = [
        _make_member(status="online", display_name="Alice"),
        _make_member(status="offline", display_name="Ghost"),
        _make_member(status="online", display_name="Robot", bot=True),
    ]
    svc = PresenceService(_make_roster_client(members), guild_id=42)
    assert svc.roster() == ["Alice est en ligne."]


def test_roster_prioritizes_dnd_then_busy_then_idle_then_online():
    members = [
        _make_member(status="online", display_name="OnlineGuy"),
        _make_member(status="idle", display_name="IdleGuy"),
        _make_member(
            status="online", display_name="Gamer",
            activities=[_make_activity(discord.ActivityType.playing, "Apex")],
        ),
        _make_member(status="dnd", display_name="Busy"),
    ]
    svc = PresenceService(_make_roster_client(members), guild_id=42)
    assert svc.roster() == [
        "Busy est ne pas déranger.",
        "Gamer est en ligne — joue à Apex.",
        "IdleGuy est inactif.",
        "OnlineGuy est en ligne.",
    ]


def test_roster_listening_music_is_not_busy():
    # Écouter de la musique ne classe pas « occupé » : reste après un gamer.
    spotify = MagicMock()
    spotify.__class__ = discord.Spotify
    spotify.title = "Strobe"
    spotify.artist = "deadmau5"
    spotify.type = discord.ActivityType.listening
    members = [
        _make_member(status="online", display_name="Listener", activities=[spotify]),
        _make_member(
            status="online", display_name="Gamer",
            activities=[_make_activity(discord.ActivityType.playing, "Apex")],
        ),
    ]
    svc = PresenceService(_make_roster_client(members), guild_id=42)
    assert svc.roster() == [
        "Gamer est en ligne — joue à Apex.",
        "Listener est en ligne — écoute Strobe — deadmau5.",
    ]


def test_roster_respects_limit():
    members = [_make_member(status="online", display_name=f"U{i}") for i in range(12)]
    svc = PresenceService(_make_roster_client(members), guild_id=42)
    assert len(svc.roster(limit=5)) == 5


def test_roster_swallows_errors():
    client = MagicMock()
    guild = MagicMock()
    # .members lève → roster doit renvoyer [] sans propager.
    type(guild).members = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    client.get_guild = MagicMock(return_value=guild)
    svc = PresenceService(client, guild_id=42)
    assert svc.roster() == []
