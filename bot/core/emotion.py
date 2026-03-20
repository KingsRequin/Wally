# bot/core/emotion.py
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config

EMOTIONS = ["anger", "joy", "sadness", "curiosity", "boredom"]

# NRC Lexicon emotion → our 5 emotions mapping
NRC_MAP: dict[str, list[str]] = {
    "anger": ["anger", "disgust"],
    "joy": ["joy", "trust", "anticipation"],
    "sadness": ["sadness", "fear"],
    "curiosity": ["surprise"],
    "boredom": [],
}

# Max delta applied per message per emotion
MAX_DELTA_PER_MESSAGE = 0.3

# Coefficient de suppression lors d'un apply_delta : la valeur montante érode la valeur adverse.
# Bidirectionnel : si joy monte, anger baisse ; si anger monte, joy baisse.
# anger↔boredom intentionnellement absent (coexistence plausible).
# sadness↔joy bidirectionnel via "elif emotion == tgt" dans _apply_suppression.
SUPPRESSION_RULES: list[tuple[str, str, float]] = [
    ("joy",     "anger",   0.8),
    ("joy",     "sadness", 0.8),
]

# Coefficient de compétition continue pendant le decay (par tick de 60s).
# extra = state[src] * state[tgt] * COMPETITION_K est soustrait des deux émotions.
# Avec K=0.05 : anger=0.65 + joy=0.33 → extra≈0.011/tick → convergence en ~10min.
COMPETITION_K: float = 0.05

# French keyword → (emotion, delta) supplements for NRCLex (English-only lexicon)
FR_EMOTION_WORDS: dict[str, list[tuple[str, float]]] = {
    "anger": [
        ("connard", 0.15), ("con", 0.10), ("merde", 0.12), ("chier", 0.10),
        ("énervant", 0.12), ("chiant", 0.08), ("débile", 0.10),
        ("nul", 0.08), ("rage", 0.12), ("putain", 0.10), ("abruti", 0.12),
    ],
    "joy": [
        ("super", 0.08), ("génial", 0.10), ("excellent", 0.10),
        ("top", 0.07), ("cool", 0.07), ("bravo", 0.08), ("gg", 0.06),
        ("lol", 0.06), ("mdr", 0.07), ("xd", 0.06), ("pog", 0.08),
        ("incroyable", 0.10), ("ouf", 0.07), ("marrant", 0.08), ("ptdr", 0.07),
    ],
    "sadness": [
        ("triste", 0.12), ("déçu", 0.10), ("dommage", 0.08),
        ("rip", 0.08), ("horrible", 0.10), ("terrible", 0.10), ("naze", 0.08),
    ],
    "curiosity": [
        ("pourquoi", 0.08), ("comment", 0.06), ("vraiment", 0.05),
        ("intéressant", 0.10), ("sérieux", 0.06), ("c'est quoi", 0.07),
    ],
    "boredom": [
        ("bof", 0.10), ("mouais", 0.08), ("meh", 0.08),
        ("ennuyeux", 0.10), ("flemme", 0.08), ("chiant", 0.06),
    ],
}

# Emotions are zeroed below this floor after decay
DECAY_FLOOR = 0.01

_LEARNED_WORDS_PATH = "data/fr_emotion_words.json"

_EMOTION_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "deltas": {
            "type": "object",
            "properties": {
                "anger": {"type": "number"},
                "joy": {"type": "number"},
                "sadness": {"type": "number"},
                "curiosity": {"type": "number"},
                "boredom": {"type": "number"},
            },
            "required": ["anger", "joy", "sadness", "curiosity", "boredom"],
            "additionalProperties": False,
        },
        "new_words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "emotion": {"type": "string"},
                    "delta": {"type": "number"},
                },
                "required": ["word", "emotion", "delta"],
                "additionalProperties": False,
            },
        },
        "trust_delta": {"type": "number"},
        "love_delta": {"type": "number"},
        "user_facts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["deltas", "new_words", "trust_delta", "love_delta", "user_facts"],
    "additionalProperties": False,
}


