"""Une migration qui rate pour une VRAIE raison doit le dire.

`database.py` porte quinze migrations idempotentes, toutes du même moule :

    try:
        await conn.execute("ALTER TABLE x ADD COLUMN y ...")
        await conn.commit()
    except aiosqlite.OperationalError:
        pass          # colonne déjà présente

Le silence est juste pour le cas visé — rejouer un `ADD COLUMN` sur une base
déjà migrée lève forcément. Mais `OperationalError` couvre bien plus que ça :
table absente, base verrouillée, disque plein, SQL fautif. Toutes ces
pannes-là passaient pour « colonne déjà présente », et la colonne manquait
ensuite en silence — jusqu'à ce qu'une requête la demande, des semaines plus
tard, dans un tout autre morceau du code.

`migrer()` ne se tait donc que sur le motif attendu, et journalise le reste.
"""
import sqlite3

import aiosqlite
import pytest

from bot.db.database import migrer


@pytest.mark.asyncio
async def test_une_colonne_deja_presente_ne_dit_rien(tmp_path, capsys):
    chemin = str(tmp_path / "m.db")
    async with aiosqlite.connect(chemin) as conn:
        await conn.execute("CREATE TABLE t (a TEXT, b TEXT)")
        await conn.commit()
        # `b` existe déjà : c'est le cas NORMAL d'une base à jour.
        assert await migrer(conn, "ALTER TABLE t ADD COLUMN b TEXT") is False


@pytest.mark.asyncio
async def test_une_migration_neuve_s_applique(tmp_path):
    chemin = str(tmp_path / "m.db")
    async with aiosqlite.connect(chemin) as conn:
        await conn.execute("CREATE TABLE t (a TEXT)")
        await conn.commit()
        assert await migrer(conn, "ALTER TABLE t ADD COLUMN neuf TEXT") is True
        cur = await conn.execute("PRAGMA table_info(t)")
        colonnes = [r[1] for r in await cur.fetchall()]
        assert "neuf" in colonnes


@pytest.mark.asyncio
async def test_une_VRAIE_panne_est_journalisee(tmp_path):
    """Le cas qui motive tout : une table absente n'est pas « déjà migrée »."""
    from loguru import logger

    vues = []
    sink = logger.add(lambda m: vues.append((m.record["level"].name,
                                             m.record["message"])), level="WARNING")
    try:
        async with aiosqlite.connect(str(tmp_path / "m.db")) as conn:
            # `table_absente` n'existe pas : `OperationalError`, mais pas du
            # tout celle qu'on accepte de taire.
            assert await migrer(
                conn, "ALTER TABLE table_absente ADD COLUMN x TEXT") is False
    finally:
        logger.remove(sink)

    assert vues, "une migration cassée doit laisser une trace"
    niveau, message = vues[0]
    assert niveau == "WARNING"
    assert "table_absente" in message


@pytest.mark.asyncio
async def test_un_index_deja_cree_ne_dit_rien(tmp_path):
    """`CREATE INDEX IF NOT EXISTS` ne lève pas, mais le helper doit l'encaisser."""
    async with aiosqlite.connect(str(tmp_path / "m.db")) as conn:
        await conn.execute("CREATE TABLE t (a TEXT)")
        await conn.commit()
        assert await migrer(conn, "CREATE INDEX IF NOT EXISTS i ON t(a)") is True
        assert await migrer(conn, "CREATE INDEX IF NOT EXISTS i ON t(a)") is True


def test_le_motif_attendu_est_bien_celui_de_sqlite(tmp_path):
    """Ancre le message exact sur lequel `migrer()` se tait.

    Il vient de SQLite, pas de nous : si une version le reformulait, le helper
    se mettrait à crier sur des bases parfaitement saines. Ce test le dirait.
    """
    conn = sqlite3.connect(str(tmp_path / "a.db"))
    conn.execute("CREATE TABLE t (a TEXT)")
    with pytest.raises(sqlite3.OperationalError) as err:
        conn.execute("ALTER TABLE t ADD COLUMN a TEXT")
    assert "duplicate column name" in str(err.value).lower()
    conn.close()


@pytest.mark.asyncio
async def test_un_index_unique_sur_des_doublons_ne_casse_pas_le_boot(tmp_path):
    """`IntegrityError`, pas `OperationalError` — et le boot doit survivre.

    Les blocs d'origine attrapaient `Exception`. Restreindre le helper à
    `OperationalError` aurait fait crasher le démarrage sur une base portant
    déjà des doublons, en croyant resserrer la prise.
    """
    from loguru import logger

    vues = []
    sink = logger.add(lambda m: vues.append(m.record["message"]), level="WARNING")
    try:
        async with aiosqlite.connect(str(tmp_path / "m.db")) as conn:
            await conn.execute("CREATE TABLE t (a TEXT)")
            await conn.execute("INSERT INTO t VALUES ('x')")
            await conn.execute("INSERT INTO t VALUES ('x')")
            await conn.commit()
            # Ne lève pas : le boot continue, mais la trace existe.
            assert await migrer(conn, "CREATE UNIQUE INDEX i ON t(a)") is False
    finally:
        logger.remove(sink)

    assert vues and "UNIQUE INDEX" in vues[0]
