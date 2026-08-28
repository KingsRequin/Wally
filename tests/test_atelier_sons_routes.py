"""L'atelier des sons de commande — Système → Overlay.

Le DOSSIER est la source de vérité : ces routes déposent, règlent et retirent,
elles ne tiennent aucun index. Les tests le vérifient sur un vrai dossier
temporaire, pas sur un double : c'est le disque qui décide de ce qui existe.
"""
import pytest
from fastapi import HTTPException

from bot.core.overlay_feed import OverlayFeed
from bot.core.sons import ReglagesSons, SoundLibrary
from bot.dashboard.routes.overlay import (
    deposer_son_commande,
    essayer_son_commande,
    lister_sons_commande,
    regler_son_commande,
    supprimer_son_commande,
)


class _Req:
    def __init__(self, state, body=None, raw=b""):
        self.app = type("A", (), {"state": type("S", (), {"wally": state})()})()
        self._body, self._raw = body, raw

    async def json(self):
        return self._body

    async def body(self):
        return self._raw


@pytest.fixture
def atelier(tmp_path):
    (tmp_path / "commande").mkdir()
    (tmp_path / "commande" / "apero.mp3").write_bytes(b"\xff\xfb" + b"0" * 200)
    state = type("W", (), {"sons": SoundLibrary(tmp_path),
                           "overlay_feed": OverlayFeed()})()
    return tmp_path, state


# ── lister ────────────────────────────────────────────────────────────────────

async def test_la_liste_porte_les_reglages_et_les_alias(atelier):
    dossier, state = atelier
    ReglagesSons(dossier).ecrire("apero", {"cooldown": 30, "volume": 0.5,
                                           "alias": ["ap"]})
    d = await lister_sons_commande(_Req(state))
    assert len(d["sons"]) == 1
    son = d["sons"][0]
    assert son["commande"] == "apero" and son["fichier"] == "apero.mp3"
    assert son["cooldown"] == 30.0 and son["volume"] == 0.5
    assert son["alias"] == ["ap"] and son["taille"] > 0
    assert d["max_octets"] > 0


async def test_un_reglage_orphelin_napparait_pas(atelier):
    """Un son supprimé à la main hors du panneau ne doit pas rester à l'écran."""
    dossier, state = atelier
    ReglagesSons(dossier).ecrire("disparu", {"volume": 0.5})
    d = await lister_sons_commande(_Req(state))
    assert [s["commande"] for s in d["sons"]] == ["apero"]


async def test_sans_bibliotheque_la_route_le_dit(atelier):
    state = type("W", (), {"sons": None})()
    with pytest.raises(HTTPException) as e:
        await lister_sons_commande(_Req(state))
    assert e.value.status_code == 503


# ── régler ────────────────────────────────────────────────────────────────────

async def test_regler_un_son_ecrit_et_rend_ce_qui_est_retenu(atelier):
    dossier, state = atelier
    d = await regler_son_commande("apero", _Req(state, {
        "cooldown": 60, "volume": 0.75, "alias": ["ap", "APÉRO"]}))
    assert d == {"commande": "apero", "cooldown": 60.0, "volume": 0.75,
                 "alias": ["ap", "apéro"]}
    assert ReglagesSons(dossier).pour("apero")["cooldown"] == 60.0


async def test_regler_un_son_inexistant_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await regler_son_commande("fantome", _Req(state, {"volume": 1}))
    assert e.value.status_code == 404


async def test_un_corps_qui_nest_pas_un_objet_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await regler_son_commande("apero", _Req(state, ["pas", "un", "objet"]))
    assert e.value.status_code == 400


# ── déposer ───────────────────────────────────────────────────────────────────

async def test_deposer_cree_un_son_appelable(atelier):
    dossier, state = atelier
    d = await deposer_son_commande("PERKS.mp3", _Req(state, raw=b"\xff\xfb" + b"0" * 50))
    assert d == {"fichier": "PERKS.mp3", "commande": "perks"}
    assert "perks" in SoundLibrary(dossier).commandes()


