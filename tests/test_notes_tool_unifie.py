"""Les trois outils de mémoire n'ont qu'UN exécutant, et leur définition vit avec.

`bot/tools/notes_tool.py` a été créé le 2026-08-26 sur ce constat, écrit dans
son propre en-tête : « L'exécution vivait en TROIS copies (Discord, Twitch,
vocal). Les garder séparées, c'est se condamner à poser le prochain garde-fou
deux fois sur trois. »

Seul `save_persistent_note` avait alors été sorti. Relevé le 2026-08-28 :
`delete_persistent_note` était encore en trois copies STRICTEMENT identiques, et
`save_user_memory` en trois copies dont la garde anti-surnom — celle-là même qui
avait motivé le module — était recopiée à chaque fois.

La définition, elle, vivait dans `bot/discord/handlers.py` : les deux moitiés du
même outil, dans deux dossiers différents, dont un adapter de plateforme que
l'autre plateforme importait.
"""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.surnoms import REFUS as REFUS_SURNOM
from bot.tools.notes_tool import (
    NOTE_TOOLS,
    run_delete_note_tool,
    run_save_user_memory_tool,
)


def test_la_definition_vit_avec_l_execution():
    noms = {t["function"]["name"] for t in NOTE_TOOLS}
    assert noms == {"save_persistent_note", "delete_persistent_note", "save_user_memory"}


def test_la_definition_ne_vit_PLUS_dans_l_adapter_discord():
    """Un adapter de plateforme n'est pas la bibliothèque commune de l'autre."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "bot/discord/handlers.py").read_text(encoding="utf-8")
    assert "_NOTE_TOOLS = [" not in src


# ── suppression d'une note ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_suppression_dit_ce_qui_s_est_passe():
    db = MagicMock()
    db.delete_persistent_note = AsyncMock(return_value=True)
    rendu = json.loads(await run_delete_note_tool(db, {"title": "Journal de Wally"}))

    db.delete_persistent_note.assert_awaited_once_with("Journal de Wally")
    assert rendu["status"] == "ok"


@pytest.mark.asyncio
async def test_une_note_introuvable_n_est_pas_une_reussite():
    """Wally annoncerait « supprimée » sur une note toujours en place."""
    db = MagicMock()
    db.delete_persistent_note = AsyncMock(return_value=False)
    rendu = json.loads(await run_delete_note_tool(db, {"title": "fantôme"}))

    assert rendu["status"] == "not_found"


@pytest.mark.asyncio
async def test_un_titre_vide_ne_part_pas_en_base():
    db = MagicMock()
    db.delete_persistent_note = AsyncMock()
    rendu = json.loads(await run_delete_note_tool(db, {}))

    db.delete_persistent_note.assert_not_awaited()
    assert rendu["status"] == "error"


# ── souvenir sur une personne ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_souvenir_part_avec_l_id_BRUT_et_son_origine():
    memoire = MagicMock()
    memoire.add = AsyncMock()
    rendu = json.loads(await run_save_user_memory_tool(
        memoire, {"content": "il joue Fuse"},
        platform="twitch", user_id="123", username="Azraël", origin="Twitch/azrael_ttv",
    ))

    memoire.add.assert_awaited_once_with(
        "twitch", "123", "il joue Fuse",
        username="Azraël", origin="Twitch/azrael_ttv",
    )
    assert rendu["status"] == "ok"


@pytest.mark.asyncio
async def test_la_garde_anti_surnom_tient_sur_CE_chemin_aussi():
    """La garde était recopiée dans les trois adapters. Un seul écrivain, un
    seul endroit où poser le prochain garde-fou."""
    memoire = MagicMock()
    memoire.add = AsyncMock()
    rendu = json.loads(await run_save_user_memory_tool(
        memoire, {"content": "KingsRequin se fait appeler petit chevreuil"},
        platform="discord", user_id="610550333042589752",
        username="KingsRequin", origin="#chambre",
    ))

    memoire.add.assert_not_awaited()
    assert rendu["status"] == "denied"
    assert rendu["message"] == REFUS_SURNOM


@pytest.mark.asyncio
async def test_un_contenu_vide_ne_va_pas_en_memoire():
    memoire = MagicMock()
    memoire.add = AsyncMock()
    rendu = json.loads(await run_save_user_memory_tool(
        memoire, {"content": "   "},
        platform="discord", user_id="1", username="x", origin="y",
    ))

    memoire.add.assert_not_awaited()
    assert rendu["status"] == "error"
