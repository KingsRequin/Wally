"""Depuis quand une personne suit la chaîne — la donnée vient de Twitch.

Le besoin est sorti des traces réelles : « wally je follow la chaine dpuis
quand? » → « Pas de date de follow dans mon dossier, j'ai pas accès à ça ».
C'était faux : le scope `moderator:read:followers` était déjà sur le token du
bot, posé pour l'EventSub `channel.follow v2`.

Ces tests visent surtout les DEUX faux négatifs silencieux que la fonctionnalité
peut produire — dire « tu ne suis pas » à quelqu'un qui suit. Ils sont plus
importants que le chemin nominal : un chiffre faux se répète en direct devant le
chat, et rien dans les logs ne le signale.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.core.follow_tool import _duree_depuis, api_twitch, run_follow_tool


def _api(**kw):
    return SimpleNamespace(
        get_follow_date=AsyncMock(**{k: v for k, v in kw.items() if k == "return_value"}),
        get_broadcaster_id=AsyncMock(return_value=kw.get("resolu")),
    )


def _bot(api):
    return SimpleNamespace(twitch_api=api)


# ── Les trois retours de l'API sont TROIS phrases différentes ────────────────

async def test_suit_depuis_une_date():
    api = _api(return_value={"followed_at": "2025-03-04T10:00:00Z"})
    out = json.loads(await run_follow_tool(
        _bot(api), {}, platform="twitch", user_id="123", author="lilio"))
    assert out["status"] == "ok"
    assert out["followed_at"] == "2025-03-04T10:00:00Z"
    assert out["user"] == "lilio"
    api.get_follow_date.assert_awaited_once_with("123")


async def test_ne_suit_pas():
    out = json.loads(await run_follow_tool(
        _bot(_api(return_value={})), {}, platform="twitch",
        user_id="123", author="lilio"))
    assert out["status"] == "not_following"


async def test_api_muette_ne_devient_JAMAIS_un_ne_suit_pas():
    """Le faux négatif le plus cher : un 500 de Helix qui se lit « tu me suis
    même pas » devant le chat. `None` et `{}` doivent rester distincts jusqu'au
    bout de la chaîne, pas seulement dans le client HTTP."""
    out = json.loads(await run_follow_tool(
        _bot(_api(return_value=None)), {}, platform="twitch",
        user_id="123", author="lilio"))
    assert out["status"] == "error"
    assert "vérifier" in out["message"]
    assert "not_following" not in json.dumps(out)


# ── L'identité : un id Discord n'est pas un id Twitch ────────────────────────

async def test_chemin_vocal_sans_pseudo_ne_va_PAS_interroger_helix():
    """En vocal, `user_id` est un snowflake Discord. L'envoyer à Helix rendrait
    une liste vide — donc « ne suit pas » — pour quelqu'un qui suit depuis deux
    ans. On refuse avant l'appel plutôt que de répondre faux."""
    api = _api(return_value={})
    out = json.loads(await run_follow_tool(
        _bot(api), {}, platform="discord",
        user_id="610550333042589752", author="KingsRequin"))
    assert out["status"] == "need_user"
    api.get_follow_date.assert_not_awaited()


async def test_pseudo_explicite_marche_depuis_n_importe_quelle_plateforme():
    api = _api(return_value={"followed_at": "2024-01-01T00:00:00Z"}, resolu="777")
    out = json.loads(await run_follow_tool(
        _bot(api), {"user": "@Lilio___"}, platform="discord",
        user_id="610550333042589752", author="KingsRequin"))
    assert out["status"] == "ok"
    api.get_broadcaster_id.assert_awaited_once_with("lilio___")
    api.get_follow_date.assert_awaited_once_with("777")


async def test_pseudo_inconnu():
    api = _api(return_value={}, resolu=None)
    out = json.loads(await run_follow_tool(
        _bot(api), {"user": "nexistepas"}, platform="twitch",
        user_id="1", author="a"))
    assert out["status"] == "not_found"
    api.get_follow_date.assert_not_awaited()


async def test_sans_api_pas_de_crash():
    out = json.loads(await run_follow_tool(
        SimpleNamespace(), {}, platform="twitch", user_id="1", author="a"))
    assert out["status"] == "unavailable"


# ── La durée est calculée ICI, pas par le modèle ─────────────────────────────

@pytest.mark.parametrize("jours, attendu", [
    (0, "0 jour(s)"), (12, "12 jour(s)"), (90, "3 mois"),
    (400, "1 an(s) et 1 mois"), (800, "2 an(s) et 2 mois"),
])
def test_duree_depuis(jours, attendu):
    iso = (datetime.now(timezone.utc) - timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _duree_depuis(iso) == attendu


def test_duree_depuis_accepte_un_offset_explicite():
    """Helix rend du `Z`, mais un `+00:00` ne doit pas lever."""
    assert _duree_depuis("2020-01-01T00:00:00+00:00").endswith("mois")


# ── Le catalogue : maison seulement ─────────────────────────────────────────

async def test_offert_sur_la_maison_pas_chez_un_invite():
    from bot.twitch.handlers import build_chat_tools

    nu = SimpleNamespace(
        config=SimpleNamespace(bot=SimpleNamespace(owner_discord_id="1")),
        twitch_api=object(),
    )
    maison = {t["function"]["name"] for t in await build_chat_tools(nu, overlay=True)}
    invite = {t["function"]["name"] for t in await build_chat_tools(nu, overlay=False)}
    assert "follow_date" in maison
    # Chez un invité, « depuis quand tu me suis » parlerait de SA chaîne — et le
    # scope ne porte que sur la maison de toute façon.
    assert "follow_date" not in invite


async def test_offert_aussi_sur_discord():
    """La parité n'est pas décorative : la communauté est la même des deux
    côtés, et l'outil prend un pseudo — rien n'y dépend de la plateforme."""
    from bot.discord.handlers import build_chat_tools as outils_discord

    nu = SimpleNamespace(
        config=SimpleNamespace(bot=SimpleNamespace(owner_discord_id="1")),
        twitch_api=object(),
    )
    noms = {t["function"]["name"] for t in await outils_discord(nu, author_id="42")}
    assert "follow_date" in noms


def test_api_vue_depuis_discord_passe_par_le_bot_twitch():
    """`WallyDiscord` n'a pas `twitch_api` : sans ce second chemin, l'outil
    disparaîtrait du catalogue Discord au montage, en silence."""
    faux_api = object()
    assert api_twitch(SimpleNamespace(twitch_api=faux_api)) is faux_api
    assert api_twitch(SimpleNamespace(
        _twitch_bot=SimpleNamespace(twitch_api=faux_api))) is faux_api
    assert api_twitch(SimpleNamespace()) is None


async def test_l_executeur_le_route():
    """Un outil au catalogue mais absent de `_impl` est un outil mort : le
    modèle l'appelle, l'exécuteur ne le connaît pas."""
    from bot.twitch.handlers import make_tool_executor

    ex = make_tool_executor(SimpleNamespace(), platform="twitch", user_id="1",
                            author="a", channel="c")
    out = json.loads(await ex("follow_date", "{}"))
    assert out["status"] == "unavailable"  # routé, puis refusé faute d'API
