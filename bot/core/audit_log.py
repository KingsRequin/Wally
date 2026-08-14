# bot/core/audit_log.py
"""Écriture *best-effort* dans le journal de conversation, et signal de réception.

Ce module n'invente pas un second format : tout part dans le
``ConversationLogger`` existant (``logs/conversations/{plateforme}/{canal}/
{date}.jsonl``), avec les mêmes conventions — un ``trace_id`` par cycle de vie,
un événement par ligne.

Il n'apporte que deux choses, celles qui manquaient partout :

1. **Un journal ne casse jamais ce qu'il observe.** `journal()` avale tout :
   logger absent, champ non sérialisable, file saturée. L'appelant ne voit
   jamais d'exception, et n'a pas à écrire son propre `try/except`.
2. **Le masquage des secrets est appliqué à l'écriture**, pas laissé à la
   discipline de chaque appelant. Le mot d'un pendu en cours passe par les
   journaux comme il passe par les bulles (`bot/core/secret_guard.py`).

`ReceptionTracker` répond à une autre question : « quelqu'un a-t-il réagi ? ».
Rien ne reliait « Wally a parlé » à « le chat a bougé » — donc rien ne
distinguait un bot vivant d'un meuble. Le signal est volontairement grossier :
on compte ce qui arrive dans la minute qui suit, sans prétendre que c'est une
réponse.
"""
from __future__ import annotations

import time
from typing import Optional

from loguru import logger

from bot.core.secret_guard import redact
from bot.core.self_trace import note_journal_act

# Plafond par champ texte. Le ConversationLogger coupe déjà à 8000 caractères,
# mais ces journaux-ci tournent en boucle chaude : une transcription ou un
# résultat d'outil n'a pas besoin de plus pour être relu.
MAX_TEXT = 600

# Profondeur maximale explorée dans les structures imbriquées. Au-delà, la
# valeur passe telle quelle : un journal ne doit pas devenir un sérialiseur.
_MAX_DEPTH = 3


def _clean(value, depth: int = 0):
    """Masque les secrets et borne les textes, en profondeur."""
    if isinstance(value, str):
        out = redact(value)
        return out if len(out) <= MAX_TEXT else out[:MAX_TEXT] + "…"
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {k: _clean(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v, depth + 1) for v in value]
    return value


def conv_log_of(*sources):
    """Le premier ``conv_log`` porté par l'un des objets donnés, ou None.

    Les services ne se connaissent pas tous : le narrateur d'overlay voit le
    bot Discord, le vocal voit les deux. Chercher dans l'ordre évite de câbler
    une dépendance de plus juste pour journaliser.
    """
    for source in sources:
        if source is None:
            continue
        clog = getattr(source, "conv_log", None)
        if clog is not None:
            return clog
    return None


def journal(conv_log, platform: str, channel: str, event_type: str, /, **fields) -> bool:
    """Écrit un événement. **Ne lève jamais**, quoi qu'il arrive.

    Renvoie True si l'événement a été remis au logger — utile aux tests, jamais
    à une décision métier : un appelant ne doit pas se comporter différemment
    selon qu'il a été journalisé ou non.
    """
    # La trace de soi vient AVANT l'écriture, et sans dépendre d'elle : un
    # `conv_log` absent (vocal hors bot, tests) ne doit pas rendre Wally aveugle
    # à ce qu'il vient de faire. Elle ne lève jamais.
    note_journal_act(platform, channel, event_type, fields)
    if conv_log is None:
        return False
    try:
        conv_log.log(platform, channel, event_type, **_clean(fields))
        return True
    except Exception as exc:  # noqa: BLE001 — un journal ne casse pas son sujet
        logger.debug("journal {t} non écrit : {e}", t=event_type, e=exc)
        return False


