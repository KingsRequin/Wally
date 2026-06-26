# bot/discord/handlers.py
from __future__ import annotations

import asyncio
import difflib
import json
import random
import re
import time
from collections import deque
from typing import TYPE_CHECKING, Any

import discord
from loguru import logger

from bot.core.llm import FALLBACK_RESPONSE
from bot.intelligence.prompts import assemble_memory_context, load_prompt
from bot.intelligence.self_fix import UpgradeRequest

try:
    from bot.discord.voice.tools import VOICE_TOOLS
except ImportError:
    VOICE_TOOLS = []

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

TIMEOUT_REACTIONS = ["💩", "⛔", "😤", "🙅", "😒"]

# Emojis jugés assez marquants pour être signalés à Wally quand ils sont posés
# sur le message d'un AUTRE membre (les réactions sur ses propres messages sont
# toujours signalées, peu importe l'emoji).
NOTABLE_REACTION_EMOJIS = {
    "😂", "🤣", "❤️", "❤", "🔥", "💀", "😭", "👏", "💯",
    "😱", "🤯", "👀", "😡", "🤮", "💩", "⛔", "😤",
}

_NOTE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_persistent_note",
            "description": (
                "Quand quelqu'un te demande de retenir, noter ou mémoriser quelque chose "
                "qui concerne tout le serveur ou la communauté (un événement, une règle, "
                "une info partagée, un engagement que tu prends), utilise cet outil. "
                "La note sera injectée dans TOUTES tes futures conversations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre court et unique de la note"},
                    "content": {"type": "string", "description": "Contenu de la note"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_persistent_note",
            "description": "Supprimer une note persistante par son titre",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre exact de la note à supprimer"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_user_memory",
            "description": (
                "Quand quelqu'un te demande de retenir, noter ou mémoriser quelque chose "
                "qui le concerne personnellement (préférence, fait biographique, opinion, "
                "habitude, info privée), utilise cet outil. Le souvenir sera associé "
                "uniquement à cet utilisateur."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Fait ou information à retenir sur cet utilisateur, formulé comme une phrase factuelle courte",
                    },
                },
                "required": ["content"],
            },
        },
    },
]

# Outil de self-modification — exposé UNIQUEMENT au créateur (voir l'assemblage des
# tools). Quand le créateur demande explicitement d'ajouter/corriger une capacité,
# Wally route vers le flux Claude Code : une demande d'autorisation 🧠 (✅/❌) est
# envoyée en DM, et sur ✅ Claude Code écrit le code puis le bot se rebuild.
_SELF_MODIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "request_self_modification",
        "description": (
            "Demande une modification de ton PROPRE code source. À utiliser UNIQUEMENT "
            "quand ton créateur te demande explicitement d'ajouter, corriger ou changer "
            "une de tes capacités/fonctionnalités (ex. « ajoute la lecture des réactions "
            "emoji »). Tu décris le BUT recherché — pas le comment, Claude Code écrira le "
            "code. Ton créateur recevra une demande d'autorisation 🧠 en DM (✅/❌) ; sur ✅, "
            "Claude Code modifie le code et le bot redémarre. N'utilise JAMAIS "
            "save_persistent_note pour ça, et ne prétends jamais avoir « envoyé la demande » "
            "sans appeler cet outil. Réservé à ton créateur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": (
                        "Le but de la modification, rédigé PROPREMENT : un BUT clair et "
                        "concret (le comportement voulu, pas les détails techniques), le "
                        "périmètre exact (Discord/Twitch, DM ou serveur), UNE seule "
                        "intention. Ne suppose JAMAIS l'état du code : ne prétends pas "
                        "qu'une fonction ou un fichier 'existe déjà' — Claude vérifiera."
                    ),
                },
            },
            "required": ["goal"],
        },
    },
}


def _resolve_discord_roles(member) -> list[str]:
    """Return member's actual Discord role IDs plus 'everyone' and 'admin' if applicable."""
    roles = ["everyone"]
    roles.extend(str(r.id) for r in member.roles if not r.is_default())
    if member.guild_permissions.administrator:
        roles.append("admin")
    return roles

_REACT_TAG_RE = re.compile(r"^\[react:(.+?)\]\s*")

_LAUGH_WORDS = {"mdr", "lol", "ptdr", "xd", "haha", "😂", "🤣"}
_POSITIVE_WORDS = {"gg", "bravo", "trop bien", "bien joué", "incroyable"}
_NEGATIVE_WORDS = {"merde", "putain", "nul", "chier"}

_LAUGH_EMOJIS = ("😂", "💀")
_POSITIVE_EMOJIS = ("🔥", "👏")
_NEGATIVE_EMOJIS = ("😤", "💀")


def _parse_react_tag(text: str) -> tuple[str | None, str]:
    """Parse un tag [react:emoji] au début du texte.
    Retourne (emoji, texte_nettoyé) ou (None, texte_original).
    """
    m = _REACT_TAG_RE.match(text)
    if m:
        return m.group(1), text[m.end():].strip()
    return None, text


def _author_label(member: discord.Member | discord.User) -> str:
    """Format author label for LLM context: 'display_name (@username)' if different, else just display_name."""
    display = member.display_name
    username = member.name
    if username and username != display:
        return f"{display} (@{username})"
    return display


_USER_MENTION_RE = re.compile(r"<@!?(\d+)>")


def _resolve_mentions(message: "discord.Message", content: str) -> str:
    """Remplace les mentions brutes ``<@id>`` du texte par le pseudo lisible.

    discord.py laisse les mentions sous forme d'identifiant nu dans
    ``message.content`` ; sans cette résolution, le LLM ne voit qu'un nombre
    (« <@792842038332358656> ») au lieu du pseudo de la personne pingée. On
    s'appuie sur ``message.mentions`` (objets déjà résolus), avec repli sur le
    cache du serveur. Lecture seule, ne casse jamais : un id introuvable est
    laissé tel quel."""
    if not content or "<@" not in content:
        return content
    by_id = {m.id: m for m in getattr(message, "mentions", []) or []}
    guild = getattr(message, "guild", None)

    def _sub(match: "re.Match") -> str:
        uid = int(match.group(1))
        member = by_id.get(uid)
        if member is None and guild is not None:
            member = guild.get_member(uid)
        if member is None:
            return match.group(0)
        return f"@{member.display_name}"

    return _USER_MENTION_RE.sub(_sub, content)


# Mentions autorisées sur les messages que Wally envoie : il peut ping des
# membres (<@id>) mais JAMAIS @everyone/@here ni un rôle entier — garde-fou
# contre un ping de masse depuis un bot autonome. replied_user=True conserve
# le ping de l'auteur sur les réponses (comportement discord.py par défaut).
_ALLOWED_MENTIONS = discord.AllowedMentions(
    everyone=False, roles=False, users=True, replied_user=True
)

# Borne le nombre de membres listés dans l'annuaire de mentions pour ne pas
# gonfler le prompt sur un gros serveur.
_MENTION_DIRECTORY_MAX = 80


def _build_mention_directory(
    message: discord.Message, *, max_members: int = _MENTION_DIRECTORY_MAX
) -> str:
    """Annuaire des membres mentionnables du serveur, pour le LLM.

    Permet à Wally de ping correctement n'importe quel membre via la syntaxe
    Discord ``<@id>``. Sans cet annuaire, le LLM ignore les identifiants et
    écrit au mieux un texte « @pseudo » qui ne notifie personne.

    Lecture seule, jamais bloquant : toute erreur (DM, intent members absent,
    cache vide…) renvoie une chaîne vide. L'auteur du message courant est listé
    en premier (le plus susceptible d'être mentionné)."""
    guild = getattr(message, "guild", None)
    if guild is None:
        return ""
    try:
        members = list(getattr(guild, "members", []) or [])
    except Exception:
        return ""

    ordered: list = []
    seen: set[int] = set()

    author = getattr(message, "author", None)
    if (
        author is not None
        and not getattr(author, "bot", False)
        and getattr(author, "id", None) is not None
    ):
        ordered.append(author)
        seen.add(author.id)

    for m in members:
        mid = getattr(m, "id", None)
        if mid is None or mid in seen or getattr(m, "bot", False):
            continue
        ordered.append(m)
        seen.add(mid)

    lines = [f"- {_author_label(m)} → <@{m.id}>" for m in ordered[:max_members]]
    if not lines:
        return ""

    return (
        "\n--- Membres du serveur (pour les mentionner) ---\n"
        "Pour notifier (ping) un membre, insère son identifiant au format "
        "<@id> dans ta réponse (ex : « salut <@123456> »). Le simple texte "
        "« @pseudo » ne notifie personne. N'écris JAMAIS @everyone ni @here.\n"
        + "\n".join(lines)
    )


