# tests/test_cout_tool.py
"""« Tu coûtes combien ? » — il répond, mais ne le dit jamais de lui-même (2026-08-31).

Arbitrage de l'owner : l'alerte publique de coût est éteinte (le défaut de
`cost_alert_threshold` est passé à 0), mais la question doit trouver une
réponse. Sans cet outil, Wally n'avait que deux issues devant « il coute chère
le wally » : inventer un chiffre, ou nier avoir accès à une table qu'il tient
depuis 98 957 lignes.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.tools.cout_tool import COUT_TOOL, run_cout_tool


def _bot(*, jour=0.5, mois=22.93, projection=35.26):
    bot = MagicMock()
    bot.db.get_cost_since = AsyncMock(side_effect=lambda depuis: (
        jour if depuis > __import__("time").time() - 2 * 86_400 else mois))
    return bot


@pytest.mark.asyncio
async def test_les_trois_fenetres_sont_rendues(monkeypatch):
    """Elles ne disent pas la même chose : le dépensé, l'aujourd'hui, et le
    rythme projeté — c'est ce dernier qui a montré la dérive de DeepSeek."""
    monkeypatch.setattr("bot.core.cout_veille.projection_mensuelle",
                        AsyncMock(return_value=35.26))

    rendu = json.loads(await run_cout_tool(_bot(), {}))

    assert rendu["dernieres_24h_usd"] == 0.5
    assert rendu["30_derniers_jours_usd"] == 22.93
    assert rendu["projection_mensuelle_usd"] == 35.26


@pytest.mark.asyncio
async def test_une_base_vide_ne_dit_pas_zero(monkeypatch):
    """0,00 $ se lirait « ça ne coûte rien » alors que ça veut dire « on ne
    sait pas encore » — même règle que `cout_veille.projection_mensuelle`."""
    monkeypatch.setattr("bot.core.cout_veille.projection_mensuelle",
                        AsyncMock(return_value=None))

    rendu = json.loads(await run_cout_tool(_bot(jour=0.0, mois=0.0), {}))

    assert "reponse" in rendu
    assert "0" not in rendu["reponse"]


@pytest.mark.asyncio
async def test_une_base_illisible_ne_leve_pas():
    bot = MagicMock()
    bot.db.get_cost_since = AsyncMock(side_effect=RuntimeError("db locked"))

    rendu = json.loads(await run_cout_tool(bot, {}))

    assert "erreur" in rendu


@pytest.mark.asyncio
async def test_sans_base_il_ne_devine_pas():
    bot = MagicMock()
    bot.db = None

    assert "erreur" in json.loads(await run_cout_tool(bot, {}))


def test_l_outil_interdit_d_en_parler_de_lui_meme():
    """C'est la demande de l'owner, et elle ne tient qu'à cette phrase : rien
    dans le code n'empêche le modèle d'aborder le sujet, seule la description
    de l'outil le lui dit."""
    description = COUT_TOOL["function"]["description"]

    assert "JAMAIS de toi-même" in description or "de toi-même" in description
    assert "invente" in description
