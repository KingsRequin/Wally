# bot/twitch/events/redemptions.py
"""Achat d'une récompense de points de chaîne → ouverture d'un duel Apex.

Perception passive comme tout événement de stream ici : on alimente le flux
(`stream_feed`), on ne réveille aucune cadence de parole (`notify_*` absent
volontairement — le `feed.record()` en dessous n'en fait pas partie, il ne
touche que l'observateur de l'overlay).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


def _feed(bot, description: str) -> None:
    """Inscrit l'achat dans le flux passif (best-effort).

    Import inline plutôt que `from bot.twitch.events.social import _feed` :
    `social.py` importe déjà ce module (pour enregistrer le handler
    EventSub) — importer dans l'autre sens créerait un cycle. `getattr`
    reste donc la façon la plus simple de rester indépendant de social.py.
    """
    feed = getattr(bot, "stream_feed", None)
    if feed is None:
        return
    try:
        feed.record(description, kind="duel_redemption")
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("StreamFeed: enregistrement échoué : {e}", e=exc)


async def _est_notre_recompense(bot, reward_id: str) -> bool:
    """La récompense créée par Wally lui-même, identifiée par son ID.

    Jamais par son titre : un titre se renomme d'un clic dans la console Twitch
    et le duel cesserait de répondre sans un mot dans les logs.

    Jamais par la config non plus : Twitch réserve le remboursement d'une
    redemption à l'application qui a CRÉÉ la récompense, donc c'est Wally qui
    la crée au démarrage — son ID est découvert à l'exécution et vit sur
    `bot.duel_runner._reward_id`, jamais dans `config.yaml`.

    `bot.duel_runner` peut être absent (Apex indisponible au boot, ou pas
    encore câblé) : on retombe alors sur l'ID persisté dans `bot_state`
    (`apex:duel_reward_id`, écrit par `DuelRunner.assurer_recompense`). SANS ce
    repli, un achat pendant que le runner est down ne serait jamais reconnu
    comme « notre » récompense — cette fonction rendrait `False` avant même que
    `handle_redemption` puisse atteindre sa branche « runner absent » et
    rembourser. Le viewer paierait pour rien.

    Un `reward_id` vide (aucune des deux sources connue) DÉSACTIVE le duel —
    sans ce garde, la moindre récompense de la chaîne en lancerait un.
    """
    runner = getattr(bot, "duel_runner", None)
    attendu = str(getattr(runner, "_reward_id", "") or "")
    if not attendu:
        db = getattr(bot, "db", None)
        if db is not None:
            try:
                attendu = str(await db.get_state("apex:duel_reward_id") or "")
            except Exception as exc:  # noqa: BLE001 — un repli ne casse jamais le filtrage
                logger.debug("Repli reward_id persistée indisponible : {e}", e=exc)
    return bool(attendu) and str(reward_id) == attendu


async def handle_redemption(bot: "WallyTwitch", event) -> None:
    """Point d'entrée EventSub. N'échoue jamais vers l'appelant."""
    reward_id = ""
    redemption_id = ""
    try:
        reward_id = str(getattr(getattr(event, "reward", None), "id", ""))
        if not await _est_notre_recompense(bot, reward_id):
            return

        redemption_id = str(getattr(event, "id", ""))
        acheteur = str(getattr(getattr(event, "user", None), "name", "") or "?")
        saisie = str(getattr(event, "input", "") or "")

        logger.info("Duel Apex demandé par {u} (saisie : {s!r})", u=acheteur, s=saisie[:60])
        _feed(bot, f"{acheteur} a acheté un duel Apex contre Azraël (points de chaîne)")

        runner = getattr(bot, "duel_runner", None)
        if runner is None:
            logger.error("Duel demandé mais aucun runner câblé — remboursement")
            await bot.twitch_api.refund_redemption(reward_id, redemption_id)
            return

        # Le cas « duel déjà en cours » n'est PLUS court-circuité ici : seul
        # `ouvrir()` détient à la fois le remboursement ET le canal d'annonce
        # (Task 8) — un refus muet, remboursé en direct depuis ce handler,
        # laissait le viewer sans un mot d'explication.
        await runner.ouvrir(
            acheteur=acheteur, saisie=saisie,
            reward_id=reward_id, redemption_id=redemption_id,
        )
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("Redemption en erreur : {e}", e=exc)
        # Best-effort : une exception ici (p. ex. un timeout réseau au milieu
        # d'`ouvrir()`) ne doit pas coûter ses points au viewer. `reward_id` et
        # `redemption_id` ne sont posés qu'après le filtrage — vides, il n'y a
        # rien à rembourser. Un remboursement en double sur une redemption déjà
        # traitée est refusé proprement côté Twitch, donc sans risque.
        if reward_id and redemption_id:
            try:
                await bot.twitch_api.refund_redemption(reward_id, redemption_id)
            except Exception as exc2:  # noqa: BLE001 — le repli ne relève jamais non plus
                logger.error("Remboursement de secours en erreur : {e}", e=exc2)
