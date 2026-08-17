"""Ce qu'il croit avoir affiché doit correspondre à ce qui s'est produit.

C'est la leçon de « il ne savait pas qu'il affichait les bingos », dans l'autre
sens : un widget masqué sur TOUTES les scènes ne doit ni lui être proposé, ni le
laisser annoncer « c'est à l'écran » s'il le demande quand même.

Masqué sur une SEULE scène, il reste utilisable — Wally ignore laquelle est à
l'antenne, et c'est la page qui filtre. Seul un masquage partout vaut « tu ne
peux pas t'en servir ».

Deux pièges, et le second est celui qui rendrait la garde inutile en silence :

  1. **Les alias.** L'outil nomme `goal` et `uptime` ; la page ne connaît ni
     l'un ni l'autre — `goal` est publié en `gauge`, `uptime` en `counter`. Le
     modèle suit la page, donc masquer la jauge doit retirer l'objectif.
  2. **Ne pas savoir ne vaut pas interdire.** Base absente, layout illisible,
     cache jamais chargé : Wally garde tous ses outils. Une garde qui se
     referme sur son propre silence priverait le live de tout l'overlay pour
     une lecture SQLite ratée.

Ces tests échouent sur le code d'avant : `widgets_disponibles` n'existait pas et
`overlay_narrator.py` ne connaissait pas le layout (zéro occurrence).
"""
import json
from unittest.mock import AsyncMock

import pytest

from bot.core.overlay_layout import layout_par_defaut
from bot.core.overlay_layout_store import LAYOUT_KEY
from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import (
    OVERLAY_TOOL_SPEC,
    OverlayNarrator,
    spec_overlay_filtree,
    widgets_disponibles,
)


class _State:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


def _base(masque_partout=(), visible_sur_une=()):
    """Une base porteuse d'un layout.

    Les scènes sont désignées par leur RANG et non par leur slug : ceux du
    modèle livré sont `stream-starting`, `en-jeu`, `fin`, l'owner les renomme
    (en production : `start`, `jeu`, `end`), et un test qui les recopie casse au
    premier renommage sans rien dire du comportement.
    """
    layout = layout_par_defaut()
    scenes = layout["scenes"]
    for cle in masque_partout:
        for scene in scenes:
            scene["elements"][cle]["hidden"] = True
    for cle in visible_sur_une:
        for scene in scenes[1:]:
            scene["elements"][cle]["hidden"] = True
    return _State({LAYOUT_KEY: json.dumps(layout)})


def _narrateur(db):
    return OverlayNarrator(
        OverlayFeed(), AsyncMock(), lambda: True, db=db,
        stream_status=lambda: {"live": True, "started_at": "2026-08-15T07:00:00Z"},
    )


# ── Ce qui est disponible ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_masque_dans_une_seule_scene_reste_disponible():
    """Le bingo masqué sur deux scènes sur trois sert quand même sur la
    troisième — Wally ignore laquelle est à l'antenne, c'est la page qui
    filtre."""
    assert "bingo" in await widgets_disponibles(_base(visible_sur_une=["bingo"]))


@pytest.mark.asyncio
async def test_masque_partout_devient_indisponible():
    db = _base(masque_partout=["bingo"])
    assert "bingo" not in await widgets_disponibles(db)


@pytest.mark.asyncio
async def test_sans_layout_tout_est_disponible():
    """Une base vide ne doit pas priver Wally de ses outils."""
    assert "bingo" in await widgets_disponibles(_State())
    assert "bingo" in await widgets_disponibles(None)


@pytest.mark.asyncio
async def test_masquer_la_jauge_retire_aussi_lobjectif():
    """`goal` est publié en `gauge` : le modèle ne connaît que la seconde. Sans
    la table d'alias, l'objectif resterait proposé jauge masquée partout — et
    Wally annoncerait un objectif que personne ne voit."""
    db = _base(masque_partout=["gauge"])
    dispo = await widgets_disponibles(db)
    assert "gauge" not in dispo and "goal" not in dispo


@pytest.mark.asyncio
async def test_masquer_le_compteur_retire_aussi_luptime():
    db = _base(masque_partout=["counter"])
    dispo = await widgets_disponibles(db)
    assert "counter" not in dispo and "uptime" not in dispo


@pytest.mark.asyncio
async def test_un_widget_hors_du_modele_reste_disponible():
    """`clip` et `planning` sont dans l'enum de l'outil ; tout ce que le modèle
    ne décrit pas ne doit pas disparaître par omission."""
    dispo = await widgets_disponibles(_base())
    for cle in OverlayNarrator._WIDGETS:
        assert cle in dispo, cle


# ── L'enum que voit le LLM ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lenum_de_loutil_perd_le_widget_masque_partout():
    db = _base(masque_partout=["dice"])
    spec = await spec_overlay_filtree(db)
    enum = spec["function"]["parameters"]["properties"]["widget"]["enum"]
    assert "dice" not in enum and "bingo" in enum


