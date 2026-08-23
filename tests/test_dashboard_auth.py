import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from bot.dashboard.auth import BearerAuthMiddleware, SseTickets


def _make_app(token: str | None) -> FastAPI:
    """Helper : app minimale avec middleware auth et une route admin."""
    cfg = MagicMock()
    cfg.bot.dashboard_token = token
    state = MagicMock()
    state.config = cfg
    state.sse_tickets = SseTickets()

    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, state=state)
    app.state.tickets = state.sse_tickets

    @app.get("/api/admin/test")
    async def admin_route():
        return {"ok": True}

    @app.get("/api/public/test")
    async def public_route():
        return {"ok": True}

    @app.get("/api/admin/sse/logs")
    async def sse_logs_route():
        return {"ok": True}

    @app.get("/api/actions/tasks")
    async def actions_route():
        return {"ok": True}

    @app.get("/api/chat/sessions")
    async def chat_route():
        return {"ok": True}

    @app.get("/overlay")
    async def overlay_page():
        return {"ok": True}

    return app


def test_public_route_no_auth_required():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/public/test")
    assert r.status_code == 200


def test_admin_valid_token():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer secret123"})
    assert r.status_code == 200


def test_admin_invalid_token_returns_401():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_admin_no_token_header_returns_401():
    client = TestClient(_make_app("secret123"))
    r = client.get("/api/admin/test")
    assert r.status_code == 401


def test_admin_token_not_configured_returns_503():
    client = TestClient(_make_app(None))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503


def test_admin_empty_token_returns_503():
    client = TestClient(_make_app(""))
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503


def test_sse_logs_refuse_sans_ticket():
    """Ces routes étaient servies SANS AUCUNE authentification — `/sse/logs`
    diffuse le contenu des DM Discord, et le port est publié sur 0.0.0.0."""
    client = TestClient(_make_app("secret123"))
    assert client.get("/api/admin/sse/logs").status_code == 401


def test_sse_logs_accepte_un_ticket_valide():
    """`EventSource` ne peut pas envoyer d'en-tête : un ticket à usage unique
    remplace le Bearer, sans laisser le token dans les logs d'accès."""
    app = _make_app("secret123")
    client = TestClient(app)
    ticket = app.state.tickets.issue()
    assert client.get(f"/api/admin/sse/logs?ticket={ticket}").status_code == 200


def test_un_ticket_ne_sert_qu_une_fois():
    app = _make_app("secret123")
    client = TestClient(app)
    ticket = app.state.tickets.issue()
    client.get(f"/api/admin/sse/logs?ticket={ticket}")
    assert client.get(f"/api/admin/sse/logs?ticket={ticket}").status_code == 401


def test_un_ticket_expire():
    tickets = SseTickets()
    ticket = tickets.issue()
    tickets._issued[ticket] = 0.0        # périmé
    assert tickets.consume(ticket) is False


def test_le_callback_twitch_reste_sans_auth():
    """Redirect de navigateur venu de Twitch : aucun en-tête possible, et la
    route valide elle-même le `state` OAuth."""
    from bot.dashboard.auth import _NO_AUTH
    assert "/api/admin/twitch/auth/callback" in _NO_AUTH


def test_api_actions_exige_le_bearer():
    """`/api/actions/*` était servi SANS AUCUNE authentification.

    La garde ne couvrait que le préfixe `/api/admin/`, or ce routeur est monté
    sous `/api/actions` — et le port est publié sur 0.0.0.0. N'importe qui
    pouvait lire les tâches planifiées, DÉCLENCHER leur exécution (Wally poste
    alors dans Discord/Twitch) et réécrire les permissions d'actions.
    """
    client = TestClient(_make_app("secret123"))
    assert client.get("/api/actions/tasks").status_code == 401
    assert client.get(
        "/api/actions/tasks", headers={"Authorization": "Bearer secret123"}
    ).status_code == 200


def test_tout_nouveau_routeur_api_est_ferme_par_defaut():
    """Le fond du bug : une garde par préfixe laisse passer ce qu'on monte
    ailleurs, en silence. Elle refuse désormais par défaut — un routeur `/api/`
    inconnu de la liste publique est fermé sans qu'on ait à y penser."""
    from bot.dashboard.auth import _needs_auth

    assert _needs_auth("/api/actions/tasks")
    assert _needs_auth("/api/admin/config")
    assert _needs_auth("/api/un-routeur-invente-demain/x")
    # Les seules ouvertures, explicites.
    assert not _needs_auth("/api/public/status")
    assert not _needs_auth("/api/chat/sessions")
    assert not _needs_auth("/api/setup/abc/save")
    assert not _needs_auth("/api/admin/twitch/auth/callback")
    # Hors `/api/` : pages HTML, statiques, overlay.
    assert not _needs_auth("/overlay")
    assert not _needs_auth("/static/app.js")


def test_les_chemins_non_api_restent_ouverts():
    """Le durcissement ne doit pas fermer l'overlay ni le site public."""
    client = TestClient(_make_app("secret123"))
    assert client.get("/overlay").status_code == 200
    assert client.get("/api/public/test").status_code == 200
    assert client.get("/api/chat/sessions").status_code == 200


def test_middleware_is_pure_asgi_not_basehttp():
    """Régression bug 500 SSE : le middleware NE DOIT PAS hériter de
    BaseHTTPMiddleware (dont le pipe memory-stream lève « No response returned. »
    quand un client SSE se déconnecte). Un pur ASGI middleware est immunisé."""
    from starlette.middleware.base import BaseHTTPMiddleware
    assert not issubclass(BearerAuthMiddleware, BaseHTTPMiddleware)


