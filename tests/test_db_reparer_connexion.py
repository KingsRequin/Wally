"""Une connexion qui ne sait plus écrire doit être REMPLACÉE, pas subie.

Vécu deux fois : le 2026-08-30 pendant dix heures, le 2026-09-18 pendant une
heure. Un curseur de lecture resté ouvert accroche la connexion à un vieil
instantané WAL ; dès qu'une AUTRE connexion valide quelque chose, SQLite refuse
toutes ses écritures par « database is locked », instantanément — sans consommer
le `busy_timeout` — et pour toujours. Le fichier, lui, n'est verrouillé pour
personne : c'est ce qui rendait le diagnostic faux.

Ces tests reproduisent exactement cet état, puis vérifient que
`reparer_connexion()` en sort. C'est le seul chemin qui en sorte sans
redémarrer le processus : ni `rollback()` ni la fermeture d'un AUTRE curseur
n'y suffisent.

Le montage est écrit en toutes lettres dans chaque test plutôt qu'en fixture :
une fixture asynchrone n'ouvre pas la connexion dans la même boucle que le
test, et l'empoisonnement ne s'y reproduit pas — un test vert dirait alors le
contraire de la vérité.
"""
from __future__ import annotations

import sqlite3

import aiosqlite
import pytest
from loguru import logger

from bot.db.database import Database

_INSERT = (
    "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, "
    "curiosity, boredom) VALUES (?, 0, 0, 0, 0, 0)"
)


async def _base_peuplee(tmp_path) -> tuple[Database, str]:
    """Une base avec de quoi parcourir : un SELECT sur une table vide s'épuise
    du premier coup et n'accroche aucun instantané."""
    chemin = str(tmp_path / "poison.db")
    db = await Database.create(chemin)
    for i in range(200):
        await db.execute(_INSERT, (float(i),))
    return db, chemin


async def _empoisonner(db: Database, chemin: str) -> tuple[aiosqlite.Connection, object]:
    """Épingle un instantané périmé sur la connexion partagée de `db`.

    Le curseur est RENDU à l'appelant, et pas seulement créé : dès que plus
    personne ne le référence, CPython le libère, le statement est réinitialisé
    et l'instantané se relâche. En prod c'est exactement l'inverse qui s'est
    produit — quelque chose le tenait en vie, et l'état a duré une heure.
    """
    curseur = await db._conn.execute("SELECT * FROM emotion_history")
    await curseur.fetchone()          # curseur NON épuisé : l'instantané tient

    autre = await aiosqlite.connect(chemin)
    await autre.execute(_INSERT, (1000.0,))
    await autre.commit()              # l'instantané de `db` devient périmé
    return autre, curseur


async def test_un_curseur_oublie_condamne_les_ecritures(tmp_path):
    """L'état de départ : la panne se reproduit, sinon le correctif ne prouve rien."""
    db, chemin = await _base_peuplee(tmp_path)
    autre, _curseur = await _empoisonner(db, chemin)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        await db.execute(_INSERT, (2000.0,))
    await autre.close()
    await db.close()


async def test_le_fichier_lui_meme_n_est_verrouille_pour_personne(tmp_path):
    """« database is locked » SANS verrou de fichier — d'où trois diagnostics ratés."""
    db, chemin = await _base_peuplee(tmp_path)
    autre, _curseur = await _empoisonner(db, chemin)
    temoin = sqlite3.connect(chemin, timeout=0)
    temoin.execute("PRAGMA busy_timeout=0")
    temoin.execute("BEGIN IMMEDIATE")   # ne lève pas : le fichier est libre
    temoin.execute("ROLLBACK")
    temoin.close()
    await autre.close()
    await db.close()


async def test_reparer_connexion_rend_les_ecritures(tmp_path):
    """Le correctif : lâcher la connexion entière, faute de savoir quel curseur."""
    db, chemin = await _base_peuplee(tmp_path)
    autre, _curseur = await _empoisonner(db, chemin)
    assert await db.reparer_connexion() is True
    await db.execute(_INSERT, (3000.0,))
    lignes = await db.fetch_all(
        "SELECT snapshot_at FROM emotion_history WHERE snapshot_at = 3000.0")
    assert len(lignes) == 1
    await autre.close()
    await db.close()


async def test_la_connexion_reparee_garde_ses_reglages(tmp_path):
    """WAL et `busy_timeout` sont des réglages DE CONNEXION : ils se reposent."""
    db, _ = await _base_peuplee(tmp_path)
    assert await db.reparer_connexion() is True
    mode = await db.fetch_one("PRAGMA journal_mode")
    assert mode[0].lower() == "wal"
    delai = await db.fetch_one("PRAGMA busy_timeout")
    assert delai[0] == 10000
    await db.close()


async def test_la_reparation_nomme_le_curseur_oublie(tmp_path):
    """Sans ce relevé, deux pannes ont passé sans qu'on sache QUI accrochait.

    SQLite ne désigne pas le curseur fautif ; sa `description` porte en
    revanche les colonnes de la requête, ce qui suffit à retrouver le site.
    """
    db, chemin = await _base_peuplee(tmp_path)
    autre, _curseur = await _empoisonner(db, chemin)
    vus: list[str] = []
    sid = logger.add(lambda m: vus.append(str(m)), level="ERROR")
    try:
        assert await db.reparer_connexion() is True
    finally:
        logger.remove(sid)
    releve = "\n".join(vus)
    assert "Curseur encore ouvert" in releve
    assert "snapshot_at" in releve      # les colonnes de `SELECT * FROM emotion_history`
    await autre.close()
    await db.close()