def _presence_line(bot: "WallyDiscord", user_id: str, display_name: str) -> str:
    """Présence en direct de l'interlocuteur (statut + activité) ou "".

    Lecture seule, serveur principal uniquement. Ne casse jamais une réponse :
    toute erreur renvoie une chaîne vide."""
    svc = getattr(bot, "presence", None)
    if svc is None:
        return ""
    try:
        return svc.describe(user_id, display_name) or ""
    except Exception:
        return ""


def _channel_origin(channel) -> str:
    """Libellé lisible du lieu d'un message Discord, pour la provenance mémoire.

    Ex. « Discord #discussions », « Discord MP ». Sert d'`origin` aux faits."""
    if isinstance(channel, discord.DMChannel):
        return "Discord MP"
    name = getattr(channel, "name", None)
    return f"Discord #{name}" if name else "Discord"


def _format_reactions(
    emoji: str, target_label: str, target_content: str, on_own_message: bool
) -> str:
    """Construit la phrase de contexte décrivant une réaction emoji.

    Retourne uniquement la partie « contenu » (sans le pseudo de l'auteur de la
    réaction) : elle est injectée dans la fenêtre de contexte avec ce pseudo en
    tête, rendu ensuite « [pseudo]: a réagi 😂 à ton message « ... » ».
    """
    snippet = (target_content or "").strip().replace("\n", " ")
    if len(snippet) > 120:
        snippet = snippet[:120].rstrip() + "…"
    if on_own_message:
        head = f"a réagi {emoji} à ton message"
    else:
        head = f"a réagi {emoji} au message de {target_label}"
    return f"{head} « {snippet} »" if snippet else head


async def _reactions_context(bot: "WallyDiscord", payload: discord.RawReactionActionEvent) -> None:
    """Injecte une réaction emoji dans le contexte du canal pour que Wally la perçoive.

    Couvre (A) les réactions sur les messages de Wally et (B) les réactions
    marquantes sur les messages des autres membres. Ne touche pas au tracking
    émotionnel (ReactionTracker), qui reste géré séparément.
    """
    if getattr(bot, "memory", None) is None or bot.user is None:
        return
    if payload.user_id == bot.user.id:
        return
    if payload.guild_id and payload.guild_id in bot.config.discord.ignored_guilds:
        return
    member = payload.member
    if member is not None and member.bot:
        return

    channel = bot.get_channel(payload.channel_id)
    if channel is None:
        # En MP (et pour les canaux non encore mis en cache), get_channel renvoie
        # None : on récupère le canal directement auprès de l'API.
        try:
            channel = await bot.fetch_channel(payload.channel_id)
        except Exception as e:
            logger.debug("Réaction ignorée (fetch_channel échoué) : {e}", e=e)
            return
    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception as e:
        logger.debug("Réaction ignorée (fetch_message échoué) : {e}", e=e)
        return

    on_own_message = message.author.id == bot.user.id
    emoji = str(payload.emoji)

    if not on_own_message:
        # Cas B : on ne signale que les réactions marquantes sur les messages
        # d'autres humains (pas les bots, pas les auto-réactions).
        if message.author.bot:
            return
        if payload.user_id == message.author.id:
            return
        if emoji not in NOTABLE_REACTION_EMOJIS:
            return

    reactor = member or bot.get_user(payload.user_id)
    if reactor is None:
        # En MP, payload.member est None et l'utilisateur peut ne pas être caché.
        try:
            reactor = await bot.fetch_user(payload.user_id)
        except Exception:
            return

    self_name = bot.config.bot.name
    target_label = self_name if on_own_message else _author_label(message.author)
    notice = _format_reactions(emoji, target_label, message.content, on_own_message)
    channel_id = str(payload.channel_id)
    bot.memory.append_message(channel_id, _author_label(reactor), notice, platform="discord")
    logger.debug(
        "Réaction injectée dans le contexte : {who} {notice} (canal {ch})",
        who=_author_label(reactor), notice=notice, ch=channel_id,
    )


def _pick_passive_emoji(text: str, curiosity: float) -> str | None:
    """Choisit un emoji de réaction passive basé sur le contenu du message.
    Retourne None si aucun signal détecté.
    """
    text_lower = text.lower()
    if any(w in text_lower for w in _LAUGH_WORDS):
        return random.choice(_LAUGH_EMOJIS)
    if any(w in text_lower for w in _POSITIVE_WORDS):
        return random.choice(_POSITIVE_EMOJIS)
    if any(w in text_lower for w in _NEGATIVE_WORDS):
        return random.choice(_NEGATIVE_EMOJIS)
    if curiosity >= 0.4 and "?" in text:
        return "🤔"
    return None


# Emoji d'humeur — pour laisser un signe quand Wally choisit de NE PAS répondre :
# il réagit quand même, avec un emoji qui dit son humeur / pourquoi il se tait.
_MOOD_EMOJIS = {
    "anger":     ["😒", "😤", "🙄"],
    "boredom":   ["🥱", "😴", "😑"],
    "sadness":   ["😔", "😞"],
    "curiosity": ["🤔", "👀"],
    "joy":       ["🙂", "😏"],
}


def _mood_emoji(emotion_state: dict[str, float]) -> str:
    """Emoji reflétant l'émotion dominante de Wally. Résout TOUJOURS."""
    dominant, value = max(emotion_state.items(), key=lambda x: x[1], default=("", 0.0))
    if value < 0.15 or dominant not in _MOOD_EMOJIS:
        return random.choice(["😶", "🤷", "💭"])
    return random.choice(_MOOD_EMOJIS[dominant])


def _resolve_emoji(raw: str, bot: "WallyDiscord"):
    """Résout l'emoji renvoyé par le LLM en quelque chose que add_reaction accepte.

    - Emote custom (nom, ":nom:" ou "<:nom:id>") cherchée dans TOUS les serveurs du
      bot (`bot.emojis`, animées incluses) → l'objet discord.Emoji (Nitro-like).
    - Sinon, emoji Unicode standard → la chaîne telle quelle.
    """
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("<") and raw.endswith(">"):
        return raw  # déjà au format custom <:nom:id> / <a:nom:id>
    name = raw.strip(":")
    if name:
        match = discord.utils.get(bot.emojis, name=name)
        if match is not None:
            return match
    return raw


_PASSION_KEYWORDS = {
    "bouchon", "bouchons", "silice", "chariot", "chariots",
    "néon", "néons", "ticket de caisse", "notice pliée",
    "feuille morte", "feuilles mortes",
}
_AVERSION_KEYWORDS = {
    "ananas", "pizza ananas", "ketchup", "croque-monsieur",
    "c'est juste un jeu", "on part sur", "eau tiède",
    "clavier mécanique", "applaudir",
}
_SPONTANEOUS_KEYWORDS = _PASSION_KEYWORDS | _AVERSION_KEYWORDS


def _check_spontaneous_trigger(
    text: str, curiosity: float, anger: float, boredom: float,
) -> str | None:
    """Check if a message should trigger a spontaneous intervention.
    Returns 'passion' (higher prob), 'emotion' (lower prob), or None.
    """
    text_lower = text.lower()
    if any(kw in text_lower for kw in _SPONTANEOUS_KEYWORDS):
        return "passion"
    if curiosity >= 0.6 or anger >= 0.7 or boredom >= 0.7:
        return "emotion"
    return None


# Strong references to fire-and-forget tasks to prevent GC cancellation.
_bg_tasks: set[asyncio.Task] = set()
_spontaneous_cooldowns: dict[str, float] = {}  # channel_id → last spontaneous timestamp
_spam_tracker: dict[tuple[str, str], deque] = {}
_processed_message_ids: dict[int, float] = {}  # message_id → timestamp (dedup Discord replays)
_scrape_cooldowns: dict[str, float] = {}  # channel_id → last auto-scrape timestamp
_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def _fire(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)

    def _done(task: asyncio.Task) -> None:
        _bg_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.opt(exception=task.exception()).error("Tâche de fond échouée")

    t.add_done_callback(_done)
    return t


