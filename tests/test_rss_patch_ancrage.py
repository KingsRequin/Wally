"""Wally doit pouvoir répondre « il ne s'est rien passé », patch notes à l'appui.

Symptôme de l'owner : « si je lui demande si le Wingman a eu un nerf ou un buff,
il va ressortir des patchs de la saison 20 en me disant que oui, il a reçu un
buff récemment et que c'est encore d'actualité. Mais la question ne vaut que
pour la dernière saison : ça devrait être "non, pas de changement depuis la
saison 20". »

Le bloc donnait déjà l'âge de chaque extrait. Il lui manquait deux choses, et
c'est la seconde qui coûte :

  1. L'ANCRE — jusqu'à quand va sa connaissance. Sans elle, « rien depuis » est
     indémontrable : il ne sait pas s'il n'a rien vu parce qu'il n'y a rien eu,
     ou parce que sa base s'arrête là.
  2. L'AUTORISATION de conclure à l'absence. Un modèle à qui l'on tend trois
     extraits parlant du Wingman répond sur le Wingman : il lui faut la
     permission explicite de dire « ça date, et depuis, rien ».

Relevé sur la base de production le 2026-08-17 : 176 sections de patch notes, la
plus récente du 11 août, et le Wingman n'apparaît que dans deux extraits de juin
et juillet. C'est exactement la situation où il répondait « buff récent ».
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.handlers import _rss_knowledge_context


def _bot(articles, dernier_ts=None):
    bot = MagicMock()
    bot.config.rss = SimpleNamespace(
        enabled=True,
        knowledge_max_age_days=120,
        feeds=[SimpleNamespace(role="knowledge", enabled=True)],
    )
    bot.db.rss_search_knowledge_avec_synthese = AsyncMock(return_value=articles)
    bot.db.rss_dernier_knowledge_ts = AsyncMock(return_value=dernier_ts)
    return bot


def _article(titre, jours):
    return {
        "title": titre,
        "summary": "Dev Note: juggling around another hop-up.",
        "link": "https://store.steampowered.com/news/app/1172470/view/1",
        "published_ts": time.time() - jours * 86400,
    }


@pytest.mark.asyncio
async def test_le_bloc_dit_jusqu_ou_va_sa_connaissance():
    """L'ancre. Sans elle, « rien depuis » est une affirmation qu'il ne peut pas
    fonder — il ignore si le silence vient du jeu ou de sa propre base."""
    bot = _bot([_article("Overclocked Midseason", 56)],
               dernier_ts=time.time() - 6 * 86400)

    bloc = await _rss_knowledge_context(bot, "le wingman a eu un nerf ?")

    assert "6 jours" in bloc, "l'âge du patch le plus récent doit être annoncé"
    assert "récent" in bloc.lower()


@pytest.mark.asyncio
async def test_il_est_autorise_a_conclure_qu_il_ne_s_est_rien_passe():
    """L'autorisation. Trois extraits parlant du Wingman appellent une réponse
    sur le Wingman ; il faut lui dire explicitement qu'« aucun changement » est
    une réponse valable — et préférable à un vieux patch présenté comme actuel."""
    bot = _bot([_article("Overclocked Midseason", 56)],
               dernier_ts=time.time() - 6 * 86400)

    bloc = await _rss_knowledge_context(bot, "le wingman a eu un nerf ?")

    assert "rien" in bloc.lower() or "aucun" in bloc.lower()
    assert "actuel" in bloc.lower() or "récent" in bloc.lower()


@pytest.mark.asyncio
async def test_sans_ancre_le_bloc_reste_utilisable():
    """Base neuve, feed muet, requête en échec : l'absence d'ancre ne doit pas
    priver Wally des extraits qu'il a bel et bien."""
    bot = _bot([_article("Overclocked Midseason", 56)], dernier_ts=None)

    bloc = await _rss_knowledge_context(bot, "le wingman a eu un nerf ?")

    assert bloc and "Overclocked Midseason" in bloc


@pytest.mark.asyncio
async def test_une_base_qui_ne_sait_pas_dater_ne_bloque_pas_la_reponse():
    """La méthode d'ancrage peut manquer (instance plus ancienne) : on s'en
    passe plutôt que de perdre le bloc entier."""
    bot = _bot([_article("Overclocked Midseason", 56)])
    del bot.db.rss_dernier_knowledge_ts

    bloc = await _rss_knowledge_context(bot, "le wingman a eu un nerf ?")

    assert bloc and "Overclocked Midseason" in bloc
