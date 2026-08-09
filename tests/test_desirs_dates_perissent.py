"""Un désir qui porte une échéance doit naître avec sa date de péremption.

Relevé le 2026-08-09 : six désirs « Lire le blog post Hytale **aujourd'hui** à 16h »
étaient encore actifs 18 à 26 jours après l'heure dite, plus trois « ressortir
l'actu … **ce soir** » vieux de 31 jours. Les 156 désirs actifs avaient tous
`expires_at = NULL`.

Tout existait pourtant : la colonne, `archive_expired()` qui la consomme dans la
passe nocturne, `_compute_expiry()` qui force un TTL dès qu'un marqueur temporel
apparaît dans le texte (« ce soir », « aujourd'hui », « demain »), et depuis le
commit 546797f un filtre sur les trois chemins de lecture — donc un désir périmé
n'atteint même plus le prompt. Il manquait seulement l'appel à la création.
"""
import pytest

from bot.intelligence.memory.facts import FactCategory, SQLiteFactStore


async def _dispatcher(tmp_path):
    from unittest.mock import MagicMock

    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.action_dispatcher import ActionDispatcher

    chemin = str(tmp_path / "d.db")
    await create_v2_tables(chemin)
    store = SQLiteFactStore(chemin)
    disp = ActionDispatcher.__new__(ActionDispatcher)
    disp._facts = store
    disp._feed = None
    disp._bot = MagicMock()
    return disp, chemin


async def _peremptions(chemin) -> list[str | None]:
    """`expires_at` des désirs, lu en SQL direct.

    `search_by_category` consomme bien la colonne dans son `WHERE` mais ne la liste
    pas dans son `SELECT` : passer par elle rendrait ce test aveugle à ce qu'il teste.
    """
    import aiosqlite

    async with aiosqlite.connect(chemin) as db:
        cur = await db.execute(
            "SELECT expires_at FROM atomic_facts WHERE category = ?",
            (FactCategory.DESIRE.value,),
        )
        return [r[0] for r in await cur.fetchall()]


@pytest.mark.asyncio
async def test_un_desir_pour_ce_soir_perime_de_lui_meme(tmp_path):
    disp, chemin = await _dispatcher(tmp_path)

    await disp._act(
        "create_desire",
        {"content": "Ressortir l'actu Sony ce soir dans #discussions quand le canal sera vivant"},
    )

    (peremption,) = await _peremptions(chemin)
    assert peremption is not None, (
        "un désir daté naît sans péremption — il traînera des semaines après l'heure dite"
    )


@pytest.mark.asyncio
async def test_un_desir_sans_echeance_reste_durable(tmp_path):
    """« Mieux connaître Raiky » n'a pas de date : rien ne doit l'effacer."""
    disp, chemin = await _dispatcher(tmp_path)

    await disp._act(
        "create_desire",
        {"content": "Mieux connaître Raiky, au-delà de son humour pince-sans-rire"},
    )

    (peremption,) = await _peremptions(chemin)
    assert peremption is None
