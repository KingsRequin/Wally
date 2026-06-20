import pytest

from bot.config import LLMRoleConfig
from bot.core.llm.factory import create_llm_client
from bot.core.llm.deepseek import DeepSeekLLMClient


def test_factory_returns_deepseek_for_deepseek_provider():
    client = create_llm_client(LLMRoleConfig(provider="deepseek", model="deepseek-v4-pro"), db=None)
    assert isinstance(client, DeepSeekLLMClient)


def test_factory_raises_on_non_deepseek_text_provider():
    with pytest.raises(ValueError):
        create_llm_client(LLMRoleConfig(provider="openai", model="gpt-5-nano"), db=None)
    with pytest.raises(ValueError):
        create_llm_client(LLMRoleConfig(provider="claude", model="claude-haiku-4-5-20251001"), db=None)