class ReceptionTracker:
    """Ce qui suit une prise de parole de Wally, dans la minute.

    Volontairement grossier : on ne cherche pas à savoir si le message répond à
    Wally, seulement si le canal a bougé après qu'il a parlé. Un compteur à zéro
    sur toute une soirée dit déjà l'essentiel.

    L'état vit en mémoire et n'est jamais persisté : une fiche perdue au
    redémarrage n'est pas un problème, c'est un signal statistique.
    """

    def __init__(self, window_s: float = 60.0, max_pending: int = 300) -> None:
        self._window = window_s
        self._max_pending = max_pending
        self._pending: list[dict] = []

    def spoke(self, platform: str, channel: str, trace_id: str,
              now: Optional[float] = None) -> None:
        """Wally vient de parler : ouvre une fenêtre d'écoute."""
        now = time.time() if now is None else now
        self._pending.append({
            "platform": platform, "channel": channel, "trace_id": trace_id,
            "ts": now, "replies": 0, "authors": [], "first_delay_s": None,
            "first_reply": "",
        })
        # Un canal muet laisserait sinon grossir la liste sans fin : les plus
        # vieilles fiches sont de toute façon les premières à échoir.
        if len(self._pending) > self._max_pending:
            del self._pending[: len(self._pending) - self._max_pending]

    def heard(self, platform: str, channel: str, author: str, content: str,
              now: Optional[float] = None) -> None:
        """Quelqu'un a parlé : crédite les fenêtres ouvertes de ce canal."""
        now = time.time() if now is None else now
        for entry in self._pending:
            if entry["platform"] != platform or entry["channel"] != channel:
                continue
            delay = now - entry["ts"]
            if delay < 0 or delay > self._window:
                continue
            entry["replies"] += 1
            if entry["first_delay_s"] is None:
                entry["first_delay_s"] = round(delay, 2)
                entry["first_reply"] = (content or "")[:200]
            if author and author not in entry["authors"] and len(entry["authors"]) < 5:
                entry["authors"].append(author)

    def due(self, now: Optional[float] = None) -> list[tuple[str, str, dict]]:
        """Fiches dont la fenêtre est close : ``(plateforme, canal, champs)``.

        Les retire de l'attente — une fiche n'est rendue qu'une fois.
        """
        now = time.time() if now is None else now
        mures, restantes = [], []
        for entry in self._pending:
            if now - entry["ts"] >= self._window:
                mures.append(entry)
            else:
                restantes.append(entry)
        self._pending = restantes
        return [
            (e["platform"], e["channel"], {
                "trace_id": e["trace_id"], "replies": e["replies"],
                "authors": e["authors"], "first_delay_s": e["first_delay_s"],
                "first_reply": e["first_reply"], "window_s": self._window,
            })
            for e in mures
        ]


# Instance de processus. Le suivi est purement statistique et sans état durable :
# le faire porter par chaque adaptateur obligerait à le câbler dans six
# constructeurs pour la même information.
_RECEPTION = ReceptionTracker()


def reset_reception() -> None:
    """Vide le suivi (tests)."""
    _RECEPTION._pending.clear()


def _flush_reception(conv_log) -> None:
    for plat, chan, payload in _RECEPTION.due():
        journal(conv_log, plat, chan, "reception", **payload)


def note_speech(conv_log, platform: str, channel: str, trace_id: str) -> None:
    """Wally vient de parler ici : ouvre la fenêtre d'écoute. Ne lève jamais."""
    try:
        if trace_id:
            _RECEPTION.spoke(platform, channel, str(trace_id))
        _flush_reception(conv_log)
    except Exception as exc:  # noqa: BLE001 — un journal ne casse pas son sujet
        logger.debug("signal de réception non ouvert : {e}", e=exc)


def note_audience(conv_log, platform: str, channel: str, author: str,
                  content: str) -> None:
    """Quelqu'un a parlé ici : crédite les fenêtres ouvertes. Ne lève jamais."""
    try:
        _RECEPTION.heard(platform, channel, str(author or ""), str(content or ""))
        _flush_reception(conv_log)
    except Exception as exc:  # noqa: BLE001 — un journal ne casse pas son sujet
        logger.debug("signal de réception non crédité : {e}", e=exc)


def observe_event(conv_log, platform: str, channel: str, event_type: str,
                  fields: dict) -> None:
    """Branche les observateurs EN MÉMOIRE sur un flux d'événements journalisés.

    Appelé depuis les `_clog` des adaptateurs : ils voient déjà passer tous les
    événements de leur canal, et c'est le seul endroit qui les voie tous. Un
    point d'entrée UNIQUE, et pas un par observateur : c'est ce qui fait qu'un
    adaptateur ajouté demain hérite du signal de réception ET de la trace de
    soi sans qu'on ait à y penser. Ne lève jamais.
    """
    note_journal_act(platform, channel, event_type, fields)
    if event_type == "message_out":
        note_speech(conv_log, platform, channel, str(fields.get("trace_id") or ""))
    elif event_type == "message_in":
        note_audience(conv_log, platform, channel,
                      str(fields.get("author") or ""), str(fields.get("content") or ""))
