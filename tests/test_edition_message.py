"""Wally percevait les messages, jamais leurs corrections.

Écrit par lui le 2026-08-18 : « parfois je réponds à un contenu déjà périmé sans
le savoir ». Zéro occurrence de `on_message_edit` dans le dépôt — la fenêtre de
contexte, le prélude et les faits gardaient la version d'origine, pour toujours.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _msg(contenu, uid=7, nom="Alice", bot_flag=False, salon=42, guilde=1):
    auteur = SimpleNamespace(id=uid, name=nom, display_name=nom, bot=bot_flag)
    return SimpleNamespace(
        content=contenu, author=auteur, id=999,
        channel=SimpleNamespace(id=salon, guild=SimpleNamespace(id=guilde)),
        guild=SimpleNamespace(id=guilde) if guilde is not None else None,
        mentions=[],
    )


def _bot(salon_autorise=True):
    bot = MagicMock()
    bot.user = SimpleNamespace(id=1, name="Wally", display_name="Wally", bot=True)
    bot.config.discord.ignored_guilds = set()
    bot.memory.append_prelude = MagicMock()
    bot.memory.append_message = MagicMock()
    bot.cognitive_loop.notify_activity = MagicMock()

    captured = {}
    bot.event = lambda fn: captured.__setitem__(fn.__name__, fn) or fn

    from bot.discord.events import edits
    edits.register(bot)

    import bot.discord.handlers as handlers
    bot._patch = (handlers, salon_autorise)
    return bot, captured["on_message_edit"]


@pytest.fixture(autouse=True)
def _salon_ouvert(monkeypatch):
    import bot.discord.handlers as handlers
    monkeypatch.setattr(handlers, "_is_channel_allowed", lambda *a, **k: True)


# ── Ce qui est perçu ──────────────────────────────────────────────────────


async def test_une_correction_ajoute_une_ligne_au_prelude():
    """On AJOUTE : remplacer une ligne déjà partie au modèle ne réécrit pas le
    passé, et donnerait à Wally un souvenir sans tour de parole correspondant."""
    bot, on_edit = _bot()

    await on_edit(_msg("il fait beau"), _msg("il fait moche"))

    salon, auteur, ligne = bot.memory.append_prelude.call_args[0]
    assert salon == "42"
    assert "corrigé" in ligne and "il fait moche" in ligne


async def test_la_correction_entre_aussi_dans_la_fenetre_de_contexte():
    bot, on_edit = _bot()

    await on_edit(_msg("avant"), _msg("après"))

    assert bot.memory.append_message.called


async def test_un_message_vide_se_dit_autrement():
    """« a corrigé son message en :  » se lirait comme une panne."""
    bot, on_edit = _bot()

    await on_edit(_msg("quelque chose"), _msg(""))

    ligne = bot.memory.append_prelude.call_args[0][2]
    assert "effacé" in ligne


async def test_une_correction_tres_longue_est_bornee():
    bot, on_edit = _bot()

    await on_edit(_msg("court"), _msg("x" * 900))

    assert len(bot.memory.append_prelude.call_args[0][2]) < 340


# ── Ce qui n'est PAS perçu ────────────────────────────────────────────────


async def test_un_embed_de_lien_ne_reveille_rien():
    """Discord émet une édition quand l'aperçu d'un lien apparaît, sans que
    personne n'ait touché au texte. Sans ce filtre, chaque lien posté réveille
    la perception pour rien."""
    bot, on_edit = _bot()

    await on_edit(_msg("regarde https://x.fr"), _msg("regarde https://x.fr"))

    bot.memory.append_prelude.assert_not_called()
    bot.cognitive_loop.notify_activity.assert_not_called()


async def test_une_correction_de_bot_est_ignoree():
    bot, on_edit = _bot()

    await on_edit(_msg("a", bot_flag=True), _msg("b", bot_flag=True))

    bot.memory.append_prelude.assert_not_called()


async def test_wally_qui_edite_son_propre_message_est_ignore():
    bot, on_edit = _bot()

    await on_edit(_msg("a", uid=1), _msg("b", uid=1))

    bot.memory.append_prelude.assert_not_called()


async def test_une_guilde_ignoree_reste_ignoree():
    bot, on_edit = _bot()
    bot.config.discord.ignored_guilds = {1}

    await on_edit(_msg("a"), _msg("b"))

    bot.memory.append_prelude.assert_not_called()


async def test_un_salon_ferme_reste_ferme(monkeypatch):
    import bot.discord.handlers as handlers
    monkeypatch.setattr(handlers, "_is_channel_allowed", lambda *a, **k: False)
    bot, on_edit = _bot()

    await on_edit(_msg("a"), _msg("b"))

    bot.memory.append_prelude.assert_not_called()


# ── Perception, pas sollicitation ─────────────────────────────────────────


async def test_une_correction_ne_reveille_pas_la_cadence_vive():
    """Une correction n'est pas un nouveau message : Wally en tient compte à son
    prochain tour de parole, il ne repart pas au quart de tour."""
    bot, on_edit = _bot()

    await on_edit(_msg("salut"), _msg("salut wally"))

    assert bot.cognitive_loop.notify_activity.call_args.kwargs["relevant"] is False


async def test_une_edition_ratee_ne_fait_pas_tomber_le_bot():
    bot, on_edit = _bot()
    bot.memory.append_prelude.side_effect = RuntimeError("mémoire pleine")

    await on_edit(_msg("a"), _msg("b"))   # ne doit pas lever


# ── Le câblage ────────────────────────────────────────────────────────────


def test_le_handler_est_bien_enregistre():
    from bot.discord.events import register_events

    captured = {}
    bot = MagicMock()
    bot.event = lambda fn: captured.__setitem__(fn.__name__, fn) or fn
    register_events(bot)

    assert "on_message_edit" in captured
