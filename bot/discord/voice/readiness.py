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

# Durée du mode test pris automatiquement en écoute. Le plafond du narrateur :
# il est de toute façon coupé à la sortie du salon, donc borné par la présence.
_TEST_MODE_MINUTES = 120


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


async def take_test_mode_if_needed(narrator: Any) -> bool:
    """Active le mode test s'il n'y a pas de live. Rend True si on l'a pris.

    Wally en écoute dans un salon vocal, c'est le compagnon de stream. Sans live
    derrière, on est forcément en train de régler quelque chose : lui faire
    croire à un live évite d'avoir à cocher la case à chaque essai, et évite
    surtout le symptôme le plus déroutant — un overlay muet sans rien pour
    l'expliquer.
    """
    if narrator is None:
        return False
    try:
        if narrator.is_active() or narrator.force_live_remaining() > 0:
            return False          # vrai live, ou réglage posé à la main
        narrator.force_live(_TEST_MODE_MINUTES)
        await narrator.flush_force_live()
        logger.info("voice: pas de live — mode test activé pour l'écoute")
        return True
    except Exception as exc:  # noqa: BLE001 — jamais bloquant pour l'écoute
        logger.debug("voice: mode test non activé: {e}", e=exc)
        return False


async def release_test_mode(narrator: Any, *, taken: bool) -> None:
    """Coupe le mode test, mais seulement si c'est nous qui l'avions pris."""
    if narrator is None or not taken:
        return
    try:
        narrator.force_live(0)
        await narrator.flush_force_live()
        logger.info("voice: sortie du vocal — mode test coupé")
    except Exception as exc:  # noqa: BLE001
        logger.debug("voice: mode test non coupé: {e}", e=exc)
