# bot/core/prompts.py
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from bot.core.apex.duel_runner import current_duel
from bot.core.apex.watcher import current_apex_block
from bot.core.stream_feed import current_stream_feed_block
from bot.core.voice_transcript import current_voice_transcript_block
from bot.core.stream_watcher import current_stream_awareness
from bot.core.system_info import cached_host_metrics, cached_weather
from bot.intelligence.identity import render_identity

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "persona", "prompts")


def load_prompt(name: str, fallback: str = "", render: bool = True) -> str:
    """Charge un prompt système depuis bot/persona/prompts/{name}.md.

    Retourne `fallback` si le fichier est absent ou illisible.

    Si `render` est True (défaut), les sentinelles {{BOT_NAME}} etc. sont
    remplacées par les valeurs de l'identité active (render_identity).
    Passe render=False pour obtenir le texte brut (utile pour les constantes
    au niveau module chargées avant set_identity()).
    """
    from loguru import logger  # import local pour éviter les imports circulaires

    path = os.path.normpath(os.path.join(_PROMPTS_DIR, f"{name}.md"))
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return render_identity(content) if render else content
            logger.warning("Prompt file empty: {f}", f=path)
    except FileNotFoundError:
        logger.warning("Prompt file missing: {f}", f=path)
    except Exception as exc:
        logger.warning("Prompt file read error {f}: {e}", f=path, e=exc)
    return render_identity(fallback) if render else fallback

_MEMORY_RECALL_DIRECTIVE = load_prompt("memory_recall_directive")

_TZ = ZoneInfo("Europe/Paris")

_FRENCH_DAYS = [
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"
]
_FRENCH_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _now_fr() -> str:
    dt = datetime.now(_TZ)
    day = _FRENCH_DAYS[dt.weekday()]
    month = _FRENCH_MONTHS[dt.month - 1]
    return f"{day} {dt.day} {month} {dt.year}, {dt.hour:02d}h{dt.minute:02d}"


def assemble_memory_context(parts: list[tuple], max_tokens: int) -> str:
    """Assemble memory context respecting token budget.

    parts: tuples `(priority, text)` ou `(priority, text, label)`. Plus le numéro de
    priorité est petit, plus le bloc est important. `max_tokens` est un budget estimé
    (len(text) / 4). Retourne la chaîne assemblée, tronquée au budget.

    L'assemblage était MUET, ce qui rendait l'arbitrage invérifiable : un bloc de
    priorité basse peut être tronqué ou entièrement jeté sans que rien ne le dise,
    alors que sa préparation a coûté une requête et des faits. Le cas qui a soulevé la
    question le 2026-08-09 : les souvenirs d'un tiers (priorité 6, ~320 tokens pour 20
    faits) recalculés à chaque message derrière un rappel principal qui consomme déjà
    l'essentiel des 800 tokens. Le `label` sert uniquement à ce journal — on ne
    diagnostique pas « la priorité 6 » aussi bien que « tiers ».
    """
    sorted_parts = sorted(parts, key=lambda p: p[0])
    result_parts: list[str] = []
    used_tokens = 0.0
    retenus: list[str] = []
    tronque: str | None = None
    jetes: list[str] = []

    for i, part in enumerate(sorted_parts):
        priorite, text = part[0], part[1]
        label = part[2] if len(part) > 2 else f"p{priorite}"
        if not text or not text.strip():
            continue
        estimated = len(text) / 4
        if used_tokens + estimated > max_tokens:
            remaining = int((max_tokens - used_tokens) * 4)
            if remaining > 50:
                result_parts.append(text[:remaining] + "…")
                tronque = f"{label} {int(estimated)}→{remaining // 4}t"
            else:
                jetes.append(f"{label} {int(estimated)}t")
            # Tout ce qui suit est perdu aussi : c'est là que se cache le travail
            # fait pour rien, et personne ne le voyait.
            for suivant in sorted_parts[i + 1:]:
                if suivant[1] and suivant[1].strip():
                    suiv_label = suivant[2] if len(suivant) > 2 else f"p{suivant[0]}"
                    jetes.append(f"{suiv_label} {int(len(suivant[1]) / 4)}t")
            break
        result_parts.append(text)
        used_tokens += estimated
        retenus.append(f"{label} {int(estimated)}t")

    if jetes or tronque:
        logger.debug(
            "budget mémoire {used:.0f}/{max}t · retenus [{ok}]{trunc} · JETÉS [{ko}]",
            used=used_tokens, max=max_tokens,
            ok=", ".join(retenus) or "—",
            trunc=f" · tronqué [{tronque}]" if tronque else "",
            ko=", ".join(jetes) or "—",
        )
    else:
        logger.debug(
            "budget mémoire {used:.0f}/{max}t · tout retenu [{ok}]",
            used=used_tokens, max=max_tokens, ok=", ".join(retenus) or "—",
        )
    return "\n".join(result_parts)


