# bot/discord/voice/readiness.py
"""Signaler à partir de quand Wally entend vraiment.

Le modèle STT se charge APRÈS l'arrivée dans le salon : la connexion est
établie, l'écoute est branchée, mais les premières secondes de parole se
perdent. Rien ne le montrait.

Il rejoint donc **en sourdine** et se démute une fois prêt. C'est visible d'un
coup d'œil dans la liste du vocal, et silencieux — un bip serait entendu par les
spectateurs pendant un live.
"""
from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Optional

from loguru import logger


async def set_muted(vc: Any, muted: bool) -> None:
    """Coupe ou rend le micro de Wally. Sans effet s'il a quitté le salon."""
    if vc is None or getattr(vc, "channel", None) is None:
        return
    try:
        await vc.guild.change_voice_state(channel=vc.channel, self_mute=muted)
    except Exception as exc:  # noqa: BLE001 — un signal raté ne casse pas l'écoute
        logger.debug("voice: micro non {e}: {x}", e="coupé" if muted else "rétabli", x=exc)


async def signal_ready_when_warm(vc: Any, warmup: Awaitable | None) -> None:
    """Attend le chargement du modèle, puis démute pour dire « je t'écoute ».

    Un préchauffage en échec démute quand même : mieux vaut l'annoncer prêt à
    tort que le laisser muet pour toujours — le repli CPU finira par répondre.
    """
    if warmup is not None:
        try:
            await warmup
        except Exception as exc:  # noqa: BLE001
            logger.warning("voice: préchauffage STT en échec : {e}", e=exc)
    await set_muted(vc, False)
    logger.info("voice: prêt à écouter")
