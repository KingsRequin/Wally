"""Le catalogue de l'image autonome ne part qu'une fois la capacité OUVERTE.

Même patron que les widgets d'overlay : décrire une action impossible coûte des
tokens à chaque tick et fait décider en boucle une action qui sera jetée au
dispatch. Et les salons annoncés doivent être ceux qui autorisent réellement —
sinon Wally promet un salon interdit et se fait refuser sans comprendre.
"""
from pathlib import Path

import pytest

from bot.config import ImageGenerationConfig
from bot.core.image_initiative import ImageInitiative
from bot.intelligence.reasoning_agent import ReasoningAgent
from tests.test_selfupgrade_historique_groupe import _ctx

_PROMPTS = Path(__file__).parent.parent / "bot" / "intelligence" / "persona" / "prompts"
SALON = "938504877464768603"


class _Db:
    async def get_user_image_count_today(self, user_id):
        return 0

    async def get_last_image_ts(self, user_id):
        return None


@pytest.fixture(autouse=True)
def _overlay_au_repos(monkeypatch):
    monkeypatch.setattr(
        "bot.intelligence.overlay_narrator.overlay_actif", lambda: False, raising=False
    )


def _initiative(salons):
    config = type("C", (), {"image_generation": ImageGenerationConfig(
        autonomous_enabled=True, autonomous_channel_ids=salons,
        autonomous_daily_limit=3, autonomous_cooldown_minutes=90,
    )})()
    return ImageInitiative(config, _Db(), channel_names={SALON: "#shitpost"},
                           auteur_id="discord:7")


def _agent(salons):
    return ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS,
                          image_initiative=_initiative(salons))


def test_rien_quand_aucun_salon_nest_ouvert():
    assert "generate_image" not in _agent([])._format_context(_ctx())


def test_le_catalogue_apparait_avec_les_salons_reels():
    rendu = _agent([SALON])._format_context(_ctx())
    assert "generate_image" in rendu
    assert SALON in rendu and "#shitpost" in rendu
    # La cadence est SERVIE par la politique, pas recopiée dans le gabarit.
    assert "3 image(s) par jour" in rendu
    assert "{{SALONS}}" not in rendu and "{{CADENCE}}" not in rendu


def test_un_agent_sans_initiative_ne_casse_pas():
    """Plusieurs chemins construisent l'agent sans cette dépendance."""
    agent = ReasoningAgent(llm=None, fact_store=None, prompts_dir=_PROMPTS)
    assert "generate_image" not in agent._format_context(_ctx())
