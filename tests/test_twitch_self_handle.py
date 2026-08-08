# tests/test_twitch_self_handle.py
"""Wally doit savoir sous quel pseudo il apparaît sur Twitch.

Il s'appelle « Wally », mais le chat l'interpelle par « @WallyTeBully » — son
login Twitch, qui n'est écrit nulle part dans son prompt. Il voyait donc passer
des messages qui lui étaient adressés sans faire le lien avec lui-même, et
pouvait répondre « je ne sais pas qui c'est » à propos de son propre compte.

Le pseudo dépend de la PLATEFORME, pas de la personne : il a sa place dans le
contexte situationnel, à côté du salon et de la chaîne.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from bot.intelligence.prompts import PromptBuilder
from bot.twitch.handlers import _build_situation


def _bot(nick="WallyTeBully"):
    bot = MagicMock()
    bot._stream_info = {}
    bot.twitch_api = SimpleNamespace(_bot_nick=nick)
    return bot


def test_le_pseudo_twitch_est_dans_la_situation(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "WallyTeBully")
    situation = _build_situation(_bot(), "potitewonder")
    assert situation["self_handle"] == "WallyTeBully"


def test_sans_pseudo_configure_la_cle_est_absente(monkeypatch):
    """Mieux vaut rien qu'une ligne « Ton pseudo : » vide, qui inviterait le
    modèle à en inventer un."""
    monkeypatch.delenv("TWITCH_BOT_NICK", raising=False)
    situation = _build_situation(_bot(), "potitewonder")
    assert "self_handle" not in situation


def test_le_prompt_annonce_le_pseudo():
    prompt = PromptBuilder().build_system_prompt(
        emotion_state={},
        situation={"platform": "Twitch", "self_handle": "WallyTeBully"},
    )
    assert "WallyTeBully" in prompt


def test_le_prompt_dit_que_c_est_LUI():
    """Écrire le pseudo ne suffit pas : sans le rattacher explicitement, le
    modèle peut le lire comme le nom d'un tiers présent dans le salon."""
    prompt = PromptBuilder().build_system_prompt(
        emotion_state={},
        situation={"platform": "Twitch", "self_handle": "WallyTeBully"},
    )
    ligne = next(l for l in prompt.splitlines() if "WallyTeBully" in l)
    assert "@WallyTeBully" in ligne, "la forme mentionnée dans le chat"
    assert "toi" in ligne.lower() or "ton pseudo" in ligne.lower()


def test_sans_pseudo_aucune_ligne_n_est_ajoutee():
    prompt = PromptBuilder().build_system_prompt(
        emotion_state={}, situation={"platform": "Twitch"},
    )
    assert "pseudo" not in prompt.lower().split("--- contexte situationnel ---")[-1][:400]