@pytest.mark.asyncio
async def test_la_spec_dorigine_nest_jamais_modifiee():
    """Elle est importée au niveau module par les deux plateformes : la muter
    ferait disparaître un widget pour TOUT LE MONDE, définitivement, jusqu'au
    prochain redémarrage."""
    avant = list(
        OVERLAY_TOOL_SPEC["function"]["parameters"]["properties"]["widget"]["enum"])
    db = _base(masque_partout=["dice"])
    await spec_overlay_filtree(db)
    apres = OVERLAY_TOOL_SPEC["function"]["parameters"]["properties"]["widget"]["enum"]
    assert apres == avant


@pytest.mark.asyncio
async def test_sans_base_la_spec_reste_entiere():
    spec = await spec_overlay_filtree(None)
    enum = spec["function"]["parameters"]["properties"]["widget"]["enum"]
    assert "dice" in enum and "bingo" in enum


# ── Le refus à l'exécution ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_widget_masque_partout_est_refuse_pas_annonce():
    """Une action différée passe à côté de l'enum : le refus doit venir de
    l'EXÉCUTION, sinon il annonce « c'est à l'écran » sans que rien ne le soit."""
    n = _narrateur(_base(masque_partout=["dice"]))
    await n.rafraichir_widgets_disponibles()
    assert n.show_widget("dice", "regardez ça") is None


@pytest.mark.asyncio
async def test_un_widget_visible_quelque_part_saffiche():
    """Le pendant du test précédent : sans lui, « rend toujours None » passerait
    pour un correctif."""
    n = _narrateur(_base(visible_sur_une=["dice"]))
    await n.rafraichir_widgets_disponibles()
    assert n.show_widget("dice", "regardez ça") is not None


@pytest.mark.asyncio
async def test_lobjectif_masque_est_refuse_sous_son_nom_doutil():
    """Il arrive par `goal`, il se rend en `gauge` : le refus doit faire la
    correspondance, sinon la garde ne l'attrape jamais."""
    n = _narrateur(_base(masque_partout=["gauge"]))
    await n.rafraichir_widgets_disponibles()
    assert n.show_widget("gauge", "ça monte") is None


def test_un_cache_jamais_charge_ne_refuse_rien():
    """LE garde-fou. Base absente, lecture ratée, narrateur construit sans `db` :
    ne pas savoir ne vaut pas interdire. Refuser ici priverait le live de tout
    l'overlay pour une requête SQLite manquée."""
    n = _narrateur(None)
    assert n.show_widget("dice", "regardez ça") is not None


@pytest.mark.asyncio
async def test_un_layout_illisible_ne_prive_de_rien():
    n = _narrateur(_State({LAYOUT_KEY: "{ceci n'est pas du json"}))
    await n.rafraichir_widgets_disponibles()
    assert n.show_widget("dice", "regardez ça") is not None


# ── Le câblage ──────────────────────────────────────────────────────────────
#
# La garde peut être parfaite et ne servir à rien : il suffit que les
# adaptateurs continuent d'ajouter la spec d'origine. C'est le défaut le plus
# facile à ne pas voir — tout est vert, et l'enum part entier.

@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["bot.discord.handlers", "bot.twitch.handlers"])
async def test_les_deux_plateformes_demandent_la_spec_a_jour(module, monkeypatch):
    """Discord et Twitch bâtissent leurs outils séparément : brancher l'un sans
    l'autre laisserait la moitié des chemins proposer un widget invisible."""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module).build_chat_tools)
    assert "_spec_overlay_pour(" in source, (
        f"{module} n'appelle pas la spec filtrée — l'enum part entier")
    # `append(_OVERLAY_TOOL)` et non `_OVERLAY_TOOL` seul : `_APEX_OVERLAY_TOOL`
    # contient la même sous-chaîne, et c'est un autre outil, légitime.
    assert "append(_OVERLAY_TOOL)" not in source, (
        f"{module} ajoute encore la spec d'origine, non filtrée")


@pytest.mark.asyncio
async def test_un_filtrage_impossible_rend_la_spec_entiere():
    """Le filtrage est un CONFORT. Le laisser lever priverait Wally de TOUS ses
    outils d'un coup : l'exception remonte dans `build_chat_tools`, qui en
    construit vingt autres — plus de mémoire, plus de notes, plus d'Apex, pour
    une lecture SQLite manquée.
    """
    from bot.intelligence.overlay_narrator import spec_overlay_pour

    class _Casse:
        async def spec_outil(self):
            raise RuntimeError("base injoignable")

    for narrateur in (_Casse(), object(), None):
        spec = await spec_overlay_pour(narrateur)
        assert spec is OVERLAY_TOOL_SPEC


@pytest.mark.asyncio
async def test_le_repli_ne_masque_pas_un_filtrage_qui_marche():
    """Sans ce pendant, « rend toujours la spec entière » passerait pour un
    correctif et la garde ne servirait plus à rien."""
    from bot.intelligence.overlay_narrator import spec_overlay_pour

    n = _narrateur(_base(masque_partout=["dice"]))
    spec = await spec_overlay_pour(n)
    assert "dice" not in spec["function"]["parameters"]["properties"]["widget"]["enum"]