async def _mirror_pass(
    bot: "WallyDiscord",
    channel_id: str,
    draft: str,
    mem_context: str,
) -> str:
    """Pass secondaire : détecte et corrige patterns répétitifs ou mémoire ratée.

    Retourne le draft inchangé en cas d'erreur ou si aucun défaut n'est trouvé.
    Skippé si la réponse est trop courte (monosyllabes intentionnels).
    """
    if len(draft) < 30:
        return draft

    system = load_prompt("response_mirror_system")
    if not system:
        return draft

    try:
        self_name = bot.config.bot.name
        current_prelude = bot.memory.get_prelude(channel_id)
        recent_wally = [
            m["content"] for m in current_prelude
            if m.get("author") == self_name
        ][-3:]

        parts: list[str] = []
        if recent_wally:
            parts.append(f"Dernières réponses de {self_name} dans ce canal :\n" + "\n---\n".join(recent_wally))
        if mem_context:
            parts.append(f"Souvenirs connus sur l'utilisateur :\n{mem_context}")
        parts.append(f"Réponse à analyser :\n{draft}")

        user_msg = "\n\n".join(parts)

        corrected = await bot.llm_secondary.complete(
            system,
            [{"role": "user", "content": user_msg}],
            purpose="response_mirror",
        )
        corrected = corrected.strip()
        if not corrected or corrected.upper() == "OK" or corrected == FALLBACK_RESPONSE:
            return draft
        return corrected

    except Exception as exc:
        logger.warning("Mirror pass failed: {e}", e=exc)
        return draft


async def _fetch_discord_history(channel, limit: int, exclude_id: int | None = None) -> list[dict]:
    """Fallback cold start : récupère l'historique Discord via API.
    Retourne les messages en ordre chronologique (plus ancien en premier).
    Retourne [] en cas d'erreur (permissions, etc.).
    Note : dicts sans 'timestamp' — utilisés uniquement pour le prompt,
    non stockés dans _prelude_windows."""
    try:
        msgs = []
        async for m in channel.history(limit=limit + (1 if exclude_id is not None else 0)):
            if m.id == exclude_id:
                continue
            # Include Wally's own messages for context awareness
            msgs.append({"author": _author_label(m.author), "content": _resolve_mentions(m, m.content)})
        msgs.reverse()  # Discord renvoie du plus récent au plus ancien
        return msgs[-limit:] if len(msgs) > limit else msgs
    except Exception as e:
        logger.warning("channel.history() fallback failed: {e}", e=e)
        return []


def _is_channel_allowed(config, channel_id: int, guild_id: int | None = None) -> bool:
    """Vérifie si Wally peut répondre dans ce canal selon le mode de filtrage."""
    if guild_id is None:
        # DM channel — toujours autorisé (Wally peut lui-même initier des DM,
        # les réponses doivent donc être traitées quel que soit le filtrage de guild).
        return True
    pgw = config.discord.per_guild_channel_whitelist
    guild_key = str(guild_id)
    if guild_key in pgw:
        guild_wl = pgw[guild_key]
        if guild_wl is None:  # null dans config = tous les canaux autorisés
            return True
        return channel_id in guild_wl
    mode = config.discord.channel_filter_mode
    if mode == "whitelist":
        wl = config.discord.channel_whitelist
        return not wl or channel_id in wl
    if mode == "blacklist":
        bl = config.discord.channel_blacklist
        return channel_id not in bl
    return True  # mode "none" ou inconnu : tout autorisé


async def _check_spam(bot: "WallyDiscord", message: discord.Message) -> bool:
    """Track message rate and trigger spam mute if threshold exceeded.
    Returns True if spam was detected and handled (caller should return early).
    """
    cfg = bot.config.discord.spam_detection
    if not cfg.enabled:
        return False
    if not message.guild:
        return False
    channel_id = message.channel.id
    if channel_id in cfg.exempt_channels:
        return False

    user_id = str(message.author.id)
    key = (user_id, str(channel_id))
    now = time.time()
    cutoff = now - cfg.window_seconds

    dq = _spam_tracker.get(key)
    if dq is None:
        dq = deque()
        _spam_tracker[key] = dq

    # Purge old timestamps
    while dq and dq[0] < cutoff:
        dq.popleft()
    # Clean up empty entries before adding new one
    if not dq:
        _spam_tracker.pop(key, None)
    dq.append(now)
    # Re-register in case we popped above
    if key not in _spam_tracker:
        _spam_tracker[key] = dq

    if len(dq) < cfg.max_messages:
        return False

    # --- Spam detected ---
    guild_id = str(message.guild.id)
    username = _author_label(message.author)
    anger = bot.emotion.get_state().get("anger", 0.0)

    # Generate LLM warning
    system = load_prompt("spam_warning_system", "Dis à l'utilisateur de se calmer.")
    user_msg = (
        f"L'utilisateur {username} a envoyé {len(dq)} messages "
        f"en {cfg.window_seconds} secondes."
    )
    try:
        warning = await bot.llm_secondary.complete(
            system_prompt=system,
            messages=[{"role": "user", "content": user_msg}],
            purpose="spam_warning",
            user_id=user_id,
        )
        await message.channel.send(warning)
    except Exception as e:
        logger.error("Spam warning LLM failed: {e}", e=e)
        await message.channel.send(f"{username}, calme-toi un peu. 😤")

    # Mute user
    await bot.db.add_timeout(user_id, guild_id, cfg.mute_minutes, anger)

    # Store memory fact
    try:
        self_name = bot.config.bot.name
        await bot.memory.add(
            "discord", user_id,
            f"{self_name} a coupé {username} pour spam — trop de messages en peu de temps. "
            f"Il en a eu marre et a arrêté de lui répondre.",
            username=username,
            origin=_channel_origin(message.channel),
        )
    except Exception as e:
        logger.warning("Failed to store spam memory: {e}", e=e)

    # Reset tracker for this user/channel
    dq.clear()
    _spam_tracker.pop(key, None)

    logger.info(
        "Spam detected: {user} in channel {ch} — muted {min}min",
        user=username, ch=channel_id, min=cfg.mute_minutes,
    )
    return True


async def _third_party_mention_context(
    bot,
    platform: str,
    author_user_id: str,
    prelude: list[dict],
    context_messages: list[dict],
) -> str:
    """Detect mentions of third-party users and inject their memories."""
    # Gather text from recent messages
    texts = []
    for msg in (prelude or []):
        texts.append(msg.get("author", ""))
        texts.append(msg.get("content", ""))
    for msg in (context_messages or []):
        content = msg.get("content", "")
        if isinstance(content, str):
            texts.append(content)

    full_text = " ".join(texts)
    words = re.findall(r"[A-Za-z0-9_À-ÿ]{3,}", full_text)

    # Build candidate set: starts with uppercase or in alias map
    alias_cache = bot.memory._alias_cache
    known_nicknames = {
        k[len("nickname:"):] for k in alias_cache
        if k.startswith("nickname:")
    }

    candidates = set()
    for word in words:
        if word[0].isupper() or word.lower() in known_nicknames:
            candidates.add(word)

    if not candidates:
        return ""

    # Load known users for fuzzy matching
    try:
        users = await bot.db.list_memory_users()
    except Exception:
        users = []
    known_usernames = {u["username"].lower(): u for u in users if u.get("username")}

    # Remove the current author by user_id AND by their username (for Discord snowflake IDs)
    author_lower = author_user_id.lower()
    author_username_lower = None
    for u in users:
        uid = u.get("user_id", "")
        if uid == author_user_id or uid.endswith(":" + author_user_id):
            author_username_lower = (u.get("username") or "").lower()
            break
    candidates = {
        c for c in candidates
        if c.lower() != author_lower
        and (author_username_lower is None or c.lower() != author_username_lower)
    }

    parts = []
    processed = 0

    for token in sorted(candidates):  # sorted for determinism
        if processed >= 2:
            break

        token_lower = token.lower()
        cache_key = f"nickname:{token_lower}"

        if cache_key in alias_cache:
            # Exact alias match
            canonical_uid = alias_cache[cache_key]  # e.g. "twitch:mkszedd"
            uid_parts = canonical_uid.split(":", 1)
            if len(uid_parts) == 2:
                third_platform, third_raw_id = uid_parts
                try:
                    memories_text = await bot.memory.search(third_platform, third_raw_id, query=token, username_hint=token)
                    if memories_text:
                        # Find username for display
                        display = third_raw_id
                        for u in users:
                            if u.get("user_id") == canonical_uid:
                                display = u.get("username", third_raw_id)
                                break
                        parts.append(f"--- Souvenirs sur {display} ---\n{memories_text}")
                        processed += 1
                except Exception:
                    pass
        else:
            # Fuzzy match against known usernames
            best_ratio = 0.0
            best_username = None
            for uname_lower, udata in known_usernames.items():
                ratio = difflib.SequenceMatcher(None, token_lower, uname_lower).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_username = udata.get("username", uname_lower)

            if best_ratio >= 0.75 and best_username:
                pct = int(best_ratio * 100)
                parts.append(
                    f"Note interne : '{token}' ressemble à {best_username} (confiance {pct}%) "
                    f"— si c'est bien lui, mentionne-le naturellement"
                )
                processed += 1

    return "\n\n".join(parts)


