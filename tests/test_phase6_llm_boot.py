# tests/test_phase6_llm_boot.py
"""Phase 6 de l'audit du 2026-08-10 : la couche LLM et l'arrêt.

C13 — `complete()` pouvait rendre "" et violer son propre contrat.
C14 — DeepSeek, SEUL provider texte de prod, n'avait aucune reprise.
C15 — `APIConnectionError`/`APITimeoutError` ne sont pas des `APIStatusError` :
      zéro reprise sur la panne la plus fréquente.
C16 — un JSON d'arguments irréparable faisait exécuter l'outil À VIDE.
C17 — le repli du rappel ne testait pas `FALLBACK_RESPONSE`.
C18 — un arrêt pendant le démarrage laissait les transports Twitch occupés.
"""
import asyncio
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.llm.base import FALLBACK_RESPONSE
from bot.core.llm.deepseek import DeepSeekLLMClient


def _client():
    c = DeepSeekLLMClient.__new__(DeepSeekLLMClient)
    c._client = MagicMock()
    c._model = "deepseek-chat"
    c._temperature = 0.8
    c._max_tool_iters = 3
    c._db = MagicMock()
    c._log_cost = AsyncMock()
    c._api_params = MagicMock(return_value={"model": "deepseek-chat"})
    return c


def _reponse(contenu):
    msg = MagicMock(content=contenu, tool_calls=None)
    return MagicMock(choices=[MagicMock(message=msg)], usage=MagicMock(), model="deepseek-chat")


# ────────────────────────────── C13 ──────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("vide", ["", "   ", None])
async def test_une_reponse_vide_rend_le_fallback_pas_le_silence(vide):
    c = _client()
    c._client.chat.completions.create = AsyncMock(return_value=_reponse(vide))
    assert await c.complete("sys", [{"role": "user", "content": "x"}]) == FALLBACK_RESPONSE


@pytest.mark.asyncio
async def test_une_reponse_100_pourcent_dsml_rend_le_fallback():
    """`_strip_dsml` peut tout retirer : il ne reste rien à publier."""
    c = _client()
    dsml = "<｜DSML｜tool_calls><｜DSML｜invoke name=\"x\"></｜DSML｜invoke></｜DSML｜tool_calls>"
    c._client.chat.completions.create = AsyncMock(return_value=_reponse(dsml))
    assert await c.complete("sys", [{"role": "user", "content": "x"}]) == FALLBACK_RESPONSE


@pytest.mark.asyncio
async def test_une_vraie_reponse_passe_toujours():
    c = _client()
    c._client.chat.completions.create = AsyncMock(return_value=_reponse("salut toi"))
    assert await c.complete("sys", [{"role": "user", "content": "x"}]) == "salut toi"


# ────────────────────────────── C14 ──────────────────────────────
@pytest.mark.asyncio
async def test_un_429_transitoire_est_rejoue():
    c = _client()
    erreur = Exception("rate limited")
    erreur.status_code = 429
    c._client.chat.completions.create = AsyncMock(
        side_effect=[erreur, _reponse("enfin là")]
    )
    with patch("asyncio.sleep", new=AsyncMock()):
        out = await c.complete("sys", [{"role": "user", "content": "x"}])
    assert out == "enfin là"
    assert c._client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_une_erreur_definitive_nest_pas_rejouee():
    """Un 400 rejoué trois fois ne fait que retarder l'échec."""
    c = _client()
    erreur = Exception("bad request")
    erreur.status_code = 400
    c._client.chat.completions.create = AsyncMock(side_effect=erreur)
    with patch("asyncio.sleep", new=AsyncMock()):
        out = await c.complete("sys", [{"role": "user", "content": "x"}])
    assert out == FALLBACK_RESPONSE
    assert c._client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_les_reprises_sont_bornees():
    c = _client()
    erreur = Exception("500")
    erreur.status_code = 500
    c._client.chat.completions.create = AsyncMock(side_effect=erreur)
    with patch("asyncio.sleep", new=AsyncMock()):
        out = await c.complete("sys", [{"role": "user", "content": "x"}])
    assert out == FALLBACK_RESPONSE
    assert c._client.chat.completions.create.await_count == 3


