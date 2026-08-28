"""Trois pannes qui ne disent rien : decay mort, vote annulé, onglet injoignable."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock


# ── La boucle de decay survit à un tour raté ─────────────────────────────────
#
# `_decay_loop` n'avait aucune garde. Une seule exception tuait la tâche
# DÉFINITIVEMENT et rien ne la relançait : plus de decay (la colère restait
# figée, donc permanente), plus d'ennui, plus de compétition, plus de
# sauvegarde. Sans un log : l'exception d'une Task morte n'est rapportée qu'au
# ramassage. Symptôme observable : « ses émotions ne bougent plus ».

async def test_un_tick_qui_leve_ne_tue_pas_la_boucle(monkeypatch):
    from bot.core.emotion import EmotionEngine

    moteur = EmotionEngine.__new__(EmotionEngine)
    moteur._state = {"anger": 0.5}
    moteur._dirty = False
    moteur._ticks = 0
    moteur._db = None
    moteur._schedule_save = lambda: None

    appels = {"n": 0}

    def _decay_capricieux():
        appels["n"] += 1
        if appels["n"] == 1:
            raise ValueError("total of weights must be greater than zero")

    moteur._apply_decay = _decay_capricieux
    # Un sleep instantané mais qui REND la main : un mock qui retourne sans
    # yielder empêcherait la tâche d'être planifiée du tout.
    vrai_sleep = asyncio.sleep

    async def _sans_attendre(_):
        await vrai_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _sans_attendre)

    tache = asyncio.create_task(moteur._decay_loop())
    for _ in range(20):                      # laisse tourner quelques tours
        await asyncio.sleep(0)
        if appels["n"] >= 3:
            break
    tache.cancel()

    assert appels["n"] >= 3, "la boucle est morte au premier tour raté"


# ── Le vote 🔥 n'est compté qu'une fois ───────────────────────────────────────
#
# La view est persistante, donc enregistrée dans le `ViewStore` : discord.py
# exécutait le callback du bouton PUIS réveillait le listener. Les deux
# appelaient `toggle_gallery_vote` — le vote s'ajoutait puis se retirait, net
# zéro, et le second `edit_message` levait `InteractionResponded`.

def test_les_boutons_de_galerie_nont_pas_de_callback_propre():
    """Le seul chemin de traitement est `ImagineCog.on_interaction`."""
    import discord

    from bot.discord.commands.imagine import EditTitleButton, FlameButton

    # `Item.callback` est un no-op : ne pas le surcharger rend `dispatch_view`
    # inoffensif, et supprime la course avec le listener.
    assert FlameButton.callback is discord.ui.Item.callback
    assert EditTitleButton.callback is discord.ui.Item.callback


async def test_un_clic_ne_bascule_le_vote_quune_fois():
    from bot.discord.commands.imagine import GalleryView, ImagineCog

    db = MagicMock()
    db.toggle_gallery_vote = AsyncMock(return_value=True)
    db.get_gallery_image = AsyncMock(return_value={"votes": 1, "user_id": "discord:610"})

    bot = MagicMock()
    bot.db = db
    cog = ImagineCog(bot)

    import discord

    interaction = MagicMock()
    interaction.type = discord.InteractionType.component
    interaction.data = {"custom_id": "gallery_vote:img42"}
    interaction.user.id = 610
    interaction.response.edit_message = AsyncMock()

    # Le clic tel que discord.py le livre : la view ne fait rien, le listener agit.
    vue = GalleryView("img42", 610, db)
    await vue.children[0].callback(interaction)      # dispatch_view → no-op
    await cog.on_interaction(interaction)            # dispatch('interaction')

    assert db.toggle_gallery_vote.await_count == 1


# ── L'onglet Twitch de /wally setup s'ouvre ──────────────────────────────────

def test_twitch_config_lit_un_champ_qui_existe():
    """`cfg.channels` a disparu du dataclass — `Config.load()` fait
    `twitch_raw.pop("channels")`. La ligne d'affichage levait une AttributeError
    avant toute réponse : « Cette interaction a échoué », onglet injoignable."""
    from dataclasses import fields

    from bot.config import TwitchConfig

    noms = {f.name for f in fields(TwitchConfig)}
    assert "channels" not in noms
    assert "guest_channels" in noms

    source = (
        __import__("pathlib").Path("bot/discord/commands/setup/advanced.py")
        .read_text(encoding="utf-8")
    )
    assert "', '.join(cfg.guest_channels)" in source
    assert "', '.join(cfg.channels)" not in source


# ── Les flux SSE ne laissent pas de file orpheline ───────────────────────────

def test_les_flux_sse_sabonnent_dans_le_generateur():
    """Hors du générateur, une requête abandonnée avant le premier `send`
    laissait la file dans `_log_queues` POUR TOUJOURS — le `finally` ne
    s'exécute que si le générateur a démarré. `_log_sink` itère sur cette liste
    à CHAQUE ligne de log, et chaque file morte retient 100 entrées.

    Le piège est documenté depuis `sse_overlay_feed` ; il n'avait pas été
    reporté sur ses deux voisins."""
    import inspect

    from bot.dashboard.routes import sse

    for route, registre in (
        (sse.sse_logs, "_log_queues"),
        (sse.sse_actions, "_action_queues"),
        (sse.sse_overlay_feed, "feed.subscribe"),
    ):
        source = inspect.getsource(route)
        avant, _, apres = source.partition("async def generate()")
        assert registre not in avant, (
            f"{route.__name__} s'abonne AVANT le générateur → file orpheline"
        )
        assert registre in apres, f"{route.__name__} ne s'abonne nulle part"


def test_le_sous_onglet_vocal_passe_par_la_garde_anti_double_montage():
    """`_renderParametresVoice` vide le panneau, PUIS attend le réseau, PUIS
    écrit : deux appels rapprochés produisaient deux formulaires. Or
    `saveVoiceConfigParams` lit par `getElementById`, qui ne rend que le
    premier — un réglage saisi dans la seconde copie partait depuis la
    première."""
    import re
    from pathlib import Path

    source = Path("bot/dashboard/static/app.js").read_text(encoding="utf-8")

    # L'INVARIANT, pas le site d'appel : `_renderParametresVoice` est CONFIÉE à
    # la garde, jamais appelée directement. La version d'avant assertait la
    # ligne exacte `_renderPanelOnce(panel, _renderParametresVoice)` — elle a
    # cassé le jour où la page Voix a hébergé le panneau ailleurs, sans que
    # l'invariant bouge d'un pouce. Asserter une ligne d'implémentation fige le
    # code, pas la propriété.
    directs = [
        l.strip() for l in source.splitlines()
        if "_renderParametresVoice(" in l and "function _renderParametresVoice(" not in l
    ]
    assert not directs, (
        "`_renderParametresVoice` est appelée directement : deux appels "
        f"rapprochés monteraient deux formulaires — {directs}"
    )
    confiee = re.search(
        r"_renderPanelOnce\([^;]*?,\s*_renderParametresVoice\s*\)", source, re.S)
    assert confiee, "`_renderParametresVoice` n'est plus confiée à `_renderPanelOnce`"
