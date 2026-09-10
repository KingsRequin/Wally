"""Les clips du live republiés dans Discord (`bot/discord/clip_post.py`).

Le défaut visé n'est pas « le clip ne part pas », c'est « le clip part DEUX
fois ». L'overlay est éphémère, un salon Discord garde ce qu'on y met : la
mémoire des ids publiés doit donc survivre au rebuild, et il y en a plusieurs
par soirée de live.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.discord.clip_post import (
    MARQUEUR_VIGNETTE_ABSENTE,
    PublicationDesClips,
    carte_de_clip,
)

CLIP = {
    "id": "AwkwardHelplessSalamander",
    "title": "le 1v3 de la mort",
    "creator_name": "Taki",
    "url": "https://clips.twitch.tv/AwkwardHelplessSalamander",
    "thumbnail_url": "https://clips-media-assets2.twitch.tv/x-preview-480x272.jpg",
    "duration": 30.0,
}


class _FausseBase:
    """`bot_state` réduit à un dict — la seule part qui compte ici.

    Le `sleep(0)` n'est pas décoratif : sans point de suspension, deux
    `publier()` concurrents ne s'entrelaceraient JAMAIS et le test du verrou
    passerait aussi bien sans verrou. Une base réelle cède la main.
    """

    def __init__(self, etat=None):
        self.etat = dict(etat or {})

    async def get_state(self, key):
        await asyncio.sleep(0)
        return self.etat.get(key)

    async def set_state(self, key, value):
        await asyncio.sleep(0)
        self.etat[key] = value


def _publication(*, salon=None, db=None, salon_id=1414933470861332520):
    salon = salon if salon is not None else MagicMock(send=AsyncMock())
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=salon)
    config = MagicMock()
    config.discord.clips_channel_id = salon_id
    return PublicationDesClips(discord_bot=bot, db=db or _FausseBase(),
                               config=config), salon


# ── la carte ──────────────────────────────────────────────────────────────────

def _textes(vue: discord.ui.LayoutView) -> list[str]:
    return [i.content for i in vue.walk_children()
            if isinstance(i, discord.ui.TextDisplay)]


def test_la_carte_porte_le_titre_le_clippeur_et_le_lien():
    textes = _textes(carte_de_clip(CLIP))
    assert textes[0] == "## 🎬 le 1v3 de la mort"
    assert "Taki" in textes[1] and "30 s" in textes[1]
    assert CLIP["url"] in textes


def test_un_titre_en_markdown_ne_deforme_pas_la_carte():
    """Un titre de clip est du texte d'utilisateur : `**` ou `_` y passent."""
    textes = _textes(carte_de_clip({**CLIP, "title": "un *gros* _fail_"}))
    assert textes[0] == "## 🎬 un \\*gros\\* \\_fail\\_"


def test_la_vignette_en_cours_de_traitement_n_entre_pas_dans_la_carte():
    """Twitch sert cette image tant que le clip n'est pas transcodé. Discord met
    en cache ce qu'il proxyfie : postée, elle resterait DÉFINITIVEMENT vide."""
    en_cours = f"https://vod-secure.twitch.tv/_404/{MARQUEUR_VIGNETTE_ABSENTE}_320x180.png"
    vue = carte_de_clip({**CLIP, "thumbnail_url": en_cours})
    assert not any(isinstance(i, discord.ui.MediaGallery) for i in vue.walk_children())
    vue_ok = carte_de_clip(CLIP)
    assert any(isinstance(i, discord.ui.MediaGallery) for i in vue_ok.walk_children())


# ── les doublons ──────────────────────────────────────────────────────────────

async def test_un_clip_est_publie_une_fois():
    pub, salon = _publication()
    assert await pub.publier(CLIP) is True
    assert await pub.publier(CLIP) is False
    assert salon.send.await_count == 1


async def test_la_memoire_survit_au_redemarrage():
    """LE défaut visé. La `deque` de la veille meurt à chaque rebuild, et la
    fenêtre demandée à Twitch fait cinq minutes : sans la base, jusqu'à vingt
    clips repartaient dans le salon au boot suivant."""
    db = _FausseBase()
    pub, _ = _publication(db=db)
    await pub.publier(CLIP)

    apres_rebuild, salon = _publication(db=db)
    await apres_rebuild.charger()
    assert await apres_rebuild.publier(CLIP) is False
    salon.send.assert_not_awaited()


async def test_un_envoi_rate_ne_marque_PAS_le_clip_comme_publie():
    """Sinon une coupure réseau perd le clip pour de bon, alors qu'il repasse
    au tour suivant de la veille."""
    salon = MagicMock(send=AsyncMock(side_effect=discord.HTTPException(
        MagicMock(status=503), "boom")))
    db = _FausseBase()
    pub, _ = _publication(salon=salon, db=db)
    assert await pub.publier(CLIP) is False
    assert db.etat == {}


async def test_sans_salon_configure_rien_ne_part():
    """Le défaut est `None` : poster des clips dans un salon qu'on n'a pas
    désigné serait du bruit chez les autres."""
    pub, salon = _publication(salon_id=None)
    assert await pub.publier(CLIP) is False
    salon.send.assert_not_awaited()


