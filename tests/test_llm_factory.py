import pytest

from bot.config import LLMRoleConfig
from bot.core.llm.factory import SUPPORTED_TEXT_PROVIDERS, create_llm_client
from bot.core.llm.deepseek import DeepSeekLLMClient
from bot.core.llm.openai_client import OpenAILLMClient


def test_factory_returns_deepseek_for_deepseek_provider():
    client = create_llm_client(LLMRoleConfig(provider="deepseek", model="deepseek-v4-pro"), db=None)
    assert isinstance(client, DeepSeekLLMClient)


def test_factory_returns_openai_for_openai_provider():
    """`openai` est un fournisseur de TEXTE depuis le 2026-08-25.

    Ce test exigeait auparavant une `ValueError` : la factory refusait un
    fournisseur dont le client implémentait pourtant `BaseLLMClient` en entier et
    tournait déjà en production pour la vision. Le refus était la limite d'alors,
    pas une propriété à préserver.
    """
    client = create_llm_client(LLMRoleConfig(provider="openai", model="gpt-5.6-luna"), db=None)
    assert isinstance(client, OpenAILLMClient)


def test_factory_transmet_les_reglages_du_role():
    """Les champs OpenAI de `LLMRoleConfig` doivent arriver jusqu'au client.

    `reasoning_effort` gouverne la Responses API : le laisser au défaut ferait
    raisonner un modèle choisi POUR sa latence, et `max_output_tokens` est omis
    dès qu'il est actif — le piège qui rend des réponses vides.
    """
    client = create_llm_client(
        LLMRoleConfig(
            provider="openai", model="gpt-5.6-luna", temperature=0.4,
            max_tokens=512, reasoning_effort="low", text_verbosity="high",
        ),
        db=None,
    )
    assert client.model == "gpt-5.6-luna"
    assert client.temperature == 0.4
    assert client.max_tokens == 512
    assert client.reasoning_effort == "low"
    assert client.text_verbosity == "high"


def test_factory_raises_on_unknown_text_provider():
    with pytest.raises(ValueError):
        create_llm_client(LLMRoleConfig(provider="claude", model="claude-haiku-4-5"), db=None)
    with pytest.raises(ValueError):
        create_llm_client(LLMRoleConfig(provider="mistral", model="mistral-small-4"), db=None)


def test_chaque_provider_annonce_est_constructible():
    """`SUPPORTED_TEXT_PROVIDERS` ne doit jamais promettre plus que le `if`.

    Le dashboard sert cette liste au `<select>` : un fournisseur qui y figure
    sans branche de construction se choisit dans l'UI, se grave dans
    `config.yaml`, puis tue le bot au démarrage suivant.
    """
    for provider in SUPPORTED_TEXT_PROVIDERS:
        client = create_llm_client(LLMRoleConfig(provider=provider, model="peu-importe"), db=None)
        assert client is not None
