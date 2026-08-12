# tests/test_cognition_llm_config.py
"""La boucle cognitive construit ses propres clients LLM, à part de `llm.primary`.

Ces clients naissaient d'un `LLMRoleConfig(provider=…, model=…)` sans plus :
`max_tokens` retombait donc sur le défaut du dataclass, 1000 tokens. Mesuré sur
30 jours de production, 479 pensées sur 5250 (9,1 %) sortaient pile à 1000 —
coupées net, avec les tags d'action que `parse_decisions` devait y lire.
"""
from bot.config import LLMConfig, LLMRoleConfig
from bot.discord.bot import cognition_llm_config


def _llm_config(max_tokens: int = 8192) -> LLMConfig:
    return LLMConfig(
        primary=LLMRoleConfig(provider="deepseek", model="deepseek-v4-flash", max_tokens=max_tokens),
        secondary=LLMRoleConfig(provider="deepseek", model="deepseek-v4-flash"),
    )


def test_reprend_le_provider_et_le_modele_de_la_section_cognitive():
    role = cognition_llm_config(
        {"provider": "deepseek", "model_pro": "deepseek-v4-flash"}, _llm_config()
    )
    assert role.provider == "deepseek"
    assert role.model == "deepseek-v4-flash"


def test_le_plafond_de_sortie_ne_tronque_plus_les_pensees():
    role = cognition_llm_config({}, _llm_config(max_tokens=8192))
    assert role.max_tokens == 8192, "défaut du dataclass (1000) = 1 pensée sur 11 coupée"


def test_le_plafond_suit_le_reglage_du_modele_principal():
    """Pas de nombre magique : la cognition hérite du plafond réglé pour le primaire."""
    role = cognition_llm_config({}, _llm_config(max_tokens=4096))
    assert role.max_tokens == 4096


def test_valeurs_par_defaut_quand_la_section_est_absente():
    role = cognition_llm_config({}, _llm_config())
    assert role.provider == "deepseek"
    assert role.model == "deepseek-v4-pro"
