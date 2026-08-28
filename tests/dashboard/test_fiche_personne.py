"""La fiche Personne agrégée : `GET /api/admin/person/{identite}`.

Le sujet de ces tests n'est pas le JSON rendu, c'est **l'identité**. Une
personne peut avoir un compte Discord et un compte Twitch liés ; ses faits sont
alors répartis entre `discord:123` et `twitch:pseudo`. Interroger une seule des
deux identités en montre la moitié — sans rien dire, et sans erreur. C'est la
signature de panne que tout le projet traque : quelque chose manque, personne
n'est prévenu.
"""
from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from bot.dashboard.routes.person import _groupe_didentites, fiche_personne


class _FauxStore:
    def __init__(self, par_user: dict[str, list]):
        self._par_user = par_user

    async def get_by_user(self, user_id: str):
        return self._par_user.get(user_id, [])


class _FauxDB:
    def __init__(self, **kw):
        self.gens = kw.get("gens", [])
        self.liens = kw.get("liens", [])
        self.alias = kw.get("alias", [])
        self.notes = kw.get("notes", [])
        self.trust = kw.get("trust", {})
        self.love = kw.get("love", {})
        self.apex = kw.get("apex")
        self.bans = kw.get("bans", [])

    async def list_memory_users(self, q=None, include_no_memory=False):
        return self.gens

    async def list_link_proposals(self, status=None):
        return self.liens

    async def list_aliases(self, canonical_uid=None):
        return [a for a in self.alias if a["canonical_uid"] == canonical_uid]

    async def get_persistent_notes(self):
        return self.notes

    async def get_trust_score(self, platform, user_id):
        return self.trust.get(f"{platform}:{user_id}", 0.0)

    async def get_love_score(self, platform, user_id, decay_lambda=0.1):
        return self.love.get(f"{platform}:{user_id}", 0.0)

    async def apex_account_for_person(self, identity):
        return self.apex

    async def list_chat_bans(self):
        return self.bans


def _requete(db, store=None, ignores=()):
    """Une requête FastAPI réduite à ce que la route lit vraiment."""
    wally = types.SimpleNamespace(
        db=db,
        fact_store=store,
        config=types.SimpleNamespace(
            twitch=types.SimpleNamespace(ignored_users=list(ignores))
        ),
    )
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(wally=wally)))


def _fait(user_id, contenu, **kw):
    from datetime import datetime

    from bot.intelligence.memory.facts import AtomicFact, FactCategory

    return AtomicFact(
        user_id=user_id, content=contenu,
        category=kw.get("categorie", FactCategory.FAIT),
        created_at=kw.get("cree", datetime(2026, 8, 1, 12, 0)),
        expires_at=kw.get("expire"),
        id=kw.get("id", 1),
    )


# ── Le groupe d'identités ───────────────────────────────────────────────────

async def test_une_identite_seule_est_son_propre_groupe():
    db = _FauxDB()
    canonique, groupe = await _groupe_didentites(db, "discord:123")
    assert canonique == "discord:123"
    assert groupe == ["discord:123"]


async def test_un_alias_ramene_vers_son_canonique():
    """Un lien partagé peut viser l'alias. Renvoyer 404 parce que la personne a
    été fusionnée depuis serait absurde."""
    db = _FauxDB(liens=[{"canonical_id": "discord:123", "alias_id": "twitch:kr"}])
    canonique, groupe = await _groupe_didentites(db, "twitch:kr")
    assert canonique == "discord:123"
    assert set(groupe) == {"discord:123", "twitch:kr"}


async def test_le_canonique_ramene_tous_ses_alias():
    db = _FauxDB(liens=[
        {"canonical_id": "discord:123", "alias_id": "twitch:kr"},
        {"canonical_id": "discord:123", "alias_id": "twitch:kr2"},
        {"canonical_id": "discord:999", "alias_id": "twitch:autre"},
    ])
    _, groupe = await _groupe_didentites(db, "discord:123")
    assert set(groupe) == {"discord:123", "twitch:kr", "twitch:kr2"}
    assert "twitch:autre" not in groupe


# ── Ce que la fiche rassemble ───────────────────────────────────────────────

async def test_les_faits_des_deux_plateformes_sont_reunis():
    """LE test de cette route. Les faits d'un compte lié étaient invisibles."""
    db = _FauxDB(
        gens=[{"user_id": "discord:123", "username": "KingsRequin", "last_updated": 1.0}],
        liens=[{"canonical_id": "discord:123", "alias_id": "twitch:kr"}],
    )
    store = _FauxStore({
        "discord:123": [_fait("discord:123", "aime les crevettes", id=1)],
        "twitch:kr": [_fait("twitch:kr", "joue à Apex", id=2)],
    })
    fiche = await fiche_personne("discord:123", _requete(db, store))
    contenus = {m["content"] for m in fiche["memoires"]}
    assert contenus == {"aime les crevettes", "joue à Apex"}