def _conv_channel(message: discord.Message) -> str:
    """Segment de chemin pour le log de conversation : ``guild/canal`` (ou ``dm``)."""
    guild = getattr(getattr(message, "guild", None), "name", None)
    chan = getattr(message.channel, "name", None) or "dm"
    return f"{guild}/{chan}" if guild else chan


def _clog(bot: "WallyDiscord", channel: str, event_type: str, **fields) -> None:
    """Journalise un événement de conversation si le logger est câblé (no-op sinon)."""
    clog = getattr(bot, "conv_log", None)
    if clog is not None:
        clog.log("discord", channel, event_type, **fields)


async def handle_message(bot: "WallyDiscord", message: discord.Message) -> None:
    logger.debug("on_message: author={} bot={} guild={} channel={}", message.author, message.author.bot, getattr(message.guild, 'id', 'dm'), message.channel.id)
    if message.author.bot:
        return

    # Ignore entièrement les guilds blacklistés (ex: serveurs de test/notification)
    if message.guild and message.guild.id in bot.config.discord.ignored_guilds:
        return

    # Dedup: Discord can replay events on WebSocket reconnect — skip already-processed messages
    _now = time.time()
    if message.id in _processed_message_ids:
        logger.debug("Duplicate on_message event for id={}, skipping", message.id)
        return
    _processed_message_ids[message.id] = _now
    # Purge entries older than 120s to avoid unbounded growth
    for _mid in [k for k, v in _processed_message_ids.items() if _now - v > 120]:
        del _processed_message_ids[_mid]

    # Dashboard message counter
    if getattr(bot, "dashboard_state", None) is not None:
        bot.dashboard_state.message_count += 1
        bot.dashboard_state.message_count_discord += 1

    user_id = str(message.author.id)
    # DMs et always_trigger_channels : tout message est un trigger
    _is_dm = message.guild is None
    _is_always_trigger = _is_dm or message.channel.id in getattr(bot.config.discord, "always_trigger_channels", [])
    channel_allowed = _is_always_trigger or _is_channel_allowed(bot.config, message.channel.id, message.guild.id if message.guild else None)

    # Contenu enrichi : inclut un tag [image] si des images sont jointes
    _has_images = any(
        a.content_type and a.content_type.startswith("image/")
        for a in message.attachments
    )
    _enriched_content = _resolve_mentions(message, message.content or "")
    if _has_images and not _enriched_content:
        n = sum(1 for a in message.attachments if a.content_type and a.content_type.startswith("image/"))
        _enriched_content = f"[a envoyé {'une image' if n == 1 else f'{n} images'}]"
    elif _has_images:
        n = sum(1 for a in message.attachments if a.content_type and a.content_type.startswith("image/"))
        _enriched_content += f" [+ {'une image' if n == 1 else f'{n} images'}]"

    # Capture passive + récupération prelude AVANT d'ajouter le message courant
    if channel_allowed:
        prelude = bot.memory.get_prelude(str(message.channel.id))
        author_label = _author_label(message.author)
        bot.memory.append_prelude(
            str(message.channel.id), author_label, _enriched_content
        )
        # Enregistrement dans la session active du canal (tous les messages)
        if getattr(bot, "fact_extractor", None) is not None:
            bot.fact_extractor.record_message(
                str(message.channel.id), "discord", user_id,
                author_label, _enriched_content,
                is_reply=message.reference is not None,
                origin=_channel_origin(message.channel),
            )
        _clog(
            bot, _conv_channel(message), "message_in",
            trace_id=str(message.id), author=author_label, author_id=user_id,
            content=_enriched_content, is_reply=message.reference is not None,
            has_images=_has_images,
        )
    else:
        prelude = []

    # Reaction tracking: detect positive replies to Wally's messages
    tracker = getattr(bot, "reaction_tracker", None)
    if tracker and message.reference and message.reference.message_id:
        tracker.record_discord_reply(
            message.reference.message_id, message.content, message.author.bot,
        )

    # Spam detection — track all messages in allowed channels
    if channel_allowed and message.guild:
        if await _check_spam(bot, message):
            return

    # Perception cognitive : le « cerveau » perçoit TOUS les messages des salons
    # autorisés (pas seulement ceux qui mentionnent Wally), afin de pouvoir
    # intervenir spontanément quand c'est pertinent sans avoir besoin d'être ping.
    # Aligné sur le comportement Twitch (cf. twitch/handlers.py). La boucle
    # cognitive applique ses propres garde-fous (cooldowns, anti-rumination,
    # conscience sociale) avant tout SPEAK.
    if channel_allowed and getattr(bot, "cognitive_loop", None) is not None:
        try:
            bot.cognitive_loop.notify_activity(
                channel_id=message.channel.id,
                author=str(message.author.display_name),
                content=_resolve_mentions(message, message.content or ""),
                message_id=str(message.id),
                is_dm=message.guild is None,
            )
        except Exception as e:
            logger.warning("cognitive_loop.notify_activity failed: {e}", e=e)

    content_lower = message.content.lower()
    mentioned = bot.user in message.mentions
    always_trigger = _is_always_trigger
    triggered = always_trigger or mentioned or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )
    logger.debug("triggered={} mentioned={} always={} channel={}", triggered, mentioned, always_trigger, message.channel.id)
    if not triggered:
        # Passive emoji reaction on non-trigger messages (Discord only)
        if channel_allowed and random.random() < bot.config.discord.emoji_reaction_probability:
            curiosity = bot.emotion.get_state().get("curiosity", 0.0)
            passive_emoji = _pick_passive_emoji(message.content, curiosity)
            if passive_emoji:
                try:
                    await message.add_reaction(passive_emoji)
                    _clog(
                        bot, _conv_channel(message), "reaction",
                        trace_id=str(message.id), emoji=passive_emoji, passive=True,
                    )
                except Exception:
                    pass
        # Spontaneous intervention
        if channel_allowed and bot.config.bot.spontaneous_discord_enabled:
            state = bot.emotion.get_state()
            trigger_type = _check_spontaneous_trigger(
                message.content,
                curiosity=state.get("curiosity", 0.0),
                anger=state.get("anger", 0.0),
                boredom=state.get("boredom", 0.0),
            )
            chan_id = str(message.channel.id)
            now = time.time()
            cooldown = bot.config.bot.spontaneous_cooldown_seconds
            cooldown_ok = now - _spontaneous_cooldowns.get(chan_id, 0) >= cooldown

            if trigger_type and cooldown_ok:
                prob = (
                    bot.config.bot.spontaneous_passion_probability
                    if trigger_type == "passion"
                    else bot.config.bot.spontaneous_probability
                )
                if random.random() < prob:
                    _spontaneous_cooldowns[chan_id] = now
                    _clog(
                        bot, _conv_channel(message), "gate_decision",
                        trace_id=str(message.id), triggered=False, spontaneous=True,
                        trigger_type=trigger_type, decision="spontaneous",
                    )
                    _fire(_spontaneous_respond(bot, message, prelude_snapshot=prelude))
        return

    if not channel_allowed:
        logger.info(
            "Triggered by {user} but channel #{ch} (guild {g}) not allowed — skipping",
            user=message.author.display_name,
            ch=message.channel.id,
            g=message.guild.id if message.guild else "dm",
        )
        return

    guild_id = str(message.guild.id) if message.guild else "dm"

    if await bot.db.is_muted(user_id, guild_id):
        emoji = random.choice(TIMEOUT_REACTIONS)
        await message.add_reaction(emoji)
        if bot.config.discord.spam_detection.enabled:
            bot.emotion.apply_delta("anger", bot.config.discord.spam_detection.spam_anger_delta)
        return

    first_contact = not await bot.db.is_welcomed(user_id, guild_id)

    # Gate : Wally décide s'il répond (RESPOND), se tait (IGNORE/DEFER) ou
    # réagit juste en emoji (REACT) — même sur un trigger. Le silence est un
    # choix autonome. Fallback RESPOND si le gate est absent ou échoue : jamais
    # de blocage silencieux dû à une panne.
    gate = getattr(bot, "response_gate", None)
    decision, gate_reason, gate_emoji = "RESPOND", None, None
    if gate is not None:
        try:
            from bot.intelligence.memory.facts import FactCategory
            _store = gate._fact_store  # même paquet : accès interne assumé
            _rel = await _store.get_by_user(user_id, categories=[FactCategory.REL])
            _desires = await _store.get_by_user("wally:self", categories=[FactCategory.DESIRE])
            _last = getattr(bot, "_wally_recent_speaks", {}).get(message.channel.id)
            # Toutes les emotes de TOUS les serveurs du bot (Nitro-like), dédupliquées.
            _guild_emojis = list(dict.fromkeys(e.name for e in bot.emojis))
            # Notes d'usage apprises ("nom → quand l'utiliser") → guide le choix.
            _emote_notes = await _store.get_by_user("wally:emotes", categories=[FactCategory.PREF])
            _emoji_usage = [f.content for f in _emote_notes]
            _thread = []
            try:
                _thread = bot.memory.get_context(str(message.channel.id))[-5:]
            except Exception:
                _thread = []
            _gd = await gate.decide(
                message_content=_resolve_mentions(message, message.content or ""),
                author_user_id=user_id,
                emotion_state=bot.emotion.get_state(),
                relationship_facts=_rel,
                active_desires=_desires,
                is_mentioned=mentioned,
                is_triggered=True,
                is_dm=message.guild is None,
                wally_last_message=_last,
                available_emojis=_guild_emojis,
                emoji_usage=_emoji_usage,
                recent_messages=_thread,
            )
            decision, gate_reason, gate_emoji = _gd.decision, _gd.reason, _gd.emoji
        except Exception as e:
            logger.warning("gate.decide() failed, fallback RESPOND: {e}", e=e)

    _clog(
        bot, _conv_channel(message), "gate_decision",
        trace_id=str(message.id), triggered=True, mentioned=mentioned,
        always_trigger=always_trigger, spontaneous=False,
        decision=decision.lower(), reason=gate_reason,
    )

    # Non-réponse (IGNORE / DEFER / REACT) : Wally se tait MAIS laisse toujours un
    # emoji — son humeur, ou pourquoi il ne répond pas. Le gate fournit l'emoji
    # contextuel ; à défaut, fallback sur l'émotion dominante (résout toujours).
    if decision in ("IGNORE", "DEFER", "REACT"):
        _raw = gate_emoji or _mood_emoji(bot.emotion.get_state())
        _emoji = _resolve_emoji(_raw, bot)
        try:
            await message.add_reaction(_emoji)
        except Exception:
            pass
        return

    await _respond(bot, message, user_id, guild_id, prelude, first_contact=first_contact, enriched_content=_enriched_content)


