# bot/discord/message_split.py
"""Découpage propre des longs messages Discord.

Discord refuse tout message > 2000 caractères (HTTP 400). Quand Wally envoie un
rapport ou un long texte (typiquement un MP au créateur), il faut le scinder en
plusieurs messages — mais jamais en plein milieu d'un mot ou d'une phrase.

`split_for_discord()` coupe sur la meilleure frontière disponible dans la
fenêtre autorisée, par ordre de préférence : fin de paragraphe / saut de ligne,
puis fin de phrase (``. ! ? …``), puis frontière de mot (espace). La coupe brute
au caractère n'arrive qu'en dernier recours (mot unique plus long que la limite).
"""

from __future__ import annotations

import re

# Limite dure d'un message Discord.
DISCORD_MAX_LEN = 2000

# Fin de phrase : ponctuation terminale, éventuels guillemets/parenthèses
# fermants, puis une espace. On capture jusqu'à la ponctuation incluse.
_SENTENCE_END = re.compile(r"[.!?…][\"')\]]*\s")


def _find_cut(window: str) -> int:
    """Indice de coupure dans `window` : tout ce qui précède part dans le
    morceau courant, tout ce qui suit est reporté. Toujours ``>= 1`` pour
    garantir la progression."""
    best = -1

    # Frontière la plus propre : saut de ligne (paragraphe ou fin de ligne).
    nl = window.rfind("\n")
    if nl != -1:
        best = max(best, nl + 1)

    # Fin de phrase la plus tardive dans la fenêtre.
    last_sentence = None
    for m in _SENTENCE_END.finditer(window):
        last_sentence = m
    if last_sentence is not None:
        best = max(best, last_sentence.end())

    if best > 0:
        return best

    # Aucune frontière de phrase/ligne : on coupe au dernier espace (mot entier).
    sp = window.rfind(" ")
    if sp > 0:
        return sp + 1

    # Mot unique plus long que la limite : coupe brute, en tout dernier recours.
    return len(window)


def split_for_discord(text: str, limit: int = DISCORD_MAX_LEN) -> list[str]:
    """Découpe `text` en morceaux de `limit` caractères max, sur des frontières
    propres. Retourne ``[]`` pour un texte vide, ``[text]`` s'il tient déjà."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while len(text) > limit:
        cut = _find_cut(text[:limit])
        head, text = text[:cut].rstrip(), text[cut:].lstrip()
        if head:
            chunks.append(head)
    if text:
        chunks.append(text)
    return chunks


async def send_chunked(sendable, text: str, *, limit: int = DISCORD_MAX_LEN):
    """Envoie `text` via `sendable.send()`, découpé si nécessaire. Les morceaux
    partent dans l'ordre, sans délai entre eux. Retourne le premier message
    envoyé (ou ``None`` si rien à envoyer)."""
    parts = split_for_discord(text, limit)
    first = None
    for part in parts:
        sent = await sendable.send(part)
        if first is None:
            first = sent
    return first
