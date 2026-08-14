# bot/twitch/events/__init__.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import httpx
from loguru import logger

from bot.twitch.events.models import ChatMessageData
from bot.twitch.events.social import (  # noqa: F401 — re-exports
    register_events,
    _bits_joy,
    _generate_and_send,
)

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


async def start_eventsub_client(bot: "WallyTwitch") -> None:
    """Create an EventSub WebSocket client and subscribe to channel events.

    Patches twitchio v2's SubscriptionTypes at runtime to add
    channel.chat.message support (absent from twitchio v2 natively).

    Token usage:
      Bot token  (BOT_ACCESS_TOKEN):
        channel.follow v2  — moderator:read:followers
        channel.raid       — (no scope)
        channel.chat.message — user:read:chat

      Streamer token (STREAMER_ACCESS_TOKEN):
        channel.subscribe, channel.subscription.message,
        channel.subscription.gift, channel.subscription.end — channel:read:subscriptions
        channel.cheer — bits:read
        channel.channel_points_custom_reward_redemption.add — channel:read:redemptions
    """
    broadcaster_id = os.getenv("TWITCH_BROADCASTER_ID", "").strip()
    bot_id = os.getenv("TWITCH_BOT_ID", "").strip() or broadcaster_id
    bot_token = bot.token_manager.bot_token
    streamer_token = bot.token_manager.streamer_token

    if not broadcaster_id or not bot_token:
        logger.warning(
            "EventSub skipped — TWITCH_BROADCASTER_ID and BOT_ACCESS_TOKEN required"
        )
        return

    try:
        from twitchio.ext import eventsub
        from twitchio.ext.eventsub.models import SubscriptionTypes

        # Patch twitchio v2 to support channel.chat.message
        # (absent from SubscriptionTypes — would cause KeyError in pump() if not patched)
        if "channel.chat.message" not in SubscriptionTypes._name_map:
            SubscriptionTypes._name_map["channel.chat.message"] = "channel_chat_message"
            SubscriptionTypes._type_map["channel.chat.message"] = ChatMessageData

        # Empêche twitchio d'ouvrir une WebSocket par souscription streamer
        # (limite Twitch : 3 par utilisateur) — cf. _patch_socket_tracking.
        # Le patch touche à l'interne d'une lib : s'il devient inapplicable (mise à
        # jour, signature changée), on repart sur le comportement d'origine plutôt
        # que de faire tomber TOUT EventSub.
        try:
            _patch_socket_tracking()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "EventSub: correctif de suivi des sockets inapplicable ({e}) — "
                "les dernières souscriptions risquent d'échouer en 429", e=exc,
            )

        # Avant toute création : rendre les places occupées par les souscriptions
        # de la session précédente, sinon elles plafonnent le quota et les
        # dernières créations tombent en 429.
        client_id = os.getenv("TWITCH_CLIENT_ID", "").strip()
        seen_tokens: set[str] = set()
        for tok in (streamer_token, bot_token):
            if tok and tok not in seen_tokens:
                seen_tokens.add(tok)
                await purge_stale_subscriptions(client_id, tok)

        client = eventsub.EventSubWSClient(bot)
        # Référencé TOUT DE SUITE, avant les ~15 s de souscriptions qui suivent
        # (8 × 1.5 s, plus les chaînes invitées). Il n'était posé qu'à la fin :
        # une exception ou une annulation en cours de route laissait un client
        # bien vivant, WebSockets ouvertes, mais que plus personne ne pouvait
        # fermer — d'où des transports occupés (429 au redémarrage) et, deux
        # clients coexistant, le chat livré en double (vécu le 2026-08-08).
        # Contrepartie assumée : le dashboard affiche EventSub « actif » pendant
        # ces quelques secondes de mise en place.
        bot._eventsub_client = client

        # Subscriptions are awaited sequentially — see existing code comment re: 4003 errors.
        # Des FABRIQUES, pas des coroutines : une coroutine ne s'await qu'une fois,
        # or les échecs 429 sont retentés plus tard (cf. _retry_failed_subscriptions).
        subscriptions: list[tuple[str, object]] = [
            ("follow", lambda: client.subscribe_channel_follows_v2(
                broadcaster=broadcaster_id, moderator=bot_id, token=bot_token
            )),
            ("raid", lambda: client.subscribe_channel_raid(
                token=bot_token, to_broadcaster=broadcaster_id
            )),
            ("chat", lambda: _subscribe_chat(client, broadcaster_id, bot_id, bot_token)),
        ]

        if streamer_token:
            # Ordre = importance décroissante. L'expérience du 2026-08-05 a montré
            # que le 429 frappe purement par POSITION (les 2 dernières sautent,
            # quel que soit leur type) : réordonner ne fait que déplacer la perte,
            # d'où le nettoyage des souscriptions mortes en amont. Cet ordre reste
            # le bon filet de sécurité si le quota venait quand même à manquer.
            subscriptions += [
                ("sub", lambda: client.subscribe_channel_subscriptions(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("resub", lambda: client.subscribe_channel_subscription_messages(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("gift_sub", lambda: client.subscribe_channel_subscription_gifts(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                # Devant cheer/subscription_end (pas en fin de liste) : le 429 du
                # 2026-08-05 frappe par POSITION, les deux dernières sautent. En fin
                # de liste, une souscription perdue ici veut dire une récompense
                # achetable dont l'achat n'arrive JAMAIS — et donc pas remboursable,
                # faute du moindre événement pour le déclencher.
                ("duel_redemption", lambda: client.subscribe_channel_points_redeemed(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("cheer", lambda: client.subscribe_channel_cheers(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("subscription_end", lambda: client.subscribe_channel_subscription_end(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
            ]
        else:
            logger.warning(
                "EventSub: streamer subscriptions skipped — set STREAMER_ACCESS_TOKEN "
                "(channel:read:subscriptions, bits:read)"
            )

        failed: list[tuple[str, object]] = []
        for name, make_sub in subscriptions:
            try:
                await make_sub()
                logger.info("EventSub subscribed: {sub}", sub=name)
            except Exception as exc:
                # Un 429 au boot est attendu quand les reboots sont rapprochés :
                # le budget de CRÉATION se recharge en minutes, pas en secondes.
                # Ce n'est pas une anomalie tant que le retry différé n'a pas
                # abandonné — d'où le niveau INFO ici, WARNING seulement à la fin.
                logger.info(
                    "EventSub subscription deferred [{sub}]: {e}", sub=name, e=exc
                )
                failed.append((name, make_sub))
            await asyncio.sleep(1.5)  # avoid 429 rate-limit on rapid subscription bursts

        # Chaînes invitées : chat seulement
        for guest_name in bot.config.twitch.guest_channels:
            guest_id = await bot.twitch_api.get_broadcaster_id(guest_name)
            if guest_id:
                bot._channel_ids[guest_name] = guest_id
                try:
                    await _subscribe_chat(client, guest_id, bot_id, bot_token)
                    logger.info("EventSub subscribed: chat guest {name}", name=guest_name)
                except Exception as exc:
                    logger.warning(
                        "EventSub guest chat failed [{name}]: {e}", name=guest_name, e=exc
                    )
            else:
                logger.warning(
                    "Chaîne invitée introuvable ou API indisponible: {name}", name=guest_name
                )
            await asyncio.sleep(0.5)

        logger.info(
            "EventSub WebSocket client active (broadcaster_id={bid})", bid=broadcaster_id
        )

        if failed:
            # En arrière-plan : le boot ne doit pas attendre. Un fix qui retentait
            # dans la foulée (3/6/12 s) avait été réfuté en live puis reverté — il
            # ralentissait le démarrage de 40 s sans rien récupérer, parce que la
            # fenêtre de recharge se compte en minutes.
            task = asyncio.create_task(_retry_failed_subscriptions(failed))
            bot._eventsub_retry_task = task  # référence forte : sinon le GC l'annule

    except Exception as exc:
        logger.error("EventSub client setup failed: {e}", e=exc)


_ES_SUBSCRIPTIONS_URL = "https://api.twitch.tv/helix/eventsub/subscriptions"


def _patch_socket_tracking() -> None:
    """Corrige une fuite de connexions WebSocket dans twitchio 2.10.0.

    Dans `EventSubWSClient._assign_subscription`, quand aucun socket connu n'a de
    place, twitchio en ouvre un nouveau… mais **ne l'ajoute jamais** à
    `self._sockets` (`ext/eventsub/websocket.py`, branche `for/else`).

    Une WebSocket EventSub n'accepte qu'un seul utilisateur authentifié. Les
    souscriptions du streamer sont donc refusées sur le socket du bot (400), et
    comme le socket de remplacement n'est pas mémorisé, CHAQUE souscription
    streamer en rouvrait un neuf : `sub`→2e, `resub`→3e, `gift_sub`→4e. Twitch
    plafonnant à **3 connexions par utilisateur**, la suivante était refusée avec
    un 429 trompeur (« number of websocket transports limit exceeded », renvoyé à
    la place d'un 400 — bug Twitch connu). D'où `cheer`/`subscription_end` perdus
    à chaque démarrage, et des sockets orphelins impossibles à fermer.

    Deux autres défauts du même code se payaient à la RECONNEXION, pas au
    démarrage — `Websocket.connect()` rejoue tout son `_subscription_pool` :

    1. la souscription refusée en 400 restait dans le pool du socket fautif,
       `add_subscription` l'y ayant empilée AVANT de savoir si Twitch
       l'acceptait. Le socket du bot rejouait donc les six souscriptions du
       streamer à chaque reconnexion ;
    2. la souscription posée sur le socket de secours repartait sans qu'on
       attende `sub.created` : `_wakeup_and_connect` résolvait la Future dans
       son coin, et plus personne ne la remettait à `None`. À la reconnexion
       suivante, `_subscribe()` la voyait encore là et appelait `set_result`
       une deuxième fois — `InvalidStateError`, remontée jusqu'à `pump()`, la
       tâche meurt et le chat Twitch ne descend plus. Vécu le 2026-08-14 en
       plein live : deux minutes de surdité complète, jusqu'au chien de garde.

    twitchio v2 n'est plus maintenu (le projet est en v3, API incompatible), donc
    le correctif vit ici. Idempotent.
    """
    from twitchio.ext.eventsub import EventSubWSClient

    if getattr(EventSubWSClient, "_wally_socket_tracking_patched", False):
        return

    async def _assign_subscription(self, sub) -> None:  # noqa: ANN001
        # Import LOCAL, et non capturé à l'application du correctif : c'est le
        # seul point de création de socket, donc le seul endroit où un test peut
        # se substituer à une vraie connexion vers Twitch.
        from twitchio.ext.eventsub.websocket import Websocket

        # Reprise fidèle de twitchio 2.10.0, à trois endroits près, tous
        # signalés ci-dessous.
        if not self._sockets:
            w = Websocket(self.client, self._http)
            await w.connect()
            self._sockets.append(w)

        success = False
        bad_sockets: set | None = None

        while not success:
            if bad_sockets is not None:
                socks = filter(lambda sock: sock not in bad_sockets, self._sockets)
            else:
                socks = self._sockets

            s = None
            for s in socks:
                if s.remaining_slots > 0:
                    s.add_subscription(sub)
                    break
            else:
                s = Websocket(self.client, self._http)
                await s.connect()
                self._sockets.append(s)  # ← CORRECTION 1 : socket mémorisé
                s.add_subscription(sub)
                # CORRECTION 2 : on attend le verdict et on referme `created`.
                # Repartir tout de suite laissait une Future RÉSOLUE sur la
                # souscription — le `set_result` de trop, à la reconnexion.
                # Le `return` est conservé : un socket neuf ne peut pas être
                # « occupé par un autre utilisateur », donc rien à réessayer, et
                # boucler ici ouvrirait une WebSocket de plus à chaque tour.
                assert sub.created is not None
                success, status = await sub.created
                sub.created = None
                if not success:
                    raise RuntimeError(
                        f"Subscription failed on a fresh socket. Status: {status}"
                    )
                return

            assert sub.created is not None
            success, status = await sub.created

            if not success and status == 400:
                # Socket occupé par un autre utilisateur : on en essaie un autre.
                # CORRECTION 3 : le pool du socket refusé est purgé. Sans ça il
                # rejouait à chaque reconnexion une souscription que Twitch lui
                # refusera toujours.
                if bad_sockets is None:
                    bad_sockets = set()
                bad_sockets.add(s)
                try:
                    s._subscription_pool.remove(sub)
                except ValueError:  # déjà retirée : rien à faire
                    pass
                sub.created = asyncio.Future()
                continue
            elif not success and status in (401, 403):
                from twitchio import Unauthorized

                raise Unauthorized(
                    "You are not authorized to make this subscription", status=status
                )
            elif not success:
                raise RuntimeError(f"Subscription failed, reason unknown. Status: {status}")
            else:
                sub.created = None
                break

    EventSubWSClient._assign_subscription = _assign_subscription
    EventSubWSClient._wally_socket_tracking_patched = True


def cancel_retry_task(bot: "WallyTwitch") -> bool:
    """Annule la reprise différée des souscriptions. Vrai si une tâche vivait.

    À appeler AVANT de fermer les sockets, partout où le client EventSub est
    démonté. `_retry_failed_subscriptions` capture le client et le token de
    l'appel qui l'a créée : après une reconstruction, elle se réveille jusqu'à
    20 minutes plus tard et travaille sur un client mort. Deux issues, toutes
    deux vérifiées dans twitchio 2.10 :

    — l'ancien socket est encore dans `client._sockets` avec des places libres,
      donc `add_subscription` y atterrit ; `_wakeup_and_connect` teste
      `if self.is_connected`, le socket est fermé, la coroutine ne fait RIEN, et
      `await sub.created` n'est jamais résolu : la tâche se bloque à vie, avec
      elle toutes les souscriptions différées restantes ;
    — plus aucune place libre, et twitchio ouvre une NOUVELLE WebSocket vivante
      hors de `_eventsub_client`, donc infermable. Pour `channel.chat.message`,
      c'est la double réception corrigée par `2c035a9` qui revient.
    """
    # Lecture d'abord, écriture seulement s'il y avait quelque chose : cette
    # fonction est appelée depuis `close_eventsub_client`, qui promet de ne
    # jamais lever. Écrire d'office plantait sur un objet sans attributs.
    task = getattr(bot, "_eventsub_retry_task", None)
    if task is None:
        return False
    bot._eventsub_retry_task = None
    if task.done():
        return False
    task.cancel()
    logger.info("EventSub: reprise différée annulée (client démonté)")
    return True


async def close_eventsub_client(bot: "WallyTwitch") -> int:
    """Ferme les WebSockets EventSub pour rendre les transports à Twitch.

    Twitch plafonne à **3 connexions WebSocket concurrentes** par couple
    (user, client_id) — et renvoie un 429 trompeur quand la limite est atteinte
    (« number of websocket transports limit exceeded »), là où un 400 est attendu.
    twitchio ne sait rebasculer que sur un 400 : le 429 remonte donc en
    « Subscription failed, reason unknown » et la souscription est perdue.

    twitchio ouvre une connexion par token (le socket du bot refuse les
    souscriptions du streamer), soit 2 par démarrage. Un process tué sans
    fermeture laisse ces transports ouverts côté Twitch : deux redémarrages
    rapprochés suffisent alors à saturer les 3 places.

    Retourne le nombre de sockets fermés. Jamais bloquant.
    """
    cancel_retry_task(bot)
    client = getattr(bot, "_eventsub_client", None)
    if client is None:
        return 0
    closed = 0
    for ws in list(getattr(client, "_sockets", []) or []):
        sock = getattr(ws, "_sock", None)
        try:
            if sock is not None and not sock.closed:
                await sock.close()
                closed += 1
        except Exception as exc:  # noqa: BLE001 — arrêt, on ne bloque jamais
            logger.debug("EventSub: fermeture d'un socket échouée: {e}", e=exc)
    if closed:
        logger.info("EventSub: {n} connexion(s) WebSocket fermée(s)", n=closed)
    return closed


async def purge_stale_subscriptions(client_id: str, token: str) -> int:
    """Supprime les souscriptions EventSub qui ne sont plus `enabled`.

    À chaque redémarrage, la WebSocket précédente meurt et ses souscriptions
    passent en `websocket_disconnected`. Twitch les conserve un moment, et elles
    **occupent encore des places** : au boot suivant on repartait donc avec 3
    fantômes, seules 3 créations passaient et les suivantes tombaient en 429.
    C'est ce qui faisait perdre `resub`/`gift_sub` (ou `cheer` selon l'ordre)
    jusqu'au prochain démarrage « propre ».

    Retourne le nombre de souscriptions supprimées. Silencieux en cas d'échec :
    le nettoyage est un confort, il ne doit jamais empêcher le boot.
    """
    if not client_id or not token:
        return 0
    headers = {"Authorization": f"Bearer {token}", "Client-Id": client_id}
    removed = 0
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(_ES_SUBSCRIPTIONS_URL, headers=headers)
            if resp.status_code != 200:
                logger.info(
                    "EventSub: nettoyage ignoré (HTTP {code})", code=resp.status_code
                )
                return 0
            stale = [
                s for s in resp.json().get("data", []) if s.get("status") != "enabled"
            ]
            for sub in stale:
                r = await http.delete(
                    _ES_SUBSCRIPTIONS_URL, headers=headers, params={"id": sub["id"]}
                )
                if r.status_code in (200, 204):
                    removed += 1
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.info("EventSub: nettoyage des souscriptions mortes échoué: {e}", e=exc)
    if removed:
        logger.info(
            "EventSub: {n} souscription(s) morte(s) supprimée(s) — places libérées",
            n=removed,
        )
    return removed


async def count_active_subscriptions(client_id: str, token: str) -> int | None:
    """Nombre de souscriptions EventSub WebSocket réellement vivantes.

    Seul Twitch sait si la session livre encore : l'état interne de twitchio dit
    « connecté » alors que la WebSocket est morte et que les souscriptions ont
    été révoquées. Un statut `websocket_disconnected` occupe encore une place
    mais ne livre plus rien — le compter masquerait précisément la panne.

    Retourne `None` si la question n'a pas pu être posée (réseau, HTTP non-200) :
    « je n'ai pas pu demander » n'est pas « il n'y a plus rien », et c'est une
    coupure réseau qui déclenche ce genre d'incident.
    """
    if not client_id or not token:
        return None
    headers = {"Authorization": f"Bearer {token}", "Client-Id": client_id}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(_ES_SUBSCRIPTIONS_URL, headers=headers)
            if resp.status_code != 200:
                return None
            return sum(
                1
                for s in resp.json().get("data", [])
                if s.get("status") == "enabled"
                and (s.get("transport") or {}).get("method") == "websocket"
            )
    except Exception as exc:  # noqa: BLE001 — une panne de sonde n'est pas un diagnostic
        logger.debug("EventSub: état des souscriptions indisponible: {e}", e=exc)
        return None


# Délais de reprise des souscriptions tombées en 429, en SECONDES. Espacés en
# minutes, car un backoff de quelques secondes avait été réfuté en live.
_RETRY_DELAYS = (120, 480, 1200)


async def _retry_failed_subscriptions(failed: list[tuple[str, object]]) -> None:
    """Reprend en arrière-plan les souscriptions refusées au démarrage.

    Sans ça, une souscription perdue au boot le restait jusqu'au redémarrage
    suivant : `channel.cheer` et `channel.subscription.end` manquaient
    durablement, donc les bits et les fins d'abonnement passaient inaperçus.
    """
    pending = list(failed)
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        await asyncio.sleep(delay)
        logger.info(
            "EventSub: reprise {n}/{total} de {subs}",
            n=attempt, total=len(_RETRY_DELAYS),
            subs=", ".join(name for name, _ in pending),
        )
        still_failing: list[tuple[str, object]] = []
        for name, make_sub in pending:
            try:
                await make_sub()
                logger.info("EventSub subscribed on retry: {sub}", sub=name)
            except Exception as exc:
                # INFO et pas DEBUG : en DEBUG, une reprise ratée était totalement
                # invisible en prod, impossible de distinguer « la tâche n'a pas
                # démarré » de « la reprise a échoué ».
                logger.info(
                    "EventSub retry {n}/{total} failed [{sub}]: {e}",
                    n=attempt, total=len(_RETRY_DELAYS), sub=name, e=exc,
                )
                still_failing.append((name, make_sub))
            await asyncio.sleep(1.5)
        pending = still_failing
        if not pending:
            logger.info("EventSub: toutes les souscriptions différées ont abouti")
            return

    # Là seulement c'est une vraie anomalie : le budget aurait dû se recharger.
    logger.warning(
        "EventSub: abandon après reprises — souscriptions manquantes: {subs}",
        subs=", ".join(name for name, _ in pending),
    )


async def _subscribe_chat(client, broadcaster_id: str, bot_id: str, token: str):
    """Subscribe to channel.chat.message via manual _Subscription (not in twitchio v2 API).

    Uses EventSubWSClient._assign_subscription() — the same internal path used by all
    native subscribe_* methods (e.g. subscribe_channel_follows_v2). add_subscription()
    and _wakeup_and_connect() are methods on the inner Websocket class, not on
    EventSubWSClient — using them directly would raise AttributeError.
    """
    from twitchio.ext.eventsub.websocket import _Subscription

    sub = _Subscription(
        ("channel.chat.message", 1, ChatMessageData),
        {"broadcaster_user_id": broadcaster_id, "user_id": bot_id},
        token,
    )
    await client._assign_subscription(sub)