_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)]) ")


def _is_list_item(line: str) -> bool:
    return bool(_LIST_RE.match(line))



async def _send_in_parts(message: discord.Message, text: str) -> tuple[int | None, int]:
    """Split text on newlines, group consecutive list items, send as separate messages.

    Retourne ``(id du premier message envoyé, nombre de parts)`` — le compte de
    parts alimente l'event ``message_out`` (un reply découpé en N messages).
    """
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return None, 0

    # Group lines: consecutive list items are bundled into one message
    groups: list[str] = []
    current: list[str] = []
    in_list = False
    for line in lines:
        if _is_list_item(line):
            if not in_list:
                if current:
                    groups.append("\n".join(current))
                current = []
                in_list = True
            current.append(line)
        else:
            if in_list:
                groups.append("\n".join(current))
                current = []
                in_list = False
            current.append(line)
    if current:
        groups.append("\n".join(current))

    first_msg = await message.reply(groups[0], allowed_mentions=_ALLOWED_MENTIONS)
    for group in groups[1:]:
        await asyncio.sleep(random.uniform(0.6, 1.8))
        await message.channel.send(group, allowed_mentions=_ALLOWED_MENTIONS)
    return first_msg.id, len(groups)


async def _fetch_referenced_message(
    message: discord.Message,
) -> "discord.Message | None":
    """Récupère le message auquel `message` répond (resolved ou fetch), ou None.

    Sert à la fois à enrichir la recherche mémoire (chercher les faits liés au
    contenu cité) et à injecter le contexte de la citation dans le prompt.
    """
    ref = message.reference
    if not (ref and ref.message_id):
        return None
    try:
        ref_msg = ref.resolved
        if ref_msg is None:
            ref_msg = await message.channel.fetch_message(ref.message_id)
        if isinstance(ref_msg, discord.Message):
            return ref_msg
    except Exception as e:
        logger.debug("Failed to fetch referenced message: {e}", e=e)
    return None


async def _auto_scrape_block(bot: "WallyDiscord", message: "discord.Message") -> str:
    """Scrape le 1er lien web d'un message (cooldown par canal). Retourne un bloc ou ""."""
    scrape = getattr(bot, "scrape", None)
    if not scrape or not scrape.available:
        return ""
    if not bot.config.firecrawl.auto_scrape_links:
        return ""

    match = _URL_RE.search(message.content or "")
    if not match:
        return ""
    url = match.group(0).rstrip(").,;")
    if not scrape.is_scrapable_url(url):
        return ""

    channel_id = str(message.channel.id)
    now = time.time()
    last = _scrape_cooldowns.get(channel_id, 0.0)
    if now - last < bot.config.firecrawl.auto_scrape_cooldown_s:
        return ""
    _scrape_cooldowns[channel_id] = now

    try:
        content = await scrape.scrape(url)
    except Exception as exc:
        logger.warning("Auto-scrape failed for {u}: {e}", u=url, e=exc)
        return ""
    if not content:
        return ""
    return f"--- Page web ---\n{content}\n"


