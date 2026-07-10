from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from bot.intelligence.identity import render_identity
from bot.intelligence.meta_agent import MetaDecision, parse_decisions

_EMO_FR = {
    "anger": "colère", "joy": "joie", "curiosity": "curiosité",
    "sadness": "tristesse", "boredom": "ennui",
}

# Consigne de langue renforcée, injectée à la FIN du message user (juste avant la
# génération) dès la 1re passe : le rappel placé au point de génération réduit à la
# source les dérapages en anglais de DeepSeek. La même consigne sert de dernier
# recours en régénération — source unique, formulation identique.
_FR_DIRECTIVE = (
    "⚠️ IMPÉRATIF : pense et écris EXCLUSIVEMENT en français, "
    "pas un mot d'anglais dans ton raisonnement."
)


def _one_line(text: str, limit: int = 220) -> str:
    """Rend un texte sur une seule ligne, tronqué proprement avec ellipse.

    Neutralise les retours à la ligne internes (qui casseraient le format
    « [canal] auteur: … » et feraient perdre l'attribution à la 2e ligne) et
    marque toute troncature par « … » — sans quoi un message simplement coupé à
    l'affichage paraît *incomplet* à Wally, qui rumine alors la « suite » absente.
    """
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[:limit].rstrip() + "…"


def _fmt_emotions(state: dict[str, float]) -> str:
    """Formate les émotions de façon qualitative — pas de chiffres bruts."""
    parts = []
    for name, val in sorted(state.items(), key=lambda x: -x[1]):
        if val >= 0.65:
            intensity = "fort"
        elif val >= 0.35:
            intensity = "modéré"
        elif val >= 0.15:
            intensity = "léger"
        else:
            continue
        parts.append(f"{_EMO_FR.get(name, name)} {intensity}")
    return ", ".join(parts) if parts else "neutre"


@dataclass
class ReasoningResult:
    thought_text: str                    # la pensée privée (reasoning_content)
    thought_fact_id: int | None
    decisions: list[MetaDecision] = field(default_factory=list)


