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

        bot._eventsub_client = client
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
