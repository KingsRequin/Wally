"""Une question de suivi doit atteindre le PROMPT, pas seulement le dashboard.

La chaîne est complète depuis mars 2026 : la passe nocturne crée les questions
(`MemoryConsolidator._apply_cleanup_verdict`), la base les range avec leur
priorité, `get_pending_question()` sait choisir la plus importante en
respectant les 3 tentatives et la temporisation de 24 h,
`increment_question_attempts()` compte, `resolve_question()` clôt, et le
dashboard les affiche.

Il manquait le maillon du milieu. Le 2026-06-20, `ad975eb3` — un refactor de
migration mémoire V1→V2 — a retiré l'injection au prompt, sans le dire dans son
message. Wally n'a plus jamais posé de question de suivi.

Deux relectures ultérieures ont pourtant traité la fonctionnalité comme
VIVANTE :

  · le 2026-08-10, `9c845c60` corrige `get_pending_question` en invoquant
    « 44 questions de plus de 30 jours, réinjectées au prompt chaque nuit » —
    un symptôme devenu impossible deux mois plus tôt ;
  · le 2026-08-20, la revue du CLAUDE.md garde « (3) questions en attente »
    dans l'ordre de priorité du budget mémoire.

C'est ce qui range ce retrait du côté de l'accident, pas de la décision. Le
numéro de priorité 3, resté VIDE entre « recall-session » (2) et « blagues »
(4), en est la trace fossile.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.intelligence.memory.service import MemoryService


def _memoire(question: dict | None):
    """Un `MemoryService` gréé du minimum pour la directive."""
    svc = MemoryService.__new__(MemoryService)
    svc._db = SimpleNamespace(
        get_pending_question=AsyncMock(return_value=question),
        increment_question_attempts=AsyncMock(),
    )
    svc._alias_cache = {}
    return svc


@pytest.mark.asyncio
async def test_la_question_en_attente_devient_une_directive():
    svc = _memoire({"id": 7, "question": "dans quelle ville habite-t-il ?",
                    "priority": "high"})

    directive = await svc.get_pending_question_directive("discord", "42")

    assert "dans quelle ville habite-t-il ?" in directive
    # Le TON compte autant que le contenu : une question de suivi qui s'impose
    # transforme une conversation en interrogatoire.
    assert "force" in directive.lower() or "occasion" in directive.lower()


@pytest.mark.asyncio
async def test_la_tentative_est_COMPTÉE_a_l_injection():
    """Sans ce compteur, les 3 tentatives max ne s'épuisent jamais.

    C'est lui qui rend la question mortelle : au bout de trois passages sans
    réponse, `get_pending_question` cesse de la rendre. Le compteur mort, elle
    reviendrait éternellement — 44 cas de plus de 30 jours l'ont déjà prouvé.
    """
    svc = _memoire({"id": 7, "question": "où habite-t-il ?", "priority": "low"})

    await svc.get_pending_question_directive("discord", "42")

    svc._db.increment_question_attempts.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_sans_question_la_directive_est_vide():
    """Pas de bloc vide dans le prompt : il coûterait des tokens pour rien."""
    svc = _memoire(None)

    assert await svc.get_pending_question_directive("discord", "42") == ""
    svc._db.increment_question_attempts.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_panne_de_base_ne_casse_pas_la_reponse():
    """Une question de suivi est un bonus : elle ne fait jamais tomber un tour."""
    svc = _memoire(None)
    svc._db.get_pending_question = AsyncMock(side_effect=RuntimeError("base fermée"))

    assert await svc.get_pending_question_directive("discord", "42") == ""


def test_la_priorite_3_est_bien_celle_des_questions():
    """La place vide dans le budget mémoire, et ce qui la remplit.

    L'ordre est documenté dans le CLAUDE.md : (1) souvenirs (2) relations
    (3) questions en attente (4) blagues (5) opinions (6) tiers. Le code
    n'avait plus de 3 — assez pour que le trou se voie, pas assez pour que
    quelqu'un le remarque.
    """
    from pathlib import Path

    for fichier in ("bot/discord/handlers.py", "bot/twitch/handlers.py"):
        source = Path(fichier).read_text(encoding="utf-8")
        assert 'memory_parts.append((3,' in source, (
            f"{fichier} : la priorité 3 du budget mémoire est vide"
        )