def test_streaming_response_flows_through_middleware():
    """Une réponse SSE (StreamingResponse) traverse le middleware sans être
    bufferisée : le corps streamé arrive intégralement au client."""
    from fastapi.responses import StreamingResponse

    cfg = MagicMock()
    cfg.bot.dashboard_token = "secret123"
    state = MagicMock()
    state.config = cfg
    tickets = SseTickets()
    state.sse_tickets = tickets

    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, state=state)

    async def _gen():
        for i in range(3):
            yield f"data: {i}\n\n"

    @app.get("/api/admin/sse/logs")
    async def sse_logs():
        return StreamingResponse(_gen(), media_type="text/event-stream")

    client = TestClient(app)
    with client.stream("GET", f"/api/admin/sse/logs?ticket={tickets.issue()}") as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())
    assert "data: 0" in body and "data: 2" in body


# ── verrou sur les échecs d'authentification ────────────────────────────────
#
# Le port est publié sur `0.0.0.0` et le tunnel Cloudflare rend `/api/admin/`
# joignable depuis Internet. Avant ce verrou, on cherchait un Bearer à la
# vitesse du réseau sans laisser la moindre trace dans les logs.

def _client_verrou(token="bon-token"):
    """App minimale protégée. Chaque appel rend un verrou NEUF (le middleware
    est instancié avec l'app), donc les tests ne se contaminent pas."""
    cfg = MagicMock()
    cfg.bot.dashboard_token = token
    state = MagicMock()
    state.config = cfg
    state.sse_tickets = SseTickets()

    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, state=state)

    @app.get("/api/admin/test")
    async def admin_route():
        return {"ok": True}

    return TestClient(app)


def _mauvais(client, n):
    for _ in range(n):
        client.get("/api/admin/test", headers={"Authorization": "Bearer faux"})


def test_dix_echecs_verrouillent_l_origine():
    client = _client_verrou()
    _mauvais(client, 10)
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer faux"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_le_verrou_ferme_AUSSI_la_porte_au_bon_token():
    """Sinon il ne servirait à rien : l'attaquant qui tombe juste passerait
    quand même, et le verrou n'aurait fait que ralentir les mauvais essais."""
    client = _client_verrou()
    _mauvais(client, 10)
    r = client.get("/api/admin/test", headers={"Authorization": "Bearer bon-token"})
    assert r.status_code == 429


def test_neuf_echecs_ne_verrouillent_PAS():
    """Le seuil est large exprès : un verrou serré offrirait un déni de service
    — n'importe qui tiendrait l'owner hors de son propre dashboard."""
    client = _client_verrou()
    _mauvais(client, 9)
    assert client.get("/api/admin/test",
                      headers={"Authorization": "Bearer bon-token"}).status_code == 200


def test_un_succes_efface_l_ardoise():
    client = _client_verrou()
    _mauvais(client, 9)
    assert client.get("/api/admin/test",
                      headers={"Authorization": "Bearer bon-token"}).status_code == 200
    _mauvais(client, 9)    # 18 échecs en tout, mais le compteur est reparti de 0
    assert client.get("/api/admin/test",
                      headers={"Authorization": "Bearer bon-token"}).status_code == 200


def test_le_verrou_double_a_chaque_recidive_et_plafonne():
    from bot.dashboard.auth import VerrouEchecs, _VERROU_MAX_S, _VERROU_S, _ECHECS_SEUIL
    v = VerrouEchecs()
    durees = []
    for _ in range(6):
        for _ in range(_ECHECS_SEUIL):
            v.echec("1.2.3.4")
        durees.append(v.verrouille("1.2.3.4"))
    assert durees[0] == pytest.approx(_VERROU_S, abs=1.0)
    assert durees[1] == pytest.approx(_VERROU_S * 2, abs=1.0)
    assert durees[-1] == pytest.approx(_VERROU_MAX_S, abs=1.0)   # plafonné


def test_une_autre_origine_n_est_pas_punie():
    """Le verrou est PAR origine : sinon un attaquant enfermerait l'owner."""
    from bot.dashboard.auth import VerrouEchecs, _ECHECS_SEUIL
    v = VerrouEchecs()
    for _ in range(_ECHECS_SEUIL):
        v.echec("9.9.9.9")
    assert v.verrouille("9.9.9.9") > 0
    assert v.verrouille("192.168.1.10") == 0


def test_un_ticket_SSE_devine_compte_comme_un_echec():
    """Un ticket s'échange contre le Bearer : en deviner un revient au même."""
    from bot.dashboard.auth import VerrouEchecs, _ECHECS_SEUIL
    cfg = MagicMock(); cfg.bot.dashboard_token = "bon-token"
    state = MagicMock(); state.config = cfg; state.sse_tickets = SseTickets()
    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, state=state)

    @app.get("/api/admin/sse/logs")
    async def flux():
        return {"ok": True}

    client = TestClient(app)
    for _ in range(_ECHECS_SEUIL):
        client.get("/api/admin/sse/logs?ticket=invente")
    assert client.get("/api/admin/sse/logs?ticket=invente").status_code == 429


def test_le_verrou_ne_grossit_pas_sans_fin():
    """Un balayage d'adresses ne doit pas faire enfler la mémoire du process."""
    from bot.dashboard.auth import VerrouEchecs, _ORIGINES_MAX
    v = VerrouEchecs()
    for i in range(_ORIGINES_MAX * 2):
        v.echec(f"10.0.{i // 256}.{i % 256}")
    assert len(v._echecs) <= _ORIGINES_MAX
