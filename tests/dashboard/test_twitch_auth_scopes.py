"""Les scopes demandés et l'URI de redirection produite.

Un nouveau token REMPLACE l'ancien avec exactement les scopes demandés :
n'en demander que deux ferait perdre abonnés et bits en silence.
"""
import urllib.parse

from bot.dashboard.routes.twitch_auth import _STREAMER_SCOPES, _base_url_propre


def test_les_six_scopes_streamer_sont_demandes():
    """Le compte EXACT, et pas seulement une inclusion : c'est ce qui rend
    visible un scope perdu en route.

    Six depuis le 2026-09-01 : `channel:manage:clips` (clipper à la demande)
    s'ajoute à `channel:manage:predictions` (2026-08-18, §13) et aux quatre
    d'origine. Le token EN SERVICE n'en porte que cinq — il faut refaire
    l'autorisation du streamer depuis le dashboard pour que le sixième prenne
    effet, et `scopes_manquants()` le journalise désormais à chaque validation.
    """
    scopes = set(_STREAMER_SCOPES.split())
    assert scopes == {
        "channel:read:subscriptions", "bits:read",
        "channel:read:redemptions", "channel:manage:redemptions",
        "channel:manage:predictions", "channel:manage:clips",
    }


def test_le_slash_final_de_WEB_BASE_URL_est_retire(monkeypatch):
    """Twitch exige une correspondance EXACTE de l'URI enregistrée. Un
    WEB_BASE_URL finissant par « / » produisait un double slash."""
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    assert _base_url_propre("http://fallback") == "https://heywally.fr"


def test_le_fallback_est_nettoye_aussi(monkeypatch):
    monkeypatch.delenv("WEB_BASE_URL", raising=False)
    assert _base_url_propre("http://localhost:8080/") == "http://localhost:8080"


def test_l_uri_de_redirection_n_a_pas_de_double_slash(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    uri = f"{_base_url_propre('x')}/api/admin/twitch/auth/callback"
    assert "//api" not in uri
    assert uri == "https://heywally.fr/api/admin/twitch/auth/callback"
    # et il survit à l'encodage utilisé dans l'URL d'autorisation
    assert "%2F%2Fapi" not in urllib.parse.quote(uri, safe="")
