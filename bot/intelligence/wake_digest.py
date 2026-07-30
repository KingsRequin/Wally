"""Digest de réveil : ce que Wally a manqué pendant son sommeil.

Wally n'a pas d'interrupteur de sommeil. Il « dort » quand plus personne ne le
sollicite — et quand son process est arrêté. Pendant ce temps, la communauté
continue de parler dans les canaux Discord qu'il perçoit passivement, et il se
réveille aveugle à tout ça : le contexte cognitif ne porte que les 20 dernières
interactions brutes, sans hiérarchie ni synthèse.

**Réveil** = un des deux événements suivants :
  1. la première sollicitation (mention / DM / réponse) après un silence d'au
     moins `MIN_SLEEP_SECONDS` sans être sollicité ;
  2. un démarrage du process alors que le dernier signe de vie de Wally dans les
     logs remonte à plus de `MIN_SLEEP_SECONDS`.

Le réveil est *armé* (synchrone, non bloquant) puis *consommé* au tick cognitif
suivant, qui génère le résumé et l'injecte dans le contexte (`AttentionContext.
wake_digest`).

**Source des messages** : les logs de conversation JSONL
(`logs/conversations/discord/{canal}/{jour}.jsonl`). Ce sont les seuls à contenir
TOUTE la perception passive : `daily_log` (SQLite) ne garde que les échanges
auxquels Wally a lui-même participé, donc rien de ce qui se dit pendant qu'il
dort.

**Scoring** — chaque message perçu reçoit un poids cumulatif, qui sert à choisir
ce qui entre dans le prompt de résumé quand la nuit a été bavarde :
  · mention directe de Wally .................. 10
  · message d'une personne à forte affinité ..... 8
  · sujet lié à ses intérêts connus ............. 6
  · événement communautaire ..................... 5

Les deux dernières catégories sont dérivées des données, pas d'un lexique figé :
les « intérêts » sortent de ses désirs/buts/focus actifs en mémoire, et un
« événement communautaire » est un moment où la communauté se rassemble
(≥ `_BURST_AUTHORS` personnes distinctes dans la même fenêtre de 5 min sur un
canal) ou une annonce diffusée à tous (@everyone / @here).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

from bot.intelligence.identity import bot_name, render_identity

_PARIS = ZoneInfo("Europe/Paris")

# Silence minimal (sans sollicitation) au-delà duquel la reprise est un « réveil ».
MIN_SLEEP_SECONDS = 4 * 3600
# On ne résume jamais plus loin que ça, même après une très longue absence.
MAX_LOOKBACK_SECONDS = 48 * 3600

# Poids du scoring (cf. docstring du module).
WEIGHT_MENTION = 10.0
WEIGHT_AFFINITY = 8.0
WEIGHT_INTEREST = 6.0
WEIGHT_COMMUNITY_EVENT = 5.0

# Affinité (max de trust et love, tous deux dans [0,1]) à partir de laquelle une
# personne compte comme « proche » de Wally.
AFFINITY_THRESHOLD = 0.5

# Segment de chemin des logs de MP (cf. `_conv_channel` : un DM n'a pas de nom
# de canal). Exclu du digest : périmètre = conversations de la communauté.
_DM_SEGMENT = "dm"

_MIN_MESSAGES = 5      # en dessous, la nuit n'a rien à raconter
_MAX_MESSAGES = 120    # borne le prompt de résumé
_MAX_CONTENT = 300     # tronque chaque message
_BURST_WINDOW_S = 300  # fenêtre d'un rassemblement communautaire
_BURST_AUTHORS = 3     # nb de personnes distinctes qui en fait un événement

# Mots-outils français exclus des « intérêts » : ils matcheraient n'importe quoi.
# Le seuil de 4 lettres laisse passer les vrais sujets courts (« apex », « chat »,
# « anime ») ; cette liste rattrape les mots-outils de cette taille-là.
_STOPWORDS = {
    "alors", "aussi", "autre", "avant", "avec", "avoir", "beaucoup", "bien",
    "cela", "cette", "chez", "chose", "comme", "comment", "dans", "depuis",
    "dire", "donc", "elle", "elles", "encore", "entre", "etre", "faire", "fait",
    "ils", "juste", "leur", "leurs", "mais", "meme", "moins", "nous", "parce",
    "pendant", "peut", "plus", "pour", "quand", "quelque", "quoi", "sans",
    "sont", "sous", "toujours", "tous", "tout", "toute", "tres", "trop", "vers",
    "voir", "vous", "vraiment", "wally",
}
_TOKEN_RE = re.compile(r"[^\W\d_]{4,}", re.UNICODE)


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _tokens(text: str) -> set[str]:
    """Mots signifiants d'un texte (≥ 4 lettres, sans accents, hors mots-outils)."""
    return {
        t for t in _TOKEN_RE.findall(_strip_accents(text or "").lower())
        if t not in _STOPWORDS
    }


