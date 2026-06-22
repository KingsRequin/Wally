# bot/core/persona.py
from __future__ import annotations

import os

from loguru import logger


class PersonaService:
    """Charge et expose les fichiers de persona Markdown (SOUL, IDENTITY, VOICE, EMOTIONS)."""

    _FILES = ["SOUL.md", "IDENTITY.md", "VOICE.md", "EXEMPLES.md", "CAPABILITIES.md"]  # ordre canonique pour persona_block

    def __init__(self, persona_dir: str = "bot/persona"):
        self._dir = persona_dir
        self._blocks: dict[str, str] = {}
        self._emotion_directives: dict[str, str] = {}
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

        self._emotion_directives = self._parse_emotions()
        self._weekday_directives = self._parse_weekdays()
        self._composite_directives = self._parse_composites()
        self._secondary_directives = self._parse_secondaries()

    def _parse_emotions(self) -> dict[str, str]:
        """Parse EMOTIONS.md en un dict {emotion: directive}."""
        path = os.path.join(self._dir, "EMOTIONS.md")
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            logger.warning("Persona file missing: EMOTIONS.md")
            return {}
        except Exception as exc:
            logger.warning("EMOTIONS.md read error: {e}", e=exc)
            return {}

        directives: dict[str, str] = {}
        # Sections délimitées par "## emotion_name"
        sections = content.split("\n## ")
        for section in sections[1:]:  # sections[0] = préambule
            lines = section.strip().split("\n", 1)
            if len(lines) >= 2:
                emotion = lines[0].strip()
                text = " ".join(lines[1].strip().split("\n")).strip()
                if emotion and text:
                    directives[emotion] = text
        logger.info("EMOTIONS.md loaded: {n} directives", n=len(directives))
        return directives

    def _parse_weekdays(self) -> dict[str, str]:
        """Parse WEEKDAYS.md en un dict {jour: directive}."""
        path = os.path.join(self._dir, "WEEKDAYS.md")
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            logger.warning("Persona file missing: WEEKDAYS.md")
            return {}
        except Exception as exc:
            logger.warning("WEEKDAYS.md read error: {e}", e=exc)
            return {}

        directives: dict[str, str] = {}
        sections = ("\n" + content).split("\n## ")
        for section in sections[1:]:
            lines = section.strip().split("\n", 1)
            if len(lines) >= 2:
                day = lines[0].strip()
                text = " ".join(lines[1].strip().split("\n")).strip()
                if day and text:
                    directives[day] = text
        logger.info("WEEKDAYS.md loaded: {n} directives", n=len(directives))
        return directives

    def _parse_composites(self) -> dict[str, str]:
        """Parse COMPOSITES.md en un dict {paire: directive}."""
        path = os.path.join(self._dir, "COMPOSITES.md")
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            logger.warning("Persona file missing: COMPOSITES.md")
            return {}
        except Exception as exc:
            logger.warning("COMPOSITES.md read error: {e}", e=exc)
            return {}

        directives: dict[str, str] = {}
        sections = ("\n" + content).split("\n## ")
        for section in sections[1:]:
            lines = section.strip().split("\n", 1)
            if len(lines) >= 2:
                key = lines[0].strip()
                text = " ".join(lines[1].strip().split("\n")).strip()
                if key and text:
                    directives[key] = text
        logger.info("COMPOSITES.md loaded: {n} directives", n=len(directives))
        return directives

    def _parse_secondaries(self) -> dict[str, str]:
        """Parse SECONDARIES.md en un dict {key: directive}."""
        path = os.path.join(self._dir, "SECONDARIES.md")
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            logger.warning("Persona file missing: SECONDARIES.md")
            return {}
        except Exception as exc:
            logger.warning("SECONDARIES.md read error: {e}", e=exc)
            return {}

        directives: dict[str, str] = {}
        sections = ("\n" + content).split("\n## ")
        for section in sections[1:]:
            lines = section.strip().split("\n", 1)
            if len(lines) >= 2:
                key = lines[0].strip()
                text = " ".join(lines[1].strip().split("\n")).strip()
                if key and text:
                    directives[key] = text
        logger.info("SECONDARIES.md loaded: {n} directives", n=len(directives))
        return directives

    @property
    def secondary_directives(self) -> dict[str, str]:
        """Directives comportementales pour les émotions secondaires."""
        return self._secondary_directives

    @property
    def composite_directives(self) -> dict[str, str]:
        """Directives comportementales pour les émotions composites."""
        return self._composite_directives

    @property
    def emotion_directives(self) -> dict[str, str]:
        """Directives comportementales par état émotionnel."""
        return self._emotion_directives

    @property
    def weekday_directives(self) -> dict[str, str]:
        """Directives comportementales par jour de la semaine."""
        return self._weekday_directives

    def build_prompt_block(self) -> str:
        """Retourne les blocs SOUL → IDENTITY → VOICE concaténés."""
        from datetime import datetime
        today = datetime.now().strftime("%A %d %B %Y")
        blocks = [v.replace("{current_date}", today) for v in self._blocks.values() if v]
        return "\n\n".join(blocks)
