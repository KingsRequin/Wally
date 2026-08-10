# tests/test_audit2_phaseM_dashboard.py
"""Phase M du second audit : dashboard, LLM et front.

A2-sink  — le sink SSE des logs faisait `put_nowait` sur des `asyncio.Queue`
           depuis des threads `to_thread` → RuntimeError avalé par loguru.
A2-nan   — `NaN` accepté sur `/overlay/force-live` : 500, et échéance « nan »
           persistée qui tuait le mode test en silence.
A2-token — `str(None)` vaut « None », une chaîne non vide : le jeton admin
           devenait devinable.
A2-cout  — `complete_structured` calculait son coût sans jamais l'écrire.
A2-front — listener global ajouté à chaque montage, ResizeObserver jamais
           déconnecté.
"""
import inspect
import math
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException


# ────────────────────────────── A2-sink ──────────────────────────────
def test_le_sink_des_logs_est_thread_safe():
    from bot.dashboard.routes import sse

    src = inspect.getsource(sse.setup_log_sink)
    assert "enqueue=True" in src


# ────────────────────────────── A2-nan ──────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("valeur", [float("nan"), float("inf")])
async def test_une_duree_non_finie_est_refusee(valeur):
    from bot.dashboard.routes.overlay import set_force_live

    requete = MagicMock()
    requete.json = AsyncMock(return_value={"minutes": valeur})

    with pytest.raises(HTTPException) as e:
        await set_force_live(requete)
    assert e.value.status_code == 400


def test_json_loads_accepte_bien_nan_pour_minutes():
    """Le point de départ : `float(nan)` ne lève pas, `nan <= 0` est faux."""
    import json

    v = json.loads('{"minutes": NaN}')["minutes"]
    assert math.isnan(float(v))
    assert not (float(v) <= 0)


# ────────────────────────────── A2-token ──────────────────────────────
def test_un_jeton_nul_ne_devient_pas_la_chaine_none():
    from bot.dashboard.routes import admin

    src = inspect.getsource(admin)
    assert 'str(d["dashboard_token"]) or None' not in src
    assert 'str(_brut).strip() if _brut else None' in src


def test_str_de_none_est_bien_une_chaine_non_vide():
    """La raison du défaut, explicitée."""
    assert str(None) == "None"
    assert bool(str(None)) is True


# ────────────────────────────── A2-cout ──────────────────────────────
def test_les_appels_structures_comptabilisent_leur_cout():
    from bot.core.llm.openai_client import OpenAILLMClient

    src = inspect.getsource(OpenAILLMClient.complete_structured)
    # Les deux branches (Responses et Chat Completions).
    assert src.count("await self._log_cost(") == 2


# ────────────────────────────── A2-front ──────────────────────────────
def test_le_listener_global_du_chat_est_pose_une_seule_fois():
    src = Path("bot/dashboard/static/public-starter/tabs/chat.js").read_text(encoding="utf-8")
    assert "_clicHorsChampPose" in src
    assert src.count("document.addEventListener('click'") == 1


def test_l_observateur_de_taille_est_libere_avant_d_en_creer_un_autre():
    src = Path("bot/dashboard/static/public-starter/tabs/status.js").read_text(encoding="utf-8")
    i_disconnect = src.index("_resizeObserver.disconnect()")
    i_new = src.index("new ResizeObserver(")
    assert i_disconnect < i_new
