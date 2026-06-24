from __future__ import annotations

import asyncio
import difflib
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

OWNER_DISCORD_ID = "610550333042589752"

# Dossiers ignorés lors de la recherche de fichiers candidats (suggestions).
_SKIP_DIRS = {".git", "__pycache__", "data", "logs", ".venv", "node_modules", ".pytest_cache"}

_FIX_SYSTEM = (
    "Tu es un assistant de correction de code Python. "
    "Génère UNIQUEMENT un diff unifié (format git diff) pour corriger le problème décrit. "
    "Le diff doit être applicable via `git apply`. "
    "Aucune explication, seulement le diff."
)


@dataclass
class FixRequest:
    requester_discord_id: str
    file_path: str       # relative to repo root, e.g. "bot/core/emotion.py"
    description: str


class SelfFix:
    def __init__(self, llm, bridge, bot, repo_root: str = "/app") -> None:
        self._llm = llm
        self._bridge = bridge
        self._bot = bot
        self._repo_root = Path(repo_root)

    def resolve(self, file_path: str) -> tuple[Path | None, str | None]:
        """Validation synchrone du chemin.

        Retourne ``(abs_path, None)`` si le fichier existe dans le dépôt,
        sinon ``(None, message d'erreur)`` — avec suggestions de fichiers proches
        pour que le LLM puisse se corriger plutôt que d'échouer en silence.
        """
        if not file_path or not file_path.strip():
            return None, "Aucun fichier précisé."

        root = self._repo_root.resolve()
        abs_path = (root / file_path).resolve()

        # Anti path-traversal : refuse tout chemin hors du dépôt.
        try:
            abs_path.relative_to(root)
        except ValueError:
            return None, f"Chemin hors du dépôt refusé : `{file_path}`."

        if abs_path.is_file():
            return abs_path, None

        suggestions = self._suggest(file_path)
        hint = f" Tu voulais peut-être : {', '.join(f'`{s}`' for s in suggestions)} ?" if suggestions else ""
        return None, f"Le fichier `{file_path}` n'existe pas dans le dépôt.{hint}"

    def _suggest(self, file_path: str, limit: int = 3) -> list[str]:
        """Fichiers .py du dépôt les plus proches du chemin demandé."""
        root = self._repo_root.resolve()
        name = Path(file_path).name
        candidates: list[str] = []
        for p in root.rglob("*.py"):
            rel = p.relative_to(root)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            candidates.append(str(rel))

        scored = sorted(
            candidates,
            key=lambda c: difflib.SequenceMatcher(None, c, file_path).ratio(),
            reverse=True,
        )
        # Priorité aux fichiers portant exactement le même nom de base.
        exact = [c for c in scored if Path(c).name == name]
        ordered = exact + [c for c in scored if c not in exact]
        return ordered[:limit]

    async def fix(self, request: FixRequest) -> None:
        if request.requester_discord_id != OWNER_DISCORD_ID:
            logger.warning("SelfFix refusé: {} n'est pas owner", request.requester_discord_id)
            return
        try:
            await self._run(request)
        except Exception as e:  # noqa: BLE001 — on ne doit JAMAIS échouer en silence
            logger.exception("SelfFix a échoué pour {}", request.file_path)
            await self._notify(f"❌ La self-modification de `{request.file_path}` a échoué : {e}")

    async def _run(self, request: FixRequest) -> None:
        abs_path, err = self.resolve(request.file_path)
        if err:
            logger.warning("SelfFix: {}", err)
            await self._notify(f"❌ {err}")
            return
        assert abs_path is not None

        original = abs_path.read_text(encoding="utf-8")
        user_msg = (
            f"Fichier : {request.file_path}\n\n"
            f"```python\n{original[:6000]}\n```\n\n"
            f"Problème : {request.description}"
        )
        diff = await self._llm.complete(_FIX_SYSTEM, [{"role": "user", "content": user_msg}])

        if not diff or not diff.strip():
            await self._notify(
                f"❌ Le modèle n'a produit aucun diff pour `{request.file_path}` — rien à appliquer."
            )
            return

        owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
        dm = await owner.create_dm()
        preview = diff[:1800]
        msg = await dm.send(
            f"🔧 **Correction proposée — `{request.file_path}`**\n"
            f"```diff\n{preview}\n```\n"
            "✅ appliquer (rebuild + restart ~2min) · ❌ annuler · _(timeout 1h)_"
        )
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        try:
            emoji = await self._await_reaction(msg, timeout=3600)
        except asyncio.TimeoutError:
            await dm.send("⏱ Timeout — correction annulée.")
            return

        if emoji == "✅":
            await dm.send("⚙️ Application du patch + rebuild...")
            try:
                await self._bridge.git_apply(diff)
                await self._bridge.docker_rebuild("wally")
            except Exception as e:
                await dm.send(f"❌ Erreur bridge: {e}")
        else:
            await dm.send("❌ Correction annulée.")

    async def _notify(self, text: str) -> None:
        """Envoie un message au créateur en DM. Best-effort : ne propage jamais."""
        try:
            owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
            dm = await owner.create_dm()
            await dm.send(text)
        except Exception:  # noqa: BLE001
            logger.exception("SelfFix: impossible de notifier le créateur en DM")

    async def _await_reaction(self, msg, timeout: float) -> str:
        def check(reaction, user):
            return (
                str(user.id) == OWNER_DISCORD_ID
                and str(reaction.emoji) in ("✅", "❌")
                and reaction.message.id == msg.id
            )
        reaction, _ = await self._bot.wait_for("reaction_add", check=check, timeout=timeout)
        return str(reaction.emoji)
