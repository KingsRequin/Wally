# tests/test_openai_client.py
"""
Tests for OpenAILLMClient — all OpenAI API calls are mocked.
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.llm.openai_client import OpenAILLMClient, estimate_cost, _uses_responses_api
from bot.core.llm.base import FALLBACK_IMAGE_RESPONSE, FALLBACK_RESPONSE


def make_client(model="gpt-5", temperature=0.8, max_tokens=1000,
                reasoning_effort="medium", text_verbosity="medium"):
    db = MagicMock()
    db.log_cost = AsyncMock()
    db.get_cost_since = AsyncMock(return_value=0.042)
    client = OpenAILLMClient(
        model=model, db=db, temperature=temperature, max_tokens=max_tokens,
        reasoning_effort=reasoning_effort, text_verbosity=text_verbosity,
    )
    return client, db


def make_mock_response(content: str, prompt_tokens: int = 50, completion_tokens: int = 30):
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.prompt_tokens_details = None
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.usage = usage
    response.choices = [choice]
    return response


def test_estimate_cost_known_model():
    """Un million d'entrée + un million de sortie = le tarif catalogue, à l'unité près.

    `assert cost > 0` laissait passer n'importe quel chiffre : la table entière
    était fausse (gpt-5 à 2,00/8,00 au lieu de 1,25/10,00) sans qu'un seul test
    bronche. On assert désormais la valeur, pas sa positivité.
    """
    assert estimate_cost("gpt-5", 1_000_000, 1_000_000) == pytest.approx(1.25 + 10.0)
    assert estimate_cost("gpt-5.6-luna", 1_000_000, 1_000_000) == pytest.approx(0.20 + 1.20)
    assert estimate_cost("gpt-5-nano", 1_000_000, 1_000_000) == pytest.approx(0.05 + 0.40)


def test_estimate_cost_prefixe_le_plus_long_gagne():
    """`gpt-5.6-luna` ne doit pas être facturé au tarif de `gpt-5`.

    Le repli par préfixe trie du plus long au plus court ; sans ce tri, un modèle
    daté (`gpt-5.6-luna-2026-07-09`) tomberait sur l'entrée `gpt-5` et serait
    chiffré six fois trop cher.
    """
    assert estimate_cost("gpt-5.6-luna-2026-07-09", 1_000_000, 0) == pytest.approx(0.20)
    assert estimate_cost("gpt-5.4-mini-preview", 1_000_000, 0) == pytest.approx(0.75)


def test_estimate_cost_unknown_model_uses_default():
    cost = estimate_cost("some-unknown-model-xyz", 1000, 500)
    assert cost > 0


def test_estimate_cost_cached_tokens_reduce_cost():
    """OpenAI facture le cache à 10 % de l'entrée, pas à 50 %.

    Ce test EXIGEAIT auparavant la remise de 50 % que le code appliquait — il
    verrouillait donc l'erreur au lieu de la révéler. Tout appel avec cache était
    chiffré cinq fois trop cher.
    """
    full_cost = estimate_cost("gpt-5", 1000, 0, cached_input_tokens=0)
    tout_en_cache = estimate_cost("gpt-5", 1000, 0, cached_input_tokens=1000)
    assert tout_en_cache == pytest.approx(full_cost * 0.1)


def test_estimate_cost_partial_cache():
    full_cost = estimate_cost("gpt-5", 1000, 0, cached_input_tokens=0)
    partial = estimate_cost("gpt-5", 1000, 0, cached_input_tokens=500)
    assert partial == pytest.approx(full_cost * 0.55)   # moitié plein + moitié à 10 %


def test_estimate_cost_pro_sans_remise_de_cache():
    """`gpt-5-pro` n'a aucun tarif caché publié : on ne suppose aucune remise.

    Inventer un cache à 10 % là où OpenAI n'en annonce pas ferait sous-estimer
    la facture du modèle le plus cher du catalogue.
    """
    plein = estimate_cost("gpt-5-pro", 1_000_000, 0, cached_input_tokens=0)
    cache = estimate_cost("gpt-5-pro", 1_000_000, 0, cached_input_tokens=1_000_000)
    assert plein == pytest.approx(15.0)
    assert cache == pytest.approx(plein)


@pytest.mark.asyncio
async def test_complete_success():
    """GPT-5 routes through Responses API."""
    client, db = make_client()

    with patch.object(client, "_complete_responses_api", new=AsyncMock(return_value="Bonjour !")) as mock_resp:
        result = await client.complete("System prompt", [{"role": "user", "content": "Hi"}])

    assert result == "Bonjour !"
    mock_resp.assert_called_once()


@pytest.mark.asyncio
async def test_complete_chat_completions_retries_on_rate_limit():
    from openai import RateLimitError
    client, db = make_client(model="gpt-4o")

    mock_response = make_mock_response("OK after retry")
    side_effects = [
        RateLimitError("rate limit", response=MagicMock(status_code=429), body=None),
        mock_response,
    ]
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=side_effects)
    ):
        with patch("asyncio.sleep", new=AsyncMock()):
            result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    assert result == "OK after retry"


@pytest.mark.asyncio
async def test_complete_returns_fallback_on_responses_api_error():
    client, db = make_client()

    with patch.object(
        client._client.responses, "create", new=AsyncMock(side_effect=Exception("API down"))
    ):
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    assert isinstance(result, str) and len(result) > 0


@pytest.mark.asyncio
async def test_get_daily_cost():
    client, db = make_client()
    cost = await client.get_daily_cost()
    assert cost == 0.042
    db.get_cost_since.assert_called_once()


@pytest.mark.asyncio
async def test_get_monthly_cost():
    client, db = make_client()
    cost = await client.get_monthly_cost()
    assert cost == 0.042


def test_uses_responses_api_detection():
    assert _uses_responses_api("gpt-5-mini") is True
    assert _uses_responses_api("gpt-5.2-mini") is True
    assert _uses_responses_api("gpt-5.4-nano") is True
    assert _uses_responses_api("gpt-5-pro") is True
    assert _uses_responses_api("o1-mini") is True
    assert _uses_responses_api("o3-mini") is True
    assert _uses_responses_api("o4") is True
    assert _uses_responses_api("gpt-4o") is False
    assert _uses_responses_api("gpt-4o-mini") is False


@pytest.mark.asyncio
async def test_complete_stream_yields_chunks():
    """complete_stream() yields text chunks from streaming API."""
    client, _ = make_client(model="gpt-4o", reasoning_effort=None)

    async def mock_stream_iter():
        for text in ["Bonjour", " monde", "!"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = text
            yield chunk
        # Final chunk with no content
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = None
        yield chunk

    with patch.object(client._client.chat.completions, "create", AsyncMock(return_value=mock_stream_iter())):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

    assert chunks == ["Bonjour", " monde", "!"]


@pytest.mark.asyncio
async def test_complete_stream_responses_api_yields_single_chunk():
    """Responses API models (o1/o3/o4) yield the full response as one chunk."""
    client, _ = make_client(model="o3", reasoning_effort="medium")
    with patch.object(client, "complete", AsyncMock(return_value="full response text")):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
    assert chunks == ["full response text"]


@pytest.mark.asyncio
async def test_complete_stream_error_yields_fallback():
    """On API error, complete_stream() yields FALLBACK_RESPONSE."""
    client, _ = make_client(model="gpt-4o", reasoning_effort=None)
    with patch.object(client._client.chat.completions, "create", AsyncMock(side_effect=Exception("boom"))):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
    assert chunks == [FALLBACK_RESPONSE]


@pytest.mark.asyncio
async def test_responses_api_passes_reasoning_effort():
    client, db = make_client(reasoning_effort="high", text_verbosity="low")

    captured = {}

    async def capture_create(**kwargs):
        captured.update(kwargs)
        resp = MagicMock()
        resp.output_text = "test"
        resp.usage = MagicMock()
        resp.usage.input_tokens = 10
        resp.usage.output_tokens = 5
        resp.usage.input_tokens_details = None
        return resp

    with patch.object(client._client.responses, "create", new=AsyncMock(side_effect=capture_create)):
        await client.complete("System", [{"role": "user", "content": "Hi"}])

    assert captured["reasoning"] == {"effort": "high"}
    assert captured["text"]["verbosity"] == "low"
    # max_output_tokens is omitted when reasoning is active to avoid starving
    # the visible text response (reasoning tokens share the same budget).
    assert "max_output_tokens" not in captured


@pytest.mark.asyncio
async def test_complete_routes_to_responses_api_for_gpt5():
    client, db = make_client(model="gpt-5-mini")

    with patch.object(client, "_complete_responses_api", new=AsyncMock(return_value="Réponse LLM")) as mock_resp:
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    mock_resp.assert_called_once()
    assert result == "Réponse LLM"


@pytest.mark.asyncio
async def test_complete_routes_to_chat_completions_for_gpt4():
    client, db = make_client(model="gpt-4o")

    mock_response = make_mock_response("Chat response")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ) as mock_create:
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    mock_create.assert_called_once()
    assert result == "Chat response"


# ── Vision ────────────────────────────────────────────────────────────────────


def test_build_image_content_chat_completions():
    client, db = make_client()

    result = client._build_image_content(
        "bonjour", ["http://img1.png", "http://img2.png"], use_responses_api=False
    )

    assert result[0] == {"type": "text", "text": "bonjour"}
    assert result[1] == {"type": "image_url", "image_url": {"url": "http://img1.png"}}
    assert result[2] == {"type": "image_url", "image_url": {"url": "http://img2.png"}}
    assert len(result) == 3


def test_build_image_content_responses_api():
    client, db = make_client()

    result = client._build_image_content(
        "bonjour", ["http://img1.png"], use_responses_api=True
    )

    assert result[0] == {"type": "input_text", "text": "bonjour"}
    assert result[1] == {"type": "input_image", "image_url": "http://img1.png"}
    assert len(result) == 2


@pytest.mark.asyncio
async def test_complete_with_images_transforms_last_message():
    client, db = make_client(model="gpt-4o")

    captured = {}

    async def capture_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return make_mock_response("Je vois une image!")

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=capture_create)
    ):
        await client.complete(
            "System",
            [{"role": "user", "content": "regarde"}],
            image_urls=["https://cdn.discord.com/img.png"],
        )

    last_content = captured["messages"][-1]["content"]
    assert isinstance(last_content, list)
    assert last_content[0] == {"type": "text", "text": "regarde"}
    assert last_content[1] == {"type": "image_url", "image_url": {"url": "https://cdn.discord.com/img.png"}}


@pytest.mark.asyncio
async def test_complete_image_error_returns_image_fallback():
    client, db = make_client()

    with patch.object(
        client._client.responses,
        "create",
        new=AsyncMock(side_effect=Exception("Invalid image URL")),
    ):
        result = await client.complete(
            "System",
            [{"role": "user", "content": "regarde"}],
            image_urls=["https://invalid.png"],
        )

    assert result == FALLBACK_IMAGE_RESPONSE


@pytest.mark.asyncio
async def test_complete_no_images_uses_generic_fallback():
    client, db = make_client()

    with patch.object(
        client._client.responses,
        "create",
        new=AsyncMock(side_effect=Exception("Server error")),
    ):
        result = await client.complete(
            "System",
            [{"role": "user", "content": "bonjour"}],
        )

    assert result == FALLBACK_RESPONSE


# ── reasoning_effort : « none » doit être ENVOYÉ, pas omis ───────────────────

def _client(effort: str, max_tokens: int = 8192):
    return OpenAILLMClient(
        model="gpt-5.6-luna", db=None, max_tokens=max_tokens, reasoning_effort=effort,
    )


def test_effort_none_est_envoye_explicitement():
    """`none` est une valeur que l'API accepte et qui rend 0 token de raisonnement.

    L'omettre ne désactive rien : le modèle applique SON défaut, qui raisonne.
    Le code omettait le paramètre pour `none`, aux trois endroits qui le
    construisaient — un `reasoning_effort: none` en config produisait donc
    l'inverse de ce qu'il demande (2 234 tokens de sortie contre 1 051 en `low`,
    mesuré au banc sur gpt-5.6-luna).
    """
    params = _client("none")._params_raisonnement()
    assert params["reasoning"] == {"effort": "none"}


def test_plafond_pose_sans_raisonnement_et_retire_avec():
    """Le plafond n'est retiré que quand le raisonnement peut l'affamer.

    La Responses API partage `max_output_tokens` entre réflexion et texte : un
    petit modèle épuise le budget avant d'écrire un mot. Sans raisonnement, il
    n'y a rien à affamer — le plafond doit revenir, c'est lui qui borne la
    dépense.
    """
    assert _client("none")._params_raisonnement()["max_output_tokens"] == 8192
    assert "max_output_tokens" not in _client("low")._params_raisonnement()
    assert "max_output_tokens" not in _client("high")._params_raisonnement()


def test_plafond_ponctuel_prime_sur_celui_du_client():
    assert _client("none")._params_raisonnement(512)["max_output_tokens"] == 512


def test_sortie_structuree_ne_pose_jamais_de_plafond():
    """Un JSON coupé au plafond serait un schéma invalide."""
    params = _client("none")._params_raisonnement(avec_plafond=False)
    assert "max_output_tokens" not in params
    assert params["reasoning"] == {"effort": "none"}


def test_effort_vide_n_envoie_pas_de_reasoning():
    """Chaîne vide = « ne te prononce pas », le modèle garde son défaut."""
    params = _client("")._params_raisonnement()
    assert "reasoning" not in params
    assert params["max_output_tokens"] == 8192


# ── le comptage de jetons ne doit pas casser une génération ────────────
#
# `response.usage` est typé `CompletionUsage | None` par le SDK OpenAI, et le
# code le lisait sans garde : `usage.prompt_tokens` sur un `usage` absent lève
# un AttributeError EN PLEIN milieu d'une réponse déjà générée et payée. mypy
# le signalait 20 fois ; ce n'était pas qu'une question de types.
#
# Deux API cohabitent, et le même code les traverse : Responses
# (`input_tokens`/`output_tokens`) et Chat Completions
# (`prompt_tokens`/`completion_tokens`).
import pytest as _pytest

from bot.core.llm.openai_client import compter_jetons


class _Details:
    def __init__(self, caches):
        self.cached_tokens = caches


def test_compter_jetons_lit_l_api_responses():
    usage = type("U", (), {"input_tokens": 120, "output_tokens": 30,
                           "input_tokens_details": _Details(50)})()
    assert compter_jetons(usage) == (120, 30, 50)


def test_compter_jetons_lit_l_api_chat_completions():
    usage = type("U", (), {"prompt_tokens": 200, "completion_tokens": 45,
                           "prompt_tokens_details": _Details(80)})()
    assert compter_jetons(usage) == (200, 45, 80)


def test_un_usage_absent_ne_leve_pas():
    """Le cas que le type du SDK prévoit et que le code ignorait."""
    assert compter_jetons(None) == (0, 0, 0)


def test_un_usage_sans_detail_de_cache_compte_zero():
    """`cached_tokens` est facultatif et varie d'un modèle à l'autre."""
    usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 2,
                           "prompt_tokens_details": None})()
    assert compter_jetons(usage) == (10, 2, 0)


def test_un_usage_incomplet_ne_leve_pas():
    """Un objet qui ne porte AUCUN des deux jeux de noms."""
    assert compter_jetons(object()) == (0, 0, 0)


@_pytest.mark.asyncio
async def test_un_echec_d_enregistrement_de_cout_SE_VOIT():
    """Une compta ratée n'est pas fatale, mais elle doit se dire.

    Les quatre gestionnaires d'échec de `log_cost` journalisaient en DEBUG —
    donc dans le vide, le niveau de prod étant plus haut. Si l'écriture des
    coûts s'arrêtait (base verrouillée, disque plein, colonne manquante), la
    facturation cesserait sans que rien ne l'annonce, et on ne s'en
    apercevrait qu'en cherchant pourquoi le total ne bouge plus.

    C'est la signature de défaut que ce dépôt combat : ça échoue, personne
    n'est prévenu, ça vit des semaines.
    """
    from unittest.mock import AsyncMock, MagicMock

    from loguru import logger

    from bot.core.llm.openai_client import OpenAILLMClient

    client = OpenAILLMClient.__new__(OpenAILLMClient)
    client._model = "gpt-test"
    client._db = MagicMock()
    client._db.log_cost = AsyncMock(side_effect=RuntimeError("base verrouillée"))

    vues = []
    sink = logger.add(lambda m: vues.append((m.record["level"].name,
                                             m.record["message"])), level="INFO")
    try:
        await client._log_cost(input_tokens=10, output_tokens=2, cost=0.001,
                               purpose="test", user_id=None)
    finally:
        logger.remove(sink)

    niveaux = [n for n, _m in vues]
    assert "WARNING" in niveaux, f"l'échec est resté invisible : {vues}"
    # `{e!r}` et pas `{e}` : `RuntimeError('')` a un `str()` vide.
    assert any("RuntimeError" in m for _n, m in vues)
