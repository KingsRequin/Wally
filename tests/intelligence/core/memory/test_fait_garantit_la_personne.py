"""Un fait écrit sur quelqu'un garantit sa ligne `memory_users`.

Mesuré le 2026-09-17 : 54 identités portaient des faits sans aucune ligne
`memory_users` (dont `twitch:502342016`, 383 faits). La ligne n'était posée que
par les handlers de RÉPONSE ; l'import d'archives PhantomBot, la perception
passive Discord et les descriptions d'images écrivaient des faits sans elle, et
la personne disparaissait de `list_memory_users()` — donc de la résolution des
tiers du FactExtractor et de la liste des personnes du dashboard.
"""
from datetime import datetime, timezone

import aiosqlite

from bot.intelligence.memory.facts import AtomicFact, FactCategory, SQLiteFactStore


def _fait(user_id: str, subject: str | None = None, quand: datetime | None = None) -> AtomicFact:
    fait = AtomicFact(
        user_id=user_id, content=f"{subject or 'quelqu’un'} aime le thé",
        category=FactCategory.PREF, subject=subject,
    )
    if quand is not None:
        fait.created_at = fait.last_seen_at = quand
    return fait


async def _ligne(path: str, user_id: str):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "SELECT platform, username, last_updated FROM memory_users WHERE user_id = ?",
            (user_id,),
        )
        return await cur.fetchone()


async def test_un_fait_cree_la_personne_datee_du_fait(tmp_db_path):
    quand = datetime(2026, 2, 16)
    await SQLiteFactStore(tmp_db_path).add(_fait("twitch:502342016", "elhya__", quand))

    ligne = await _ligne(tmp_db_path, "twitch:502342016")
    assert ligne is not None
    platform, username, last_updated = ligne
    assert platform == "twitch"
    assert username == "elhya__"
    # Datée du FAIT, pas de l'écriture : une archive de février ne fait pas
    # passer la personne pour « vue à l'instant » (salut de l'overlay, habitués
    # absents du journal).
    assert last_updated == quand.replace(tzinfo=timezone.utc).timestamp()


async def test_une_personne_connue_n_est_pas_modifiee(tmp_db_path):
    async with aiosqlite.connect(tmp_db_path) as db:
        await db.execute(
            "INSERT INTO memory_users(user_id, platform, last_updated, username) "
            "VALUES ('discord:610550333042589752', 'discord', 123.0, 'KingsRequin')"
        )
        await db.commit()

    await SQLiteFactStore(tmp_db_path).add(_fait("discord:610550333042589752", "kingsrequin"))

    assert await _ligne(tmp_db_path, "discord:610550333042589752") == (
        "discord", "KingsRequin", 123.0,
    )


async def test_les_faits_de_wally_ne_creent_personne(tmp_db_path):
    store = SQLiteFactStore(tmp_db_path)
    await store.add(_fait("wally:self"))
    await store.add(_fait("wally:emotes"))

    assert await _ligne(tmp_db_path, "wally:self") is None
    assert await _ligne(tmp_db_path, "wally:emotes") is None


async def test_un_inconnu_est_range_sans_pseudo(tmp_db_path):
    """Même forme que les 94 `unknown:` déjà en base : le pseudo EST la clé,
    et `list_unknown_users()` les lit là pour l'écran de rattachement."""
    await SQLiteFactStore(tmp_db_path).add(_fait("unknown:azshona", "Azshona"))

    platform, username, _ = await _ligne(tmp_db_path, "unknown:azshona")
    assert (platform, username) == ("unknown", None)


async def test_un_rattachement_cree_la_personne_cible(tmp_db_path):
    store = SQLiteFactStore(tmp_db_path)
    await store.add(_fait("unknown:elya", "Elya"))

    assert await store.reassign_user("unknown:elya", "twitch:502342016") == 1

    ligne = await _ligne(tmp_db_path, "twitch:502342016")
    assert ligne is not None
    assert ligne[0] == "twitch"
