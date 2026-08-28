"""Le Journal : la source de chaque ligne, et le regroupement des erreurs.

Deux choses que le panneau ne pouvait pas faire avant la refonte du
2026-08-28 :

· **filtrer par sous-système** — la colonne « source » d'`app.log` était bien
  écrite sur le disque, mais `_parse_log_line` et le sink loguru la jetaient
  tous les deux. Le front n'avait donc jamais de quoi construire une puce.
· **compter les répétitions** — quarante occurrences de la même panne défilent
  dans le flux, on lit la dernière, et rien ne dit que c'est la quarantième.
"""
from __future__ import annotations

import pytest

from bot.dashboard.routes.sse import (
    _cle_de_groupe,
    _parse_log_line,
    journal_erreurs,
)


# ── La source, rendue au panneau ────────────────────────────────────────────

def test_la_ligne_porte_son_module_sans_le_numero_de_ligne():
    ligne = "18:50:09 | INFO     | bot.twitch.events:178 | EventSub subscribed: chat"
    lu = _parse_log_line(ligne)
    assert lu is not None
    # Le module DÉSIGNE le sous-système ; le rang du `logger.info` dedans ne
    # veut rien dire pour qui filtre, et ferait un groupe par ligne de code.
    assert lu["source"] == "bot.twitch.events"


def test_une_ligne_sans_colonne_source_ne_ment_pas():
    """Trois champs seulement : on rend une source VIDE, pas le message."""
    lu = _parse_log_line("10:00:00 | INFO | quelque chose s'est passé")
    assert lu is not None
    assert lu["source"] == ""
    assert lu["message"] == "quelque chose s'est passé"


def test_le_module_survit_a_un_deux_points_dans_le_message():
    ligne = "10:00:00 | INFO     | bot.main:10 | url=http://host:8080/path"
    lu = _parse_log_line(ligne)
    assert lu is not None
    assert lu["source"] == "bot.main"
    assert lu["message"] == "url=http://host:8080/path"


def test_le_sink_loguru_rend_les_memes_champs_que_le_fichier():
    """L'historique relu et le direct alimentent le MÊME panneau.

    Si les deux ne portaient pas les mêmes clés, les lignes d'avant l'ouverture
    de la page seraient invisibles à tous les filtres — et rien ne le dirait.
    """
    import inspect

    from bot.dashboard.routes import sse

    code = inspect.getsource(sse._log_sink)
    for champ in ("level", "message", "time", "source"):
        assert f'"{champ}"' in code, f"le sink n'émet pas {champ}"


# ── Le regroupement ─────────────────────────────────────────────────────────

def test_deux_occurrences_qui_ne_different_que_par_un_id_se_rejoignent():
    a = _cle_de_groupe("tâche 4173 échouée : Row object has no attribute 'get'")
    b = _cle_de_groupe("tâche 9982 échouée : Row object has no attribute 'get'")
    assert a == b


def test_le_pseudo_entre_guillemets_ne_separe_pas_deux_fois_la_meme_panne():
    a = _cle_de_groupe("tâche « rappeler à KingsRequin » — sqlite3.Row")
    b = _cle_de_groupe("tâche « rappeler à Azrael » — sqlite3.Row")
    assert a == b


def test_deux_pannes_distinctes_restent_distinctes():
    """Sur-grouper serait pire que sous-grouper : ça cacherait une panne."""
    a = _cle_de_groupe("OpenAI call failed: timeout")
    b = _cle_de_groupe("Twitch token refresh failed")
    assert a != b


# ── La route ────────────────────────────────────────────────────────────────

class _Requete:
    """La route ne lit rien de la requête — elle lit le disque."""


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """Un `logs/<jour>/app.log` bidon, pointé par `_find_latest_log`."""
    fichier = tmp_path / "app.log"

    def _poser(lignes: list[str]) -> None:
        fichier.write_text("\n".join(lignes), encoding="utf-8")
        monkeypatch.setattr(
            "bot.dashboard.routes.sse._find_latest_log", lambda: fichier
        )

    return _poser