def _dates_in_window(since: float, until: float) -> set[str]:
    """Noms de fichiers (YYYY-MM-DD, Europe/Paris) couvrant la fenêtre."""
    day = datetime.fromtimestamp(since, _PARIS).date()
    last = datetime.fromtimestamp(until, _PARIS).date()
    out: set[str] = set()
    while day <= last:
        out.add(day.isoformat())
        day += timedelta(days=1)
    return out


def read_messages(logs_root: str | Path, since: float, until: float) -> list[dict]:
    """Messages Discord perçus dans [since, until], lus depuis les logs JSONL.

    Bloquant (I/O disque) : appeler via `asyncio.to_thread`. Ne lève jamais —
    un fichier ou une ligne illisible est simplement ignoré.
    """
    root = Path(logs_root) / "discord"
    if not root.is_dir():
        return []
    wanted = _dates_in_window(since, until)
    messages: list[dict] = []
    for path in root.glob("*/*.jsonl"):
        if path.stem not in wanted or path.parent.name == _DM_SEGMENT:
            # Les MP ne sont pas la vie de la communauté : ils restent hors du
            # digest (et ne fuitent donc pas dans un contexte partagé).
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("type") != "message_in":
                        continue
                    ts = rec.get("ts")
                    if not isinstance(ts, (int, float)) or not since <= ts <= until:
                        continue
                    content = (rec.get("content") or "").strip()
                    if not content:
                        continue
                    messages.append({
                        "ts": float(ts),
                        "channel": path.parent.name,
                        "author": rec.get("author") or "?",
                        "author_id": str(rec.get("author_id") or ""),
                        "content": content,
                    })
        except OSError as e:
            logger.warning("WakeDigest: {} illisible: {}", path, e)
    messages.sort(key=lambda m: m["ts"])
    return messages


def last_engagement_ts(logs_root: str | Path) -> float | None:
    """Dernier moment où Wally a lui-même parlé (event `message_out`), d'après les
    logs du jour le plus récent. À défaut, le dernier événement journalisé quel
    qu'il soit. None si aucun log exploitable.

    Bloquant (I/O disque) : appeler via `asyncio.to_thread`.
    """
    root = Path(logs_root) / "discord"
    if not root.is_dir():
        return None
    files = list(root.glob("*/*.jsonl"))
    if not files:
        return None
    latest_date = max(f.stem for f in files)
    best_out: float | None = None
    best_any: float | None = None
    for path in files:
        if path.stem != latest_date:
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("ts")
                    if not isinstance(ts, (int, float)):
                        continue
                    if best_any is None or ts > best_any:
                        best_any = float(ts)
                    if rec.get("type") == "message_out" and (
                        best_out is None or ts > best_out
                    ):
                        best_out = float(ts)
        except OSError as e:
            logger.warning("WakeDigest: {} illisible: {}", path, e)
    return best_out if best_out is not None else best_any


