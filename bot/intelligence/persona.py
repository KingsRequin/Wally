# bot/core/persona.py
from __future__ import annotations

import os

from loguru import logger


class PersonaService:
    """Charge et expose les fichiers de persona Markdown (SOUL, IDENTITY, VOICE, EMOTIONS)."""

    _FILES = ["SOUL.md", "IDENTITY.md", "VOICE.md", "EXEMPLES.md"]  # ordre canonique ; CAPABILITIES dérivé à part
    _CAPS_FILE = "CAPABILITIES.md"

    def __init__(self, persona_dir: str = "bot/persona", config=None):
        self._dir = persona_dir
        self._config = config
        self._blocks: dict[str, str] = {}
        self._caps_static: str = ""
        self._emotion_directives: dict[str, str] = {}
        self._user_directives: dict[str, str] = {}
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

        # Self-model : la partie narrative stable est chargée à part ; les capacités
        # « à bascule » (vocal…) sont dérivées de la config dans build_prompt_block,
        # pour ne plus fossiliser (cf. self_model.build_self_model).
        caps_path = os.path.join(self._dir, self._CAPS_FILE)
        try:
            with open(caps_path, encoding="utf-8") as f:
                self._caps_static = f.read().strip()
        except FileNotFoundError:
            logger.warning("Persona file missing: {f}", f=self._CAPS_FILE)
            self._caps_static = ""
        except Exception as exc:
            logger.warning("Persona file read error {f}: {e}", f=self._CAPS_FILE, e=exc)
            self._caps_static = ""

        self._emotion_directives = self._parse_emotions()
        self._weekday_directives = self._parse_weekdays()
        self._composite_directives = self._parse_composites()
        self._secondary_directives = self._parse_secondaries()
        self._user_directives = self._parse_users()

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

    def _parse_sections(self, filename: str) -> dict[str, str]:
        """Parse un fichier Markdown en {clé de section: directive}.

        Sections délimitées par « ## clé » ; le préambule éventuel est ignoré.
        """
        path = os.path.join(self._dir, filename)
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            logger.warning("Persona file missing: {f}", f=filename)
            return {}
        except Exception as exc:
            logger.warning("{f} read error: {e}", f=filename, e=exc)
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
        logger.info("{f} loaded: {n} directives", f=filename, n=len(directives))
        return directives

    def _parse_users(self) -> dict[str, str]:
        """Parse USERS.md en un dict {clé utilisateur: directive}."""
        return self._parse_sections("USERS.md")

    @staticmethod
    def user_key(platform: str, user_id: str, username: str = "") -> str:
        """Clé de directive d'un utilisateur.

        Discord → `discord:<id>`. Twitch → `twitch:<pseudo en minuscules>`.

        ⚠️ Sur Twitch la clé est le PSEUDO, alors que le reste du repo (mémoire,
        trust_scores, user_profiles) indexe sur l'ID numérique de
        `payload.chatter.id`. Les deux formes coexistent volontairement : le
        pseudo est l'identifiant lisible dans USERS.md. Conséquence assumée : un
        changement de pseudo Twitch désactive la directive.
        """
        if platform == "twitch":
            return f"twitch:{username.lower()}"
        return f"{platform}:{user_id}"

    def user_directive(self, platform: str, user_id: str, username: str = "") -> str | None:
        """Directive comportementale propre à cet utilisateur, ou None."""
        return self._user_directives.get(self.user_key(platform, user_id, username))

    def is_beloved(self, platform: str, user_id: str, username: str = "") -> bool:
        """True si cet utilisateur a une directive dédiée → il bénéficie des immunités."""
        return self.user_directive(platform, user_id, username) is not None

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

    @property
    def user_directives(self) -> dict[str, str]:
        """Directives comportementales propres à un utilisateur donné."""
        return self._user_directives

    def build_prompt_block(self) -> str:
        """Retourne SOUL → IDENTITY → VOICE → EXEMPLES + le self-model dérivé."""
        from datetime import datetime

        from bot.intelligence.self_model import build_self_model

        today = datetime.now().strftime("%A %d %B %Y")
        blocks = [v.replace("{current_date}", today) for v in self._blocks.values() if v]
        self_model = (
            build_self_model(
                self._caps_static, self._config,
                # Dispo web côté persona : la clé Tavily vit dans l'env (le service
                # WebSearchService n'est pas injecté ici). En prod la lib est
                # installée, donc la présence de la clé suffit comme approximation.
                web_available=bool(__import__("os").environ.get("TAVILY_API_KEY")),
            )
            if self._config is not None
            else self._caps_static
        )
        if self_model:
            blocks.append(self_model.replace("{current_date}", today))
        return "\n\n".join(blocks)
