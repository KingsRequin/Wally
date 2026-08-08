# bot/dashboard/auth.py
from __future__ import annotations

import hmac
import secrets
import time
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, QueryParams

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

    from bot.dashboard.state import AppState

# Tout ce qui est servi sous `/api/` demande le Bearer, SAUF les préfixes
# ci-dessous. Le sens de la garde est délibéré : elle refuse par défaut.
#
# Elle ne protégeait auparavant que `/api/admin/`, ce qui laissait `/api/actions/`
# — monté dans le bloc « Admin routes » de `app.py`, sans aucune `Depends()` —
# ouvert à qui atteignait le port : lecture des tâches planifiées, DÉCLENCHEMENT
# de leur exécution (Wally poste alors dans Discord/Twitch), réécriture des
# permissions, et les IDs de serveurs et de rôles Discord en prime. Le port est
# publié sur `0.0.0.0` (`docker-compose.yml`).
#
# La faille venait de la forme de la garde, pas de l'oubli : une protection par
# préfixe laisse passer tout routeur monté ailleurs, en silence. Un nouveau
# routeur est désormais fermé tant qu'on ne l'ouvre pas ICI, explicitement.
_API_PREFIX = "/api/"
_PUBLIC_PREFIXES = (
    "/api/public/",   # site public
    "/api/chat/",     # chat web : JWT Discord validé dans chaque route
    "/api/setup/",    # assistant de première installation, jeton dans l'URL
)

# Un redirect de navigateur venu de Twitch : aucun en-tête possible, et la route
# valide elle-même le `state` OAuth. Seule exemption inconditionnelle légitime.
_NO_AUTH = {"/api/admin/twitch/auth/callback"}

# `EventSource` ne peut pas envoyer d'en-tête : ces flux s'authentifient avec un
# TICKET à usage unique (`?ticket=`), échangé au préalable contre le Bearer.
# Ils étaient auparavant exemptés sans condition « trusted local network » —
# or `docker-compose.yml` publie le port sur `0.0.0.0`, et le sink loguru de
# `/sse/logs` diffuse le contenu des DM Discord.
_SSE_TICKETED = {
    "/api/admin/sse/logs",
    "/api/admin/sse/actions",
    "/api/admin/sse/voice",
}

# Court : le ticket ne sert qu'à ouvrir la connexion, dans la foulée de l'échange.
_TICKET_TTL_S = 30.0


def _needs_auth(path: str) -> bool:
    """Ce chemin exige-t-il le Bearer admin ?

    Hors de `/api/`, non : pages HTML, `/static`, `/overlay`, WebSocket. Sous
    `/api/`, OUI par défaut — seuls `_PUBLIC_PREFIXES` et `_NO_AUTH` en sortent.
    """
    if not path.startswith(_API_PREFIX):
        return False
    if path in _NO_AUTH:
        return False
    return not path.startswith(_PUBLIC_PREFIXES)


class SseTickets:
    """Tickets à usage unique pour les flux SSE admin.

    Un ticket plutôt qu'un `?token=` : le token du dashboard finirait dans les
    logs d'accès, l'historique du navigateur et le `Referer`, et il ne tourne
    jamais. Un ticket est valable 30 s, une seule fois.
    """

    def __init__(self) -> None:
        self._issued: dict[str, float] = {}

    def issue(self) -> str:
        now = time.monotonic()
        self._purge(now)
        ticket = secrets.token_urlsafe(32)
        self._issued[ticket] = now + _TICKET_TTL_S
        return ticket

    def consume(self, ticket: str) -> bool:
        now = time.monotonic()
        self._purge(now)
        expires = self._issued.pop(ticket, None)
        return expires is not None and expires >= now

    def _purge(self, now: float) -> None:
        for key in [k for k, exp in self._issued.items() if exp < now]:
            del self._issued[key]


class BearerAuthMiddleware:
    """Pur ASGI middleware (surtout PAS ``BaseHTTPMiddleware``).

    ``BaseHTTPMiddleware`` pipe la réponse dans un memory-stream anyio ; sur un
    flux SSE de longue durée, une déconnexion client interrompt ce stream et
    ``call_next`` lève ``RuntimeError("No response returned.")`` → une 500
    parasite loggée à chaque fermeture d'un ``/sse/*``. Un middleware ASGI natif
    ne bufferise jamais le corps : il délègue directement à ``self.app`` et est
    donc immunisé contre ce mode d'échec.
    """

    def __init__(self, app: ASGIApp, state: AppState) -> None:
        self.app = app
        self._state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not _needs_auth(path):
            await self.app(scope, receive, send)
            return

        token = self._state.config.bot.dashboard_token
        if not token:
            await JSONResponse(
                {"detail": "dashboard_token not configured"},
                status_code=503,
            )(scope, receive, send)
            return

        if path in _SSE_TICKETED:
            ticket = QueryParams(scope.get("query_string", b"")).get("ticket", "")
            if not ticket or not self._state.sse_tickets.consume(ticket):
                await JSONResponse(
                    {"detail": "Unauthorized"}, status_code=401
                )(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        auth = Headers(scope=scope).get("Authorization", "")
        # Comparaison à temps constant : le token ne bouge pas d'un redémarrage
        # à l'autre, une comparaison naïve est mesurable.
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], token):
            await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
            return

        await self.app(scope, receive, send)
