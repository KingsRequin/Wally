from __future__ import annotations

from loguru import logger


class OwnerOutreachGate:
    """Un seul fil de sollicitation vers l'owner à la fois (tout type confondu :
    self-fix, questions DM). Tant qu'un MP est sans réponse, on n'en envoie plus ;
    quand l'owner répond, la cognition re-soulève d'elle-même ce qui compte encore.

    État volontairement minimal et en mémoire : au redémarrage, repartir « non
    bloqué » est sûr (au pire un message de plus, jamais un empilement)."""

    def __init__(self) -> None:
        self._blocked = False

    def is_blocked(self) -> bool:
        return self._blocked

    def mark_sent(self) -> None:
        self._blocked = True
        logger.info("OwnerOutreachGate: sollicitation owner en attente de réponse")

    def clear(self) -> None:
        if self._blocked:
            logger.info("OwnerOutreachGate: owner a répondu → fil libéré")
        self._blocked = False
