"""`GET /api/admin/decisions` — la file du cockpit.

Quatre choses attendent quelqu'un dans ce bot, et chacune vivait sur une page
différente : une tâche qui échoue, une erreur qui se répète, deux identités qui
semblent désigner la même personne, une question que Wally aimerait poser. On
ne les voyait qu'en allant les chercher — donc jamais, sauf le jour où ça se
remarque autrement.

Le point qui compte pour chaque item n'est pas son libellé, c'est sa **cible** :
un hash complet, filtre compris, pour que cliquer ouvre la page déjà réglée sur
ce dont il s'agit. Un item qui ouvre une page non filtrée fait retomber sur le
problème d'origine — retrouver l'aiguille.
"""
from __future__ import annotations

import types

import pytest

from bot.dashboard.routes.admin import file_de_decisions


class _FauxDB:
    def __init__(self, taches=(), liens=(), questions=()):
        self.taches = list(taches)
        self.liens = list(liens)
        self.questions = list(questions)
        self._conn = self

    async def list_action_tasks(self, **kw):
        return self.taches

    async def list_link_proposals(self, status=None):
        return [x for x in self.liens if status is None or x.get("status") == status]

    def execute(self, *a, **k):
        """`memory_dashboard` interroge la base à la main, en context manager."""
        questions = self.questions

        class _Curseur:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *a):
                return False

            async def fetchall(self_inner):
                return questions

            async def fetchone(self_inner):
                return {"total": len(questions), "resolved": 0,
                        "pending": len(questions)}

        return _Curseur()


def _requete(db, journal=None):
    wally = types.SimpleNamespace(db=db, start_time=0.0, overlay_visible=True)
    return types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(wally=wally))
    )


@pytest.fixture(autouse=True)
def _journal_muet(monkeypatch):
    """Par défaut, aucun groupe d'erreurs : chaque test décide des siens."""
    async def _vide(request, max_groupes=8):
        return {"groupes": [], "niveaux": {}}

    monkeypatch.setattr("bot.dashboard.routes.admin.journal_erreurs", _vide)


def _groupes(monkeypatch, groupes, niveaux=None):
    async def _faux(request, max_groupes=8):
        return {"groupes": groupes, "niveaux": niveaux or {}}

    monkeypatch.setattr("bot.dashboard.routes.admin.journal_erreurs", _faux)


async def test_une_file_vide_est_une_file_vide():
    d = await file_de_decisions(_requete(_FauxDB()))
    assert d["items"] == []
    assert d["total"] == 0


async def test_une_tache_en_echec_ouvre_automatisations_deja_filtre():
    db = _FauxDB(taches=[
        {"id": 4, "description": "Dire bonjour", "last_error": "Row has no attribute"},
        {"id": 5, "description": "Rappel sain", "last_error": None},
    ])
    d = await file_de_decisions(_requete(db))
    assert len(d["items"]) == 1
    item = d["items"][0]
    assert item["type"] == "echec"
    assert item["cible"] == "#/live/automatisations?vue=echec"
    assert "Row has no attribute" in item["detail"]


async def test_une_erreur_unique_nappelle_pas_encore_de_decision(monkeypatch):
    """Une occurrence, c'est du bruit. Deux, c'est un motif."""
    _groupes(monkeypatch, [
        {"message": "hoquet", "fois": 1, "derniere": "10:00", "source": "bot.a"},
        {"message": "vraie panne", "fois": 7, "derniere": "11:00", "source": "bot.b"},
    ])
    d = await file_de_decisions(_requete(_FauxDB()))
    titres = [i["titre"] for i in d["items"]]
    assert titres == ["vraie panne"]
    assert d["items"][0]["cible"] == "#/systeme/journal?niveau=error"


async def test_ce_qui_est_casse_passe_devant_ce_qui_attend_une_reponse(monkeypatch):
    _groupes(monkeypatch, [
        {"message": "err", "fois": 3, "derniere": "10:00", "source": "bot.a"},
    ])
    db = _FauxDB(
        taches=[{"id": 1, "description": "t", "last_error": "boum"}],
        liens=[{"status": "pending", "alias_id": "twitch:x", "canonical_id": "discord:1",
                "alias_username": "x"}],
        questions=[{"id": 1, "question": "q", "username": "a", "priority": "high"}],
    )
    d = await file_de_decisions(_requete(db))
    assert [i["type"] for i in d["items"]] == ["echec", "erreur", "fusion", "question"]


async def test_chaque_item_porte_une_cible_navigable(monkeypatch):
    _groupes(monkeypatch, [
        {"message": "err", "fois": 3, "derniere": "10:00", "source": "bot.a"},
    ])
    db = _FauxDB(
        taches=[{"id": 1, "description": "t", "last_error": "boum"}],
        liens=[{"status": "pending", "alias_id": "twitch:x", "canonical_id": "discord:1",
                "alias_username": "x"}],
        questions=[{"id": 1, "question": "q", "username": "a", "priority": "high"}],
    )
    d = await file_de_decisions(_requete(db))
    assert d["items"], "aucun item — le test ne prouverait rien"
    for i in d["items"]:
        assert i["cible"].startswith("#/"), f"cible non navigable : {i}"


async def test_seules_les_fusions_en_attente_comptent():
    """Une liaison déjà acceptée n'attend plus personne."""
    db = _FauxDB(liens=[
        {"status": "accepted", "alias_id": "a", "canonical_id": "b", "alias_username": "a"},
    ])
    d = await file_de_decisions(_requete(db))
    assert d["items"] == []


async def test_la_liste_est_bornee_mais_le_total_dit_la_verite():
    """Tronquer sans le dire ferait croire que tout est réglé à la douzième
    ligne."""
    db = _FauxDB(taches=[
        {"id": i, "description": f"t{i}", "last_error": "boum"} for i in range(30)
    ])
    d = await file_de_decisions(_requete(db), )
    assert len(d["items"]) == 12
    assert d["total"] == 30


async def test_un_message_derreur_immense_est_coupe(monkeypatch):
    _groupes(monkeypatch, [
        {"message": "x" * 900, "fois": 4, "derniere": "10:00", "source": "bot.a"},
    ])
    d = await file_de_decisions(_requete(_FauxDB()))
    assert len(d["items"][0]["titre"]) <= 160


async def test_les_erreurs_du_jour_sont_comptees_pour_la_tuile(monkeypatch):
    _groupes(monkeypatch, [], niveaux={"ERROR": 11, "CRITICAL": 2, "INFO": 900})
    d = await file_de_decisions(_requete(_FauxDB()))
    assert d["erreurs_du_jour"] == 13
