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


# Une demi-seconde de silence, à 16 kHz mono 16 bits : de quoi faire traverser
# toute la chaîne à vide.
_SILENCE = b"\x00" * 16000


def _transcriber(stt: Any) -> Any:
    """L'objet qui transcrit vraiment. En mode distant, c'est le repli local qui
    porte le modèle — et c'est lui qui met des secondes à charger."""
    if stt is None:
        return None
    return getattr(stt, "_fallback", None) or stt


async def signal_ready_when_warm(
    vc: Any, warmup: Awaitable | None, stt: Any = None
) -> None:
    """Attend que le STT sache vraiment transcrire, puis démute.

    Attendre le `warmup` ne suffisait pas : le modèle se charge en DEUX
    exemplaires — constaté le 2026-08-08, deux « chargement du modèle » à trois
    secondes d'intervalle — et on n'en attendait qu'un. Wally se démutait donc
    quelques secondes trop tôt, et on lui parlait encore dans le vide.

    On fait donc passer un silence dans la chaîne complète : si une
    transcription à blanc aboutit, la parole suivante aboutira. C'est le seul
    signal qui ne dépende pas du nombre d'objets à réveiller.

    Un échec démute quand même : mieux vaut l'annoncer prêt à tort que le
    laisser muet pour toujours.
    """
    if warmup is not None:
        try:
            await warmup
        except Exception as exc:  # noqa: BLE001
            logger.warning("voice: préchauffage STT en échec : {e}", e=exc)
    transcriber = _transcriber(stt)
    if transcriber is not None and hasattr(transcriber, "transcribe"):
        try:
            await transcriber.transcribe(_SILENCE)
        except Exception as exc:  # noqa: BLE001
            logger.debug("voice: transcription à blanc en échec : {e}", e=exc)
    await set_muted(vc, False)
    logger.info("voice: prêt à écouter")