@pytest.mark.asyncio
async def test_le_backoff_est_exponentiel():
    c = _client()
    erreur = Exception("panne réseau")   # sans status_code → rejouable
    c._client.chat.completions.create = AsyncMock(side_effect=erreur)
    with patch("asyncio.sleep", new=AsyncMock()) as dodo:
        await c.complete("sys", [{"role": "user", "content": "x"}])
    assert [a.args[0] for a in dodo.await_args_list] == [1.0, 2.0]


# ────────────────────────────── C15 ──────────────────────────────
def test_les_erreurs_reseau_openai_sont_rejouees():
    from bot.core.llm import openai_client

    src = inspect.getsource(openai_client)
    assert "APIConnectionError" in src and "APITimeoutError" in src
    # Un handler par boucle de reprise (5 chemins recensés dans l'audit).
    assert src.count("except (APIConnectionError, APITimeoutError)") == 5


# ────────────────────────────── C16 ──────────────────────────────
@pytest.mark.asyncio
async def test_un_json_irreparable_est_signale_au_modele():
    """L'outil s'exécutait à vide et le modèle ne l'apprenait jamais."""
    c = _client()
    appel = MagicMock()
    appel.function.name = "create_action_task"
    appel.function.arguments = '{"message": "coucou'   # tronqué au-delà du réparable
    appel.id = "t1"
    appel.model_dump = MagicMock(return_value={})

    msg = MagicMock(content="", tool_calls=[appel])
    reponse = MagicMock(choices=[MagicMock(message=msg)], usage=MagicMock(), model="deepseek-chat")
    finale = _reponse("c'est noté")
    c._client.chat.completions.create = AsyncMock(side_effect=[reponse, finale])

    executeur = AsyncMock(return_value="OK")
    with patch.object(DeepSeekLLMClient, "_safe_parse_args", return_value={}):
        texte, _ = await c.complete_with_tools(
            "sys", [{"role": "user", "content": "x"}], tools=[], tool_executor=executeur
        )

    executeur.assert_not_awaited()          # l'outil n'a PAS tourné à vide
    envoye = c._client.chat.completions.create.await_args_list[1].kwargs["messages"]
    assert any("JSON" in str(m.get("content", "")) for m in envoye)


@pytest.mark.asyncio
async def test_un_outil_sans_argument_reste_legitime():
    """`{}` volontaire (outil sans paramètre) ne doit pas être pris pour une erreur."""
    c = _client()
    appel = MagicMock()
    appel.function.name = "get_status"
    appel.function.arguments = "{}"
    appel.id = "t1"
    appel.model_dump = MagicMock(return_value={})

    msg = MagicMock(content="", tool_calls=[appel])
    reponse = MagicMock(choices=[MagicMock(message=msg)], usage=MagicMock(), model="deepseek-chat")
    c._client.chat.completions.create = AsyncMock(side_effect=[reponse, _reponse("voilà")])

    executeur = AsyncMock(return_value="OK")
    await c.complete_with_tools(
        "sys", [{"role": "user", "content": "x"}], tools=[], tool_executor=executeur
    )
    executeur.assert_awaited_once()


# ────────────────────────────── C18 ──────────────────────────────
@pytest.mark.asyncio
async def test_un_arret_au_demarrage_rend_les_transports_twitch():
    import bot.main as m

    faux_twitch = MagicMock()
    m._AU_DEMARRAGE["twitch"] = faux_twitch
    ferme = AsyncMock()

    async def _main_annule():
        raise asyncio.CancelledError()

    with patch.object(m, "main", _main_annule), \
         patch("bot.twitch.events.close_eventsub_client", ferme):
        with pytest.raises(asyncio.CancelledError):
            await m._demarrer()

    ferme.assert_awaited_once_with(faux_twitch)
    m._AU_DEMARRAGE.clear()


@pytest.mark.asyncio
async def test_sans_bot_twitch_l_arret_reste_propre():
    import bot.main as m

    m._AU_DEMARRAGE.clear()

    async def _main_annule():
        raise asyncio.CancelledError()

    with patch.object(m, "main", _main_annule):
        with pytest.raises(asyncio.CancelledError):
            await m._demarrer()