def _community_event_indexes(messages: list[dict]) -> set[int]:
    """Indexes des messages qui relèvent d'un événement communautaire.

    Émergent : pas de lexique. Un message compte si la communauté s'y rassemble
    (≥ `_BURST_AUTHORS` personnes distinctes dans une fenêtre de `_BURST_WINDOW_S`
    sur le même canal) ou s'il diffuse une annonce à tous (@everyone / @here).
    """
    flagged: set[int] = set()
    by_channel: dict[str, list[int]] = {}
    for i, m in enumerate(messages):
        low = m["content"].lower()
        if "@everyone" in low or "@here" in low:
            flagged.add(i)
        by_channel.setdefault(m["channel"], []).append(i)
    for indexes in by_channel.values():
        start = 0
        for end in range(len(indexes)):
            while messages[indexes[end]]["ts"] - messages[indexes[start]]["ts"] > _BURST_WINDOW_S:
                start += 1
            window = indexes[start:end + 1]
            authors = {messages[i]["author"] for i in window}
            if len(authors) >= _BURST_AUTHORS:
                flagged.update(window)
    return flagged


def score_messages(
    messages: list[dict],
    *,
    bot_aliases: set[str],
    affinity_ids: set[str],
    interest_tokens: set[str],
) -> list[dict]:
    """Annote chaque message d'un `score` pondéré et des `tags` qui l'expliquent.

    Les poids se cumulent : un message d'un proche qui mentionne Wally sur un
    sujet qui l'intéresse pèse 24.
    """
    events = _community_event_indexes(messages)
    scored: list[dict] = []
    for i, m in enumerate(messages):
        low = _strip_accents(m["content"].lower())
        score = 0.0
        tags: list[str] = []
        if any(alias in low for alias in bot_aliases):
            score += WEIGHT_MENTION
            tags.append("mention")
        if m.get("author_id") and m["author_id"] in affinity_ids:
            score += WEIGHT_AFFINITY
            tags.append("proche")
        if interest_tokens and (_tokens(m["content"]) & interest_tokens):
            score += WEIGHT_INTEREST
            tags.append("intérêt")
        if i in events:
            score += WEIGHT_COMMUNITY_EVENT
            tags.append("événement")
        scored.append({**m, "score": score, "tags": tags})
    return scored


