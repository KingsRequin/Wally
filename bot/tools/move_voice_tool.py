"""« Wally, fais venir Lilio sur le stream » — déplacer quelqu'un en vocal.

Demandé par l'owner le 2026-09-01. Pendant le live, Azraël joue : il ne peut
pas ouvrir Discord, cliquer-glisser un pseudo d'un salon vers un autre et
revenir à sa partie. Il le DIT, et Wally le fait.

Trois arbitrages, tous rendus par l'owner :

  · **Le créateur et le streamer, personne d'autre.** Déplacer quelqu'un de
    force est un geste subi : ouvert au chat, il deviendrait un jeu. Le droit
    se dérive de `voice.requesters` par `droits_du_demandeur()` — la même
    fonction que le chemin vocal, pour que la règle n'ait qu'un seul écrivain.
  · **Pendant le live seulement.** Hors live, le « salon du stream » ne
    désigne rien que Wally sache tenir, et le geste n'a pas d'objet.
  · **Il redemande au lieu de deviner.** Le pseudo arrive d'une transcription
    vocale, qui écorche : deux candidats trop proches valent une QUESTION, pas
    un tirage au sort. Se tromper de personne, c'est déplacer quelqu'un qui
    n'avait rien demandé — l'erreur qu'on ne peut pas rattraper poliment.

La cible est le salon résolu par `resolve_voice_channel()`, exactement comme
`PresenceDeStream._salon()` : c'est déjà la définition maison du « salon du
stream » (celui où Wally s'assoit en écoute quand le live monte), et en avoir
une seconde ici les ferait diverger le jour où l'owner change de salon.
"""
from __future__ import annotations

import json
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from loguru import logger

from bot.tools.follow_tool import api_twitch

# En dessous, ce n'est plus « le même nom mal entendu », c'est un autre nom.
# 0,72 est le seuil déjà retenu par `voice/brain.py` pour reconnaître un mot
# dans une transcription — même source d'erreur, même tolérance.
_PROCHE = 0.72

# L'écart minimal entre le meilleur candidat et le suivant. En deçà, Wally
# REDEMANDE : c'est le geste que l'owner a explicitement demandé, et c'est la
# seule protection contre un déplacement infligé à la mauvaise personne.
_ECART_MIN = 0.12

# Ce qu'on renvoie au modèle quand plusieurs personnes se ressemblent. Trois
# suffisent à poser la question ; au-delà, la question devient une liste.
_MAX_CANDIDATS = 3


MOVE_TO_STREAM_TOOL = {
    "type": "function",
    "function": {
        "name": "move_to_stream",
        "description": (
            "Déplacer quelqu'un vers le salon vocal du STREAM, quand le "
            "streamer ou le créateur te le demande pendant le live (« fais "
            "venir Lilio », « ramène-le sur le stream », « mets-la avec "
            "nous »). Tu ne devines JAMAIS : si l'outil répond qu'il hésite "
            "entre plusieurs personnes, demande laquelle et rappelle l'outil "
            "après la réponse. Ne prétends pas avoir déplacé quelqu'un tant "
            "que l'outil ne te l'a pas confirmé."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "person": {
                    "type": "string",
                    "description": (
                        "Le pseudo tel que tu l'as entendu ou lu, même si tu "
                        "doutes de l'orthographe : l'outil cherche le plus "
                        "proche parmi les gens réellement en vocal."
                    ),
                },
            },
            "required": ["person"],
        },
    },
}


def _plier(mot: str) -> str:
    """Minuscules sans accents : « Lïlio » et « lilio » se rangent ensemble."""
    plie = unicodedata.normalize("NFD", (mot or "").lower().strip())
    return "".join(c for c in plie if unicodedata.category(c) != "Mn")


def _noms(membre: Any) -> list[str]:
    """Toutes les façons d'appeler quelqu'un sur Discord.

    Le surnom de serveur, le pseudo de compte et le nom global : la personne
    qui parle emploie celui qu'elle voit, et ce n'est pas toujours le même que
    celui affiché dans la liste vocale.
    """
    return [n for n in (getattr(membre, "display_name", None),
                        getattr(membre, "global_name", None),
                        getattr(membre, "name", None)) if n]


