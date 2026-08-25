"""Phase 12 : modèles non conversationnels offerts, but bloqué à vie, pseudos courts."""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest

from bot.core.account_linker import matches_name
from bot.discord.commands.setup.utils import is_valid_model


# ── Le menu de modèles n'offre plus que du conversationnel ───────────────────
#
# L'exclusion ne couvrait que realtime/preview/audio/vision, et l'inclusion
# testait `o1`/`o3`/`o4` en sous-chaîne non ancrée. `gpt-image-1.5` — le modèle
# IMAGE du projet — passait donc le filtre, comme `gpt-4o-transcribe`,
# `gpt-4o-mini-tts` et `gpt-3.5-turbo-instruct`. En choisir un cassait le LLM en
# silence, et le choix était persisté par `config.save()`.

@pytest.mark.parametrize("modele", [
    "gpt-image-1.5", "gpt-image-1", "gpt-4o-transcribe", "gpt-4o-mini-tts",
    "gpt-3.5-turbo-instruct", "text-embedding-3-large", "omni-moderation-latest",
    "gpt-4o-realtime-preview", "gpt-4o-audio-preview",
    "deepseek-vision-preview", "deepseek-embedding",
])
def test_un_modele_non_conversationnel_est_ecarte(modele):
    assert is_valid_model(modele) is False


# Ce cas a changé DEUX fois de sens, toujours pour la même raison de fond : le
# menu doit refléter ce que `create_llm_client` sait construire, ni plus ni
# moins. `gpt-*` était offert quand le texte passait par OpenAI, écarté quand la
# factory s'est restreinte à DeepSeek, et redevient offert le 2026-08-25 quand
# `openai` réintègre `SUPPORTED_TEXT_PROVIDERS`. Ce n'est pas la marque du
# fournisseur qui décide — c'est la factory.
@pytest.mark.parametrize(
    "modele",
    ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat",
     "gpt-5.6-luna", "gpt-5-mini", "gpt-5.4"],
)
def test_un_modele_conversationnel_reste_offert(modele):
    assert is_valid_model(modele) is True


@pytest.mark.parametrize(
    "modele",
    ["claude-haiku-4-5", "mistral-small-4", "gemini-2.5-flash", "grok-4.3", "o3-mini"],
)
def test_un_modele_d_un_fournisseur_non_constructible_est_ecarte(modele):
    assert is_valid_model(modele) is False


# ── Un pseudo de deux lettres ne matche plus tout le monde ───────────────────

def test_les_deux_cotes_sont_bornes_a_trois_caracteres():
    """Seul le surnom cherché l'était : dans la branche `a in b`, c'est le nom du
    CANDIDAT qui sert de sous-chaîne, sans plancher. Or, comme le dit le
    docstring, personne ne valide derrière — la confusion part à l'écran."""
    # « al » était une sous-chaîne d'« alexandre », donc un match, alors que
    # Jaro-Winkler les sépare (0.79 < 0.85).
    assert matches_name("Al", "Alexandre") is False
    assert matches_name("Ed", "Edouard") is False
    # « Bo »/« Bob » reste un match, mais par le flou (0.91) — un autre
    # mécanisme, avec son propre seuil, qu'on ne touche pas ici.
    assert matches_name("Bo", "Bob") is True


def test_la_sous_chaine_utile_fonctionne_toujours():
    """« requin » n'a aucun préfixe commun avec « KingsRequin » : c'est le cas
    que la sous-chaîne existe pour rattraper."""
    assert matches_name("KingsRequin", "requin") is True
    assert matches_name("Azrael", "azra") is True


# ── Une demande d'auto-modif ne bloque plus un but à vie ─────────────────────

@pytest.fixture
async def registre(tmp_path):
    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.upgrade_registry import UpgradeRegistry

    chemin = str(tmp_path / "wally.db")
    await create_v2_tables(chemin)      # `pending_upgrades` vit dans le schéma V2
    return UpgradeRegistry(chemin)


async def test_une_demande_en_suspens_est_rouverte_au_demarrage(registre):
    """`request_upgrade` attend l'autorisation jusqu'à 72 h via un `wait_for` :
    tout redémarrage pendant la fenêtre — et un self-fix se TERMINE par un
    `docker_rebuild` — perdait l'attente sans repasser par le `TimeoutError` qui
    aurait posé ABANDONED. La ligne restait REQUESTED, donc `_BLOCKING`, et
    `find_similar` écartant tout ce qui dépasse un Jaccard de 0.3, le but — et
    tout but proche — devenait irrattrapable, en silence."""
    import aiosqlite

    from bot.intelligence.upgrade_registry import ABANDONED, REQUESTED

    uid = await registre.record_request("corriger la détection de spam")
    vieille = (datetime.utcnow() - timedelta(hours=100)).isoformat()
    async with aiosqlite.connect(registre._db_path) as db:
        await db.execute("UPDATE pending_upgrades SET created_at = ? WHERE id = ?", (vieille, uid))
        await db.commit()

    assert await registre.reconcile_stale(older_than_hours=72) == 1

    async with aiosqlite.connect(registre._db_path) as db:
        async with db.execute("SELECT status FROM pending_upgrades WHERE id = ?", (uid,)) as cur:
            statut = (await cur.fetchone())[0]
    assert statut == ABANDONED != REQUESTED


async def test_une_demande_recente_nest_pas_touchee(registre):
    await registre.record_request("un but tout frais")
    assert await registre.reconcile_stale(older_than_hours=72) == 0


def test_sans_owner_la_demande_est_close():
    """Le retour anticipé « pas d'owner configuré » ne posait aucun statut : la
    ligne venait pourtant d'être inscrite en REQUESTED."""
    from bot.intelligence.self_fix import SelfFix

    code = inspect.getsource(SelfFix._run_upgrade)
    debut = code[: code.index("owner = await")]
    assert "self._set_status(upgrade_id, ABANDONED)" in debut


# ── L'enregistrement d'une blague ne se perd plus ────────────────────────────

def test_la_tache_denregistrement_de_blague_est_retenue():
    """La boucle ne garde qu'une référence FAIBLE : la tâche pouvait être
    collectée avant la fin, et son exception ne se manifestait qu'en « Task
    exception was never retrieved » au ramassage, hors de loguru."""
    from bot.core.reaction_tracker import ReactionTracker

    code = inspect.getsource(ReactionTracker)
    assert "self._tasks.add(task)" in code
    assert "add_done_callback" in code


def test_la_doc_des_jours_correspond_au_fichier():
    """`CLAUDE.md` annonçait des clés anglaises ; le fichier et le code sont en
    français. Quiconque suivait la doc créait des sections jamais lues."""
    from pathlib import Path

    doc = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "## lundi … dimanche" in doc
    assert "## monday" not in doc