async def _respond(
    bot: "WallyDiscord",
    message: discord.Message,
    user_id: str,
    guild_id: str,
    prelude: list[dict],
    first_contact: bool = False,
    enriched_content: str = "",
) -> None:
    try:
        await message.add_reaction("🔍")

        platform = "discord"
        trust = await bot.db.get_trust_score(platform, user_id)

        # Si c'est une réponse à un message, on récupère le message cité tôt :
        # son contenu enrichit la recherche mémoire (sinon Wally cherche sur
        # "j'ai po la ref" → 0 fait → il comble le vide en inventant) et sert
        # plus bas à injecter la citation dans le prompt.
        # Mentions <@id> → pseudo lisible, pour que le LLM voie QUI est pingé
        # (recherche mémoire, citation, texte courant) au lieu d'un identifiant nu.
        resolved_content = _resolve_mentions(message, message.content or "")
        ref_msg = await _fetch_referenced_message(message)
        replied_quote = (
            _resolve_mentions(ref_msg, ref_msg.content or "").strip() if ref_msg else ""
        )
        search_query = (
            f"{resolved_content}\n{replied_quote}".strip()
            if replied_quote else resolved_content
        )

        mem_context = await bot.memory.search(platform, user_id, search_query, context_messages=prelude, username_hint=message.author.display_name)

        # Temporal activity: inject absence note if user hasn't been seen in 7+ days
        try:
            last_seen = await bot.db.get_last_interaction(f"{platform}:{user_id}")
            if last_seen:
                days_ago = int((time.time() - last_seen) / 86400)
                if days_ago >= 7:
                    absence_note = f"\nDernière interaction avec cet utilisateur : il y a {days_ago} jours."
                    mem_context = (mem_context + absence_note) if mem_context else absence_note.strip()
        except Exception:
            pass

        # ── Fetch context messages early (needed for priority 6) ──────
        context_messages = await bot.memory.get_context_summarized_if_needed(
            str(message.channel.id)
        )

        # ── Assemble memory context with token budget ──────────────────
        max_tokens = bot.config.bot.memory_context_max_tokens
        memory_parts: list[tuple[int, str]] = []

        # Priority 1: Semantic memories (already fetched)
        if mem_context:
            memory_parts.append((1, mem_context))

        # Priority 4: Recent successful jokes for this channel
        try:
            recent_jokes = await bot.db.get_recent_jokes(str(message.channel.id), limit=3)
            if recent_jokes:
                jokes_block = "--- Tes blagues récentes qui ont bien marché dans ce salon ---"
                for j in recent_jokes:
                    jokes_block += f'\n- "{j}"'
                memory_parts.append((4, jokes_block))
        except Exception:
            pass

        # Priority 5: Community opinions
        try:
            opinions = await bot.db.get_opinions(limit=10)
            if opinions:
                opinions_block = "--- Tes opinions sur les sujets de la communauté ---"
                for o in opinions:
                    opinions_block += f'\n- {o["topic"]} : "{o["opinion"]}"'
                memory_parts.append((5, opinions_block))
        except Exception:
            pass

        # Priority 6: Third-party mentions
        try:
            third_party_ctx = await _third_party_mention_context(
                bot, platform, user_id, prelude, context_messages
            )
            if third_party_ctx:
                memory_parts.append((6, third_party_ctx))
        except Exception:
            pass

        mem_context = assemble_memory_context(memory_parts, max_tokens)

        # Trust/love go in separate relationship_context (outside token budget)
        love = await bot.db.get_love_score(platform, user_id, bot.config.bot.love_decay_lambda)
        relationship_context = f"Niveau de confiance : {trust:.2f}/1.0\nNiveau d'affection : {love:.2f}/1.0"

        # Fallback cold start si prelude vide
        if not prelude:
            prelude = await _fetch_discord_history(
                message.channel, bot.config.bot.prelude_window_size, exclude_id=message.id
            )

        # Persistent notes
        try:
            persistent_notes = await bot.db.get_persistent_notes()
        except Exception:
            persistent_notes = []

        situation: dict = {"platform": "Discord"}
        if message.guild:
            situation["server"] = message.guild.name
        if isinstance(message.channel, discord.TextChannel):
            situation["channel"] = f"#{message.channel.name}"

        presence_context = _presence_line(bot, user_id, message.author.display_name)

        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=mem_context,
            situation=situation,
            presence_context=presence_context,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            relationship_context=relationship_context,
            persistent_notes=persistent_notes or None,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_messages)

        # Extraction des images (message courant)
        image_urls = [
            a.url for a in message.attachments
            if a.content_type and a.content_type.startswith("image/")
        ][:4]

        author_label = _author_label(message.author)

        # `ref_msg` (message cité) a déjà été récupéré plus haut pour la recherche
        # mémoire. On l'utilise ici pour injecter la citation + ses images dans le
        # prompt, afin que Wally sache à QUOI on répond, même hors fenêtre de contexte.
        replied_image_context = ""
        replied_text_context = ""
        if ref_msg is not None:
            try:
                # Texte du message cité (tronqué) — auteur attribué explicitement
                ref_text = " ".join(_resolve_mentions(ref_msg, ref_msg.content or "").split())
                if ref_text:
                    if len(ref_text) > 300:
                        ref_text = ref_text[:300] + "…"
                    ref_who = (
                        f"toi ({bot.config.bot.name})" if ref_msg.author.id == bot.user.id
                        else _author_label(ref_msg.author)
                    )
                    replied_text_context = (
                        f"\n↪ [{author_label} répond à ce message de {ref_who}] : "
                        f"« {ref_text} »\n"
                    )
                # Images du message référencé — seulement si le message courant
                # n'en contient pas déjà
                if not image_urls:
                    _img_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp")
                    ref_images = [
                        a.url for a in ref_msg.attachments
                        if (a.content_type and a.content_type.startswith("image/"))
                        or a.filename.lower().endswith(_img_exts)
                    ]
                    # Images dans les embeds (URLs CDN uniquement, pas attachment://)
                    if not ref_images:
                        for embed in ref_msg.embeds:
                            if embed.image and embed.image.url and not embed.image.url.startswith("attachment://"):
                                ref_images.append(embed.image.url)
                    image_urls = ref_images[:4]
                    if image_urls:
                        # Contexte sur l'image référencée
                        is_wally_image = ref_msg.author.id == bot.user.id
                        ref_desc = ""
                        for embed in ref_msg.embeds:
                            if embed.title:
                                ref_desc += f" Titre: {embed.title}."
                            if embed.description:
                                ref_desc += f" Prompt: {embed.description}"
                        if is_wally_image:
                            replied_image_context = (
                                f"[L'utilisateur répond à une image que TU as générée avec /imagine."
                                f"{ref_desc} Tu es l'auteur de cette image.]\n"
                            )
                        else:
                            replied_image_context = (
                                f"[L'utilisateur répond à un message contenant une image."
                                f"{ref_desc}]\n"
                            )
            except Exception as e:
                logger.debug("Failed to process referenced message: {e}", e=e)

        # Texte à envoyer — ajoute un marqueur image si texte+image pour que le LLM traite l'image
        if image_urls and resolved_content:
            n = len(image_urls)
            img_tag = "[Image jointe]" if n == 1 else f"[{n} images jointes]"
            text_content = f"{resolved_content}\n{img_tag}"
        elif image_urls:
            text_content = "Regarde cette image."
        else:
            text_content = resolved_content

        # ── Vision : le LLM principal est AVEUGLE (DeepSeek ignore image_urls).
        # On analyse réellement l'image via VisionService et on injecte les faits
        # dans le contexte texte, pour que Wally commente l'image au lieu d'inventer.
        # L'analyse est réutilisée plus bas par _post_process (mémoire) sans 2e appel.
        image_analysis: str | None = None
        image_analysis_context = ""
        if image_urls:
            vision = getattr(bot, "vision", None)
            if vision is not None and vision.available:
                async with message.channel.typing():
                    image_analysis = await vision.analyze(
                        image_urls, caption=resolved_content
                    )
                if image_analysis:
                    image_analysis_context = (
                        "\n[ANALYSE VISUELLE de l'image jointe — ce que tu VOIS "
                        "réellement, des faits vérifiés ; commente-les, n'invente "
                        f"rien d'autre] :\n{image_analysis}\n"
                    )
                    _clog(
                        bot, _conv_channel(message), "image_analysis",
                        trace_id=str(message.id), analysis=image_analysis[:500],
                    )

        target_notice = (
            f"\n⚠️ Tu réponds à {author_label}. "
            "Le contexte ci-dessus contient des messages de PLUSIEURS personnes — "
            "attribue chaque propos à son auteur (indiqué entre crochets). "
            "Ne confonds JAMAIS les propos d'un utilisateur avec ceux d'un autre. "
            "Réponds UNIQUEMENT avec ton propre texte — ne répète jamais le message auquel tu réponds."
        )
        auto_scrape_block = await _auto_scrape_block(bot, message)
        mention_block = _build_mention_directory(message)
        user_content = (
            prelude_block
            + auto_scrape_block
            + context_block
            + target_notice
            + mention_block
            + replied_text_context
            + replied_image_context
            + image_analysis_context
            + f"\n[{author_label}]: {text_content}"
        )

        if first_contact:
            user_content = (
                f"[CONTEXTE: C'est la première fois que {_author_label(message.author)} "
                f"t'adresse la parole sur ce serveur. Commence ta réponse par une "
                f"bienvenue chaleureuse en une phrase courte, puis réponds à son message.]\n\n"
                + user_content
            )

        openai_messages = [{"role": "user", "content": user_content}]

        # ── Collect available tools ──────────────────────────────────────
        tools: list[dict] = []
        web_search = getattr(bot, "web_search", None)
        if web_search and web_search.available and not await web_search.is_quota_exceeded():
            tools.extend(web_search.get_tool_definitions())
        scrape = getattr(bot, "scrape", None)
        if scrape and scrape.available and not await scrape.daily_limit_reached():
            tools.extend(scrape.get_tool_definitions())
        apex_api = getattr(bot, "apex_api", None)
        if apex_api and apex_api.available:
            tools.append(apex_api.get_tool_definition())
        action_service = getattr(bot, "action_service", None)
        if action_service:
            tools.extend(action_service.get_tool_definitions())
        tools.extend(_NOTE_TOOLS)
        if getattr(bot, "voice_service", None) is not None:
            tools += VOICE_TOOLS
        # Self-modification : réservée au créateur, et seulement si SelfFix est câblé.
        if str(message.author.id) == bot.config.bot.owner_discord_id and getattr(bot, "self_fix", None) is not None:
            tools.append(_SELF_MODIFY_TOOL)

        _reaction_emojis: set[str] = set()

        async def _tool_executor_impl(name: str, arguments: str) -> str:
            _clog(
                bot, _conv_channel(message), "tool_called",
                trace_id=str(message.id), tool=name, args=arguments,
            )
            args = json.loads(arguments)
            if name == "save_persistent_note":
                await bot.db.upsert_persistent_note(args["title"], args["content"])
                return json.dumps({"status": "ok", "message": f"Note '{args['title']}' sauvegardée."})
            if name == "delete_persistent_note":
                deleted = await bot.db.delete_persistent_note(args["title"])
                if deleted:
                    return json.dumps({"status": "ok", "message": f"Note '{args['title']}' supprimée."})
                return json.dumps({"status": "not_found", "message": f"Note '{args['title']}' introuvable."})
            if name == "save_user_memory":
                await bot.memory.add("discord", user_id, args["content"], username=_author_label(message.author),
                                     origin=_channel_origin(message.channel))
                return json.dumps({"status": "ok", "message": "Souvenir sauvegardé."})

            if name in ("web_search", "image_search"):
                if "🌐" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🌐")
                        _reaction_emojis.add("🌐")
                    except Exception:
                        pass
                if name == "image_search":
                    return await web_search.search_images(args["query"])
                return await web_search.search(args["query"])
            if name == "scrape_url":
                if "🌐" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🌐")
                        _reaction_emojis.add("🌐")
                    except Exception:
                        pass
                return await scrape.scrape(args["url"])
            if name == "apex_legends":
                if "🔫" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🔫")
                        _reaction_emojis.add("🔫")
                    except Exception:
                        pass
                return await apex_api.execute(
                    args.get("action", ""),
                    player_name=args.get("player_name", ""),
                    platform=args.get("platform", "PC"),
                )
            if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
                if "⏱️" not in _reaction_emojis:
                    try:
                        await message.add_reaction("⏱️")
                        _reaction_emojis.add("⏱️")
                    except Exception:
                        pass
                user_roles = _resolve_discord_roles(message.author)
                # Check config admin list too
                admin_ids = getattr(bot.config, "admin_ids", [])
                if str(message.author.id) in [str(a) for a in admin_ids]:
                    user_roles.append("admin")
                guild_id = str(message.guild.id) if message.guild else None
                result = await action_service.execute_tool(
                    name, args,
                    user_id=str(message.author.id),
                    platform="discord",
                    user_roles=user_roles,
                    channel_id=str(message.channel.id),
                    guild_id=guild_id,
                )
                return json.dumps(result)
            if name == "request_self_modification":
                if str(message.author.id) != bot.config.bot.owner_discord_id or getattr(bot, "self_fix", None) is None:
                    return json.dumps({"status": "refused", "message": "Réservé au créateur, et mécanisme indisponible."})
                goal = (args.get("goal") or "").strip()
                if not goal:
                    return json.dumps({"status": "error", "message": "Précise le but de la modification que tu veux."})
                # Demande explicite du créateur → force=True (outrepasse un refus précédent).
                # request_upgrade attend la réaction ✅/❌ (jusqu'à 1h) → tâche de fond.
                _fire(bot.self_fix.request_upgrade(UpgradeRequest(goal=goal), force=True))
                return json.dumps({
                    "status": "ok",
                    "message": "Je t'envoie une demande d'autorisation 🧠 en DM avec le but reformulé — réagis ✅ pour que Claude Code s'en charge, ❌ pour annuler.",
                })
            if name == "join_voice":
                voice = getattr(message.author, "voice", None)
                if voice is None or voice.channel is None:
                    return json.dumps({"status": "denied", "message": "Tu n'es dans aucun salon vocal."})
                await bot.voice_service.join(voice.channel)
                return json.dumps({"status": "ok", "message": f"Rejoint {voice.channel.name}."})
            if name == "leave_voice":
                if getattr(bot, "voice_service", None) and bot.voice_service.is_connected:
                    await bot.voice_service.leave()
                    return json.dumps({"status": "ok", "message": "Quitté le vocal."})
                return json.dumps({"status": "ok", "message": "Pas en vocal."})
            return f"Unknown tool: {name}"

        async def _tool_executor(name: str, arguments: str) -> str:
            result = await _tool_executor_impl(name, arguments)
            _clog(
                bot, _conv_channel(message), "tool_result",
                trace_id=str(message.id), tool=name, result=str(result)[:500],
            )
            return result

        _llm_t0 = time.monotonic()
        async with message.channel.typing():
            if tools:
                reply, tools_called = await bot.llm.complete_with_tools(
                    system_prompt, openai_messages, tools, _tool_executor,
                    purpose="discord_response",
                    image_urls=image_urls or None,
                    user_id=f"discord:{message.author.id}",
                )
            else:
                reply = await bot.llm.complete(
                    system_prompt, openai_messages, purpose="discord_response",
                    image_urls=image_urls or None,
                    user_id=f"discord:{message.author.id}",
                )
                tools_called = []

        _emo = bot.emotion.get_state()
        _dom = max(_emo, key=_emo.get) if _emo else None
        _clog(
            bot, _conv_channel(message), "llm_call",
            trace_id=str(message.id),
            model=getattr(bot.llm, "_model", "?"),
            dominant_emotion=_dom,
            emotion_value=round(_emo.get(_dom, 0.0), 3) if _dom else None,
            tools_offered=[t.get("function", {}).get("name") for t in tools],
            tools_called=tools_called,
            latency_ms=int((time.monotonic() - _llm_t0) * 1000),
            system_prompt=system_prompt,
            user_content=user_content,
            raw_reply=reply,
        )

        # Mirror pass — detect and fix repetitive patterns or missed memories
        _mirror_before = reply
        reply = await _mirror_pass(bot, str(message.channel.id), reply, mem_context)
        if reply != _mirror_before:
            _clog(
                bot, _conv_channel(message), "mirror_pass",
                trace_id=str(message.id),
                before=_mirror_before[:400], after=reply[:400],
            )

        # Parse optional [react:emoji] tag from LLM response
        react_emoji, reply = _parse_react_tag(reply)

        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass
        for emoji in _reaction_emojis:
            try:
                await message.remove_reaction(emoji, bot.user)
            except Exception:
                pass

        if react_emoji:
            try:
                await message.add_reaction(react_emoji)
            except Exception:
                pass

        self_name = bot.config.bot.name
        reply_msg_id, _parts = await _send_in_parts(message, reply)
        _clog(
            bot, _conv_channel(message), "message_out",
            trace_id=str(message.id), author=self_name, content=reply,
            parts=_parts, sent_msg_id=str(reply_msg_id) if reply_msg_id else None,
            react_emoji=react_emoji,
        )
        # Signale à la boucle cognitive que le bot a déjà répondu ici → pas de SPEAK
        # proactif redondant dans la foulée.
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(message.channel.id, content=reply)
        _speaks = getattr(bot, "_wally_recent_speaks", None)
        if _speaks is not None:
            _speaks[message.channel.id] = reply
        if reply_msg_id and getattr(bot, "reaction_tracker", None):
            bot.reaction_tracker.track_discord_message(reply_msg_id, reply_text=reply, channel_id=str(message.channel.id))

        if first_contact:
            await bot.db.mark_welcomed(user_id, guild_id)
            _clog(
                bot, _conv_channel(message), "welcome",
                trace_id=str(message.id), user=_author_label(message.author),
            )

        bot.memory.append_message(
            str(message.channel.id), _author_label(message.author), enriched_content or message.content, platform="discord"
        )
        bot.memory.append_prelude(str(message.channel.id), self_name, reply)
        bot.memory.append_message(str(message.channel.id), self_name, reply, platform="discord")

        # Persiste le display_name pour que le dashboard coûts affiche un nom lisible
        await bot.db.upsert_memory_user(
            f"discord:{message.author.id}", "discord",
            username=message.author.display_name,
        )

        _fire(_post_process(
            bot, text_content, platform, user_id, guild_id, trust, context_messages,
            image_urls=image_urls or None,
            image_analysis=image_analysis,
            channel_id=str(message.channel.id),
            display_name=message.author.display_name,
            trace_id=str(message.id),
            conv_channel=_conv_channel(message),
            origin=_channel_origin(message.channel),
        ))

    except Exception as e:
        logger.error("Error handling Discord message: {e}", e=e)
        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass


