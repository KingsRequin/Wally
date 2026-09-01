"""« Wally, fais venir Lilio sur le stream » — le déplacement vocal.

Demande de l'owner du 2026-09-01. Ce qui est vérifié ici est surtout ce qui
peut NUIRE : déplacer quelqu'un que personne n'a nommé, obéir à quelqu'un qui
n'en a pas le droit, ou choisir tout seul entre deux pseudos qui se
ressemblent — l'owner a explicitement demandé que Wally REDEMANDE dans ce cas.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.tools.move_voice_tool import (
    MOVE_TO_STREAM_TOOL, classer, presents_hors_stream, run_move_to_stream_tool,
)

OWNER_DISCORD = "610550333042589752"
STREAMER_DISCORD = "419172225451556874"
STREAMER_TWITCH = "659251746"
REQUESTERS = [
    {"discord_id": OWNER_DISCORD, "twitch_id": "105904256"},
    {"discord_id": STREAMER_DISCORD, "twitch_id": STREAMER_TWITCH},
]


def _membre(nom: str, *, salon=None, bot=False):
    m = MagicMock()
    m.display_name = nom
    m.name = nom.lower()
    m.global_name = None
    m.bot = bot
    m.voice = MagicMock()
    m.voice.channel = salon
    m.move_to = AsyncMock()
    return m


def _salon(nom: str, ident: int, membres=None):
    s = MagicMock()
    s.name = nom
    s.id = ident
    s.members = membres or []
    return s


def _guilde(salons):
    g = MagicMock()
    g.voice_channels = salons
    for s in salons:
        s.guild = g
    return g


def _bot(*, live=True, autres=("Lilio",), stream_membres=()):
    """Un bot Twitch complet : live en cours, un salon stream, un salon à côté."""
    stream = _salon("🔴 Stream", 1, [_membre(n) for n in stream_membres])
    cote = _salon("Général", 2)
    cote.members = [_membre(n, salon=cote) for n in autres]
    _guilde([stream, cote])

    b = MagicMock()
    b.config.voice.requesters = REQUESTERS
    b.config.bot.owner_discord_id = OWNER_DISCORD
    b.config.bot.stream_voice_channel_id = 1
    b.twitch_api._broadcaster_id = STREAMER_TWITCH
    b.discord_bot = MagicMock()
    b.overlay_narrator.is_active.return_value = live
    b.db = MagicMock()
    b._salon_resolu = stream
    return b


@pytest.fixture(autouse=True)
def _salon_resolu(monkeypatch):
    """`resolve_voice_channel` interroge Discord : on rend le salon du bot."""
    async def _resolve(discord_bot, db, configured):
        return _COURANT["salon"]

    monkeypatch.setattr("bot.discord.voice.channel_memory.resolve_voice_channel",
                        _resolve)
    yield


_COURANT: dict = {"salon": None}


async def _appel(b, personne, *, platform="discord", user_id=STREAMER_DISCORD):
    _COURANT["salon"] = b._salon_resolu
    return json.loads(await run_move_to_stream_tool(
        b, {"person": personne}, platform=platform, user_id=user_id,
        author="Azraël"))


# ── le geste ────────────────────────────────────────────────────────────────

async def test_le_streamer_fait_venir_quelqu_un():
    b = _bot(autres=("Lilio", "Marceau"))
    rendu = await _appel(b, "lilio")
    assert rendu["status"] == "ok"
    assert rendu["moved"] == "Lilio"
    cible = b._salon_resolu
    lilio = next(m for m in cible.guild.voice_channels[1].members if m.display_name == "Lilio")
    lilio.move_to.assert_awaited_once()
    assert lilio.move_to.await_args.args[0] is cible


async def test_le_createur_aussi():
    b = _bot()
    rendu = await _appel(b, "Lilio", user_id=OWNER_DISCORD)
    assert rendu["status"] == "ok"


async def test_un_pseudo_ecorche_par_la_transcription_retombe_sur_la_personne():
    """« Lilio » entendu « Lilo » : c'est le cas NORMAL en vocal, pas une faute."""
    b = _bot(autres=("Lilio", "Marceau"))
    assert (await _appel(b, "Lilo"))["status"] == "ok"


# ── ce qui doit être refusé ─────────────────────────────────────────────────

async def test_un_viewer_ne_deplace_personne():
    b = _bot()
    rendu = await _appel(b, "Lilio", platform="twitch", user_id="999")
    assert rendu["status"] == "denied"
    for m in b._salon_resolu.guild.voice_channels[1].members:
        m.move_to.assert_not_awaited()


async def test_un_demandeur_sans_identite_ne_passe_pas():
    """Le refus est le défaut sûr : sans identité établie, pas de déplacement.

    L'autorisation vient de l'APPELANT (`platform`/`user_id`), jamais de ce que
    la phrase prétend — un « je suis modérateur » dans le message ne peut donc
    rien changer, il n'atteint même pas cette fonction.
    """
    b = _bot()
    assert (await _appel(b, "Lilio", platform="twitch",
                         user_id=""))["status"] == "denied"


async def test_hors_live_il_ne_deplace_personne():
    b = _bot(live=False)
    rendu = await _appel(b, "Lilio")
    assert rendu["status"] == "offline"
    for m in b._salon_resolu.guild.voice_channels[1].members:
        m.move_to.assert_not_awaited()


