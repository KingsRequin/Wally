# bot/core/memory.py
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Optional

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.openai_client import OpenAIClient

_SUMMARIZE_SYSTEM = (
    "Résume ce contexte de conversation de façon concise en conservant les informations "
    "importantes : qui parle, les sujets abordés, les faits clés. Sois bref."
)

_CHUNK_SIZE = 10  # messages per summarization chunk


class MemoryService:
    def __init__(self, config: "Config"):
        self._config = config
        self._mem0: Optional[object] = None
        self._mem0_init_attempted: bool = False
        # Sliding context window: channel_id → list[{author, content, timestamp}]
        self._context_windows: dict[str, list[dict]] = {}
        # Prelude buffer: channel_id → list[{author, content, timestamp}]
        self._prelude_windows: dict[str, list[dict]] = {}
        self._openai: Optional["OpenAIClient"] = None

    def set_openai_client(self, client: "OpenAIClient") -> None:
        self._openai = client

    # ── mem0 long-term memory ─────────────────────────────────────────────────

    def _init_mem0(self) -> None:
        if self._mem0_init_attempted:
            return
        self._mem0_init_attempted = True
        try:
            from mem0 import Memory

            self._mem0 = Memory.from_config(
                {
                    "vector_store": {
                        "provider": "qdrant",
                        "config": {
                            "url": os.getenv("QDRANT_URL", "http://localhost:6333"),
                            "collection_name": "wally_memory",
                        },
                    },
                    "llm": {
                        "provider": "openai",
                        "config": {
                            "model": self._config.openai.secondary_model,
                            "temperature": 0.1,
                        },
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {
                            "model": "text-embedding-3-small",
                        },
                    },
                }
            )
            logger.info("mem0 initialized with local Qdrant")
        except Exception as exc:
            logger.warning("mem0 init failed (Qdrant unavailable?): {e}", e=exc)
            self._mem0 = None

    def _user_id(self, platform: str, user_id: str) -> str:
        return f"{platform}:{user_id}"

    async def add(self, platform: str, user_id: str, content: str) -> None:
        self._init_mem0()
        if self._mem0 is None:
            return
        try:
            uid = self._user_id(platform, user_id)
            await asyncio.to_thread(self._mem0.add, content, user_id=uid)
        except Exception as exc:
            logger.warning("mem0 add failed: {e}", e=exc)

    async def reset_all(self) -> None:
        """Clear all context windows and all mem0 long-term memories."""
        self._context_windows.clear()
        self._prelude_windows.clear()
        logger.info("Memory context windows cleared")
        if self._mem0 is not None:
            try:
                await asyncio.to_thread(self._mem0.reset)
                logger.info("mem0 long-term memory reset")
            except Exception as exc:
                logger.warning("mem0 reset failed: {e}", e=exc)

    async def search(self, platform: str, user_id: str, query: str) -> str:
        self._init_mem0()
        if self._mem0 is None:
            return ""
        try:
            uid = self._user_id(platform, user_id)
            results = await asyncio.to_thread(
                self._mem0.search, query, user_id=uid, limit=5
            )
            # mem0 >=0.1.40 returns {"results": [...]} dict instead of a list
            if isinstance(results, dict):
                results = results.get("results", [])
            if not results:
                return ""
            return "\n".join(
                r.get("memory", "") for r in results if r.get("memory")
            )
        except Exception as exc:
            logger.warning("mem0 search failed: {e}", e=exc)
            return ""

    # ── Sliding context window ────────────────────────────────────────────────

    def append_message(self, channel_id: str, author: str, content: str) -> None:
        window = self._context_windows.setdefault(channel_id, [])
        window.append(
            {"author": author, "content": content, "timestamp": time.time()}
        )
        max_size = self._config.bot.context_window_size
        if len(window) > max_size:
            self._context_windows[channel_id] = window[-max_size:]

    def get_context(self, channel_id: str) -> list[dict]:
        return list(self._context_windows.get(channel_id, []))

    def append_prelude(self, channel_id: str, author: str, content: str) -> None:
        window = self._prelude_windows.setdefault(channel_id, [])
        window.append(
            {"author": author, "content": content, "timestamp": time.time()}
        )
        max_size = self._config.bot.prelude_window_size
        if len(window) > max_size:
            self._prelude_windows[channel_id] = window[-max_size:]

    def get_prelude(self, channel_id: str) -> list[dict]:
        return list(self._prelude_windows.get(channel_id, []))

    def get_all_contexts(self) -> list[dict]:
        """Return all messages from all channels, sorted by timestamp."""
        all_messages: list[dict] = []
        for msgs in self._context_windows.values():
            all_messages.extend(msgs)
        all_messages.sort(key=lambda m: m["timestamp"])
        return all_messages

    async def get_context_summarized_if_needed(
        self, channel_id: str
    ) -> list[dict]:
        messages = self.get_context(channel_id)
        if not messages or self._openai is None:
            return messages

        # Guard: a single summary entry is already compact — never re-summarize it.
        if len(messages) == 1 and messages[0].get("author") == "RÉSUMÉ":
            return messages

        # Rough token estimate: 4 chars ≈ 1 token
        total_chars = sum(len(m["content"]) for m in messages)
        threshold = self._config.bot.context_token_threshold
        if total_chars / 4 < threshold:
            return messages

        logger.info(
            "Context window for {ch} exceeds token threshold, summarizing",
            ch=channel_id,
        )
        # Record the timestamp boundary before the await so we can recover any
        # messages that arrive on this channel while summarization is in progress.
        snapshot_ts = messages[-1]["timestamp"]
        summary = await self._summarize_messages(messages)
        summary_entry = {
            "author": "RÉSUMÉ",
            "content": summary,
            "timestamp": time.time(),
        }
        # Preserve messages appended to the window during the await.
        current = self._context_windows.get(channel_id, [])
        added_during = [m for m in current if m["timestamp"] > snapshot_ts]
        self._context_windows[channel_id] = [summary_entry] + added_during
        return [summary_entry]

    async def _summarize_messages(self, messages: list[dict]) -> str:
        """Multi-pass sliding summarization."""
        summaries: list[str] = []
        for i in range(0, len(messages), _CHUNK_SIZE):
            chunk = messages[i : i + _CHUNK_SIZE]
            chunk_text = "\n".join(
                f"[{m['author']}]: {m['content']}" for m in chunk
            )
            summary = await self._openai.complete_secondary(
                _SUMMARIZE_SYSTEM,
                [{"role": "user", "content": chunk_text}],
                purpose="context_summary",
            )
            summaries.append(summary)

        if len(summaries) == 1:
            return summaries[0]

        combined = "\n---\n".join(summaries)
        return await self._openai.complete_secondary(
            _SUMMARIZE_SYSTEM,
            [{"role": "user", "content": combined}],
            purpose="context_summary_final",
        )