async def test_un_salon_introuvable_ne_leve_pas():
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(
        MagicMock(status=404), "nope"))
    config = MagicMock()
    config.discord.clips_channel_id = 42
    pub = PublicationDesClips(discord_bot=bot, db=_FausseBase(), config=config)
    assert await pub.publier(CLIP) is False


async def test_une_memoire_illisible_ne_bloque_pas_le_boot():
    """Une écriture interrompue laisse du JSON tronqué. On repart à vide plutôt
    que d'emporter le démarrage."""
    db = _FausseBase({"clips_publies_discord": "{tronqué"})
    pub, _ = _publication(db=db)
    await pub.charger()
    assert await pub.publier(CLIP) is True


async def test_la_memoire_rangee_est_relisible():
    db = _FausseBase()
    pub, _ = _publication(db=db)
    await pub.publier(CLIP)
    assert json.loads(db.etat["clips_publies_discord"]) == [CLIP["id"]]


# ── le branchement sur la veille ──────────────────────────────────────────────

async def test_la_veille_publie_apres_l_overlay(monkeypatch):
    """« En même temps », mais pas AVANT : `announce_clip` attend que Twitch ait
    transcodé le clip, et c'est cette attente qui garantit une vignette réelle."""
    from bot.twitch import clip_announce

    ordre: list[str] = []

    async def _annonce(narrateur, api, clip):
        ordre.append("overlay")

    monkeypatch.setattr(clip_announce, "announce_clip", _annonce)

    publication = MagicMock()
    publication.publier = AsyncMock(side_effect=lambda c: ordre.append("discord"))
    narrateur = MagicMock(is_active=MagicMock(return_value=True))
    discord_bot = MagicMock(overlay_narrator=narrateur)
    twitch_bot = MagicMock()
    twitch_bot.twitch_api.get_recent_clips = AsyncMock(return_value=[CLIP])

    veille = clip_announce.VeilleDesClips(
        discord_bot=discord_bot, twitch_bot=twitch_bot, publication=publication,
    )
    await veille.un_tour()
    await asyncio.gather(*list(veille._taches))
    assert ordre == ["overlay", "discord"]


async def test_le_live_coupe_pendant_l_attente_publie_quand_meme(monkeypatch):
    """L'overlay n'a plus personne devant lui ; le salon Discord si."""
    from bot.twitch import clip_announce

    async def _annonce_interrompue(narrateur, api, clip):
        return  # `announce_clip` sort tôt quand le live s'arrête

    monkeypatch.setattr(clip_announce, "announce_clip", _annonce_interrompue)
    publication = MagicMock(publier=AsyncMock())
    veille = clip_announce.VeilleDesClips(
        discord_bot=MagicMock(), twitch_bot=MagicMock(), publication=publication,
    )
    await veille._montrer_puis_publier(MagicMock(), CLIP)
    publication.publier.assert_awaited_once_with(CLIP)


async def test_une_annonce_overlay_en_erreur_est_DITE_et_n_arrete_pas_discord(monkeypatch):
    """La tâche n'est attendue par personne : sans capture, l'exception part dans
    le « Task exception was never retrieved » d'asyncio, que loguru ne
    journalise pas. L'overlay reste noir et rien ne le dit."""
    from bot.twitch import clip_announce

    async def _boum(narrateur, api, clip):
        raise RuntimeError("overlay mort")

    monkeypatch.setattr(clip_announce, "announce_clip", _boum)
    publication = MagicMock(publier=AsyncMock())
    veille = clip_announce.VeilleDesClips(
        discord_bot=MagicMock(), twitch_bot=MagicMock(), publication=publication,
    )
    dits: list[str] = []
    jeton = clip_announce.logger.add(lambda m: dits.append(str(m)), level="WARNING")
    try:
        await veille._montrer_puis_publier(MagicMock(), CLIP)
    finally:
        clip_announce.logger.remove(jeton)
    assert any("overlay mort" in d for d in dits)
    publication.publier.assert_awaited_once_with(CLIP)


# ── deux écrivains sur la même clé ────────────────────────────────────────────

async def test_un_id_ecrit_par_un_TIERS_survit_a_une_publication():
    """`scripts/rattraper_clips_discord.py` écrit sur la MÊME clé. Écraser avec
    la seule mémoire de ce process effacerait son travail au premier clip du
    live, et les clips rattrapés repartiraient en doublon."""
    db = _FausseBase()
    pub, _ = _publication(db=db)
    await pub.charger()
    db.etat["clips_publies_discord"] = json.dumps(["rattrape-a", "rattrape-b"])

    await pub.publier(CLIP)
    ranges = json.loads(db.etat["clips_publies_discord"])
    assert ranges == ["rattrape-a", "rattrape-b", CLIP["id"]]
    # ...et ce process a APPRIS le rattrapage : il ne republiera pas ces deux-là
    assert await pub.publier({**CLIP, "id": "rattrape-a"}) is False
