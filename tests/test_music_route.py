"""La porte d'entrée de l'extension : `/api/music/beat`.

C'est la seule route de ce bot appelée depuis le NAVIGATEUR D'UN TIERS, à
travers internet. Elle mérite donc ses gardes propres, et ce fichier ne teste
qu'elles : qui entre, et ce qui se passe quand on force.

La garde d'authentification du dépôt est fermée par défaut — tout ce qui est
sous `/api/` exige le Bearer admin tant qu'on ne l'ouvre pas explicitement. Ce
routeur est ouvert (l'extension n'a pas le token du dashboard, et le lui donner
reviendrait à lui confier la mémoire, les logs et les DM) puis referme
lui-même sa porte avec SON jeton, comme `/api/chat/` le fait avec son JWT.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from bot.core.music import MusicService
    from bot.dashboard.routes.music import router

    app = FastAPI()
    app.include_router(router, prefix="/api/music")
    app.state.wally = MagicMock()
    app.state.wally.music = MusicService()
    app.state.wally.config.music.extension_token = "letoken"
    return TestClient(app)


_BEAT = {"actif": True, "joue": True, "titre": "Numb", "artiste": "Linkin Park",
         "url": "https://youtube.com/watch?v=abc", "accuses": []}
_AUTH = {"Authorization": "Bearer letoken"}


# ── la porte ────────────────────────────────────────────────────────────────

def test_sans_jeton_c_est_NON(client):
    assert client.post("/api/music/beat", json=_BEAT).status_code == 401


def test_avec_un_MAUVAIS_jeton_c_est_non(client):
    r = client.post("/api/music/beat", json=_BEAT,
                    headers={"Authorization": "Bearer pasletoken"})
    assert r.status_code == 401


def test_un_jeton_NON_CONFIGURE_ferme_la_porte_au_lieu_de_l_ouvrir(client):
    """Le défaut le plus dangereux serait qu'un jeton vide laisse tout passer :
    la route est publiée sur internet, et le champ est vide tant que personne ne
    l'a rempli."""
    client.app.state.wally.config.music.extension_token = ""
    r = client.post("/api/music/beat", json=_BEAT,
                    headers={"Authorization": "Bearer "})
    assert r.status_code in (401, 503)


def test_avec_le_bon_jeton_ca_passe(client):
    r = client.post("/api/music/beat", json=_BEAT, headers=_AUTH)
    assert r.status_code == 200
    assert r.json()["ordres"] == []


# ── ce qui entre ────────────────────────────────────────────────────────────

def test_le_battement_nourrit_l_etat(client):
    client.post("/api/music/beat", json=_BEAT, headers=_AUTH)
    etat = client.app.state.wally.music.etat()
    assert etat["titre"] == "Numb"


def test_un_corps_qui_n_est_pas_du_JSON_est_refuse_proprement(client):
    r = client.post("/api/music/beat", data="pas du json", headers=_AUTH)
    assert r.status_code == 400


def test_un_corps_TORDU_ne_fait_pas_tomber_la_route(client):
    """Champs manquants, types faux, `accuses` qui n'est pas une liste : la
    route ne doit pas rendre un 500 — c'est du code appelé par un navigateur
    qu'on ne contrôle pas."""
    for corps in ({}, {"actif": "oui", "titre": 42},
                  {"actif": True, "accuses": "pas une liste"},
                  {"actif": True, "accuses": [None, 3, {"id": None}]}):
        r = client.post("/api/music/beat", json=corps, headers=_AUTH)
        assert r.status_code == 200, corps


def test_l_extension_repart_avec_les_ordres_en_attente(client):
    import asyncio

    svc = client.app.state.wally.music

    async def poser():
        tache = asyncio.create_task(svc.commander("next"))
        await asyncio.sleep(0)
        return tache

    asyncio.get_event_loop_policy().new_event_loop()
    boucle = asyncio.new_event_loop()
    try:
        tache = boucle.run_until_complete(poser())
        r = client.post("/api/music/beat", json=_BEAT, headers=_AUTH)
        assert [o["action"] for o in r.json()["ordres"]] == ["next"]
        tache.cancel()
    finally:
        boucle.close()


# ── CORS : l'extension appelle depuis youtube.com ───────────────────────────

def test_l_origine_youtube_est_la_SEULE_autorisee():
    """Sans CORS, le navigateur refuse la réponse ; avec un CORS ouvert à tous,
    n'importe quel site visité par n'importe qui pourrait tenter d'appeler cette
    route. L'origine est donc close."""
    from bot.dashboard.routes.music import ORIGINES

    assert "https://www.youtube.com" in ORIGINES
    assert "*" not in ORIGINES


# ── la garde, sur l'application RÉELLE ──────────────────────────────────────

