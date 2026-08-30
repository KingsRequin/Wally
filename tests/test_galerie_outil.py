"""Wally peut relire les images qu'il a lui-même faites.

Une image générée est un acte de Wally au même titre qu'une phrase, et c'était
le seul de ses actes dont il ne gardait aucun accès : `gallery_images` n'était
lue que par le journal, le dashboard et la route galerie, jamais par un outil.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.tools.galerie_tool import run_gallery_tool


def _sql(jours_avant: int = 0) -> str:
    """Un `created_at` au format de la table : datetime SQL UTC, pas un epoch."""
    quand = datetime.now(timezone.utc) - timedelta(days=jours_avant)
    return quand.strftime("%Y-%m-%d %H:%M:%S")


def _image(**kw):
    base = {"id": "abc", "title": "Fuse en père Noël", "prompt": "Fuse déguisé",
            "username": "KingsRequin", "votes": 0, "created_at": _sql(3)}
    base.update(kw)
    return base


def _bot(images=None):
    bot = MagicMock()
    bot.db.get_gallery_images = AsyncMock(return_value=images if images is not None else [])
    return bot


async def _appel(bot, **args):
    return json.loads(await run_gallery_tool(bot, args))


async def test_le_sujet_devient_une_recherche():
    bot = _bot([_image()])

    await _appel(bot, sujet="pirate")

    assert bot.db.get_gallery_images.await_args.kwargs["search"] == "pirate"


async def test_sans_sujet_ce_sont_les_dernieres():
    """`search=""` ferait un LIKE '%%' inutile ; `None` dit « pas de filtre »."""
    bot = _bot([_image()])

    await _appel(bot)

    assert bot.db.get_gallery_images.await_args.kwargs["search"] is None


async def test_la_date_sql_est_lue_comme_une_date_pas_comme_un_nombre():
    """⚠️ `created_at` est un datetime SQL UTC : le lire comme un epoch daterait
    toutes les images de 1970."""
    bot = _bot([_image(created_at=_sql(3))])

    assert (await _appel(bot))["images"][0]["quand"] == "il y a 3 jours"


@pytest.mark.parametrize(("jours", "attendu"), [(0, "aujourd'hui"), (1, "hier")])
async def test_les_dates_proches_se_disent_en_mots(jours, attendu):
    bot = _bot([_image(created_at=_sql(jours))])

    assert (await _appel(bot))["images"][0]["quand"] == attendu


async def test_une_date_illisible_ne_fait_pas_tomber_l_outil():
    bot = _bot([_image(created_at="n'importe quoi")])

    assert (await _appel(bot))["images"][0]["quand"] == "à une date inconnue"


async def test_une_image_de_sa_propre_initiative_n_est_attribuee_a_personne():
    """`username` vaut « Wally » quand l'ACTE cognitif l'a générée : sans ce
    drapeau, il l'attribuerait à un utilisateur nommé Wally."""
    bot = _bot([_image(username="Wally")])

    fiche = (await _appel(bot))["images"][0]

    assert fiche["a_ta_propre_initiative"] is True
    assert "demandee_par" not in fiche


async def test_une_image_commandee_garde_son_demandeur():
    fiche = (await _appel(_bot([_image(username="KingsRequin")])))["images"][0]

    assert fiche["a_ta_propre_initiative"] is False
    assert fiche["demandee_par"] == "KingsRequin"


async def test_le_lien_est_l_url_publique(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    bot = _bot([_image(id="xyz")])

    lien = (await _appel(bot))["images"][0]["lien"]

    assert lien == "https://heywally.fr/api/public/gallery/xyz/image"


async def test_sans_base_publique_aucun_lien_bancal(monkeypatch):
    """Mieux pas de lien qu'un « /api/public/… » que personne ne peut ouvrir."""
    monkeypatch.setenv("WEB_BASE_URL", "")
    bot = _bot([_image()])

    assert "lien" not in (await _appel(bot))["images"][0]


async def test_le_prompt_est_borne():
    bot = _bot([_image(title=None, prompt="x" * 600)])

    assert len((await _appel(bot))["images"][0]["sujet"]) <= 140


async def test_les_votes_ne_sont_rendus_que_s_il_y_en_a():
    avec = (await _appel(_bot([_image(votes=3)])))["images"][0]
    sans = (await _appel(_bot([_image(votes=0)])))["images"][0]

    assert avec["votes"] == 3
    assert "votes" not in sans


async def test_rien_trouve_le_dit_pour_qu_il_n_invente_pas():
    reponse = await _appel(_bot([]), sujet="licorne")

    assert reponse["status"] == "vide"
    assert "licorne" in reponse["message"]


async def test_base_en_panne_le_dit_au_lieu_d_inventer():
    bot = _bot()
    bot.db.get_gallery_images.side_effect = RuntimeError("base fermée")

    reponse = await _appel(bot)

    assert reponse["status"] == "error"
    assert "invent" in reponse["message"]


async def test_sans_base_l_outil_le_dit():
    bot = MagicMock()
    bot.db = None

    assert (await _appel(bot))["status"] == "unavailable"


async def test_l_outil_est_offert_aux_deux_chats():
    from tests.test_parite_plateformes import _bot_avec_tout, _noms
    from bot.discord.handlers import build_chat_tools as discord
    from bot.twitch.handlers import build_chat_tools as twitch

    bot = _bot_avec_tout()
    assert "my_images" in _noms(await discord(bot, author_id="42"))
    assert "my_images" in _noms(await twitch(bot))