async def test_sans_personne_nommee_il_demande_qui():
    b = _bot()
    rendu = json.loads(await run_move_to_stream_tool(
        b, {}, platform="discord", user_id=STREAMER_DISCORD))
    assert rendu["status"] == "error"


# ── l'hésitation, qui est la fonctionnalité ─────────────────────────────────

async def test_deux_pseudos_proches_font_REDEMANDER():
    """L'owner l'a demandé nommément : en cas de doute, Wally repose la question."""
    b = _bot(autres=("Marceau", "Marceaux"))
    rendu = await _appel(b, "Marcau")
    assert rendu["status"] == "ambiguous"
    assert set(rendu["candidats"]) == {"Marceau", "Marceaux"}
    for m in b._salon_resolu.guild.voice_channels[1].members:
        m.move_to.assert_not_awaited()


async def test_un_nom_inconnu_liste_qui_est_la():
    """« je n'ai personne de ce nom » vaut mieux qu'un déplacement au hasard."""
    b = _bot(autres=("Lilio", "Marceau"))
    rendu = await _appel(b, "Gontrand")
    assert rendu["status"] == "unknown"
    assert set(rendu["en_vocal"]) == {"Lilio", "Marceau"}


async def test_personne_en_vocal_le_dit():
    b = _bot(autres=())
    assert (await _appel(b, "Lilio"))["status"] == "empty"


# ── le tri lui-même ─────────────────────────────────────────────────────────

def test_le_surnom_usuel_bat_le_ratio_brut():
    """« azra » ne vaut que 0,57 en SequenceMatcher face à « Azrael_ttv »."""
    azrael, autre = _membre("Azrael_ttv"), _membre("Marceau")
    assert classer("azra", [autre, azrael])[0][1] is azrael


def test_les_bots_ne_sont_jamais_candidats():
    """Wally est lui-même en vocal : il ne va pas se déplacer sur son propre ordre."""
    stream = _salon("🔴 Stream", 1)
    cote = _salon("Général", 2)
    cote.members = [_membre("Wally", salon=cote, bot=True), _membre("Lilio", salon=cote)]
    _guilde([stream, cote])
    assert [m.display_name for m in presents_hors_stream(stream)] == ["Lilio"]


def test_ceux_qui_sont_DEJA_dans_le_salon_du_stream_ne_sont_pas_candidats():
    stream = _salon("🔴 Stream", 1)
    stream.members = [_membre("Azraël", salon=stream)]
    cote = _salon("Général", 2)
    cote.members = [_membre("Lilio", salon=cote)]
    _guilde([stream, cote])
    assert [m.display_name for m in presents_hors_stream(stream)] == ["Lilio"]


# ── le contrat passé au modèle ──────────────────────────────────────────────

def test_l_outil_INTERDIT_au_modele_de_choisir_a_la_place():
    description = MOVE_TO_STREAM_TOOL["function"]["description"]
    assert "devines JAMAIS" in description or "JAMAIS" in description
    assert MOVE_TO_STREAM_TOOL["function"]["parameters"]["required"] == ["person"]


async def test_un_droit_discord_manquant_est_DIT_et_pas_confirme():
    b = _bot()
    lilio = b._salon_resolu.guild.voice_channels[1].members[0]
    lilio.move_to = AsyncMock(side_effect=RuntimeError("Missing Permissions"))
    rendu = await _appel(b, "Lilio")
    assert rendu["status"] == "failed"
    assert "Déplacer des membres" in rendu["message"]


# ── le câblage : offert, et routé ───────────────────────────────────────────

async def test_l_outil_est_offert_au_chat_de_la_chaine_maison():
    """Un outil absent du catalogue manque en SILENCE — trois refus muets en
    direct le 2026-08-25 avant qu'on s'en aperçoive."""
    from bot.twitch.handlers import build_chat_tools

    b = _bot()
    b.web_search = None
    b.scrape = None
    b.apex_api = None
    b.action_service = None
    b.tally = None
    b.predictions = None
    b.quotes = None
    b.music = None
    noms = [t["function"]["name"] for t in await build_chat_tools(b)]
    assert "move_to_stream" in noms

    # Chaîne INVITÉE : l'overlay et le vocal appartiennent au stream maison.
    noms = [t["function"]["name"] for t in await build_chat_tools(b, overlay=False)]
    assert "move_to_stream" not in noms


async def test_l_executeur_route_l_outil_avec_l_identite_de_l_appelant():
    from bot.twitch.handlers import make_tool_executor

    b = _bot()
    _COURANT["salon"] = b._salon_resolu
    executor = make_tool_executor(b, platform="discord", user_id=STREAMER_DISCORD,
                                  author="Azraël", channel="azrael_ttv")
    rendu = json.loads(await executor("move_to_stream", json.dumps({"person": "Lilio"})))
    assert rendu["status"] == "ok"


async def test_quelqu_un_deja_dans_le_salon_du_stream_n_est_pas_un_inconnu():
    """« Personne ne s'appelle Lilio » alors qu'il est assis là est FAUX."""
    b = _bot(autres=("Marceau",), stream_membres=("Lilio",))
    rendu = await _appel(b, "Lilio")
    assert rendu["status"] == "already"
    assert rendu["moved"] == "Lilio"