def _score(cible: str, membre: Any) -> float:
    """À quel point ce membre répond au nom `cible`. 0 à 1."""
    c = _plier(cible)
    if not c:
        return 0.0
    meilleur = 0.0
    for nom in _noms(membre):
        n = _plier(nom)
        if not n:
            continue
        if n == c:
            return 1.0
        # Une inclusion vaut mieux qu'un ratio : « azra » dans « Azrael_ttv »
        # ne vaut que 0,57 en SequenceMatcher alors que c'est le surnom usuel.
        # Trois lettres au moins, sinon « al » désignerait la moitié du salon.
        if len(c) >= 3 and (c in n or n in c):
            meilleur = max(meilleur, 0.9)
        meilleur = max(meilleur, SequenceMatcher(None, c, n).ratio())
    return meilleur


def classer(cible: str, membres: list) -> list[tuple[float, Any]]:
    """Les membres du plus au moins ressemblant. Exposé pour les tests."""
    return sorted(((_score(cible, m), m) for m in membres),
                  key=lambda p: p[0], reverse=True)


def _discord(bot: Any) -> Any:
    """Le bot Discord, vu depuis l'une OU l'autre plateforme.

    Le chemin Twitch y accède par la référence croisée `discord_bot` ; appelé
    depuis Discord, `bot` EST déjà le bon — la seule recherche croisée rendait
    None, piège déjà payé sur `say_in_voice`.
    """
    return (getattr(bot, "discord_bot", None)
            or (bot if getattr(bot, "voice_service", None) is not None else None))


async def _salon_du_stream(bot: Any) -> Any:
    """Le salon vocal du stream, VÉRIFIÉ présent — ou None."""
    from bot.discord.voice.channel_memory import resolve_voice_channel

    discord_bot = _discord(bot)
    db = getattr(bot, "db", None)
    if discord_bot is None or db is None:
        return None
    return await resolve_voice_channel(
        discord_bot, db, getattr(bot.config.bot, "stream_voice_channel_id", None))


def _autorise(bot: Any, *, platform: str, user_id: str) -> bool:
    """Le créateur et le streamer, personne d'autre.

    La règle n'est pas réécrite ici : `droits_du_demandeur()` la tient déjà
    pour le chemin vocal, et c'est elle qui sait qu'appartenir à
    `voice.requesters` ne donne AUCUN droit par soi-même — cette liste sert
    aussi à déclarer les comptes Apex.
    """
    from bot.discord.voice.request import droits_du_demandeur

    uid = str(user_id or "").strip()
    if not uid:
        return False
    champ = "discord_id" if str(platform).startswith("discord") else "twitch_id"
    entree = next(
        (r for r in (getattr(bot.config.voice, "requesters", None) or [])
         if str((r or {}).get(champ) or "").strip() == uid),
        None,
    )
    if entree is None:
        return False
    roles, _ = droits_du_demandeur(
        entree,
        broadcaster_id=getattr(api_twitch(bot), "_broadcaster_id", "") or "",
        owner_discord_id=str(getattr(bot.config.bot, "owner_discord_id", "") or ""),
    )
    return "admin" in roles


def presents_hors_stream(salon_stream: Any) -> list:
    """Qui est en vocal ailleurs que dans le salon du stream, sur ce serveur.

    Les bots sont écartés : Wally s'y trouve lui-même, et se déplacer sur
    ordre d'un pseudo mal entendu ferait un beau numéro.
    """
    guilde = getattr(salon_stream, "guild", None)
    if guilde is None:
        return []
    return [m
            for salon in getattr(guilde, "voice_channels", []) or []
            if salon.id != salon_stream.id
            for m in getattr(salon, "members", []) or []
            if not getattr(m, "bot", False)]


