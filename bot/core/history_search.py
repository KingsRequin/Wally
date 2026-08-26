# bot/core/history_search.py
"""Recherche plein texte dans l'historique des conversations Discord.

Wally perçoit passivement tous les salons publics, mais son contexte ne porte
que les dernières interactions : dès qu'un membre fait référence à un événement
d'il y a trois semaines, il est aveugle. Ce module lui rend cet historique
consultable — « retrouve tous les messages qui parlent de "bachelier" ces six
derniers mois » — sans dépendre de la présence de qui que ce soit.

**Source** : les logs JSONL de conversation
(``logs/conversations/discord/{canal}/{YYYY-MM-DD}.jsonl``, cf.
:mod:`bot.core.conversation_log`). Ce sont les seuls à contenir TOUTE la
perception passive — ``daily_log`` (SQLite) ne garde que les échanges auxquels
Wally a lui-même participé. Aucun index n'est construit : l'arborescence est
déjà partitionnée par canal et par jour (Europe/Paris), donc les filtres
« salon » et « plage de dates » se résolvent en sélection de fichiers, et le
volume restant se scanne en quelques dizaines de millisecondes hors event loop.

**Périmètre** : Discord uniquement, et jamais les MP — tous les messages privés
partagent le dossier ``dm`` (cf. ``_conv_channel``), les fouiller reviendrait à
laisser n'importe qui exhumer la conversation privée d'un autre.

Les messages de Wally (``message_out``) sont inclus au même titre que ceux des
membres : son historique est aussi le sien, et le total renvoyé lui donne un
ordre de grandeur (combien de fois ce sujet est-il revenu ?).
"""
from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from loguru import logger

from bot.core.temps import PARIS

_PARIS = PARIS
# Segment de chemin des logs de MP — exclu de toute recherche (cf. docstring).
_DM_SEGMENT = "dm"
# Événements porteurs de texte conversationnel ; le reste du journal (décisions
# de gate, appels LLM, émotions…) est du diagnostic, pas de la conversation.
_SEARCHABLE_TYPES = frozenset({"message_in", "message_out"})

DEFAULT_LIMIT = 15
MAX_LIMIT = 50
# Un terme d'une seule lettre matche tout : on l'ignore plutôt que de noyer.
_MIN_TERM_LEN = 2
_MAX_CONTENT = 400  # troncature d'affichage par message

_TERM_RE = re.compile(r"[^\W_]+", re.UNICODE)

