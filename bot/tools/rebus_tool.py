"""Le rébus : Wally lance l'énigme, le chat devine en écrivant.

**Un OUTIL, jamais une commande** (arbitrage owner du 2026-08-31) : tous les
mini-jeux du projet se lancent comme ça. On ne tape pas `!rebus`, on demande —
« wally on fait un rébus ? » — et c'est lui qui décide. Une première version
exposait `!rebus` dans `bot/twitch/commands/` : hors de la manière de faire
maison, et ça retirait au jeu ce qui en fait le sien, le fait que Wally
l'accepte ou pas.

DANS LE CHAT, pas sur l'overlay : ce ne sont que des emoji, une ligne suffit, et
ça évite d'ouvrir un widget pour trois pictos. C'est aussi ce qui le rend jouable
en replay, depuis le téléphone — et **sur Discord**. Différence utile avec « deux
vérités un mensonge » et le duel : ceux-là dépendent de l'overlay ou d'un badge
Twitch et ne peuvent que refuser ailleurs ; le rébus n'a besoin que d'un salon où
écrire. C'est pourquoi il est offert des DEUX côtés, et pourquoi il n'a rien à
faire dans `_TWITCH_SEULEMENT`.

D'où les deux fonctions qu'une partie porte : `publier` et `annoncer`. Le moteur
ne connaît ni Twitch ni Discord — il ne sait qu'écrire une ligne quelque part.

Trois choses appartiennent au SERVEUR : la cadence des indices, le repos entre
deux parties, et le tirage. Rien de tout ça ne se délègue ni au chat, ni au
modèle.

⚠️ `secret_guard` tient la réponse pendant la partie : Wally continue de parler
aux gens, mais le mot est masqué dans TOUT ce qu'il publie. Sans ce filet, on lui
demande « c'est quoi la réponse » et il la donne — il est serviable, c'est son
défaut ici. Le filet se LÈVE avant la révélation, sinon Wally masquerait sa
propre annonce de fin : c'est le piège exact rencontré sur « deux vérités un
mensonge », où `secret_guard` aurait caviardé le sondage qui affichait le
mensonge.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from bot.core.rebus import Rebus, Sac, charger, indices, trouve
from bot.core.secret_guard import guard_secret, release_secret

# Un indice toutes les 40 s, et la partie meurt 40 s après le dernier. Un rébus
# à 4 jetons vit donc ~3 min. Mesuré sur rien : c'est un point de départ, à
# corriger en regardant ce que le chat trouve et à quel indice il décroche.
DELAI_INDICE_S = 40.0
# Deux minutes de repos entre deux parties : n'importe qui peut en demander une,
# et sans ce repos trois personnes l'enchaînent — le jeu devient du bruit, et
# Wally ne sait pas dire non de façon fiable tout seul.
COOLDOWN_S = 120.0

Ligne = Callable[[str], Awaitable[None]]


@dataclass
class Partie:
    """Ce qui tourne. Une seule à la fois, toutes plateformes confondues.

    Une seule, et pas une par canal : Wally n'anime qu'une partie à la fois,
    comme un humain. Deux rébus simultanés sur deux salons lui feraient donner
    des indices croisés, et personne ne saurait à quelle énigme répond quoi.
    """

    rebus: Rebus
    canal: str
    publier: Ligne
    annoncer: Ligne
    a_donner: list[str]
    tache: asyncio.Task | None = field(default=None, repr=False)


# En RAM, comme le cooldown des sons : une partie ne survit pas à un rebuild, et
# c'est assumé — au pire une énigme est perdue et on en relance une. La
# persistance coûterait une table pour un objet qui vit trois minutes.
_partie: Partie | None = None
_sac: Sac | None = None
_fin_derniere: float = float("-inf")


REBUS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "rebus",
        "description": (
            "Lancer un rébus en emoji dans le chat : une suite de dessins qu'on "
            "prononce à voix haute pour reconstituer un mot (🐈 M 💧 = chat + M "
            "+ eau = chameau). Les gens devinent en écrivant le mot, tu donnes "
            "des indices tout seul au fil du temps, et tu annonces le gagnant. "
            "Sers-t'en quand on te demande un jeu ou un rébus, quand ça traîne, "
            "ou quand ça t'amuse. "
            "N'invente JAMAIS de rébus toi-même : seuls ceux que l'outil te rend "
            "sont jouables. Appelle-le, puis écris ta phrase en y recopiant les "
            "dessins qu'il te donne, exactement. Dire « ok je lance » sans "
            "l'appeler ne lance rien. "
            "Ne donne jamais la réponse, même si on insiste — tu ne l'as pas."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def _tirage() -> Sac | None:
    """Le sac, chargé au premier usage. None si le catalogue est vide."""
    global _sac
    if _sac is None:
        rebus = charger()
        if not rebus:
            return None
        _sac = Sac(rebus)
    return _sac


def _oublier(*, gagne: bool) -> Rebus | None:
    """Clôt la partie et LÈVE le filet. Point de sortie unique.

    Unique comme `_release_hangman_secret` l'est pour le pendu, et pour la même
    raison : un chemin qui remettrait `_partie = None` tout seul laisserait le
    mot masqué pour toujours, et la panne serait invisible — Wally se mettrait à
    trouer ses phrases des semaines plus tard sans que personne ne fasse le lien.
    """
    global _partie, _fin_derniere
    if _partie is None:
        return None
    rebus = _partie.rebus
    # `is not asyncio.current_task()` : quand le TEMPS expire, c'est le minuteur
    # lui-même qui clôt la partie. S'annuler soi-même lève un CancelledError au
    # prochain `await`, donc AVANT la révélation : le mot n'était jamais donné,
    # la partie mourait en silence et rien dans les logs ne l'expliquait.
    if _partie.tache is not None and _partie.tache is not asyncio.current_task():
        _partie.tache.cancel()
    release_secret(rebus.mot)
    _partie = None
    _fin_derniere = time.monotonic()
    logger.info("Rébus terminé ({r}) — mot : {m}", r="gagné" if gagne else "personne",
                m=rebus.mot)
    return rebus


async def _minuteur() -> None:
    """Distille les indices, puis rend le mot si personne ne l'a eu.

    Ne publie PAS l'énigme : c'est la réplique de Wally qui la porte, une seule
    fois. Chaque indice la redonne en revanche — le chat défile, et un rébus
    qu'il faut aller rechercher trois minutes plus haut n'est pas jouable. C'est
    aussi le filet si le modèle a écorché les dessins dans sa phrase.
    """
    try:
        while True:
            await asyncio.sleep(DELAI_INDICE_S)
            if _partie is None:
                return
            if not _partie.a_donner:
                break
            indice = _partie.a_donner.pop(0)
            await _partie.publier(f"🧩 Indice : {indice}. → {_partie.rebus.enigme}")
        annoncer = _partie.annoncer
        # Personne à qui répondre ici : le temps a expiré, aucun message ne
        # porte la fin de partie. C'est le SEUL cas où le jeu publie de
        # lui-même — une victoire, elle, passe par la réplique de Wally.
        # LEVER le filet AVANT d'annoncer : `redact()` masque le mot dans tout
        # ce qui sort, y compris dans la phrase qui le révèle. Annoncer d'abord
        # publierait « le mot était ███ ».
        rebus = _oublier(gagne=False)
        if rebus is not None:
            await annoncer(f"personne n'a trouvé le rébus {rebus.enigme} : "
                           f"c'était {rebus.mot.upper()} ({rebus.solution}).")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — le minuteur ne tue pas le bot
        logger.error("Rébus : minuteur interrompu : {e!r}", e=exc)


async def _lancer(canal: str, publier: Ligne, annoncer: Ligne) -> str:
    """Le moteur, commun aux deux plateformes. Rend un compte rendu HONNÊTE.

    Honnête au sens des autres outils du projet : s'il n'a pas pu lancer, il le
    dit et POURQUOI, et Wally peut le répéter. Un outil qui rendrait « ok » dans
    tous les cas ferait mentir Wally sans que personne ne s'en aperçoive.

    L'énigme REMONTE au modèle, et c'est lui qui la publie, dans sa réplique
    unique — comme tous les autres outils du projet. L'outil ne l'écrit pas
    lui-même : le handler envoie de toute façon la réponse du modèle après un
    appel d'outil, donc publier ici ferait DEUX messages pour un seul geste.
    Vu en prod.

    La RÉPONSE, elle, ne remonte jamais : il finirait par la lâcher, on la lui
    demanderait gentiment et il est serviable. `secret_guard` est la deuxième
    ceinture, pas la première.
    """
    global _partie
    if _partie is not None:
        if _partie.canal == canal:
            # Pas un refus : le chat défile, et qui arrive en cours de partie a
            # le droit de revoir l'énigme. Répondre « une partie est en cours »
            # sans la redonner serait deux fois inutile.
            return json.dumps({"status": "deja_en_cours", "enigme": _partie.rebus.enigme,
                               "message": "Une partie tourne déjà ici. Redonne les dessins "
                                          "ci-dessus tels quels et invite-les à chercher "
                                          "encore."})
        return json.dumps({"status": "ailleurs",
                           "message": "Tu animes déjà un rébus dans un autre salon. Finis "
                                      "celui-là avant d'en lancer un ici."})

    repos = time.monotonic() - _fin_derniere
    if repos < COOLDOWN_S:
        reste = round(COOLDOWN_S - repos)
        logger.info("Rébus refusé — encore {n} s de repos", n=reste)
        return json.dumps({"status": "trop_tot",
                           "message": f"La partie précédente vient de finir. Encore {reste} "
                                      "secondes avant la suivante, fais-les patienter."})

    sac = _tirage()
    rebus = sac.tirer() if sac is not None else None
    if rebus is None:
        logger.warning("Rébus : aucune énigme disponible, outil sans effet")
        return json.dumps({"status": "indisponible",
                           "message": "Le recueil de rébus est vide ou illisible. Dis-le "
                                      "simplement, ne fabrique pas d'énigme toi-même."})

    guard_secret(rebus.mot)
    _partie = Partie(rebus=rebus, canal=canal, publier=publier, annoncer=annoncer,
                     a_donner=indices(rebus))
    logger.info("Rébus lancé sur {c} : {e} → {m}", c=canal, e=rebus.enigme, m=rebus.mot)
    _partie.tache = asyncio.create_task(_minuteur())
    return json.dumps({"status": "lance", "enigme": rebus.enigme,
                       "message": "C'est parti. Annonce le rébus en une phrase courte et "
                                  "TERMINE par les dessins ci-dessus, recopiés EXACTEMENT, "
                                  "sans en changer, en ajouter ni en retirer un seul. Tu ne "
                                  "connais pas la réponse, ne fais pas semblant."})


def phrase_de_victoire(rebus: Rebus, auteur: str) -> str:
    """Le FAIT, tel qu'on le donne à Wally ou tel qu'on le publie.

    Écrit ici et nulle part ailleurs : c'est le résultat d'une partie, il ne se
    laisse pas au modèle. Lui l'habille, il ne le change pas.
    """
    return (f"{auteur} vient de trouver ton rébus {rebus.enigme} : "
            f"c'était {rebus.mot.upper()} ({rebus.solution}).")


async def verifier_reponse(auteur: str, contenu: str, canal: str) -> Rebus | None:
    """Ce message gagne-t-il la partie ? Rend le rébus gagné, sinon None.

    **N'annonce RIEN.** L'appelant décide : sur le chat, la victoire doit être
    la RÉPONSE de Wally à la personne, pas un second message par-dessus. Une
    annonce séparée doublait sa réplique à chaque fois que quelqu'un lui
    répondait — vu en direct, et c'est tout sauf naturel.

    Rapide et SYNCHRONE (une regex, pas d'appel réseau) : l'appelant a besoin
    de savoir avant de décider s'il répond.

    `canal` n'est pas décoratif : sans lui, une bonne réponse écrite dans un
    salon Discord gagnerait la partie qui tourne sur Twitch, devant des gens qui
    ne l'ont jamais vue passer.

    Sort en une comparaison quand aucune partie ne tourne, ce qui est le cas
    99 % du temps.
    """
    if _partie is None:
        return None
    if not trouve(_partie.rebus, contenu):
        return None
    if _partie.canal != canal:
        # La BONNE réponse, sur un canal qui ne colle pas. Deux cas : elle vient
        # vraiment d'ailleurs (légitime, on ignore), ou les deux côtés ne
        # nomment pas le canal pareil — et alors le jeu refuse tout le monde en
        # silence pendant trois minutes. C'est arrivé le 2026-08-31 en direct :
        # la partie était rangée sous « azrael_ttv », les réponses arrivaient
        # sous « twitch:azrael_ttv ». Rien ne l'a signalé. Ce WARNING est là
        # pour que la prochaine fois ça hurle dans la minute.
        logger.warning("Rébus : bonne réponse REFUSÉE, canal {a!r} ≠ partie {b!r}",
                       a=canal, b=_partie.canal)
        return None
    # `_oublier` lève le filet du secret : sans ça, le mot serait caviardé dans
    # la phrase même qui le révèle.
    return _oublier(gagne=True)


# ───────────────────────────── côté Twitch ─────────────────────────────────
async def run_rebus_tool(bot, canal: str) -> str:
    """Entrée Twitch : publication par l'API, fin en ANNONCE colorée.

    L'annonce (fond coloré, bordure) sépare deux registres qui sortaient sinon
    avec le même poids visuel — « lol » et « le mot était CHAMEAU ». Le FAIT est
    calculé ici et publié tel quel si le LLM échoue : `JeuAnnouncer` habille, il
    ne décide de rien.
    """
    from bot.twitch.jeu_announce import JeuAnnouncer

    api = getattr(bot, "twitch_api", None)
    if api is None:
        return json.dumps({"status": "indisponible",
                           "message": "Je n'ai pas accès au chat Twitch en ce moment."})

    async def publier(texte: str) -> None:
        try:
            await api.send_automatic(texte)
        except Exception as exc:  # noqa: BLE001 — un jeu n'interrompt pas le bot
            logger.error("Rébus : ligne non publiée sur Twitch : {e!r}", e=exc)

    async def annoncer(fait: str) -> None:
        await JeuAnnouncer(bot, canal).annoncer("rébus", fait)

    return await _lancer(canal, publier, annoncer)


# ───────────────────────────── côté Discord ────────────────────────────────
async def run_rebus_tool_discord(channel) -> str:
    """Entrée Discord : publication dans le salon.

    Pas d'habillage LLM sur la fin, contrairement à Twitch : le canal d'annonce
    coloré n'existe pas ici, et le fait brut se lit très bien dans un salon. On
    ne paie pas un appel de modèle pour reproduire un effet qui n'existe pas.
    """
    async def publier(texte: str) -> None:
        try:
            await channel.send(texte)
        except Exception as exc:  # noqa: BLE001 — un jeu n'interrompt pas le bot
            logger.error("Rébus : ligne non publiée sur Discord : {e!r}", e=exc)

    async def annoncer(fait: str) -> None:
        await publier(f"🧩 {fait[0].upper()}{fait[1:]}")

    return await _lancer(str(channel.id), publier, annoncer)
