"""Nettoyage du texte sortant — ce que Wally écrit vraiment dans un chat.

La consigne « pas de didascalies » existe depuis longtemps dans VOICE.md, et
elle vise les astérisques. Le modèle est passé par les parenthèses :

    (Je lance un coup d'œil au message, un sourcil levé par la curiosité)
    Oh ? Un coup de main pour quoi au juste ?

D'où ce filtre : une consigne se contourne, un mécanisme non.
"""
from __future__ import annotations

import re

# Une didascalie occupe TOUTE une ligne, ou ouvre le message. Une incise
# légitime — « ouais enfin (si on veut) » — vit au milieu d'une phrase et n'est
# donc jamais touchée.
_WHOLE_LINE = re.compile(r"(?m)^[ \t]*(?:\((?P<p>[^()]{6,})\)|\*(?P<a>[^*]{6,})\*)[ \t]*$")
_LEADING = re.compile(r"^[ \t]*(?:\([^()]{6,}\)|\*[^*]{6,}\*)[ \t]*")


def strip_stage_directions(text: str) -> str:
    """Retire les didascalies de roleplay d'un texte destiné à un chat.

    Ne touche ni aux incises en milieu de phrase, ni aux parenthèses courtes
    (« (si) », « (bref) ») : trop brèves pour être une mise en scène.
    """
    if not text:
        return text
    cleaned = _WHOLE_LINE.sub("", text)
    # Une didascalie peut aussi précéder la réplique sur la même ligne.
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _LEADING.sub("", cleaned)
    # Les lignes vides laissées derrière feraient un blanc en tête de message.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    # Tout retirer voudrait dire que le message n'était QUE de la mise en scène :
    # mieux vaut le laisser passer que d'envoyer du vide.
    return cleaned or text.strip()
