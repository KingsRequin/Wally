# bot/intelligence/gate.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from bot.core.llm.base import BaseLLMClient
from bot.core.self_trace import COMPACT_LIMIT, current_self_trace_block
from bot.intelligence.identity import bot_name, render_identity
from bot.intelligence.memory.facts import AtomicFact, FactCategory, SQLiteFactStore

_DEFAULT_PROMPTS_DIR = Path(__file__).parent / "persona" / "prompts"

# Durée de vie d'une trace « j'ai ignoré ce message ». Elle sert à ne pas répondre
# en décalé à un message déjà écarté ; passé ce délai elle n'apprend plus rien.
_IGNORE_TRACE_TTL_HOURS = 24


_GATE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision":      {"type": "string", "enum": ["RESPOND", "IGNORE", "REACT", "DEFER"]},
        "emoji":         {"type": ["string", "null"]},
        "defer_seconds": {"type": ["integer", "null"]},
        "reason":        {"type": ["string", "null"]},
    },
    "required": ["decision"],
    "additionalProperties": False,
}

_FALLBACK_SYSTEM = (
    "Tu es le filtre de réponse de {{BOT_NAME}}. Retourne une décision: RESPOND, IGNORE, REACT ou DEFER."
)


@dataclass
class GateDecision:
    decision:      str             # RESPOND | IGNORE | REACT | DEFER
    emoji:         str | None = None
    defer_seconds: int | None = None
    reason:        str | None = None


