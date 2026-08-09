"""Phase 7 : réglages LLM jamais relus, vision aveuglée, réponses vides."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from bot.core.llm.deepseek import DeepSeekLLMClient
from bot.core.llm.openai_client import OpenAILLMClient


def _deepseek():
    return DeepSeekLLMClient(model="deepseek-v4-pro", db=MagicMock())


# ── Le hot-reload du dashboard atteint enfin le client ───────────────────────
#
# La factory ne construit QUE du DeepSeek, mais seul `OpenAILLMClient` exposait
# ces propriétés. `state.primary_llm.model = …`, écrit par le dashboard et par
# `/wally setup`, créait donc un attribut FANTÔME jamais relu — « sauvegardé »
# s'affichait, et le client en vol gardait l'ancienne valeur.

def test_le_client_deepseek_expose_les_reglages_reglables():
    client = _deepseek()

    client.model = "deepseek-v4-flash"
    client.temperature = 0.3
    client.max_tokens = 512
    client.thinking_type = "enabled"
    client.thinking_effort = "high"

    # Ce sont bien les champs INTERNES qui bougent, pas des attributs fantômes.
    assert client._model == "deepseek-v4-flash"
    assert client._temperature == 0.3
    assert client._max_tokens == 512
    assert client._thinking_type == "enabled"
    assert client._thinking_effort == "high"


def test_les_gardes_hasattr_du_dashboard_passent_maintenant():
    """`admin.py` conditionne l'application des réglages « thinking » à un
    `hasattr(..., "thinking_type")` — toujours faux, donc ignoré en silence."""
    client = _deepseek()
    assert hasattr(client, "thinking_type")
    assert hasattr(client, "thinking_effort")
    assert hasattr(client, "max_tokens")


def test_le_modele_change_atteint_les_appels():
    client = _deepseek()
    client.model = "deepseek-v4-flash"
    assert client._api_params()["model"] == "deepseek-v4-flash"


# ── La vision a son propre modèle ────────────────────────────────────────────

def test_openai_config_a_un_champ_de_vision_dedie():
    """`bootstrap` prenait le modèle de vision dans `secondary_model`, que le
    dashboard écrase dès qu'on touche au LLM texte secondaire. Choisir un modèle
    non-OpenAI comme secondaire rendait Wally aveugle au redémarrage — 404 sur
    chaque image, et `VisionService.analyze()` filtrant les fallbacks, sans un
    seul log."""
    from dataclasses import fields

    from bot.config import OpenAIConfig

    assert "vision_model" in {f.name for f in fields(OpenAIConfig)}


def test_bootstrap_prefere_le_champ_dedie_avec_repli():
    from pathlib import Path

    source = Path("bot/bootstrap.py").read_text(encoding="utf-8")
    assert 'getattr(config.openai, "vision_model", "") or config.openai.secondary_model' in source


def test_la_temperature_est_propagee_vers_la_section_llm():
    """Elle était le SEUL champ de la section héritée à ne pas l'être, alors que
    `_build_llm_config` privilégie `llm:` et n'y retombe jamais sur `openai:` :
    le réglage n'était appliqué ni à chaud ni au redémarrage."""
    from pathlib import Path

    source = Path("bot/dashboard/routes/admin.py").read_text(encoding="utf-8")
    assert "cfg.llm.primary.temperature = temp" in source
    assert "cfg.llm.secondary.temperature = temp" in source


# ── Robustesse des réponses OpenAI ───────────────────────────────────────────

def test_le_streaming_a_un_plafond_de_tours_doutils():
    """`while True:` nu : un modèle qui redemande un outil en boucle bloquait la
    coroutine indéfiniment. Les deux autres chemins ont un plafond."""
    # Sur le CODE, hors commentaires : le correctif s'y explique et cite la
    # forme d'origine.
    code = "\n".join(
        ligne for ligne in inspect.getsource(OpenAILLMClient.complete_stream).splitlines()
        if not ligne.lstrip().startswith("#")
    )
    assert "while True:" not in code
    assert "range(self.STREAM_MAX_TOOL_ITERS)" in code
    assert OpenAILLMClient.STREAM_MAX_TOOL_ITERS > 0


def test_un_content_none_ne_leve_plus():
    """`content` est None sur un refus, un filtrage ou des `tool_calls` :
    l'AttributeError était avalée par le `except Exception` générique, qui
    loguait « unexpected error » — on cherchait une panne réseau alors que
    l'API avait répondu 200."""
    source = inspect.getsource(OpenAILLMClient.complete)
    assert 'response.choices[0].message.content.strip()' not in source
    assert '(response.choices[0].message.content or "")' in source


def test_une_sortie_sans_texte_rend_le_fallback():
    """Après les 3 itérations, la sortie peut ne contenir QUE des appels
    d'outils : `output_text` vaut "" et cette chaîne partait comme un succès —
    message vide, indiscernable d'un modèle silencieux."""
    source = inspect.getsource(OpenAILLMClient._complete_with_tools_responses)
    assert "if not text:" in source
    assert "text = FALLBACK_RESPONSE" in source


def test_les_deux_chemins_de_complete_comptabilisent_le_cout():
    """Seules les variantes outillées appelaient `log_cost`. Or le seul chemin
    OpenAI texte vivant aujourd'hui est la VisionService : aucune description
    d'image n'était comptabilisée."""
    assert "await self._log_cost(" in inspect.getsource(OpenAILLMClient.complete)
    assert "await self._log_cost(" in inspect.getsource(
        OpenAILLMClient._complete_responses_api
    )


async def test_le_fallback_de_streaming_ne_sajoute_pas_au_texte_deja_emis():
    """Le lecteur recevait une demi-phrase suivie de « Je rencontre un problème
    technique… »."""
    from bot.core.llm.base import FALLBACK_RESPONSE

    client = _deepseek()

    class _StreamQuiCasse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise RuntimeError("le flux casse en cours de route")

    client._client = MagicMock()
    client._client.chat.completions.stream = MagicMock(return_value=_StreamQuiCasse())

    morceaux = [m async for m in client.complete_stream("sys", [], purpose="test")]
    assert morceaux == [FALLBACK_RESPONSE]        # rien n'avait été émis

    source = inspect.getsource(DeepSeekLLMClient.complete_stream)
    assert "if not emis:" in source               # …et sinon, on n'ajoute rien
