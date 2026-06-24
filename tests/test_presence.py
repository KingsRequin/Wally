# tests/test_presence.py
"""Tests pour PresenceService (perception lecture seule de la présence Discord)."""
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


def _make_member(status="online", activities=()):
    member = MagicMock()
    member.status = MagicMock()
    member.status.__str__ = lambda self: status
    member.activities = list(activities)
    return member


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
    member = _make_member(status="online", activities=[act])
    svc = PresenceService(_make_client(member), guild_id=42)
    assert svc.describe("610", "Bob") == "Bob est en ligne — statut perso : « en pause clope »."


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
