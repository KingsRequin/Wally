"""Politique de la génération d'image à l'initiative de Wally.

Ce qui compte ici, c'est le REFUS : c'est lui qui borne une dépense réelle, et
c'est lui qui, motivé, empêche Wally de redemander la même image à chaque tick.
"""
import time

import pytest

from bot.config import ImageGenerationConfig
from bot.core.image_initiative import AUTEUR_PAR_DEFAUT, ImageInitiative

SHITPOST = "938504877464768603"
MEMES = "875450811151450143"
NOMS = {SHITPOST: "#shitpost", MEMES: "#memes", "111": "#discussions"}


class _Db:
    def __init__(self, aujourd_hui=0, dernier=None, casse=False):
        self.aujourd_hui = aujourd_hui
        self.dernier = dernier
        self.casse = casse

    async def get_user_image_count_today(self, user_id):
        if self.casse:
            raise RuntimeError("base fermée")
        return self.aujourd_hui

    async def get_last_image_ts(self, user_id):
        if self.casse:
            raise RuntimeError("base fermée")
        return self.dernier


def _config(**kw):
    base = dict(
        autonomous_enabled=True,
        autonomous_channel_ids=[SHITPOST, MEMES],
        autonomous_daily_limit=3,
        autonomous_cooldown_minutes=90,
    )
    base.update(kw)
    return type("C", (), {"image_generation": ImageGenerationConfig(**base)})()


def _initiative(db=None, **kw):
    return ImageInitiative(_config(**kw), db or _Db(), channel_names=NOMS,
                           auteur_id="discord:7")


def test_les_ids_yaml_en_int_sont_normalises():
    """YAML rend un id Discord en int : sans normalisation, AUCUN salon ne
    correspondrait au `channel_id` (une chaîne) décidé par le modèle."""
    ini = _initiative(autonomous_channel_ids=[938504877464768603])
    assert list(ini.salons()) == [SHITPOST]


def test_les_salons_portent_le_nom_de_lannuaire():
    assert _initiative().salons() == {SHITPOST: "#shitpost", MEMES: "#memes"}


def test_un_salon_inconnu_de_lannuaire_reste_autorise():
    """La config autorise, l'annuaire ne fait que nommer."""
    ini = _initiative(autonomous_channel_ids=["999"])
    assert ini.salons() == {"999": "999"}
    assert ini.enabled is True


def test_capacite_eteinte_sans_salon():
    assert _initiative(autonomous_channel_ids=[]).enabled is False


def test_capacite_eteinte_quand_desactivee():
    assert _initiative(autonomous_enabled=False).enabled is False


@pytest.mark.asyncio
async def test_salon_autorise_passe():
    assert await _initiative().refus(SHITPOST) == ""


@pytest.mark.asyncio
async def test_salon_interdit_refuse_et_nomme_les_salons_ouverts():
    motif = await _initiative().refus("111")
    assert "interdit" in motif
    assert "#shitpost" in motif


@pytest.mark.asyncio
async def test_plafond_du_jour():
    motif = await _initiative(_Db(aujourd_hui=3)).refus(SHITPOST)
    assert "plafond du jour" in motif and "3/3" in motif


@pytest.mark.asyncio
async def test_plafond_du_jour_desactivable():
    ini = _initiative(_Db(aujourd_hui=99), autonomous_daily_limit=-1)
    assert await ini.refus(SHITPOST) == ""


@pytest.mark.asyncio
async def test_delai_entre_deux_images():
    """Le délai se lit en BASE : une image postée avant un rebuild compte
    toujours, là où un compteur en RAM serait reparti à zéro."""
    ini = _initiative(_Db(dernier=time.time() - 600))
    motif = await ini.refus(SHITPOST)
    assert "trop tôt" in motif


@pytest.mark.asyncio
async def test_delai_ecoule():
    ini = _initiative(_Db(dernier=time.time() - 91 * 60))
    assert await ini.refus(SHITPOST) == ""


@pytest.mark.asyncio
async def test_quota_illisible_refuse_au_lieu_douvrir():
    """Une base muette ne doit pas lever le plafond : c'est la seule garde de coût."""
    motif = await _initiative(_Db(casse=True)).refus(SHITPOST)
    assert "quota" in motif


@pytest.mark.asyncio
async def test_desactivation_refuse_meme_un_salon_liste():
    motif = await _initiative(autonomous_enabled=False).refus(SHITPOST)
    assert "désactivée" in motif


def test_auteur_par_defaut_quand_le_bot_na_pas_encore_didentite():
    ini = ImageInitiative(_config(), _Db(), channel_names=NOMS, auteur_id=lambda: "")
    assert ini.auteur_id() == AUTEUR_PAR_DEFAUT


def test_cadence_texte_dit_les_deux_bornes():
    texte = _initiative().cadence_texte()
    assert "3 image(s) par jour" in texte and "90 minutes" in texte
