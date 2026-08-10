# tests/test_audit2_phaseD_integrite.py
"""Phase D du second audit : intégrité et exposition.

A2-12 — le tirage « top » de la galerie était INVERSÉ : `RANDOM()` est signé,
        le tri ascendant favorisait donc les images sans vote.
A2-status — `/api/public/status` publiait le snowflake réel du propriétaire à
        tout visiteur anonyme, pour une comparaison cosmétique côté client.
"""
import sqlite3
from pathlib import Path

import pytest
from unittest.mock import MagicMock


# ────────────────────────────── A2-12 ──────────────────────────────
def _tirages(expression: str, n: int = 3000) -> float:
    """Part des images à 50 votes tirées, en pourcentage."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE g(id INT, votes INT)")
    for i in range(8):
        c.execute("INSERT INTO g VALUES(?, 0)", (i,))
    c.execute("INSERT INTO g VALUES(8, 50)")
    c.execute("INSERT INTO g VALUES(9, 50)")
    gagnants = sum(
        1 for _ in range(n)
        if c.execute(f"SELECT id FROM g ORDER BY {expression} LIMIT 1").fetchone()[0] >= 8
    )
    return gagnants * 100.0 / n


def test_random_signe_inverse_bien_la_ponderation():
    """Le point de départ : ce n'est pas une hypothèse sur SQLite."""
    assert _tirages("RANDOM() * 1.0 / (votes + 1)") < 5.0


def test_la_ponderation_favorise_desormais_les_images_votees():
    assert _tirages("ABS(RANDOM()) * 1.0 / (votes + 1)") > 80.0


def test_la_requete_de_production_utilise_abs():
    src = Path("bot/db/mixins/gallery.py").read_text(encoding="utf-8")
    assert "ORDER BY ABS(RANDOM()) * 1.0 / (COALESCE(v.votes, 0) + 1)" in src
    assert "ORDER BY RANDOM() * 1.0 /" not in src


# ────────────────────────────── statut public ──────────────────────────────
@pytest.mark.asyncio
async def test_le_statut_public_ne_publie_plus_l_identifiant_du_proprietaire():
    from bot.dashboard.routes.status import get_status

    requete = MagicMock()
    etat = requete.app.state.wally
    etat.config.bot.owner_discord_id = "610550333042589752"

    out = await get_status(requete)
    assert "owner_discord_id" not in out
    assert "610550333042589752" not in str(out)


def test_le_jwt_porte_le_verdict_signe():
    from bot.dashboard.routes.chat_auth import create_jwt, decode_jwt

    secret = "s3cr3t"
    jeton = create_jwt("610", "KingsRequin", None, secret, is_owner=True)
    charge = decode_jwt(jeton, secret)
    assert charge["is_owner"] is True

    autre = decode_jwt(create_jwt("111", "Bob", None, secret), secret)
    assert autre["is_owner"] is False


def test_le_front_lit_le_verdict_et_non_l_identifiant():
    src = Path("bot/dashboard/static/public-starter/app.js").read_text(encoding="utf-8")
    assert "p.is_owner === true" in src
    assert "OWNER_DISCORD_ID" not in src
    assert "owner_discord_id" not in src


def test_est_owner_refuse_quand_aucun_proprietaire_nest_configure():
    from bot.dashboard.routes.chat_auth import _est_owner

    requete = MagicMock()
    requete.app.state.wally.config.bot.owner_discord_id = ""
    assert _est_owner(requete, "610") is False
