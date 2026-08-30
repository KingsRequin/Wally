# bot/core/emotion.py
from __future__ import annotations

import asyncio
import datetime
import json
import math
import os
import random
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from loguru import logger

from bot.core import fiction
from bot.intelligence.identity import bot_name, render_identity

if TYPE_CHECKING:
    from bot.config import Config

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def _extract_json(raw: str) -> dict:
    """Parse JSON from LLM output, handling markdown code blocks."""
    raw = raw.strip()
    # Try direct parse first
    try:
        return json.loads(raw)
    # Première tentative sur trois : le modèle rend souvent son JSON enveloppé
    # dans un bloc markdown, et l'échec ici n'est PAS une erreur — c'est le cas
    # le plus fréquent. Les extractions suivantes prennent le relais, et c'est
    # le bout de la chaîne qui décide s'il faut se plaindre.
    except json.JSONDecodeError:
        pass
    # Try extracting from ```json ... ``` blocks
    m = _JSON_BLOCK_RE.search(raw)
    if m:
        return json.loads(m.group(1).strip())
    # Try finding first { ... } in the text
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        return json.loads(raw[start:end + 1])
    raise json.JSONDecodeError("No JSON found in LLM output", raw, 0)


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
    ("anger",   "joy",     0.4),   # anger érode joy (mais moins que l'inverse)
]


def _build_suppression_map(
    rules: list[tuple[str, str, float]],
) -> dict[str, dict[str, float]]:
    """{émotion qui monte: {émotion érodée: coefficient}}.

    Une paire n'apparaît QU'UNE FOIS par sens. `_apply_suppression` parcourait la
    liste brute avec `if emotion == src` / `elif emotion == tgt` : joy/anger y
    figurant deux fois, une hausse de joy érodait anger de 0.8 (règle 1) PUIS de
    0.4 (règle 3), soit 1.2 — et symétriquement. L'asymétrie annoncée juste
    au-dessus (« anger érode joy, mais moins que l'inverse ») était donc annulée :
    les deux sens valaient 1.2.

    Le sens déclaré explicitement l'emporte ; les autres sont complétés par le
    sens inverse, ce qui préserve la bidirectionnalité voulue.
    """
    directed: dict[str, dict[str, float]] = {}
    for src, tgt, coeff in rules:
        directed.setdefault(src, {})[tgt] = coeff
    for src, tgt, coeff in rules:
        directed.setdefault(tgt, {}).setdefault(src, coeff)
    return directed


SUPPRESSION_MAP: dict[str, dict[str, float]] = _build_suppression_map(SUPPRESSION_RULES)


@lru_cache(maxsize=2048)
def _motif_mot(mot: str) -> "re.Pattern[str]":
    """Motif d'un mot du lexique : frontières de mot, allongement final toléré.

    Le lexique était testé en SOUS-CHAÎNE (`if w in text_lower`). En français,
    « con » est un préfixe extrêmement fréquent : « concert », « conseil »,
    « configuration », « content » déclenchaient tous +0.10 de colère. Idem
    « nul » dans « annulé », « top » dans « topo ». Ce chemin est le repli
    (utilisé quand le LLM est absent ou en échec) — c'est-à-dire précisément le
    moment où plus rien ne vient contredire une colère qui monte à chaque phrase.

    La dernière lettre accepte d'être répétée : sur du chat, « mdrrr » et
    « ptdrrr » sont la règle, pas l'exception, et perdre ces formes en corrigeant
    les faux positifs serait un échange perdant. Les entrées à plusieurs mots
    (apprises, ex. « à côté de la plaque ») gardent de simples frontières.
    """
    corps = re.escape(mot)
    if mot[-1:].isalpha() and " " not in mot:
        corps = re.escape(mot[:-1]) + re.escape(mot[-1]) + "+"
    return re.compile(rf"(?<!\w){corps}(?!\w)", re.IGNORECASE)


def _mot_present(mot: str, texte: str) -> bool:
    if not mot:
        return False
    return _motif_mot(mot).search(texte) is not None

# Paires distinctes, pour la compétition : elle est symétrique, donc une paire
# traitée deux fois soustrait deux fois `extra`.
COMPETITION_PAIRS: list[tuple[str, str]] = list(
    dict.fromkeys(tuple(sorted((s, t))) for s, t, _ in SUPPRESSION_RULES)
)

# Coefficient de compétition continue pendant le decay (par tick de 60s).
# extra = state[src] * state[tgt] * COMPETITION_K est soustrait des deux émotions.
# Avec K=0.05 : anger=0.65 + joy=0.33 → extra≈0.011/tick → convergence en ~1h.
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

# Template système de _analyze_llm. Les sentinelles {{BOT_NAME}} sont résolues
# au runtime via render_identity() afin que Cindy/Wally/etc. soient corrects.
_ANALYSIS_SYSTEM_TEMPLATE = (
    "Tu es le module d'analyse émotionnelle de {{BOT_NAME}}, un bot de chat Discord. "
    "Ton rôle est de mesurer l'impact d'un échange sur l'état interne de {{BOT_NAME}}.\n\n"

    "## Émotions disponibles\n"
    "anger, joy, sadness, curiosity, boredom\n\n"

    "## Calcul des deltas\n"
    "- Chaque delta est un float dans [0.0, 0.3] représentant une variation positive de l'émotion.\n"
    "- Pondération par la cible :\n"
    "  • Émotion dirigée vers {{BOT_NAME}} → impact plein (delta normal)\n"
    "  • Émotion dirigée entre utilisateurs ({{BOT_NAME}} non concerné) → delta ÷ 3\n"
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
    "- Inside joke, complicité, défendre {{BOT_NAME}} → bonus (+0.05 à +0.10)\n\n"

    "## Love delta\n"
    "Retourne aussi \"love_delta\" : un float dans [0.0, 0.10].\n"
    "- Interaction chaleureuse, drôle partagée, intérêt sincère pour {{BOT_NAME}} → positif (+0.02 à +0.08)\n"
    "- Le love_delta n'est jamais négatif. L'affection ne baisse que par le decay temporel.\n"
    "- Interaction neutre ou hostile → 0.0\n\n"

    "## Extraction de faits\n"
    "Retourne aussi \"user_facts\" : une liste de faits durables sur l'utilisateur "
    "qui envoie le message déclencheur (centres d'intérêt, préférences, faits "
    "biographiques, opinions exprimées). Liste vide si rien de durable.\n"
    "Ignore les GIF, mèmes, liens média (Tenor, Giphy, Imgur, etc.), "
    "partager un GIF n'est PAS un fait durable.\n\n"

    "## Exemple\n"
    "trust_score: 0.30\n"
    "Historique :\n"
    "[Alice]: c'est vraiment nul comme réponse\n"
    "Message déclencheur :\n"
    "[Bob]: ouais {{BOT_NAME}} t'es carrément à côté de la plaque là\n"
    "→ Réponse attendue :\n"
    '{"deltas": {"anger": 0.22, "joy": 0.0, "sadness": 0.05, "curiosity": 0.0, "boredom": 0.0}, '
    '"new_words": [{"word": "à côté de la plaque", "emotion": "anger", "delta": 0.10}], '
    '"trust_delta": -0.05, "love_delta": 0.0, "user_facts": []}\n\n'

    "## Format de sortie\n"
    "JSON valide uniquement, sans markdown ni commentaire :\n"
    '{"deltas": {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}, '
    '"new_words": [{"word": "...", "emotion": "...", "delta": 0.0}], "trust_delta": 0.0, "love_delta": 0.0, "user_facts": []}'
)


