# tests/test_llm_deepseek_dsml.py
"""Fuite de markup DSML de DeepSeek V4 dans le texte public.

Vécu le 2026-08-07 sur le chat d'azrael_ttv : Wally a posté tel quel
`<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="scrape_url">…` au lieu d'appeler
l'outil. L'appel avait épuisé `max_tool_iters` (6 outils, seul appel du corpus à
atteindre le cap) et la génération finale retirait `tools` de la requête : le
modèle, encore en mode outil, a écrit son appel en texte.

Bug amont connu (émission non déterministe) : deepseek-ai/DeepSeek-V3#1244,
vllm-project/vllm#40801.
"""
from types import SimpleNamespace

import pytest

from bot.core.llm.deepseek import (
    DeepSeekLLMClient,
    _parse_dsml_tool_calls,
    _strip_dsml,
)

# Le markup exact relevé dans logs/conversations/twitch/azrael_ttv/2026-08-07.jsonl
DSML_SCRAPE = (
    '<｜｜DSML｜｜tool_calls>\n'
    '<｜｜DSML｜｜invoke name="scrape_url">\n'
    '<｜｜DSML｜｜parameter name="url" string="true">'
    'https://apex.tracker.gg/apex/leaderboards/stats/all/Kills?page=1&legend=ash'
    '</｜｜DSML｜｜parameter>\n'
    '</｜｜DSML｜｜invoke>\n'
    '</｜｜DSML｜｜tool_calls>'
)


# ── Doublures ────────────────────────────────────────────────────────────────

class _FakeToolCall:
    def __init__(self, name: str, arguments: str, id_: str = "call_1") -> None:
        self.id = id_
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments=arguments)

    def model_dump(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


def _response(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        model="deepseek-v4-pro",
    )


class _FakeCompletions:
    """Rejoue `responses` dans l'ordre ; la dernière est répétée si besoin."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


class _FakeDB:
    async def log_cost(self, **_kwargs) -> None:
        return None


def _client(responses: list) -> tuple[DeepSeekLLMClient, _FakeCompletions]:
    client = DeepSeekLLMClient(model="deepseek-v4-pro", db=_FakeDB(), max_tool_iters=6)
    fake = _FakeCompletions(responses)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return client, fake


async def _executor(_name: str, _args: str) -> str:
    return "resultat outil"


TOOLS = [{"type": "function", "function": {"name": "scrape_url", "parameters": {}}}]


# ── Le parseur ───────────────────────────────────────────────────────────────

def test_parse_extrait_nom_et_parametres():
    assert _parse_dsml_tool_calls(DSML_SCRAPE) == [
        ("scrape_url", {"url": "https://apex.tracker.gg/apex/leaderboards/stats/all/Kills?page=1&legend=ash"})
    ]


def test_parse_ignore_un_texte_normal():
    assert _parse_dsml_tool_calls("Le top 3 avec Ash en France, c'est chaud à trouver.") == []


def test_strip_retire_le_bloc_entier_pas_seulement_les_balises():
    nettoye = _strip_dsml(f"Je regarde ça.\n{DSML_SCRAPE}")
    assert nettoye == "Je regarde ça."
    assert "DSML" not in nettoye
    assert "apex.tracker.gg" not in nettoye


def test_strip_retire_les_fragments_orphelins():
    # Cas streaming : marqueur coupé entre deux chunks (vllm#40801)
    assert "DSML" not in _strip_dsml("Salut <｜｜DSML｜｜invoke name=\"web_search\"> les gens")


# ── Le comportement du client ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generation_finale_garde_les_outils_mais_en_interdit_l_appel():
    """La racine : retirer `tools` pousse le modèle à écrire son appel en texte."""
    boucle = [_response(tool_calls=[_FakeToolCall("scrape_url", "{}")]) for _ in range(6)]
    client, fake = _client(boucle + [_response(content="Voilà ce que j'ai trouvé.")])

    texte, _ = await client.complete_with_tools("sys", [{"role": "user", "content": "top 3"}], TOOLS, _executor)

    dernier = fake.calls[-1]
    assert dernier.get("tools") == TOOLS, "les outils doivent rester visibles à la génération finale"
    assert dernier.get("tool_choice") == "none", "le modèle doit savoir qu'il ne peut plus les appeler"
    assert texte == "Voilà ce que j'ai trouvé."


@pytest.mark.asyncio
async def test_le_markup_ne_part_jamais_en_texte_public():
    """Défense en profondeur : même si le modèle fuit, rien ne sort en public."""
    boucle = [_response(tool_calls=[_FakeToolCall("scrape_url", "{}")]) for _ in range(6)]
    client, _ = _client(boucle + [_response(content=DSML_SCRAPE)])

    texte, _ = await client.complete_with_tools("sys", [{"role": "user", "content": "top 3"}], TOOLS, _executor)

    assert "DSML" not in texte


@pytest.mark.asyncio
async def test_un_appel_fuite_en_texte_est_quand_meme_execute():
    """Bug amont : `tool_calls` vide + markup dans `content` → on exécute l'outil."""
    client, _ = _client([
        _response(content=DSML_SCRAPE, tool_calls=None),
        _response(content="Le top 3 Ash France : …"),
    ])
    appels: list[tuple[str, str]] = []

    async def _spy(name: str, args: str) -> str:
        appels.append((name, args))
        return "page scrapée"

    texte, outils = await client.complete_with_tools("sys", [{"role": "user", "content": "top 3"}], TOOLS, _spy)

    assert appels and appels[0][0] == "scrape_url"
    assert "apex.tracker.gg" in appels[0][1]
    assert outils == ["scrape_url"]
    assert texte == "Le top 3 Ash France : …"


@pytest.mark.asyncio
async def test_complete_nettoie_aussi_le_markup():
    client, _ = _client([_response(content=f"Bonjour.\n{DSML_SCRAPE}")])
    assert await client.complete("sys", [{"role": "user", "content": "salut"}]) == "Bonjour."
