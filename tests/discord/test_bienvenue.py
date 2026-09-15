from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import httpx

from bot.discord import bienvenue as bv

COMMU = 9


def _bot(guild_ids=(COMMU,), salon_id=20):
    salon = SimpleNamespace(id=20, name="discussions", send=AsyncMock())
    cfg = SimpleNamespace(salon_id=salon_id, guild_ids=list(guild_ids),
                          messages=["Bienvenue !"], gifs=["https://g/1.gif"])
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(bienvenue=cfg)))
    bot.get_channel = lambda cid: salon if cid == 20 else None
    return bot, salon


def _membre(bot_=False, guild=COMMU, uid=42):
    return SimpleNamespace(
        id=uid, bot=bot_, name="alice", mention=f"<@{uid}>",
        display_avatar=SimpleNamespace(url="https://cdn/a.png"),
        guild=SimpleNamespace(id=guild, system_channel=None),
    )


def _vue(salon):
    return salon.send.await_args.kwargs["view"]


def _textes(vue) -> list[str]:
    return [c.content for c in vue.walk_children() if isinstance(c, discord.ui.TextDisplay)]


def _vignette(vue) -> str | None:
    for c in vue.walk_children():
        if isinstance(c, discord.ui.Thumbnail):
            return c.media.url
    return None


def _medias(vue) -> list[str]:
    noms = []
    for c in vue.walk_children():
        if isinstance(c, discord.ui.MediaGallery):
            noms.extend(item.media.url for item in c.items)
    return noms


async def test_fiche_postee_et_acte_consigne(monkeypatch):
    bot, salon = _bot()
    monkeypatch.setattr(bv, "_recuperer_fact", AsyncMock(return_value=("A fact.", "Un fait.")))
    actes = []
    monkeypatch.setattr(bv, "note_act", actes.append)

    await bv.accueillir(bot, _membre())

    salon.send.assert_awaited_once()
    kwargs = salon.send.await_args.kwargs
    vue = kwargs["view"]
    textes = _textes(vue)
    assert any("BIENVENUE A alice" in t for t in textes)
    assert any("**français :** Un fait." in t for t in textes)
    assert any("**original :** A fact." in t for t in textes)
    assert any("Le Purgatoire" in t for t in textes)
    assert _vignette(vue) == "https://cdn/a.png"
    assert _medias(vue) == ["https://g/1.gif"]
    mentions = kwargs["allowed_mentions"]
    assert mentions.everyone is False
    assert mentions.roles is False
    assert actes and "alice" in actes[0]


async def test_allowed_mentions_ne_cible_que_le_membre(monkeypatch):
    bot, salon = _bot()
    monkeypatch.setattr(bv, "_recuperer_fact", AsyncMock(return_value=("A fact.", "Un fait.")))
    monkeypatch.setattr(bv, "note_act", lambda *_a, **_k: None)
    membre = _membre()

    await bv.accueillir(bot, membre)

    mentions = salon.send.await_args.kwargs["allowed_mentions"]
    assert list(mentions.users) == [membre]


async def test_guild_hors_liste_ou_bot_ignores(monkeypatch):
    monkeypatch.setattr(bv, "_recuperer_fact", AsyncMock(return_value=("x", "y")))
    for bot_, guild in ((False, 123), (True, COMMU)):
        bot, salon = _bot()
        await bv.accueillir(bot, _membre(bot_=bot_, guild=guild))
        salon.send.assert_not_awaited()


async def test_aucun_salon_disponible_avertit_et_ne_publie_rien(monkeypatch):
    monkeypatch.setattr(bv, "_recuperer_fact", AsyncMock(return_value=("x", "y")))
    bot, salon = _bot(salon_id=None)
    bot.get_channel = lambda cid: None
    membre = _membre()
    membre.guild.system_channel = None

    dits: list[str] = []
    jeton = bv.logger.add(lambda m: dits.append(str(m)), level="WARNING")
    try:
        await bv.accueillir(bot, membre)
    finally:
        bv.logger.remove(jeton)

    salon.send.assert_not_awaited()
    assert any(str(COMMU) in d for d in dits)


