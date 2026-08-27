# bot/twitch/api.py
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import asyncio
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import unicodedata

import httpx
from loguru import logger

from bot.core.account_linker import matches_name
from bot.core.secret_guard import redact

if TYPE_CHECKING:
    from bot.twitch.token_manager import TwitchTokenManager

# Client-ID public du site web Twitch. Il n'appartient pas à l'application :
# c'est celui que le lecteur du site présente, et le seul que l'API GraphQL
# accepte. Identique dans yt-dlp et streamlink. Rien de secret ici.
_GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


def _refus_helix(resp: httpx.Response) -> Optional[dict]:
    """Le refus que Twitch cache dans un 200. `None` = message publié.

    `POST /helix/chat/messages` répond 200 « requête recevable », puis dit dans
    son corps s'il a publié quoi que ce soit : `is_sent: false` accompagné d'un
    `drop_reason` quand AutoMod retient le message, que la chaîne est en mode
    abonnés ou followers, ou que le bot y est en timeout. Le statut seul ne
    distingue donc pas une réplique lue de tous d'une réplique tombée dans le
    vide.

    Le doute profite à l'envoi : un corps illisible rend `None`. Répondre
    « refusé » à tort ferait oublier à Wally une phrase réellement publiée,
    alors qu'il la retrouve dans son prélude et sa mémoire.
    """
    try:
        data = (resp.json() or {}).get("data") or []
        envoi = data[0] if data else {}
        # `is False` et non `not ...` : un `is_sent` absent est un corps qu'on ne
        # sait pas lire, pas un refus.
        if envoi.get("is_sent") is False:
            # `or {}` plutôt qu'un défaut de `.get` : Twitch écrit
            # explicitement `drop_reason: null` quand il n'en donne pas.
            return envoi.get("drop_reason") or {}
    except Exception:  # noqa: BLE001 — un corps inattendu ne perd pas le message
        return None
    return None


def _ratelimit_wait(resp, *, default: float = 1.0, cap: float = 5.0) -> float:
    """Secondes à attendre après un 429, d'après `Ratelimit-Reset` (epoch)."""
    try:
        reset = float(resp.headers.get("Ratelimit-Reset", ""))
    except (TypeError, ValueError):
        return default
    return max(default, min(cap, reset - time.time()))


# Forme canonique du « pas de live ». `get_stream()` doit TOUJOURS rendre un
# dict : tout le reste du code (StreamWatcher, build_system_prompt, handlers)
# l'indexe sans garde, et un `None` y remonte en AttributeError/TypeError.
_OFFLINE_STREAM = {
    "live": False,
    "title": None,
    "category": None,
    "viewers": 0,
    "started_at": None,
}

# Même forme, marquée « je n'ai pas pu demander ». Une API muette rendait un
# « pas de live » indiscernable d'une vraie fin de stream : le 2026-08-08, une
# coupure réseau a produit une transition live → offline en plein live, et Wally
# a quitté le vocal dans la seconde. Les appelants qui se contentent d'un statut
# (prompt, dashboard) n'y voient que du feu ; `StreamWatcher` s'en sert pour
# garder son état plutôt que d'inventer une transition.
_UNKNOWN_STREAM = {**_OFFLINE_STREAM, "unknown": True}



# Limites Twitch sur une récompense de points de chaîne (§6 de la spec du duel).
TITRE_MAX = 45
PROMPT_MAX = 200


def _corps_recompense(titre: str, cout: int, prompt: str,
                      cooldown_s: int = 0) -> dict:
    """Les champs éditables d'une récompense, tronqués aux limites Twitch.

    Partagé par la création et la mise à jour, et c'est tout l'intérêt : une
    récompense créée et la même récompense mise à jour portent ainsi le MÊME
    libellé au caractère près. Sans ce partage, un titre trop long serait
    tronqué à la création puis jugé « différent » du titre configuré à chaque
    démarrage — un PATCH par boot, indéfiniment.

    `cooldown_s` est le temps de recharge GLOBAL : Twitch refuse lui-même
    l'achat pendant ce délai, donc il n'y a rien à rembourser et le viewer voit
    le compte à rebours sur le bouton. Un garde maison aurait fait payer puis
    remboursé — beaucoup de code pour un moins bon résultat.

    À zéro, la DURÉE n'est pas envoyée du tout : Twitch impose un minimum de 1,
    et « désactivé » se dit par le seul booléen. L'envoyer quand même ferait
    refuser la requête entière pour un champ qui ne sert à rien.
    """
    corps = {
        "title": (titre or "")[:TITRE_MAX],
        "cost": max(1, int(cout)),
        "prompt": (prompt or "")[:PROMPT_MAX],
        "is_global_cooldown_enabled": int(cooldown_s or 0) > 0,
    }
    if int(cooldown_s or 0) > 0:
        corps["global_cooldown_seconds"] = int(cooldown_s)
    return corps


def _aplatir_cooldown(recompense: dict) -> dict:
    """La récompense telle que Twitch la REND, ramenée à la forme qu'il LIT.

    Asymétrie confirmée dans la doc Helix : la requête porte
    `is_global_cooldown_enabled` et `global_cooldown_seconds` à plat, la
    réponse les rend imbriqués dans `global_cooldown_setting {is_enabled,
    global_cooldown_seconds}`.

    Sans cette traduction, les deux clés seraient toujours ABSENTES de la
    récompense actuelle — donc jamais comptées comme un écart (règle « un champ
    absent n'est pas un champ vide »), donc un cooldown ne serait JAMAIS posé
    sur une récompense déjà créée. Et la relecture d'après-PATCH ne le verrait
    pas revenir non plus : un PATCH réussi serait déclaré non appliqué.
    """
    reglage = recompense.get("global_cooldown_setting")
    if not isinstance(reglage, dict):
        return recompense
    return {
        **recompense,
        "is_global_cooldown_enabled": bool(reglage.get("is_enabled")),
        "global_cooldown_seconds": int(reglage.get("global_cooldown_seconds") or 0),
    }


def _fold(text: str) -> str:
    """Minuscules sans accents : « fusée » et « fusee » se cherchent pareil."""
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