async def _post_process(
    bot: "WallyDiscord",
    text: str,
    platform: str,
    user_id: str,
    guild_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
    image_urls: list[str] | None = None,
    image_analysis: str | None = None,
    channel_id: str = "",
    display_name: str = "",
    trace_id: str = "",
    conv_channel: str = "",
    origin: str = "",
) -> None:
    try:
        _emo_before = bot.emotion.get_state()
        llm_deltas = await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            image_urls=image_urls,
            trigger_user=user_id, channel_id=channel_id, platform="discord",
            user_id=user_id,
        )
        _emo_after = bot.emotion.get_state()
        if trace_id:
            _emo_deltas = {
                _k: round(_emo_after.get(_k, 0.0) - _emo_before.get(_k, 0.0), 3)
                for _k in ("anger", "joy", "sadness", "curiosity", "boredom")
            }
            if any(_v != 0 for _v in _emo_deltas.values()):
                _clog(
                    bot, conv_channel, "emotion_change",
                    trace_id=trace_id,
                    deltas=_emo_deltas,
                    after={_k: round(_emo_after.get(_k, 0.0), 3) for _k in _emo_deltas},
                )

        if llm_deltas:
            await bot.db.update_trust_score(platform, user_id, llm_deltas["trust_delta"])
            if llm_deltas["love_delta"] > 0:
                await bot.db.update_love_score(
                    platform, user_id, llm_deltas["love_delta"],
                    bot.config.bot.love_decay_lambda,
                )
        else:
            # Fallback: simple heuristic when LLM unavailable
            insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
            if any(w in text.lower() for w in insult_words):
                await bot.db.update_trust_score(platform, user_id, -0.05)
            else:
                await bot.db.update_trust_score(platform, user_id, 0.01)

        if llm_deltas and llm_deltas.get("user_facts"):
            for _fact in llm_deltas["user_facts"]:
                await bot.memory.add(platform, user_id, _fact, username=display_name,
                                     origin=origin or None)

        # Stocke une description visuelle VÉRIDIQUE en mémoire long-terme.
        # Le LLM principal/secondaire (DeepSeek) est aveugle → on s'appuie sur
        # VisionService. On réutilise l'analyse déjà calculée dans _respond si
        # disponible (zéro appel supplémentaire), sinon on la calcule ici.
        if image_urls:
            try:
                analysis = image_analysis
                if not analysis:
                    vision = getattr(bot, "vision", None)
                    if vision is not None and vision.available:
                        analysis = await vision.analyze(image_urls, caption=text or "")
                if analysis:
                    summary = " ".join(analysis.split())
                    if len(summary) > 240:
                        summary = summary[:240].rstrip() + "…"
                    fact = f"{display_name} a envoyé une image : {summary}"
                    await bot.memory.add(platform, user_id, fact, username=display_name,
                                         origin=origin or None)
                    logger.debug("Image analysis stored for {u}", u=display_name)
            except Exception as e:
                logger.warning("Image analysis (memory) failed: {e}", e=e)

        anger = bot.emotion.get_state().get("anger", 0.0)
        if anger >= 0.8:
            # Always record the anger trigger (duration=0 → tracking only, not a real mute)
            await bot.db.add_timeout(user_id, guild_id, 0, anger)
            count = await bot.db.count_recent_triggers(user_id, guild_id)
            if count >= bot.config.discord.anger_trigger_threshold:
                await bot.db.add_timeout(
                    user_id,
                    guild_id,
                    bot.config.discord.timeout_minutes,
                    anger,
                )
                logger.info(
                    "User {uid} muted for {m} minutes",
                    uid=user_id,
                    m=bot.config.discord.timeout_minutes,
                )
                _clog(
                    bot, conv_channel, "moderation",
                    trace_id=trace_id, action="timeout",
                    minutes=bot.config.discord.timeout_minutes,
                    anger=round(anger, 3),
                )

        if trace_id:
            _clog(
                bot, conv_channel, "post_process",
                trace_id=trace_id,
                facts_extracted=len(llm_deltas.get("user_facts", [])) if llm_deltas else 0,
                image_described=bool(image_urls),
                trust_delta=round(llm_deltas["trust_delta"], 3) if llm_deltas else None,
                anger=round(anger, 3),
            )
    except Exception as e:
        logger.error("Post-process error: {e}", e=e)