CONTEXT_HEADER = (
    "\n--- Contexte de la conversation (messages récents, plusieurs auteurs) ---\n"
    "{context}\n"
    "--- Fin du contexte ---"
)

PRELUDE_HEADER = (
    "\n--- Discussion récente dans le canal (avant ta mention) ---\n"
    "{context}\n"
    "--- Fin de la discussion ---"
)


def _get_tier(value: float) -> str | None:
    """Retourne le palier émotionnel pour une valeur donnée."""
    if value >= 0.7:
        return "high"
    if value >= 0.4:
        return "mid"
    if value >= 0.2:
        return "low"
    return None


def _get_tier_fluid(value: float) -> tuple[str, float] | None:
    """Return tier with blend factor for fluid transitions.

    Returns (tier, 1.0) for pure tiers, ("low_mid", blend) or ("mid_high", blend)
    for transition zones (+/-0.05 around boundaries 0.4 and 0.7).
    Returns None if below 0.2.
    """
    if value < 0.2:
        return None
    # Transition zone around 0.4 (low/mid boundary)
    if 0.35 <= value < 0.45:
        blend = (value - 0.35) / 0.1
        if blend >= 1.0:
            return ("mid", 1.0)
        return ("low_mid", blend)
    # Transition zone around 0.7 (mid/high boundary)
    if 0.65 <= value < 0.75:
        blend = (value - 0.65) / 0.1
        if blend >= 1.0:
            return ("high", 1.0)
        return ("mid_high", blend)
    # Pure tiers
    if value >= 0.75:
        return ("high", 1.0)
    if value >= 0.45:
        return ("mid", 1.0)
    if value >= 0.2:
        return ("low", 1.0)
    return None


