from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from loguru import logger

from bot.intelligence.prompts import load_prompt
from bot.intelligence.identity import render_identity
from bot.intelligence.memory.vocab import PREDICATES, render_triplet

if TYPE_CHECKING:
    from bot.config import Config
    from bot.intelligence.memory.service import MemoryService
    from bot.core.llm import BaseLLMClient
    from bot.intelligence.memory.ingest import MemoryIngest

_MIN_LENGTH = 15

_DISCORD_SYNTAX_RE = re.compile(
    r"<@[!&]?\d+>|<#\d+>|<:\w+:\d+>|<a:\w+:\d+>|<t:\d+(?::[tTdDfFR])?>"
)

# URLs that are never memorable (GIF/media/image hosting)
_MEDIA_URL_RE = re.compile(
    r"https?://(?:"
    r"tenor\.com/view/|"
    r"giphy\.com/gifs/|"
    r"media\.giphy\.com/|"
    r"media[0-9]*\.giphy\.com/|"
    r"cdn\.discordapp\.com/attachments/|"
    r"media\.discordapp\.net/|"
    r"i\.imgur\.com/|"
    r"imgur\.com/(?:a/|gallery/)?|"
    r"gfycat\.com/|"
    r"streamable\.com/|"
    r"clips\.twitch\.tv/|"
    r"youtube\.com/shorts/|"
    r"vm\.tiktok\.com/|"
    r"tiktok\.com/"
    r")",
    re.IGNORECASE,
)

# Generic URL pattern for "URL-only" detection
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

_INTERJECTION_PATTERNS = [
    re.compile(r"^lo+l+$"),
    re.compile(r"^md(r+)$"),
    re.compile(r"^ptd(r+)$"),
    re.compile(r"^x+d+$"),
    re.compile(r"^ha(ha)+$"),
    re.compile(r"^o+k+$"),
    re.compile(r"^gg+$"),
    re.compile(r"^wp+$"),
    re.compile(r"^a+h+$"),
    re.compile(r"^o+h+$"),
    re.compile(r"^ri+p+$"),
    re.compile(r"^ou+i+$"),
    re.compile(r"^no+n+$"),
    re.compile(r"^\^{2,}$"),
    re.compile(r"^\+1$"),
    # English / franglais
    re.compile(r"^su+re+$"),
    re.compile(r"^ye+a+h+$"),
    re.compile(r"^ye+p+$"),
    re.compile(r"^no+pe+$"),
    re.compile(r"^na+h+$"),
    re.compile(r"^l+m+a+o+$"),
    re.compile(r"^l+m+f+a+o+$"),
    re.compile(r"^ro+fl+$"),
    re.compile(r"^bru+h+$"),
    re.compile(r"^da+mn+$"),
    re.compile(r"^ni+ce+$"),
    re.compile(r"^co+l+$"),
    re.compile(r"^tru+e+$"),
    re.compile(r"^fr+$"),
    re.compile(r"^idk$"),
    re.compile(r"^ikr$"),
    re.compile(r"^ngl$"),
    re.compile(r"^tbh$"),
    re.compile(r"^o+mg+$"),
    re.compile(r"^wo+w+$"),
    re.compile(r"^we+lp+$"),
    re.compile(r"^yi+ke+s+$"),
    re.compile(r"^she+sh+$"),
    re.compile(r"^be+t+$"),
]


# ── Péremption des faits éphémères (TTL) ────────────────────────────────────────
# Le LLM classe chaque fait par durée de vie ; le code calcule la date absolue
# (déterministe). Garde-fou heuristique : un marqueur temporel explicite force un
# TTL court même si le LLM a répondu "durable".
_TTL_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("hours", ("ce soir", "cet aprem", "cet après-midi", "cet apres-midi",
               "ce matin", "ce midi", "tout à l'heure", "tout a l'heure",
               "tantôt", "tantot", "aujourd'hui", "aujourdhui",
               "tonight", "this evening", "this morning", "this afternoon")),
    ("days", ("demain", "après-demain", "apres-demain", "tomorrow")),
    ("week", ("ce week-end", "ce weekend", "cette semaine", "this week",
              "this weekend", "le week-end")),
]

