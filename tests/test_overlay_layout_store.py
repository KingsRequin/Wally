"""Le rangement du layout dans `bot_state`.

Patron du `_State` simulé repris de `tests/test_overlay_etat_partie_persist.py`.
"""
import json

import pytest

from bot.core.overlay_layout import ELEMENTS, layout_par_defaut
from bot.core.overlay_layout_store import (
    LAYOUT_KEY, charger_layout, enregistrer_layout,
)


class _State:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


@pytest.mark.asyncio
async def test_charger_sans_rien_en_base_rend_les_defauts():
    assert await charger_layout(_State()) == layout_par_defaut()


@pytest.mark.asyncio
async def test_charger_un_json_illisible_rend_les_defauts():
    """Une écriture interrompue laisse du JSON tronqué. L'overlay doit quand
    même s'afficher."""
    db = _State({LAYOUT_KEY: '{"scenes": [{"slug": "jeu"'})
    assert await charger_layout(db) == layout_par_defaut()


@pytest.mark.asyncio
async def test_charger_sans_base_rend_les_defauts():
    """`db=None` arrive avant la connexion du bot : la page ne doit pas
    attendre pour s'afficher."""
    assert await charger_layout(None) == layout_par_defaut()


@pytest.mark.asyncio
async def test_enregistrer_puis_recharger_conserve_les_positions():
    db = _State()
    layout = layout_par_defaut()
    layout["scenes"][0]["elements"]["avatar"]["x"] = 12.5
    await enregistrer_layout(db, layout)
    relu = await charger_layout(db)
    assert relu["scenes"][0]["elements"]["avatar"]["x"] == 12.5


@pytest.mark.asyncio
async def test_enregistrer_valide_avant_de_ranger():
    """Ce qui entre est fusionné : une valeur hors bornes n'atteint pas la
    base, sinon elle y resterait jusqu'au prochain enregistrement."""
    db = _State()
    layout = layout_par_defaut()
    layout["scenes"][0]["elements"]["avatar"]["x"] = 5000.0
    rendu = await enregistrer_layout(db, layout)
    assert rendu["scenes"][0]["elements"]["avatar"]["x"] == 100.0
    assert json.loads(db.rows[LAYOUT_KEY])["scenes"][0]["elements"]["avatar"]["x"] == 100.0


@pytest.mark.asyncio
async def test_enregistrer_sans_base_ne_leve_pas():
    """Le panneau doit répondre même si la base est absente — il rend alors ce
    qu'il a compris, sans prétendre l'avoir rangé."""
    assert await enregistrer_layout(None, layout_par_defaut()) == layout_par_defaut()


@pytest.mark.asyncio
async def test_toutes_les_cles_delements_survivent_a_un_aller_retour():
    db = _State()
    await enregistrer_layout(db, layout_par_defaut())
    relu = await charger_layout(db)
    for scene in relu["scenes"]:
        assert set(scene["elements"]) == set(ELEMENTS)


# ── La graine des réglages de la galerie (2026-08-21) ───────────────────────
#
# Les quatre réglages d'affichage du widget `image` vivaient dans `config.yaml`
# (`overlay_image`), GLOBALEMENT. Deux autorités sur la même question, c'est la
# signature de défaut que ce dépôt traque. Ils passent dans le layout, où ils se
# règlent PAR SCÈNE comme ceux de tous les autres widgets.

class _ConfigImage:
    """Ce que `config.overlay_image` expose, réduit à ce que la graine lit."""

    def __init__(self, **kw):
        self.display_duration = kw.get("display_duration", 15)
        self.animation_in = kw.get("animation_in", "fadeIn")
        self.animation_out = kw.get("animation_out", "fadeOut")
        self.animation_duration = kw.get("animation_duration", 1.0)


class _Config:
    def __init__(self, image=None):
        self.overlay_image = image


@pytest.mark.asyncio
async def test_la_graine_recopie_les_reglages_du_fichier_dans_les_trois_scenes():
    from bot.core.overlay_layout_store import semer_reglages_image
    db = _State()
    cfg = _Config(_ConfigImage(display_duration=7, animation_in="bounceInLeft",
                               animation_out="bounceOutLeft",
                               animation_duration=1.4))
    assert await semer_reglages_image(db, cfg) is True
    layout = await charger_layout(db)
    for scene in layout["scenes"]:
        img = scene["elements"]["image"]
        assert img["duree"] == 7.0
        assert img["anim_entree"] == "bounceInLeft"
        assert img["anim_sortie"] == "bounceOutLeft"
        assert img["anim_duree"] == 1.4


@pytest.mark.asyncio
async def test_la_graine_ne_repousse_pas_par_dessus_un_reglage_fait_a_la_main():
    """Sans le drapeau, chaque boot écraserait le choix du streamer avec la
    valeur d'un fichier qu'il ne regarde plus — et il ne pourrait JAMAIS rien
    régler durablement."""
    from bot.core.overlay_layout_store import semer_reglages_image
    db = _State()
    cfg = _Config(_ConfigImage(display_duration=7))
    await semer_reglages_image(db, cfg)

    layout = await charger_layout(db)
    layout["scenes"][0]["elements"]["image"]["duree"] = 20.0
    await enregistrer_layout(db, layout)

    # Second boot : la graine a déjà été semée, elle ne refait rien.
    assert await semer_reglages_image(db, cfg) is False
    assert (await charger_layout(db))["scenes"][0]["elements"]["image"]["duree"] == 20.0