async def test_le_score_le_plus_haut_du_groupe_gagne():
    """Un compte fraîchement lié part à zéro. Afficher CE zéro parce qu'il se
    trouve être l'identité canonique effacerait dix mois de relation."""
    db = _FauxDB(
        gens=[{"user_id": "twitch:neuf", "username": "neuf", "last_updated": 1.0}],
        liens=[{"canonical_id": "twitch:neuf", "alias_id": "discord:vieux"}],
        trust={"twitch:neuf": 0.0, "discord:vieux": 0.93},
        love={"twitch:neuf": 0.0, "discord:vieux": 0.43},
    )
    fiche = await fiche_personne("twitch:neuf", _requete(db, _FauxStore({})))
    assert fiche["trust"] == 0.93
    assert fiche["love"] == 0.43


async def test_lavatar_discord_prime_sur_le_reste():
    db = _FauxDB(
        gens=[
            {"user_id": "twitch:kr", "username": "kr", "avatar_url": "tw.png",
             "last_updated": 1.0},
            {"user_id": "discord:123", "username": "KingsRequin",
             "avatar_url": "dc.png", "last_updated": 1.0},
        ],
        liens=[{"canonical_id": "twitch:kr", "alias_id": "discord:123"}],
    )
    fiche = await fiche_personne("twitch:kr", _requete(db, _FauxStore({})))
    assert fiche["avatar_url"] == "dc.png"


async def test_les_memoires_sont_rendues_de_la_plus_recente_a_la_plus_vieille():
    from datetime import datetime

    db = _FauxDB(gens=[{"user_id": "discord:1", "username": "a", "last_updated": 1.0}])
    store = _FauxStore({"discord:1": [
        _fait("discord:1", "vieux", cree=datetime(2026, 1, 1), id=1),
        _fait("discord:1", "récent", cree=datetime(2026, 8, 1), id=2),
    ]})
    fiche = await fiche_personne("discord:1", _requete(db, store))
    assert [m["content"] for m in fiche["memoires"]] == ["récent", "vieux"]


async def test_seules_les_notes_qui_mentionnent_la_personne_remontent():
    """`persistent_notes` est GLOBALE — aucune colonne d'utilisateur. On rend
    une recherche, jamais « ses » notes, et le panneau le dit."""
    db = _FauxDB(
        gens=[{"user_id": "discord:1", "username": "Azrael", "last_updated": 1.0}],
        notes=[
            {"id": 1, "title": "Surnoms", "content": "ne pas appeler Azrael « Azra »"},
            {"id": 2, "title": "Divers", "content": "penser à rien"},
        ],
    )
    fiche = await fiche_personne("discord:1", _requete(db, _FauxStore({})))
    assert [n["id"] for n in fiche["notes"]] == [1]


async def test_un_nom_trop_court_ne_ramene_pas_toutes_les_notes():
    """Un pseudo de deux lettres apparaîtrait dans la moitié des notes."""
    db = _FauxDB(
        gens=[{"user_id": "discord:1", "username": "Az", "last_updated": 1.0}],
        notes=[{"id": 1, "title": "Divers", "content": "faire une pizza"}],
    )
    fiche = await fiche_personne("discord:1", _requete(db, _FauxStore({})))
    assert fiche["notes"] == []


# ── Ignorée ou pas ──────────────────────────────────────────────────────────

async def test_un_pseudo_twitch_ignore_est_signale():
    db = _FauxDB(gens=[{"user_id": "twitch:nightbot", "username": "nightbot",
                        "last_updated": 1.0}])
    fiche = await fiche_personne("twitch:nightbot",
                                 _requete(db, _FauxStore({}), ignores=["NightBot"]))
    assert fiche["ignore"] is True


async def test_un_banni_discord_est_signale_lui_aussi():
    """Les deux mécanismes ne se voient pas l'un l'autre : n'en lire qu'un
    répondrait « écouté » à propos de quelqu'un que l'autre fait taire."""
    db = _FauxDB(
        gens=[{"user_id": "discord:42", "username": "gêneur", "last_updated": 1.0}],
        bans=[{"discord_id": "42", "username": "gêneur"}],
    )
    fiche = await fiche_personne("discord:42", _requete(db, _FauxStore({})))
    assert fiche["ignore"] is True


async def test_quelqu_un_d_ecoute_n_est_pas_marque_ignore():
    db = _FauxDB(gens=[{"user_id": "discord:1", "username": "a", "last_updated": 1.0}])
    fiche = await fiche_personne("discord:1", _requete(db, _FauxStore({})))
    assert fiche["ignore"] is False


# ── Les refus ───────────────────────────────────────────────────────────────

async def test_une_identite_sans_prefixe_est_refusee():
    """`610550333042589752` seul est ambigu : Discord ou Twitch ? Deviner
    donnerait une fiche vide au lieu d'une erreur."""
    with pytest.raises(HTTPException) as e:
        await fiche_personne("610550333042589752", _requete(_FauxDB()))
    assert e.value.status_code == 400


async def test_une_personne_inconnue_rend_404():
    with pytest.raises(HTTPException) as e:
        await fiche_personne("discord:inconnu", _requete(_FauxDB()))
    assert e.value.status_code == 404


async def test_la_memoire_indisponible_ne_casse_pas_la_fiche():
    """Le reste de ce qu'on sait vaut mieux qu'une page d'erreur."""
    db = _FauxDB(gens=[{"user_id": "discord:1", "username": "a", "last_updated": 1.0}])
    fiche = await fiche_personne("discord:1", _requete(db, store=None))
    assert fiche["memoires"] == []
    assert fiche["nom"] == "a"