# Durée ajoutée à la date d'énonciation selon le TTL.
_TTL_DELTAS: dict[str, timedelta] = {
    "day":  timedelta(days=1),
    "days": timedelta(days=3),
    "week": timedelta(days=7),
}


def _compute_expiry(ttl: str | None, fact_text: str, now: datetime) -> "datetime | None":
    """Date de péremption (UTC naïf) d'un fait éphémère, ou None si durable.

    `ttl` = classe de durée de vie estimée par le LLM (durable/hours/day/days/
    week). Garde-fou : un marqueur temporel explicite dans le texte force le TTL
    correspondant même si le LLM a répondu 'durable'.
    """
    text = (fact_text or "").lower()
    for forced, markers in _TTL_MARKERS:
        if any(m in text for m in markers):
            ttl = forced
            break
    if not ttl or ttl == "durable":
        return None
    if ttl == "hours":
        # Fin de la journée d'énonciation, au moins +6h.
        end_of_day = now.replace(hour=23, minute=59, second=0, microsecond=0)
        return max(end_of_day, now + timedelta(hours=6))
    return now + _TTL_DELTAS.get(ttl, timedelta(days=3))


def _is_emoji_only(text: str) -> bool:
    for ch in text:
        if ch.isspace():
            continue
        if unicodedata.category(ch) not in ("So", "Sk", "Mn", "Cf"):
            return False
    return True


def _is_interjection(word: str) -> bool:
    return any(p.match(word) for p in _INTERJECTION_PATTERNS)


def _is_media_url_only(text: str) -> bool:
    """Return True if the message is just media/GIF URLs (with optional filler)."""
    stripped = text.strip()
    # Remove all URLs from the text
    without_urls = _URL_RE.sub("", stripped).strip()
    # If nothing meaningful remains (empty or just punctuation/emoji/interjections)
    if not without_urls or len(without_urls) < _MIN_LENGTH:
        # Only reject if at least one URL is a known media host
        if _MEDIA_URL_RE.search(stripped):
            return True
        # Pure URL-only messages (single URL, no text) are also not memorable
        if not without_urls and _URL_RE.search(stripped):
            return True
    return False


def _is_memorable(text: str) -> bool:
    text = text.strip()
    if len(text) < _MIN_LENGTH:
        return False
    if _is_emoji_only(text):
        return False
    if _is_media_url_only(text):
        return False
    words = text.lower().split()
    if not words:
        return False
    if all(_is_interjection(w) for w in words):
        return False
    return True


# ── Constants & schema ────────────────────────────────────────────────────────

_FACT_EXTRACTION_SYSTEM = load_prompt(
    "fact_extraction_system",
    fallback=(
        "Tu es le module d'extraction de faits de {{BOT_NAME}}. "
        "Extrais les faits durables par participant. Format JSON."
    ),
    render=False,
)

FACT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "target_user_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "facts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "subject": {"type": "string"},
                                "predicate": {
                                    "type": "string",
                                    "enum": sorted(PREDICATES),
                                },
                                "object": {"type": "string"},
                                "category": {
                                    "type": "string",
                                    "enum": ["FAIT", "PREF", "LANG", "REL"],
                                },
                                "importance": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "text": {"type": "string"},
                                "ttl": {
                                    "type": "string",
                                    "enum": ["durable", "hours", "day", "days", "week"],
                                },
                            },
                            "required": [
                                "subject",
                                "predicate",
                                "object",
                                "category",
                                "importance",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["target", "target_user_id", "facts"],
                "additionalProperties": False,
            },
        },
        "aliases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nickname": {"type": "string"},
                    "resolved_to": {"type": "string"},
                    "resolved_user_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "confidence": {"type": "number"},
                },
                "required": [
                    "nickname",
                    "resolved_to",
                    "resolved_user_id",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["facts", "aliases"],
    "additionalProperties": False,
}

_FLUSH_THRESHOLD = 5
_SAFETY_CAP = 15
_PARTIAL_KEEP = 5
_MAX_AGE_SECONDS = 600
_REPLY_PAUSE_SECONDS = 180