HISTORY_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_history",
        "description": (
            "Cherche des mots-clés dans l'historique complet des conversations Discord "
            "(tous les salons que tu perçois, tes propres messages inclus). "
            "UTILISE-LE quand quelqu'un fait référence à un moment passé que tu ne "
            "retrouves pas dans le contexte sous tes yeux : 'tu te souviens quand…', "
            "'comme l'autre fois avec X', une blague interne, un événement, une promesse. "
            "Utilise-le aussi pour vérifier qui a dit quoi, ou depuis quand un sujet revient, "
            "plutôt que d'inventer ou de dire que tu ne sais plus. "
            "Ne cherche PAS ce qui est déjà dans ton contexte immédiat, et ne l'utilise pas "
            "pour des faits généraux (c'est web_search qu'il te faut). "
            "Les messages privés ne sont jamais fouillés."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Mots-clés à retrouver dans le texte des messages. Tous doivent "
                        "être présents. Reste large : 2-3 mots significatifs, pas une phrase."
                    ),
                },
                "author": {
                    "type": "string",
                    "description": "Optionnel : pseudo (même partiel) de l'auteur des messages.",
                },
                "channel": {
                    "type": "string",
                    "description": "Optionnel : nom (même partiel) du salon où chercher.",
                },
                "after": {
                    "type": "string",
                    "description": "Optionnel : ne rien renvoyer avant cette date (AAAA-MM-JJ).",
                },
                "before": {
                    "type": "string",
                    "description": "Optionnel : ne rien renvoyer après cette date (AAAA-MM-JJ).",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        f"Optionnel : nombre de messages à renvoyer "
                        f"(défaut {DEFAULT_LIMIT}, max {MAX_LIMIT}). Les plus récents gagnent."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


class HistorySearchError(ValueError):
    """Filtre invalide fourni par l'appelant (message destiné au LLM)."""


def _normalize(text: str) -> str:
    """Minuscules sans accents — la recherche ignore la casse et les diacritiques."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def extract_terms(query: str) -> list[str]:
    """Termes significatifs d'une requête (normalisés, ≥ `_MIN_TERM_LEN` caractères)."""
    return [t for t in _TERM_RE.findall(_normalize(query)) if len(t) >= _MIN_TERM_LEN]


def _term_patterns(terms: list[str]) -> list[re.Pattern]:
    """Un motif par terme, ancré en début de mot.

    L'ancrage à gauche seulement fait que « bachelier » retrouve « bacheliers »
    ou « bachelières » sans exiger du LLM qu'il devine la forme exacte, tout en
    évitant les faux positifs en milieu de mot (« art » ≠ « départ »).
    """
    return [re.compile(r"(?<![^\W_])" + re.escape(t)) for t in terms]


def _parse_date(value: str, field: str) -> date:
    """Date AAAA-MM-JJ. Lève `HistorySearchError` si la forme est invalide."""
    try:
        return date.fromisoformat(value.strip())
    except (AttributeError, ValueError):
        raise HistorySearchError(
            f"Date invalide pour « {field} » : « {value} ». Format attendu : AAAA-MM-JJ."
        ) from None


@dataclass(frozen=True)
class HistoryHit:
    """Un message de l'historique qui satisfait la requête."""

    ts: float
    channel: str
    author: str
    author_id: str
    content: str

    def render(self) -> str:
        when = datetime.fromtimestamp(self.ts, _PARIS).strftime("%d/%m/%Y %Hh%M")
        content = self.content[:_MAX_CONTENT]
        if len(self.content) > _MAX_CONTENT:
            content += "…"
        return f"[{when}] #{self.channel} — {self.author}: {content}"


def search_logs(
    logs_root: str | Path,
    terms: list[str],
    *,
    author: str | None = None,
    channel: str | None = None,
    after: date | None = None,
    before: date | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[HistoryHit], int]:
    """Scanne les logs Discord et renvoie ``(les `limit` plus récents, total trouvé)``.

    Bloquant (I/O disque) : appeler via `asyncio.to_thread`. Ne lève jamais sur
    une donnée illisible — un fichier ou une ligne corrompue est simplement
    ignoré, une recherche partielle valant mieux qu'une erreur.
    """
    root = Path(logs_root) / "discord"
    if not root.is_dir():
        logger.warning("HistorySearch: {} introuvable", root)
        return [], 0

    patterns = _term_patterns(terms)
    author_needle = _normalize(author) if author else None
    channel_needle = _normalize(channel).replace("_", " ") if channel else None
    hits: list[HistoryHit] = []

    for path in root.glob("*/*.jsonl"):
        dir_name = path.parent.name
        if dir_name == _DM_SEGMENT:
            continue
        if channel_needle and channel_needle not in _normalize(dir_name).replace("_", " "):
            continue
        # Les fichiers sont bucketés par jour Europe/Paris (cf. ConversationLogger)
        # : filtrer sur le nom du fichier est exact, et évite d'ouvrir l'immense
        # majorité des jours hors plage.
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if (after and day < after) or (before and day > before):
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
                    if rec.get("type") not in _SEARCHABLE_TYPES:
                        continue
                    ts = rec.get("ts")
                    content = (rec.get("content") or "").strip()
                    if not isinstance(ts, (int, float)) or not content:
                        continue
                    rec_author = str(rec.get("author") or "?")
                    rec_author_id = str(rec.get("author_id") or "")
                    if author_needle and (
                        author_needle not in _normalize(rec_author)
                        and author_needle != rec_author_id
                    ):
                        continue
                    haystack = _normalize(content)
                    if not all(p.search(haystack) for p in patterns):
                        continue
                    hits.append(HistoryHit(
                        ts=float(ts),
                        channel=dir_name,
                        author=rec_author,
                        author_id=rec_author_id,
                        content=content,
                    ))
        except OSError as e:
            logger.warning("HistorySearch: {} illisible: {!r}", path, e)

    total = len(hits)
    hits.sort(key=lambda h: h.ts)
    # Les plus récents sont les plus pertinents, mais on les rend dans l'ordre
    # chronologique : une suite de messages doit se lire comme une conversation.
    return hits[-limit:], total


class HistorySearchService:
    """Recherche plein texte dans l'historique Discord, exposée comme outil LLM."""

    def __init__(self, logs_root: str | Path = "logs/conversations") -> None:
        self._logs_root = Path(logs_root)

    @property
    def available(self) -> bool:
        """False tant qu'aucun log Discord n'a été écrit (rien à fouiller)."""
        return (self._logs_root / "discord").is_dir()

    def get_tool_definitions(self) -> list[dict]:
        return [HISTORY_SEARCH_TOOL]

    async def search(
        self,
        query: str,
        *,
        author: str | None = None,
        channel: str | None = None,
        after: str | None = None,
        before: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> str:
        """Exécute la recherche et renvoie un résultat prêt à lire par le LLM.

        Ne lève jamais : toute erreur devient un message explicatif que le
        modèle peut exploiter pour corriger sa requête.
        """
        terms = extract_terms(query)
        if not terms:
            return (
                "Recherche impossible : donne au moins un mot-clé de "
                f"{_MIN_TERM_LEN} caractères ou plus."
            )
        try:
            after_date = _parse_date(after, "after") if after else None
            before_date = _parse_date(before, "before") if before else None
        except HistorySearchError as e:
            return str(e)
        if after_date and before_date and after_date > before_date:
            return "Plage de dates invalide : « after » est postérieur à « before »."

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
        limit = max(1, min(limit, MAX_LIMIT))

        try:
            hits, total = await asyncio.to_thread(
                search_logs,
                self._logs_root, terms,
                author=author or None, channel=channel or None,
                after=after_date, before=before_date, limit=limit,
            )
        except Exception as e:  # noqa: BLE001 — un outil ne fait jamais tomber la réponse
            logger.warning("HistorySearch: recherche « {} » échouée: {!r}", query, e)
            return "La recherche dans l'historique a échoué."

        filters = self._describe_filters(author, channel, after, before)
        logger.info(
            "HistorySearch: « {q} »{f} → {n} résultat(s)",
            q=query, f=f" ({filters})" if filters else "", n=total,
        )
        if not hits:
            return (
                f"Aucun message trouvé pour « {query} »"
                + (f" ({filters})" if filters else "")
                + ". Élargis les mots-clés ou retire un filtre."
            )

        header = f"{total} message(s) trouvé(s) pour « {query} »"
        if filters:
            header += f" ({filters})"
        if total > len(hits):
            header += f" — voici les {len(hits)} plus récents"
        return header + " :\n" + "\n".join(h.render() for h in hits)

    @staticmethod
    def _describe_filters(
        author: str | None, channel: str | None, after: str | None, before: str | None
    ) -> str:
        parts = []
        if author:
            parts.append(f"auteur: {author}")
        if channel:
            parts.append(f"salon: {channel}")
        if after:
            parts.append(f"depuis le {after}")
        if before:
            parts.append(f"jusqu'au {before}")
        return ", ".join(parts)
