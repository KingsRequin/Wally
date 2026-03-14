# bot/core/persona.py
from __future__ import annotations

import os

from loguru import logger


class PersonaService:
    """Charge et expose les fichiers de persona Markdown (SOUL, IDENTITY, VOICE)."""

    _FILES = ["SOUL.md", "IDENTITY.md", "VOICE.md"]  # ordre canonique

    def __init__(self, persona_dir: str = "bot/persona"):
        self._dir = persona_dir
        self._blocks: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        """Recharge tous les fichiers .md depuis le disque."""
        for filename in self._FILES:
            path = os.path.join(self._dir, filename)
            try:
                with open(path, encoding="utf-8") as f:
                    self._blocks[filename] = f.read().strip()
                logger.info("Persona file loaded: {f}", f=filename)
            except FileNotFoundError:
                logger.warning("Persona file missing: {f}", f=filename)
                self._blocks[filename] = ""
            except Exception as exc:
                logger.warning("Persona file read error {f}: {e}", f=filename, e=exc)
                self._blocks[filename] = ""

    def build_prompt_block(self) -> str:
        """Retourne les blocs SOUL → IDENTITY → VOICE concaténés."""
        return "\n\n".join(v for v in self._blocks.values() if v)