class ReasoningAgent:
    """Reasoning unifié : un seul appel LLM qui *pense* (raisonnement privé) ET
    *décide* (tags d'action publics).

    Fusion d'InnerMonologue (qui pensait) et de MetaAgent (qui décidait) en un
    appel `complete_with_reasoning` :
    - `reasoning` (reasoning_content / `<think>`) = la pensée privée → stockée en
      THOUGHT, jamais montrée à l'utilisateur.
    - `content` = la sortie publique = uniquement des tags d'action → parsés via
      `parse_decisions`.
    """

    def __init__(self, llm, fact_store, prompts_dir: str | Path, channels_text: str = "", capabilities_text: str = "", channel_names: dict[str, str] | None = None) -> None:
        self._llm = llm
        self._facts = fact_store
        self._system = render_identity((Path(prompts_dir) / "reasoning_system.md").read_text(encoding="utf-8"))
        self._channels_text = channels_text
        self._capabilities_text = capabilities_text
        self._channel_names = channel_names or {}
        # Garde langue FR (Phase 4) : détecte un monologue parti en anglais.
        from bot.core.language import LanguageDetector
        self._lang = LanguageDetector("fr")

    async def reason(self, context) -> ReasoningResult:
        # Consigne FR placée en toute fin de message user (au point de génération)
        # dès la 1re passe : réduit à la source les monologues qui partent en
        # anglais, au lieu de ne corriger qu'après coup par régénération.
        user_msg = self._format_context(context) + "\n\n" + _FR_DIRECTIVE
        content, reasoning = await self._llm.complete_with_reasoning(
            self._system, [{"role": "user", "content": user_msg}]
        )

        # La pensée privée = le raisonnement ; à défaut (serveur sans
        # reasoning_content), on retombe sur le content pour ne pas perdre la trace.
        thought_text = reasoning or content

        # Garde langue FR (Phase 4) : si le monologue part en anglais, UNE
        # régénération avec consigne renforcée. S'il reste anglais, on publie
        # quand même (ne jamais bloquer le tick) mais on logge un WARNING.
        if thought_text and self._lang.detect(thought_text) == "en":
            logger.warning("ReasoningAgent: monologue en anglais → régénération FR")
            # user_msg se termine déjà par _FR_DIRECTIVE : on renchérit d'un cran
            # (dernier recours) plutôt que de dupliquer la même consigne.
            fr_msg = (
                user_msg
                + "\n\nTa dernière réponse était en anglais. RECOMMENCE en français, "
                "intégralement — c'est non négociable."
            )
            content, reasoning = await self._llm.complete_with_reasoning(
                self._system, [{"role": "user", "content": fr_msg}]
            )
            thought_text = reasoning or content
            if thought_text and self._lang.detect(thought_text) == "en":
                logger.warning("ReasoningAgent: toujours en anglais après régénération — publié tel quel")
        thought_fact_id: int | None = None
        if thought_text:
            from bot.intelligence.memory.facts import AtomicFact, FactCategory
            now = datetime.now(timezone.utc)
            thought = AtomicFact(
                user_id="wally:self",
                content=thought_text,
                category=FactCategory.THOUGHT,
                confidence=1.0,
                created_at=now,
                last_seen_at=now,
            )
            thought_fact_id = await self._facts.add(thought)
            logger.debug("Reasoning : pensée stockée #{}", thought_fact_id)

        # Le content (tags) porte les décisions. parse_decisions retombe sur
        # [THINK] si content est vide.
        decisions = parse_decisions(content)
        if "SPEAK" in content and not any(d.action == "SPEAK" for d in decisions):
            logger.warning("ReasoningAgent: intention SPEAK non parsée — content brut : {}", content[:300])
        logger.debug("ReasoningAgent: {} décision(s) — {}", len(decisions), [d.action for d in decisions])

        return ReasoningResult(
            thought_text=thought_text,
            thought_fact_id=thought_fact_id,
            decisions=decisions,
        )

    def _format_context(self, ctx) -> str:
        lines: list[str] = []
        if getattr(ctx, "web_finding", None):
            lines.append(
                "**Tu viens de chercher sur le web — voici ce que tu as trouvé :**\n"
                f"{ctx.web_finding}\n"
                "(Réagis à cette info : ce qu'elle t'apprend, ce que tu en penses. Tu peux "
                "la mémoriser ([ACT create_memory]), la partager si c'est pertinent, ou "
                "juste y réfléchir. Ne relance PAS de recherche maintenant.)"
            )
        if getattr(ctx, "preoccupation", None):
            lines.append(
                f"**Ta préoccupation du moment (ton fil de pensée) :** {_one_line(ctx.preoccupation, 400)}\n"
                f"(Fais-la avancer si ta pensée progresse — mets-la à jour via "
                f"[ACT set_focus] ; sinon laisse-la mûrir.)"
            )
        if getattr(ctx, "emotional_drive", None):
            lines.append(
                f"**Ce que ton émotion te pousse à faire :** {ctx.emotional_drive}\n"
            )
        if getattr(ctx, "idle_seed", None):
            # Quand aucun focus ne t'occupe (préoccupation absente/expirée),
            # l'amorce PRIME : présentée comme une bifurcation franche pour éviter
            # de retomber dans le fil qu'on vient de clore (Phase 2a).
            if not getattr(ctx, "preoccupation", None):
                lines.append(
                    f"**Personne ne te sollicite, et tu as fait le tour de ce qui "
                    f"t'occupait.** Pars sur du neuf, à partir de : {ctx.idle_seed}\n"
                    f"(Pense pour toi. Tu n'es pas obligé de parler — le plus souvent, "
                    f"garde ça interne. Ne reviens pas sur le sujet que tu viens de clore.)"
                )
            else:
                lines.append(
                    f"**Personne ne te sollicite là.** Laisse ton esprit vagabonder "
                    f"à partir de : {ctx.idle_seed}\n"
                    f"(Pense pour toi. Tu n'es pas obligé de parler — le plus souvent, "
                    f"garde ça interne.)"
                )
            # Amorce issue d'un flux RSS : c'est une friction PRIVÉE pour nourrir ta
            # pensée, pas un sujet à diffuser. Balancer un avis sur un article que
            # personne d'autre n'a vu, dans un canal calme, c'est parler tout seul —
            # même si l'avis est « bon ». Il ne s'ouvre au [SPEAK] que s'il rejoint
            # vraiment une personne ou une conversation en cours.
            if getattr(ctx, "rss_stimulus", None):
                lines.append(
                    "(⚠️ Cette actu vient de TON fil perso — personne d'autre ne l'a "
                    "vue. C'est une friction pour ta pensée, pas un sujet à balancer. "
                    "En sortir un avis dans un canal calme, c'est parler tout seul, "
                    "même si l'avis est juste. Ne la ressors en [SPEAK] QUE si elle "
                    "accroche vraiment quelqu'un de présent ou une conversation vivante "
                    "— sinon, elle nourrit ta réflexion en interne, point.)"
                )
        if self._channels_text:
            lines.append(self._channels_text + "\n")
        if self._capabilities_text:
            lines.append(
                f"**Ce que tu es et sais faire (ton self-model) :**\n{self._capabilities_text}\n"
            )
        if getattr(ctx, "self_narrative", None):
            lines.append(
                f"**Là où tu en es de qui tu deviens :** {ctx.self_narrative}"
            )
        if getattr(ctx, "upgrade_requests", None):
            _labels = {
                "requested": "en attente d'autorisation",
                "delivered": "DÉJÀ LIVRÉE — tu l'as",
                "declined": "refusée par ton créateur",
                "abandoned": "abandonnée",
            }
            lines.append(
                "**Améliorations que tu as déjà demandées (ne les redemande pas) :**"
            )
            for u in ctx.upgrade_requests:
                status = _labels.get(getattr(u, "status", ""), getattr(u, "status", ""))
                day = (getattr(u, "created_at", "") or "")[:10]
                lines.append(f"  · {_one_line(u.proposal, 120)} — {status} ({day})")
        if getattr(ctx, "relationships", None):
            lines.append("**Ce que tu penses des gens (tes affinités) :**")
            for rel in ctx.relationships:
                lines.append(f"  · {rel.content}")
        if getattr(ctx, "participant_memories", None):
            lines.append(
                "**Ce que tu sais des personnes présentes"
                " (le `<@id>` entre parenthèses est leur identifiant de ping) :** "
                "quand tu t'adresses à l'une d'elles — surtout pour lui poser une "
                "question — écris ce `<@id>` à la place de son pseudo, sinon elle "
                "n'est PAS notifiée et peut ne jamais voir ton message."
            )
            for pm in ctx.participant_memories:
                facts = " ; ".join(pm.get("facts", []))
                mention = pm.get("mention", "")
                name = pm.get("author", "?")
                who = f"{name} ({mention})" if mention else name
                lines.append(f"  · {who} : {facts}")
        if getattr(ctx, "member_presence", None):
            lines.append(
                "**Qui est là en ce moment (barre latérale Discord) :** tiens-en "
                "compte avant de solliciter quelqu'un — ne dérange pas une personne "
                "en « ne pas déranger » ou en pleine game, laisse tranquille qui est "
                "inactif ou hors ligne."
            )
            for line in ctx.member_presence:
                lines.append(f"  · {line}")
        if getattr(ctx, "mention_directory", None):
            lines.append(
                "**Pour t'adresser à quelqu'un (le NOTIFIER) :** insère son "
                "identifiant au format `<@id>` dans ton message (ex : « <@123> tu "
                "penses quoi ? »). Le simple texte « @pseudo » ou son prénom nu ne "
                "notifie personne — la personne peut ne jamais voir ta question. "
                "Quand tu poses une question à un membre précis, ping-le. N'écris "
                "JAMAIS @everyone ni @here."
            )
            for line in ctx.mention_directory:
                lines.append(f"  · {line}")
        if getattr(ctx, "emotes_known", None) or getattr(ctx, "emotes_unknown", None):
            lines.append(
                "**Emotes custom des serveurs.** Pour AFFICHER une emote dans ton "
                "message, écris EXACTEMENT son code `<:nom:id>` (le raccourci `:nom:` "
                "seul ne s'affiche pas pour un bot, il reste en texte brut). Colle le "
                "code tel quel, sans le modifier."
            )
        if getattr(ctx, "emotes_known", None):
            lines.append(
                "Emotes dont tu connais l'usage : " + " ; ".join(ctx.emotes_known[:10])
            )
        if getattr(ctx, "emotes_unknown", None):
            sample = ", ".join(ctx.emotes_unknown[:20])
            lines.append(
                f"Emotes dispo dont tu ignores encore l'usage (tu peux quand même les "
                f"poster) : {sample}\n"
                f"(Si l'une t'intrigue vraiment, demande à ton créateur en DM à quoi "
                f"elle sert — groupe plusieurs emotes en une seule question, reste rare. "
                f"Quand il t'explique, enregistre-le via [ACT note_emote].)"
            )
        if getattr(ctx, "social_receptivity", None):
            lines.append(
                f"**Rythme social (conscience, pas une consigne)** : {ctx.social_receptivity}"
            )
        lines.extend([
            f"**Heure :** {ctx.time_of_day}",
            f"**État émotionnel :** {_fmt_emotions(ctx.emotion_state)}",
        ])
        if getattr(ctx, "host_metrics", None):
            # Supprimer les métriques si un SPEAK récent (<60 min) les mentionnait
            # déjà — évite de répéter "56°C ça tient" à chaque tick idle.
            _now = time.time()
            _recent_sp = getattr(ctx, "recent_speaks", [])
            _metrics_keywords = ("°C", "RAM", "charge", "CPU")
            _already_spoken = any(
                any(kw in sp.get("content", "") for kw in _metrics_keywords)
                and _now - sp.get("ts", 0) < 3600
                for sp in _recent_sp
            )
            if not _already_spoken:
                lines.append(f"**Ton serveur :** {ctx.host_metrics}")
        if getattr(ctx, "weather_fr", None):
            lines.append(f"**Météo en France en ce moment :** {ctx.weather_fr}")
        if ctx.active_desires:
            lines.append("**Désirs actifs :**")
            for d in ctx.active_desires[:3]:
                did = getattr(d, "id", None)
                prefix = f"#{did} — " if did is not None else ""
                lines.append(f"  {prefix}{d.content}")
        if ctx.active_goals:
            lines.append("**Tes objectifs en cours :**")
            for g in ctx.active_goals[:3]:
                gid = getattr(g, "id", None)
                prefix = f"#{gid} — " if gid is not None else ""
                lines.append(f"  {prefix}{g.content}")
        # En vagabondage SANS focus, on n'injecte PAS la dernière pensée : c'est
        # elle qui ré-amorce la boucle de rumination (l'amorce de nouveauté doit
        # primer). On la garde quand un focus est en cours ou hors idle (Phase 2a).
        _idle_no_focus = bool(getattr(ctx, "idle_seed", None)) and not getattr(ctx, "preoccupation", None)
        if ctx.recent_thoughts and not _idle_no_focus:
            lines.append(f"**Dernière pensée :** {_one_line(ctx.recent_thoughts[0].content, 300)}")
        if ctx.recent_interactions:
            recent = ctx.recent_interactions[-10:]
            last = recent[-1]
            last_name = self._channel_names.get(last.get("channel", ""), last.get("channel", "?"))
            last_label = (
                f"DM privé avec {last.get('author', '?')}" if last.get("is_dm")
                else f"#{last_name}"
            )
            lines.append(
                f"**Canal où tu peux parler maintenant :** {last_label} "
                f"(id {last.get('channel', '?')} — n'émets [SPEAK <id> ...] qu'avec cet id exact)"
            )
            lines.append(
                "**Conversations récentes — chaque bloc est une conversation SÉPARÉE.** "
                "Ne ramène JAMAIS dans un canal un sujet entendu dans un autre. "
                "Un bloc « DM privé » ne doit JAMAIS être évoqué ailleurs, et inversement."
            )
            # Regroupe en préservant l'ordre d'apparition des canaux.
            groups: dict[str, list[dict]] = {}
            order: list[str] = []
            for msg in recent:
                ch = msg.get("channel", "?")
                if ch not in groups:
                    groups[ch] = []
                    order.append(ch)
                groups[ch].append(msg)
            for ch in order:
                msgs = groups[ch]
                if msgs[0].get("is_dm"):
                    title = f"### DM privé avec {msgs[0].get('author', '?')}"
                else:
                    title = f"### #{self._channel_names.get(ch, ch)} (id {ch})"
                lines.append(title)
                for msg in msgs:
                    mid = msg.get("message_id")
                    mid_part = f"(msg {mid}) " if mid else ""
                    lines.append(
                        f"  {mid_part}{msg.get('author', '?')}: "
                        f"{_one_line(msg.get('content', ''), 220)}"
                    )
        if getattr(ctx, "spontaneous_outreach", None):
            lines.append("**Tes messages spontanés restés sans réponse :**")
            for o in ctx.spontaneous_outreach:
                mins = max(1, o.get("seconds_since", 0) // 60)
                lines.append(
                    f"  canal {o.get('channel', '?')} : {o.get('unanswered', 0)} message(s) "
                    f"envoyé(s), aucune réponse depuis ~{mins} min."
                )
        recent_speaks = getattr(ctx, "recent_speaks", [])
        if recent_speaks:
            _now = time.time()
            lines.append("**Tes derniers messages envoyés spontanément :**")
            for sp in recent_speaks[-3:]:
                secs = int(_now - sp.get("ts", _now))
                mins = max(1, secs // 60)
                lines.append(
                    f"  canal {sp.get('channel', '?')} (il y a ~{mins} min) : "
                    f"{_one_line(sp.get('content', ''))}"
                )
        return "\n".join(lines)
