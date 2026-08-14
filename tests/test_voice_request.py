# tests/test_voice_request.py
"""Une demande à voix haute vaut une mention écrite.

Ce que le chemin vocal doit garantir : les mêmes outils qu'à l'écrit, une
réponse dans le chat Twitch adressée à celui qui a parlé, et personne d'autre
que les demandeurs déclarés ne peut lui donner d'ordre.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.voice.request import (
    handle_voice_request,
    is_addressed,
    resolve_requester,
)


def _requesters():
    return [
        {"discord_id": "610550333042589752", "twitch_login": "kingsrequin"},
        {"discord_id": "419172225451556874", "twitch_login": "azrael_ttv"},
    ]


# ── qui a le droit de demander ───────────────────────────────────────────────


def test_un_demandeur_declare_est_reconnu():
    who = resolve_requester("419172225451556874", _requesters())
    assert who["twitch_login"] == "azrael_ttv"


def test_un_tiers_n_est_pas_reconnu():
    assert resolve_requester("999", _requesters()) is None


def test_sans_liste_personne_ne_demande_rien():
    """Config vide = fonctionnalité éteinte, pas ouverte à tous."""
    assert resolve_requester("610550333042589752", []) is None


# ── le déclencheur, malgré le STT ────────────────────────────────────────────


@pytest.mark.parametrize("phrase", [
    "wally fais un pile ou face",
    "Wally, tu peux afficher mon rang ?",
    "wallis fait un pile ou face",      # le STT entend mal son nom
    "walli t'en penses quoi",       # idem
    "wallie tu dors ?",             # idem
    "le wally il a rien compris",   # nommé au milieu d'une phrase
    "wallly regarde ça",            # faute de frappe
    "WALLY !!",                     # casse et ponctuation
])
def test_son_nom_est_reconnu_meme_mal_transcrit(phrase):
    assert is_addressed(phrase, ["wally"])


@pytest.mark.parametrize("phrase", [
    "il y a des jambons dans le loot",
    "attention derrière toi",
    "valise",                            # trop loin, et sans rapport
])
def test_une_phrase_qui_ne_le_nomme_pas_ne_declenche_rien(phrase):
    assert not is_addressed(phrase, ["wally"])


# Relevés en live : 9 déclenchements sur 31 le 13/08 (29 %), et jusqu'à 60 % sur
# un autre jour. Chacun coûte un appel au modèle ET un message publié dans le
# chat de la chaîne — Azraël dit « Well… », Wally répond « Allez, accouche, on
# t'écoute 😄 » à quelqu'un qui n'a rien demandé.
@pytest.mark.parametrize("mot", [
    "balle", "salle", "dalle", "allô", "allé", "aller", "all", "well", "way",
    "early",
])
def test_les_mots_qui_le_declenchaient_a_tort(mot):
    assert not is_addressed(f"si on n'a pas de {mot} on fait comment", ["wally"])


def test_son_nom_prive_de_son_initiale_nest_plus_son_nom():
    """« wally » sans le `w` n'est pas une transcription ratée : c'est autre chose."""
    assert not is_addressed("ally tu m'entends", ["wally"])


def test_un_mot_court_doit_tomber_juste():
    """Trois lettres n'ont pas de quoi encaisser deux corrections."""
    assert not is_addressed("on y va", ["wally"])
    assert not is_addressed("waly", ["wally"])          # 4 lettres : trop court
    assert is_addressed("wal", ["wal"])                 # sauf s'il tombe pile


# ── le chemin complet ────────────────────────────────────────────────────────


def _bot(live=True):
    bot = MagicMock()
    bot.config.voice.requesters = _requesters()
    bot.config.bot.name = "Wally"
    bot.config.bot.trigger_names = ["wally"]
    narrator = MagicMock()
    narrator.is_active = MagicMock(return_value=live)
    narrator.on_voice_bubble = AsyncMock()
    bot.overlay_narrator = narrator
    twitch = MagicMock()
    twitch.send_message = AsyncMock()
    bot._twitch_bot = MagicMock()
    bot._twitch_bot.twitch_api = twitch
    bot._twitch_bot.config = bot.config
    return bot


@pytest.mark.asyncio
async def test_la_reponse_part_dans_le_chat_en_mentionnant_qui_a_parle(monkeypatch):
    bot = _bot()
    envoi = []

    async def _fake_reply(_bot, _texte, **_kw):
        return "Pile. Tu commences fort."

    monkeypatch.setattr("bot.discord.voice.request._answer", _fake_reply)
    bot._twitch_bot.twitch_api.send_message = AsyncMock(side_effect=lambda *a, **k: envoi.append((a, k)))

    await handle_voice_request(bot, "419172225451556874", "Azraël", "wally fais un pile ou face")

    assert envoi, "rien n'a été envoyé dans le chat"
    message = str(envoi[0])
    assert "@azrael_ttv" in message
    assert "Pile" in message


@pytest.mark.asyncio
async def test_un_tiers_ne_declenche_rien(monkeypatch):
    bot = _bot()
    appels = []
    monkeypatch.setattr("bot.discord.voice.request._answer",
                        AsyncMock(side_effect=lambda *a, **k: appels.append(a)))

    await handle_voice_request(bot, "999", "Quelqu'un", "wally fais un pile ou face")

    assert appels == []
    bot._twitch_bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_hors_live_rien_ne_part_dans_le_chat(monkeypatch):
    """Personne ne lit le chat d'un stream éteint."""
    bot = _bot(live=False)
    monkeypatch.setattr("bot.discord.voice.request._answer",
                        AsyncMock(return_value="Pile."))

    await handle_voice_request(bot, "419172225451556874", "Azraël", "wally pile ou face")

    bot._twitch_bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_phrase_qui_ne_le_nomme_pas_est_ignoree(monkeypatch):
    bot = _bot()
    appels = []
    monkeypatch.setattr("bot.discord.voice.request._answer",
                        AsyncMock(side_effect=lambda *a, **k: appels.append(a)))

    await handle_voice_request(bot, "419172225451556874", "Azraël", "putain le ping")

    assert appels == []