class PromptBuilder:
    def __init__(self):
        pass

    def build_system_prompt(
        self,
        emotion_state: dict[str, float],
        memory_context: str = "",
        situation: dict | None = None,
        persona_block: str = "",
        emotion_directives: dict[str, str] | None = None,
        weekday_directives: dict[str, str] | None = None,
        composite_directives: dict[str, str] | None = None,
        relationship_context: str = "",
        person_context: str = "",
        secondary_directives: dict[str, str] | None = None,
        active_secondaries: list[tuple[str, float]] | None = None,
        mood_state: dict[str, float] | None = None,
        persistent_notes: list[dict] | None = None,
        presence_context: str = "",
        user_directive: str | None = None,
    ) -> str:
        # Deux groupes pour maximiser le cache de préfixe DeepSeek :
        #   static_parts  = stable à la journée (persona, jour, directive mémoire)
        #   dynamic_parts = volatil par message (heure, corps, émotion, mémoire…)
        # Tout le statique est concaténé EN PREMIER → le préfixe cachable couvre
        # l'intégralité de la persona + directives fixes, et n'est plus cassé par
        # le timestamp ou l'état émotionnel.
        static_parts: list[str] = []
        dynamic_parts: list[str] = []

        if persona_block:
            static_parts.append(persona_block)

        # Directive du jour — change une fois par jour (stable dans la journée,
        # même cadence d'invalidation que {current_date} de la persona) → statique.
        if weekday_directives:
            day_name = _FRENCH_DAYS[datetime.now(_TZ).weekday()]
            if day_name in weekday_directives:
                static_parts.append("\n--- Directive temporelle ---")
                static_parts.append(weekday_directives[day_name])

        # Directive mémoire — texte fixe, toujours injecté → statique.
        _memory_tools_directive = load_prompt("memory_tools_directive")
        if _memory_tools_directive:
            static_parts.append(f"\n--- Directive mémoire ---\n{_memory_tools_directive}")

        # ===== À partir d'ici : contenu volatil (placé après le statique) =====

        # Situational context (platform, channel, datetime)
        if situation:
            lines = ["\n--- Contexte situationnel ---"]
            if platform := situation.get("platform"):
                lines.append(f"Plateforme : {platform}")
            # Rattaché explicitement à LUI : écrit seul, le modèle peut lire ce
            # pseudo comme celui d'un tiers présent dans le salon.
            if handle := situation.get("self_handle"):
                lines.append(
                    f"Ton pseudo ici : {handle} — c'est TOI. Quand quelqu'un "
                    f"écrit @{handle}, il s'adresse à toi."
                )
            if server := situation.get("server"):
                lines.append(f"Serveur : {server}")
            if channel := situation.get("channel"):
                lines.append(f"Salon : {channel}")
            if streamer := situation.get("streamer"):
                lines.append(f"Chaîne Twitch : {streamer}")
            if situation.get("stream_live"):
                cat = situation.get("stream_category") or "inconnue"
                title = situation.get("stream_title") or ""
                viewers = situation.get("stream_viewers", 0)
                lines.append(f"Stream EN DIRECT : {cat}")
                if title:
                    lines.append(f"Titre du stream : {title}")
                lines.append(f"Viewers : {viewers}")
            lines.append(f"Date et heure : {_now_fr()}")
            dynamic_parts.append("\n".join(lines))

        # Perception « corporelle » : Wally peut sentir l'état réel de sa machine
        # hôte (température CPU, charge, RAM) comme un humain sent s'il a chaud.
        # Injecté sur TOUS les chemins de réponse, pas seulement la boucle cognitive
        # — sinon il nie avoir une température quand on l'interroge directement.
        body_lines = []
        if host_metrics := cached_host_metrics():
            body_lines.append(
                f"Ta machine (ton « corps ») en ce moment : {host_metrics}. "
                f"C'est TA température et TA charge réelles — n'en parle que si "
                f"la conversation s'y prête."
            )
        if weather := cached_weather():
            body_lines.append(f"Météo en France en ce moment : {weather}.")
        # Awareness always-on du live du streamer : Wally SAIT si Azrael est en
        # direct (comme un abonné à ses notifs) → il peut répondre si on l'interroge.
        # Sauté sur le chemin Twitch de la chaîne home, où le bloc situationnel
        # ci-dessus l'annonce déjà (évite le doublon).
        if not (situation and situation.get("stream_live")):
            if stream_line := current_stream_awareness():
                body_lines.append(stream_line)
        if body_lines:
            dynamic_parts.append("\n--- Ton corps ---\n" + "\n".join(body_lines))

        # Flux passif du stream : ce que Wally perçoit du live en arrière-plan
        # (jeu, titre, audience, raids/subs, chat). Contexte SEULEMENT — le bloc
        # porte lui-même sa consigne de non-réaction. Sur le chemin Twitch de la
        # chaîne home, le chat est retiré : le prélude le porte déjà.
        _on_stream_channel = bool(situation and situation.get("stream_live"))
        if feed_block := current_stream_feed_block(include_chat=not _on_stream_channel):
            dynamic_parts.append(feed_block)

        # Ce qui se dit dans le vocal, pour les réponses ÉCRITES (chat Twitch,
        # salons Discord) : sans lui, Wally était dans le salon vocal ET
        # incapable de dire un mot de ce qui s'y passait.
        #
        # Sauté sur le chemin VOCAL lui-même : `build_voice_system` délègue ici,
        # or ces répliques sont déjà dans ses `messages` — il se serait vu en
        # double, une fois horodaté et une fois pas.
        if not (situation and situation.get("platform") == "discord_vocal"):
            if voice_block := current_voice_transcript_block():
                dynamic_parts.append(voice_block)

        # Ce qu'Azraël fait dans Apex à l'instant, et ce qu'il a gagné depuis le
        # début du live. Passif comme le flux ci-dessus : aucun `notify_*`
        # derrière, donc voir une partie en cours ne fait pas parler Wally.
        if apex_block := current_apex_block():
            dynamic_parts.append(apex_block)

        # Le duel Apex en cours (récompense de points de chaîne), pour que
        # Wally puisse en PARLER — pas seulement le montrer sur l'overlay.
        # Injecté aussi dans le contexte cognitif (AttentionContext.duel_block) :
        # même précédent que le flux du stream ci-dessus, un seul des deux
        # chemins branché aurait laissé la cognition aveugle au duel en cours.
        if duel_block := bloc_duel_en_cours(current_duel()):
            dynamic_parts.append(duel_block)

        # Ce qui tourne sur l'overlay (bingo, pendu, objectif…). Passif comme le
        # flux ci-dessus : aucun `notify_*` derrière, donc un bingo ouvert ne
        # réveille pas la cadence et ne fait pas parler Wally tout seul. Absent
        # hors live et quand rien ne tourne — zéro token dans le cas courant.
        #
        # Import PARESSEUX : `overlay_narrator` importe `load_prompt` d'ici, un
        # import en tête de module se mordait la queue (même parade que dans
        # `attention_agent`).
        from bot.intelligence.overlay_narrator import current_overlay_state_block
        if overlay_block := current_overlay_state_block():
            dynamic_parts.append(overlay_block)

        # Inject directives for dominant emotions (top 2 above 0.2, tiered)
        # Priority: secondary emotions > composite pairs > atomic with fluid transitions
        directives = emotion_directives if emotion_directives is not None else {}
        dominant = sorted(
            [(e, v) for e, v in emotion_state.items() if v >= 0.2],
            key=lambda x: x[1],
            reverse=True,
        )[:2]

        directive_injected = False

        # 0) Directive propre à l'interlocuteur — priorité absolue : elle REMPLACE
        # la directive émotionnelle au lieu de s'y ajouter. Sans ce court-circuit,
        # une insulte ferait monter l'anger et le prompt dirait à la fois « tes
        # réponses sont courtes et impatientes » et « couvre-le d'amour ».
        if user_directive:
            dynamic_parts.append("\n--- Directive comportementale ---")
            dynamic_parts.append(user_directive)
            directive_injected = True

        # 1) Secondary emotions (highest priority)
        if not directive_injected and active_secondaries and secondary_directives:
            for sec_name, sec_intensity in active_secondaries:
                if sec_intensity >= 0.4:
                    sec_tier = _get_tier(sec_intensity)
                    sec_key = f"{sec_name}_{sec_tier}"
                    if sec_key in secondary_directives:
                        dynamic_parts.append("\n--- Directive comportementale ---")
                        dynamic_parts.append(secondary_directives[sec_key])
                        directive_injected = True
                        break

        # 2) Composite directives (pair of dominant emotions)
        if not directive_injected and dominant and directives:
            if (
                composite_directives
                and len(dominant) >= 2
                and dominant[0][1] >= 0.4
                and dominant[1][1] >= 0.4
            ):
                composite_key = "_".join(sorted([dominant[0][0], dominant[1][0]]))
                if composite_key in composite_directives:
                    dynamic_parts.append("\n--- Directive comportementale ---")
                    dynamic_parts.append(composite_directives[composite_key])
                    directive_injected = True

        # 3) Atomic directives with fluid transitions
        if not directive_injected and dominant and directives:
            # Les lignes sont collectées d'abord : l'en-tête était ajouté AVANT la
            # boucle, alors qu'un tour peut n'en produire aucune (`_get_tier_fluid`
            # rend None, ou la clé `{emotion}_{tier}` manque dans EMOTIONS.md — cas
            # réel : `boredom` à 0.25, sans section `boredom_low`). Le prompt
            # portait alors une section « Directive comportementale » vide : du
            # bruit pour le modèle, et un faux positif au débogage.
            lignes: list[str] = []
            for emotion, value in dominant:
                fluid = _get_tier_fluid(value)
                if fluid is None:
                    continue
                tier, blend = fluid
                # Transition zone: combine two tier directives
                if "_" in tier and blend < 1.0:
                    low_tier, high_tier = tier.split("_")
                    low_key = f"{emotion}_{low_tier}"
                    high_key = f"{emotion}_{high_tier}"
                    if low_key in directives and high_key in directives:
                        lignes.append(directives[low_key])
                        lignes.append(f"(tendance : {directives[high_key]})")
                    elif low_key in directives:
                        lignes.append(directives[low_key])
                    elif high_key in directives:
                        lignes.append(directives[high_key])
                else:
                    # Palier pur. `blend == 1.0` n'arrive jamais en zone de
                    # transition (`(value - 0.35) / 0.1` y est < 1.0 par
                    # construction) : les valeurs pures sont couvertes par les
                    # branches finales de `_get_tier_fluid`.
                    pure_tier = tier.split("_")[-1] if "_" in tier else tier
                    key = f"{emotion}_{pure_tier}"
                    if key in directives:
                        lignes.append(directives[key])
            if lignes:
                dynamic_parts.append("\n--- Directive comportementale ---")
                dynamic_parts.extend(lignes)

        # Long-term memory context
        if memory_context:
            dynamic_parts.append(
                f"\n--- Ce que tu sais de cet utilisateur ---\n{memory_context}"
            )
            if _MEMORY_RECALL_DIRECTIVE:
                dynamic_parts.append(_MEMORY_RECALL_DIRECTIVE)

        # Présence en direct de l'interlocuteur (statut + activité, comme dans
        # la barre latérale Discord). Transitoire — hors budget mémoire.
        if presence_context:
            dynamic_parts.append(f"\n--- Présence en direct ---\n{presence_context}")

        # Portrait de la personne (user model)
        if person_context:
            dynamic_parts.append(f"\n--- Qui est cette personne ---\n{person_context}")

        # Trust/love relationship context (separate from semantic memories)
        if relationship_context:
            dynamic_parts.append(f"\n--- Relation ---\n{relationship_context}")

        # Persistent notes (written by the LLM itself for long-term retention)
        if persistent_notes:
            lines = ["\n--- Notes persistantes ---"]
            for note in persistent_notes:
                lines.append(f"**{note['title']}** : {note['content']}")
            dynamic_parts.append("\n".join(lines))

        return "\n".join(static_parts + dynamic_parts)

    def build_voice_system(
        self,
        emotion_state: dict[str, float],
        memory_context: str = "",
        speaker_label: str = "",
        persona_block: str = "",
        emotion_directives: dict[str, str] | None = None,
        weekday_directives: dict[str, str] | None = None,
        composite_directives: dict[str, str] | None = None,
        secondary_directives: dict[str, str] | None = None,
        active_secondaries: list[tuple[str, float]] | None = None,
        user_directive: str | None = None,
    ) -> str:
        """Construit le system prompt vocal en réutilisant la machinerie persona+émotions.

        Délègue à build_system_prompt avec un contexte situationnel minimal (vocal) ;
        zéro duplication de la logique d'émotion.
        """
        situation = {"platform": "discord_vocal"}
        if speaker_label:
            situation["channel"] = f"vocal (locuteur : {speaker_label})"
        return self.build_system_prompt(
            emotion_state=emotion_state,
            memory_context=memory_context,
            situation=situation,
            persona_block=persona_block,
            emotion_directives=emotion_directives,
            weekday_directives=weekday_directives,
            composite_directives=composite_directives,
            secondary_directives=secondary_directives,
            active_secondaries=active_secondaries,
            user_directive=user_directive,
        )

    def build_context_block(self, messages: list[dict]) -> str:
        if not messages:
            return ""
        lines = [f"[{m['author']}]: {m['content']}" for m in messages]
        return CONTEXT_HEADER.format(context="\n".join(lines))

    def build_prelude_block(self, messages: list[dict]) -> str:
        if not messages:
            return ""
        lines = [f"[{m['author']}]: {m['content']}" for m in messages]
        return PRELUDE_HEADER.format(context="\n".join(lines))

    @staticmethod
    def format_event_message(template: str, **kwargs) -> str:
        """Interpole un gabarit d'événement, sans jamais lever.

        Ces gabarits sont ÉDITABLES depuis le dashboard : un `{viewers}` qui
        n'existe pas donnait un KeyError, une accolade littérale un ValueError,
        et l'événement (follow, sub, raid) passait en silence. Un placeholder
        inconnu est laissé tel quel — visible, donc corrigeable.
        """
        from loguru import logger  # import local, cf. load_prompt ci-dessus
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "Gabarit d'événement invalide ({e}) — laissé tel quel : {t}",
                e=exc, t=template[:80],
            )
            return template