class TwitchAPI:
    MESSAGES_URL = "https://api.twitch.tv/helix/chat/messages"
    STREAMS_URL = "https://api.twitch.tv/helix/streams"
    USERS_URL = "https://api.twitch.tv/helix/users"
    REDEMPTIONS_URL = "https://api.twitch.tv/helix/channel_points/custom_rewards/redemptions"
    REWARDS_URL = "https://api.twitch.tv/helix/channel_points/custom_rewards"
    PREDICTIONS_URL = "https://api.twitch.tv/helix/predictions"

    def __init__(
        self,
        token_manager: "TwitchTokenManager",
        client_id: str,
        bot_id: str,
        broadcaster_id: str,
    ):
        self._tm = token_manager
        self._client_id = client_id
        self._bot_id = bot_id
        self._broadcaster_id = broadcaster_id

    async def send_message(
        self,
        text: str,
        broadcaster_id: Optional[str] = None,
        reply_parent_message_id: Optional[str] = None,
    ) -> bool:
        """POST /helix/chat/messages. Retry once on 401 after bot token refresh.

        Retourne True si le message a bien été publié. La fonction avalait
        toutes ses erreurs en rendant `None` : l'appelant posait alors un
        cooldown, enrichissait le prélude et la mémoire d'une réplique qui
        n'était JAMAIS partie. Un échec doit se voir.

        broadcaster_id: chaîne cible. Si None, utilise self._broadcaster_id (chaîne home).
        reply_parent_message_id: ID du message parent pour créer un thread de réponse.
        """
        target = broadcaster_id or self._broadcaster_id
        # Dernier filet avant publication : un mot en jeu (pendu) ne sort pas,
        # même si le modèle l'a écrit malgré la consigne.
        text = redact(text)
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.post(
                        self.MESSAGES_URL,
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        json={k: v for k, v in {
                            "broadcaster_id": target,
                            "sender_id": self._bot_id,
                            "message": text,
                            "reply_parent_message_id": reply_parent_message_id,
                        }.items() if v is not None},
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            logger.warning(
                                "Twitch chat API 401 — refreshing bot token and retrying"
                            )
                            refreshed = await self._tm.refresh("bot")
                            if not refreshed:
                                logger.error(
                                    "Bot token refresh failed, cannot send message"
                                )
                                return False
                            continue
                        logger.error("Twitch chat API 401 after refresh, giving up")
                        return False
                    if resp.status_code == 429 and attempt == 0:
                        # Franchi pendant un raid : sans attente, le message
                        # était simplement perdu. Twitch donne l'instant de
                        # recharge, on le respecte plutôt que de deviner.
                        wait = _ratelimit_wait(resp)
                        logger.warning("Twitch chat API 429 — nouvel essai dans {w}s", w=wait)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    refus = _refus_helix(resp)
                    if refus is not None:
                        # Pas de nouvel essai : un refus d'AutoMod ou de réglage
                        # de chaîne ne se répare pas en réémettant le même texte.
                        logger.warning(
                            "Twitch a refusé de publier sur {t} : {code} — {msg}",
                            t=target,
                            code=refus.get("code") or "sans code",
                            msg=refus.get("message") or "sans détail",
                        )
                        return False
                    return True
        except httpx.HTTPStatusError as exc:
            logger.error("Twitch send_message HTTP error: {e!r}", e=exc)
        except Exception as exc:
            logger.error("Twitch send_message error: {e!r}", e=exc)
        return False

    async def get_broadcaster_id(self, login: str) -> Optional[str]:
        """GET /helix/users?login={login}. Retourne l'ID ou None si introuvable.

        Retry une fois sur 401. Retourne None si la chaîne n'existe pas ou si
        l'API est indisponible.
        """
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.get(
                        self.USERS_URL,
                        params={"login": login.lower()},
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            logger.warning(
                                "Twitch users API 401 — refreshing bot token and retrying"
                            )
                            refreshed = await self._tm.refresh("bot")
                            if not refreshed:
                                return None
                            continue
                        return None
                    resp.raise_for_status()
                    data = resp.json().get("data", [])
                    return data[0]["id"] if data else None
        except Exception as exc:
            logger.warning("get_broadcaster_id failed for {login}: {e!r}", login=login, e=exc)
            return None

    async def get_streams_status(self, broadcaster_ids: list[str]) -> dict[str, bool]:
        """GET /helix/streams?user_id=id1&user_id=id2...

        Retourne {broadcaster_id: is_live}. Retourne {} si la liste est vide ou en cas
        d'erreur (pas de faux positif de suppression).
        """
        if not broadcaster_ids:
            return {}
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.get(
                        self.STREAMS_URL,
                        params=[("user_id", bid) for bid in broadcaster_ids],
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            refreshed = await self._tm.refresh("bot")
                            if not refreshed:
                                return {}
                            continue
                        return {}
                    resp.raise_for_status()
                    live_ids = {s["user_id"] for s in resp.json().get("data", [])}
                    return {bid: (bid in live_ids) for bid in broadcaster_ids}
        except Exception as exc:
            logger.warning("get_streams_status failed: {e!r}", e=exc)
            return {}

    async def get_users_by_ids(self, ids: list[str]) -> dict[str, str]:
        """GET /helix/users?id=... Returns {numeric_id: login_name}.

        Processes up to 100 IDs per request (Helix API limit).
        Returns empty dict on error.
        """
        if not ids:
            return {}
        result: dict[str, str] = {}
        try:
            async with httpx.AsyncClient() as client:
                # Helix allows max 100 ids per request
                for chunk_start in range(0, len(ids), 100):
                    chunk = ids[chunk_start:chunk_start + 100]
                    for attempt in range(2):
                        resp = await client.get(
                            self.USERS_URL,
                            params=[("id", uid) for uid in chunk],
                            headers={
                                "Authorization": f"Bearer {self._tm.bot_token}",
                                "Client-Id": self._client_id,
                            },
                            timeout=10,
                        )
                        if resp.status_code == 401:
                            if attempt == 0:
                                refreshed = await self._tm.refresh("bot")
                                if not refreshed:
                                    return result
                                continue
                            return result
                        resp.raise_for_status()
                        for user in resp.json().get("data", []):
                            result[user["id"]] = user["login"]
                        break
        except Exception as exc:
            logger.warning("get_users_by_ids failed: {e!r}", e=exc)
        return result

    # ------------------------------------------------------------------
    # Emotes
    # ------------------------------------------------------------------

    FOLLOWERS_URL = "https://api.twitch.tv/helix/channels/followers"
    EMOTES_GLOBAL_URL = "https://api.twitch.tv/helix/chat/emotes/global"
    EMOTES_USER_URL = "https://api.twitch.tv/helix/chat/emotes/user"

    async def _get_json(self, url: str, params: dict) -> Optional[dict]:
        """GET Helix avec le token du bot, retry une fois sur 401. None si échec.

        Les six méthodes ci-dessus recopient chacune ce squelette ; les deux
        appels d'emotes ne le recopient pas une septième fois. Rendre `None`
        plutôt que `{}` distingue « l'API n'a pas répondu » de « elle a répondu
        une liste vide » — un registre d'emotes ne doit surtout pas confondre
        les deux, sinon une panne réseau efface les emotes connues.
        """
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.get(
                        url, params=params,
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401 and attempt == 0:
                        # Un scope manquant rend AUSSI 401, et aucun
                        # renouvellement ne le réparera : ne pas boucler dessus,
                        # et le dire en INFO — c'est une décision d'autorisation,
                        # pas une panne. Sans ce tri, un scope absent se lisait
                        # « token expiré » et déclenchait un renouvellement
                        # inutile toutes les six heures.
                        if "scope" in (resp.text or "").lower():
                            logger.info("Twitch {u} refusé : {m}", u=url,
                                        m=(resp.text or "")[:200])
                            return None
                        if not await self._tm.refresh("bot"):
                            return None
                        continue
                    if resp.status_code != 200:
                        logger.warning("Twitch {u} → HTTP {c}", u=url, c=resp.status_code)
                        return None
                    return resp.json()
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("Twitch {u} a échoué : {e!r}", u=url, e=exc)
        return None

    async def get_follow_date(self, user_id: str) -> Optional[dict]:
        """GET /helix/channels/followers — depuis quand `user_id` suit la maison.

        Trois retours DISTINCTS, parce que les trois se disent différemment :

          `None` → l'API n'a pas répondu   ................ « j'arrive pas à vérifier »
          `{}`   → la personne ne suit pas ................ « tu me suis même pas »
          `{"followed_at": "<ISO 8601 UTC>"}` ............. « depuis mars »

        Les confondre donnerait le pire des cas : annoncer à quelqu'un qui suit
        depuis deux ans qu'il ne suit pas, parce que Helix a eu un 500.

        Le scope `moderator:read:followers` est sur le token du BOT et exige
        qu'il soit modérateur de la chaîne. Ce n'est pas une hypothèse :
        l'EventSub `channel.follow v2` a la même exigence et tourne déjà.
        """
        data = await self._get_json(
            self.FOLLOWERS_URL,
            {"broadcaster_id": self._broadcaster_id, "user_id": str(user_id)},
        )
        if data is None:
            return None
        entrees = data.get("data") or []
        if not entrees:
            return {}
        quand = str(entrees[0].get("followed_at") or "")
        # Un `followed_at` vide serait un « il suit » sans date : indéfendable à
        # l'oral. On retombe sur « ne suit pas », le seul repli honnête.
        return {"followed_at": quand} if quand else {}

    async def get_global_emotes(self) -> Optional[list[str]]:
        """Les emotes globales Twitch, utilisables par TOUT LE MONDE. None si échec.

        Aucun scope : c'est le catalogue public. Ce sont les seules qu'un compte
        sans abonnement puisse écrire sans risque — une emote de chaîne à
        laquelle on n'a pas droit s'affiche en toutes lettres dans le chat.
        """
        data = await self._get_json(self.EMOTES_GLOBAL_URL, {})
        if data is None:
            return None
        return [str(e.get("name") or "") for e in data.get("data", []) if e.get("name")]

    async def get_entitled_channel_emotes(self) -> Optional[list[str]]:
        """Les emotes DE LA CHAÎNE que le compte du bot a le droit d'écrire.

        `/helix/chat/emotes?broadcaster_id=` liste les 27 emotes de la chaîne
        mais ne dit pas lesquelles sont ouvertes à CE compte : 26 sont réservées
        aux abonnés, une aux followers. C'est `/helix/chat/emotes/user` qui
        répond à la question — d'où le filtre sur `owner_id`, l'endpoint rendant
        aussi les globales et celles des autres chaînes.

        Demande le scope `user:read:emotes`, que le token du bot n'a pas encore
        (il l'obtiendra à la prochaine autorisation, cf. `_BOT_SCOPES`). Sans
        lui : liste vide, donc aucune emote de chaîne proposée — jamais une
        emote inventée. Le jour où le bot est abonné ET le scope accordé, les
        `azrael74*` entrent d'elles-mêmes.
        """
        data = await self._get_json(
            self.EMOTES_USER_URL,
            {"user_id": self._bot_id, "broadcaster_id": self._broadcaster_id},
        )
        if data is None:
            return None
        return [
            str(e.get("name") or "")
            for e in data.get("data", [])
            if e.get("name") and str(e.get("owner_id") or "") == str(self._broadcaster_id)
        ]

    # Qualité visée pour l'overlay : la vidéo y fait 540 px de large, le 1080p
    # ne serait que du poids en plus (17 Mo pour 25 s) et un démarrage plus lent.
    _CLIP_QUALITY = "720"

    async def get_clip_video_url(self, slug: str) -> Optional[dict]:
        """URL du FICHIER vidéo d'un clip, et sa durée. None si indisponible.

        ⚠️ Passe par l'API GraphQL **non officielle** de Twitch (celle qu'emploient
        yt-dlp et streamlink). L'API Helix publique n'expose aucune URL de
        lecture, et le player officiel en iframe REFUSE de démarrer tout seul
        dans un overlay — « Autoplay disabled … style visibility », faux positif
        connu et non corrigé (twitchdev/issues#1127). Une balise `<video muted>`
        alimentée par cette URL, elle, démarre toujours.

        Twitch peut changer cette API sans préavis : l'appelant DOIT savoir
        retomber sur l'iframe puis sur la carte.
        """
        slug = str(slug or "").strip()
        if not slug:
            return None
        query = (
            "query($slug: ID!){clip(slug:$slug){durationSeconds "
            "playbackAccessToken(params:{platform:\"web\",playerBackend:\"mediaplayer\","
            "playerType:\"site\"}){signature value} videoQualities{quality sourceURL}}}"
        )
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://gql.twitch.tv/gql",
                    headers={"Client-ID": _GQL_CLIENT_ID,
                             "Content-Type": "application/json"},
                    json={"query": query, "variables": {"slug": slug}},
                    timeout=10,
                )
            if resp.status_code != 200:
                logger.warning("Twitch GQL clip {c}", c=resp.status_code)
                return None
            clip = ((resp.json().get("data") or {}).get("clip")) or {}
            qualities = clip.get("videoQualities") or []
            token = clip.get("playbackAccessToken") or {}
            if not qualities or not token.get("signature"):
                return None
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("Twitch GQL clip a échoué : {e!r}", e=exc)
            return None

        # La qualité voulue si elle existe, sinon la plus haute en dessous —
        # les qualités arrivent triées du plus grand au plus petit.
        chosen = next(
            (q for q in qualities if str(q.get("quality")) == self._CLIP_QUALITY),
            None,
        ) or next(
            (q for q in qualities
             if str(q.get("quality")).isdigit()
             and int(q["quality"]) <= int(self._CLIP_QUALITY)),
            qualities[-1],
        )
        source = str(chosen.get("sourceURL") or "")
        if not source.startswith("https://"):
            return None
        sig = quote(str(token["signature"]))
        val = quote(str(token.get("value") or ""))
        return {"url": f"{source}?sig={sig}&token={val}",
                "duration": clip.get("durationSeconds") or 0}

    async def get_last_clip(self, days: int = 30,
                            creator: str | None = None) -> dict | None:
        """Le clip le plus RÉCENT de la chaîne, ou None.

        La fenêtre était de 24 h : un clip vieux de trois jours restait donc
        « le dernier clip de la chaîne » pour tout le monde sauf pour Wally, qui
        répondait « aucun clip récent, même pas de Lolofun » — deux clips de
        Lolofun dataient de quatre jours. Trente jours : « le dernier » n'a pas
        de raison d'expirer, et à ce rythme (16 clips en 90 jours) on reste très
        loin des 100 que renvoie Helix.

        ⚠️ Helix trie les clips par nombre de vues, pas par date : sur une
        fenêtre longue, le dernier créé peut tomber hors du lot renvoyé. D'où
        `first=100` — au-delà, il faudrait paginer pour un gain nul.

        `creator` restreint au clippeur demandé — un surnom suffit (« azra »
        pour « Azrael »). Helix ne sait pas filtrer là-dessus : le tri se fait
        ici, sur le `creator_name` que renvoie l'API. À noter que la fenêtre
        reste celle de CETTE chaîne : « le dernier clip d'Azra » veut dire ce
        qu'Azra a clippé ici, pas ce qui a été clippé sur sa chaîne à lui.
        """
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        clips = await self.get_recent_clips(
            since.strftime("%Y-%m-%dT%H:%M:%SZ"), first=100
        )
        if creator:
            clips = [c for c in clips
                     if matches_name(str(c.get("creator_name") or ""), creator)]
        if not clips:
            return None
        return max(clips, key=lambda c: str(c.get("created_at") or ""))

    async def get_top_clips(self, days: int = 7, first: int = 5) -> list[dict]:
        """Les clips les plus VUS de la chaîne sur les `days` derniers jours.

        Helix trie déjà par nombre de vues, mais ce n'est écrit nulle part dans
        son contrat : on retrie ici. Un jour où l'ordre changerait, le podium
        resterait juste.
        """
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        clips = await self.get_recent_clips(
            since.strftime("%Y-%m-%dT%H:%M:%SZ"), first=100
        )
        clips.sort(key=lambda c: int(c.get("view_count") or 0), reverse=True)
        return clips[:max(1, first)]

    async def find_clip(self, query: str, days: int = 30) -> dict | None:
        """Le clip dont le TITRE colle le mieux à `query`, ou None.

        Helix ne sait pas chercher dans les titres : le tri se fait ici, sur les
        mots du titre. À pertinence égale on prend le plus vu — c'est celui que
        les gens ont en tête. Rien de convaincant : None plutôt qu'un clip au
        hasard, qu'il faudrait ensuite justifier à l'écran.
        """
        query = (query or "").strip()
        if not query:
            return None
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        clips = await self.get_recent_clips(
            since.strftime("%Y-%m-%dT%H:%M:%SZ"), first=100
        )
        mots = [m for m in _fold(query).split() if len(m) > 2]
        if not mots:
            mots = [_fold(query)]
        meilleurs: list[tuple[int, int, dict]] = []
        for clip in clips:
            titre = _fold(str(clip.get("title") or ""))
            score = sum(1 for m in mots if m in titre)
            if score:
                meilleurs.append((score, int(clip.get("view_count") or 0), clip))
        if not meilleurs:
            return None
        meilleurs.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return meilleurs[0][2]

    async def get_recent_clips(self, since_iso: str, first: int = 20) -> list[dict]:
        """GET /helix/clips — clips créés depuis `since_iso` sur la chaîne.

        Twitch n'émet AUCUN événement EventSub à la création d'un clip : la
        seule façon de les voir est d'interroger l'API. Retourne une liste vide
        en cas d'erreur — un clip manqué ne vaut pas un plantage.
        """
        try:
            async with httpx.AsyncClient() as client:
                # Retry sur 401 comme les cinq autres méthodes Helix : sans lui,
                # un token expiré condamnait la veille des clips pour tout le
                # reste du live, et le seul indice était un `logger.debug`
                # invisible en production.
                for attempt in range(2):
                    resp = await client.get(
                        "https://api.twitch.tv/helix/clips",
                        params={
                            "broadcaster_id": self._broadcaster_id,
                            "started_at": since_iso,
                            # OBLIGATOIRE, malgré les apparences : sans borne de
                            # fin, Helix en pose une à `started_at + 1 semaine`.
                            # « Les clips des 30 derniers jours » ne regardait
                            # donc que la semaine du 30e au 23e jour, et rien du
                            # présent. Constaté le 2026-08-11 : 3 clips (tous de
                            # mai) sur 90 jours, contre 16 avec cette ligne.
                            "ended_at": datetime.now(timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                            "first": max(1, min(100, int(first))),
                        },
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401 and attempt == 0:
                        logger.warning("Twitch clips API 401 — renouvellement du token")
                        if not await self._tm.refresh("bot"):
                            return []
                        continue
                    if resp.status_code != 200:
                        logger.warning("Twitch clips API {c}", c=resp.status_code)
                        return []
                    return resp.json().get("data") or []
                return []
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("Twitch clips API a échoué : {e!r}", e=exc)
            return []

    async def refund_redemption(self, reward_id: str, redemption_id: str) -> bool:
        """Annule une redemption — les points sont RENDUS au viewer.

        Utilise le token STREAMER : `channel:manage:redemptions` est un scope de
        la chaîne, le token du bot ne l'a pas. Retry une fois sur 401 après
        renouvellement du token streamer, comme `get_stream()`/`send_message()` —
        c'est le filet de sécurité de toute la feature : si le token expire pile
        pendant un remboursement, rien d'autre ne rattrape les points perdus.

        Comme partout sur Helix, un 200 ne prouve pas que l'ordre est passé : on
        vérifie que le corps renvoie bien `status: CANCELED`. Ce projet a déjà
        payé la leçon avec `is_sent` sur l'envoi de messages.
        """
        return await self._trancher_redemption(reward_id, redemption_id, "CANCELED")

    async def honorer_redemption(self, reward_id: str, redemption_id: str) -> bool:
        """Marque une redemption comme honorée — les points sont CONSOMMÉS.

        Le pendant du remboursement, et il n'est pas décoratif : une redemption
        laissée `UNFULFILLED` reste dans la file de validation du streamer et
        s'y accumule duel après duel. Chaque duel se solde donc par l'un ou par
        l'autre, jamais par rien.

        Même patron que `refund_redemption` — token streamer, retry sur 401,
        vérification du CORPS (`status: FULFILLED`) et non du seul statut HTTP.
        """
        return await self._trancher_redemption(reward_id, redemption_id, "FULFILLED")

    async def _trancher_redemption(self, reward_id: str, redemption_id: str,
                                   statut: str) -> bool:
        """Le PATCH commun aux deux issues d'une redemption.

        Un seul corps de méthode pour `CANCELED` et `FULFILLED` : les deux
        portent le même filet (token streamer, retry sur 401, lecture du corps),
        et le dédoubler garantissait qu'une correction future ne s'applique qu'à
        moitié.
        """
        rendu = ("points rendus au viewer" if statut == "CANCELED"
                 else "points consommés")
        if not (reward_id and redemption_id):
            logger.warning("Redemption {s} impossible : reward_id ou redemption_id vide",
                           s=statut)
            return False
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.patch(
                        self.REDEMPTIONS_URL,
                        params={"broadcaster_id": self._broadcaster_id,
                                "reward_id": reward_id, "id": redemption_id},
                        json={"status": statut},
                        headers={"Authorization": f"Bearer {self._tm.streamer_token}",
                                 "Client-Id": self._client_id},
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            logger.warning(
                                "Redemption {s} 401 — renouvellement du token streamer",
                                s=statut,
                            )
                            refreshed = await self._tm.refresh("streamer")
                            if not refreshed:
                                logger.error(
                                    "Renouvellement du token streamer échoué — "
                                    "redemption {s} abandonnée", s=statut,
                                )
                                return False
                            continue
                        logger.error("Redemption {s} 401 après renouvellement — abandon",
                                     s=statut)
                        return False
                    if resp.status_code != 200:
                        logger.error("Redemption {s} refusée HTTP {c} : {t}",
                                     s=statut, c=resp.status_code, t=resp.text[:200])
                        return False
                    data = (resp.json() or {}).get("data") or []
                    rendu_api = (data[0] or {}).get("status") if data else None
                    if rendu_api != statut:
                        logger.error("Redemption non appliquée — statut rendu : {s}",
                                     s=rendu_api)
                        return False
                    logger.info("Duel : {r} (redemption {i})", r=rendu, i=redemption_id)
                    return True
                return False
        except Exception as exc:  # noqa: BLE001 — un arbitrage raté ne tue pas le duel
            logger.error("Redemption {s} en erreur : {e!r}", s=statut, e=exc)
            return False

    async def redemptions_en_attente(self, reward_id: str) -> list[dict] | None:
        """Les achats de NOTRE récompense encore en attente. `None` sur erreur.

        EventSub ne rejoue pas les événements manqués : un viewer qui achète
        pendant un rebuild — fréquents ici — voit sa mise disparaître sans
        duel, sans remboursement et sans un mot, et sa redemption reste coincée
        dans la file de validation du streamer. Cette liste est le seul moyen
        de les retrouver au démarrage.

        `reward_id` est passé à Twitch en paramètre (il est d'ailleurs
        OBLIGATOIRE sur cet endpoint) : on ne voit jamais les redemptions des
        autres récompenses de la chaîne, qui ne nous regardent pas.

        `status=UNFULFILLED` : seules celles-là sont encore modifiables, donc
        remboursables. Pagination suivie jusqu'au bout — un stream chargé peut
        en accumuler plus d'une page — avec un plafond de tours, faute de quoi
        un curseur qui ne bouge pas ferait tourner le démarrage en rond.

        `None` et non `[]` sur erreur, comme `recompenses_gerables()` : les
        confondre ferait conclure « aucun achat manqué » sur une simple panne.
        """
        if not reward_id:
            logger.warning("Redemptions en attente : reward_id vide")
            return None
        tout: list[dict] = []
        curseur = ""
        renouvele = False
        try:
            async with httpx.AsyncClient() as client:
                for _page in range(20):
                    params = {"broadcaster_id": self._broadcaster_id,
                              "reward_id": reward_id, "status": "UNFULFILLED",
                              "first": "50"}
                    if curseur:
                        params["after"] = curseur
                    resp = await client.get(
                        self.REDEMPTIONS_URL, params=params,
                        headers={"Authorization": f"Bearer {self._tm.streamer_token}",
                                 "Client-Id": self._client_id},
                        timeout=10,
                    )
                    if resp.status_code == 401 and not renouvele:
                        # Une seule fois, comme partout ailleurs ici : un token
                        # qui reste refusé après renouvellement ne le sera pas
                        # davantage au vingtième tour.
                        renouvele = True
                        logger.warning(
                            "Redemptions en attente 401 — renouvellement du token streamer")
                        if not await self._tm.refresh("streamer"):
                            logger.error("Renouvellement du token streamer échoué — "
                                         "redemptions en attente abandonnées")
                            return None
                        continue
                    if resp.status_code != 200:
                        logger.error("Redemptions en attente refusées HTTP {c} : {t}",
                                     c=resp.status_code, t=resp.text[:200])
                        return tout or None
                    corps = resp.json() or {}
                    tout.extend(corps.get("data") or [])
                    curseur = str((corps.get("pagination") or {}).get("cursor") or "")
                    if not curseur:
                        return tout
                logger.warning(
                    "Redemptions en attente : pagination interrompue au plafond "
                    "({n} déjà lues)", n=len(tout))
                return tout
        except Exception as exc:  # noqa: BLE001
            logger.error("Redemptions en attente en erreur : {e!r}", e=exc)
            return None

    async def recompenses_gerables(self) -> list[dict] | None:
        """Les récompenses que NOTRE application peut piloter. `None` sur erreur.

        `only_manageable_rewards=true` ne rend que celles créées par ce
        `client_id`. Les autres — créées depuis le site Twitch — sont
        inaccessibles à l'API : les rembourser renvoie 403.

        Retry une fois sur 401 après renouvellement du token streamer, comme
        `refund_redemption` : un token expiré ne doit pas faire disparaître la
        liste des récompenses pilotables.

        `None` et non `[]` sur une erreur : les deux étaient indiscernables, et
        `DuelRunner.assurer_recompense()` lisait un `[]` d'erreur comme « ma
        récompense a disparu » — un simple hoquet Twitch au boot suffisait à en
        recréer une seconde, écrasant l'ID persisté et rendant l'ancienne
        irremboursable (403). `[]` reste réservé à une vraie liste vide.
        """
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.get(
                        self.REWARDS_URL,
                        params={"broadcaster_id": self._broadcaster_id,
                                "only_manageable_rewards": "true"},
                        headers={"Authorization": f"Bearer {self._tm.streamer_token}",
                                 "Client-Id": self._client_id},
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            logger.warning(
                                "Liste des récompenses 401 — renouvellement du token streamer"
                            )
                            refreshed = await self._tm.refresh("streamer")
                            if not refreshed:
                                logger.error(
                                    "Renouvellement du token streamer échoué — "
                                    "liste des récompenses abandonnée"
                                )
                                return None
                            continue
                        logger.error("Liste des récompenses 401 après renouvellement — abandon")
                        return None
                    if resp.status_code != 200:
                        logger.error("Liste des récompenses refusée HTTP {c} : {t}",
                                     c=resp.status_code, t=resp.text[:200])
                        return None
                    return (resp.json() or {}).get("data") or []
                return None
        except Exception as exc:  # noqa: BLE001
            logger.error("Liste des récompenses en erreur : {e!r}", e=exc)
            return None

    async def inventaire_recompenses(self) -> tuple[int, int] | None:
        """`(total, désactivées)` sur TOUTE la chaîne. `None` si illisible.

        Sans `only_manageable_rewards`, donc les récompenses posées à la main ou
        par un autre outil comptent aussi — c'est ce périmètre-là, et pas le
        nôtre, que Twitch plafonne à 50.
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.REWARDS_URL,
                    params={"broadcaster_id": self._broadcaster_id},
                    headers={"Authorization": f"Bearer {self._tm.streamer_token}",
                             "Client-Id": self._client_id},
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.warning("Inventaire des récompenses refusé HTTP {c}",
                                   c=resp.status_code)
                    return None
                data = (resp.json() or {}).get("data") or []
                return len(data), sum(1 for r in data if not r.get("is_enabled"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Inventaire des récompenses en erreur : {e!r}", e=exc)
            return None

    async def _diagnostic_plafond(self, titre: str) -> str:
        """Pourquoi la chaîne est pleine, avec son décompte mesuré.

        Le premier message se contentait d'annoncer « PLAFOND de 50 » : l'owner
        en comptait 33 dans son tableau de bord et en a conclu à une panne du
        bot. Les deux chiffres étaient justes — Twitch compte les récompenses
        **désactivées** dans les 50, et le tableau de bord ne les montre pas.
        Un chiffre asséné sans sa mesure se fait contredire par un autre chiffre.
        """
        geste = ("Il faut en SUPPRIMER une dans le tableau de bord Twitch "
                 "(la désactiver ne libère aucune place), puis redémarrer — "
                 "rien à corriger côté bot.")
        inventaire = await self.inventaire_recompenses()
        if inventaire is None:
            return (f"Récompense « {titre} » impossible : la chaîne est à son PLAFOND "
                    f"de 50 récompenses de points de chaîne. {geste}")
        total, eteintes = inventaire
        return (f"Récompense « {titre} » impossible : la chaîne est à son PLAFOND "
                f"de 50 récompenses de points de chaîne ({total} en tout, dont "
                f"{eteintes} DÉSACTIVÉES — elles comptent, et le tableau de bord "
                f"ne les affiche pas par défaut). {geste}")

    async def creer_recompense(self, titre: str, cout: int, prompt: str, *,
                               saisie_requise: bool = True,
                               cooldown_s: int = 0) -> str | None:
        """Crée la récompense de points de chaîne, et rend son ID.

        C'est Wally qui doit la créer : Twitch réserve la mise à jour d'une
        redemption à l'application qui a créé la récompense. Une récompense
        posée à la main dans la console renverrait 403 à chaque remboursement —
        et chaque refus de duel rembourse.

        Retry une fois sur 401 après renouvellement du token streamer, comme
        `refund_redemption` — sans lui, un token expiré pile à la création
        rendrait le duel indisponible sans rattrapage.
        """
        corps = {
            **_corps_recompense(titre, cout, prompt, cooldown_s),
            # `is_user_input_required` est OPTIONNEL côté Twitch (défaut
            # `false`) : il était posé à `True` en dur ici, hérité du duel qui
            # attend un uid. Toute récompense héritait donc d'un champ de saisie
            # inutile, et devait s'en excuser dans son invite.
            #
            # Le défaut reste `True` : les deux appelants historiques (duel,
            # humeur) en dépendent, et un défaut à `False` les aurait cassés en
            # silence.
            "is_user_input_required": bool(saisie_requise),
            "is_enabled": True,
            # JAMAIS True : une redemption qui saute la file est aussitôt
            # FULFILLED, et seul un statut UNFULFILLED peut être mis à jour.
            # On perdrait tout moyen de rendre les points.
            "should_redemptions_skip_request_queue": False,
        }
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.post(
                        self.REWARDS_URL,
                        params={"broadcaster_id": self._broadcaster_id},
                        json=corps,
                        headers={"Authorization": f"Bearer {self._tm.streamer_token}",
                                 "Client-Id": self._client_id},
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            logger.warning(
                                "Création de récompense 401 — renouvellement du token streamer"
                            )
                            refreshed = await self._tm.refresh("streamer")
                            if not refreshed:
                                logger.error(
                                    "Renouvellement du token streamer échoué — "
                                    "création de récompense abandonnée"
                                )
                                return None
                            continue
                        logger.error(
                            "Création de récompense 401 après renouvellement — abandon"
                        )
                        return None
                    if resp.status_code not in (200, 201):
                        # Le plafond de Twitch est de 50 récompenses PAR CHAÎNE,
                        # toutes applications confondues. Le code brut
                        # (`CREATE_CUSTOM_REWARD_TOO_MANY_REWARDS`) ne dit ni le
                        # chiffre ni le geste : sans cette traduction, on relit
                        # le code du bot en cherchant une panne qui n'existe pas.
                        if "TOO_MANY_REWARDS" in resp.text:
                            logger.error(await self._diagnostic_plafond(titre))
                            return None
                        logger.error("Création de récompense refusée HTTP {c} : {t}",
                                     c=resp.status_code, t=resp.text[:200])
                        return None
                    data = (resp.json() or {}).get("data") or []
                    rid = (data[0] or {}).get("id") if data else None
                    if rid:
                        logger.info("Récompense créée : {t} ({i})",
                                    t=corps["title"], i=rid)
                    return rid
                return None
        except Exception as exc:  # noqa: BLE001
            logger.error("Création de récompense en erreur : {e!r}", e=exc)
            return None

    # ── Prédictions (§13) ───────────────────────────────────────────────────

    async def creer_prediction(self, titre: str, choix: list[str],
                               fenetre_s: int) -> dict | None:
        """Ouvre une prédiction. Rend son id ET l'id de chaque choix.

        Les identifiants des choix DOIVENT remonter : c'est avec eux qu'on
        résout, et les libellés ne suffisent pas — deux choix peuvent se
        ressembler, et Twitch n'accepte que l'id.
        """
        propres = [str(c).strip()[:_PRED_CHOIX_MAX]
                   for c in (choix or []) if str(c).strip()][:_PRED_CHOIX_MAX_N]
        if len(propres) < _PRED_CHOIX_MIN_N:
            logger.error("Prédiction refusée : il faut au moins {n} choix, reçu {r}",
                         n=_PRED_CHOIX_MIN_N, r=len(propres))
            return None
        corps = {
            "broadcaster_id": self._broadcaster_id,
            "title": str(titre or "").strip()[:_PRED_TITRE_MAX],
            "outcomes": [{"title": c} for c in propres],
            "prediction_window": max(_PRED_FENETRE_MIN,
                                     min(_PRED_FENETRE_MAX, int(fenetre_s or 0))),
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.PREDICTIONS_URL, json=corps,
                    headers={"Authorization": f"Bearer {self._tm.streamer_token}",
                             "Client-Id": self._client_id},
                    timeout=10,
                )
                if resp.status_code not in (200, 201):
                    _prediction_sans_scope("création", resp)
                    return None
                data = (resp.json() or {}).get("data") or []
                if not data:
                    logger.error("Prédiction créée mais réponse vide")
                    return None
                pred = data[0]
                logger.info("Prédiction ouverte : « {t} » ({n} choix, {f} s)",
                            t=corps["title"], n=len(propres), f=corps["prediction_window"])
                return {"id": str(pred.get("id") or ""),
                        "title": str(pred.get("title") or ""),
                        "outcomes": [{"id": str(o.get("id") or ""),
                                      "title": str(o.get("title") or "")}
                                     for o in (pred.get("outcomes") or [])]}
        except Exception as exc:  # noqa: BLE001 — une panne d'API ne casse pas le chat
            logger.error("Prédiction en erreur : {e!r}", e=exc)
            return None

    async def resoudre_prediction(self, prediction_id: str,
                                  choix_gagnant_id: str) -> bool:
        """Désigne le gagnant. Faux si Twitch a refusé.

        Faux et non « None optimiste » : l'appelant annoncerait un verdict qui
        n'a pas eu lieu, alors que les points des viewers sont toujours en jeu.
        """
        return await self._patch_prediction(
            prediction_id, {"status": "RESOLVED",
                            "winning_outcome_id": str(choix_gagnant_id or "")},
            "résolution")

    async def annuler_prediction(self, prediction_id: str) -> bool:
        """Annule et REMBOURSE tout le monde.

        La seule issue honnête quand le résultat n'est pas mesurable : résoudre
        au hasard punirait des gens qui avaient raison.
        """
        return await self._patch_prediction(prediction_id, {"status": "CANCELED"},
                                            "annulation")

    async def _patch_prediction(self, prediction_id: str, champs: dict,
                                action: str) -> bool:
        corps = {"broadcaster_id": self._broadcaster_id,
                 "id": str(prediction_id or ""), **champs}
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.patch(
                    self.PREDICTIONS_URL, json=corps,
                    headers={"Authorization": f"Bearer {self._tm.streamer_token}",
                             "Client-Id": self._client_id},
                    timeout=10,
                )
                if resp.status_code != 200:
                    _prediction_sans_scope(action, resp)
                    return False
                logger.info("Prédiction {a} : {i}", a=action, i=prediction_id)
                return True
        except Exception as exc:  # noqa: BLE001 — une panne d'API ne casse pas le chat
            logger.error("Prédiction ({a}) en erreur : {e!r}", a=action, e=exc)
            return False

    async def maj_recompense(self, reward_id: str, titre: str, cout: int,
                             prompt: str, *, actuelle: dict | None = None,
                             saisie_requise: bool = True,
                             cooldown_s: int = 0) -> bool:
        """Aligne une récompense EXISTANTE sur le libellé voulu (PATCH).

        Sans elle, éditer `apex.duel` dans `config.yaml` ne changeait rien :
        la récompense n'était écrite qu'à sa création, et la seule façon de la
        corriger aurait été de la recréer — or une récompense recréée perd son
        historique, et une récompense créée hors de notre application est
        irremboursable (403). On modifie donc, jamais on ne remplace.

        `actuelle` est la récompense telle que Twitch la rend. Les champs qu'on
        y lit déjà à la bonne valeur ne déclenchent rien, et si RIEN ne diffère
        aucun appel ne part — un boot ne doit pas écrire pour écrire. Un champ
        ABSENT de `actuelle` n'est pas un champ vide : on n'en conclut pas
        qu'il diffère, sinon une réponse partielle de Twitch ferait patcher à
        chaque démarrage.

        Même patron que ses voisines : token streamer, retry une fois sur 401,
        lecture du CORPS (le champ doit être revenu à la valeur demandée) et
        non du seul statut HTTP, et aucune exception qui remonte.
        """
        if not reward_id:
            logger.warning("Mise à jour de récompense impossible : reward_id vide")
            return False
        try:
            # DANS le `try` : un coût illisible en configuration ne doit pas
            # remonter jusqu'au démarrage du bot pour un simple libellé.
            # Le champ de saisie voyage AVEC le reste : sans lui, changer
            # `saisie_requise` sur une récompense déjà créée ne ferait rien, et
            # silencieusement — elle continuerait de marcher avec son champ de
            # trop. Hors de `_corps_recompense`, que la création remplit déjà de
            # son côté.
            corps = {**_corps_recompense(titre, cout, prompt, cooldown_s),
                     "is_user_input_required": bool(saisie_requise)}
            if actuelle is not None:
                # Aplatie AVANT la comparaison : le temps de recharge est le
                # seul champ que Twitch rend sous une autre forme qu'il ne le
                # lit, et une clé jamais trouvée n'est jamais un écart.
                actuelle = _aplatir_cooldown(actuelle)
                ecarts = {c: v for c, v in corps.items()
                          if c in actuelle and actuelle[c] != v}
                if not ecarts:
                    return True
                logger.info("Récompense {i} à réaligner : {e}",
                            i=reward_id, e=", ".join(sorted(ecarts)))
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.patch(
                        self.REWARDS_URL,
                        params={"broadcaster_id": self._broadcaster_id,
                                "id": reward_id},
                        json=corps,
                        headers={"Authorization": f"Bearer {self._tm.streamer_token}",
                                 "Client-Id": self._client_id},
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            logger.warning(
                                "Mise à jour de récompense 401 — renouvellement du "
                                "token streamer"
                            )
                            refreshed = await self._tm.refresh("streamer")
                            if not refreshed:
                                logger.error(
                                    "Renouvellement du token streamer échoué — "
                                    "mise à jour de récompense abandonnée"
                                )
                                return False
                            continue
                        logger.error(
                            "Mise à jour de récompense 401 après renouvellement — abandon"
                        )
                        return False
                    if resp.status_code != 200:
                        logger.error("Mise à jour de récompense refusée HTTP {c} : {t}",
                                     c=resp.status_code, t=resp.text[:200])
                        return False
                    data = (resp.json() or {}).get("data") or []
                    # Même traduction qu'à l'aller : relue à plat, la recharge
                    # que Twitch vient d'appliquer passerait pour absente, et un
                    # PATCH réussi serait déclaré non appliqué.
                    rendue = _aplatir_cooldown(data[0] or {}) if data else {}
                    restants = [c for c, v in corps.items()
                                if c in rendue and rendue[c] != v]
                    if not rendue or restants:
                        logger.error(
                            "Mise à jour de récompense non appliquée — toujours "
                            "différent : {r}", r=", ".join(sorted(restants)) or "corps vide")
                        return False
                    logger.info("Récompense mise à jour : {t} ({i})",
                                t=corps["title"], i=reward_id)
                    return True
                return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Mise à jour de récompense en erreur : {e!r}", e=exc)
            return False

    async def get_stream(self) -> dict:
        """GET /helix/streams?user_id={self._broadcaster_id}.

        Retourne un dict normalisé :
          {live, title, category, viewers, started_at}
        En cas d'erreur ou de stream offline, live=False et les autres champs sont None/0.
        Utilise self._tm.bot_token (cohérent avec send_message).
        """
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.get(
                        self.STREAMS_URL,
                        params={"user_id": self._broadcaster_id},
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        # `break` sortait du `for`, du `async with`, PUIS de la
                        # fonction : retour implicite `None` là où tout le reste
                        # du code attend un dict. `StreamWatcher` mourait sur un
                        # AttributeError hors de son try, et `build_system_prompt`
                        # levait un TypeError — plus aucun prompt nulle part.
                        if attempt == 0:
                            logger.warning(
                                "Twitch streams API 401 — refreshing bot token and retrying"
                            )
                            refreshed = await self._tm.refresh("bot")
                            if not refreshed:
                                logger.error(
                                    "Bot token refresh failed, cannot fetch stream status"
                                )
                                return _UNKNOWN_STREAM.copy()
                            continue
                        logger.error("Twitch streams API 401 after refresh, giving up")
                        return _UNKNOWN_STREAM.copy()
                    resp.raise_for_status()
                    data = resp.json().get("data", [])
                    if not data:
                        return _OFFLINE_STREAM.copy()
                    s = data[0]
                    return {
                        "live": True,
                        "title": s.get("title"),
                        "category": s.get("game_name"),
                        "viewers": s.get("viewer_count", 0),
                        "started_at": s.get("started_at"),
                    }
        except Exception as exc:
            # `{e!r}` : sans lui, un timeout réseau (message vide) rendait
            # « Failed to fetch Twitch stream status: » suivi de rien —
            # 117 fois en août. Le type est la seule donnée qui distingue une
            # coupure réseau d'un refus d'API.
            logger.warning("Failed to fetch Twitch stream status: {e!r}", e=exc)
            return _UNKNOWN_STREAM.copy()


# ── Prédictions Twitch (§13) ────────────────────────────────────────────────
#
# Les bornes de l'API, qu'on ne devine pas : titre 45 caractères, 2 à 10 choix
# de 25 caractères, fenêtre de pari de 30 s à 30 min. Les dépasser rend un 400
# qui ne dit pas lequel des trois est en cause.
_PRED_TITRE_MAX = 45
_PRED_CHOIX_MAX = 25
_PRED_CHOIX_MIN_N, _PRED_CHOIX_MAX_N = 2, 10
_PRED_FENETRE_MIN, _PRED_FENETRE_MAX = 30, 1800

# Ce qu'il faut avoir autorisé pour piloter les prédictions. Le token en service
# ne le portait pas (vérifié le 2026-08-18 sur /oauth2/validate) : il faut
# refaire l'autorisation du compte STREAMER depuis le dashboard.
_SCOPE_PREDICTIONS = "channel:manage:predictions"


def _prediction_sans_scope(action: str, reponse) -> None:
    """Journalise un refus de prédiction en NOMMANT le geste à faire.

    Un « 401 » sec envoie chercher la panne dans le code du bot, où il n'y a
    rien à trouver. Même leçon que le plafond des récompenses de points de
    chaîne, dont le code brut ne disait ni le chiffre ni le geste.
    """
    texte = (getattr(reponse, "text", "") or "")[:200]
    if reponse.status_code in (401, 403):
        logger.error(
            "Prédiction ({a}) refusée : le compte streamer n'a pas autorisé "
            "« {s} ». Il faut REFAIRE l'autorisation Twitch du streamer depuis "
            "le dashboard — rien à corriger côté bot. Réponse : {t}",
            a=action, s=_SCOPE_PREDICTIONS, t=texte)
    else:
        logger.error("Prédiction ({a}) refusée HTTP {c} : {t}",
                     a=action, c=reponse.status_code, t=texte)
