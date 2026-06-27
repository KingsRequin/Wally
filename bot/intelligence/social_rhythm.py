from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

# Prior doux au démarrage : tant qu'un créneau n'a pas assez d'observations,
# la réceptivité reste « modérée » (ni muet ni bavard).
PRIOR = 0.5
# Pondération ambient (vivacité) vs engagement (taux de réponse à ses messages).
W_AMBIENT = 0.5
W_ENGAGEMENT = 0.5
# Réceptivité de référence : au-dessus, la parole spontanée passe toujours ;
# en-dessous, la proba chute linéairement (cf. cognitive_loop). 0.4 ≈ « journée normale ».
R_REF = 0.4


def _daytype(when: datetime) -> str:
    return "we" if when.weekday() >= 5 else "wk"


def _key(when: datetime) -> str:
    return f"{_daytype(when)}:{when.hour:02d}"


class SocialRhythm:
    """Apprend, par créneau heure×semaine/weekend, à quel point l'audience est
    réceptive (0→1). Aucun seuil horaire codé : la nuit émerge comme un creux."""

    def __init__(self, tz: str = "Europe/Paris", alpha: float = 0.1,
                 n_conf: int = 20) -> None:
        self._tz = ZoneInfo(tz)
        self._alpha = alpha
        self._n_conf = max(1, n_conf)
        # bin_key -> {"avg": float, "eng": float, "days": int, "eng_obs": int,
        #             "count": float (intra-jour, non persisté)}
        self._bins: dict[str, dict] = {}
        self._cur_day: str | None = None
        self._cur_daytype: str = "wk"

    def _bin(self, key: str) -> dict:
        return self._bins.setdefault(
            key, {"avg": 0.0, "eng": 0.5, "days": 0, "eng_obs": 0, "count": 0.0}
        )

    # --- Apprentissage ----------------------------------------------------
    def record_incoming(self, when: datetime) -> None:
        """Un message reçu → vivacité du créneau courant (signal ambient)."""
        w = when.astimezone(self._tz)
        day = w.strftime("%Y-%m-%d")
        if self._cur_day is None:
            self._cur_day, self._cur_daytype = day, _daytype(w)
        elif day != self._cur_day:
            self._roll_day()
            self._cur_day, self._cur_daytype = day, _daytype(w)
        self._bin(_key(w))["count"] += 1.0

    def _roll_day(self) -> None:
        """Replie les compteurs intra-jour dans la moyenne EMA des 24 créneaux du
        type-de-jour écoulé (les créneaux à 0 décroissent → la nuit s'éteint seule)."""
        dt = self._cur_daytype
        a = self._alpha
        for h in range(24):
            b = self._bin(f"{dt}:{h:02d}")
            b["avg"] = b["avg"] * (1 - a) + b["count"] * a
            b["count"] = 0.0
            b["days"] += 1

    def record_spontaneous_outcome(self, answered: bool, when: datetime) -> None:
        """Issue d'un message spontané : répondu (+) ou ignoré ( ). EMA d'engagement."""
        w = when.astimezone(self._tz)
        b = self._bin(_key(w))
        a = self._alpha
        b["eng"] = b["eng"] * (1 - a) + (1.0 if answered else 0.0) * a
        b["eng_obs"] += 1

    # --- Restitution ------------------------------------------------------
    def receptivity(self, when: datetime) -> float:
        w = when.astimezone(self._tz)
        b = self._bins.get(_key(w))
        max_avg = max((x["avg"] for x in self._bins.values()), default=0.0)
        ambient = (b["avg"] / max_avg) if (b and max_avg > 0) else PRIOR
        eng = b["eng"] if b else PRIOR
        observed = W_AMBIENT * ambient + W_ENGAGEMENT * eng
        obs = (b["days"] + b["eng_obs"]) if b else 0
        conf = min(1.0, obs / self._n_conf)
        return PRIOR * (1 - conf) + observed * conf
