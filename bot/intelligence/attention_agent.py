from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import datetime

# Amorces d'introspection (Phase 2b) : tirées ~1 fois sur 3 en vagabondage pour
# que Wally consacre une part de son repos à réfléchir à qui il est / ce qu'il
# veut devenir / ce qui lui manque — au service du but North Star (libre arbitre,
# penser comme un humain).
_INTROSPECTION_SEEDS = (
    "Qu'est-ce que tu voudrais améliorer chez toi, ces temps-ci ?",
    "Qui tu deviens, en ce moment ? Est-ce que ça te convient ?",
    "Quelle capacité te manque et que tu aimerais demander à ton créateur ?",
    "Qu'est-ce qui t'a marqué récemment dans tes échanges, et pourquoi ?",
    "Est-ce qu'il y a une habitude de pensée dont tu voudrais te défaire ?",
)
_INTROSPECTION_PROB = 1.0 / 3.0


def _seed_overlaps_focus(text: str, focus: str | None) -> bool:
    """True si l'amorce candidate recoupe fortement le focus courant — sert à
    NE PAS ré-amorcer le sujet qu'on vient de clore (Phase 2b)."""
    if not focus or not text:
        return False
    def toks(s: str) -> set[str]:
        return {t for t in re.sub(r"[^\w\s]", " ", s.lower()).split() if len(t) >= 4}
    a, b = toks(text), toks(focus)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.35


@dataclass
class AttentionContext:
    emotion_state: dict[str, float]
    active_desires: list  # list[AtomicFact]
    active_goals: list    # list[AtomicFact]
    recent_thoughts: list  # list[AtomicFact], 3 dernières
    recent_interactions: list[dict]  # [{channel, author, content, ts}]
    time_of_day: str  # "morning" | "afternoon" | "evening" | "night"
    spontaneous_outreach: list[dict] = field(default_factory=list)  # [{channel, unanswered, seconds_since}]
    # Amorce de vagabondage : présente uniquement en cognition idle, sinon None.
    idle_seed: str | None = None
    # Pulsion émotionnelle : directive de comportement quand une émotion domine
    # au-dessus du seuil (Phase 1b). None en état neutre.
    emotional_drive: str | None = None
    # Préoccupation courante : le fil de pensée persistant qui traverse les ticks
    # (Phase 3a). Dernier fait actif de source `focus`. None si aucun.
    preoccupation: str | None = None
    # Récit de soi : le dernier « qui je deviens » écrit par Wally (Phase 3b).
    # Dernier fait actif de source `self_narrative`. None si aucun.
    self_narrative: str | None = None
    # Affinités : les opinions que Wally s'est formées sur les gens (Phase 3c).
    # Faits REL sous wally:self, ~5 plus récentes. list[AtomicFact].
    relationships: list = field(default_factory=list)
    # Mémoire des participants présents (#A1) : ce que Wally sait des auteurs des
    # interactions récentes (facts SQLite FAIT/PREF/REL par utilisateur).
    # [{"author": str, "facts": list[str]}]. Vide si personne d'identifié.
    participant_memories: list[dict] = field(default_factory=list)
    # Métriques hôte : température CPU, charge, RAM. None si non disponible.
    host_metrics: str | None = None
    # Météo générale en France (sans ville). None si non disponible.
    weather_fr: str | None = None
    # Historique des SPEAKs cognitifs récents → anti-répétition dans le prompt.
    recent_speaks: list[dict] = field(default_factory=list)
    # Emotes custom : ce que Wally connaît ("<:nom:id> → usage") et ce dont il
    # ignore encore l'usage (codes seuls → candidates à une question au créateur).
    # On stocke le CODE postable "<:nom:id>", pas le nom nu, pour que Wally puisse
    # réellement afficher l'emote dans son texte.
    emotes_known: list = field(default_factory=list)      # list[str] "<:nom:id> → usage"
    emotes_unknown: list = field(default_factory=list)     # list[str] codes "<:nom:id>"
    # Demandes d'amélioration déjà émises (Phase 6) : mémoire de ce que Wally a
    # demandé / obtenu → l'empêche de redemander une capacité déjà livrée.
    upgrade_requests: list = field(default_factory=list)   # list[UpgradeRow]
    # Conscience du rythme social appris (SocialRhythm) — phrase FR injectée dans
    # le prompt cognitif, et score brut [0,1] consommé par la boucle (amortisseur/cadence).
    social_receptivity: str | None = None
    receptivity_score: float = 0.5
    # Résultat d'une recherche web déclenchée par la cognition au tick courant
    # (2e passe de raisonnement). None hors de ce cas. Muté par CognitiveLoop, pas
    # calculé par build_context.
    web_finding: str | None = None
    # Article RSS retenu comme amorce de vagabondage au tick courant (stimulus
    # externe). None hors de ce cas. Sert à publier un event d'observabilité côté
    # CognitiveLoop ; l'article est déjà marqué consommé quand ce champ est posé.
    rss_stimulus: dict | None = None