def build_emotion_tag(emotion_state: dict[str, float]) -> str:
    """Construit un tag textuel à partir des émotions dominantes (≥ 0.2).

    Retourne "" si aucune émotion n'est dominante.
    Exemple : "Wally: joy, curiosity"
    """
    dominant = [e for e, v in emotion_state.items() if v >= 0.2]
    if not dominant:
        return ""
    return f"{bot_name()}: " + ", ".join(dominant)


def _coerce_facts(facts) -> list[str]:
    """Normalise `user_facts` du LLM en liste de strings non vides.

    Le schéma demande des strings, mais le LLM renvoie parfois des dicts
    (`{"fact": "..."}`) ou des valeurs nulles. On extrait le texte et on jette
    le reste, pour garantir le contrat `memory.add(content: str)`.
    """
    if not isinstance(facts, list):
        return []
    out: list[str] = []
    for f in facts:
        if isinstance(f, dict):
            f = f.get("fact") or f.get("text") or f.get("content") or ""
        if isinstance(f, str) and f.strip():
            out.append(f.strip())
    return out


class EmotionEngine:
    # Taux de montée du boredom par heure d'inactivité (linéaire, clampé à 1.0)
    DEFAULT_BOREDOM_RISE_PER_HOUR: float = 1.2

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
        # Quand la sauvegarde en attente a été demandée pour la 1re fois, pour
        # borner le debounce (cf. `_schedule_save`).
        self._save_first_requested_at: float = 0.0
        self._ticks: int = 0
        # Peak detection anti-spam cache: emotion → timestamp of last peak
        self._last_peak_ts: dict[str, float] = {}
        self._bg_tasks: set[asyncio.Task] = set()
        # Mood layer (EMA of emotions, slow-moving baseline)
        self._mood: dict[str, float] = {e: 0.0 for e in EMOTIONS}
        # Fatigue: refractory period after peaks
        self._fatigue: dict[str, float] = {e: 0.0 for e in EMOTIONS}
        # Retombée : pic atteint depuis le début de l'épisode en cours, par
        # émotion. Remis à zéro quand l'émotion repasse sous `reset_below` —
        # sans quoi une seule vraie colère justifierait des retombées jusqu'au
        # prochain redémarrage.
        self._peak_since_calm: dict[str, float] = {e: 0.0 for e in EMOTIONS}
        # Per-user emotional memory (affinity)
        self._user_affinity: dict[tuple[str, str], dict] = {}
        # Habituation tracker
        self._habituation_tracker: dict[tuple[str, str], list[tuple[str, float]]] = {}
        self._load_learned_words()

    # ── State access ─────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, float]:
        return dict(self._state)

    def get_mood(self) -> dict[str, float]:
        return dict(self._mood)

    def _update_mood(self, delta_t_hours: float = 0.0) -> None:
        """EMA update + slow exponential decay toward neutral."""
        mood_cfg = getattr(self._config, "mood", None)
        a = mood_cfg.alpha if mood_cfg and isinstance(getattr(mood_cfg, "alpha", None), (int, float)) else 0.02
        lam = mood_cfg.decay_lambda if mood_cfg and isinstance(getattr(mood_cfg, "decay_lambda", None), (int, float)) else 0.1
        for e in EMOTIONS:
            self._mood[e] = a * self._state[e] + (1 - a) * self._mood[e]
            if delta_t_hours > 0 and self._mood[e] > 0:
                self._mood[e] *= math.exp(-lam * delta_t_hours)

    def _apply_mood_bias(self, emotion: str, delta: float) -> float:
        """Mood amplifies deltas for matching emotions."""
        if delta <= 0:
            return delta
        mood_cfg = getattr(self._config, "mood", None)
        bias = mood_cfg.bias_factor if mood_cfg and isinstance(getattr(mood_cfg, "bias_factor", None), (int, float)) else 0.3
        return delta * (1 + self._mood.get(emotion, 0.0) * bias)

    def get_fatigue(self) -> dict[str, float]:
        return dict(self._fatigue)

    def _apply_fatigue(self, emotion: str, delta: float) -> float:
        if delta <= 0 or self._fatigue.get(emotion, 0.0) <= 0:
            return delta
        fatigue_cfg = getattr(self._config, "fatigue", None)
        dampening = fatigue_cfg.dampening if fatigue_cfg and isinstance(getattr(fatigue_cfg, "dampening", None), (int, float)) else 0.7
        return delta * (1 - self._fatigue[emotion] * dampening)

    def _check_fatigue_trigger(self, emotion: str, old_value: float, new_value: float) -> None:
        if emotion == "boredom":
            return
        threshold = getattr(self._config.bot, "emotion_peak_threshold", 0.7)
        if not isinstance(threshold, (int, float)):
            threshold = 0.7
        if old_value < threshold <= new_value:
            self._fatigue[emotion] = new_value

    def _recover_fatigue(self, hours_elapsed: float) -> None:
        fatigue_cfg = getattr(self._config, "fatigue", None)
        rate = fatigue_cfg.recovery_rate if fatigue_cfg and isinstance(getattr(fatigue_cfg, "recovery_rate", None), (int, float)) else 0.1
        for e in EMOTIONS:
            if self._fatigue[e] > 0:
                self._fatigue[e] = max(0.0, self._fatigue[e] - rate * hours_elapsed)

    def _maybe_spontaneous_event(self) -> None:
        """Roll for a spontaneous internal emotion event, modulated by mood."""
        spont = getattr(self._config, "spontaneous", None)
        if not spont or not isinstance(getattr(spont, "probability_per_tick", None), (int, float)) or spont.probability_per_tick <= 0:
            return
        if random.random() >= spont.probability_per_tick:
            return
        events = spont.events
        if not events:
            return
        # Build mood-biased weights
        items = list(events.items())
        mood_bias_map = {
            "sadness": ["unpleasant_memory"],
            "curiosity": ["wandering_thought", "creative_spark"],
            "joy": ["pleasant_memory"],
            "boredom": ["existential_ennui"],
        }
        weights = []
        for name, ev in items:
            w = ev.weight
            for mood_e, event_names in mood_bias_map.items():
                if name in event_names and self._mood.get(mood_e, 0.0) > 0.3:
                    w *= 1 + self._mood[mood_e]
            weights.append(w)
        chosen = random.choices(items, weights=weights, k=1)[0]
        name, event = chosen
        max_d = spont.max_delta
        for emotion, delta in event.effects.items():
            clamped = max(-max_d, min(max_d, delta))
            if emotion in self._state:
                self._state[emotion] = max(0.0, min(1.0, self._state[emotion] + clamped))

    def _apply_competition(self) -> None:
        """Érode mutuellement les émotions incompatibles (appelée après chaque decay tick).

        Pour chaque paire (src, tgt) dans SUPPRESSION_RULES :
            extra = state[src] * state[tgt] * COMPETITION_K
        Les deux valeurs baissent de `extra`, clampées à 0.0.
        """
        # Sur les PAIRES distinctes : joy/anger figurant deux fois dans
        # SUPPRESSION_RULES, elle subissait deux passes par tick, soit le double
        # de l'`extra` annoncé dans le commentaire de COMPETITION_K.
        for src, tgt in COMPETITION_PAIRS:
            extra = self._state[src] * self._state[tgt] * COMPETITION_K
            if extra <= 0:
                continue
            self._state[src] = max(0.0, self._state[src] - extra)
            self._state[tgt] = max(0.0, self._state[tgt] - extra)

    def _apply_suppression(self, emotion: str, delta: float) -> None:
        """Supprime partiellement les émotions incompatibles si delta > 0.

        Un seul coefficient par sens (cf. `_build_suppression_map`) : le parcours
        de la liste brute cumulait deux règles pour joy/anger.
        """
        if delta <= 0:
            return
        for cible, coeff in SUPPRESSION_MAP.get(emotion, {}).items():
            self._state[cible] = max(0.0, self._state[cible] - delta * coeff)

    def _apply_circadian(self, emotion: str, delta: float) -> float:
        """Apply circadian rhythm multiplier to delta based on time of day."""
        if delta <= 0:
            return delta
        circ = getattr(self._config, "circadian", None)
        if not circ or not getattr(circ, "enabled", True):
            return delta

        tz_name = getattr(circ, "timezone", None)
        if not isinstance(tz_name, str):
            return delta
        tz = ZoneInfo(tz_name)
        now = datetime.datetime.now(tz)
        hour_float = now.hour + now.minute / 60.0

        # Find current period
        periods = circ.periods if hasattr(circ, "periods") else {}
        for _name, p in periods.items():
            start, end = p.hours
            if start <= hour_float < end:
                mult = getattr(p, emotion, 1.0)
                return delta * mult

        return delta

    # ── Per-user affinity & habituation ────────────────────────────────────

    def get_user_affinity(self, user_id: str, platform: str) -> dict[str, float]:
        key = (user_id, platform)
        if key not in self._user_affinity:
            return {e: 0.0 for e in EMOTIONS}
        return {e: self._user_affinity[key].get(e, 0.0) for e in EMOTIONS}

    def update_user_affinity(self, user_id: str, platform: str, deltas: dict[str, float]) -> None:
        key = (user_id, platform)
        if key not in self._user_affinity:
            self._user_affinity[key] = {e: 0.0 for e in EMOTIONS}
            self._user_affinity[key]["_count"] = {e: 0 for e in EMOTIONS}
        mem_cfg = getattr(self._config, "emotional_memory", None)
        lr = mem_cfg.learning_rate if mem_cfg else 0.05
        for e in EMOTIONS:
            d = deltas.get(e, 0.0)
            if d != 0.0:
                self._user_affinity[key][e] = max(-1.0, min(1.0, self._user_affinity[key].get(e, 0.0) + lr * d))
                self._user_affinity[key]["_count"][e] = self._user_affinity[key]["_count"].get(e, 0) + 1

    def _get_priming_deltas(self, user_id: str, platform: str) -> dict[str, float]:
        mem_cfg = getattr(self._config, "emotional_memory", None)
        pf = mem_cfg.priming_factor if mem_cfg else 0.05
        aff = self.get_user_affinity(user_id, platform)
        return {e: aff[e] * pf for e in EMOTIONS}

    def _apply_affinity_amplification(self, user_id: str, platform: str, emotion: str, delta: float) -> float:
        if delta <= 0:
            return delta
        mem_cfg = getattr(self._config, "emotional_memory", None)
        amp = mem_cfg.amplification_factor if mem_cfg else 0.3
        aff = self.get_user_affinity(user_id, platform)
        affinity_val = aff.get(emotion, 0.0)
        if affinity_val <= 0:
            return delta
        return delta * (1 + affinity_val * amp)

    def _apply_habituation(self, user_id: str, emotion: str, delta: float) -> float:
        if delta <= 0:
            return delta
        hab_cfg = getattr(self._config, "habituation", None)
        if not hab_cfg:
            return delta
        exempt = hab_cfg.exempt if hasattr(hab_cfg, "exempt") else ["anger"]
        if emotion in exempt:
            return delta
        key = (user_id, emotion)
        now = time.time()
        # Purge paresseuse : seules les LISTES étaient élaguées, jamais les clés.
        # Quatre entrées par personne croisée — chat Twitch compris — sur un
        # process qui tourne des semaines, sans borne. Même patron que celui
        # déjà appliqué à `_cooldowns` et `_relances`.
        if len(self._habituation_tracker) > 512:
            fenetre = getattr(hab_cfg, "reset_seconds", 1800)
            self._habituation_tracker = {
                k: v for k, v in self._habituation_tracker.items()
                if v and now - v[-1][1] < fenetre
            }
        if key not in self._habituation_tracker:
            self._habituation_tracker[key] = []
        entries = self._habituation_tracker[key]
        reset = hab_cfg.reset_seconds if hasattr(hab_cfg, "reset_seconds") else 1800
        if entries and (now - entries[-1][1]) > reset:
            entries.clear()
        window = hab_cfg.window_seconds if hasattr(hab_cfg, "window_seconds") else 600
        entries[:] = [(e, t) for e, t in entries if now - t < window]
        entries.append((emotion, now))
        threshold = hab_cfg.threshold_count if hasattr(hab_cfg, "threshold_count") else 3
        count = len(entries)
        if count <= threshold:
            return delta
        excess = count - threshold
        decay = hab_cfg.decay_factor if hasattr(hab_cfg, "decay_factor") else 0.5
        return delta * (decay ** excess)

    def prepare_deltas(
        self, raw_deltas: dict[str, float],
        user_id: str = "", platform: str = "",
        beloved: bool = False,
    ) -> dict[str, float]:
        """Full pipeline: circadian -> priming -> mood -> amplification -> habituation -> fatigue.

        beloved=True annule les HAUSSES d'anger et de sadness : cet utilisateur ne
        peut pas dégrader l'humeur, qui est globale et partagée par tout le monde.
        Les baisses passent, et joy/curiosity ne sont pas touchées.
        """
        result = {}
        priming = self._get_priming_deltas(user_id, platform) if user_id else {e: 0.0 for e in EMOTIONS}
        for e in EMOTIONS:
            delta = raw_deltas.get(e, 0.0) + priming.get(e, 0.0)
            if delta > 0:
                delta = self._apply_circadian(e, delta)
                delta = self._apply_mood_bias(e, delta)
                if user_id:
                    delta = self._apply_affinity_amplification(user_id, platform, e, delta)
                if user_id:
                    delta = self._apply_habituation(user_id, e, delta)
                delta = self._apply_fatigue(e, delta)
            result[e] = delta
        if beloved:
            for e in ("anger", "sadness"):
                if result.get(e, 0.0) > 0:
                    result[e] = 0.0
        return result

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
        self._check_fatigue_trigger(emotion, old, self._state[emotion])
        self._dirty = True
        self._schedule_save()

    def world_event(self, nom: str, trigger_user: str = "", platform: str = "") -> None:
        """Ce que le monde fait à Wally — point d'entrée unique des déclencheurs.

        Le mécanisme est ici, les intensités dans `config.yaml`
        (`emotions.world_events`). Ce n'est pas de la décoration : mesuré sur
        30 jours, le code portait onze `apply_delta("joy")` codés en dur dans
        autant de handlers (follow, sub, bits, raid, réaction, on lui répond…),
        trois pour la curiosité, deux pour la colère — et **aucun** pour la
        tristesse. Un déséquilibre pareil ne se voit pas quand chaque source
        vit chez elle ; il saute aux yeux dans une liste unique.

        Passe par `apply_delta`, donc subit inertie et suppression comme le
        reste : une tristesse qui tombe sur une grosse joie est amortie et érode
        cette joie, au lieu de coexister avec elle.

        Silencieux sur un nom inconnu : retirer un déclencheur de la config ne
        doit jamais casser le sous-système qui l'appelle.
        """
        events = getattr(self._config, "world_events", None)
        if not events:
            return
        event = events.get(nom)
        if event is None:
            return
        effects = getattr(event, "effects", None) or {}
        avant = self.get_state()
        for emotion, delta in effects.items():
            if emotion in self._state and delta:
                self.apply_delta(emotion, delta)
        apres = self.get_state()
        logger.info(
            "Événement du monde « {n} » : {d}",
            n=nom,
            d=", ".join(
                f"{e} {avant[e]:.2f}→{apres[e]:.2f}"
                for e in effects if e in self._state and abs(apres[e] - avant[e]) > 0.001
            ) or "aucun effet",
        )
        # Les pics de tristesse n'apparaissaient nulle part dans `emotion_peaks`
        # (61 pics de colère, 54 de joie, 0 de tristesse) : sans ce log, on ne
        # saurait pas davantage mesurer l'effet du correctif que le défaut.
        for emotion, delta in effects.items():
            if delta > 0 and emotion in self._state:
                try:
                    self._fire(self._maybe_log_peak(
                        emotion, avant.get(emotion, 0.0), apres.get(emotion, 0.0),
                        trigger_user=trigger_user, trigger_message=f"[monde] {nom}",
                        platform=platform,
                    ))
                # Appelé hors boucle asyncio : l'émotion est déjà appliquée, seule
                # la trace manque. Un confort d'observabilité n'a pas à faire
                # échouer un événement du monde.
                except RuntimeError:
                    pass

    def set_emotion(self, emotion: str, value: float) -> None:
        if emotion in self._state:
            old = self._state[emotion]
            self._state[emotion] = max(0.0, min(1.0, value))
            effective_delta = self._state[emotion] - old
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

    def get_secondary_emotions(self) -> list[tuple[str, float]]:
        """Secondaires actives, en (nom, intensité), la plus saillante en tête.

        Le tri se fait par intensité PUIS par exigence, et ce second critère
        n'est pas cosmétique : `prompts.py` retient la première et s'arrête.

        Deux secondaires peuvent porter le même couple d'émotions — `pride`
        (joy+curiosity, 0.4) et `wonder` (curiosity+joy, 0.5), `frustration` et
        `contempt` (anger+boredom). Comme l'intensité vaut `min(a, b)`, elle est
        alors IDENTIQUE des deux côtés : un tri par intensité seule ne les
        départage pas et laisse gagner l'ordre d'insertion, c'est-à-dire la
        version la moins exigeante. Mesuré sur 30 jours, `wonder` était éligible
        15 fois et n'est jamais sortie une seule.

        À intensité égale, la règle qui demande le plus passe donc devant —
        comme une règle précise l'emporte sur une règle générale.
        """
        secondaries = getattr(self._config, "secondaries", None)
        if not secondaries or not isinstance(secondaries, dict):
            return []
        classees: list[tuple[str, float, float]] = []
        for name, defn in secondaries.items():
            val_a = self._state.get(defn.a, 0.0)
            val_b = self._state.get(defn.b, 0.0)
            threshold = defn.threshold
            if isinstance(threshold, list):
                if val_a < threshold[0] or val_b < threshold[1]:
                    continue
                exigence = max(threshold)
            else:
                if val_a < threshold or val_b < threshold:
                    continue
                exigence = threshold
            classees.append((name, min(val_a, val_b), exigence))
        classees.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [(nom, intensite) for nom, intensite, _ in classees]

    def set_openai_client(self, client) -> None:
        """Injection du client LLM secondaire pour l'analyse émotionnelle."""
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
                logger.warning("Failed to log emotion peak: {e!r}", e=exc)

    async def load_state(self) -> None:
        """Charge l'état émotionnel depuis la DB. No-op si db est None."""
        if self._db is None:
            return
        try:
            loaded = await self._db.load_emotion_state()
            for emotion, value in loaded.items():
                if emotion in self._state:
                    self._state[emotion] = max(0.0, min(1.0, value))
            # Rattrapage du temps d'arrêt. `updated_at` était écrit à chaque
            # sauvegarde et jamais relu : l'état repartait figé, si bien qu'une
            # colère à 0.80 sauvée à 2 h du matin revenait à 0.80 à 14 h. En
            # reculant `_last_decay` à la date de la sauvegarde, la décroissance
            # normale s'applique d'elle-même sur l'intervalle écoulé.
            try:
                sauvegarde = await self._db.load_emotion_state_age()
            except Exception as exc:  # noqa: BLE001 — jamais bloquant au boot
                logger.warning("Âge de l'état émotionnel illisible : {e!r}", e=exc)
                sauvegarde = None
            logger.info("Emotion state loaded from DB: {s}", s=self._state)
            # Load mood layer
            mood = await self._db.load_mood_state()
            for e in EMOTIONS:
                self._mood[e] = mood.get(e, 0.0)
            logger.info("Mood state loaded from DB: {s}", s=self._mood)
            # Load fatigue layer
            fatigue = await self._db.load_fatigue_state()
            for e in EMOTIONS:
                self._fatigue[e] = fatigue.get(e, 0.0)
            logger.info("Fatigue state loaded from DB: {s}", s=self._fatigue)
            # Load user affinities (emotional memory)
            await self.load_user_affinities()

            # Le vieillissement vient EN DERNIER, une fois toutes les couches
            # chargées. Placé plus haut, `_apply_decay` faisait décroître une
            # humeur, une fatigue et des affinités encore à zéro, puis les
            # lectures ci-dessus écrasaient son travail : seul `_state` était
            # réellement vieilli, et l'affinité par personne ne redescendait
            # jamais à travers un redémarrage — le cliquet exact que ce
            # rattrapage était censé supprimer.
            #
            # Seuil de 60 s : `_apply_decay` déclenche aussi la compétition
            # entre émotions et la récupération de fatigue ; le faire tourner
            # pour un redémarrage de trois secondes altérerait l'état sans
            # raison — la boucle de decay s'en charge toutes les 60 s.
            ecoule = time.time() - sauvegarde if sauvegarde else 0.0
            if sauvegarde and 0 < sauvegarde < time.time() and ecoule > 60:
                self._last_decay = sauvegarde
                # L'ennui ne décroît pas, il MONTE avec l'inactivité, et il se
                # calcule sur `_last_interaction` — laissé à l'heure du boot, il
                # rendait `idle_hours ≈ 0` : Wally revenait de douze heures
                # d'absence sans le moindre ennui accumulé.
                self._last_interaction = sauvegarde
                self._apply_decay()
                logger.info(
                    "État émotionnel vieilli de {h:.1f} h d'arrêt : {s}",
                    h=ecoule / 3600.0, s=self._state,
                )
        except Exception as exc:
            logger.warning("Failed to load emotion state: {e!r}", e=exc)

    async def load_user_affinities(self) -> None:
        """Load all affinities from DB into memory cache."""
        if not self._db:
            return
        rows = await self._db.fetch_all(
            "SELECT user_id, platform, emotion, affinity, interaction_count FROM emotional_memory"
        )
        for row in rows:
            key = (row["user_id"], row["platform"])
            if key not in self._user_affinity:
                self._user_affinity[key] = {e: 0.0 for e in EMOTIONS}
                self._user_affinity[key]["_count"] = {e: 0 for e in EMOTIONS}
            self._user_affinity[key][row["emotion"]] = float(row["affinity"])
            self._user_affinity[key]["_count"][row["emotion"]] = int(row["interaction_count"])
        if rows:
            logger.info("Loaded emotional memory for {n} user-emotion pairs", n=len(rows))

    async def _save_user_affinities(self) -> None:
        """Persist all in-memory affinities to DB."""
        if not self._db:
            return
        # `list()` : chaque `upsert` cède la main, et un message d'un nouvel
        # interlocuteur pendant ce temps agrandit le dict — jusqu'à 385 points de
        # yield avec 77 couples en base. Le RuntimeError qui en résultait était
        # avalé par `_delayed_save` : la mémoire émotionnelle par personne ne
        # s'écrivait jamais, précisément pendant un live ou une discussion animée.
        for (user_id, platform), data in list(self._user_affinity.items()):
            for e in EMOTIONS:
                aff = data.get(e, 0.0)
                count = data.get("_count", {}).get(e, 0)
                if aff != 0.0 or count > 0:
                    await self._db.upsert_emotional_memory(user_id, platform, e, aff, count)

    # Au-delà, le debounce cède : on écrit même si les demandes continuent.
    SAVE_MAX_DEFERRAL_S = 30.0

    def _schedule_save(self) -> None:
        """Debounce BORNÉ : au plus tard `SAVE_MAX_DEFERRAL_S` après la 1re demande.

        Le debounce annulait la tâche en attente et en replanifiait une à +5 s.
        Or `process_message` appelle `apply_delta` une fois par émotion — cinq
        par message — plus `record_interaction`, et chacun replanifiait. Il
        suffisait donc qu'un message arrive moins de 5 s après le précédent pour
        que la sauvegarde ne parte JAMAIS.

        Autrement dit : pendant un live ou une discussion animée — le moment où
        l'état émotionnel bouge le plus — `emotion_state`, `mood`, `fatigue` et
        les affinités n'étaient plus écrits du tout, et un rebuild ramenait
        l'état à la dernière fenêtre calme.
        """
        if self._db is None:
            return
        maintenant = time.monotonic()
        if self._save_task and not self._save_task.done():
            # Une écriture attend déjà depuis trop longtemps : on la laisse
            # aboutir au lieu de repousser encore l'échéance.
            if maintenant - self._save_first_requested_at >= self.SAVE_MAX_DEFERRAL_S:
                return
            self._save_task.cancel()
        else:
            self._save_first_requested_at = maintenant
        self._save_task = asyncio.create_task(self._delayed_save())

    async def flush(self) -> None:
        """Écrit l'état en attente MAINTENANT. À appeler à l'arrêt du process.

        La séquence d'arrêt ne touchait ni le moteur ni `_save_task`, simplement
        annulée avec la boucle : tout ce qui attendait dans le debounce était
        perdu.
        """
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
            self._save_task = None
        if not (self._db and self._dirty):
            return
        try:
            await self._db.save_emotion_state(self._state)
            await self._db.save_mood_state(self._mood)
            await self._db.save_fatigue_state(self._fatigue)
            await self._save_user_affinities()
            self._dirty = False
            logger.info("État émotionnel écrit avant l'arrêt")
        except Exception as exc:  # noqa: BLE001 — un arrêt ne doit pas bloquer
            logger.warning("Flush de l'état émotionnel échoué: {e!r}", e=exc)

    async def _delayed_save(self) -> None:
        await asyncio.sleep(5)
        if self._db and self._dirty:
            try:
                await self._db.save_emotion_state(self._state)
                await self._db.save_mood_state(self._mood)
                await self._db.save_fatigue_state(self._fatigue)
                await self._save_user_affinities()
                self._dirty = False
            except Exception as exc:
                logger.warning("Failed to persist emotion state: {e!r}", e=exc)
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
        # Premier démarrage : le fichier d'apprentissage n'existe pas encore, et
        # c'est le cas NORMAL. Toute autre erreur est journalisée juste en dessous
        # — seule l'absence est muette.
        except FileNotFoundError:
            pass  # premier démarrage — normal
        except Exception as exc:
            logger.warning("Failed to load learned words: {e!r}", e=exc)

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
                logger.warning("Failed to save learned words: {e!r}", e=exc)

    async def _learn_words(self, new_words: list[dict]) -> None:
        """Valide et ajoute les nouveaux mots appris depuis le LLM."""
        added = False
        for entry in new_words:
            # Sur le chemin image, la réponse est parsée sans schéma : le modèle
            # rend parfois une liste de chaînes. `entry.get()` levait alors une
            # AttributeError qui faisait rejouer toute l'analyse émotionnelle.
            if not isinstance(entry, dict):
                logger.debug("Mot appris ignoré (format inattendu) : {e}", e=entry)
                continue
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
        system_prompt = render_identity(_ANALYSIS_SYSTEM_TEMPLATE)
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
            # Images require multimodal content blocks — use plain complete + json.loads
            raw = await self._openai.complete(
                system_prompt,
                [{"role": "user", "content": user_msg}],
                purpose="emotion_analysis",
                image_urls=image_urls,
            )
            parsed = _extract_json(raw)
            raw_deltas = parsed.get("deltas", {})
            new_words = parsed.get("new_words", [])
            trust_delta = max(-0.1, min(0.1, float(parsed.get("trust_delta", 0.0))))
            love_delta = max(0.0, min(0.1, float(parsed.get("love_delta", 0.0))))
            user_facts = parsed.get("user_facts", [])
        else:
            # No images — use structured outputs (schema-guaranteed response)
            parsed = await self._openai.complete_structured(
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
        # DeFensif : le schéma demande des strings, mais DeepSeek renvoie parfois
        # des dicts (confusion avec new_words voisin) → `memory.add(content: str)`
        # plante ensuite sur un `.lower()` (« 'dict' object has no attribute 'lower' »).
        user_facts = _coerce_facts(user_facts)
        return deltas, new_words, trust_delta, love_delta, user_facts

    # ── Decay ─────────────────────────────────────────────────────────────────

    def _apply_decay(self) -> None:
        now = time.time()
        delta_t = now - self._last_decay
        if delta_t <= 0:
            return
        pertes: dict[str, float] = {}
        for emotion in EMOTIONS:
            if emotion == "boredom":
                continue  # boredom géré séparément ci-dessous
            cfg = self._config.emotions.get(emotion)
            if not cfg or self._state[emotion] <= 0:
                continue
            avant = self._state[emotion]
            if avant > self._peak_since_calm[emotion]:
                self._peak_since_calm[emotion] = avant
            lam = cfg.decay_lambda
            decayed = avant * math.exp(-lam * (delta_t / 3600.0))
            self._state[emotion] = 0.0 if decayed < DECAY_FLOOR else decayed
            pertes[emotion] = avant - self._state[emotion]
        # Boredom monte quand personne n'interagit (inversement au decay des autres)
        idle_hours = (now - self._last_interaction) / 3600.0
        boredom_cfg = self._config.emotions.get("boredom")
        rise = boredom_cfg.boredom_rise_per_hour if boredom_cfg and boredom_cfg.boredom_rise_per_hour is not None else self.DEFAULT_BOREDOM_RISE_PER_HOUR
        boredom_target = min(1.0, idle_hours * rise)
        if boredom_target > self._state["boredom"]:
            self._state["boredom"] = boredom_target
        self._last_decay = now
        self._apply_aftermath(pertes)
        self._decay_user_affinity(delta_t / 86400.0)
        self._apply_competition()
        self._recover_fatigue(delta_t / 3600.0)
        self._update_mood(delta_t / 3600.0)
        self._maybe_spontaneous_event()

    def _apply_aftermath(self, pertes: dict[str, float]) -> None:
        """Le contrecoup : la décrue d'une émotion en nourrit une autre.

        Une vraie colère ne s'évapore pas, elle laisse un goût amer. Mesuré sur
        30 jours de production, la tristesse ne dominait que 0.3 % du temps et
        n'avait produit aucun pic : le monde de Wally comptait onze sources de
        joie, deux de colère et aucune de tristesse. Le contrecoup est la
        première — et il est un MÉCANISME, pas une humeur écrite en dur : les
        couples et les coefficients vivent dans `config.yaml`.

        Deux garde-fous portent tout le sens :

        - Seule la décrue par DECAY compte. La suppression fait elle aussi
          tomber la colère (`apply_delta("joy")` l'érode de 0.8×) ; convertir
          cette baisse-là rendrait Wally triste chaque fois qu'on le déride,
          exactement l'inverse du mécanisme voulu. D'où le passage par `pertes`,
          rempli dans la seule boucle de decay.
        - Sous `min_peak`, rien. Un agacement de dix secondes qui retombe ne
          doit pas laisser de traîne mélancolique.

        La retombée passe par `apply_delta` et non par une écriture directe :
        elle subit ainsi l'inertie et la suppression comme n'importe quelle
        émotion — une tristesse qui naît alors que la joie est haute est
        amortie, et elle érode cette joie en retour.
        """
        cfg = getattr(self._config, "aftermath", None)
        if not cfg or not getattr(cfg, "enabled", False):
            return
        regles = getattr(cfg, "rules", None)
        if not regles:
            return
        for regle in regles.values():
            perte = pertes.get(regle.source, 0.0)
            if perte <= 0:
                continue
            if self._peak_since_calm.get(regle.source, 0.0) < regle.min_peak:
                continue
            self.apply_delta(regle.target, perte * regle.ratio)
        # Réarmement APRÈS conversion : inverser l'ordre perdrait la dernière
        # tranche, celle qui fait passer la source sous le seuil.
        for regle in regles.values():
            if self._state.get(regle.source, 0.0) < regle.reset_below:
                self._peak_since_calm[regle.source] = 0.0

    def _decay_user_affinity(self, delta_jours: float) -> None:
        """Fait s'estomper l'affinité par personne. `A(t) = A₀ × e^(−λ × Δjours)`.

        `EmotionalMemoryConfig.decay_lambda_per_day` existait dans la config et
        dans `config.yaml`, mais n'était lu NULLE PART : l'affinité était un
        cliquet. `update_user_affinity` n'est alimentée que par des deltas ≥ 0
        (`_analyze_llm` clampe à [0, MAX_DELTA_PER_MESSAGE], `_analyze_sync` ne
        produit que du positif), donc elle ne pouvait que croître jusqu'au clamp
        à 1.0 — et elle est persistée, donc le cliquet survivait aux
        redémarrages.

        Ce qui en découlait : `_get_priming_deltas` ajoute `affinity × 0.05` à
        CHACUNE des cinq émotions avant même l'analyse, colère comprise. Après
        quelques centaines d'échanges, le moindre message d'un habitué poussait
        mécaniquement les cinq émotions vers le haut. L'intention portée par la
        config — « la mémoire émotionnelle s'estompe » — était exactement
        inversée.
        """
        if delta_jours <= 0 or not self._user_affinity:
            return
        mem_cfg = getattr(self._config, "emotional_memory", None)
        lam = getattr(mem_cfg, "decay_lambda_per_day", 0.0) if mem_cfg else 0.0
        if not lam or lam <= 0:
            return
        facteur = math.exp(-lam * delta_jours)
        for affinites in self._user_affinity.values():
            for emotion in EMOTIONS:
                valeur = affinites.get(emotion, 0.0)
                if not valeur:
                    continue
                estompee = valeur * facteur
                affinites[emotion] = 0.0 if abs(estompee) < DECAY_FLOOR else estompee

    async def _decay_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            # Le tour entier est gardé, pas seulement le snapshot. Sans ça, une
            # seule exception tuait la tâche DÉFINITIVEMENT et rien ne la
            # relançait : plus de decay (la colère restait figée à sa valeur,
            # donc permanente), plus de montée d'ennui, plus de compétition,
            # plus de sauvegarde. Et pas une ligne de log — l'exception d'une
            # Task morte n'est rapportée qu'au ramassage. Le symptôme observable
            # aurait été « ses émotions ne bougent plus », sans cause visible.
            #
            # La porte d'entrée n'est pas théorique : `_maybe_spontaneous_event`
            # finit par un `random.choices(items, weights=…)`, qui lève sur une
            # somme de poids nulle — et ces poids viennent de `config.yaml`,
            # que le dashboard réécrit.
            try:
                self._apply_decay()
                self._dirty = True
                self._schedule_save()
                logger.debug("Emotion decay applied: {state}", state=self._state)
                self._ticks += 1
                if self._ticks % 60 == 0 and self._db:
                    await self._db.insert_emotion_snapshot(self._state)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — un tour raté ne tue pas la boucle
                logger.error("Emotion decay tick failed: {e!r}", e=exc)

    def start_decay_task(self) -> None:
        self._decay_task = asyncio.create_task(self._decay_loop())
        logger.info("Emotion decay task started")

    # ── NRCLex analysis ───────────────────────────────────────────────────────

    async def analyze_message(
        self, text: str, trust_score: float = 0.0
    ) -> dict[str, float]:
        return await asyncio.to_thread(self._analyze_sync, text, trust_score)

    def _analyze_sync(self, text: str, trust_score: float) -> dict[str, float]:
        """Note l'humeur d'un message sans LLM : lexique anglais puis français.

        Les deux moitiés sont gardées SÉPARÉMENT, et ce n'est pas un détail de
        style : elles étaient sous un `try` unique, si bien qu'une panne de
        `nrclex` — un lexique ANGLAIS — emportait aussi la détection des mots
        FRANÇAIS, sur un bot qui parle français. Une moitié qui tombe ne doit
        coûter que sa moitié.
        """
        deltas: dict[str, float] = {}
        text_lower = text.lower()

        try:
            from nrclex import NRCLex  # local import — heavy at first call

            # v4 API: constructor loads the lexicon (no text arg); then
            # load_token_list avoids NLTK/textblob corpus dependency.
            nrc = NRCLex()
            nrc.load_token_list(text_lower.split())
            scores = nrc.affect_frequencies

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
        except Exception as exc:
            logger.warning("NRCLex analysis failed: {e!r}", e=exc)

        # Supplement with French keyword detection (NRCLex is English-only)
        # Merge hardcoded + learned words
        try:
            all_fr_words: dict[str, list[tuple[str, float]]] = {}
            for emotion in EMOTIONS:
                all_fr_words[emotion] = list(FR_EMOTION_WORDS.get(emotion, [])) + list(self._learned_words.get(emotion, []))

            for emotion, word_deltas in all_fr_words.items():
                fr_raw = sum(d for w, d in word_deltas if _mot_present(w, text_lower))
                if fr_raw > 0:
                    combined = deltas.get(emotion, 0.0) + fr_raw
                    # Note: anger amplification already applied above on the
                    # NRCLex portion — only cap the combined value here to
                    # avoid double-amplifying.
                    combined = min(combined, MAX_DELTA_PER_MESSAGE)
                    deltas[emotion] = combined
        except Exception as exc:
            logger.warning("Analyse des mots français échouée : {e!r}", e=exc)

        return deltas

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
        user_id: str = "",
        beloved: bool = False,
    ) -> dict | None:
        self.record_interaction()
        state_before = self.get_state()
        # SEUL l'appel au LLM est protégé. Le `try` englobait aussi l'application
        # des deltas, `_learn_words` et `update_user_affinity` : une panne APRÈS
        # l'application tombait dans le repli, qui recalculait et RÉAPPLIQUAIT —
        # colère doublée sur un mème insultant, habituation comptée deux fois, et
        # trust/love/user_facts du LLM jetés au profit de l'heuristique ±0.05.
        analyse = None
        if self._openai is not None and context_messages:
            try:
                analyse = await self._analyze_llm(
                    text, trust_score, context_messages, image_urls=image_urls
                )
            except Exception as exc:
                logger.warning("LLM emotion analysis failed, using fallback: {e!r}", e=exc)

        if analyse is not None:
            deltas, new_words, trust_delta, love_delta, user_facts = analyse
            prepared = self.prepare_deltas(deltas, user_id, platform, beloved=beloved)
            for emotion, delta in prepared.items():
                self.apply_delta(emotion, delta)
            if new_words:
                # Écrire sur disque peut échouer sans que l'analyse, elle, soit à refaire.
                try:
                    await self._learn_words(new_words)
                except Exception as exc:
                    logger.warning("Apprentissage des mots échoué : {e!r}", e=exc)
            if user_id and platform:
                self.update_user_affinity(user_id, platform, deltas)
            # Check for peaks
            state_after = self.get_state()
            for emotion, delta in prepared.items():
                if delta > 0:
                    self._fire(self._maybe_log_peak(
                        emotion, state_before.get(emotion, 0.0), state_after.get(emotion, 0.0),
                        trigger_user=trigger_user, trigger_message=text,
                        channel_id=channel_id, platform=platform,
                    ))
            # ── Le cloisonnement de la fiction ────────────────────────
            #
            # LE point de fuite, et il est unique. `context_messages` est la
            # fenêtre glissante du canal, où `append_prelude` a déposé les
            # répliques de WALLY : le LLM d'analyse voit donc ce qu'il vient
            # d'inventer pour un jeu, et le rend volontiers en `user_facts`,
            # qui part droit en `memory.add(source="post_process")`.
            #
            # La garde est ICI et pas dans les deux `_post_process` : c'est le
            # seul endroit où `channel_id` et `user_facts` se rencontrent, donc
            # le seul qui couvre Discord et Twitch sans avoir à y penser deux
            # fois. Voir `bot/core/fiction.py` pour pourquoi on ferme large au
            # lieu de comparer les textes.
            if user_facts and fiction.en_cours(channel_id):
                logger.info(
                    "Fiction en cours sur {c} : {n} fait(s) écarté(s) plutôt "
                    "que mémorisé(s)", c=channel_id, n=len(user_facts),
                )
                user_facts = []
            return {"trust_delta": trust_delta, "love_delta": love_delta, "user_facts": user_facts}
        # Fallback : NRCLex + FR_EMOTION_WORDS
        deltas = await self.analyze_message(text, trust_score)
        prepared = self.prepare_deltas(deltas, user_id, platform, beloved=beloved)
        for emotion, delta in prepared.items():
            self.apply_delta(emotion, delta)
        if user_id and platform:
            self.update_user_affinity(user_id, platform, deltas)
        state_after = self.get_state()
        for emotion, delta in prepared.items():
            if delta > 0:
                self._fire(self._maybe_log_peak(
                    emotion, state_before.get(emotion, 0.0), state_after.get(emotion, 0.0),
                    trigger_user=trigger_user, trigger_message=text,
                    channel_id=channel_id, platform=platform,
                ))
        return None