async def test_une_extension_inconnue_est_refusee(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await deposer_son_commande("virus.exe", _Req(state, raw=b"MZ"))
    assert e.value.status_code == 400


async def test_un_fichier_vide_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await deposer_son_commande("vide.mp3", _Req(state, raw=b""))
    assert e.value.status_code == 400


async def test_un_fichier_trop_lourd_est_refuse(atelier):
    """Le même plafond que la bibliothèque : accepter au-delà déposerait un
    fichier que l'overlay refuserait ensuite de lister, sans rien dire."""
    from bot.core.sons import _MAX_BYTES
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await deposer_son_commande("gros.mp3", _Req(state, raw=b"0" * (_MAX_BYTES + 1)))
    assert e.value.status_code == 413


async def test_un_nom_qui_remonte_larborescence_est_refuse(atelier):
    """`_safe_name` réduit au basename : le fichier ne peut pas sortir du dossier."""
    dossier, state = atelier
    await deposer_son_commande("../../evade.mp3", _Req(state, raw=b"\xff\xfb0"))
    assert not (dossier.parent / "evade.mp3").exists()
    assert (dossier / "commande" / "evade.mp3").is_file()


# ── supprimer ─────────────────────────────────────────────────────────────────

async def test_supprimer_emporte_le_fichier_ET_les_reglages(atelier):
    """Sinon un alias orphelin survit au son et reste proposé à l'écran."""
    dossier, state = atelier
    ReglagesSons(dossier).ecrire("apero", {"alias": ["ap"]})
    await supprimer_son_commande("apero", _Req(state))
    assert SoundLibrary(dossier).commandes() == {}
    assert ReglagesSons(dossier).alias() == {}


async def test_supprimer_un_son_inconnu_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await supprimer_son_commande("fantome", _Req(state))
    assert e.value.status_code == 404


# ── écouter ───────────────────────────────────────────────────────────────────

async def test_lessai_publie_le_son_sur_loverlay(atelier):
    dossier, state = atelier
    ReglagesSons(dossier).ecrire("apero", {"volume": 0.3})
    file = state.overlay_feed.subscribe()
    await essayer_son_commande("apero", _Req(state))
    event = file.get_nowait()
    assert event["type"] == "son" and event["nom"] == "apero.mp3"
    assert event["volume"] == 0.3


async def test_lessai_passe_outre_le_cooldown(atelier):
    """C'est un essai, pas une demande du chat : on doit pouvoir réécouter."""
    dossier, state = atelier
    ReglagesSons(dossier).ecrire("apero", {"cooldown": 9999})
    file = state.overlay_feed.subscribe()
    await essayer_son_commande("apero", _Req(state))
    await essayer_son_commande("apero", _Req(state))
    assert file.qsize() == 2


# ── Le nom d'un son ne traverse jamais un contexte JavaScript ────────────────

def test_aucun_onclick_ninterpole_un_nom_de_son():
    """`_escHtml` n'échappe PAS l'apostrophe, et la commande vient d'un FICHIER.

    Un `x');alert(1);a.mp3` déposé dans le dossier — par le panneau ou à la
    main — s'exécuterait au rendu si son nom atterrissait dans un `onclick`.
    Les boutons de l'atelier passent donc par `data-son-action` et un écouteur
    délégué : le nom vit dans un attribut `data-`, lu comme une chaîne.
    """
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1]
          / "bot/dashboard/static/app.js").read_text(encoding="utf-8")
    atelier = js[js.index("// ── Atelier des sons de commande"):]
    for interdit in ("onclick=\"essayerSon(", "onclick=\"enregistrerSon(",
                     "onclick=\"supprimerSon("):
        assert interdit not in atelier, f"{interdit} remet un nom de fichier dans du JS"
    assert 'data-son-action="essai"' in atelier
    assert "closest('[data-son-action]')" in atelier


def test_letat_est_pose_APRES_le_rendu():
    """`renderAtelierSons` réécrit tout le panneau, ligne d'état comprise.

    Posé avant le rendu, le message était effacé dans la foulée : cliquer
    « Enregistrer » ne renvoyait rien du tout à l'écran. Vu en navigateur, pas
    en test — d'où ce garde-fou textuel.
    """
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1]
          / "bot/dashboard/static/app.js").read_text(encoding="utf-8")
    atelier = js[js.index("// ── Atelier des sons de commande"):]
    for geste in ("enregistrerSon", "supprimerSon", "deposerSon", "normaliserSons"):
        corps = atelier[atelier.index("async function " + geste):]
        corps = corps[:corps.index("\n}\n")]
        if "renderAtelierSons" not in corps:
            continue
        assert corps.index("renderAtelierSons") < corps.rindex("_etatAtelier"), (
            f"{geste} pose son message avant de re-rendre : il sera effacé")