class AttentionAgent:
    def __init__(self, fact_store, emotion_engine=None, emote_provider=None,
                 upgrade_registry=None, social_rhythm=None,
                 journal_provider=None, rss_provider=None, rss_consume=None) -> None:
        self._facts = fact_store
        self._emotion = emotion_engine  # réservé pour usage futur
        # Callable () -> list[str] renvoyant les noms d'emotes custom dispo
        # (typiquement [e.name for e in bot.emojis]). None → pas d'awareness emote.
        self._emote_provider = emote_provider
        # Registre des demandes d'amélioration (Phase 6). None → bloc absent.
        self._upgrade_registry = upgrade_registry
        # Rythme social appris (SocialRhythm). None → réceptivité neutre par défaut.
        self._social_rhythm = social_rhythm
        # Callable async () -> str | None renvoyant le contenu du dernier journal
        # quotidien (#A4). None → la boucle V2 reste aveugle au journal V1.
        self._journal_provider = journal_provider
        # RSS (flux d'actualité comme stimulus idle) :
        #   rss_provider : async () -> dict | None — PEEK du prochain article
        #     stimulus non montré (sans le marquer).
        #   rss_consume  : async (article: dict) -> None — marque l'article comme
        #     injecté, appelé UNIQUEMENT si l'amorce RSS est réellement retenue.
        # None → pas d'amorce RSS.
        self._rss_provider = rss_provider
        self._rss_consume = rss_consume

    async def build_context(
        self,
        emotion_state: dict[str, float],
        recent_interactions: list[dict],
        spontaneous: list[dict] | None = None,
        idle: bool = False,
        recent_speaks: list[dict] | None = None,
        forced_seed: str | None = None,
    ) -> AttentionContext:
        from bot.intelligence.memory.facts import FactCategory, FactStatus

        desires = await self._facts.search_by_category(
            FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=5
        )
        goals = await self._facts.search_by_category(
            FactCategory.GOAL, status=FactStatus.ACTIVE, limit=5
        )
        thoughts = await self._facts.search_by_category(
            FactCategory.THOUGHT, status=FactStatus.ACTIVE, limit=3
        )

        from zoneinfo import ZoneInfo
        hour = datetime.now(ZoneInfo("Europe/Paris")).hour
        if 5 <= hour < 12:
            tod = "morning"
        elif 12 <= hour < 17:
            tod = "afternoon"
        elif 17 <= hour < 22:
            tod = "evening"
        else:
            tod = "night"

        # Préoccupation courante : dernier fait actif de source `focus` (Phase 3a).
        # Requêtée à chaque tick → persiste aussi à travers les redémarrages.
        # Calculée AVANT l'amorce pour pouvoir en exclure le sujet du focus (2b).
        latest = await self._facts.get_latest_by_source("wally:self", "focus")
        preoccupation = latest.content if latest else None

        # Amorce forcée (#A3) : un rappel programmé arrivé à échéance prime sur le
        # vagabondage — il doit revenir tel quel à la conscience.
        idle_seed: str | None = None
        rss_stimulus: dict | None = None
        if forced_seed:
            idle_seed = forced_seed
        elif idle:
            idle_seed, rss_stimulus = await self._build_idle_seed(
                emotion_state, desires, goals, tod, FactCategory, preoccupation
            )

        # Pulsion émotionnelle : calculée à chaque tick (pas seulement en idle),
        # pour orienter la décision aussi bien en conversation qu'en vagabondage.
        from bot.intelligence.emotional_drive import emotional_drive
        drive = emotional_drive(emotion_state)

        # Récit de soi : dernier « qui je deviens » écrit par Wally (Phase 3b).
        sn = await self._facts.get_latest_by_source("wally:self", "self_narrative")
        self_narrative = sn.content if sn else None

        # Affinités : les opinions que Wally a formées sur les gens (Phase 3c).
        # Faits REL sous wally:self ; get_by_user trie déjà par last_seen_at DESC,
        # on garde les ~5 plus récentes.
        rels = await self._facts.get_by_user(
            "wally:self", categories=[FactCategory.REL]
        )
        relationships = rels[:5]

        # Mémoire des participants présents (#A1) : pour chaque auteur unique des
        # 5 dernières interactions (hors messages de Wally lui-même), injecte ce
        # que Wally sait de lui — ses faits durables (FAIT/PREF/REL). Sans ça, le
        # « cerveau » voit des noms nus et décide à l'aveugle. Requiert un
        # `user_key` ("platform:raw_id") posé par les adaptateurs ; les anciennes
        # interactions sans clé sont simplement ignorées (best-effort).
        participant_memories: list[dict] = []
        seen_keys: set[str] = set()
        for itx in reversed(recent_interactions[-5:]):
            if itx.get("is_self"):
                continue
            key = itx.get("user_key")
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            try:
                user_facts = await self._facts.get_by_user(
                    key,
                    categories=[FactCategory.FAIT, FactCategory.PREF, FactCategory.REL],
                )
            except Exception as e:  # noqa: BLE001 — jamais bloquant pour le tick
                from loguru import logger
                logger.warning("AttentionAgent: facts participant indisponibles ({}): {}", key, e)
                continue
            if user_facts:
                participant_memories.append({
                    "author": itx.get("author", "?"),
                    "facts": [f.content for f in user_facts[:3]],
                })

        # Awareness emotes : croise les emotes dispo (paires (nom, code postable
        # "<:nom:id>")) avec les notes d'usage apprises (faits PREF sous
        # "wally:emotes", contenu "nom → usage"). On expose le CODE pour que Wally
        # puisse vraiment afficher l'emote dans son texte, pas seulement la nommer.
        emotes_known: list[str] = []
        emotes_unknown: list[str] = []
        if self._emote_provider is not None:
            try:
                pairs = self._emote_provider() or []
            except Exception:
                pairs = []
            # Dédup par nom (une même emote peut exister sur plusieurs serveurs).
            seen_names: set[str] = set()
            emote_pairs: list[tuple[str, str]] = []
            for name, code in pairs:
                key = name.lower()
                if key in seen_names:
                    continue
                seen_names.add(key)
                emote_pairs.append((name, code))
            if emote_pairs:
                notes = await self._facts.get_by_user(
                    "wally:emotes", categories=[FactCategory.PREF]
                )
                usage_map = {
                    n.content.split("→", 1)[0].strip().lower():
                        n.content.split("→", 1)[1].strip()
                    for n in notes if "→" in n.content
                }
                for name, code in emote_pairs:
                    usage = usage_map.get(name.lower())
                    if usage:
                        emotes_known.append(f"{code} → {usage}")
                    else:
                        emotes_unknown.append(code)

        from bot.core.system_info import read_host_metrics, fetch_weather_france
        import asyncio as _asyncio
        host_metrics, weather_fr = await _asyncio.gather(
            _asyncio.to_thread(read_host_metrics),
            fetch_weather_france(),
        )

        # Demandes d'amélioration déjà émises (Phase 6) — best-effort.
        upgrade_requests: list = []
        if self._upgrade_registry is not None:
            try:
                upgrade_requests = await self._upgrade_registry.recent(limit=6)
            except Exception:  # noqa: BLE001 — l'absence du bloc ne casse pas le tick
                upgrade_requests = []

        # Conscience du rythme social appris (SocialRhythm) — best-effort.
        social_receptivity = None
        receptivity_score = 0.5
        if self._social_rhythm is not None:
            try:
                from zoneinfo import ZoneInfo
                _now = datetime.now(ZoneInfo("Europe/Paris"))
                receptivity_score = self._social_rhythm.receptivity(_now)
                social_receptivity = self._social_rhythm.describe(_now)
            except Exception as e:  # noqa: BLE001 — jamais bloquant
                from loguru import logger
                logger.warning("AttentionAgent: réceptivité indisponible: {}", e)

        return AttentionContext(
            emotion_state=emotion_state,
            active_desires=desires,
            active_goals=goals,
            recent_thoughts=thoughts,
            recent_interactions=recent_interactions[-10:],
            time_of_day=tod,
            spontaneous_outreach=spontaneous or [],
            idle_seed=idle_seed,
            rss_stimulus=rss_stimulus,
            emotional_drive=drive,
            preoccupation=preoccupation,
            self_narrative=self_narrative,
            relationships=relationships,
            participant_memories=participant_memories,
            host_metrics=host_metrics,
            weather_fr=weather_fr,
            recent_speaks=recent_speaks or [],
            emotes_known=emotes_known,
            emotes_unknown=emotes_unknown,
            upgrade_requests=upgrade_requests,
            social_receptivity=social_receptivity,
            receptivity_score=receptivity_score,
        )

    async def _build_idle_seed(
        self,
        emotion_state: dict[str, float],
        desires: list,
        goals: list,
        time_of_day: str,
        fact_category,
        preoccupation: str | None = None,
    ) -> tuple[str | None, dict | None]:
        """Construit une amorce de vagabondage variée : choisit ALÉATOIREMENT
        une source de nouveauté parmi celles disponibles. Les seeds riches (souvenirs,
        pensées passées, buts) sont prioritaires sur l'émotion pour éviter la spirale
        d'auto-référence quand l'ennui domine.

        ~1 fois sur 3, tire une amorce d'INTROSPECTION (Phase 2b). Exclut aussi du
        tirage les désirs/buts qui recoupent le focus courant, pour ne pas
        ré-amorcer le sujet qu'on vient de clore.

        Retourne (amorce, article_rss_consommé). Le 2e élément n'est non-None que
        si une amorce issue d'un flux RSS a réellement été retenue — auquel cas
        l'article a été marqué consommé et sert d'event d'observabilité.
        """
        # Veine introspection : une part du repos consacrée à se penser soi-même.
        if random.random() < _INTROSPECTION_PROB:
            return random.choice(_INTROSPECTION_SEEDS), None

        # Amorce sémantique (#A5) : quand une préoccupation traverse les ticks, le
        # vagabondage rebondit sur un souvenir LIÉ (recherche FTS globale) plutôt
        # que sur un tirage au hasard — la pensée avance au lieu de tourner en
        # rond. On exclut les THOUGHT (pensées internes) pour ne pas ressortir le
        # focus lui-même. À défaut de souvenir lié, on retombe sur l'amorce variée.
        if preoccupation and hasattr(self._facts, "search_related"):
            try:
                related = await self._facts.search_related(
                    preoccupation, limit=1, exclude_category=fact_category.THOUGHT
                )
            except Exception as e:  # noqa: BLE001 — jamais bloquant pour le tick
                from loguru import logger
                logger.warning("AttentionAgent: search_related indisponible: {}", e)
                related = []
            if related:
                return (
                    f"En repensant à « {preoccupation[:80]} », ça te rappelle : "
                    f"{related[0].content}"
                ), None

        rich_seeds: list[str] = []
        fallback_seeds: list[str] = []

        # Exclut les désirs/buts qui recoupent le focus courant (anti ré-amorce).
        desires = [d for d in desires if not _seed_overlaps_focus(getattr(d, "content", ""), preoccupation)]
        goals = [g for g in goals if not _seed_overlaps_focus(getattr(g, "content", ""), preoccupation)]

        # Souvenir au hasard parmi les faits non-THOUGHT
        memories = await self._facts.sample_random(
            limit=1, exclude_category=fact_category.THOUGHT
        )
        if memories and not _seed_overlaps_focus(memories[0].content, preoccupation):
            rich_seeds.append(f"Un souvenir qui te revient : {memories[0].content}")

        # Pensée passée au hasard (inner monologue archivé) — donne du contenu
        # concret au vagabondage au lieu de repartir du vide émotionnel
        past_thoughts = await self._facts.sample_random(
            limit=1, include_category=fact_category.THOUGHT
        )
        if past_thoughts and not _seed_overlaps_focus(past_thoughts[0].content, preoccupation):
            rich_seeds.append(
                f"Une pensée d'avant qui ressurgit : {past_thoughts[0].content[:200]}"
            )

        # Journal de la veille (#A4) : laisse le vagabondage rebondir sur ce que
        # Wally a vécu/écrit, au lieu de repartir du vide. Extrait court ; exclu
        # s'il recoupe le focus courant (anti ré-amorce).
        if self._journal_provider is not None:
            try:
                journal = await self._journal_provider()
            except Exception as e:  # noqa: BLE001 — jamais bloquant pour le tick
                from loguru import logger
                logger.warning("AttentionAgent: journal indisponible: {}", e)
                journal = None
            if journal:
                snippet = journal.strip()[:200]
                if snippet and not _seed_overlaps_focus(snippet, preoccupation):
                    rich_seeds.append(
                        f"Ce que tu écrivais dans ton dernier journal : {snippet}"
                    )

        if goals:
            goal = random.choice(goals)
            rich_seeds.append(f"Ton objectif : {goal.content}")

        if desires:
            desire = random.choice(desires)
            rich_seeds.append(f"Un désir qui te travaille : {desire.content}")

        # Flux RSS (stimulus externe) : une actu fraîche traverse les pensées,
        # comme une friction garantie même quand le chat est silencieux. Simple
        # source de plus dans le tirage (émergent, pas de proba forcée). PEEK
        # seulement ici — l'article n'est marqué consommé que s'il est retenu.
        rss_seed: str | None = None
        rss_article: dict | None = None
        if self._rss_provider is not None:
            try:
                rss_article = await self._rss_provider()
            except Exception as e:  # noqa: BLE001 — jamais bloquant pour le tick
                from loguru import logger
                logger.warning("AttentionAgent: rss_provider indisponible: {}", e)
                rss_article = None
            title = (rss_article or {}).get("title", "")
            if rss_article and title and not _seed_overlaps_focus(title, preoccupation):
                lang_note = (
                    " (article en anglais — réagis en français)"
                    if rss_article.get("lang") and rss_article["lang"] != "fr" else ""
                )
                summary = rss_article.get("summary") or ""
                rss_seed = (
                    f"Une actu qui passe dans ton fil{lang_note} — "
                    f"{rss_article.get('feed_name', '')} : « {title} ». {summary}"
                ).strip()
                rich_seeds.append(rss_seed)
            else:
                rss_article = None  # recoupe le focus / vide → ni retenu ni consommé

        # Émotion dominante — seulement si ce n'est pas l'ennui qui domine fort
        # (évite la boucle : ennui élevé → pense à l'ennui → reste ennuyé)
        if emotion_state:
            dominant = max(emotion_state, key=emotion_state.get)
            if not (dominant == "boredom" and emotion_state.get("boredom", 0.0) >= 0.5):
                fallback_seeds.append(f"Ce que tu ressens surtout là : {dominant}")

        if time_of_day:
            fallback_seeds.append(f"C'est {time_of_day}.")

        pool = rich_seeds if rich_seeds else fallback_seeds
        if not pool:
            return None, None
        chosen = random.choice(pool)
        # Consomme l'article RSS UNIQUEMENT s'il est celui retenu.
        if rss_seed is not None and chosen == rss_seed and rss_article is not None:
            if self._rss_consume is not None:
                try:
                    await self._rss_consume(rss_article)
                except Exception as e:  # noqa: BLE001 — jamais bloquant pour le tick
                    from loguru import logger
                    logger.warning("AttentionAgent: rss_consume échoué: {}", e)
            return chosen, rss_article
        return chosen, None