def build_emotion_tag(emotion_state: dict[str, float]) -> str:
    """Construit un tag textuel à partir des émotions dominantes (≥ 0.2).

    Retourne "" si aucune émotion n'est dominante.
    Exemple : "Wally: joy, curiosity"
    """
    dominant = [e for e, v in emotion_state.items() if v >= 0.2]
    if not dominant:
        return ""
    return "Wally: " + ", ".join(dominant)


class EmotionEngine:
    # Taux de montée du boredom par minute d'inactivité (linéaire, clampé à 1.0)
    BOREDOM_RISE_PER_MINUTE: float = 0.02

    def __init__(self, config: "Config", db=None):
        self._config = config
        self._state: dict[str, float] = {e: 0.0 for e in EMOTIONS}
        self._last_decay: float = time.time()
        self._last_interaction: float = time.time()
        self._decay_task: asyncio.Task | None = None
        self._openai = None
        self._learned_words: dict[str, list[tuple[str, float]]] = {e: [] for e in EMOTIONS}
        self._learned_lock = asyncio.Lock()
        # Persistence
        self._db = db
        self._dirty: bool = False
        self._save_task: asyncio.Task | None = None
        self._ticks: int = 0
        # Peak detection anti-spam cache: emotion → timestamp of last peak
        self._last_peak_ts: dict[str, float] = {}
        self._bg_tasks: set[asyncio.Task] = set()
        self._load_learned_words()

    # ── State access ─────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, float]:
        return dict(self._state)

    def _apply_competition(self) -> None:
        """Érode mutuellement les émotions incompatibles (appelée après chaque decay tick).

        Pour chaque paire (src, tgt) dans SUPPRESSION_RULES :
            extra = state[src] * state[tgt] * COMPETITION_K
        Les deux valeurs baissent de `extra`, clampées à 0.0.
        """
        for src, tgt, _ in SUPPRESSION_RULES:
            extra = self._state[src] * self._state[tgt] * COMPETITION_K
            if extra <= 0:
                continue
            self._state[src] = max(0.0, self._state[src] - extra)
            self._state[tgt] = max(0.0, self._state[tgt] - extra)

    def _apply_suppression(self, emotion: str, delta: float) -> None:
        """Supprime partiellement les émotions incompatibles si delta > 0."""
        if delta <= 0:
            return
        for src, tgt, coeff in SUPPRESSION_RULES:
            if emotion == src:
                self._state[tgt] = max(0.0, self._state[tgt] - delta * coeff)
            elif emotion == tgt:
                self._state[src] = max(0.0, self._state[src] - delta * coeff)

    def apply_delta(self, emotion: str, delta: float) -> None:
        if emotion not in self._state:
            return
        # Inertie : atténuer si une émotion opposée est dominante
        inertia = getattr(self._config.bot, "emotion_inertia_factor", 0.5)
        if inertia > 0 and delta > 0:
            max_opposite = 0.0
            for src, tgt, _ in SUPPRESSION_RULES:
                if emotion == src:
                    max_opposite = max(max_opposite, self._state.get(tgt, 0.0))
                elif emotion == tgt:
                    max_opposite = max(max_opposite, self._state.get(src, 0.0))
            if max_opposite > 0:
                delta = delta * (1 - max_opposite * inertia)
        old = self._state[emotion]
        self._state[emotion] = max(0.0, min(1.0, old + delta))
        effective_delta = self._state[emotion] - old
        self._apply_suppression(emotion, effective_delta)
        self._dirty = True
        self._schedule_save()

    def set_emotion(self, emotion: str, value: float) -> None:
        if emotion in self._state:
            effective_delta = value - self._state[emotion]
            self._state[emotion] = max(0.0, min(1.0, value))
            self._apply_suppression(emotion, effective_delta)
            self._dirty = True
            self._schedule_save()

    def reset(self) -> None:
        self._state = {e: 0.0 for e in EMOTIONS}
        self._dirty = True
        self._schedule_save()
        logger.info("Emotion state reset to zero")

    def get_dominant(self, threshold: float = 0.2) -> list[str]:
        return [e for e in EMOTIONS if self._state.get(e, 0.0) >= threshold]

    def set_openai_client(self, client) -> None:
        """Injection du client OpenAI (pattern identique à MemoryService)."""
        self._openai = client

    def _fire(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        return t

    async def _maybe_log_peak(
        self, emotion: str, old_value: float, new_value: float,
        trigger_user: str = "", trigger_message: str = "",
        channel_id: str = "", platform: str = "",
    ) -> None:
        """Log an emotion peak if it crosses the threshold."""
        threshold = getattr(self._config.bot, "emotion_peak_threshold", 0.7)
        if new_value <= threshold or new_value <= old_value:
            return
        now = time.time()
        last = self._last_peak_ts.get(emotion, 0.0)
        if now - last < 300:  # 5 minute anti-spam
            return
        self._last_peak_ts[emotion] = now
        if self._db is not None:
            try:
                await self._db.insert_emotion_peak(
                    now, emotion, new_value,
                    trigger_user, trigger_message, channel_id, platform,
                )
                logger.info(
                    "Emotion peak logged: {e}={v:.0%} triggered by {u}",
                    e=emotion, v=new_value, u=trigger_user or "unknown",
                )
            except Exception as exc:
                logger.warning("Failed to log emotion peak: {e}", e=exc)

    async def load_state(self) -> None:
        """Charge l'état émotionnel depuis la DB. No-op si db est None."""
        if self._db is None:
            return
        try:
            loaded = await self._db.load_emotion_state()
            for emotion, value in loaded.items():
                if emotion in self._state:
                    self._state[emotion] = max(0.0, min(1.0, value))
            logger.info("Emotion state loaded from DB: {s}", s=self._state)
        except Exception as exc:
            logger.warning("Failed to load emotion state: {e}", e=exc)

    def _schedule_save(self) -> None:
        """Debounce : annule la tâche en cours et en planifie une nouvelle dans 5s."""
        if self._db is None:
            return
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = asyncio.create_task(self._delayed_save())

    async def _delayed_save(self) -> None:
        await asyncio.sleep(5)
        if self._db and self._dirty:
            try:
                await self._db.save_emotion_state(self._state)
                self._dirty = False
            except Exception as exc:
                logger.warning("Failed to persist emotion state: {e}", e=exc)
                # _dirty reste True → retry au prochain apply_delta

    def _load_learned_words(self) -> None:
        """Charge les mots appris depuis le disque au démarrage."""
        try:
            with open(_LEARNED_WORDS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for emotion in EMOTIONS:
                self._learned_words[emotion] = [
                    (pair[0], float(pair[1])) for pair in data.get(emotion, [])
                ]
            logger.info("Learned emotion words loaded from {p}", p=_LEARNED_WORDS_PATH)
        except FileNotFoundError:
            pass  # premier démarrage — normal
        except Exception as exc:
            logger.warning("Failed to load learned words: {e}", e=exc)

    def _is_known_word(self, word: str) -> bool:
        """Vérifie si un mot existe déjà (hardcodé ou appris) — case-insensitive."""
        word_lower = word.lower()
        for entries in FR_EMOTION_WORDS.values():
            if any(w.lower() == word_lower for w, _ in entries):
                return True
        for entries in self._learned_words.values():
            if any(w.lower() == word_lower for w, _ in entries):
                return True
        return False

    @staticmethod
    def _write_learned_words_sync(data: dict, path: str) -> None:
        """Écriture atomique dans un thread — ne pas appeler directement."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

    async def _save_learned_words(self) -> None:
        """Sauvegarde atomique des mots appris (lock + to_thread)."""
        async with self._learned_lock:
            data = {e: [[w, d] for w, d in self._learned_words[e]] for e in EMOTIONS}
            try:
                await asyncio.to_thread(self._write_learned_words_sync, data, _LEARNED_WORDS_PATH)
            except Exception as exc:
                logger.warning("Failed to save learned words: {e}", e=exc)

    async def _learn_words(self, new_words: list[dict]) -> None:
        """Valide et ajoute les nouveaux mots appris depuis le LLM."""
        added = False
        for entry in new_words:
            word = entry.get("word", "")
            emotion = entry.get("emotion", "")
            delta = entry.get("delta", 0.0)
            if emotion not in EMOTIONS:
                continue
            if not (0.0 < delta <= MAX_DELTA_PER_MESSAGE):
                continue
            if len(word) < 2:
                continue
            if self._is_known_word(word):
                continue
            self._learned_words[emotion].append((word, float(delta)))
            logger.info("New emotion word learned: {w} → {e} ({d})", w=word, e=emotion, d=delta)
            added = True
        if added:
            await self._save_learned_words()

    async def _analyze_llm(
        self, text: str, trust_score: float, context_messages: list[dict],
        image_urls: list[str] | None = None,
    ) -> tuple[dict[str, float], list[dict], float, float, list[str]]:
        """Analyse émotionnelle via LLM — retourne (deltas, new_words, trust_delta, love_delta, user_facts)."""
        system_prompt = (
            "Tu es le module d'analyse émotionnelle de Wally, un bot de chat Discord. "
            "Ton rôle est de mesurer l'impact d'un échange sur l'état interne de Wally.\n\n"

            "## Émotions disponibles\n"
            "anger, joy, sadness, curiosity, boredom\n\n"

            "## Calcul des deltas\n"
            "- Chaque delta est un float dans [0.0, 0.3] représentant une variation positive de l'émotion.\n"
            "- Pondération par la cible :\n"
            "  • Émotion dirigée vers Wally → impact plein (delta normal)\n"
            "  • Émotion dirigée entre utilisateurs (Wally non concerné) → delta ÷ 3\n"
            "- Pondération par la confiance :\n"
            "  • trust_score proche de 0.0 → anger amplifié (×2 max)\n"
            "  • trust_score proche de 1.0 → pas d'amplification\n"
            "- Le dernier message (« Message déclencheur ») a un poids plus élevé que l'historique.\n"
            "- Si un message est neutre ou sans contenu émotionnel, laisse tous les deltas à 0.0.\n\n"

            "## Apprentissage de nouveaux mots (new_words)\n"
            "Identifie au maximum 3 mots ou expressions françaises absents du lexique standard "
            "qui expriment clairement une émotion dans ce message. "
            "Critères : mot non anglais, porteur d'émotion explicite, delta entre 0.05 et 0.3.\n\n"

            "## Trust delta\n"
            "Retourne aussi \"trust_delta\" : un float dans [-0.10, +0.10].\n"
            "- Interaction constructive, amicale, drôle, engageante → positif (+0.01 à +0.05)\n"
            "- Interaction hostile, insulte, provocation, toxique → négatif (-0.03 à -0.10)\n"
            "- Interaction neutre, factuelle, sans charge émotionnelle → 0.0\n"
            "- Inside joke, complicité, défendre Wally → bonus (+0.05 à +0.10)\n\n"

            "## Love delta\n"
            "Retourne aussi \"love_delta\" : un float dans [0.0, 0.10].\n"
            "- Interaction chaleureuse, drôle partagée, intérêt sincère pour Wally → positif (+0.02 à +0.08)\n"
            "- Le love_delta n'est jamais négatif. L'affection ne baisse que par le decay temporel.\n"
            "- Interaction neutre ou hostile → 0.0\n\n"

            "## Extraction de faits\n"
            "Retourne aussi \"user_facts\" : une liste de faits durables sur l'utilisateur "
            "qui envoie le message déclencheur (centres d'intérêt, préférences, faits "
            "biographiques, opinions exprimées). Liste vide si rien de durable.\n\n"

            "## Exemple\n"
            "trust_score: 0.30\n"
            "Historique :\n"
            "[Alice]: c'est vraiment nul comme réponse\n"
            "Message déclencheur :\n"
            "[Bob]: ouais Wally t'es carrément à côté de la plaque là\n"
            "→ Réponse attendue :\n"
            '{"deltas": {"anger": 0.22, "joy": 0.0, "sadness": 0.05, "curiosity": 0.0, "boredom": 0.0}, '
            '"new_words": [{"word": "à côté de la plaque", "emotion": "anger", "delta": 0.10}], '
            '"trust_delta": -0.05, "love_delta": 0.0, "user_facts": []}\n\n'

            "## Format de sortie\n"
            "JSON valide uniquement, sans markdown ni commentaire :\n"
            '{"deltas": {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}, '
            '"new_words": [{"word": "...", "emotion": "...", "delta": 0.0}], "trust_delta": 0.0, "love_delta": 0.0, "user_facts": []}'
        )
        if image_urls:
            system_prompt += (
                "\n\n## Images jointes\n"
                "Des images accompagnent ce message. Analyse aussi leur contenu émotionnel "
                "(ton visuel, sujet représenté, contexte apparent) pour affiner les deltas. "
                "Une image de rage, un mème sarcastique ou une photo triste doit influencer "
                "les deltas au même titre que le texte."
            )
        context_lines = "\n".join(
            f"[{m['author']}]: {m['content']}" for m in context_messages
        )
        user_msg = (
            f"trust_score: {trust_score:.2f}\n\n"
            f"Historique récent :\n{context_lines}\n\n"
            f"Message déclencheur :\n{text}"
        )
        if image_urls:
            # Images require multimodal content blocks — use plain complete_secondary + json.loads
            raw = await self._openai.complete_secondary(
                system_prompt,
                [{"role": "user", "content": user_msg}],
                purpose="emotion_analysis",
                image_urls=image_urls,
            )
            parsed = json.loads(raw)
            raw_deltas = parsed.get("deltas", {})
            new_words = parsed.get("new_words", [])
            trust_delta = max(-0.1, min(0.1, float(parsed.get("trust_delta", 0.0))))
            love_delta = max(0.0, min(0.1, float(parsed.get("love_delta", 0.0))))
            user_facts = parsed.get("user_facts", [])
        else:
            # No images — use structured outputs (schema-guaranteed response)
            parsed = await self._openai.complete_secondary_structured(
                system_prompt,
                [{"role": "user", "content": user_msg}],
                schema=_EMOTION_ANALYSIS_SCHEMA,
                purpose="emotion_analysis",
            )
            raw_deltas = parsed["deltas"]
            new_words = parsed["new_words"]
            trust_delta = max(-0.1, min(0.1, float(parsed["trust_delta"])))
            love_delta = max(0.0, min(0.1, float(parsed["love_delta"])))
            user_facts = parsed["user_facts"]
        deltas = {
            e: min(max(float(raw_deltas.get(e, 0.0)), 0.0), MAX_DELTA_PER_MESSAGE)
            for e in EMOTIONS
        }
        return deltas, new_words, trust_delta, love_delta, user_facts

    # ── Decay ─────────────────────────────────────────────────────────────────

    def _apply_decay(self) -> None:
        now = time.time()
        delta_t = now - self._last_decay
        if delta_t <= 0:
            return
        for emotion in EMOTIONS:
            if emotion == "boredom":
                continue  # boredom géré séparément ci-dessous
            cfg = self._config.emotions.get(emotion)
            if not cfg or self._state[emotion] <= 0:
                continue
            lam = cfg.decay_lambda
            decayed = self._state[emotion] * math.exp(-lam * (delta_t / 60.0))
            self._state[emotion] = 0.0 if decayed < DECAY_FLOOR else decayed
        # Boredom monte quand personne n'interagit (inversement au decay des autres)
        idle_minutes = (now - self._last_interaction) / 60.0
        boredom_target = min(1.0, idle_minutes * self.BOREDOM_RISE_PER_MINUTE)
        if boredom_target > self._state["boredom"]:
            self._state["boredom"] = boredom_target
        self._last_decay = now
        self._apply_competition()

    async def _decay_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            self._apply_decay()
            self._dirty = True
            self._schedule_save()
            logger.debug("Emotion decay applied: {state}", state=self._state)
            self._ticks += 1
            if self._ticks % 60 == 0 and self._db:
                try:
                    await self._db.insert_emotion_snapshot(self._state)
                except Exception as exc:
                    logger.warning("Failed to insert emotion snapshot: {e}", e=exc)

    def start_decay_task(self) -> None:
        self._decay_task = asyncio.create_task(self._decay_loop())
        logger.info("Emotion decay task started")

    # ── NRCLex analysis ───────────────────────────────────────────────────────

    async def analyze_message(
        self, text: str, trust_score: float = 0.0
    ) -> dict[str, float]:
        return await asyncio.to_thread(self._analyze_sync, text, trust_score)

    def _analyze_sync(self, text: str, trust_score: float) -> dict[str, float]:
        try:
            from nrclex import NRCLex  # local import — heavy at first call

            # v4 API: constructor loads the lexicon (no text arg); then
            # load_token_list avoids NLTK/textblob corpus dependency.
            nrc = NRCLex()
            nrc.load_token_list(text.lower().split())
            scores = nrc.affect_frequencies
            deltas: dict[str, float] = {}

            for emotion, nrc_keys in NRC_MAP.items():
                if not nrc_keys:
                    continue
                raw = sum(scores.get(k, 0.0) for k in nrc_keys)
                if raw <= 0:
                    continue
                if emotion == "anger":
                    # Low trust amplifies anger response
                    amplifier = 1.0 + max(0.0, 1.0 - trust_score)
                    raw = min(raw * amplifier, MAX_DELTA_PER_MESSAGE)
                else:
                    raw = min(raw * 0.3, MAX_DELTA_PER_MESSAGE)
                deltas[emotion] = raw

            # Supplement with French keyword detection (NRCLex is English-only)
            # Merge hardcoded + learned words
            text_lower = text.lower()
            all_fr_words: dict[str, list[tuple[str, float]]] = {}
            for emotion in EMOTIONS:
                all_fr_words[emotion] = list(FR_EMOTION_WORDS.get(emotion, [])) + list(self._learned_words.get(emotion, []))

            for emotion, word_deltas in all_fr_words.items():
                fr_raw = sum(d for w, d in word_deltas if w in text_lower)
                if fr_raw > 0:
                    combined = deltas.get(emotion, 0.0) + fr_raw
                    if emotion == "anger":
                        combined = min(combined * (1.0 + max(0.0, 1.0 - trust_score)), MAX_DELTA_PER_MESSAGE)
                    else:
                        combined = min(combined, MAX_DELTA_PER_MESSAGE)
                    deltas[emotion] = combined

            return deltas
        except Exception as exc:
            logger.warning("NRCLex analysis failed: {e}", e=exc)
            return {}

    def record_interaction(self) -> None:
        """Enregistre une interaction — fait baisser le boredom proportionnellement."""
        self._last_interaction = time.time()
        if self._state["boredom"] > 0:
            # Réduction immédiate : chaque message réduit le boredom de 30%
            self._state["boredom"] = max(0.0, self._state["boredom"] * 0.7)
            if self._state["boredom"] < DECAY_FLOOR:
                self._state["boredom"] = 0.0
            self._dirty = True
            self._schedule_save()

    async def process_message(
        self, text: str, trust_score: float = 0.0, context_messages: list[dict] | None = None,
        image_urls: list[str] | None = None,
        trigger_user: str = "", channel_id: str = "", platform: str = "",
    ) -> dict | None:
        self.record_interaction()
        state_before = self.get_state()
        if self._openai is not None and context_messages:
            try:
                deltas, new_words, trust_delta, love_delta, user_facts = await self._analyze_llm(
                    text, trust_score, context_messages, image_urls=image_urls
                )
                for emotion, delta in deltas.items():
                    self.apply_delta(emotion, delta)
                if new_words:
                    await self._learn_words(new_words)
                # Check for peaks
                state_after = self.get_state()
                for emotion, delta in deltas.items():
                    if delta > 0:
                        self._fire(self._maybe_log_peak(
                            emotion, state_before.get(emotion, 0.0), state_after.get(emotion, 0.0),
                            trigger_user=trigger_user, trigger_message=text,
                            channel_id=channel_id, platform=platform,
                        ))
                return {"trust_delta": trust_delta, "love_delta": love_delta, "user_facts": user_facts}
            except Exception as exc:
                logger.warning("LLM emotion analysis failed, using fallback: {e}", e=exc)
        # Fallback : NRCLex + FR_EMOTION_WORDS
        deltas = await self.analyze_message(text, trust_score)
        for emotion, delta in deltas.items():
            self.apply_delta(emotion, delta)
        state_after = self.get_state()
        for emotion, delta in deltas.items():
            if delta > 0:
                self._fire(self._maybe_log_peak(
                    emotion, state_before.get(emotion, 0.0), state_after.get(emotion, 0.0),
                    trigger_user=trigger_user, trigger_message=text,
                    channel_id=channel_id, platform=platform,
                ))
        return None
