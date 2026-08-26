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


# ── Liens markdown : justes sur Discord, illisibles sur Twitch ───────────────
#
# La convention de citation façon Perplexity — « colle son marqueur cliquable
# juste après la phrase, ex. [¹](<url>), garde les chevrons » — vient de
# `WebSearchService` et du recall RSS. Elle est juste sur Discord, qui rend le
# markdown et masque l'aperçu grâce aux chevrons.
#
# Le chat Twitch est du TEXTE BRUT. Le viewer y lit
# `[²](<https://steamstore-a.akamaihd.net/…>)` en toutes lettres, au milieu
# d'une phrase déjà tronquée à 480 caractères. Constaté par l'owner le
# 2026-08-26 sur les patch notes Apex.
#
# Le libellé est GARDÉ, l'URL jetée : dans « [le patch note](https://…) »,
# l'information est dans le libellé et tout jeter effacerait le sujet de la
# phrase. Un marqueur de citation, lui, n'est qu'un exposant : il part en
# entier, avec l'espace qui le précède.
_LIEN_MD = re.compile(r"[ \t]*\[([^\]\n]*)\]\(\s*<?\s*(?:https?|ftp)://[^\s)]*\s*>?\s*\)")
# Les exposants Unicode que le projet emploie comme marqueurs (`⁰`…`⁹`).
_EXPOSANTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"


def retirer_liens_markdown(text: str | None) -> str:
    """Rend `text` sans syntaxe de lien markdown, pour un chat en texte brut.

    Une URL NUE est laissée intacte : c'est le seul lien qui marche sur Twitch,
    et Wally y publie le planning comme ça. Seule la forme `[texte](url)` est
    visée — des crochets sans lien derrière (grille de pendu, tableau de score)
    ne sont pas touchés.
    """
    if not text:
        return ""

    def _remplacer(m: "re.Match[str]") -> str:
        libelle = m.group(1).strip()
        # Un marqueur de citation ne porte aucune information : il disparaît
        # avec l'espace qui le précédait, sinon la phrase garde un blanc double.
        if not libelle or all(c in _EXPOSANTS for c in libelle):
            return ""
        return f"{m.group(0)[: len(m.group(0)) - len(m.group(0).lstrip())]}{libelle}"

    return _LIEN_MD.sub(_remplacer, text)
