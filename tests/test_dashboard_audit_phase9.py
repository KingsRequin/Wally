"""Phase 9 : CSRF de connexion, PUT mensonger, fork bloquant, fuites de mémoire."""
from __future__ import annotations

import inspect
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bot.dashboard.routes import chat_auth
from bot.dashboard.routes.memory import router as memory_router


def _sans_commentaires(source: str) -> str:
    """Le code seul. Un correctif explique souvent en commentaire la forme
    fautive qu'il remplace ; chercher cette forme dans la source entière fait
    échouer le test sur sa propre justification."""
    return "\n".join(
        ligne for ligne in source.splitlines() if not ligne.lstrip().startswith("#")
    )


# ── OAuth2 Discord : un `state` anti-CSRF ────────────────────────────────────
#
# Sans lui, un attaquant faisait consommer SON code par le navigateur d'une
# victime (lien piégé) : la victime se retrouvait authentifiée sur le chat web
# sous l'identité de l'attaquant, et ses messages, sa mémoire et ses votes de
# galerie lui étaient attribués. `twitch_auth.py` gérait déjà un `state`.

def test_lurl_de_connexion_porte_un_state(monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_ID", "cid")
    monkeypatch.setenv("WEB_BASE_URL", "https://exemple.fr")
    chat_auth._pending_states.clear()

    app = FastAPI()
    app.include_router(chat_auth.router, prefix="/api/chat")
    reponse = TestClient(app, follow_redirects=False).get("/api/chat/auth/login")

    assert reponse.status_code in (302, 307)
    assert "state=" in reponse.headers["location"]
    assert len(chat_auth._pending_states) == 1


async def test_un_callback_sans_state_est_refuse():
    chat_auth._pending_states.clear()
    with pytest.raises(HTTPException) as e:
        await chat_auth.callback(code="volé", request=MagicMock(), state="")
    assert e.value.status_code == 400


async def test_un_state_inconnu_est_refuse():
    chat_auth._pending_states.clear()
    chat_auth._pending_states["le_mien"] = time.time() + 600
    with pytest.raises(HTTPException) as e:
        await chat_auth.callback(code="volé", request=MagicMock(), state="celui_de_lattaquant")
    assert e.value.status_code == 400


def test_un_state_perime_est_purge():
    chat_auth._pending_states.clear()
    chat_auth._pending_states["vieux"] = time.time() - 1
    chat_auth._purge_states()
    assert "vieux" not in chat_auth._pending_states


def test_les_codes_ephemeres_sont_purges():
    """Le TTL de 60 s n'était vérifié qu'à la LECTURE : un code jamais échangé —
    onglet fermé après le redirect — restait indéfiniment en mémoire, avec son
    JWT et son refresh token valide 30 jours."""
    chat_auth._pending_codes.clear()
    chat_auth._pending_codes["perime"] = {"expires": time.time() - 1, "jwt": "x"}
    chat_auth._pending_codes["frais"] = {"expires": time.time() + 60, "jwt": "y"}

    chat_auth._purge_codes()

    assert "perime" not in chat_auth._pending_codes
    assert "frais" in chat_auth._pending_codes


# ── PUT /notes/{id} utilise enfin son id ─────────────────────────────────────

async def test_modifier_une_note_ne_cree_plus_de_doublon():
    """La route appelait `upsert_persistent_note(title, content)`, dont la clé de
    conflit est `ON CONFLICT(title)` : `note_id` n'était jamais utilisé et la
    route était identique au POST. Renommer créait un doublon, et l'originale
    restait injectée dans chaque conversation via `_NOTE_TOOLS`."""
    from bot.dashboard.routes.admin import update_note

    db = MagicMock()
    db.update_persistent_note = AsyncMock(return_value=True)
    db.upsert_persistent_note = AsyncMock()
    request = MagicMock()
    request.app.state.wally.db = db
    request.json = AsyncMock(return_value={"title": "Nouveau titre", "content": "corps"})

    assert await update_note(42, request) == {"ok": True}
    db.update_persistent_note.assert_awaited_once_with(42, "Nouveau titre", "corps")
    db.upsert_persistent_note.assert_not_awaited()


async def test_modifier_une_note_absente_rend_404():
    from bot.dashboard.routes.admin import update_note

    db = MagicMock()
    db.update_persistent_note = AsyncMock(return_value=False)
    request = MagicMock()
    request.app.state.wally.db = db
    request.json = AsyncMock(return_value={"title": "t", "content": "c"})

    with pytest.raises(HTTPException) as e:
        await update_note(999, request)
    assert e.value.status_code == 404


# ── Un id de souvenir non numérique rend 422, pas 500 ────────────────────────

def test_un_memory_id_non_numerique_rend_422():
    """`int(memory_id)` non gardé levait une ValueError → 500, et l'admin voyait
    « Erreur » sans détail."""
    app = FastAPI()
    app.include_router(memory_router)
    wally = MagicMock()
    wally.fact_store = MagicMock()
    app.state.wally = wally

    reponse = TestClient(app).delete("/memory/users/discord:1/memories/pas-un-nombre")
    assert reponse.status_code == 422        # validation FastAPI, pas une trace


# ── Plus de fork bloquant ni de tâche ramassable ─────────────────────────────

def test_le_self_update_ne_forke_plus_dans_la_boucle():
    """Le `fork()` d'un process Python à gros tas duplique l'espace d'adressage
    et gèle toute la boucle — Discord, Twitch, dashboard, ticks cognitifs."""
    from bot.dashboard.routes.admin import self_update

    # Sur le CODE seul : le correctif s'explique en commentaire et y cite la
    # forme d'origine, qu'on ne veut justement plus voir s'exécuter.
    code = _sans_commentaires(inspect.getsource(self_update))
    assert "subprocess.Popen" not in code
    assert "asyncio.create_subprocess_shell" in code
    assert "_bg_tasks.add(task)" in code


@pytest.mark.parametrize("module", ["memory", "chat"])
def test_les_taches_detachees_du_dashboard_sont_retenues(module):
    """La boucle ne garde qu'une référence FAIBLE : le GC pouvait annuler la
    réconciliation d'alias ou la réponse de Wally au chat web, sans un log."""
    import importlib

    mod = importlib.import_module(f"bot.dashboard.routes.{module}")
    source = _sans_commentaires(inspect.getsource(mod))
    assert "_bg_tasks" in source
    assert "def _fire(" in source
    # Plus de `create_task` nu sur les coroutines métier.
    for nu in ("asyncio.create_task(_wally_respond", "asyncio.create_task(_post_process",
               "asyncio.create_task(fe._reconcile"):
        assert nu not in source


@pytest.mark.parametrize("module", ["memory", "chat"])
def test_plus_de_curseur_laisse_ouvert(module):
    import importlib

    code = _sans_commentaires(
        inspect.getsource(importlib.import_module(f"bot.dashboard.routes.{module}"))
    )
    assert "cursor = await state.db._conn.execute" not in code
    assert "cursor = await db._conn.execute" not in code
