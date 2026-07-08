from __future__ import annotations

from pathlib import Path

from loguru import logger

from bot.intelligence.identity import render_identity


class SpeakGuard:
    """Dernier filtre avant l'envoi d'un message SPONTANÉ (SPEAK cognitif ou DM
    créateur). Un appel LLM léger juge si le brouillon vaut le coup d'être envoyé
    ou s'il vaut mieux se taire — filet adversarial contre les messages inutiles,
    redondants ou besogneux que la boucle cognitive laisse parfois passer.

    Fail-open : toute erreur, verdict illisible ou doute → on envoie. Le garde
    ne muselle jamais Wally par accident et ne fait jamais crasher la boucle.
    """

    def __init__(self, llm, prompts_dir: str | Path, enabled: bool = True) -> None:
        self._llm = llm
        self.enabled = enabled
        self._system = render_identity(
            (Path(prompts_dir) / "speak_guard.md").read_text(encoding="utf-8")
        )

    async def worth_sending(self, message: str, context: str = "") -> tuple[bool, str]:
        """Retourne (envoyer?, raison). (True, "") si désactivé ou en cas d'échec."""
        if not self.enabled:
            return True, ""
        message = (message or "").strip()
        if not message:
            return True, ""
        user_msg = (
            f"CONTEXTE RÉCENT :\n{context or '(aucun)'}\n\n"
            f"MESSAGE QUE WALLY VEUT ENVOYER :\n{message}"
        )
        try:
            reply = await self._llm.complete(
                self._system, [{"role": "user", "content": user_msg}]
            )
        except Exception as e:  # noqa: BLE001 — jamais bloquer/crasher la boucle
            logger.warning("SpeakGuard: appel LLM échoué → envoi ({})", e)
            return True, ""

        raw = (reply or "").strip()
        reason = raw.split("—", 1)[1].strip() if "—" in raw else raw[:200]
        # On ne bloque que sur un TAIS-TOI explicite ; tout le reste = fail-open.
        if raw.upper().lstrip().startswith("TAIS-TOI"):
            return False, reason
        if not raw:
            logger.debug("SpeakGuard: verdict vide → envoi")
        return True, reason
