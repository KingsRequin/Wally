# tests/test_db_fusion_comptes.py
"""La liaison de deux comptes doit DÉPLACER la mémoire, pas seulement rediriger.

Vécu le 2026-09-04 : `MemoryService._user_id()` résout l'alias vers le canonical
et `search`/`get_all`/`add` passent tous par lui — mais `_merge_memories()` ne
déplaçait plus rien depuis la migration V2. Lier deux comptes rendait donc les
faits de l'alias INVISIBLES, sans une seule erreur. Mesuré : 427 faits sur trois
personnes.
"""
import pytest

from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables


async def _base(tmp_path):
    chemin = str(tmp_path / "t.db")
    db = await Database.create(chemin)
    await create_v2_tables(chemin)
    return db


async def _fait(db, user_id: str, contenu: str, statut: str = "active") -> None:
    await db.execute(
        "INSERT INTO atomic_facts (user_id, content, category, status, "
        "created_at, last_seen_at) VALUES (?, ?, 'FAIT', ?, '2026-01-01', '2026-01-01')",
        (user_id, contenu, statut),
    )


async def _nb(db, user_id: str) -> int:
    row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM atomic_facts WHERE user_id = ?", (user_id,)
    )
    return row["n"]


@pytest.mark.asyncio
async def test_les_faits_de_l_alias_rejoignent_le_canonical(tmp_path):
    db = await _base(tmp_path)
    for i in range(3):
        await _fait(db, "twitch:999", f"fait twitch {i}")
    await _fait(db, "discord:111", "fait discord")

    bilan = await db.merge_user_facts("discord:111", "twitch:999")

    assert await _nb(db, "discord:111") == 4
    assert await _nb(db, "twitch:999") == 0
    assert bilan["atomic_facts"] == 3
    await db.close()


@pytest.mark.asyncio
async def test_un_alias_vide_ne_change_rien(tmp_path):
    """Le cas COURANT : on lie tôt, l'alias n'a rien. Aucun déplacement."""
    db = await _base(tmp_path)
    await _fait(db, "discord:111", "fait discord")

    bilan = await db.merge_user_facts("discord:111", "twitch:999")

    assert await _nb(db, "discord:111") == 1
    assert bilan["atomic_facts"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_un_doublon_exact_reste_sur_l_alias_sans_faire_echouer(tmp_path):
    """`idx_facts_actif_unique` porte sur (user_id, category, contenu) si actif.

    Le doublon ne peut pas rejoindre le canonical — mais l'information y est
    DÉJÀ. On ne supprime rien, et surtout on ne fait pas échouer la liaison
    entière pour un fait redondant.
    """
    db = await _base(tmp_path)
    await _fait(db, "discord:111", "aime les chats")
    await _fait(db, "twitch:999", "aime les chats")
    await _fait(db, "twitch:999", "joue à Apex")

    bilan = await db.merge_user_facts("discord:111", "twitch:999")

    assert await _nb(db, "discord:111") == 2       # le sien + « joue à Apex »
    assert await _nb(db, "twitch:999") == 1        # le doublon, intact
    assert bilan["atomic_facts"] == 1
    assert bilan["doublons"] == 1
    await db.close()


@pytest.mark.asyncio
async def test_le_portrait_le_plus_riche_gagne(tmp_path):
    """`user_profiles.user_id` est CLÉ PRIMAIRE : un UPDATE nu échouerait."""
    db = await _base(tmp_path)
    await db.execute(
        "INSERT INTO user_profiles (user_id, portrait, updated_at) VALUES (?, ?, ?)",
        ("discord:111", "court", "2026-01-01"),
    )
    await db.execute(
        "INSERT INTO user_profiles (user_id, portrait, updated_at) VALUES (?, ?, ?)",
        ("twitch:999", "un portrait beaucoup plus long et détaillé", "2026-01-01"),
    )

    await db.merge_user_facts("discord:111", "twitch:999")

    row = await db.fetch_one(
        "SELECT portrait FROM user_profiles WHERE user_id = ?", ("discord:111",)
    )
    assert row["portrait"] == "un portrait beaucoup plus long et détaillé"
    reste = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM user_profiles WHERE user_id = ?", ("twitch:999",)
    )
    assert reste["n"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_le_portrait_du_canonical_est_garde_s_il_est_plus_riche(tmp_path):
    db = await _base(tmp_path)
    await db.execute(
        "INSERT INTO user_profiles (user_id, portrait, updated_at) VALUES (?, ?, ?)",
        ("discord:111", "un portrait long et bien fourni", "2026-01-01"),
    )
    await db.execute(
        "INSERT INTO user_profiles (user_id, portrait, updated_at) VALUES (?, ?, ?)",
        ("twitch:999", "bref", "2026-01-01"),
    )

    await db.merge_user_facts("discord:111", "twitch:999")

    row = await db.fetch_one(
        "SELECT portrait FROM user_profiles WHERE user_id = ?", ("discord:111",)
    )
    assert row["portrait"] == "un portrait long et bien fourni"
    await db.close()


@pytest.mark.asyncio
async def test_les_questions_en_attente_suivent_aussi(tmp_path):
    db = await _base(tmp_path)
    await db.execute(
        "INSERT INTO memory_questions (user_id, memory_text, question, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("twitch:999", "il joue à Apex", "tu joues encore à Apex ?", "2026-01-01"),
    )

    bilan = await db.merge_user_facts("discord:111", "twitch:999")

    row = await db.fetch_one(
        "SELECT user_id FROM memory_questions WHERE question = ?",
        ("tu joues encore à Apex ?",),
    )
    assert row["user_id"] == "discord:111"
    assert bilan["memory_questions"] == 1
    await db.close()


@pytest.mark.asyncio
async def test_fusionner_sur_soi_meme_ne_fait_rien(tmp_path):
    db = await _base(tmp_path)
    await _fait(db, "discord:111", "un fait")

    bilan = await db.merge_user_facts("discord:111", "discord:111")

    assert await _nb(db, "discord:111") == 1
    assert bilan["atomic_facts"] == 0
    await db.close()
