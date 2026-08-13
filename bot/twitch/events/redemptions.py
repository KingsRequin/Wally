# bot/twitch/events/redemptions.py
"""Achat d'une récompense de points de chaîne → ouverture d'un duel Apex.

Perception passive comme tout événement de stream ici : on alimente le flux,
on ne réveille aucune cadence de parole (`notify_*` absent volontairement).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


def _est_notre_recompense(bot, reward_id: str) -> bool:
    """La récompense créée par Wally lui-même, identifiée par son ID.

    Jamais par son titre : un titre se renomme d'un clic dans la console Twitch
    et le duel cesserait de répondre sans un mot dans les logs.

    Jamais par la config non plus : Twitch réserve le remboursement d'une
    redemption à l'application qui a CRÉÉ la récompense, donc c'est Wally qui
    la crée au démarrage — son ID est découvert à l'exécution et vit sur
    `bot.duel_runner._reward_id`, jamais dans `config.yaml`.

    Un `reward_id` vide (runner absent, ou récompense pas encore créée)
    DÉSACTIVE le duel — sans ce garde, la moindre récompense de la chaîne en
    lancerait un. `bot.duel_runner` lui-même peut ne pas exister tant que sa
    tâche de câblage n'est pas passée — d'où le double `getattr`.
    """
    runner = getattr(bot, "duel_runner", None)
    attendu = str(getattr(runner, "_reward_id", "") or "")
    return bool(attendu) and str(reward_id) == attendu


async def handle_redemption(bot: "WallyTwitch", event) -> None:
    """Point d'entrée EventSub. N'échoue jamais vers l'appelant."""
    try:
        reward_id = str(getattr(getattr(event, "reward", None), "id", ""))
        if not _est_notre_recompense(bot, reward_id):
            return

        redemption_id = str(getattr(event, "id", ""))
        acheteur = str(getattr(getattr(event, "user", None), "name", "") or "?")
        saisie = str(getattr(event, "input", "") or "")

        logger.info("Duel Apex demandé par {u} (saisie : {s!r})", u=acheteur, s=saisie[:60])

        runner = getattr(bot, "duel_runner", None)
        if runner is None:
            logger.error("Duel demandé mais aucun runner câblé — remboursement")
            await bot.twitch_api.refund_redemption(reward_id, redemption_id)
            return

        if runner.duel_en_cours is not None:
            logger.info("Duel déjà en cours — remboursement de {u}", u=acheteur)
            await bot.twitch_api.refund_redemption(reward_id, redemption_id)
            return

        await runner.ouvrir(
            acheteur=acheteur, saisie=saisie,
            reward_id=reward_id, redemption_id=redemption_id,
        )
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("Redemption en erreur : {e}", e=exc)
