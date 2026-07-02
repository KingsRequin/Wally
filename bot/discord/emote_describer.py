# bot/discord/emote_describer.py
"""Auto-description des emotes custom du serveur principal.

Wally connaît déjà le NOM et le CODE postable de toutes les emotes custom de ses
serveurs (cf. `attention_agent.emote_provider`), mais IGNORE ce que chacune veut
dire tant que le créateur ne le lui a pas expliqué une par une en MP
([ACT note_emote]). Ce service comble ce vide de façon autonome : pour chaque
emote du serveur principal encore sans note d'usage, il fait « voir » l'image à
Wally (`VisionService`, seule vue réelle du bot puisque DeepSeek est aveugle) et
en déduit une courte description d'usage, stockée au MÊME format que les notes
manuelles ("nom → usage", faits PREF sous "wally:emotes"). L'awareness emote
existante (known/unknown) la consomme donc sans modification.

Le créateur garde le dernier mot : une explication manuelle ultérieure archive
la note (cf. `action_dispatcher.note_emote`, qui matche par préfixe "nom →"), et
ce service ne touche jamais une emote qui a déjà une note (manuelle ou auto) →
idempotent, sûr à relancer à chaque boot.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

from bot.intelligence.memory.facts import AtomicFact, FactCategory

if TYPE_CHECKING:  # pragma: no cover
    import discord

# Source des faits générés automatiquement — distincte de "emote_note" (manuel)
# pour tracer l'origine et refléter une confiance moindre qu'une explication humaine.
AUTO_SOURCE = "emote_auto"
_AUTO_CONFIDENCE = 0.8
_MAX_USAGE_CHARS = 160


@dataclass
class EmoteInfo:
    """Vue minimale d'une emote custom, découplée de `discord.Emoji` (testable)."""
    name: str
    code: str   # "<:nom:id>" / "<a:nom:id>" — le format postable
    url: str    # URL de l'image (PNG/GIF)


class EmoteDescriber:
    """Décrit automatiquement les emotes custom encore sans note d'usage."""

    def __init__(self, fact_store, vision, *, feed=None) -> None:
        self._facts = fact_store
        self._vision = vision
        self._feed = feed

    async def describe_new(self, emotes: list[EmoteInfo]) -> int:
        """Décrit les emotes sans note d'usage connue. Retourne le nombre décrit.

        Best-effort : une emote qui échoue (vision muette, erreur API) est
        simplement ignorée, jamais bloquante pour les suivantes.
        """
        if self._vision is None or not getattr(self._vision, "available", False):
            logger.info("EmoteDescriber: vision indisponible, auto-description ignorée")
            return 0
        if not emotes:
            return 0

        existing = await self._facts.get_by_user(
            "wally:emotes", categories=[FactCategory.PREF]
        )
        # Clé = nom nu (minuscule), comme la note manuelle "nom → usage".
        known_names = {
            f.content.split("→", 1)[0].strip().lower()
            for f in existing if "→" in f.content
        }

        described = 0
        for emote in emotes:
            if not emote.name or not emote.url:
                continue
            if emote.name.lower() in known_names:
                continue
            # Dédup intra-run : même emote sur plusieurs serveurs → une seule fois.
            known_names.add(emote.name.lower())
            usage = await self._describe_one(emote)
            if not usage:
                known_names.discard(emote.name.lower())  # retry possible plus tard
                continue
            now = datetime.utcnow()
            await self._facts.add(AtomicFact(
                user_id="wally:emotes",
                content=f"{emote.name} → {usage}",
                category=FactCategory.PREF,
                source=AUTO_SOURCE,
                confidence=_AUTO_CONFIDENCE,
                created_at=now,
                last_seen_at=now,
            ))
            described += 1
            logger.info("EmoteDescriber: :{}: → {}", emote.name, usage[:60])
            if self._feed is not None:
                try:
                    self._feed.publish(
                        {"type": "ACT", "detail": f"emote comprise : :{emote.name}:"}
                    )
                except Exception:  # noqa: BLE001 — le feed ne doit jamais bloquer
                    pass

        if described:
            logger.info(
                "EmoteDescriber: {} emote(s) décrite(s) automatiquement", described
            )
        return described

    async def _describe_one(self, emote: EmoteInfo) -> str | None:
        caption = (
            f"Cette image est une emote custom Discord nommée « {emote.name} ». "
            f"En une seule phrase courte et en français, dis à quelle émotion ou "
            f"réaction elle sert (par ex. rire, bravo/GG, salut, surprise, clin "
            f"d'œil, approbation). Réponds uniquement par l'usage, sans préambule."
        )
        try:
            usage = await self._vision.analyze(
                [emote.url], caption=caption, purpose="emote_description"
            )
        except Exception as e:  # noqa: BLE001 — jamais bloquant
            logger.warning("EmoteDescriber: analyse de :{}: échouée: {}", emote.name, e)
            return None
        if not usage:
            return None
        usage = usage.strip().strip('"').replace("\n", " ").strip()
        return usage[:_MAX_USAGE_CHARS] if usage else None


def _resolve_emote_guild(bot) -> "discord.Guild | None":
    """Détermine le serveur principal dont on décrit les emotes.

    Priorité : `config.discord.emote_guild_id` s'il est configuré et que le bot
    y est présent ; sinon, si le bot n'est que dans UN serveur, celui-là ; sinon
    None (ambigu — on log les serveurs pour que le créateur fixe la config).
    """
    guilds = list(getattr(bot, "guilds", []) or [])
    configured = getattr(bot.config.discord, "emote_guild_id", None)
    if configured:
        for g in guilds:
            if g.id == configured:
                return g
        logger.warning(
            "EmoteDescriber: emote_guild_id={} configuré mais le bot n'y est pas",
            configured,
        )
        return None
    if len(guilds) == 1:
        return guilds[0]
    if len(guilds) > 1:
        listing = ", ".join(f"{g.name} ({g.id})" for g in guilds)
        logger.warning(
            "EmoteDescriber: plusieurs serveurs et discord.emote_guild_id non "
            "configuré → auto-description désactivée. Serveurs : {}", listing,
        )
    return None


def _collect_emotes(guild) -> list[EmoteInfo]:
    """Extrait les emotes custom d'un serveur en `EmoteInfo` postables."""
    out: list[EmoteInfo] = []
    for e in getattr(guild, "emojis", []) or []:
        url = str(getattr(e, "url", "") or "")
        if not e.name or not url:
            continue
        out.append(EmoteInfo(name=e.name, code=str(e), url=url))
    return out


async def run_emote_description(bot, guild=None) -> int:
    """Point d'entrée orchestré (boot / mise à jour d'emotes).

    Résout le serveur principal (sauf si `guild` est fourni), collecte ses
    emotes et lance `EmoteDescriber`. Best-effort : ne lève jamais.
    """
    try:
        vision = getattr(bot, "vision", None)
        fact_store = getattr(bot, "fact_store", None)
        if vision is None or not getattr(vision, "available", False) or fact_store is None:
            return 0
        target = guild if guild is not None else _resolve_emote_guild(bot)
        if target is None:
            return 0
        emotes = _collect_emotes(target)
        if not emotes:
            return 0
        describer = EmoteDescriber(
            fact_store, vision, feed=getattr(bot, "cognitive_feed", None)
        )
        return await describer.describe_new(emotes)
    except Exception as e:  # noqa: BLE001 — jamais bloquant pour le boot
        logger.warning("EmoteDescriber: run a échoué: {}", e)
        return 0