def test_le_prefixe_est_ouvert_mais_la_route_reste_fermee():
    """Deux vérités qui doivent coexister, et c'est leur écart qui blesse :
    le préfixe échappe au Bearer admin (l'extension ne l'a pas), donc la route
    DOIT porter sa propre serrure. Si quelqu'un retire le contrôle de jeton dans
    `music.py`, la route devient ouverte à tout internet sans qu'aucun autre
    test ne s'en aperçoive.
    """
    from bot.dashboard.auth import _needs_auth

    assert _needs_auth("/api/music/beat") is False       # pas de Bearer admin
    from bot.dashboard.routes import music
    import inspect
    assert "_verifier_jeton" in inspect.getsource(music.beat)


def test_le_service_est_bien_partage_par_l_etat():
    """La route le nourrit, l'outil du chat le lit : deux instances auraient
    divergé au premier battement."""
    from bot.dashboard.state import AppState
    assert "music" in AppState.__annotations__


# ── la version servie ───────────────────────────────────────────────────────
#
# Une extension chargée depuis un dossier ne se met JAMAIS à jour seule : seul
# le Web Store le fait. Le bot annonce donc la version qu'il sert, l'extension
# la compare à la sienne, et le dit dans sa fenêtre + par une pastille sur son
# icône. Sans ça, Azraël garde une version corrigée depuis des semaines sans
# jamais l'apprendre — c'est ce qui s'est produit le 2026-08-19.

def test_le_battement_annonce_la_version_servie(client):
    import json
    from pathlib import Path

    manifeste = json.loads(
        (Path(__file__).resolve().parents[1] / "extension-musique" /
         "manifest.json").read_text(encoding="utf-8"))
    r = client.post("/api/music/beat", json=_BEAT, headers=_AUTH)
    assert r.json()["version"] == manifeste["version"]


def test_la_version_est_LUE_dans_le_manifest_pas_recopiee():
    """Deux sources de vérité pour un numéro de version, et c'est la copie
    qu'on oublie de bouger — l'avertissement se tairait pile quand il sert."""
    import inspect

    from bot.dashboard.routes import music

    source = inspect.getsource(music._version_servie)
    assert "manifest.json" in source




# ── la réponse tenue (long polling) ─────────────────────────────────────────
#
# Chrome ramène les timers d'un onglet caché et silencieux à UN PAR MINUTE.
# Mesuré en prod le 2026-08-21 ; c'est ce qui rendait « mets lecture »
# impossible à livrer. La cadence appartient donc au serveur : il tient la
# réponse jusqu'à ce qu'un ordre arrive. Le délai vient du navigateur d'un
# tiers, il se borne ici.


class _Espion:
    """Un service qui n'écoute que ce qu'on lui passe."""

    def __init__(self) -> None:
        self.vu: list[dict] = []

    async def battement_tenu(self, **champs):
        self.vu.append(champs)
        return []


def test_le_delai_demande_par_l_extension_est_BORNE(client):
    espion = _Espion()
    client.app.state.wally.music = espion
    client.post("/api/music/beat", json={**_BEAT, "attente": 9999},
                headers=_AUTH)
    from bot.core.music import MusicService
    assert espion.vu[0]["attente_s"] == MusicService.ATTENTE_MAX_S


def test_une_EXTENSION_D_AVANT_ce_correctif_garde_la_reponse_immediate(client):
    """Elle n'envoie pas le champ et bat sur son propre timer : lui tenir la
    réponse empilerait ses requêtes au lieu de l'aider."""
    espion = _Espion()
    client.app.state.wally.music = espion
    client.post("/api/music/beat", json=_BEAT, headers=_AUTH)
    assert espion.vu[0]["attente_s"] == 0.0


def test_un_delai_TORDU_ne_fait_pas_tomber_la_route(client):
    espion = _Espion()
    client.app.state.wally.music = espion
    for bavure in ("bientôt", None, [], {"a": 1}, "NaN"):
        r = client.post("/api/music/beat", json={**_BEAT, "attente": bavure},
                        headers=_AUTH)
        assert r.status_code == 200
    assert all(v["attente_s"] == 0.0 for v in espion.vu)


def test_l_onglet_qui_parle_est_TRANSMIS_au_service(client):
    """Azraël peut avoir trois pages YouTube ouvertes : sans cette clé, celle
    qui n'a pas de lecteur efface le morceau des autres."""
    espion = _Espion()
    client.app.state.wally.music = espion
    client.post("/api/music/beat", json={**_BEAT, "onglet": "abc-123"},
                headers=_AUTH)
    assert espion.vu[0]["onglet"] == "abc-123"


def test_un_onglet_TORDU_ne_fait_pas_tomber_la_route(client):
    espion = _Espion()
    client.app.state.wally.music = espion
    for bavure in (None, 42, [], {"a": 1}):
        r = client.post("/api/music/beat", json={**_BEAT, "onglet": bavure},
                        headers=_AUTH)
        assert r.status_code == 200
    assert all(isinstance(v["onglet"], str) for v in espion.vu)
