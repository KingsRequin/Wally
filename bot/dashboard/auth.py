# bot/dashboard/auth.py
from __future__ import annotations

import hmac
import secrets
import time
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from loguru import logger
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
    "/api/music/",    # extension musique : jeton PROPRE validé dans la route —
                      # lui donner le Bearer admin reviendrait à confier la
                      # mémoire, les logs et les DM à une extension installée
                      # sur la machine de quelqu'un d'autre.
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

# Verrou sur les échecs d'authentification. Le port est publié sur `0.0.0.0` et
# le tunnel Cloudflare rend `/api/admin/` joignable depuis Internet : sans
# compteur, un Bearer se cherchait à la vitesse du réseau, sans laisser la
# moindre trace.
#
# Le seuil est volontairement LARGE. La sécurité vient du token — 32 octets
# aléatoires ne se devinent pas, quel que soit le débit. Ce verrou sert à deux
# autres choses, qui manquaient toutes les deux :
#   · rendre l'attaque VISIBLE (une ligne WARNING au déclenchement) ;
#   · empêcher qu'elle noie les logs et le CPU.
# Un seuil serré aurait au contraire offert un déni de service : n'importe qui
# aurait pu tenir l'owner hors de son propre dashboard.
_ECHECS_FENETRE_S = 60.0
_ECHECS_SEUIL = 10
_VERROU_S = 60.0
_VERROU_MAX_S = 900.0
# Au-delà, on oublie l'origine : sans quoi le dictionnaire grossit sans fin sous
# un balayage d'adresses.
_ORIGINES_MAX = 1024


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


class VerrouEchecs:
    """Compte les échecs d'authentification par origine et verrouille par paliers.

    Clé : l'adresse du pair (`scope["client"]`). Derrière le tunnel, tout ce qui
    vient d'Internet partage l'adresse du conteneur `cloudflared` et donc UN
    SEUL seau — ce qui est le bon découpage ici : l'attaquant distant est
    dehors, l'owner est sur le LAN et garde le sien. On ne lit surtout pas
    `CF-Connecting-IP` : le port étant publié sur `0.0.0.0`, n'importe qui sur
    le réseau pourrait forger cet en-tête et se donner un seau neuf à chaque
    requête.

    Le verrou double à chaque récidive, plafonné : un attaquant obstiné paie
    quinze minutes par tentative, l'owner qui se trompe deux fois ne voit rien.
    """

    def __init__(self) -> None:
        # origine -> (horodatages d'échec récents, fin du verrou, nb de verrous)
        self._echecs: dict[str, list[float]] = {}
        self._verrous: dict[str, tuple[float, int]] = {}

    def verrouille(self, origine: str) -> float:
        """Secondes restantes de verrou, 0.0 si l'origine peut essayer."""
        fin, _ = self._verrous.get(origine, (0.0, 0))
        return max(0.0, fin - time.monotonic())

    def succes(self, origine: str) -> None:
        """Un Bearer valide efface l'ardoise — y compris le compteur de récidive.

        Sinon l'owner qui se trompe une fois par semaine finirait, au bout de
        quelques mois, avec un quart d'heure de verrou sur sa propre adresse.
        """
        self._echecs.pop(origine, None)
        self._verrous.pop(origine, None)

    def echec(self, origine: str) -> None:
        maintenant = time.monotonic()
        self._purger(maintenant)
        recents = [t for t in self._echecs.get(origine, []) if t > maintenant - _ECHECS_FENETRE_S]
        recents.append(maintenant)
        self._echecs[origine] = recents
        if len(recents) < _ECHECS_SEUIL:
            return

        _, rang = self._verrous.get(origine, (0.0, 0))
        rang += 1
        duree = min(_VERROU_S * (2 ** (rang - 1)), _VERROU_MAX_S)
        self._verrous[origine] = (maintenant + duree, rang)
        self._echecs.pop(origine, None)   # la fenêtre repart après le verrou
        # INFO ne suffit pas : c'est la seule trace qu'on cherche un Bearer.
        logger.warning(
            "Auth admin : {n} échecs depuis {o} — verrou {d:.0f} s (récidive n°{r})",
            n=_ECHECS_SEUIL, o=origine, d=duree, r=rang,
        )

    def _purger(self, maintenant: float) -> None:
        if len(self._echecs) <= _ORIGINES_MAX:
            return
        morts = [o for o, ts in self._echecs.items()
                 if not ts or ts[-1] < maintenant - _ECHECS_FENETRE_S]
        for o in morts:
            del self._echecs[o]
        # Toujours trop : on repart de zéro plutôt que de gonfler sans fin. Une
        # origine légitime refera au pire une tentative.
        if len(self._echecs) > _ORIGINES_MAX:
            self._echecs.clear()


def _origine(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else "inconnue"


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
        self.verrou = VerrouEchecs()

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

        # Le verrou est consulté AVANT toute comparaison : une origine bloquée
        # ne doit pas pouvoir mesurer quoi que ce soit, ni faire tourner le CPU.
        origine = _origine(scope)
        restant = self.verrou.verrouille(origine)
        if restant > 0:
            await JSONResponse(
                {"detail": "Too many failed attempts"},
                status_code=429,
                headers={"Retry-After": str(int(restant) + 1)},
            )(scope, receive, send)
            return

        if path in _SSE_TICKETED:
            ticket = QueryParams(scope.get("query_string", b"")).get("ticket", "")
            if not ticket or not self._state.sse_tickets.consume(ticket):
                # Compté comme les autres : un ticket est échangé contre le
                # Bearer, en deviner un revient au même.
                self.verrou.echec(origine)
                await JSONResponse(
                    {"detail": "Unauthorized"}, status_code=401
                )(scope, receive, send)
                return
            self.verrou.succes(origine)
            await self.app(scope, receive, send)
            return

        auth = Headers(scope=scope).get("Authorization", "")
        # Comparaison à temps constant : le token ne bouge pas d'un redémarrage
        # à l'autre, une comparaison naïve est mesurable.
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], token):
            self.verrou.echec(origine)
            await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
            return

        self.verrou.succes(origine)
        await self.app(scope, receive, send)
