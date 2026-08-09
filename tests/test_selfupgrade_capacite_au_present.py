"""Une capacité livrée doit se dire au PRÉSENT, pas comme une demande passée.

Trois canaux disaient déjà à Wally qu'il possédait la capacité redemandée le
2026-08-09 : la table `pending_upgrades`, son prompt (« DÉJÀ LIVRÉE — tu l'as ») et
un fait mémoire à importance 0.9. Les trois ont échoué, parce que les trois parlent
la langue de la DEMANDE : « tu as demandé X, c'est livré ». Or une demande passée,
ça se requalifie — et c'est mot pour mot ce qu'il a fait (« la mienne est
différente »). Une description de son présent, non : il n'y a rien à distinguer de
soi-même.

D'où la colonne `capability` : à la livraison, la demande est reformulée en une
phrase de capacité à la première personne, et c'est ELLE qui va au prompt.
"""
import aiosqlite
import pytest

from bot.intelligence.reasoning_agent import ReasoningAgent
from bot.intelligence.upgrade_registry import DELIVERED, UpgradeRegistry, UpgradeRow
from tests.intelligence.test_phase6_upgrade_awareness import _PROMPTS
from tests.test_selfupgrade_historique_groupe import _ctx


async def _base_ancienne(tmp_path) -> str:
    """Une base au schéma d'AVANT la colonne `capability`."""
    chemin = str(tmp_path / "u.db")
    async with aiosqlite.connect(chemin) as c:
        await c.execute(
            """CREATE TABLE pending_upgrades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal TEXT NOT NULL, message_id TEXT, dm_channel_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL, decided_at TEXT)"""
        )
        await c.commit()
    return chemin


@pytest.mark.asyncio
async def test_la_colonne_capability_est_ajoutee_a_une_base_existante(tmp_path):
    """Wally tourne depuis des mois : la migration doit passer sur sa base."""
    from bot.db.schema_v2 import create_v2_tables

    chemin = await _base_ancienne(tmp_path)
    await create_v2_tables(chemin)

    async with aiosqlite.connect(chemin) as c:
        cur = await c.execute("PRAGMA table_info(pending_upgrades)")
        colonnes = {row[1] for row in await cur.fetchall()}
    assert "capability" in colonnes


@pytest.mark.asyncio
async def test_la_capacite_enregistree_ressort_avec_la_demande(tmp_path):
    from bot.db.schema_v2 import create_v2_tables

    chemin = await _base_ancienne(tmp_path)
    await create_v2_tables(chemin)
    reg = UpgradeRegistry(chemin)
    uid = await reg.record_request("recevoir les événements du stream Twitch")
    await reg.set_status(uid, DELIVERED)

    await reg.set_capability(uid, "Je reçois le chat du live et les événements de la chaîne.")

    (row,) = await reg.recent()
    assert row.capability == "Je reçois le chat du live et les événements de la chaîne."


def test_le_prompt_montre_la_capacite_plutot_que_la_demande():
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    ctx = _ctx(upgrade_requests=[UpgradeRow(
        id=19, proposal="Recevoir dans mon contexte les événements du stream Twitch d'Azraël",
        status=DELIVERED, created_at="2026-08-05T03:09", decided_at="2026-08-05T03:21",
        capability="Je vois le chat du live d'Azraël et je sais qui vient de s'abonner.",
    )])

    out = agent._format_context(ctx)

    assert "Je vois le chat du live" in out
    assert "Recevoir dans mon contexte" not in out, (
        "la formulation de la DEMANDE reste affichée alors qu'une capacité au "
        f"présent existe — c'est elle qui se requalifie.\n{out}"
    )


def test_le_prompt_retombe_sur_la_demande_sans_capacite():
    """Les 14 demandes déjà livrées n'ont pas de `capability` : rien ne doit
    disparaître de son prompt pour autant."""
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    ctx = _ctx(upgrade_requests=[UpgradeRow(
        id=17, proposal="chercher dans l'historique des conversations",
        status=DELIVERED, created_at="2026-08-04T15:25", decided_at=None,
    )])
    assert "historique des conversations" in agent._format_context(ctx)


@pytest.mark.asyncio
async def test_la_livraison_fait_rediger_la_phrase_de_capacite(tmp_path):
    """Le LLM secondaire reformule à la livraison — sinon la colonne reste vide et
    on retombe sur la méthode manuelle, qui a échoué 12 fois sur 14."""
    import types
    from unittest.mock import AsyncMock, MagicMock

    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.self_fix import SelfFix

    chemin = await _base_ancienne(tmp_path)
    await create_v2_tables(chemin)
    reg = UpgradeRegistry(chemin)
    uid = await reg.record_request("recevoir les événements du stream Twitch d'Azraël")

    bot = MagicMock()
    bot.config = types.SimpleNamespace(
        bot=types.SimpleNamespace(owner_discord_id="1", name="Wally", creator_name="KingsRequin")
    )
    bot.llm_secondary.complete = AsyncMock(
        return_value="Je vois le chat du live d'Azraël en direct."
    )
    fixer = SelfFix(MagicMock(), bot, poll_interval=0.0, registry=reg)

    await fixer._set_status(uid, DELIVERED)

    (row,) = await reg.recent()
    assert row.capability == "Je vois le chat du live d'Azraël en direct."
    assert bot.llm_secondary.complete.await_count == 1