async def _spontaneous_respond(
    bot: "WallyDiscord", message: discord.Message,
    recall_memory: str | None = None,
    prelude_snapshot: list[dict] | None = None,
) -> None:
    """Generate and send a spontaneous (unsolicited) response."""
    try:
        prelude = prelude_snapshot if prelude_snapshot is not None else bot.memory.get_prelude(str(message.channel.id))
        # Charger la mémoire de l'auteur si pas déjà fournie (#Q5).
        if recall_memory is None and message.content:
            user_id = str(message.author.id)
            ctx_msgs = [{"content": m.get("content", "")} for m in prelude[-3:]]
            recall_memory = await bot.memory.search(
                "discord", user_id, message.content[:200],
                context_messages=ctx_msgs,
            )
        situation: dict = {"platform": "Discord"}
        if message.guild:
            situation["server"] = message.guild.name
        if isinstance(message.channel, discord.TextChannel):
            situation["channel"] = f"#{message.channel.name}"

        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=recall_memory or "",
            situation=situation,
            presence_context=_presence_line(
                bot, str(message.author.id), message.author.display_name
            ),
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        recall_block = ""
        if recall_memory:
            recall_block = (
                "\n--- Souvenir qui te revient ---\n"
                f"{recall_memory}\n"
                f"Tu viens de te rappeler quelque chose en lien avec ce que dit "
                f"{_author_label(message.author)}. Évoque-le naturellement.\n\n"
            )
        mention_block = _build_mention_directory(message)
        user_content = (
            "[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément "
            "parce que le sujet t'intéresse ou te fait réagir. Réponds en une "
            "phrase courte et percutante, comme un commentaire lâché en passant.]\n\n"
            + recall_block
            + prelude_block
            + mention_block
            + f"\n[{_author_label(message.author)}]: {_resolve_mentions(message, message.content or '')}"
        )

        async with message.channel.typing():
            reply = await bot.llm.complete(
                system_prompt,
                [{"role": "user", "content": user_content}],
                purpose="discord_spontaneous",
            )
        _emo = bot.emotion.get_state()
        _dom = max(_emo, key=_emo.get) if _emo else None
        _clog(
            bot, _conv_channel(message), "llm_call",
            trace_id=str(message.id), kind="spontaneous",
            model=getattr(bot.llm, "_model", "?"),
            dominant_emotion=_dom,
            emotion_value=round(_emo.get(_dom, 0.0), 3) if _dom else None,
            system_prompt=system_prompt, user_content=user_content, raw_reply=reply,
        )

        # Parse and apply react tag if present
        react_emoji, reply = _parse_react_tag(reply)
        if react_emoji:
            try:
                await message.add_reaction(react_emoji)
            except Exception:
                pass

        # Correction ton/langue (#Q6)
        _mirror_before = reply
        reply = await _mirror_pass(bot, str(message.channel.id), reply, recall_memory or "")
        if reply != _mirror_before:
            _clog(
                bot, _conv_channel(message), "mirror_pass",
                trace_id=str(message.id),
                before=_mirror_before[:400], after=reply[:400],
            )

        # Send as a reply to the triggering message
        await message.reply(
            reply, mention_author=False, allowed_mentions=_ALLOWED_MENTIONS
        )
        self_name = bot.config.bot.name
        _clog(
            bot, _conv_channel(message), "message_out",
            trace_id=str(message.id), kind="spontaneous", author=self_name,
            content=reply, parts=1, react_emoji=react_emoji,
        )
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(message.channel.id, content=reply)

        bot.memory.append_prelude(str(message.channel.id), self_name, reply)
        bot.memory.append_message(
            str(message.channel.id), self_name, reply, platform="discord"
        )
        logger.info("Spontaneous intervention in #{ch}", ch=getattr(message.channel, 'name', 'dm'))
        if recall_memory:
            logger.info("Memory recall for {user}: {mem}", user=message.author.display_name, mem=recall_memory[:80])

    except Exception as e:
        logger.error("Spontaneous intervention error: {e}", e=e)


