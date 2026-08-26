"""Un fait extrait = un enregistrement. Sur les DEUX plateformes.

Le `_post_process` de Discord bouclait sur `llm_deltas["user_facts"]` et
écrivait un fait par appel. Celui de Twitch faisait `"\\n".join(...)` : N faits
rangés dans une seule ligne de la base.

Ce qu'un bloc collé coûte, et rien de tout ça n'est visible :

* aucun des faits ne peut être écrasé individuellement — une correction de
  l'intéressé ne peut rien remplacer, elle ne peut que s'ajouter à côté ;
* la recherche FTS remonte le bloc entier, donc N-1 faits hors sujet, qui
  mangent le budget de contexte ;
* la dédup travaille sur le bloc : deux blocs qui partagent trois faits sur
  quatre sont vus comme deux faits distincts.

Mesuré sur la base de prod au 2026-08-26 : **147 blocs Twitch contenant ≈346
faits**, contre **0 bloc côté Discord**. Une disparité de plateforme, celle que
les tests de parité du projet existent pour attraper.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _bot_factice(memory_add):
    """Le minimum pour que `_post_process` aille jusqu'à l'écriture des faits."""
    # `trust_delta` et `love_delta` sont lus AVANT les faits : sans eux le
    # `try` global avale un KeyError et rien n'est écrit — le test aurait
    # « passé » sur le mauvais chemin.
    deltas = {
        "user_facts": ["aime Apex", "joue Seer", "stream le matin"],
        "trust_delta": 0.0,
        "love_delta": 0.0,
    }
    emotion = MagicMock()
    emotion.get_state.return_value = {}
    emotion.process_message = AsyncMock(return_value=deltas)
    return SimpleNamespace(
        persona=SimpleNamespace(is_beloved=MagicMock(return_value=False)),
        emotion=emotion,
        memory=SimpleNamespace(add=memory_add),
        db=SimpleNamespace(
            update_trust_score=AsyncMock(),
            update_love_score=AsyncMock(),
        ),
        config=SimpleNamespace(bot=SimpleNamespace(love_decay_lambda=0.1)),
        conv_log=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("plateforme", ["twitch", "discord"])
async def test_trois_faits_font_trois_enregistrements(plateforme):
    from bot.discord.handlers import _post_process as post_discord
    from bot.twitch.handlers import _post_process as post_twitch

    ecrits: list[str] = []

    async def add(_plateforme, _uid, contenu, **_kw):
        ecrits.append(contenu)

    bot = _bot_factice(AsyncMock(side_effect=add))
    if plateforme == "twitch":
        await post_twitch(bot, "salut", "twitch", "42", 0.5, username="zed",
                          conv_channel="azrael_ttv")
    else:
        await post_discord(bot, "salut", "discord", "42", "guilde", 0.5,
                           display_name="zed")

    assert len(ecrits) == 3, f"{plateforme} : {len(ecrits)} écriture(s) pour 3 faits — {ecrits}"
    assert not any("\n" in e for e in ecrits), (
        f"{plateforme} : des faits sont collés dans un même enregistrement — {ecrits}"
    )
    assert set(ecrits) == {"aime Apex", "joue Seer", "stream le matin"}