@pytest.mark.asyncio
async def test_la_graine_ne_fait_pas_dater_une_publication():
    """`enregistrer_layout` pose la date de mise à l'antenne. La graine n'est
    PAS une publication : le panneau annoncerait « à l'antenne depuis 17:22 »
    pour une migration que personne n'a demandée."""
    from bot.core.overlay_layout_store import MAJ_KEY, semer_reglages_image
    db = _State()
    await semer_reglages_image(db, _Config(_ConfigImage(display_duration=7)))
    assert MAJ_KEY not in db.rows


@pytest.mark.asyncio
async def test_une_valeur_aberrante_du_fichier_est_bornee_comme_le_reste():
    """Le fichier peut porter n'importe quoi — il s'édite à la main. Une
    animation retirée d'animate.css ou une durée absurde reprend son défaut,
    comme tout ce qui entre dans ce modèle."""
    from bot.core.overlay_layout_store import semer_reglages_image
    db = _State()
    await semer_reglages_image(db, _Config(_ConfigImage(
        animation_in="nawak", display_duration=99999, animation_duration=-3)))
    img = (await charger_layout(db))["scenes"][0]["elements"]["image"]
    assert img["anim_entree"] == "glitch"
    assert img["duree"] == 180.0
    assert img["anim_duree"] == 0.1


@pytest.mark.asyncio
async def test_sans_section_dans_le_fichier_la_graine_se_marque_quand_meme_faite():
    """Sinon on rouvrirait la question à chaque boot, pour rien."""
    from bot.core.overlay_layout_store import semer_reglages_image
    db = _State()
    assert await semer_reglages_image(db, _Config(None)) is False
    assert await semer_reglages_image(db, _Config(_ConfigImage())) is False


@pytest.mark.asyncio
async def test_la_graine_ne_touche_a_rien_dautre_que_la_galerie():
    """Une migration qui déborde sur les trente-six autres éléments serait
    invisible et irréversible."""
    from bot.core.overlay_layout_store import semer_reglages_image
    db = _State()
    avant = layout_par_defaut()
    await enregistrer_layout(db, avant)
    await semer_reglages_image(db, _Config(_ConfigImage(display_duration=7)))
    apres = await charger_layout(db)
    for sa, sb in zip(avant["scenes"], apres["scenes"]):
        for cle in ELEMENTS:
            if cle == "image":
                continue
            assert sa["elements"][cle] == sb["elements"][cle], cle


@pytest.mark.asyncio
async def test_la_graine_ne_leve_jamais_meme_sans_base():
    from bot.core.overlay_layout_store import semer_reglages_image
    assert await semer_reglages_image(None, _Config(_ConfigImage())) is False


def test_le_dashboard_nenvoie_plus_les_reglages_daffichage_de_la_galerie():
    """Le doublon d'autorité est refermé : ces quatre-là vivent dans le layout.
    Les laisser dans l'onglet Paramètres enverrait la valeur d'un champ disparu
    — donc `NaN` — et écraserait ce que la scène porte."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
          / "app.js").read_text(encoding="utf-8")
    for champ in ("display_duration", "animation_in", "animation_out",
                  "animation_duration"):
        assert champ not in js, f"`{champ}` part encore du dashboard"
    # `enabled`, `command` et `random_filter` restent : ils ne parlent pas de
    # mise en scène.
    assert "random_filter" in js


def test_le_dashboard_ne_promet_plus_de_regler_les_animations():
    """Un TEXTE qui annonce « animation entrée/sortie configurable ci-dessous »
    survit au retrait des champs qu'il décrit. La promesse devient fausse sans
    que rien ne le signale — la définition même du réglage qui ment, et ce
    chantier existe pour fermer celui-là."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
          / "app.js").read_text(encoding="utf-8")
    assert "configurable ci-dessous" not in js
    assert "Animation entrée" not in js


def test_le_dashboard_ne_garde_aucune_liste_danimations():
    """`ANIMATE_CSS_IN`/`OUT` étaient la seconde liste recopiée en JavaScript
    que ce chantier existe pour supprimer. Leurs seuls lecteurs étaient les deux
    menus de la galerie, partis dans « Mise en scène » — où le catalogue vient
    du serveur."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
          / "app.js").read_text(encoding="utf-8")
    assert "ANIMATE_CSS" not in js


def test_la_graine_est_semee_au_boot_et_pas_sur_le_chemin_public():
    """`charger_layout` est appelé à chaque ouverture de page et à chaque
    redimensionnement de la source OBS. Y poser la migration coûterait une
    lecture de plus à chaque fois, et deux requêtes simultanées pourraient la
    jouer deux fois."""
    from pathlib import Path
    racine = Path(__file__).resolve().parents[1]
    main = (racine / "bot" / "main.py").read_text(encoding="utf-8")
    assert "semer_reglages_image(db, config)" in main
    store = (racine / "bot" / "core" / "overlay_layout_store.py").read_text(
        encoding="utf-8")
    charger = store[store.index("async def charger_layout"):
                    store.index("async def enregistrer_layout")]
    assert "semer" not in charger