class WakeDigest:
    """Détecte les réveils et produit le résumé du sommeil (cf. docstring module)."""

    def __init__(
        self,
        llm,
        prompts_dir: str | Path,
        logs_root: str | Path = "logs/conversations",
        db=None,
        fact_store=None,
        min_sleep_seconds: float = MIN_SLEEP_SECONDS,
    ) -> None:
        self._llm = llm
        self._system = render_identity(
            (Path(prompts_dir) / "wake_digest.md").read_text(encoding="utf-8")
        )
        self._logs_root = Path(logs_root)
        self._db = db
        self._facts = fact_store
        self._min_sleep = min_sleep_seconds
        # Dernière fois que Wally a été sollicité (epoch). None tant que le boot
        # ne l'a pas déduit des logs.
        self._last_awake_ts: float | None = None
        # Début de la fenêtre de sommeil à résumer, quand un réveil est armé.
        self._pending_from: float | None = None

    # ── Détection du réveil ───────────────────────────────────────────────────

    async def bootstrap(self, now: float | None = None) -> None:
        """Au démarrage : déduit des logs quand Wally a parlé pour la dernière
        fois. Si ça remonte à plus que le seuil, arme un réveil. Ne lève jamais."""
        if self._last_awake_ts is not None:
            return
        now = now if now is not None else time.time()
        try:
            ts = await asyncio.to_thread(last_engagement_ts, self._logs_root)
        except Exception as e:  # noqa: BLE001 — jamais bloquant pour le démarrage
            logger.warning("WakeDigest: lecture des logs au boot échouée: {}", e)
            ts = None
        self._last_awake_ts = ts if ts is not None else now
        if ts is not None and now - ts >= self._min_sleep:
            self._pending_from = ts
            logger.info(
                "WakeDigest: réveil au démarrage après {:.1f} h d'absence",
                (now - ts) / 3600,
            )

    def note_engagement(self, now: float | None = None) -> None:
        """Quelqu'un sollicite Wally (mention, nom déclencheur, DM). Si le silence
        précédent dépasse le seuil, c'est un réveil : on arme la fenêtre de
        sommeil. Synchrone et non bloquant (aucune I/O, aucun LLM ici)."""
        now = now if now is not None else time.time()
        prev = self._last_awake_ts
        self._last_awake_ts = now
        if prev is None or now - prev < self._min_sleep:
            return
        # Un réveil déjà armé n'est pas écrasé : on garde la fenêtre la plus large.
        if self._pending_from is None:
            self._pending_from = prev
        logger.info(
            "WakeDigest: réveil après {:.1f} h sans sollicitation", (now - prev) / 3600
        )

    @property
    def pending(self) -> bool:
        """True si un réveil est armé et attend d'être résumé."""
        return self._pending_from is not None

    # ── Génération du digest ──────────────────────────────────────────────────

    async def consume(self, now: float | None = None) -> str | None:
        """Si un réveil est armé, produit le digest du sommeil (une seule fois).

        Renvoie None s'il n'y a pas de réveil, rien à raconter, ou en cas
        d'échec — jamais d'exception : le tick cognitif ne doit pas en dépendre.
        """
        start = self._pending_from
        if start is None:
            return None
        self._pending_from = None
        now = now if now is not None else time.time()
        since = max(start, now - MAX_LOOKBACK_SECONDS)
        try:
            return await self._generate(since, now)
        except Exception as e:  # noqa: BLE001 — jamais bloquant pour le tick
            logger.warning("WakeDigest: génération échouée: {}", e)
            return None

    async def _generate(self, since: float, until: float) -> str | None:
        messages = await asyncio.to_thread(
            read_messages, self._logs_root, since, until
        )
        if len(messages) < _MIN_MESSAGES:
            logger.info(
                "WakeDigest: sommeil silencieux ({} message(s)), pas de digest",
                len(messages),
            )
            return None

        affinity_ids = await self._affinity_ids(
            {m["author_id"] for m in messages if m["author_id"]}
        )
        interest_tokens = await self._interest_tokens()
        scored = score_messages(
            messages,
            bot_aliases=self._bot_aliases(),
            affinity_ids=affinity_ids,
            interest_tokens=interest_tokens,
        )
        # Sélection par score (à score égal, le plus récent gagne : une nuit sans
        # rien de saillant doit quand même livrer sa fin), restitution
        # chronologique — le résumé doit lire une conversation, pas un classement.
        kept = sorted(scored, key=lambda m: (-m["score"], -m["ts"]))[:_MAX_MESSAGES]
        kept.sort(key=lambda m: m["ts"])
        dropped = len(scored) - len(kept)

        reply = await self._llm.complete(
            self._system,
            [{"role": "user", "content": self._render(kept, since, until, dropped)}],
        )
        digest = (reply or "").strip()
        if not digest:
            logger.warning("WakeDigest: résumé vide, ignoré")
            return None
        await self._remember(digest)
        logger.info(
            "WakeDigest: digest de réveil produit ({} message(s) résumés sur {})",
            len(kept), len(scored),
        )
        return digest

    def _bot_aliases(self) -> set[str]:
        """Formes sous lesquelles une mention de Wally apparaît dans les logs :
        son nom nu et sa forme pingée (les `<@id>` y sont déjà résolus en
        « @pseudo » par `_resolve_mentions`)."""
        name = _strip_accents(bot_name().lower())
        return {name, f"@{name}"}

    async def _affinity_ids(self, author_ids: set[str]) -> set[str]:
        """IDs Discord bruts des personnes dont l'affinité (trust ou love)
        dépasse le seuil. Vide si la base n'est pas disponible."""
        if self._db is None or not author_ids:
            return set()
        pairs = [("discord", uid) for uid in author_ids]
        try:
            trust = await self._db.get_trust_scores_batch(pairs)
            love = await self._db.get_love_scores_batch(pairs)
        except Exception as e:  # noqa: BLE001 — l'affinité n'est qu'un poids
            logger.warning("WakeDigest: scores d'affinité indisponibles: {}", e)
            return set()
        return {
            uid for uid in author_ids
            if max(trust.get(("discord", uid), 0.0), love.get(("discord", uid), 0.0))
            >= AFFINITY_THRESHOLD
        }

    async def _interest_tokens(self) -> set[str]:
        """Vocabulaire de ce qui intéresse Wally, dérivé de sa mémoire vive :
        désirs et buts actifs + préoccupation courante. Vide si pas de mémoire."""
        if self._facts is None:
            return set()
        from bot.intelligence.memory.facts import FactCategory, FactStatus

        texts: list[str] = []
        try:
            for category in (FactCategory.DESIRE, FactCategory.GOAL):
                facts = await self._facts.search_by_category(
                    category, status=FactStatus.ACTIVE, limit=8
                )
                texts.extend(f.content for f in facts)
            focus = await self._facts.get_latest_by_source("wally:self", "focus")
            if focus:
                texts.append(focus.content)
        except Exception as e:  # noqa: BLE001 — l'intérêt n'est qu'un poids
            logger.warning("WakeDigest: intérêts indisponibles: {}", e)
            return set()
        tokens: set[str] = set()
        for text in texts:
            tokens |= _tokens(text)
        return tokens

    def _render(
        self, messages: list[dict], since: float, until: float, dropped: int
    ) -> str:
        hours = (until - since) / 3600
        start = datetime.fromtimestamp(since, _PARIS).strftime("%d/%m %Hh%M")
        end = datetime.fromtimestamp(until, _PARIS).strftime("%d/%m %Hh%M")
        header = [
            f"Tu as décroché pendant {hours:.1f} h (de {start} à {end}).",
            "Voici ce qui s'est dit sur Discord pendant ce temps. Les crochets en "
            "fin de ligne signalent pourquoi le message ressort : mention = on te "
            "nommait, proche = quelqu'un dont tu es proche, intérêt = un sujet qui "
            "te tient, événement = un moment où la communauté s'est rassemblée.",
        ]
        if dropped > 0:
            header.append(
                f"({dropped} message(s) de moindre importance ont été écartés.)"
            )
        lines = []
        for m in messages:
            hhmm = datetime.fromtimestamp(m["ts"], _PARIS).strftime("%Hh%M")
            tags = f"  [{', '.join(m['tags'])}]" if m["tags"] else ""
            content = m["content"][:_MAX_CONTENT]
            lines.append(f"{hhmm} [#{m['channel']}] {m['author']}: {content}{tags}")
        return "\n".join(header) + "\n\n" + "\n".join(lines)

    async def _remember(self, digest: str) -> None:
        """Archive le digest comme une pensée : il reste consultable (admin
        mémoire) et retrouvable après coup, même si le tick l'a déjà consommé."""
        if self._facts is None:
            return
        try:
            from bot.intelligence.memory.facts import AtomicFact, FactCategory
            now = datetime.utcnow()
            await self._facts.add(AtomicFact(
                user_id="wally:self",
                content=digest,
                category=FactCategory.THOUGHT,
                source="wake_digest",
                importance=0.6,
                created_at=now,
                last_seen_at=now,
            ))
        except Exception as e:  # noqa: BLE001 — le digest vaut même non archivé
            logger.warning("WakeDigest: archivage du digest échoué: {}", e)
