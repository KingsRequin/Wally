"""Les decks Wallycard, rangés sur le compte Discord du joueur.

Ce qui se teste ici, c'est ce que le SERVEUR refuse. Le front applique les mêmes
limites pour l'affichage, mais une limite tenue par le client seul se contourne
avec un `curl` : c'est ici qu'elle doit tenir.

Une vraie base SQLite, et non un `MagicMock` : le cloisonnement entre comptes et
le compte des decks sont des requêtes, et un mock rendrait ce qu'on lui dit de
rendre.
"""

from __future__ import annotations

import dataclasses

import pytest
from httpx import ASGITransport, AsyncClient

from bot.core import tcg_cartes
from bot.core.tcg_cartes import CARTES
from bot.core.tcg_cartes_action import CARTES_ACTION
from bot.core.tcg_decks import DECKS_PAR_COMPTE, NOM_MAX, TAILLE_DECK
from bot.dashboard.app import create_dashboard_app
from bot.dashboard.routes.chat_auth import _jwt_secret_raw, create_jwt
from bot.db.database import Database
from tests.dashboard.conftest import _make_state

HEROS = list(CARTES)
TACTIQUES = list(CARTES_ACTION)


def _jeton(discord_id: str) -> dict:
    jwt = create_jwt(discord_id, f"joueur{discord_id}", None, _jwt_secret_raw())
    return {"Authorization": f"Bearer {jwt}"}


# 🚨 Les jetons se fabriquent PENDANT le test, sous un secret posé par lui.
# Fabriqués à l'import, ils étaient signés avec le secret du moment ; un autre
# fichier de test (`test_chat_auth.py`) pose `JWT_SECRET` à SON import, et dans
# la suite parallèle la route vérifiait alors avec un autre secret : 401 partout,
# alors que le fichier seul passait.
@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secret-de-test-des-decks")


@pytest.fixture
def A():
    return _jeton("111111111111111111")


@pytest.fixture
def B():
    return _jeton("222222222222222222")


@pytest.fixture
def heros_jouables(monkeypatch):
    """Rend TOUS les héros jouables le temps d'un test.

    Aucun ne l'est dans le vrai catalogue aujourd'hui (arbitrage de l'owner du
    2026-09-13) : sans ça, aucun test ne pourrait composer un deck complet. On
    remplace les entrées du dictionnaire lui-même, celui que `tcg_decks` lit.
    """
    for cle, carte in list(tcg_cartes.CARTES.items()):
        monkeypatch.setitem(tcg_cartes.CARTES, cle, dataclasses.replace(carte, jouable=True))


@pytest.fixture
async def client(tmp_path):
    db = await Database.create(str(tmp_path / "decks.db"))
    app = create_dashboard_app(_make_state(db=db))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await db.close()


def _deck(**champs) -> dict:
    return {"nom": "Mon deck", "heros": [], "cartes": [], **champs}


# ── L'accès ───────────────────────────────────────────────────────────────

async def test_sans_jeton_tout_est_refuse(client):
    assert (await client.get("/api/public/tcg/decks")).status_code == 401
    assert (await client.post("/api/public/tcg/decks", json=_deck())).status_code == 401
    assert (await client.put("/api/public/tcg/decks/1", json=_deck())).status_code == 401
    assert (await client.delete("/api/public/tcg/decks/1")).status_code == 401


async def test_un_jeton_falsifie_est_refuse(client):
    r = await client.get("/api/public/tcg/decks", headers={"Authorization": "Bearer faux.jeton.x"})
    assert r.status_code == 401


# ── Le parcours normal ────────────────────────────────────────────────────

async def test_un_deck_incomplet_s_enregistre(client, A):
    """Aucun héros n'est prêt aujourd'hui : refuser les brouillons rendrait
    l'éditeur inutilisable, personne ne pourrait rien sauvegarder."""
    r = await client.post("/api/public/tcg/decks", headers=A,
                          json=_deck(cartes=TACTIQUES[:2]))
    assert r.status_code == 201, r.text
    deck = r.json()["deck"]
    assert deck["cartes"] == TACTIQUES[:2]
    assert deck["complet"] is False


async def test_un_deck_plein_est_complet(client, A, heros_jouables):
    r = await client.post("/api/public/tcg/decks", headers=A,
                          json=_deck(heros=HEROS[:3], cartes=TACTIQUES[:TAILLE_DECK]))
    assert r.status_code == 201, r.text
    assert r.json()["deck"]["complet"] is True


async def test_creer_puis_retrouver_son_deck(client, A):
    await client.post("/api/public/tcg/decks", headers=A, json=_deck(nom="  Rush  "))
    decks = (await client.get("/api/public/tcg/decks", headers=A)).json()["decks"]
    assert [d["nom"] for d in decks] == ["Rush"]


async def test_modifier_son_deck(client, A):
    deck_id = (await client.post("/api/public/tcg/decks", headers=A, json=_deck())).json()["deck"]["id"]
    r = await client.put(f"/api/public/tcg/decks/{deck_id}", headers=A,
                         json=_deck(nom="Contrôle", cartes=TACTIQUES[:3]))
    assert r.status_code == 200, r.text
    assert r.json()["deck"]["nom"] == "Contrôle"
    assert r.json()["deck"]["cartes"] == TACTIQUES[:3]


async def test_supprimer_son_deck(client, A):
    deck_id = (await client.post("/api/public/tcg/decks", headers=A, json=_deck())).json()["deck"]["id"]
    assert (await client.delete(f"/api/public/tcg/decks/{deck_id}", headers=A)).status_code == 204
    assert (await client.get("/api/public/tcg/decks", headers=A)).json()["decks"] == []