async def run_move_to_stream_tool(bot: Any, args: dict, *, platform: str,
                                  user_id: str, author: str = "") -> str:
    """Déplace la personne nommée vers le salon du stream, ou dit pourquoi non.

    Chaque refus porte un `message` rédigé pour être DIT : un `{"status":
    "error"}` nu laisse le modèle inventer une explication, et il invente en
    général qu'il n'a pas la capacité.
    """
    cible = str((args or {}).get("person") or "").strip()
    if not cible:
        return json.dumps({"status": "error", "message": (
            "Tu ne m'as pas dit QUI déplacer. Demande le pseudo.")})

    if not _autorise(bot, platform=platform, user_id=user_id):
        logger.info("move_to_stream refusé — {p}:{u} n'y a pas droit",
                    p=platform, u=user_id)
        return json.dumps({"status": "denied", "message": (
            "Refusé : seuls Azraël et ton créateur peuvent faire déplacer "
            "quelqu'un en vocal. Dis-le simplement.")})

    from bot.discord.handlers import _overlay_narrator

    narrateur = _overlay_narrator(bot)
    if narrateur is None or not narrateur.is_active():
        return json.dumps({"status": "offline", "message": (
            "Il n'y a pas de live en cours : le salon du stream n'attend "
            "personne. Dis-le au lieu de déplacer qui que ce soit.")})

    salon = await _salon_du_stream(bot)
    if salon is None:
        return json.dumps({"status": "unavailable", "message": (
            "Je ne trouve pas le salon vocal du stream. Dis-le, ne déplace "
            "personne.")})

    # Ceux qui sont DÉJÀ là comptent, mais à part : sans ce passage, « fais
    # venir Lilio » alors que Lilio est assis dans le salon du stream répondait
    # « personne ne s'appelle comme ça », ce qui est faux ET vexant. Le bon mot
    # est « il y est déjà ».
    deja = [m for m in (getattr(salon, "members", []) or [])
            if not getattr(m, "bot", False) and _score(cible, m) >= _PROCHE]

    membres = presents_hors_stream(salon)
    if deja and not [m for m in membres if _score(cible, m) >= _PROCHE]:
        nom = getattr(deja[0], "display_name", cible)
        return json.dumps({"status": "already", "moved": nom, "message": (
            f"{nom} est DÉJÀ dans le salon du stream : il n'y a rien à "
            f"déplacer. Dis-le.")})
    if not membres:
        return json.dumps({"status": "empty", "message": (
            "Personne n'est en vocal ailleurs que dans le salon du stream : "
            "il n'y a personne à faire venir.")})

    classes = classer(cible, membres)
    meilleur, membre = classes[0]
    noms = [getattr(m, "display_name", "") for _, m in classes[:_MAX_CANDIDATS]]
    if meilleur < _PROCHE:
        return json.dumps({"status": "unknown", "en_vocal": noms, "message": (
            f"Personne ne s'appelle « {cible} » parmi les gens en vocal. "
            f"Il y a : {', '.join(noms)}. Demande de qui il s'agit.")})

    proches = [m for s, m in classes[1:] if meilleur - s < _ECART_MIN]
    if proches:
        hesitation = [getattr(membre, "display_name", "")] + [
            getattr(m, "display_name", "") for m in proches[:_MAX_CANDIDATS - 1]]
        logger.info("move_to_stream : hésitation sur « {c} » entre {n}",
                    c=cible, n=" et ".join(hesitation))
        return json.dumps({"status": "ambiguous", "candidats": hesitation,
                           "message": (
                               f"Plusieurs personnes répondent à « {cible} » : "
                               f"{', '.join(hesitation)}. DEMANDE laquelle, ne "
                               f"choisis pas toi-même, et rappelle-moi ensuite.")})

    depuis = getattr(getattr(membre, "voice", None), "channel", None)
    try:
        await membre.move_to(salon, reason=f"demandé par {author or 'le streamer'} via Wally")
    except Exception as exc:  # noqa: BLE001 — le chat ne casse pas sur un droit manquant
        logger.warning("move_to_stream : {m} non déplacé — {e!r}",
                       m=getattr(membre, "display_name", "?"), e=exc)
        return json.dumps({"status": "failed", "message": (
            "Le déplacement a échoué — il me manque sans doute le droit "
            "« Déplacer des membres » sur le serveur. Dis-le, et ne prétends "
            "pas l'avoir fait.")})

    nom = getattr(membre, "display_name", "")
    logger.info("move_to_stream : {m} déplacé de {d} vers {s} (demandé par {a})",
                m=nom, d=getattr(depuis, "name", "?"),
                s=getattr(salon, "name", "?"), a=author or f"{platform}:{user_id}")
    return json.dumps({"status": "ok", "moved": nom,
                       "from": getattr(depuis, "name", "") or "",
                       "message": f"{nom} est maintenant dans le salon du stream."})