async def test_membre_sans_guild_ne_leve_pas(monkeypatch):
    """Un `member` incomplet (attribut `.guild` absent) est avalé, pas levé —
    tout, y compris le garde bot/guild, vit dans le try de `accueillir`."""
    bot, salon = _bot()
    monkeypatch.setattr(bv, "note_act", lambda *_a, **_k: None)
    membre = SimpleNamespace(id=1, bot=False, name="alice", mention="<@1>",
                             display_avatar=SimpleNamespace(url="https://cdn/a.png"))

    await bv.accueillir(bot, membre)  # ne doit pas lever

    salon.send.assert_not_awaited()


async def test_texte_externe_borne_a_1000_caracteres(monkeypatch):
    bot, salon = _bot()
    long_fact = "x" * 1500
    long_traduction = "y" * 1500
    monkeypatch.setattr(bv, "_recuperer_fact", AsyncMock(return_value=(long_fact, long_traduction)))
    monkeypatch.setattr(bv, "note_act", lambda *_a, **_k: None)

    await bv.accueillir(bot, _membre())

    textes = "\n".join(_textes(_vue(salon)))
    assert "x" * 1001 not in textes
    assert "y" * 1001 not in textes
    assert "…" in textes


async def test_replis_si_les_api_tombent():
    def panne(request):
        raise httpx.ConnectTimeout("x")
    async with httpx.AsyncClient(transport=httpx.MockTransport(panne)) as client:
        assert await bv._recuperer_fact(client) == (bv.FACT_INDISPONIBLE, bv.TRADUCTION_INDISPONIBLE)


async def test_traduction_seule_en_panne():
    def reponse(request):
        if "uselessfacts" in str(request.url):
            return httpx.Response(200, json={"text": "Cats sleep."})
        return httpx.Response(500)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reponse)) as client:
        assert await bv._recuperer_fact(client) == ("Cats sleep.", bv.TRADUCTION_INDISPONIBLE)


def _reponse_traduction(fact_body, *, translated="", statut=200, quota_finished=False):
    def reponse(request):
        if "uselessfacts" in str(request.url):
            return httpx.Response(200, json=fact_body)
        corps = {"responseData": {"translatedText": translated}, "responseStatus": statut}
        if quota_finished:
            corps["quotaFinished"] = True
        return httpx.Response(200, json=corps)
    return reponse


async def test_traduction_quota_epuise_bascule_en_repli():
    """MyMemory rend un 200 HTTP même quota épuisé — l'échec est DANS le corps."""
    handler = _reponse_traduction(
        {"text": "Cats sleep."},
        translated="MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY",
        statut=200,
        quota_finished=True,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await bv._recuperer_fact(client) == ("Cats sleep.", bv.TRADUCTION_INDISPONIBLE)


async def test_traduction_responsestatus_403_dans_un_corps_200_bascule_en_repli():
    handler = _reponse_traduction(
        {"text": "Cats sleep."}, translated="PLEASE SELECT TWO DISTINCT LANGUAGES", statut=403,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await bv._recuperer_fact(client) == ("Cats sleep.", bv.TRADUCTION_INDISPONIBLE)


async def test_traduction_responsestatus_en_chaine_egalement_detecte():
    """`responseStatus` peut être une chaîne (« 403 ») plutôt qu'un entier."""
    handler = _reponse_traduction(
        {"text": "Cats sleep."}, translated="PLEASE SELECT TWO DISTINCT LANGUAGES", statut="403",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await bv._recuperer_fact(client) == ("Cats sleep.", bv.TRADUCTION_INDISPONIBLE)


async def test_traduction_normale_est_bien_rendue():
    handler = _reponse_traduction({"text": "Cats sleep."}, translated="Les chats dorment.", statut=200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await bv._recuperer_fact(client) == ("Cats sleep.", "Les chats dorment.")