def bloc_duel_en_cours(duel) -> str:
    """Le duel Apex courant, pour que Wally puisse en PARLER.

    Injecté à la fois dans `build_system_prompt` et dans le contexte cognitif
    (`AttentionContext.duel_block`) : n'alimenter que le premier laissait la
    cognition aveugle à ses propres effets — c'est ainsi qu'un bingo se
    relançait en boucle (précédent du projet).

    Une manche non mesurable est dite telle quelle. Afficher « 0 » pour une
    absence de mesure serait un mensonge : `None` dans `duel.scores` signifie
    « non mesurable », jamais zéro kill.
    """
    if duel is None:
        return ""
    lignes = [
        "--- Duel Apex en cours ---",
        f"Lancé par {duel.viewer_nom} (récompense de points de chaîne).",
        f"Manche {duel.manche_courante} sur {duel.manches}.",
    ]
    for i, s in enumerate(duel.scores, start=1):
        if s["azrael"] is None and s["viewer"] is None:
            lignes.append(f"Manche {i} : non mesurable (aucun kill enregistré).")
        else:
            lignes.append(
                f"Manche {i} : Azraël {s['azrael'] if s['azrael'] is not None else '?'}"
                f" — {duel.viewer_nom} {s['viewer'] if s['viewer'] is not None else '?'}")
    lignes.append(f"Total : Azraël {duel.total_azrael} — {duel.viewer_nom} {duel.total_viewer}.")
    return "\n".join(lignes)


def build_session_recall_block(summaries: list[dict]) -> str:
    """Construit le bloc 'Sessions précédentes' (recall cross-session). Vide si rien."""
    if not summaries:
        return ""
    lines = ["--- Sessions précédentes dans ce salon ---"]
    for s in summaries:
        text = (s.get("summary") or "").strip()
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines) if len(lines) > 1 else ""