async def test_les_repetitions_sont_comptees(journal):
    journal([
        "10:00:00 | ERROR    | bot.actions:12 | tâche 1 — Row has no attribute 'get'",
        "11:00:00 | INFO     | bot.main:3 | tout va bien",
        "12:00:00 | ERROR    | bot.actions:12 | tâche 2 — Row has no attribute 'get'",
        "13:30:00 | ERROR    | bot.actions:12 | tâche 3 — Row has no attribute 'get'",
    ])
    d = await journal_erreurs(_Requete())

    assert len(d["groupes"]) == 1
    groupe = d["groupes"][0]
    assert groupe["fois"] == 3
    assert groupe["source"] == "bot.actions"
    # L'horodatage affiché et le message affiché doivent désigner LA MÊME
    # occurrence — la dernière.
    assert groupe["derniere"] == "13:30:00"
    assert "tâche 3" in groupe["message"]


async def test_les_niveaux_sont_comptes_sur_tout_le_fichier(journal):
    journal([
        "10:00:00 | INFO     | bot.main:3 | a",
        "10:00:01 | INFO     | bot.main:3 | b",
        "10:00:02 | WARNING  | bot.main:3 | c",
        "10:00:03 | ERROR    | bot.main:3 | d",
    ])
    d = await journal_erreurs(_Requete())
    assert d["niveaux"] == {"INFO": 2, "WARNING": 1, "ERROR": 1}
    assert d["lignes"] == 4


async def test_le_plus_frequent_passe_devant(journal):
    journal([
        "10:00:00 | ERROR | bot.a:1 | rare",
        "10:00:01 | ERROR | bot.b:1 | fréquent",
        "10:00:02 | ERROR | bot.b:1 | fréquent",
    ])
    d = await journal_erreurs(_Requete())
    assert [g["fois"] for g in d["groupes"]] == [2, 1]
    assert d["groupes"][0]["source"] == "bot.b"


async def test_deux_modules_ne_se_melangent_pas(journal):
    """Le même message depuis deux modules = deux pannes, pas une."""
    journal([
        "10:00:00 | ERROR | bot.discord.handlers:1 | connexion perdue",
        "10:00:01 | ERROR | bot.twitch.bot:1 | connexion perdue",
    ])
    d = await journal_erreurs(_Requete())
    assert len(d["groupes"]) == 2


async def test_un_journal_absent_ne_pretend_pas_zero_erreur(monkeypatch):
    monkeypatch.setattr("bot.dashboard.routes.sse._find_latest_log", lambda: None)
    d = await journal_erreurs(_Requete())
    assert d["groupes"] == []
    assert d["fichier"] is None


async def test_un_journal_illisible_le_dit(tmp_path, monkeypatch):
    """Un zéro faux est pire qu'une absence avouée : la route doit AVOUER."""
    fichier = tmp_path / "app.log"
    fichier.write_text("10:00:00 | ERROR | bot.a:1 | x", encoding="utf-8")
    monkeypatch.setattr("bot.dashboard.routes.sse._find_latest_log", lambda: fichier)

    def _refuser(*a, **k):
        raise PermissionError("interdit")

    monkeypatch.setattr("pathlib.Path.read_text", _refuser)
    d = await journal_erreurs(_Requete())
    assert d["erreur"] == "journal illisible"


async def test_le_nombre_de_groupes_est_borne(journal):
    journal([f"10:00:{i:02d} | ERROR | bot.m{i}:1 | panne {chr(97 + i)}"
             for i in range(30)])
    d = await journal_erreurs(_Requete(), max_groupes=5)
    assert len(d["groupes"]) == 5
    # `0` ne doit pas se traduire en `[:0]`, c'est-à-dire en « aucune erreur »
    # sur un journal qui en porte trente. Le piège exact déjà payé sur
    # `/logs/history`, où `?lines=0` rendait le fichier ENTIER.
    zero = await journal_erreurs(_Requete(), max_groupes=0)
    assert len(zero["groupes"]) == 1