# ── Rappel de ce qu'on sait déjà ──────────────────────────────────────────────
#
# Le tampon est vidé à chaque flush : les mêmes messages ne sont jamais relus.
# Mais l'extraction repart de zéro tous les 5 messages, sans jamais voir les
# faits déjà en base — d'où le même fait ré-extrait, reformulé, à chaque
# passage. On remonte donc les souvenirs de chaque participant qui recoupent la
# conversation en cours, et on demande de ne pas les répéter.
#
# Par pertinence (FTS5/BM25 sur le texte de la conversation), pas en vrac :
# injecter les 194 souvenirs de quelqu'un toutes les 5 messages coûterait des
# milliers de tokens pour rien. Seuls ceux que la conversation risque de faire
# ré-extraire sont utiles.
_KNOWN_FACTS_PER_USER = 8
_KNOWN_FACTS_TOTAL = 40


# ── FactExtractor ─────────────────────────────────────────────────────────────


class FactExtractor:
    """Accumulates channel messages into per-channel buffers and periodically
    flushes them to extract durable facts via LLM structured output."""

    def __init__(
        self,
        config: "Config",
        memory: "MemoryService",
        llm: "BaseLLMClient",
        db=None,
        ingest: "MemoryIngest | None" = None,
    ) -> None:
        self._config = config
        self._memory = memory
        self._openai = llm
        self._db = db
        self._ingest = ingest
        # channel_id → buffer dict
        self._buffers: dict[str, dict] = {}
        # Strong refs for fire-and-forget tasks
        self._bg_tasks: set[asyncio.Task] = set()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _fire(self, coro) -> asyncio.Task:
        """Fire-and-forget: schedule coro as a tracked background task."""
        t = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        return t

    def _get_buffer(self, channel_id: str) -> dict:
        """Return (creating if needed) the buffer dict for a channel."""
        if channel_id not in self._buffers:
            self._buffers[channel_id] = {
                "messages": [],
                "reply_chain_active": False,
                "last_activity": time.time(),
                "flush_task": None,
                "flush_lock": asyncio.Lock(),
                "platform": "discord",
                "origin": None,
            }
        return self._buffers[channel_id]

    # ── Public API ────────────────────────────────────────────────────────────

    def record_message(
        self,
        channel_id: str,
        platform: str,
        user_id: str,
        display_name: str,
        content: str,
        is_reply: bool = False,
        origin: "str | None" = None,
    ) -> None:
        """Accumulate a message and trigger a flush when thresholds are met.

        This is a synchronous method that schedules async work; it can be
        called from any synchronous context inside the event loop.

        `origin` = lieu précis lisible du canal (ex. « Discord #discussions »,
        « Discord MP », « Twitch/azrael_ttv ») ; attaché aux faits extraits.
        """
        # Strip Discord-specific syntax before storing (mentions, channels, emojis, timestamps)
        content = _DISCORD_SYNTAX_RE.sub("", content).strip()
        if not content:
            return

        buf = self._get_buffer(channel_id)
        buf["last_activity"] = time.time()
        buf["platform"] = platform
        if origin:
            buf["origin"] = origin

        if is_reply:
            buf["reply_chain_active"] = True

        if not _is_memorable(content):
            return

        ts = time.time()
        msg = {
            "user_id": user_id,
            "display_name": display_name,
            "content": content,
            "timestamp": ts,
        }
        buf["messages"].append(msg)

        # Persist to DB for crash recovery
        if self._db is not None:
            self._fire(
                self._db.insert_session_message(
                    channel_id, platform, user_id, display_name, content, ts
                )
            )

        count = len(buf["messages"])

        # Safety cap: partial flush to avoid unbounded growth
        if count >= _SAFETY_CAP:
            self._fire(self._do_flush(channel_id, partial=True))
        elif count >= _FLUSH_THRESHOLD and not buf["reply_chain_active"]:
            # Normal threshold reached and no active reply chain → full flush
            self._fire(self._do_flush(channel_id, partial=False))
        else:
            # Schedule a delayed flush (timeout-based)
            self._schedule_flush(channel_id)

    def _schedule_flush(self, channel_id: str) -> None:
        """Cancel any pending flush task and schedule a new one."""
        buf = self._get_buffer(channel_id)
        old_task: Optional[asyncio.Task] = buf.get("flush_task")
        if old_task is not None and not old_task.done():
            old_task.cancel()

        delay = (
            _REPLY_PAUSE_SECONDS
            if buf["reply_chain_active"]
            else _MAX_AGE_SECONDS
        )
        task = self._fire(self._delayed_flush(channel_id, delay))
        buf["flush_task"] = task

    async def _delayed_flush(self, channel_id: str, delay: float) -> None:
        """Sleep then flush if the buffer is still non-empty."""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        buf = self._buffers.get(channel_id)
        if buf and buf["messages"]:
            await self._do_flush(channel_id, partial=False)

    async def _do_flush(self, channel_id: str, partial: bool = False) -> None:
        """Flush a channel buffer: extract facts and clean up DB entries."""
        buf = self._buffers.get(channel_id)
        if not buf:
            return

        lock: asyncio.Lock = buf["flush_lock"]
        if lock.locked():
            return  # Another flush is already in progress

        async with lock:
            # Re-check after acquiring — another task may have flushed already
            buf = self._buffers.get(channel_id)
            if not buf or not buf["messages"]:
                return

            all_messages = list(buf["messages"])
            platform = buf.get("platform", "discord")
            origin = buf.get("origin")

            if partial:
                # Flush first (_SAFETY_CAP - _PARTIAL_KEEP) messages, keep last _PARTIAL_KEEP
                flush_count = _SAFETY_CAP - _PARTIAL_KEEP
                to_flush = all_messages[:flush_count]
                to_keep = all_messages[flush_count:]
                buf["messages"] = to_keep  # cleared before any await — new msgs go here safely
                cutoff_ts = to_flush[-1]["timestamp"] if to_flush else 0.0
            else:
                to_flush = all_messages
                buf["messages"] = []       # cleared before any await — new msgs go here safely
                buf["reply_chain_active"] = False
                # Use last message's timestamp so messages appended during the LLM await
                # (which land in the now-empty buf["messages"]) are NOT deleted by DB cleanup.
                cutoff_ts = to_flush[-1]["timestamp"] if to_flush else 0.0

            if not to_flush:
                return

            # Extract facts from flushed messages
            try:
                await self._extract_facts(to_flush, platform, channel_id, origin=origin)
            except Exception as exc:
                logger.warning(
                    "FactExtractor._extract_facts failed for {ch}: {e!r}",
                    ch=channel_id,
                    e=exc,
                )

            # Clean up DB — use cutoff_ts for both partial and full flush so that
            # messages appended to buf["messages"] during the LLM await are not deleted.
            if self._db is not None and cutoff_ts is not None:
                try:
                    await self._db.delete_session_messages_before(channel_id, cutoff_ts)
                except Exception as exc:
                    logger.warning(
                        "FactExtractor DB cleanup failed for {ch}: {e!r}",
                        ch=channel_id,
                        e=exc,
                    )

    async def _store_fact(
        self,
        platform: str,
        raw_id: str,
        fact_item: dict,
        fact_text: str,
        category: str,
        display: str,
        origin: "str | None" = None,
        expires_at: "datetime | None" = None,
    ) -> bool:
        """Persist one extracted fact, routing through S-P-O reconciliation when
        possible, falling back to verbatim `memory.add()` otherwise.

        Reconciliation (dedup of paraphrases) requires: a wired `MemoryIngest`,
        and a `predicate` present and within the closed vocabulary. Any miss or
        exception falls back to `memory.add()` so a fact is NEVER lost.

        Returns True if the fact was stored (or confirmed), False on hard failure.
        """
        predicate = (fact_item.get("predicate") or "").strip()
        subject = (fact_item.get("subject") or "").strip()
        object_ = (fact_item.get("object") or "").strip()
        try:
            importance = float(fact_item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5

        _cl = getattr(self, "conv_log", None)
        if _cl is not None:
            _cl.log(
                "facts", platform, "fact_stored",
                user=raw_id, display=display, category=category,
                subject=subject, predicate=predicate, object=object_,
                text=(fact_text or "")[:300], importance=importance,
            )

        can_reconcile = (
            self._ingest is not None
            and predicate in PREDICATES
            and subject
            and object_
        )
        if can_reconcile:
            try:
                from bot.intelligence.memory.ingest import _Candidate

                prefixed_uid = self._memory._user_id(platform, raw_id)
                cand = _Candidate(
                    subject=subject,
                    predicate=predicate,
                    object=object_,
                    category=category,
                    confidence_source="explicit",
                    importance=importance,
                    origin=origin,
                    expires_at=expires_at,
                )
                await self._ingest.reconcile_candidate(prefixed_uid, cand)
                return True
            except Exception as exc:
                logger.warning(
                    "reconcile_candidate failed for {p}:{u}, falling back to add: {e!r}",
                    p=platform, u=raw_id, e=exc,
                )

        # Fallback : add verbatim (dedup texte normalisé interne). Ne perd jamais un fait.
        try:
            await self._memory.add(
                platform, raw_id, fact_text, category=category, username=display,
                origin=origin, expires_at=expires_at,
            )
            return True
        except Exception as exc:
            logger.warning(
                "memory.add fallback failed for {p}:{u}: {e!r}",
                p=platform, u=raw_id, e=exc,
            )
            return False

    async def _known_facts_hint(
        self, platform: str, participants: dict, conversation_text: str
    ) -> str:
        """Souvenirs déjà en base que la conversation risque de faire ré-extraire.

        Un appel FTS5 par participant, la conversation servant de requête : on ne
        remonte que ce qui recoupe ce qui vient d'être dit. Chaîne vide si on ne
        sait encore rien de personne — un bloc vide n'apprendrait rien au modèle
        et lui coûterait des tokens.
        """
        store = getattr(self._memory, "fact_store", None)
        if store is None or not participants:
            return ""

        lines: list[str] = []
        for uid, name in participants.items():
            if len(lines) >= _KNOWN_FACTS_TOTAL:
                break
            try:
                prefixed = self._memory._user_id(platform, uid)
                hits = await store.search_fts(
                    prefixed, conversation_text, limit=_KNOWN_FACTS_PER_USER
                )
            except Exception as exc:  # noqa: BLE001 — le rappel est un bonus
                logger.warning(
                    "FactExtractor: rappel des faits connus échoué pour {u}: {e!r}",
                    u=uid, e=exc,
                )
                continue
            for fact, _score in hits[: _KNOWN_FACTS_TOTAL - len(lines)]:
                lines.append(f"  - {name} : {fact.content}")

        if not lines:
            return ""
        return (
            "\n\nDéjà en mémoire sur ces personnes (ne les ré-extrais PAS) :\n"
            + "\n".join(lines)
            + "\nCes faits sont DÉJÀ stockés. N'extrais que ce qui est nouveau, "
            "ou ce qui les contredit / les met à jour. Redire autrement ce qui "
            "est ci-dessus crée un doublon."
        )

    @staticmethod
    def _subject_owner(
        subject: str, known_users: list[dict], alias_map: dict[str, str]
    ) -> "str | None":
        """À qui appartient un fait dont le sujet nomme quelqu'un ?

        Le LLM renvoie `target_user_id` et le code le prenait au mot. En prod,
        onze faits « Cluth joue à Valorant », « Cluth utilise un tracker »… se
        sont retrouvés dans la mémoire de KingsRequin — c'est lui qui parlait,
        et le modèle lui a attribué ce qu'il disait des autres. Le triplet, lui,
        disait bien `subject = "Cluth"`.

        Le résultat est ramené au compte CANONIQUE (`user_links`). Sans ça, un
        fait dont le sujet est le pseudo Twitch de quelqu'un — « jubeii1979 joue
        à Darktide », dit par Jubeii lui-même — partirait sur sa fiche Twitch
        alors que toute sa mémoire vit sur sa fiche Discord : on couperait sa
        mémoire en deux au lieu de la rassembler.

        Correspondance exacte sur le pseudo (casse et espaces ignorés) : sans
        certitude on ne touche à rien, une réattribution à tort déplacerait un
        souvenir chez un inconnu. Retourne None si le sujet ne désigne personne
        de connu.
        """
        cible = (subject or "").strip().casefold()
        if not cible:
            return None
        for u in known_users:
            nom = (u.get("username") or "").strip().casefold()
            if nom and nom == cible:
                trouve = u.get("user_id")
                return alias_map.get(trouve, trouve) if trouve else None
        return None

    async def _extract_facts(
        self,
        messages: list[dict],
        platform: str,
        channel_id: str,
        origin: "str | None" = None,
    ) -> int:
        """Call the LLM to extract facts from a batch of messages.

        Returns the number of fact entries stored.
        """
        if not messages:
            return 0

        # Build conversation text
        lines = []
        participants: dict[str, str] = {}  # user_id → display_name
        for m in messages:
            uid = m["user_id"]
            name = m["display_name"]
            participants[uid] = name
            lines.append(f"[{name} ({platform}:{uid})]: {m['content']}")
        conversation_text = "\n".join(lines)

        # Fetch known aliases for hint injection
        known_aliases: list[dict] = []
        if self._db is not None:
            try:
                known_aliases = await self._db.list_aliases()
            except Exception:
                known_aliases = []

        alias_hint = ""
        if known_aliases:
            alias_lines = [
                f"  - \"{a['nickname']}\" → {a['canonical_uid']}"
                for a in known_aliases[:20]
            ]
            alias_hint = "\nAliases connus:\n" + "\n".join(alias_lines)

        # Fetch known memory users so the LLM can resolve mentions of
        # third parties (users talked about but not in the conversation)
        known_users_hint = ""
        # Liste COMPLÈTE (participants inclus) : elle sert aussi à vérifier, plus
        # bas, que le sujet d'un fait désigne bien la personne à qui on l'attribue.
        all_known_users: list[dict] = []
        # {compte secondaire → compte canonique} : deux comptes liés sont la même
        # personne, sa mémoire ne doit pas se scinder entre les deux fiches.
        alias_map: dict[str, str] = {}
        if self._db is not None:
            try:
                alias_map = await self._db.get_alias_map()
            except Exception:
                alias_map = {}
            try:
                all_known_users = [
                    u for u in await self._db.list_memory_users()
                    if not u["user_id"].startswith("unknown:")
                ]
                known_users = [
                    u for u in all_known_users
                    if u["user_id"].split(":", 1)[1] not in participants
                ]
                if known_users:
                    user_lines = [
                        f"  - {u.get('username') or '?'} → {u['user_id']}"
                        for u in known_users[:50]
                    ]
                    known_users_hint = (
                        "\nUtilisateurs connus en mémoire (pour résoudre les mentions de tiers):\n"
                        + "\n".join(user_lines)
                    )
            except Exception:
                known_users_hint = ""

        known_facts_hint = await self._known_facts_hint(
            platform, participants, conversation_text
        )

        user_prompt = (
            f"Participants: {', '.join(f'{n} ({platform}:{uid})' for uid, n in participants.items())}\n"
            f"{alias_hint}{known_users_hint}{known_facts_hint}\n\n"
            f"Conversation:\n{conversation_text}"
        )

        result = await self._openai.complete_structured(
            render_identity(_FACT_EXTRACTION_SYSTEM),
            [{"role": "user", "content": user_prompt}],
            schema=FACT_EXTRACTION_SCHEMA,
            schema_name="fact_extraction",
            purpose="fact_extraction",
        )

        stored_count = 0

        # Process facts
        for entry in result.get("facts", []):
            facts_list = entry.get("facts", [])
            if not facts_list:
                continue

            # Build fact objects (backward-compat: handle both str and dict)
            fact_items = []
            for f in facts_list:
                if isinstance(f, dict):
                    fact_items.append(f)
                else:
                    fact_items.append({"text": str(f), "category": "FAIT"})

            uid = entry.get("target_user_id")
            # Store each fact individually with its own category
            for fi in fact_items:
                category = fi.get("category", "FAIT")
                # Texte lisible : `text` fourni, sinon dérivé du triplet S-P-O.
                fact_text = (fi.get("text") or "").strip()
                if not fact_text:
                    # Même rendu que l'ingest : le prédicat anglais du
                    # vocabulaire fermé ne doit pas fuir dans le texte lu.
                    fact_text = render_triplet(
                        fi.get("subject") or "",
                        fi.get("predicate") or "",
                        fi.get("object") or "",
                    )
                if not fact_text:
                    continue
                # Le sujet du triplet prime sur `target_user_id` quand il nomme
                # quelqu'un de connu : le modèle attribue volontiers à celui qui
                # PARLE ce qu'il dit des autres.
                effective_uid = uid
                owner = self._subject_owner(
                    fi.get("subject") or "", all_known_users, alias_map
                )
                # Comparaison entre canoniques : deux comptes liés sont la même
                # personne, il n'y a rien à déplacer.
                if owner and owner != alias_map.get(uid, uid):
                    logger.info(
                        "FactExtractor: « {t} » réattribué de {a} à {b} (sujet du fait)",
                        t=fact_text[:60], a=uid or "?", b=owner,
                    )
                    effective_uid = owner
                if effective_uid:
                    # Known user: parse platform:user_id
                    if ":" in effective_uid:
                        plat, raw_id = effective_uid.split(":", 1)
                    else:
                        plat, raw_id = platform, effective_uid
                else:
                    # Unknown user: store under unknown:<nickname>
                    plat = "unknown"
                    # `or`, pas le défaut de `.get()` : le schéma autorise
                    # `target: null`, et un défaut ne s'applique qu'à une clé
                    # ABSENTE. `raw_id = None` faisait ensuite lever les deux
                    # branches — quatre faits perdus dans les logs, dont un la
                    # veille de l'audit.
                    # MINUSCULES, comme partout ailleurs sur cette clé : le
                    # nickname est minusculé (l. 823), `reassign_user` cherche
                    # `unknown:{nickname}` et `load_aliases` pose la clé en
                    # minuscules. Écrite en casse d'origine, `unknown:MrMakkx`
                    # n'était donc JAMAIS retrouvée : les faits d'un inconnu
                    # reconnu plus tard ne migraient jamais vers son compte, et
                    # sa mémoire restait coupée en deux. 31 lignes en base.
                    raw_id = (entry.get("target") or "unknown").strip().lower()
                display = participants.get(raw_id, "") if effective_uid else ""
                expires_at = _compute_expiry(
                    fi.get("ttl"), fact_text, datetime.utcnow()
                )
                if await self._store_fact(
                    plat, raw_id, fi, fact_text, category, display,
                    origin=origin, expires_at=expires_at,
                ):
                    stored_count += 1

        # Process aliases
        for alias_entry in result.get("aliases", []):
            confidence = float(alias_entry.get("confidence", 0.0))
            if confidence < 0.8:
                continue

            nickname = alias_entry.get("nickname", "").lower().strip()
            resolved_to = alias_entry.get("resolved_to", "")
            resolved_uid = (alias_entry.get("resolved_user_id") or "").strip()

            if not nickname or not resolved_uid:
                continue

            # L'uid du LLM était pris au mot. Mesuré : 129 alias sur 188 écrits
            # SANS namespace (« 610550333042589752 » au lieu de
            # « discord:610… »). Conséquence : `canonical_uid.split(":", 1)` ne
            # rend qu'une partie pour 69 % des pseudos connus, la branche
            # d'injection des souvenirs de tiers est sautée, et l'uid pointe
            # vers un espace que personne ne lit.
            if ":" not in resolved_uid:
                connu = next(
                    (u["user_id"] for u in all_known_users
                     if u.get("user_id", "").split(":", 1)[-1] == resolved_uid),
                    None,
                )
                if connu is None:
                    logger.warning(
                        "Alias {n} ignoré : identifiant sans namespace ({u})",
                        n=nickname, u=resolved_uid,
                    )
                    continue
                resolved_uid = connu

            try:
                if self._db is not None:
                    await self._db.upsert_alias(
                        nickname=nickname,
                        canonical_uid=resolved_uid,
                        display_name=resolved_to,
                        source="llm",
                        confidence=confidence,
                    )
                self._memory.add_alias(
                    alias_id=f"unknown:{nickname}",
                    canonical_id=resolved_uid,
                )
                self._fire(
                    self._reconcile_orphan_facts(nickname, resolved_uid)
                )
            except Exception as exc:
                logger.warning(
                    "Alias processing failed for {nick}: {e!r}",
                    nick=nickname,
                    e=exc,
                )

        logger.info(
            "FactExtractor: extracted {n} fact entries from {m} messages in {ch}",
            n=stored_count,
            m=len(messages),
            ch=channel_id,
        )
        return stored_count

    async def _reconcile_orphan_facts(
        self, nickname: str, canonical_uid: str
    ) -> None:
        """Rattache les faits appris sous `unknown:<pseudo>` au compte reconnu.

        Passe DÉLIBÉRÉMENT par le fact store et non par `MemoryService` : les
        méthodes du service résolvent les alias (`_user_id` finit par
        `_alias_cache.get(raw, raw)`), et l'alias `unknown:<pseudo>` vient
        d'être posé quelques lignes plus haut par l'appelant. Lire ou effacer
        « les orphelins » via le service désignait donc, en réalité, le compte
        CANONIQUE.

        Ce qu'en faisait l'ancienne version, dans cet ordre : elle relisait
        tous les faits actifs du compte canonique, les recollait en un seul
        blob réinséré sous ce même compte, puis appelait `delete_user_memories`
        — un `DELETE` sec, pas un archivage — sur ce compte. Tout ce que Wally
        savait de la personne était effacé, blob compris, à chaque extraction
        résolvant un alias avec une confiance ≥ 0,8. Et les vrais orphelins, eux,
        n'étaient jamais migrés.

        Ici, un simple déplacement de clé : rien n'est reformulé, rien n'est
        supprimé.
        """
        try:
            store = getattr(self._memory, "fact_store", None)
            if store is None:
                return
            moved = await store.reassign_user(f"unknown:{nickname}", canonical_uid)
            if not moved:
                return
            logger.info(
                "Faits orphelins rattachés : {n} de unknown:{nick} → {uid}",
                n=moved,
                nick=nickname,
                uid=canonical_uid,
            )
        except Exception as exc:
            logger.warning(
                "Orphan fact reconciliation failed for {nick}: {e!r}",
                nick=nickname,
                e=exc,
            )

    async def analyze_channel_messages(
        self,
        messages: list,
        platform: str,
        channel_id: str,
        bot_user_id: int,
    ) -> int:
        """Replacement for SessionManager.analyze_channel_messages.

        Used by /wally scan. Filters bot messages, converts Discord message
        objects to dicts, calls _extract_facts(). Raises ValueError if fewer
        than 2 human messages.
        """
        human_msgs = [m for m in messages if not m.author.bot]

        if len(human_msgs) < 2:
            raise ValueError(
                f"analyze_channel_messages requires at least 2 human messages, "
                f"got {len(human_msgs)}"
            )

        msg_dicts = [
            {
                "user_id": str(m.author.id),
                "display_name": m.author.display_name,
                "content": m.content,
                "timestamp": m.created_at.timestamp(),
            }
            for m in human_msgs
        ]

        return await self._extract_facts(msg_dicts, platform, channel_id)

    async def flush_all(self) -> None:
        """Flush all non-empty buffers — called during shutdown."""
        tasks = []
        for channel_id, buf in list(self._buffers.items()):
            if buf.get("messages"):
                tasks.append(self._do_flush(channel_id, partial=False))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Wait for any fire-and-forget background tasks still in flight
        if self._bg_tasks:
            await asyncio.gather(*list(self._bg_tasks), return_exceptions=True)

    async def restore_buffers(self) -> None:
        """Restore in-memory buffers from DB after a restart."""
        if self._db is None:
            return
        try:
            cutoff = time.time() - _MAX_AGE_SECONDS
            rows = await self._db.get_recent_session_messages(since=cutoff)
            for row in rows:
                channel_id = row["channel_id"]
                buf = self._get_buffer(channel_id)
                buf["platform"] = row["platform"]
                buf["messages"].append(
                    {
                        "user_id": row["user_id"],
                        "display_name": row["display_name"],
                        "content": row["content"],
                        "timestamp": float(row["timestamp"]),
                    }
                )
            if rows:
                logger.info(
                    "FactExtractor: restored {n} messages across {c} channels from DB",
                    n=len(rows),
                    c=len(self._buffers),
                )
                # Trigger flush for any channel that already meets the threshold
                for channel_id, buf in list(self._buffers.items()):
                    count = len(buf["messages"])
                    if count >= _FLUSH_THRESHOLD:
                        self._fire(self._do_flush(channel_id, partial=count >= _SAFETY_CAP))
        except Exception as exc:
            logger.warning("FactExtractor.restore_buffers failed: {e!r}", e=exc)