class ResponseGate:
    """Décide comment Wally réagit à chaque message entrant.

    Appelé avant toute génération de réponse. Utilise deepseek-v4-flash,
    thinking disabled, pour minimiser la latence (<1s).
    """

    def __init__(
        self,
        llm: BaseLLMClient,
        fact_store: SQLiteFactStore,
        prompts_dir: str | Path = _DEFAULT_PROMPTS_DIR,
    ) -> None:
        self._llm = llm
        self._fact_store = fact_store
        self._system = self._load_system(prompts_dir)

    @staticmethod
    def _load_system(prompts_dir: str | Path) -> str:
        path = Path(prompts_dir) / "gate_system.md"
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return render_identity(content)
            logger.warning("gate_system.md est vide : {p}", p=path)
        except FileNotFoundError:
            logger.warning("gate_system.md introuvable : {p}", p=path)
        return render_identity(_FALLBACK_SYSTEM)

    async def decide(
        self,
        message_content: str,
        author_user_id: str,
        emotion_state: dict[str, float],
        relationship_facts: list[AtomicFact],
        active_desires: list[AtomicFact],
        is_ignored: bool = False,
        is_mentioned: bool = False,
        is_triggered: bool = False,
        is_dm: bool = False,
        wally_last_message: str | None = None,
        available_emojis: list[str] | None = None,
        emoji_usage: list[str] | None = None,
        recent_messages: list[dict] | None = None,
        thread_depth: int = 0,
        unanswered_question_age_s: float | None = None,
    ) -> GateDecision:
        """Retourne la décision de Wally pour ce message."""
        if is_ignored:
            return GateDecision(decision="IGNORE", reason="utilisateur marqué comme ignoré")
        # DM 1:1 : l'utilisateur s'adresse forcément à Wally. Répondre est la règle ;
        # le gate (conçu pour filtrer le bruit d'un salon) n'a pas lieu d'être ici.
        if is_dm:
            return GateDecision(decision="RESPOND", reason="DM 1:1 — réponse systématique")

        dominant_emotion, dominant_value = max(
            emotion_state.items(), key=lambda x: x[1], default=("boredom", 0.0)
        )
        if is_triggered:
            trigger_line = f"L'utilisateur a appelé {bot_name()} par son nom — répondre est la norme, ignorer l'exception."
        elif is_mentioned:
            trigger_line = f"@{bot_name()} mentionné directement."
        elif unanswered_question_age_s is not None:
            # Le seul cas où {{BOT_NAME}} peut ouvrir la bouche sans qu'on l'ait
            # nommé. Le dire explicitement, plutôt que de le laisser sous
            # « message passif » : un prompt qui ment sur ce qui l'a réveillé
            # produit des réponses hors-sol (précédent des faux raids d'overlay).
            trigger_line = (
                f"Question posée au chat il y a {int(unanswered_question_age_s)} s, "
                f"sans appeler {bot_name()}. Le fil ci-dessous est TOUT ce qui a été "
                f"dit depuis : à toi de juger si quelqu'un y a déjà répondu."
            )
        else:
            trigger_line = f"Message passif dans le channel (sans appel direct à {bot_name()})."
        context_parts = [
            f"Message reçu : {message_content[:500]}",
            trigger_line,
        ]
        if recent_messages:
            thread = "\n".join(
                f"  {m.get('author', '?')}: {(m.get('content') or '')[:200]}"
                for m in recent_messages[-5:]
            )
            context_parts.append(
                "Fil récent du canal (pour juger si une réponse a du sens dans le contexte) :\n"
                + thread
            )
        # La profondeur du fil : sans elle, le dixième aller-retour d'affilée
        # avec la même personne arrivait ici exactement comme le premier. 38 le
        # 12/08 sur une seule chaîne — un tiers de la production du jour.
        if thread_depth >= 2:
            context_parts.append(
                f"Tu as déjà répondu {thread_depth} fois d'affilée à cette personne, "
                f"sans que personne d'autre ne t'occupe entre-temps."
            )
        context_parts.append(f"Émotion dominante : {dominant_emotion} ({dominant_value:.2f})")
        if wally_last_message:
            context_parts.append(f"{bot_name()} vient de parler dans ce canal : \"{wally_last_message[:200]}\"")
        # Ce qu'il vient de faire AILLEURS. La porte ne voyait que ce canal-ci :
        # elle laissait passer un neuvième aller-retour sur Twitch sans savoir
        # qu'il ignorait la même personne sur Discord, et rouvrait un bingo
        # qu'il venait d'ouvrir. Forme COMPACTE (5 actes, sans consigne) : elle
        # tourne à chaque message reçu et doit rester bon marché.
        if actes := current_self_trace_block(limit=COMPACT_LIMIT, compact=True):
            context_parts.append(actes)
        if relationship_facts:
            rel_summary = " | ".join(f.content for f in relationship_facts[:3])
            context_parts.append(f"Relation connue : {rel_summary}")
        if active_desires:
            desire_summary = " | ".join(f.content for f in active_desires[:2])
            context_parts.append(f"Désirs actifs de {bot_name()} : {desire_summary}")
        if available_emojis:
            sample = ", ".join(f":{n}:" for n in available_emojis[:60])
            context_parts.append(
                f"Emotes custom dispo (tous tes serveurs, animées incluses — tu peux "
                f"réagir avec : renvoie le nom entre deux-points, ex. :{available_emojis[0]}:) : {sample}"
            )
        if emoji_usage:
            context_parts.append(
                "Usage que tu connais de certaines emotes (privilégie-les quand le contexte colle) : "
                + " ; ".join(emoji_usage[:30])
            )

        user_msg = "\n".join(context_parts)

        try:
            result = await self._llm.complete_structured(
                system_prompt=self._system,
                messages=[{"role": "user", "content": user_msg}],
                schema=_GATE_SCHEMA,
                schema_name="gate_decision",
                purpose="gate",
            )
            # Normalisée ET vérifiée contre l'enum du schéma. Aucun provider ne
            # garantit l'énumération — `complete_structured` force un tool_choice
            # sans validation post-hoc. Une réponse « ignore » en minuscules
            # traversait, le test de l'appelant (`in ("IGNORE","DEFER","REACT")`)
            # était faux, et Wally RÉPONDAIT alors qu'il avait décidé de se
            # taire — pendant que `conv_log` écrivait « ignore ». Le journal
            # affirmait l'inverse du comportement observé.
            _brut = str(result.get("decision") or "").strip().upper()
            if _brut not in ("RESPOND", "IGNORE", "REACT", "DEFER"):
                logger.warning(
                    "ResponseGate : décision hors enum {d!r} → RESPOND",
                    d=result.get("decision"),
                )
                _brut = "RESPOND"
            decision = GateDecision(
                decision=_brut,
                emoji=result.get("emoji"),
                defer_seconds=result.get("defer_seconds"),
                reason=result.get("reason"),
            )
            if decision.decision == "IGNORE" and decision.reason:
                # Sans motif, la trace n'apprend rien sur personne et encombre la
                # mémoire long terme — on ne l'écrit pas. Avec motif, elle sert à
                # ne pas répondre en décalé à un message déjà écarté : utile sur
                # quelques heures, pas au-delà, d'où la péremption.
                await self._fact_store.add(AtomicFact(
                    user_id=author_user_id,
                    content=f"{bot_name()} a choisi d'ignorer ce message — {decision.reason}",
                    category=FactCategory.EMOTION,
                    confidence=0.9,
                    source="gate",
                    expires_at=datetime.utcnow() + timedelta(hours=_IGNORE_TRACE_TTL_HOURS),
                ))
            return decision

        except Exception as e:
            logger.warning("ResponseGate.decide() failed, fallback RESPOND: {e!r}", e=e)
            return GateDecision(decision="RESPOND")
