from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass
class ChannelInfo:
    id: str
    name: str
    type: str
    purpose: str


class ChannelDirectory:
    """Annuaire des canaux Discord où Wally peut s'exprimer.

    Chargé depuis un fichier texte (`CHANNELS.md`) en bind-mount du dossier
    persona, donc éditable à chaud. Sert deux usages :
    - injection dans le prompt de reasoning (`render`) pour que la cognition
      choisisse PROACTIVEMENT le canal adapté à son intention ;
    - validation des décisions SPEAK (`speakable_ids` / `is_speakable`) : tout
      canal textuel de l'annuaire est une cible légitime.
    """

    def __init__(self, channels: list[ChannelInfo]) -> None:
        self._channels = channels

    @classmethod
    def load(cls, path: str | Path) -> "ChannelDirectory":
        p = Path(path)
        if not p.exists():
            logger.info("ChannelDirectory : fichier absent ({}) — annuaire vide", p)
            return cls([])
        channels: list[ChannelInfo] = []
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [f.strip() for f in line.split("|")]
            if len(parts) != 4:
                logger.warning("ChannelDirectory : ligne ignorée (malformée) : {}", raw)
                continue
            cid, name, ctype, purpose = parts
            channels.append(ChannelInfo(id=cid, name=name, type=ctype, purpose=purpose))
        logger.info("ChannelDirectory : {} canal(aux) chargé(s)", len(channels))
        return cls(channels)

    def speakable_ids(self) -> set[str]:
        return {c.id for c in self._channels if c.type == "text"}

    def name_map(self) -> dict[str, str]:
        """Mapping id → nom lisible, tous types de canaux confondus."""
        return {c.id: c.name for c in self._channels}

    def is_speakable(self, channel_id: str) -> bool:
        return channel_id in self.speakable_ids()

    def render(self) -> str:
        speakable = [c for c in self._channels if c.type == "text"]
        if not speakable:
            return ""
        lines = ["Canaux où tu peux écrire (serveur principal) :"]
        for c in speakable:
            lines.append(f"  {c.id} {c.name} — {c.purpose}")
        forums = [c for c in self._channels if c.type == "forum"]
        if forums:
            names = ", ".join(c.name for c in forums)
            lines.append(f"({names} est un forum : n'y poste pas spontanément.)")
        return "\n".join(lines)