# ── Ce que le serveur refuse ──────────────────────────────────────────────

@pytest.mark.parametrize("champs", [
    pytest.param({"cartes": TACTIQUES[:TAILLE_DECK + 1]}, id="trop-de-cartes"),
    pytest.param({"cartes": [TACTIQUES[0], TACTIQUES[0]]}, id="carte-en-double"),
    pytest.param({"cartes": ["carte_qui_n_existe_pas"]}, id="carte-inconnue"),
    pytest.param({"heros": HEROS[:4]}, id="trop-de-heros"),
    pytest.param({"heros": [HEROS[0]]}, id="heros-pas-encore-jouable"),
    pytest.param({"heros": [HEROS[0], HEROS[0]]}, id="heros-en-double"),
    pytest.param({"heros": ["heros_inconnu"]}, id="heros-inconnu"),
    pytest.param({"cartes": [HEROS[0]]}, id="heros-pose-en-carte-tactique"),
    pytest.param({"nom": "   "}, id="nom-vide"),
    pytest.param({"nom": "x" * (NOM_MAX + 1)}, id="nom-trop-long"),
])
async def test_un_deck_invalide_est_refuse(client, champs, A):
    r = await client.post("/api/public/tcg/decks", headers=A, json=_deck(**champs))
    assert r.status_code == 400, r.text
    # Le refus DIT pourquoi : l'éditeur l'affiche tel quel.
    assert r.json()["detail"]
    assert (await client.get("/api/public/tcg/decks", headers=A)).json()["decks"] == []


async def test_une_modification_invalide_ne_touche_pas_le_deck(client, A):
    deck_id = (await client.post("/api/public/tcg/decks", headers=A,
                                 json=_deck(cartes=TACTIQUES[:1]))).json()["deck"]["id"]
    r = await client.put(f"/api/public/tcg/decks/{deck_id}", headers=A,
                         json=_deck(cartes=[TACTIQUES[0], TACTIQUES[0]]))
    assert r.status_code == 400
    deck = (await client.get("/api/public/tcg/decks", headers=A)).json()["decks"][0]
    assert deck["cartes"] == TACTIQUES[:1]


async def test_le_nombre_de_decks_par_compte_est_plafonne(client, A):
    for n in range(DECKS_PAR_COMPTE):
        r = await client.post("/api/public/tcg/decks", headers=A, json=_deck(nom=f"deck {n}"))
        assert r.status_code == 201
    r = await client.post("/api/public/tcg/decks", headers=A, json=_deck(nom="de trop"))
    assert r.status_code == 400
    assert "decks" in r.json()["detail"]


# ── Le cloisonnement entre comptes ────────────────────────────────────────

async def test_un_joueur_ne_voit_que_ses_decks(client, A, B):
    await client.post("/api/public/tcg/decks", headers=A, json=_deck(nom="de A"))
    await client.post("/api/public/tcg/decks", headers=B, json=_deck(nom="de B"))
    noms_a = [d["nom"] for d in (await client.get("/api/public/tcg/decks", headers=A)).json()["decks"]]
    assert noms_a == ["de A"]


async def test_un_joueur_ne_touche_pas_au_deck_d_un_autre(client, A, B):
    """404 et non 403 : un 403 confirmerait que le deck existe."""
    deck_id = (await client.post("/api/public/tcg/decks", headers=A, json=_deck(nom="de A"))).json()["deck"]["id"]
    assert (await client.put(f"/api/public/tcg/decks/{deck_id}", headers=B,
                             json=_deck(nom="volé"))).status_code == 404
    assert (await client.delete(f"/api/public/tcg/decks/{deck_id}", headers=B)).status_code == 404
    assert [d["nom"] for d in (await client.get("/api/public/tcg/decks", headers=A)).json()["decks"]] == ["de A"]


async def test_le_plafond_se_compte_par_compte(client, A, B):
    for n in range(DECKS_PAR_COMPTE):
        await client.post("/api/public/tcg/decks", headers=A, json=_deck(nom=f"deck {n}"))
    assert (await client.post("/api/public/tcg/decks", headers=B, json=_deck())).status_code == 201


async def test_un_heros_jouable_entre_dans_un_deck(client, A, heros_jouables):
    r = await client.post("/api/public/tcg/decks", headers=A, json=_deck(heros=[HEROS[0]]))
    assert r.status_code == 201, r.text
    assert r.json()["deck"]["heros"] == [HEROS[0]]


def test_aucun_heros_n_est_jouable_aujourd_hui():
    """L'owner, 2026-09-13 : « aucun héros n'a de stats prêtes pour le moment ».
    Le jour où l'un d'eux passe `jouable: true` dans `tcg/cartes.yaml`, ce test
    tombe : c'est voulu, il faut alors le supprimer en connaissance de cause."""
    assert not [c.cle for c in CARTES.values() if c.jouable]


async def test_les_limites_sont_servies_au_front_sans_connexion(client):
    """L'éditeur les LIT ici au lieu de les recopier : une limite écrite deux
    fois finit par dire deux choses. Publique, parce qu'on compose un deck
    avant de se connecter."""
    r = await client.get("/api/public/tcg/decks/limites")
    assert r.status_code == 200
    assert r.json() == {"taille": TAILLE_DECK, "heros": 3, "nomMax": NOM_MAX}
