# bot/core/steam_news.py
"""Les annonces d'un jeu Steam — pour Apex, les patch notes de Respawn.

Source officielle, là où Dexerto paraphrasait : c'est Respawn qui écrit. Deux
difficultés à traiter avant de pouvoir chercher dedans.

1. Le contenu arrive en **BBCode** Steam (`[p]`, `[img]`, `[url]`).
2. Un patch note de saison fait **39 000 caractères** — cinq fois ce qu'on peut
   injecter. On le découpe donc par SECTIONS, sur ses propres titres : une
   question sur World's Edge doit rendre le passage sur World's Edge, pas le
   huitième arbitraire du document qui le contient.

L'endpoint marche pour n'importe quel jeu, seul l'`appid` change.
"""
from __future__ import annotations

import re
from typing import Any

NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"

# Au-delà, une section n'est plus injectable telle quelle : on la recoupe.
MAX_SECTION_CHARS = 1500

# Les titres de section du BBCode Steam : [h1] à [h6].
_HEADING_RE = re.compile(r"\[h[1-6]\](.*?)\[/h[1-6]\]", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"\[/?[a-z][^\]]*\]", re.IGNORECASE)


def strip_bbcode(text: str) -> str:
    """Le texte sans balises, ni URL d'image, ni espaces en trop."""
    if not text:
        return ""
    # Les images ne laissent aucun texte utile : on retire la balise ET son URL.
    text = re.sub(r"\[img[^\]]*\][^\[]*\[/img\]", " ", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&").replace("&nbsp;", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def _chunks(text: str, size: int) -> list[str]:
    """Découpe un texte trop long, en coupant sur une fin de phrase si possible."""
    out: list[str] = []
    while len(text) > size:
        coupe = text.rfind(". ", 0, size)
        if coupe < size // 2:
            coupe = text.rfind(" ", 0, size)
        if coupe <= 0:
            coupe = size
        out.append(text[:coupe].strip())
        text = text[coupe:].strip()
    if text:
        out.append(text)
    return out


def sections_from_item(item: dict[str, Any]) -> list[dict]:
    """Un article Steam → une liste de sections indexables.

    Chaque section porte le titre du patch note ET le sien : « World's Edge »
    tout seul ne dit pas de quelle mise à jour il s'agit.
    """
    contents = str(item.get("contents") or "")
    if not contents.strip():
        return []
    gid = str(item.get("gid") or "")
    titre_article = str(item.get("title") or "").strip()
    author = str(item.get("author") or "")
    link = str(item.get("url") or "")

    # Découpe sur les titres, en gardant le texte qui les suit.
    positions = [(m.start(), m.end(), strip_bbcode(m.group(1))) for m in _HEADING_RE.finditer(contents)]
    blocs: list[tuple[str, str]] = []
    if not positions:
        blocs = [("", strip_bbcode(contents))]
    else:
        avant = strip_bbcode(contents[: positions[0][0]])
        if avant:
            blocs.append(("", avant))
        for i, (_, fin, titre) in enumerate(positions):
            suite = positions[i + 1][0] if i + 1 < len(positions) else len(contents)
            blocs.append((titre, strip_bbcode(contents[fin:suite])))

    sections: list[dict] = []
    for titre, corps in blocs:
        if not corps:
            continue
        for n, morceau in enumerate(_chunks(corps, MAX_SECTION_CHARS)):
            suffixe = f" — {titre}" if titre else ""
            if n:
                suffixe += f" ({n + 1})"
            sections.append({
                "guid": f"{gid}#{len(sections)}",
                "title": f"{titre_article}{suffixe}"[:200],
                "text": morceau,
                "author": author,
                "link": link,
                "published_ts": float(item.get("date") or 0) or None,
            })
    return sections
