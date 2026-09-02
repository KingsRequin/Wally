# bot/twitch/commands/clip.py
"""`!clip`, `!clip 50`, `!clip 1m` — clipper sans passer par le modèle.

Demandé par l'owner le 2026-09-01, en plus de l'outil `create_clip` : une
commande de chat coûte zéro appel LLM, part en moins d'une seconde et se tape
d'une main pendant une partie. Le chemin outillé reste, pour « wally garde ce
moment » ; celui-ci est pour le viewer qui sait déjà quoi taper.

Deux choses lui sont communes avec l'outil, et c'est volontaire :

  · **le même `creer_clip()`** — donc le MÊME cooldown de chaîne. Deux
    compteurs séparés le doubleraient, soit exactement les deux clips du même
    moment que ce cooldown existe pour éviter.
  · **ouverte à tout le monde**, comme l'outil (arbitrage du 2026-09-01) : le
    chat repère des moments que le streamer ne voit pas.

En revanche elle n'écrit PAS les `message` rendus par `creer_clip()` : ils sont
rédigés pour le modèle (« dis-le », « n'invente aucune URL ») et n'ont aucun
sens recopiés tels quels dans le chat.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from bot.tools.clip_tool import creer_clip

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# `50`, `50s`, `1m`, `2 min`… La durée est ce que Twitch appelle « remonter
# dans le direct » : elle est bornée à 60 s côté API, pas ici — une demande de
# deux minutes est LÉGITIME et reçoit ce que Twitch sait faire, avec la
# précision dans la réponse.
_DUREE = re.compile(
    r"^(\d{1,3})\s*(s|sec|secs|secondes?|m|min|mins|minutes?)?\b\s*", re.I)


def parse_args(args: str) -> tuple[int, str]:
    """(durée en secondes, titre) — `0` quand aucune durée n'est donnée.

    La durée est lue en TÊTE et nulle part ailleurs : `!clip 30 kill au
    wingman` donne (30, « kill au wingman »), `!clip kill au wingman` donne
    (0, le titre entier). Ancrer la lecture au début est ce qui empêche un
    titre comme « 2 kills en 1 seconde » de se faire piller sa durée au milieu
    de la phrase — seul le « 2 » compte, le « 1 seconde » reste du texte.
    """
    texte = " ".join((args or "").split())
    if m := _DUREE.match(texte):
        facteur = 60 if (m.group(2) or "s").lower().startswith("m") else 1
        return int(m.group(1)) * facteur, texte[m.end():].strip()
    return 0, texte


def _phrase(rendu: dict, duree: int) -> str:
    """Ce qui part dans le chat, écrit ICI et jamais recopié du rendu."""
    statut = rendu.get("status")
    if statut == "ok":
        url = rendu.get("url") or ""
        if reelle := rendu.get("duree_reelle_s"):
            return (f"✂️ {url} — Twitch ne sait pas remonter plus loin que "
                    f"{reelle} s, donc {reelle} et pas {duree}.")
        return f"✂️ {url}"
    if statut == "cooldown":
        return (f"Un clip vient d'être pris, le suivant montrerait le même "
                f"moment. Encore {rendu.get('reste_s', 0)} s.")
    if statut == "failed":
        return ("Ça n'a pas pris : soit le live ne tourne pas, soit Twitch n'a "
                "pas fini de fabriquer le clip.")
    return "Je ne peux pas clipper là, l'API Twitch ne répond pas."


async def handle_clip_command(bot: "WallyTwitch", author: str, args: str) -> None:
    """Crée le clip demandé et répond dans le chat. Chaîne MAISON seulement.

    Pas de `channel_name` à recevoir : le dispatch a déjà tenu la garde maison,
    comme pour `!image` et `!code`, et la réponse part sur la chaîne d'Azraël —
    la seule où le scope `clips:edit` du token streamer vaut.
    """
    duree, titre = parse_args(args)
    rendu = await creer_clip(bot, titre=titre, duree=duree, author=author)
    texte = _phrase(rendu, duree)

    api = getattr(bot, "twitch_api", None)
    if api is None:
        logger.warning("!clip : rien à répondre à {a}, pas d'API Twitch", a=author)
        return
    # Message ordinaire et non annonce : c'est la réponse à quelqu'un qui vient
    # de demander, exactement comme une réponse de Wally dans une conversation.
    await api.send_message(f"@{author} {texte}")
