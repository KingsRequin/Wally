"""OverlayNarrator — décide de ce qui monte à l'écran, et à quel rythme.

Le risque de ce projet est produit, pas technique : un compagnon qui commente
sans arrêt devient insupportable, et un overlay ne se scrolle pas. Le budget de
parole est donc un **mécanisme qui refuse**, pas une consigne dans un prompt.

Deux garde-fous, dans cet ordre :

1. **Rien hors live.** En dehors d'un stream, personne ne regarde : on ne
   dépense ni appel LLM ni bulle.
2. **Un intervalle minimal**, vérifié AVANT de condenser — inutile de payer un
   appel pour un texte qu'on jetterait.

Les pensées internes de Wally sont longues et introspectives ; l'overlay veut
quelques mots. La condensation passe par le modèle rapide (mesuré ~1,3 s sur ce
format), pas par une troncature qui couperait au milieu d'une idée.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import re
import time
import unicodedata
from collections import deque
from math import ceil
from urllib.parse import quote
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from bot.core.audit_log import journal, note_audience, note_speech
from bot.core.conversation_log import new_trace_id
from bot.core.music import vignette
from bot.core.overlay_feed import ecourter
from bot.core.secret_guard import guard_secret, release_secret
from bot.intelligence.prompts import (
    load_prompt,
    marqueur_de_service,
    nettoyer_decorations,
)

# Le planning des streams : une image fixe déposée à la main dans
# `bot/dashboard/static/fichiers/`. Le chemin sert l'overlay (même hôte), l'URL
# absolue sert le chat — collé dans Discord, un chemin relatif ne montre rien.
PLANNING_PATH = "/static/fichiers/planning.webp"

# Où atterrit le journal des bulles, dans l'arborescence existante :
# `logs/conversations/overlay/bulles/{date}.jsonl`.
OVERLAY_JOURNAL_PLATFORM = "overlay"
OVERLAY_JOURNAL_CHANNEL = "bulles"


def _vocal_diffuse() -> bool:
    """La parole vocale entendue est-elle diffusée au live ? Fermé par défaut.

    Import PARESSEUX : `voice_transcript` tire `stream_watcher`, et ce module
    est importé très tôt par `twitch/handlers`. La question ne se pose qu'aux
    bulles issues du vocal, quelques centaines de fois par live.
    """
    try:
        from bot.core.voice_transcript import voice_broadcast_open

        return voice_broadcast_open()
    except Exception as exc:  # noqa: BLE001 — dans le doute, on n'écrit pas
        logger.debug("Overlay: diffusion vocale indéterminée ({e!r})", e=exc)
        return False


def ouverture_de_partie(widget: str, **extra) -> str | None:
    """Le nom de la partie que cet appel OUVRIRAIT, ou None.

    Quatre widgets durent : le bingo, le sondage, le pendu, l'objectif. Les
    autres ne font que passer. Mais un même widget ouvre OU continue — c'est
    l'argument qui tranche : sans `cells`, un appel au bingo coche une case ou
    remontre la grille ; sans `word`, le pendu remontre la sienne.

    Source de vérité UNIQUE des deux règles qui pèsent sur ces parties : « on
    n'en ouvre pas une par-dessus une autre » (`game_already_running`) et « on
    n'en ouvre pas une que personne n'a demandée » (`refus_faute_de_demande`).
    Deux listes finiraient par diverger, et le jour où l'une oublie un widget,
    c'est un bingo de plus à l'écran.
    """
    widget = (widget or "").strip()
    if widget == "bingo":
        cases = [c for c in (extra.get("cells") or []) if str(c).strip()]
        return "bingo" if cases else None
    if widget == "poll":
        return "sondage"
    if widget == "hangman":
        return "pendu" if str(extra.get("word") or "").strip() else None
    if widget == "goal":
        return "objectif"
    return None


def planning_url() -> str:
    """URL publique du planning, pour le chat.

    `WEB_BASE_URL` est déjà la base publique du projet (OAuth, invitations) :
    la réutiliser évite d'écrire le domaine en dur une seconde fois.
    """
    base = os.getenv("WEB_BASE_URL", "").rstrip("/")
    return f"{base}{PLANNING_PATH}"


# Intervalle minimal entre deux bulles de pensée. Elles occupent l'écran quand
# il ne se passe rien : plus fréquentes qu'une réaction, mais loin d'être
# continues.
_MIN_THOUGHT_INTERVAL_S = 90.0

# Un événement de stream mérite son propre créneau : quand un raid tombe, se
# taire parce qu'une pensée vient de passer serait absurde. Court, car ces
# événements sont rares et attendus par le public.
_MIN_EVENT_INTERVAL_S = 20.0

# La parole entendue en vocal a son PROPRE créneau, et il est long.
#
# Mesuré sur le live du 2026-08-13 : 148 bulles en 162 min (une toutes les 46 à
# 66 s) pour 357 appels au modèle, dont l'essentiel venait d'ici. À ce rythme
# l'overlay commente en continu, et une observation quelconque chasse de l'écran
# celle qui valait le coup. Le vocal est un flux permanent, pas un événement :
# son budget doit être celui d'un compagnon qui place un mot de temps en temps.
#
# Créneau séparé de `_MIN_EVENT_INTERVAL_S` dans les DEUX sens : le bavardage ne
# doit pas faire taire un raid, et un raid ne doit pas ouvrir un créneau au
# vocal. C'est justement ce que faisait l'horloge unique.
_MIN_OVERHEARD_INTERVAL_S = 150.0

# Combien de tours de vocal on met sous les yeux du modèle. Une réplique seule
# ne se comprend pas — « et toi ? », « ah bah bravo » — et condenser une phrase
# isolée ne laisse rien d'autre à faire que la paraphraser, ce que 44 % des
# bulles du 13/08 faisaient (« Il a… », « Il vise… », « Il parle… »).
_OVERHEARD_CONTEXT_LINES = 8

# Part minimale de mots qui appartiennent à la BULLE et non à ce qu'elle vient
# d'entendre. En dessous, la bulle ne fait que redire l'échange avec d'autres
# pronoms : elle occupe l'écran sans rien apprendre à personne.
#
# Le seuil sépare nettement les deux familles observées le 13/08 :
# « Il vise encore les murs » (1 mot à lui sur 3) tombe, « Il compte ses heures
# comme des PV » (2 sur 3) et « Ils se croient dans un film d'action » (3 sur 3)
# passent. Les prénoms sont exclus du calcul : nommer quelqu'un ne doit être ni
# récompensé ni puni par ce filtre.
_MIN_APPORT = 0.5

# Événements sur lesquels l'avatar s'emballe en plus de la bulle. Repérage par
# mot-clé sur la description déjà rédigée en français par StreamFeed.
_STRONG_EVENT_HINTS = ("raid", "sub", "abonn", "bits", "cheer", "don")

# Les types d'événements du live, et ceux qui méritent que l'avatar s'emballe.
# Un type connu remplace la recherche de mots dans le texte : « raid » dans un
# titre de stream ne doit pas valoir un raid.
_EVENT_KINDS = (
    "raid", "follow_wave", "sub", "resub", "gift_sub", "bits",
    "live_start", "live_end", "game_change", "title_change", "audience",
)
_STRONG_EVENT_KINDS = frozenset({"raid", "sub", "resub", "gift_sub", "bits", "follow_wave"})

# Au-delà, la condensation a échoué à faire court : on préfère se taire plutôt
# que d'afficher un pavé illisible en petit.
_MAX_BUBBLE_CHARS = 90

# Au-delà de ce délai sans être vu, un habitué qui revient mérite un mot.
_RETURN_AFTER_DAYS = 7

# Durée par défaut d'un sondage. Peut être demandée plus longue.
_POLL_DEFAULT_S = 10

# Les coups du chifoumi, en français. Au niveau du MODULE parce que le schéma
# d'outil (plus bas) doit s'en servir : deux listes divergeraient, et c'est
# précisément ce qui est arrivé — l'enum en anglais faisait retomber la triche
# sur un tirage au hasard.
_RPS_MOVES = ("pierre", "feuille", "ciseaux")

# Plafond du mode test hors live : au-delà, ce n'est plus un réglage,
# c'est un live fantôme qu'on a oublié de couper.
_MAX_FORCE_LIVE_MIN = 120

# Échéance du mode test, rangée en base. En EPOCH et non en `monotonic` :
# l'horloge monotone repart de zéro à chaque process, donc le mode test était
# perdu à chaque redémarrage — au moment précis où l'on s'en sert, puisqu'on
# règle l'overlay entre deux déploiements.
FORCE_LIVE_KEY = "overlay:force_until"

# Les parties en cours (bingo, pendu, objectif), rangées en base pour traverser
# un redémarrage. Le 2026-08-14, quatre bingos ont été ouverts dans la journée,
# un redémarrage entre chaque, les deux derniers dans le MÊME live — et sa
# pensée de 22:06:32 dit exactement pourquoi : « Est-ce que j'ai déjà ouvert le
# bingo ? Je ne vois pas de trace dans "Sur ton overlay" ni dans "Ce que TU
# viens de faire" ». La garde `game_already_running` est juste, mais elle ne
# protège que dans le process qui a ouvert la partie.
#
# Le sondage reste dehors : sa clôture est une tâche asyncio qui ne survit pas
# au process, et il dure quelques minutes — le ressusciter sans son minuteur
# laisserait un dépouillement qui n'arrive jamais.
LIVE_STATE_KEY = "overlay:live_state"

# Âge au-delà duquel un état rangé n'est plus celui du live en cours, quand le
# live n'est pas identifiable (statut Twitch pas encore revenu du poll). Un
# redémarrage se compte en minutes ; un live précédent, en heures.
_LIVE_STATE_MAX_AGE_S = 900.0

# Les mentions en tête d'un message adressé au bot. Uniquement en TÊTE : un
# « @toto » en fin de phrase appartient à la phrase, pas à l'interpellation.
_ADDRESS_RE = re.compile(r"^(?:\s*@[\w_]+[\s,:!]*)+", re.UNICODE)


def _strip_address(text: str) -> str:
    """Le message sans l'interpellation qui le précède.

    « @WallyTeBully d » → « d ». C'est ce qui permet de jouer une lettre, un
    vote ou un coup en s'adressant à Wally, ce que tout le monde fait
    naturellement sur Twitch.
    """
    return _ADDRESS_RE.sub("", text or "").strip()


_EVENT_SYSTEM = load_prompt(
    "overlay_event",
    fallback=(
        "Réagis à cet événement du stream en 3 à 8 MOTS, adressés aux SPECTATEURS. "
        "Une seule idée, ton naturel. Réponds uniquement par la phrase, ou RIEN."
    ),
    render=False,
)

# La parole entendue en vocal a son propre cadrage. Passée par `_EVENT_SYSTEM`,
# qui annonce « un raid, un abonnement, des bits… », elle sommait le modèle de
# ranger une phrase de conversation dans des catégories d'événements : il
# recopiait alors l'exemple du raid et l'overlay annonçait « du monde débarque »
# sans que personne ne soit arrivé.
_OVERHEARD_SYSTEM = load_prompt(
    "overlay_overheard",
    fallback=(
        "Réagis en 3 à 8 MOTS à cette phrase ENTENDUE en vocal, adressés aux "
        "SPECTATEURS. Ce n'est pas un événement du stream : n'annonce ni raid, "
        "ni abonnement, ni bits. Le silence est normal — réponds RIEN si tu n'as "
        "rien à dire."
    ),
    render=False,
)

_CONDENSE_SYSTEM = load_prompt(
    "overlay_thought",
    fallback=(
        "Condense cette pensée en 3 à 8 MOTS, à la première personne, ton naturel. "
        "Une seule idée. Pas de ponctuation lourde, pas de guillemets. "
        "Réponds uniquement par la phrase."
    ),
    render=False,
)


# ── Ce qu'aucune scène n'affiche ────────────────────────────────────────────
#
# Un widget masqué sur TOUTES les scènes ne doit ni être proposé à Wally, ni le
# laisser annoncer « c'est à l'écran » s'il le demande quand même : c'est la
# leçon de « il ne savait pas qu'il affichait les bingos », dans l'autre sens.
#
# Masqué sur une SEULE scène, il reste utilisable — Wally ignore laquelle est à
# l'antenne, et c'est la page qui filtre.

# Ce que l'outil nomme → ce que la page rend. Sans cette table, `goal` serait
# introuvable dans le modèle et l'enum le proposerait toujours, jauge masquée
# partout : `_publish_goal` publie un `gauge`, et `uptime` est rendu en
# `counter`. Le modèle suit la PAGE, pas les noms d'outils.
_ALIAS_RENDU = {"goal": "gauge", "uptime": "counter"}


def _cle_de_rendu(kind: str) -> str:
    return _ALIAS_RENDU.get(kind, kind)


async def widgets_disponibles(db) -> frozenset:
    """Les widgets affichables sur AU MOINS une scène.

    Rend TOUT ce que l'outil connaît quand la question n'a pas de réponse — pas
    de base, layout illisible, scène sans la clé. Ne pas savoir ne vaut pas
    interdire : une garde qui se referme sur son propre silence priverait le
    live de tout l'overlay pour une lecture SQLite ratée.
    """
    connus = frozenset(OverlayNarrator._WIDGETS)
    if db is None:
        return connus
    try:
        from bot.core.overlay_layout_store import charger_layout
        layout = await charger_layout(db)
        scenes = layout.get("scenes") or []
    except Exception as exc:      # lecture ratée, modèle inattendu
        logger.warning("Overlay : widgets disponibles illisibles ({e!r}) — "
                       "aucun n'est retiré", e=exc)
        return connus
    if not scenes:
        return connus

    def visible(cle: str) -> bool:
        rendu = _cle_de_rendu(cle)
        vu = False
        for scene in scenes:
            el = (scene.get("elements") or {}).get(rendu)
            # Clé absente du modèle (widget hors mise en scène, comme le
            # planning) : rien ne le masque, il reste disponible.
            if el is None:
                return True
            vu = True
            if not el.get("hidden"):
                return True
        return not vu

    return frozenset(cle for cle in connus if visible(cle))


async def spec_overlay_filtree(db) -> dict:
    """La définition de `show_overlay`, privée des widgets qu'aucune scène
    n'affiche."""
    return spec_overlay_depuis(await widgets_disponibles(db))


async def spec_overlay_pour(narrateur) -> dict:
    """La spec à jour si on sait la calculer, la spec ENTIÈRE sinon.

    Le filtrage est un CONFORT : il retire ce qu'aucune scène n'affiche. Le
    laisser lever priverait Wally de tous ses outils d'un coup — l'exception
    remonterait dans `build_chat_tools`, qui en construit vingt autres, et le
    chat n'aurait plus ni mémoire, ni notes, ni Apex pour une lecture SQLite
    manquée. C'est la même règle que dans `widgets_disponibles` : ne pas savoir
    ne vaut pas interdire.
    """
    try:
        return await narrateur.spec_outil()
    except Exception as exc:
        logger.warning("Overlay : enum non filtré ({e!r}) — spec entière servie",
                       e=exc)
        return OVERLAY_TOOL_SPEC


def spec_overlay_depuis(dispo) -> dict:
    """La spec filtrée par un ensemble DÉJÀ lu — le chemin des adaptateurs, qui
    rafraîchissent le cache du refus dans le même aller-retour.

    Rend une COPIE : la spec d'origine est importée au niveau module par les
    deux plateformes, et la muter ferait disparaître un widget pour tout le
    monde jusqu'au prochain redémarrage.
    """
    enum = OVERLAY_TOOL_SPEC["function"]["parameters"]["properties"]["widget"]["enum"]
    garde = [w for w in enum if w in dispo]
    # Tout masqué : on rend la spec entière plutôt qu'un enum vide, que les
    # fournisseurs refusent — un outil invalide ferait échouer TOUS les appels,
    # y compris ceux qui n'ont rien à voir avec l'overlay.
    if not garde or garde == list(enum):
        return OVERLAY_TOOL_SPEC
    spec = copy.deepcopy(OVERLAY_TOOL_SPEC)
    spec["function"]["parameters"]["properties"]["widget"]["enum"] = garde
    return spec


# Annotée `dict` : sans elle, mypy infère un type de valeur commun à toutes les
# clés (`Collection[str]`) et refuse d'indexer la structure imbriquée — que le
# filtrage de l'enum parcourt.
OVERLAY_TOOL_SPEC: dict = {
    "type": "function",
    "function": {
        "name": "show_overlay",
        "description": (
            "Affiche un widget sur l'overlay du stream, quand on te le demande ou "
            "que l'envie te prend. Ne fonctionne QUE pendant un live — hors live "
            "l'outil te le dira, et tu pourras le dire simplement. C'est toi qui "
            "décides : tu peux refuser si on t'en demande trop, commenter le "
            "résultat, et même forcer le tirage pour tricher. ⚠️ L'overlay est vu "
            "par les SPECTATEURS, pas par le streamer : ton `comment` s'adresse à "
            "eux. Ne prétends jamais avoir affiché quelque chose sans appeler cet "
            "outil. ⚠️ Une seule partie à la fois : le bingo, le sondage, le "
            "pendu et l'objectif DURENT — si l'un d'eux tourne déjà, l'outil "
            "REFUSE d'en rouvrir un du même type et te dit ce qui tourne et où "
            "ça en est ; rien n'est écrasé. Continue celle-là, ou annule-la "
            "d'abord avec `cancel_overlay`. Les autres widgets se relancent "
            "autant que tu veux."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "widget": {
                    "type": "string",
                    "enum": ["coinflip", "dice", "wheel", "countdown", "gauge",
                             "pinned", "uptime", "counter", "poll", "stats", "versus",
                             "bingo", "meme", "rps", "hangman", "goal", "talkers"],
                    "description": (
                        "coinflip = pile ou face · dice = un dé · wheel = la roue "
                        "tranche entre 2-8 options · countdown = compte à rebours "
                        "· gauge = jauge 0-100 · pinned = met en avant un message "
                        "du chat · uptime = durée du live (calculée pour toi) · "
                        "counter = un texte bref · poll = sondage, le chat vote en "
                        "tapant le numéro · stats = les chiffres d'un joueur · "
                        "versus = compare deux joueurs sur une valeur · "
                        "meme = une image de la communauté · "
                        "rps = chifoumi contre celui qui te le demande, "
                        "tranché sur-le-champ · "
                        "bingo = une grille de pronostics sur le live · "
                        "hangman = le pendu — TU choisis le mot et tu lances "
                        "dans la foulée, le chat propose ensuite des lettres, "
                        "une par message, ou tape le mot entier pour gagner "
                        "d'un coup · "
                        "goal = un objectif de follows/subs/bits qui se remplit "
                        "tout seul · talkers = le podium des plus bavards"
                    ),
                },
                "comment": {
                    "type": "string",
                    "description": "Ta réplique, quelques mots — c'est elle qu'on lit, pas l'animation.",
                },
                "result": {
                    "type": "string",
                    "description": (
                        "Résultat imposé, optionnel : 'heads'/'tails', un chiffre "
                        "de dé, l'index gagnant de la roue. Omets-le pour un "
                        "tirage au sort. (Pour la durée d'un compte à rebours, "
                        "utilise `seconds` ; pour la jauge, `percent`.)"
                    ),
                },
                "options": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Les choix, pour wheel (2-8) ou poll (2-4).",
                },
                "question": {"type": "string", "description": "La question, pour poll."},
                "seconds": {"type": "integer", "description": (
                    "Une durée en secondes : celle d'un sondage (10 par défaut, "
                    "120 max) ou celle d'un compte à rebours (600 max). Pour un "
                    "minuteur, c'est ce paramètre qu'il faut remplir."
                )},
                "percent": {"type": "number", "description": "Pour gauge : le remplissage, de 0 à 100."},
                "count": {"type": "integer", "description": "Nombre de dés à lancer, pour dice (1 par défaut, 4 max)."},
                "cells": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Pour bingo : 4 à 9 pronostics courts sur ce qui va arriver pendant le live.",
                },
                "check": {"type": "string", "description": "Pour bingo : la case qui vient de se réaliser — son numéro (0 = la première) ou quelques mots de son intitulé."},
                "target": {"type": "integer", "description": "Pour goal : le nombre à atteindre."},
                "kind": {"type": "string", "enum": ["follow", "sub", "bits"], "description": "Pour goal : ce qu'on compte."},
                "about": {"type": "string", "description": "Pour meme : de quoi tu veux qu'il parle. Omets-le pour un tirage au hasard."},
                "player": {"type": "string", "description": "Le pseudo, pour stats."},
                "lines": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Pour stats : 1 à 4 lignes déjà rédigées, ex. « Rang : Diamant 3 », « Kills : 82 522 ».",
                },
                "label": {"type": "string", "description": "L'intitulé, pour gauge et versus (ex. « Kills »)."},
                "left_name": {"type": "string", "description": "Premier joueur comparé, pour versus."},
                "left_value": {"type": "number", "description": "Sa valeur chiffrée, pour versus."},
                "right_name": {"type": "string", "description": "Second joueur comparé, pour versus."},
                "right_value": {"type": "number", "description": "Sa valeur chiffrée, pour versus."},
                "text": {"type": "string", "description": "Le message mis en avant, pour pinned."},
                "author": {"type": "string", "description": "L'auteur du message, pour pinned."},
                "word": {"type": "string", "description": (
                    "Pour hangman : le mot à deviner, 3 à 16 lettres. C'est TOI "
                    "qui le choisis, tout seul, dans le même appel — ne demande "
                    "jamais qu'on t'en propose un, c'est le principe du jeu que "
                    "les autres le devinent. Prends-le dans l'univers de la "
                    "chaîne (un jeu, une légende Apex, une expression maison). "
                    "Sans lui rien ne se lance, et ne le répète JAMAIS dans le "
                    "chat : tu ruinerais la partie."
                )},
                "hint": {"type": "string", "description": (
                    "Pour hangman : un indice court. Donne-le ici sans crainte — "
                    "il reste caché et n'apparaît à l'écran qu'à deux essais "
                    "restants. Ne l'écris donc pas dans le chat au lancement."
                )},
                "done": {"type": "string", "description": "Pour countdown : le texte affiché quand le compte à rebours arrive à zéro."},
                "move": {
                    "type": "string",
                    # En FRANÇAIS : c'est ce que `_RPS_MOVES` compare. Un enum en
                    # anglais faisait retomber la triche sur un tirage au hasard,
                    # Wally annonçant un coup et l'overlay en affichant un autre.
                    "enum": list(_RPS_MOVES),
                    "description": "Pour rps : le coup que TU joues. Omets-le pour un tirage honnête.",
                },
            },
            "required": ["widget"],
        },
    },
}


# Narrateur actif, pour que `prompts.py` puisse lire l'état de l'overlay sans
# qu'on ait à faire descendre le narrateur jusque-là. Même patron que
# `stream_feed.activate()` — l'injection de dépendance s'arrête au bot Discord.
_active_narrator: "OverlayNarrator | None" = None


def overlay_actif() -> bool:
    """Vrai si l'overlay écoute — vrai live ou mode test. Faux s'il n'y en a pas.

    Sert à ne proposer le catalogue des widgets qu'au moment où il peut servir : il
    pesait 23 % du prompt de raisonnement et partait 24 h/24 (cf.
    `prompts/overlay_widgets.md`). C'est le NARRATEUR qui tranche, pas `_stream_info` :
    lui seul connaît le mode test hors live.
    """
    if _active_narrator is None:
        return False
    return bool(_active_narrator.is_active())


def current_overlay_state_block() -> Optional[str]:
    """Ce qui tourne sur l'overlay, prêt à injecter au prompt. None si rien."""
    if _active_narrator is None:
        return None
    try:
        return _active_narrator.current_state_block() or None
    except Exception as exc:  # noqa: BLE001 — un bloc de contexte ne casse pas un prompt
        logger.debug("Overlay: bloc d'état illisible: {e!r}", e=exc)
        return None


# Ce qu'on peut annuler. Constante de module : le spec de l'outil en a besoin
# avant que la classe ne soit définie, et les deux doivent rester d'accord —
# une cible acceptée par l'enum mais inconnue de `cancel()` répondrait
# « rien en cours » sur une demande pourtant valide.
# Le chifoumi n'y est plus : il se tranche à l'instant où on le demande, il ne
# laisse donc rien d'ouvert à abandonner.
CANCEL_TARGETS = ("ecran", "bingo", "pendu", "sondage", "objectif", "tout")


CANCEL_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "cancel_overlay",
        "description": (
            "Retire quelque chose de l'overlay du stream : ce qui est affiché à "
            "l'instant, ou une partie en cours qu'on abandonne. Sers-t'en quand "
            "on te demande d'annuler ou d'enlever un truc — et de toi-même quand "
            "une partie traîne sans que personne y joue. Tu peux refuser, comme "
            "pour le reste. ⚠️ Un abandon ne donne PAS de résultat : un sondage "
            "annulé n'est pas dépouillé, un pendu annulé n'a pas de gagnant — "
            "ne les annonce pas. N'affirme jamais avoir annulé sans appeler cet "
            "outil : il te dira s'il y avait vraiment quelque chose."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": list(CANCEL_TARGETS),
                    "description": (
                        "ecran = ce qui est affiché maintenant (un meme, un "
                        "message épinglé, un compteur) sans toucher aux parties "
                        "en cours · bingo · pendu · sondage · "
                        "objectif = la partie correspondante est abandonnée · "
                        "tout = l'écran ET toutes les parties. Dans le doute "
                        "entre « enlève ce qui est affiché » et « annule le "
                        "bingo », choisis la cible précise."
                    ),
                },
                "comment": {
                    "type": "string",
                    "description": "Ta réplique, quelques mots. Facultatif.",
                },
            },
            "required": ["target"],
        },
    },
}


LAST_CLIP_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "show_clip",
        "description": (
            "Affiche un clip de la chaîne sur l'overlay : le dernier, le plus "
            "vu, ou celui qui correspond à un titre. Peut aussi montrer le "
            "PODIUM des clips les plus vus (`top`). La vidéo est MUETTE et reste "
            "à l'écran le temps du clip. Tu n'as pas vu ce clip — l'outil te rend "
            "son titre et qui l'a créé, commente à partir de ça et n'invente pas "
            "ce qu'il contient. N'affirme jamais l'avoir lancé sans appeler cet "
            "outil, et ne décrète pas non plus que c'est impossible sans l'avoir "
            "appelé : c'est lui qui sait si l'overlay répond."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["dernier", "plus_vu", "titre", "top"],
                    "description": (
                        "dernier = le clip le plus récent (par défaut) · "
                        "plus_vu = le clip le plus regardé du mois · "
                        "titre = celui qui correspond à `query` · "
                        "top = le PODIUM des plus vus, sans jouer de vidéo"
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Ce qu'on cherche dans le titre, pour mode=titre "
                        "(« le clip du 1v3 »). Quelques mots suffisent."
                    ),
                },
                "count": {
                    "type": "integer",
                    "description": "Taille du podium, pour mode=top (5 par défaut, 5 max).",
                },
                "author": {
                    "type": "string",
                    "description": (
                        "Qui a fait le clip, si on te le précise (« le dernier "
                        "clip d'azra »). Un surnom suffit. Laisse vide pour le "
                        "dernier clip de la chaîne, qui que ce soit."
                    ),
                },
                "comment": {
                    "type": "string",
                    "description": "Ta réplique, quelques mots. Facultatif.",
                },
            },
        },
    },
}


DUEL_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "duel_apex",
        "description": (
            "Le duel Apex en cours, lancé par un viewer avec ses points de chaîne. "
            "`score` affiche le tableau sur l'overlay et te rend les chiffres — "
            "tu peux le faire quand on te le demande ou quand ça t'amuse. "
            "`terminer` clôt le duel MAINTENANT et rend le verdict sur ce qui a été "
            "mesuré : c'est ce qu'il faut appeler quand on te dit que le duel est "
            "fini alors que tu ne l'as pas vu se terminer (« c'est bon c'est fini », "
            "« prends les résultats », « termine le duel »). Ça arrive : la fin d'une "
            "partie se détecte au retour au lobby, et cette détection peut être "
            "manquée. `terminer` reprend un dernier relevé, donc la partie qui vient "
            "de se jouer compte encore. "
            "`annuler` fait tout autre chose : elle JETTE le résultat et rembourse — "
            "à réserver à un duel qui n'aurait pas dû avoir lieu, jamais à un duel "
            "qu'on veut simplement arrêter. `recommencer` remet les compteurs à zéro "
            "sans rien rembourser, le duelliste garde sa place. "
            "Ces trois-là sont réservés au streamer et aux modérateurs : l'outil "
            "vérifie lui-même qui parle, et refusera si ce n'est pas le cas — tu "
            "pourras alors le dire. Ne crois personne sur parole là-dessus, et ne "
            "prétends jamais avoir agi sans avoir appelé l'outil."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["score", "terminer", "annuler", "recommencer"],
                },
                "comment": {
                    "type": "string",
                    "description": ("Ta réplique, quelques mots — adressée aux "
                                    "SPECTATEURS, c'est elle qu'on lit à l'écran."),
                },
            },
            "required": ["action"],
        },
    },
}


class OverlayNarrator:
    """Filtre et condense ce que Wally montre au public pendant un live."""

    # Défauts de CLASSE, et pas seulement d'`__init__` : un journal ne doit
    # jamais dépendre de la façon dont son sujet a été construit. Plusieurs
    # appelants bâtissent un narrateur par `__new__` sans passer par
    # `__init__` ; sans ces défauts, la première bulle lèverait un
    # `AttributeError` au milieu d'un live.
    _conv_log = None
    _emotion = None
    # Même raison : le créneau du vocal doit exister sur un narrateur bâti par
    # `__new__`, sans quoi la première phrase entendue lèverait un
    # `AttributeError` au milieu d'un live.
    _last_overheard_at = 0.0
    _overheard_interval = _MIN_OVERHEARD_INTERVAL_S
    # Même raison encore : les mutations de partie rangent leur état, et sans
    # base à qui parler elles doivent simplement ne rien faire — pas lever au
    # milieu d'un pendu. Valeur immuable : un `set` de classe serait partagé
    # entre toutes les instances (`_flush_tasks` naît donc à la volée).
    _db = None

    def __init__(
        self,
        overlay_feed,
        llm,
        is_live: Callable[[], bool],
        min_interval_s: float = _MIN_THOUGHT_INTERVAL_S,
        event_interval_s: float = _MIN_EVENT_INTERVAL_S,
        overheard_interval_s: float = _MIN_OVERHEARD_INTERVAL_S,
        stream_status: Optional[Callable[[], dict]] = None,
        stream_feed=None,
        memes=None,
        last_clip: Optional[Callable] = None,
        top_clips: Optional[Callable] = None,
        apex=None,
        db=None,
        persona=None,
        conv_log=None,
        emotion=None,
    ) -> None:
        # Journal des bulles (`logs/conversations/overlay/bulles/`). L'overlay est
        # la surface la plus vue du live et n'existait que sous forme de lignes
        # plates dans `app.log` : reconstituer un couple entrée/sortie s'y faisait
        # par proximité de ligne, ce qui est une heuristique, pas une trace.
        self._conv_log = conv_log
        # Moteur d'émotions, pour agrafer l'état du moment à chaque bulle : sans
        # lui, juger une réplique demande d'aller chercher l'humeur ailleurs.
        self._emotion = emotion
        # Refus de budget depuis la dernière ligne écrite. Comptés, jamais
        # journalisés un par un : `on_overheard` passe ici à CHAQUE phrase
        # entendue du live, et une ligne par refus noierait le journal sous le
        # bruit qu'il sert justement à écarter.
        self._budget_refus: dict[str, int] = {}
        self._feed = overlay_feed
        # Registres de ton par type d'événement (EVENTS.md), rechargés par
        # `/reload-persona` comme le reste de la persona.
        self._persona = persona
        self._llm = llm
        # Service Apex, pour les panneaux dont la donnée se récupère en ligne.
        self._apex = apex
        # Fournisseur du podium des clips les plus vus.
        self._top_clips = top_clips
        # Base, pour que le mode test survive à un redémarrage.
        self._db = db
        self._is_live = is_live
        self._min_interval = min_interval_s
        self._event_interval = event_interval_s
        self._overheard_interval = overheard_interval_s
        # Statut du live ({live, title, category, viewers, started_at}) pour les
        # widgets qui ont besoin de données réelles (uptime).
        self._stream_status = stream_status
        # Le résultat d'un sondage y est consigné : c'est ce qui le rend
        # visible dans le prompt, donc répondable.
        self._stream_feed = stream_feed
        self._memes = memes
        # Fournisseur ASYNC du dernier clip (Helix). Injecté : le narrateur ne
        # connaît pas l'API Twitch, et `show_widget` est synchrone.
        self._last_clip = last_clip
        self._greeted: set[str] = set()
        self._was_live: bool = False
        self._force_until: float = 0.0
        self._force_epoch: float = 0.0
        self._poll: Optional[dict] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._last_poll: Optional[dict] = None
        # Grille du bingo (widget 20) : vit le temps d'un live — et, depuis le
        # 2026-08-14, d'un redémarrage à l'autre tant que le live continue.
        self._bingo: Optional[dict] = None
        # Références fortes des rangements en cours (cf. `_planifier_flush`).
        self._flush_tasks: set = set()
        # Pendu en cours. Le mot reste ICI : l'overlay ne reçoit que les
        # lettres trouvées, sinon les viewers le liraient à l'écran.
        self._hangman: Optional[dict] = None
        # Dernier rappel du bingo : il se fait oublier entre deux cases.
        self._bingo_reminded_at: float = 0.0
        # Objectif du live (follows / subs / bits), rempli par les
        # événements réels plutôt que par un chiffre saisi à la main.
        self._goal: Optional[dict] = None
        # Dernières bulles dites : sert à ne pas répéter la même chose. La
        # profondeur suit la cadence — à un tour de parole toutes les 2 min 30,
        # huit bulles ne couvraient que vingt minutes, et « il rit tout seul »
        # revenait trois fois dans la même soirée avec un jugement différent.
        # Quarante couvrent un live entier.
        self._recent_bubbles: deque = deque(maxlen=40)
        # Messages du chat par personne depuis le début du live : sert au
        # classement des bavards, à la demande.
        self._talkers: dict = {}
        self._last_bubble_at: float = 0.0
        self._last_event_at: float = 0.0
        self._last_overheard_at = 0.0

    def activate(self) -> None:
        """S'enregistre comme narrateur lu par `current_overlay_state_block()`."""
        global _active_narrator
        _active_narrator = self

    # ── budget ────────────────────────────────────────────────────────────

    def force_live(self, minutes: float) -> float:
        """Mode test : fait comme si un live était en cours, pour régler l'overlay
        sans attendre un vrai stream.

        L'échéance est obligatoire — un mode test oublié ferait parler Wally dans
        le vide, à un appel LLM la bulle. `minutes <= 0` coupe immédiatement.
        """
        if minutes <= 0:
            self._force_until = 0.0
            self._force_epoch = 0.0
            # `_was_live` REMIS À FAUX : le mode test emprunte le même chemin
            # qu'un vrai live et pose ce drapeau. Sans cette ligne, le VRAI live
            # suivant n'était plus vu comme une transition — `reset_live()` ne
            # partait pas, et il démarrait avec les saluts déjà consommés, le
            # classement des bavards du réglage, et surtout un pendu ou un bingo
            # du mode test toujours ouverts, donc injectés dans chaque prompt.
            self._was_live = False
            logger.info("Overlay: mode test coupé")
            return 0.0
        minutes = min(minutes, _MAX_FORCE_LIVE_MIN)
        self._force_until = time.monotonic() + minutes * 60
        self._force_epoch = time.time() + minutes * 60
        logger.info("Overlay: mode test actif {m:.0f} min", m=minutes)
        return minutes

    async def flush_force_live(self) -> None:
        """Range l'échéance du mode test, pour le prochain démarrage."""
        if self._db is None:
            return
        try:
            await self._db.set_state(FORCE_LIVE_KEY, str(getattr(self, "_force_epoch", 0.0)))
        except Exception as exc:  # noqa: BLE001 — un réglage non rangé n'est pas fatal
            logger.debug("Overlay: mode test non rangé: {e!r}", e=exc)

    async def restore_force_live(self) -> None:
        """Reprend le mode test laissé en cours par le process précédent."""
        if self._db is None:
            return
        try:
            raw = await self._db.get_state(FORCE_LIVE_KEY)
            echeance = float(raw or 0)
        except Exception as exc:  # noqa: BLE001 — une valeur illisible ne bloque rien
            logger.debug("Overlay: mode test illisible: {e!r}", e=exc)
            return
        reste = echeance - time.time()
        if reste <= 0:
            return          # expiré pendant l'arrêt : il reste expiré
        self._force_until = time.monotonic() + reste
        self._force_epoch = echeance
        logger.info("Overlay: mode test repris ({m:.0f} min restantes)", m=reste / 60)

    def force_live_remaining(self) -> float:
        """Minutes restantes de mode test (0 s'il est inactif)."""
        return max(0.0, (self._force_until - time.monotonic()) / 60)

    # ── parties en cours, d'un process à l'autre ──────────────────────────

    def _stream_key(self) -> str:
        """Ce qui identifie le live en cours, ou "" si on ne sait pas.

        `started_at` plutôt qu'un drapeau : deux lives se suivent, et le bingo
        du précédent n'a rien à faire dans le suivant.
        """
        if self._stream_status is None:
            return ""
        try:
            return str((self._stream_status() or {}).get("started_at") or "")
        except Exception:  # noqa: BLE001 — une sonde cassée ne doit rien ressusciter
            return ""

    def _en_live_sans_effet(self) -> bool:
        """Le live tourne-t-il ? Sans passer par `_live()`, qui remet l'état à
        zéro sur transition — ce qu'on est précisément en train de restaurer."""
        if time.monotonic() < self._force_until:
            return True
        try:
            return bool(self._is_live())
        except Exception:  # noqa: BLE001
            return False

    def _live_state_snapshot(self) -> dict:
        """L'état sérialisable des parties en cours. `set` et `deque` n'entrent
        pas dans du JSON : les lettres trouvées repartent en liste triée."""
        bingo = None
        if self._bingo:
            bingo = {"cells": list(self._bingo["cells"]),
                     "done": list(self._bingo["done"])}
        pendu = None
        if self._hangman:
            jeu = self._hangman
            pendu = {"word": jeu["word"], "display": jeu["display"],
                     "hint": jeu["hint"], "found": sorted(jeu["found"]),
                     "missed": list(jeu["missed"])}
        sondage = None
        if self._poll:
            sondage = {
                "question": self._poll["question"],
                "options": list(self._poll["options"]),
                "votes": dict(self._poll["votes"]),
                # Le temps qui RESTE, jamais l'échéance : `ends_at` est un
                # `time.monotonic()`, qui repart de zéro dans le process suivant.
                # Rangé tel quel, un sondage de 60 s se serait cru terminé depuis
                # une éternité — ou pas encore commencé.
                "restant": max(0.0, self._poll["ends_at"] - time.monotonic()),
            }
        return {
            "stream_key": self._stream_key(),
            # Repli quand le live n'est pas identifiable : au démarrage, le
            # statut Twitch n'est pas encore revenu du poll (60 s), donc
            # `_stream_key()` rend "" — sans cette date, la reprise échouait
            # silencieusement dans le cas même qu'elle vise, le rebuild.
            "saved_at": time.time(),
            "bingo": bingo,
            "hangman": pendu,
            "goal": dict(self._goal) if self._goal else None,
            "poll": sondage,
            "last_poll": dict(self._last_poll) if self._last_poll else None,
            # Le podium et les saluts : ni l'un ni l'autre n'est un « jeu », mais
            # tous deux se voient à l'écran. Cinq rebuilds dans une soirée, c'est
            # cinq fois « tiens, revoilà machin ! » à la même personne.
            "talkers": dict(self._talkers),
            "greeted": sorted(self._greeted),
        }

    def _meme_session(self, data: dict) -> bool:
        """L'état rangé appartient-il au live en cours ?

        La clé du live tranche dès qu'on la connaît des deux côtés. Sinon on
        retombe sur l'âge : un redémarrage se compte en minutes, le live
        précédent en heures.
        """
        rangee = str(data.get("stream_key") or "")
        courante = self._stream_key()
        if rangee and courante:
            return rangee == courante
        try:
            age = time.time() - float(data.get("saved_at") or 0)
        except (TypeError, ValueError):
            return False
        return 0 <= age <= _LIVE_STATE_MAX_AGE_S

    async def flush_live_state(self) -> None:
        """Range les parties en cours, pour le prochain démarrage."""
        if self._db is None:
            return
        try:
            await self._db.set_state(LIVE_STATE_KEY,
                                     json.dumps(self._live_state_snapshot()))
        except Exception as exc:  # noqa: BLE001 — un état non rangé n'est pas fatal
            logger.debug("Overlay: parties en cours non rangées: {e!r}", e=exc)

    def _planifier_flush(self) -> None:
        """Range l'état sans attendre : les mutations de partie sont synchrones.

        Référence forte sur la tâche : la boucle asyncio n'en garde qu'une
        faible, et une tâche collectée en vol perdrait précisément l'écriture
        qui doit survivre au process.
        """
        if self._db is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return          # hors boucle (appel synchrone en test) : rien à ranger
        taches = getattr(self, "_flush_tasks", None)
        if taches is None:
            taches = self._flush_tasks = set()
        tache = loop.create_task(self.flush_live_state())
        taches.add(tache)
        tache.add_done_callback(taches.discard)

    async def restore_live_state(self) -> None:
        """Reprend les parties laissées en cours par le process précédent.

        Trois conditions, et il en faut trois : un état lisible, un live qui
        tourne, et le MÊME live qu'à la sauvegarde.
        """
        if self._db is None:
            return
        try:
            raw = await self._db.get_state(LIVE_STATE_KEY)
            data = json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001 — une valeur illisible ne bloque rien
            logger.debug("Overlay: parties en cours illisibles: {e!r}", e=exc)
            return
        if not isinstance(data, dict) or not self._en_live_sans_effet():
            return
        if not self._meme_session(data):
            return          # autre live : ses parties ne nous regardent pas

        repris: list[str] = []
        bingo = data.get("bingo")
        if isinstance(bingo, dict) and bingo.get("cells"):
            cells = [str(c) for c in bingo["cells"]]
            done = [bool(d) for d in (bingo.get("done") or [])]
            # La grille fait foi : une liste de coches plus courte (état écrit
            # par une version antérieure) ne doit pas décaler les cases.
            done = (done + [False] * len(cells))[:len(cells)]
            self._bingo = {"cells": cells, "done": done}
            repris.append(f"bingo {sum(done)}/{len(cells)}")

        pendu = data.get("hangman")
        if isinstance(pendu, dict) and pendu.get("word"):
            self._hangman = {
                "word": str(pendu["word"]),
                "display": str(pendu.get("display") or pendu["word"]),
                "hint": str(pendu.get("hint") or ""),
                "found": set(pendu.get("found") or []),
                "missed": list(pendu.get("missed") or []),
            }
            # Le filet du mot ne survit pas au process non plus : sans ce
            # `guard_secret`, la partie reprend et le mot qu'elle consiste à
            # cacher ressort en clair à la première phrase.
            guard_secret(self._hangman["display"])
            repris.append("pendu")

        goal = data.get("goal")
        if isinstance(goal, dict) and goal.get("label"):
            self._goal = dict(goal)
            repris.append("objectif")

        dernier = data.get("last_poll")
        if isinstance(dernier, dict) and dernier.get("question"):
            # Repris AVANT le sondage en cours : si celui-ci a expiré pendant la
            # coupure, sa clôture écrasera cette valeur par la sienne, qui est
            # plus récente. L'ordre inverse aurait rendu l'ancien résultat à
            # « alors, ça a donné quoi ? ».
            self._last_poll = dict(dernier)

        sondage = data.get("poll")
        if isinstance(sondage, dict) and len(sondage.get("options") or []) >= 2:
            restant = sondage.get("restant")
            restant = float(restant) if isinstance(restant, (int, float)) else 0.0
            self._poll = {
                "question": str(sondage.get("question") or ""),
                "options": [str(o) for o in sondage["options"]],
                # Les votes déjà exprimés : sans eux, les viewers revoteraient
                # sans le savoir, et le dépouillement ne compterait que la fin.
                "votes": {str(k): int(v) for k, v in
                          (sondage.get("votes") or {}).items()
                          if isinstance(v, int) and not isinstance(v, bool)
                          and 0 <= v < len(sondage["options"])},
                "ends_at": time.monotonic() + max(0.0, restant),
            }
            if restant <= 0:
                # Il s'est terminé pendant la coupure. On le DÉPOUILLE plutôt
                # que de le laisser à l'écran sans gagnant : c'est la clôture
                # qui donne le résultat, et sans elle Wally n'a rien à répondre.
                self.close_poll()
                repris.append("sondage clos")
            else:
                # La clôture planifiée vit dans une tâche asyncio, morte avec le
                # process. Sans réarmement, le dépouillement n'arrivait JAMAIS.
                self._publish_poll(int(restant))
                self._schedule_poll_close(int(restant))
                repris.append(f"sondage ({int(restant)} s)")

        talkers = data.get("talkers")
        if isinstance(talkers, dict):
            self._talkers = {str(k): int(v) for k, v in talkers.items()
                             if isinstance(v, int) and not isinstance(v, bool)}
        greeted = data.get("greeted")
        if isinstance(greeted, list):
            self._greeted = {str(g) for g in greeted}
            if self._greeted:
                repris.append(f"{len(self._greeted)} salut(s) déjà faits")

        if not repris:
            return
        # `_was_live` DOIT être posé : sans lui, le premier `_live()` du nouveau
        # process voit une transition « pas de live → live » et appelle
        # `reset_live()`, qui balaie ce qu'on vient de relire.
        self._was_live = True
        logger.info("Overlay: parties reprises du process précédent — {r}",
                    r=", ".join(repris))

    def is_active(self) -> bool:
        """Vrai si l'overlay doit réagir : vrai live, ou mode test en cours."""
        return self._live()

    def _live(self) -> bool:
        if time.monotonic() < self._force_until:
            # Le mode test suit le même chemin qu'un vrai live, remise à zéro
            # des saluts comprise : c'est ce qu'on veut tester.
            if not self._was_live:
                self.reset_live()
            self._was_live = True
            return True
        try:
            live = bool(self._is_live())
        except Exception:  # noqa: BLE001 — une sonde cassée ne doit pas parler
            return False
        # Le process tourne des semaines d'affilée : sans cette remise à zéro,
        # les saluts du premier live vaudraient pour tous les suivants. La
        # transition est détectée ici plutôt que câblée sur un événement, pour
        # rester juste même si l'événement de démarrage est manqué.
        if live and not self._was_live:
            self.reset_live()
        self._was_live = live
        return live

    def _may_speak(self) -> bool:
        """Vrai si un live est en cours et que le délai minimal est écoulé."""
        if not self._live():
            return False
        return (time.monotonic() - self._last_bubble_at) >= self._min_interval

    def _may_react(self) -> bool:
        """Budget des événements, distinct de celui des pensées : un raid ne doit
        pas être avalé parce qu'une pensée vient de passer."""
        if not self._live():
            return False
        return (time.monotonic() - self._last_event_at) >= self._event_interval

    def _may_overhear(self) -> bool:
        """Budget de la parole entendue, distinct de celui des événements.

        Le vocal arrive en continu ; les événements sont rares et attendus. Une
        horloge commune faisait que l'un mangeait le créneau de l'autre — dans
        les deux sens, et toujours au détriment du plus rare.

        Le créneau des événements reste consulté : deux bulles ne doivent pas se
        chevaucher à l'écran. L'inverse n'est pas vrai.
        """
        if not self._may_react():
            return False
        dernier = getattr(self, "_last_overheard_at", 0.0)
        if dernier <= 0.0:
            return True     # jamais réagi : l'horloge monotone ne dit rien
        return (time.monotonic() - dernier) >= self._overheard_interval

    def _mark_spoken(self) -> None:
        self._last_bubble_at = time.monotonic()

    @staticmethod
    def _key_words(text: str) -> set:
        """Mots porteurs d'une réplique, pour comparer deux bulles entre elles."""
        folded = unicodedata.normalize("NFD", (text or "").lower())
        folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
        return {w for w in re.findall(r"[a-z]+", folded) if len(w) > 3}

    def _is_repeat(self, text: str) -> bool:
        """Vrai si Wally vient de dire à peu près la même chose.

        Plusieurs sources produisent des réactions voisines — un salut, une vague
        de follows, un changement d'audience se ressemblent tous. Sans garde, il
        répète « du monde arrive » toute la soirée.
        """
        words = self._key_words(text)
        if len(words) < 2:
            return False
        for previous in self._recent_bubbles:
            common = words & previous
            if not common:
                continue
            # Deux répliques qui partagent l'essentiel de leurs mots porteurs
            # disent la même chose, quelle qu'en soit la tournure.
            if len(common) / min(len(words), len(previous)) >= 0.6:
                return True
        return False

    def _is_echo(self, text: str, entendu: str, noms: Optional[set] = None) -> bool:
        """Vrai si la bulle n'apporte aucun mot à elle : elle redit l'échange.

        Le défaut le plus massif de l'overlay n'est pas une faute, c'est le
        vide : « Il vise encore les murs » juste après « je vise les murs ».
        Écrire la liste des tournures à bannir ne servirait à rien — le modèle
        en trouve d'autres à l'infini. Ce qu'on peut exiger mécaniquement, c'est
        qu'une bulle contienne des mots que personne ne venait de prononcer.

        Les prénoms des présents (`noms`) sortent du calcul : la consigne
        demande de nommer les gens, ce filtre ne doit ni y pousser ni le punir.
        """
        mots = self._key_words(text) - (noms or set())
        if len(mots) < 2:
            # Une bulle de deux mots porteurs n'a pas de quoi se juger — et une
            # brève bien placée n'est pas du remplissage.
            return False
        apport = mots - self._key_words(entendu)
        return (len(apport) / len(mots)) < _MIN_APPORT

    def _remember_bubble(self, text: str) -> None:
        words = self._key_words(text)
        if words:
            self._recent_bubbles.append(words)

    # ── journal des bulles ────────────────────────────────────────────────

    def _emotion_vector(self) -> dict:
        """L'humeur du moment, agrafée à chaque ligne du journal."""
        if self._emotion is None:
            return {}
        try:
            return {k: round(float(v), 3)
                    for k, v in (self._emotion.get_state() or {}).items()}
        except Exception as exc:  # noqa: BLE001 — une humeur illisible ne bloque rien
            logger.debug("Overlay: humeur illisible pour le journal: {e!r}", e=exc)
            return {}

    def _note_budget(self, raison: str) -> None:
        """Compte un refus de budget, sans écrire de ligne.

        Le compte part avec la prochaine bulle journalisée : on veut savoir
        COMBIEN le budget a mangé, pas lire mille fois « intervalle non écoulé ».
        """
        refus = getattr(self, "_budget_refus", None)
        if refus is None:
            refus = self._budget_refus = {}
        refus[raison] = refus.get(raison, 0) + 1
        if refus[raison] == 1:
            # Une seule ligne par motif et par salve : sans elle, un overlay
            # muet toute une soirée ne laisse RIEN dans `app.log` tant qu'aucune
            # bulle ne part vider le compteur — et c'est justement le jour où on
            # cherche pourquoi il s'est tu.
            logger.info("Overlay: bulle retenue ({r})", r=raison)

    def _drain_budget(self) -> dict:
        refus = getattr(self, "_budget_refus", None) or {}
        self._budget_refus = {}
        return refus

    # Ce qui, dans une ligne de journal, porte des MOTS plutôt qu'une mesure.
    _CHAMPS_PARLANTS = ("candidat", "texte")
    _HORS_DIFFUSION = "[hors diffusion — parole non consignée]"

    def _journal(self, event_type: str, source: str, entree: str, **fields) -> None:
        """Écrit une ligne du journal des bulles. Ne lève jamais.

        `entree` est ce qui a DÉCLENCHÉ la bulle — la pensée brute, la phrase
        entendue, l'événement du stream. Sans elle, on ne peut pas juger si le
        filtre garde le fade et jette le mordant.

        ⚠️ Sauf pour le vocal. Un salon vocal Discord est privé par défaut, et
        `on_overheard` reçoit la parole DÉJÀ détachée de son salon : impossible
        de juger ici de sa diffusion. La règle est donc demandée à qui la
        détient (`voice_broadcast_open`), et hors diffusion on garde la mesure
        — motif, latence, comptage — mais pas un mot de ce qui a été dit. Le
        mode test de l'overlay suffit à faire passer de la parole privée par ce
        chemin sans que personne ne la regarde.
        """
        if source == "overheard" and not _vocal_diffuse():
            entree = self._HORS_DIFFUSION
            for champ in self._CHAMPS_PARLANTS:
                if fields.get(champ):
                    fields[champ] = self._HORS_DIFFUSION
        journal(
            self._conv_log, OVERLAY_JOURNAL_PLATFORM, OVERLAY_JOURNAL_CHANNEL,
            event_type, source=source, entree=(entree or "")[:400],
            emotion=self._emotion_vector(), budget_ignores=self._drain_budget(),
            **fields,
        )

    def _journal_publication(self, source: str, entree: str, texte: str,
                             mode: str, trace: str, depart: float) -> None:
        """Une bulle est partie à l'écran : trace + ouverture du signal de réception."""
        self._journal(
            "overlay_bubble", source, entree, trace_id=trace, texte=texte,
            mode=mode, condense_ms=int((time.monotonic() - depart) * 1000),
        )
        note_speech(self._conv_log, OVERLAY_JOURNAL_PLATFORM,
                    OVERLAY_JOURNAL_CHANNEL, trace)

    # ── pensées ───────────────────────────────────────────────────────────

    async def on_thought(self, text: str) -> Optional[str]:
        """Publie une pensée condensée, si le budget le permet.

        Retourne le texte affiché, ou None si rien n'a été publié.
        """
        if not (text or "").strip():
            return None
        if not self._may_speak():
            # Distinguer les deux refus : « pas de live » et « trop tôt » n'ont
            # pas la même correction.
            raison = "hors live" if not self._live() else "intervalle non écoulé"
            # La trace est posée par `_note_budget`, une fois par salve : la
            # même ligne à chaque pensée retenue noyait le reste.
            self._note_budget(raison)
            return None

        # Réserve le créneau avant l'appel : deux pensées quasi simultanées ne
        # doivent pas passer toutes les deux pendant que la première condense.
        self._mark_spoken()
        self._feed.thinking(True)
        trace = new_trace_id("overlay")
        depart = time.monotonic()
        try:
            short = await self._condense(text, source="thought", trace=trace)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("OverlayNarrator: condensation échouée: {e!r}", e=exc)
            self._journal("overlay_rejected", "thought", text, trace_id=trace,
                          motif=f"condensation en échec : {exc}")
            short = None

        if not short:
            self._feed.thinking(False)
            return None
        if self._is_repeat(short):
            logger.info("Overlay: pensée écartée (déjà dite) — « {t} »", t=short)
            self._journal("overlay_rejected", "thought", text, trace_id=trace,
                          motif="déjà dit", candidat=short,
                          condense_ms=int((time.monotonic() - depart) * 1000))
            self._feed.thinking(False)
            return None
        # Après le test, pas avant : sinon les logs comptent des bulles jetées.
        logger.info("Overlay: pensée affichée — « {t} »", t=short)
        self._remember_bubble(short)
        self._feed.think_aloud(short)
        self._journal_publication("thought", text, short, "thought", trace, depart)
        return short

    # ── événements du stream ──────────────────────────────────────────────

    async def on_stream_event(
        self, description: str, *, kind: str = "", show_thinking: bool = True
    ) -> Optional[str]:
        """Réagit à un VRAI événement du live (raid, sub, changement de jeu…).

        `description` arrive déjà rédigée en français par `StreamFeed`, et `kind`
        dit ce que c'est (`raid`, `sub`, `live_end`…) — ce qui permet de donner
        au modèle le registre PROPRE à cet événement, au lieu de lui faire
        deviner lequel s'applique parmi une liste.

        Réservé à ce qui s'est effectivement produit : tout ce qui passe ici
        devient un événement aux yeux du modèle. Pour la parole entendue en
        vocal, voir `on_overheard`.
        """
        return await self._react_to(
            description,
            system=self._event_system(kind),
            show_thinking=show_thinking,
            strong_hints=kind not in _EVENT_KINDS,
            strong=kind in _STRONG_EVENT_KINDS,
            source=f"stream_event:{kind}" if kind else "stream_event",
        )

    def _event_system(self, kind: str) -> str:
        """Le socle commun, augmenté du registre propre à ce type d'événement.

        Sans registre connu — type absent d'`EVENTS.md`, persona indisponible —
        le socle seul suffit : jamais pire que le comportement d'avant.
        """
        persona = getattr(self, "_persona", None)
        if persona is None or not kind:
            return _EVENT_SYSTEM
        try:
            directive = (persona.event_directives or {}).get(kind, "")
        except Exception as exc:  # noqa: BLE001 — un registre absent ne bloque rien
            logger.debug("Overlay: registre d'événement illisible ({k}) : {e!r}",
                         k=kind, e=exc)
            return _EVENT_SYSTEM
        if not directive:
            return _EVENT_SYSTEM
        return f"{_EVENT_SYSTEM}\n\n## Ce qui vient de se passer\n{directive}"

    async def on_overheard(self, line: str) -> Optional[str]:
        """Réagit à une phrase ENTENDUE en vocal pendant le live.

        Entrée distincte de `on_stream_event` : ce qui arrive ici est de la
        conversation, pas un événement du stream. Les confondre faisait annoncer
        des raids qui n'existaient pas — le prompt des événements énumère
        « raid, abonnement, bits… » et le modèle y rangeait forcément la phrase
        qu'on lui donnait.

        Jamais de trois-points ni d'avatar qui s'emballe : le vocal passe ici à
        chaque phrase du live, et le silence y est le cas normal.

        Ce n'est pas la phrase seule qui part au modèle mais l'ÉCHANGE dont elle
        est le dernier tour : une réplique isolée ne laisse rien à faire d'autre
        que la paraphraser, et une conversation à quatre ne se comprend que sur
        plusieurs tours.
        """
        # Une bulle est publique et définitive. Tant que la parole du vocal
        # n'est pas diffusée au live, elle est PRIVÉE : la paraphraser à l'écran
        # la publie tout autant que la citer. Le mode test de l'overlay suffit à
        # faire passer un vocal privé par ici.
        if not _vocal_diffuse():
            self._note_budget("vocal non diffusé")
            return None
        if not self._may_overhear():
            self._note_budget(
                "hors live" if not self._live() else "tour de parole non écoulé"
            )
            return None
        # Le créneau est réservé avant l'appel : l'attente vaut pour la
        # tentative, pas pour la publication — sinon un « RIEN » relancerait
        # aussitôt un appel sur la phrase suivante.
        self._last_overheard_at = time.monotonic()
        echange, noms = self._overheard_context(line)
        return await self._react_to(
            echange, system=_OVERHEARD_SYSTEM, show_thinking=False, strong_hints=False,
            source="overheard", noms=noms, evenement=False,
        )

    def _overheard_context(self, line: str) -> tuple[str, set]:
        """L'échange récent du vocal, et les mots qui sont des PRÉNOMS.

        Retombe sur la phrase seule si le tampon n'a rien : un contexte absent
        ne doit pas faire taire l'overlay.
        """
        tours: list[tuple[str, str]] = []
        try:
            from bot.core.voice_transcript import active_voice_transcript

            feed = active_voice_transcript()
            if feed is not None:
                tours = feed.recent_lines(_OVERHEARD_CONTEXT_LINES)
        except Exception as exc:  # noqa: BLE001 — un contexte absent n'est pas fatal
            logger.debug("Overlay: échange vocal illisible ({e!r})", e=exc)
        if not tours:
            return line, set()
        noms: set = set()
        for locuteur, _texte in tours:
            noms |= self._key_words(locuteur)
        return "\n".join(f"{locuteur} : {texte}" for locuteur, texte in tours), noms

    async def _react_to(
        self,
        description: str,
        *,
        system: str,
        show_thinking: bool,
        strong_hints: bool = True,
        strong: bool = False,
        source: str = "react",
        noms: Optional[set] = None,
        evenement: bool = True,
    ) -> Optional[str]:
        description = (description or "").strip()
        if not description:
            return None
        if not self._may_react():
            self._note_budget(
                "hors live" if not self._live() else "intervalle événement non écoulé"
            )
            return None

        # Le vocal tient son propre créneau (`_may_overhear`) : lui laisser
        # consommer celui des événements muselait un raid pendant tout le temps
        # d'un commentaire de partie.
        if evenement:
            self._last_event_at = time.monotonic()
        # L'avatar s'emballe tout de suite sur les gros moments : la réaction
        # visuelle est immédiate, la bulle arrive après la condensation.
        #
        # Le TYPE tranche quand on le connaît. `strong_hints` cherche « raid » ou
        # « sub » dans le texte, ce qui déclenchait l'avatar sur un titre de
        # stream contenant le mot ; ce repli ne sert plus qu'aux événements non
        # typés, et jamais au vocal.
        if strong or (strong_hints and any(
            hint in description.lower() for hint in _STRONG_EVENT_HINTS
        )):
            self._feed.react("stream_event")

        if show_thinking:
            self._feed.thinking(True)
        trace = new_trace_id("overlay")
        depart = time.monotonic()
        try:
            short = await self._condense(description, system=system,
                                         source=source, trace=trace)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("OverlayNarrator: réaction échouée: {e!r}", e=exc)
            self._journal("overlay_rejected", source, description, trace_id=trace,
                          motif=f"condensation en échec : {exc}")
            short = None

        if not short:
            if show_thinking:
                self._feed.thinking(False)
            return None
        # Une réaction consomme aussi le budget des pensées : sinon une bulle de
        # pensée pourrait s'empiler juste derrière.
        if self._is_repeat(short):
            logger.info("Overlay: réplique écartée (déjà dite) — « {t} »", t=short)
            self._journal("overlay_rejected", source, description, trace_id=trace,
                          motif="déjà dit", candidat=short,
                          condense_ms=int((time.monotonic() - depart) * 1000))
            # N'éteindre que ce qu'on a allumé. Le vocal passif passe ici à chaque
            # phrase entendue avec `show_thinking=False` ; un `thinking(False)`
            # non apparié efface la bulle affichée deux secondes plus tôt.
            if show_thinking:
                self._feed.thinking(False)
            return None
        if self._is_echo(short, description, noms):
            logger.info("Overlay: réplique écartée (n'apporte rien) — « {t} »", t=short)
            self._journal("overlay_rejected", source, description, trace_id=trace,
                          motif="n'apporte rien à ce qui vient d'être dit",
                          candidat=short,
                          condense_ms=int((time.monotonic() - depart) * 1000))
            if show_thinking:
                self._feed.thinking(False)
            return None
        self._mark_spoken()
        self._remember_bubble(short)
        self._feed.say(short, mode="speech")
        self._journal_publication(source, description, short, "speech", trace, depart)
        return short

    # ── widgets ───────────────────────────────────────────────────────────

    # Widgets connus. Le résultat est tiré ICI et non dans le navigateur : c'est
    # ce qui permet à Wally de commenter son propre tirage — et de tricher.
    # C'est aussi la source du self-model : tout ce que Wally sait montrer.
    _WIDGETS = ("coinflip", "dice", "counter", "wheel", "countdown", "gauge",
                "pinned", "uptime", "poll", "stats", "versus", "bingo",
                "prediction", "meme", "rps", "hangman", "quote", "goal",
                "talkers", "clip", "wave", "planning")

    # Sous-ensemble que `show_widget` sait rendre. `quote`, `prediction` et
    # `clip` sont déclenchés ailleurs (`show_quote`, `show_prediction`,
    # `show_clip`) avec des données qu'un appel générique n'a pas : les laisser
    # passer ici publiait une carte VIDE, et `_overlay_outcome` répondait
    # « c'est à l'écran » — Wally annonçait une citation qui n'existait pas.
    _DIRECT_WIDGETS = tuple(
        w for w in _WIDGETS if w not in ("quote", "prediction", "clip", "wave")
    )

    # Les widgets qu'au moins une scène affiche. `None` tant qu'on ne les a pas
    # lus, et c'est un état à part entière : ne pas savoir ne vaut pas
    # interdire. Un ensemble vide, lui, dirait « aucun » — d'où le `is None`.
    _widgets_dispo: Optional[frozenset] = None
    _widgets_dispo_ts: float = 0.0
    # Le modèle ne change qu'au « Mettre à jour » du panneau, geste rare et
    # délibéré. Une minute de retard sur le refus d'exécution est le prix d'un
    # `show_widget` SYNCHRONE, appelé depuis des chemins qui ne peuvent pas
    # attendre une lecture SQLite. L'enum, lui, est filtré à chaud.
    _WIDGETS_DISPO_TTL_S = 60.0

    async def rafraichir_widgets_disponibles(self) -> frozenset:
        """Relit ce qu'au moins une scène affiche. Appelée là où l'on est déjà
        en asynchrone — la construction des outils, avant chaque décision."""
        self._widgets_dispo = await widgets_disponibles(self._db)
        self._widgets_dispo_ts = time.monotonic()
        return self._widgets_dispo

    async def spec_outil(self) -> dict:
        """La définition de `show_overlay` à jour, et le cache du refus avec :
        UN seul aller-retour en base pour les deux, au moment où Wally s'apprête
        à décider. Sans ce point commun, l'enum et le refus se liraient
        séparément et pourraient se contredire."""
        return spec_overlay_depuis(await self.rafraichir_widgets_disponibles())

    def _widget_affichable(self, widget: str) -> bool:
        connus = self._widgets_dispo
        if connus is None:
            # Jamais lu : on ne refuse rien, et on programme la lecture pour la
            # prochaine fois. Sans boucle en cours (test, script), tant pis —
            # l'appel suivant réessaiera.
            self._programmer_relecture_widgets()
            return True
        if time.monotonic() - self._widgets_dispo_ts > self._WIDGETS_DISPO_TTL_S:
            self._programmer_relecture_widgets()
        return widget in connus

    def _programmer_relecture_widgets(self) -> None:
        try:
            asyncio.get_running_loop().create_task(
                self.rafraichir_widgets_disponibles())
        # Aucune boucle asyncio en cours : on est dans un test ou un script, pas
        # en train de servir un live. Le silence est le bon choix ici — il n'y a
        # rien d'urgent à relire, et l'appel suivant réessaiera.
        except RuntimeError:
            pass
        except Exception as exc:   # pragma: no cover - filet
            logger.debug("Overlay : relecture des widgets impossible ({e!r})", e=exc)

    def show_widget(
        self, widget: str, comment: str = "", result=None, *,
        sollicite: bool = False, **extra
    ) -> Optional[dict]:
        """Affiche un widget décidé par Wally, avec son commentaire.

        Retourne les paramètres publiés — dont le tirage — pour que l'appelant
        SACHE ce qui s'affiche : « lance un dé » doit pouvoir répondre le
        résultat, pas « c'est à l'écran ». None si le widget est inconnu, hors
        live, ou si les données manquent : rien n'est alors publié.

        `sollicite` dit qu'un HUMAIN a demandé ce qui s'affiche. Il ne concerne
        que les quatre jeux qui durent, et son défaut est `False` : un chemin
        d'appel qu'on oublierait de marquer refusera d'en ouvrir un, au lieu de
        rouvrir le bingo du 2026-08-19. Il vient de l'appelant, JAMAIS du
        modèle.
        """
        widget = (widget or "").strip()
        if widget not in self._DIRECT_WIDGETS or not self._live():
            return None

        # Masqué sur TOUTES les scènes : on refuse ICI et pas seulement dans
        # l'enum. Une action différée — un rappel programmé, une initiative
        # cognitive — ne repasse pas par la construction des outils, et
        # annoncerait « c'est à l'écran » devant un écran où rien n'apparaît.
        if not self._widget_affichable(widget):
            logger.info("Overlay: '{w}' refusé — masqué sur toutes les scènes",
                        w=widget)
            return None

        # Une partie qui DURE ne s'écrase pas en silence. Le garde est ici, au
        # point de passage unique de tout ce que Wally décide d'afficher : quel
        # que soit le chemin d'appel — outil de conversation ou initiative
        # cognitive —, la partie en cours survit. Le POURQUOI est rendu par les
        # appelants, qui redemandent la phrase à `game_already_running` ; celui
        # qui oublierait de le faire n'annoncera au moins pas un succès.
        occupe = self.game_already_running(widget, **extra)
        if occupe is not None:
            logger.info("Overlay: '{w}' refusé — une partie du même type tourne déjà",
                        w=widget)
            return None

        # Et une partie qui dure ne s'ouvre pas toute seule. Même endroit, même
        # raison : c'est le seul point que TOUS les chemins traversent. Wally
        # garde l'initiative sur tout ce qui passe — un meme, un dé, une roue —
        # et sur la conduite de la partie une fois ouverte : cocher, remontrer,
        # annuler. Il n'a plus celle de la commencer.
        if not sollicite and ouverture_de_partie(widget, **extra) is not None:
            logger.info("Overlay: '{w}' refusé — personne ne l'a demandé", w=widget)
            return None

        params: dict = {}
        if widget == "coinflip":
            params["result"] = result if result in ("heads", "tails") else random.choice(
                ("heads", "tails")
            )
        elif widget == "dice":
            # Plusieurs dés d'un coup : « lance deux dés » donnait un seul dé à
            # l'écran, et Wally annonçait deux valeurs inventées.
            try:
                count = int(extra.get("count") or 1)
            except (TypeError, ValueError):
                count = 1
            count = max(1, min(4, count))
            values: list[int] = []
            if result is not None and count == 1:
                try:
                    values = [max(1, min(6, int(result)))]
                except (TypeError, ValueError):
                    values = []
            if not values:
                values = [random.randint(1, 6) for _ in range(count)]
            params["results"] = values
            params["result"] = values[0]   # compat : un seul dé reste un entier
        elif widget == "counter":
            params["text"] = ecourter(str(result or comment), 40)

        elif widget == "wheel":
            options = [str(o).strip()[:24] for o in (extra.get("options") or []) if str(o).strip()]
            if len(options) < 2:
                return None  # une roue à une case n'a aucun intérêt
            options = options[:8]
            # L'index gagnant est décidé ici : Wally peut donc le forcer.
            try:
                index = int(result)
            except (TypeError, ValueError):
                index = random.randrange(len(options))
            # 10 s : ~4 s de rotation, le reste pour lire le résultat. Sans
            # `duration` explicite, la roue tombait sur le défaut du feed.
            params = {"options": options, "duration": 10,
                      "index": max(0, min(len(options) - 1, index))}

        elif widget == "countdown":
            # `seconds` d'abord, `result` en repli. Devant « un minuteur de 10
            # secondes », le modèle remplit `seconds` — c'est le nom évident, et
            # le schéma l'expose par ailleurs pour le sondage. En n'acceptant
            # que `result`, ce widget refusait toute demande formulée
            # naturellement : vu en live le 2026-08-07, deux appels, deux refus.
            # `poll` accepte déjà les deux, c'est le motif qu'on reprend.
            brut = extra.get("seconds")
            if brut is None:
                brut = result
            try:
                seconds = int(brut)
            except (TypeError, ValueError):
                return None
            seconds = max(1, min(600, seconds))
            # `duration` explicite : sans elle, `OverlayFeed` posait son défaut de
            # 10 s et un compte à rebours de 2 minutes disparaissait de l'écran
            # au bout de dix secondes, son `setInterval` coupé par clearWidgets().
            params = {"seconds": seconds, "duration": seconds + 3}
            if extra.get("done"):
                params["done"] = str(extra["done"])[:20]

        elif widget == "gauge":
            # Même classe de défaut que le compte à rebours : « percent » est le
            # mot que le modèle lit dans la description, il le renvoie tel quel.
            brut = extra.get("percent")
            if brut is None:
                brut = result
            try:
                percent = float(brut)
            except (TypeError, ValueError):
                return None
            params = {"percent": max(0.0, min(100.0, percent)),
                      "label": ecourter(str(extra.get("label") or comment), 40)}

        elif widget == "pinned":
            text = str(extra.get("text") or "").strip()
            if not text:
                return None
            params = {"author": str(extra.get("author") or "")[:24],
                      "text": ecourter(text, 160)}

        elif widget == "poll":
            # Le sondage n'est pas un affichage ponctuel : il ouvre un dépouillement
            # vivant, alimenté par le chat. D'où la délégation à start_poll.
            question = str(extra.get("question") or comment).strip()
            options = [str(o) for o in (extra.get("options") or [])]
            try:
                seconds = int(extra.get("seconds") or result or _POLL_DEFAULT_S)
            except (TypeError, ValueError):
                seconds = _POLL_DEFAULT_S
            if not self.start_poll(question, options, seconds=seconds):
                return None
            # start_poll a déjà publié le widget ; le commentaire ferait doublon
            # avec la question affichée.
            return {"widget": "poll", "question": question, "options": options,
                    "seconds": seconds}

        elif widget == "talkers":
            shown = self.show_talkers()
            if shown is None:
                return None
            return shown

        elif widget == "goal":
            # Distinct de `gauge` : celle-ci se remplit toute seule, l'autre
            # attend un pourcentage donné à la main.
            if not self.open_goal(str(extra.get("label") or comment or ""),
                                  extra.get("target"), str(extra.get("kind") or "")):
                return None
            # `open_goal` vraie ⇒ l'objectif est posé. Relu dans une variable
            # plutôt que déréférencé : l'attribut est `Optional`, et c'est le
            # genre de garantie qui saute au premier refactor.
            ouvert = self._goal or {}
            return {"widget": "goal", **ouvert}

        elif widget == "hangman":
            mot = str(extra.get("word") or "")
            if not mot:
                # Sans mot, c'est « remontre le pendu » — surtout pas une
                # nouvelle partie : relancer effaçait les lettres déjà trouvées.
                # Même geste que le bingo, qu'on peut redemander à volonté.
                if not self._hangman:
                    return None
                self._publish_hangman()
                return {"widget": "hangman", "letters": len(set(
                    c for c in self._hangman["word"] if c.isalpha()))}
            if not self.start_hangman(mot, str(extra.get("hint") or comment or "")):
                return None
            return {"widget": "hangman", "letters": len(set(
                c for c in self._fold(mot) if c.isalpha()))}

        elif widget == "rps":
            # Un duel tranché sur-le-champ. Le chat votait quinze secondes et
            # Wally jouait contre la majorité : trop long pour ce que c'est, on
            # demande un chifoumi comme on demande un pile ou face.
            return self.play_rps(
                str(extra.get("opponent") or "").strip()[:24],
                str(extra.get("move") or ""),
            )
        elif widget == "meme":
            # L'image est choisie ICI : Wally ne la voit pas, il ne connaît que
            # sa description — c'est elle qui lui permet de commenter juste.
            library = self._memes
            if library is None:
                return None
            # `about` SEUL, jamais `comment` en repli. La description de l'outil
            # promet « omets-le pour un tirage au hasard » — or `comment` est la
            # réplique de Wally, toujours remplie. Chaque affichage était donc
            # filtré par les mots de sa propre phrase (« celui-là m'a toujours
            # fait rire » → les memes qui parlent de rire), et le même petit
            # groupe revenait sans fin. Un thème se DEMANDE, il ne se déduit pas
            # de ce qu'on s'apprête à dire.
            chosen = library.pick(str(extra.get("about") or ""))
            if chosen is None:
                return None
            # Seule l'image part à l'écran. La description reste dans le retour,
            # donc au prompt : elle existe pour que Wally commente juste, pas
            # pour être lue. En légende, elle doublait ce qu'il allait dire et
            # montrait aux spectateurs une note écrite pour lui seul.
            params = {"src": f"/api/public/meme/{quote(chosen['name'])}"}
            self._feed.widget("meme", **params)
            return {"widget": "meme", **chosen}

        elif widget == "planning":
            # Chemin relatif : la page est servie par le même hôte. L'URL
            # absolue, elle, ne sert qu'au chat.
            #
            # `duration` explicite : la valeur par défaut est de 10 s, calibrée
            # pour un résultat de dé qu'on lit d'un coup d'œil. Sept lignes
            # d'horaires demandent qu'on s'y arrête.
            self._feed.widget("planning", src=PLANNING_PATH, duration=25.0)
            return {"widget": "planning", "src": PLANNING_PATH}

        elif widget == "bingo":
            # Deux gestes sur le même widget : ouvrir la grille, ou cocher une
            # case. Le distinguer par la présence de `cells` évite d'exposer deux
            # outils au modèle pour une seule idée.
            cells = [str(c).strip()[:34] for c in (extra.get("cells") or []) if str(c).strip()]
            if cells:
                if not self.start_bingo(cells):
                    return None
                # Les cases telles que la grille les a RANGÉES (tronquées,
                # nettoyées), pas celles qu'on lui a passées.
                ouverte = self._bingo or {}
                return {"widget": "bingo", "cells": ouverte.get("cells") or cells}
            if extra.get("check") is not None:
                checked = self.check_bingo(extra.get("check"))
                if checked is None:
                    return None
                return checked
            # Ni cases ni coche : on redemande simplement la grille. Elle ne
            # reste pas à l'écran, et sans ça on ne pouvait pas la revoir.
            return self.show_bingo()

        elif widget == "stats":
            # Les chiffres viennent de l'outil Apex, pas d'ici : Wally les a lus
            # avant d'appeler, on se contente de les mettre en forme.
            lines = [str(l).strip()[:34] for l in (extra.get("lines") or []) if str(l).strip()]
            if not lines:
                return None
            params = {"player": str(extra.get("player") or "")[:24],
                      "lines": lines[:4]}

        elif widget == "versus":
            gauche, droite = extra.get("left_value"), extra.get("right_value")
            if gauche is None or droite is None:
                return None      # sans chiffres, il n'y a rien à comparer
            try:
                left_value = float(gauche)
                right_value = float(droite)
            except (TypeError, ValueError):
                return None
            left_name = str(extra.get("left_name") or "").strip()[:14]
            right_name = str(extra.get("right_name") or "").strip()[:14]
            if not left_name or not right_name:
                return None
            params = {
                "label": ecourter(str(extra.get("label") or comment), 24),
                "left_name": left_name, "left_value": left_value,
                "right_name": right_name, "right_value": right_value,
            }
            # Sous-titres facultatifs (« Fuse · niv. 285 »), que l'overlay sait
            # rendre depuis toujours mais que ce filtre ne laissait jamais
            # passer : le duel les remplit, un appel générique ne les donne pas
            # et rien ne s'affiche alors. Une valeur vide est OMISE plutôt que
            # publiée : une ligne vide sous un nom n'est pas une information.
            for cote in ("left_sub", "right_sub"):
                sous_titre = str(extra.get(cote) or "").strip()
                if sous_titre:
                    params[cote] = ecourter(sous_titre, 24)
            # Marqueurs posés par le duel Apex, jamais par le modèle : ils ne
            # sont pas dans le schéma de l'outil. `duel` dit que cette
            # comparaison revient manche après manche — l'écran réserve alors
            # la couleur de victoire au verdict, et fait tressaillir le chiffre
            # qui vient de bouger. `final` est le verdict lui-même, et n'existe
            # que sous `duel` : une comparaison générique ne peut pas se
            # déclarer close.
            if extra.get("duel") is True:
                params["duel"] = True
                if extra.get("final") is True:
                    params["final"] = True

        elif widget == "uptime":
            label = self._uptime_label()
            if not label:
                return None  # pas de live daté : rien à afficher
            params = {"text": label}
            widget = "counter"  # même rendu, données calculées ici

        self._feed.widget(widget, **params)
        # Le commentaire accompagne le widget : c'est lui qui fait le personnage,
        # pas l'animation. Il consomme le budget des bulles.
        if comment:
            # La bulle s'efface pendant un widget : la publier la ferait surgir à
            # contretemps, une fois le widget parti. Le créneau reste consommé —
            # une pensée ne doit pas s'empiler juste derrière.
            self._mark_spoken()
        return {"widget": widget, **params}

    async def show_apex(
        self, panel: str, player: str = "", comment: str = "",
        requester: Optional[str] = None, period: str = "live",
    ) -> Optional[dict]:
        """Affiche un panneau de données Apex réelles. None si rien à montrer.

        Méthode à part — et asynchrone — pour la même raison que `play_last_clip` :
        la donnée vient du réseau, ce que `show_widget` (synchrone) ne peut pas
        faire. Le modèle ne fournit aucun chiffre, il nomme un panneau.
        """
        if self._apex is None or not self._live():
            return None
        try:
            data = await self._apex.build_panel(
                panel, player, requester=requester, period=period
            )
        except Exception as exc:  # noqa: BLE001 — un panneau raté ne casse rien
            logger.warning("Overlay: panneau Apex {p} échoué: {e!r}", p=panel, e=exc)
            return None
        if not data:
            return None
        params = {k: v for k, v in data.items() if k != "kind"}
        self._feed.widget(data["kind"], **params)
        if comment:
            # Même règle que `show_widget` : la bulle s'efface derrière un widget,
            # mais le créneau reste consommé pour qu'une pensée ne s'empile pas.
            self._mark_spoken()
        return {"widget": data["kind"], "player": str(params.get("player") or "")}

    # ── saluts (widget 9) ─────────────────────────────────────────────────

    async def on_chat_message(
        self, author: str, text: str, days_since: Optional[float] = None
    ) -> None:
        """Une ligne de chat arrive : compte un éventuel vote, puis salue.

        Le salut se déclenche à la PREMIÈRE prise de parole d'une personne
        pendant le live — on ne détecte pas les arrivées silencieuses, et un
        viewer qui ne parle jamais n'a rien à faire à l'écran.

        ⚠️ `days_since` doit être mesuré par l'appelant AVANT que le message ne
        rafraîchisse `memory_users`, sinon tout le monde paraît « vu à l'instant »
        et plus personne n'est jamais salué.
        """
        author = (author or "").strip()
        if not author:
            return
        # `author` est déjà nettoyé et non vide ici : le `if author:` et le
        # second `strip()` d'avant laissaient croire qu'un auteur vide restait
        # possible à cet endroit.
        self._talkers[author] = self._talkers.get(author, 0) + 1
        # Signal de réception : le chat qui bouge dans la minute qui suit une
        # bulle est le SEUL retour spectateur exploitable — sans lui, rien ne
        # distingue un compagnon de stream vivant d'un meuble à l'écran.
        note_audience(self._conv_log, OVERLAY_JOURNAL_PLATFORM,
                      OVERLAY_JOURNAL_CHANNEL, author, text or "")
        self.maybe_remind_bingo()
        # Les trois compteurs attendent un message NU : une lettre seule, un
        # chiffre seul, un nom de coup. Or on répond à un bot en le mentionnant —
        # « @WallyTeBully d ». Le 2026-08-07, deux parties de pendu n'ont ainsi
        # enregistré aucune lettre. On retire l'interpellation ici, une fois pour
        # les trois, plutôt que dans chacun.
        played = _strip_address(text)
        self._count_vote(author, played)
        self._count_hangman(author, played)
        await self._maybe_greet(author, days_since)

    async def _maybe_greet(self, author: str, days: Optional[float]) -> None:
        key = author.lower()
        # Une seule fois par personne et par live, sinon il resaluerait à chaque
        # message.
        if key in self._greeted or not self._may_react():
            return
        self._greeted.add(key)
        # Une fois par personne et par live : l'écriture est rare, et l'oublier
        # coûte un « tiens, revoilà machin ! » de plus à chaque rebuild.
        self._planifier_flush()

        if days is None:
            kind = f"{author} débarque pour la première fois"
        elif days >= _RETURN_AFTER_DAYS:
            kind = f"{author} revient après {int(days)} jours d'absence"
        else:
            return  # habitué vu récemment : rien à signaler

        self._last_event_at = time.monotonic()
        self._feed.thinking(True)
        trace = new_trace_id("overlay")
        depart = time.monotonic()
        try:
            short = await self._condense(kind, system=_EVENT_SYSTEM,
                                         source="greet", trace=trace)
        except Exception as exc:  # noqa: BLE001
            logger.debug("OverlayNarrator: salut échoué: {e!r}", e=exc)
            self._journal("overlay_rejected", "greet", kind, trace_id=trace,
                          motif=f"condensation en échec : {exc}")
            short = None
        if not short:
            self._feed.thinking(False)
            return
        # Deux arrivées rapprochées produisent deux « du monde arrive » quasi
        # identiques : c'est le cas que `_is_repeat` a été écrit pour couvrir.
        # Et sans `_remember_bubble`, la bulle suivante n'était pas dédupliquée
        # contre le salut non plus.
        if self._is_repeat(short):
            logger.info("Overlay: salut écarté (déjà dit) — « {t} »", t=short)
            self._journal("overlay_rejected", "greet", kind, trace_id=trace,
                          motif="déjà dit", candidat=short,
                          condense_ms=int((time.monotonic() - depart) * 1000))
            self._feed.thinking(False)
            return
        self._mark_spoken()
        self._remember_bubble(short)
        self._feed.say(short, mode="speech")
        self._journal_publication("greet", kind, short, "speech", trace, depart)

    def reset_live(self) -> None:
        """Remet à zéro l'état lié à un live (saluts, sondage, bingo)."""
        self._greeted.clear()
        self._poll = None
        self._bingo = None
        self._bingo_reminded_at = 0.0
        self._goal = None
        self._recent_bubbles.clear()
        self._talkers.clear()
        # Une partie laissée en plan quand le live s'est coupé : l'oublier sans
        # lever son filet laissait le mot interdit en sortie jusqu'au prochain
        # redémarrage — sur les quatre plateformes, y compris pour un mot aussi
        # courant qu'« apex ».
        self._release_hangman_secret()
        self._hangman = None
        # Le tampon du flux vit à côté de cet état : `recent()` le rejoue à tout
        # client qui se connecte. Sans ce vidage, un pendu `sticky` du live
        # PRÉCÉDENT revenait à l'écran dès qu'OBS rouvrait la page — et sans
        # minuteur, puisque son événement d'origine n'en portait pas.
        try:
            self._feed.clear()
        except Exception as exc:  # noqa: BLE001 — un live qui démarre ne doit pas échouer
            logger.warning("Overlay: vidage du flux au reset échoué : {e!r}", e=exc)
        # L'oubli doit franchir le redémarrage comme le reste : sans ce
        # rangement, la base garderait la partie du live précédent.
        self._planifier_flush()

    # ── annulation ────────────────────────────────────────────────────────

    def cancel(self, target: str) -> dict:
        """Retire ce qui est à l'écran, ou abandonne une partie en cours.

        Un ABANDON, pas une clôture : un sondage annulé ne dépouille pas et un
        pendu annulé ne rend pas de verdict. Passer par `close_poll()` ferait
        annoncer un gagnant à une manche qu'on vient justement d'interrompre.

        Volontairement insensible au live : on annule aussi — et surtout — quand
        le stream vient de se couper avec un bingo resté ouvert.

        Retourne ce qui a RÉELLEMENT été annulé. La liste vide est la réponse
        utile : elle permet de dire « il n'y avait pas de bingo » au lieu de
        laisser croire que quelque chose a été retiré.
        """
        target = (target or "").strip().lower()
        if target not in CANCEL_TARGETS:
            return {"target": target, "cancelled": [], "unknown": True}

        everything = target == "tout"
        done: list[str] = []

        if (everything or target == "bingo") and self._bingo:
            self._bingo = None
            self._bingo_reminded_at = 0.0
            done.append("bingo")
        if (everything or target == "pendu") and self._hangman:
            self._release_hangman_secret()
            self._hangman = None
            done.append("pendu")
        if (everything or target == "objectif") and self._goal:
            self._goal = None
            done.append("objectif")
        if (everything or target == "sondage") and self._poll:
            self._poll = None
            self._cancel_task("_poll_task")
            done.append("sondage")

        # L'écran est nettoyé dès qu'on annule quoi que ce soit : abandonner le
        # bingo en laissant sa grille affichée n'aurait aucun sens.
        if target in ("ecran", "tout") or done:
            self._feed.clear()
            if target in ("ecran", "tout"):
                done.append("ecran")

        logger.info("Overlay: annulation « {t} » — {d}",
                    t=target, d=", ".join(done) or "rien en cours")
        # Une annulation est un ORDRE — souvent celui du streamer, agacé. Elle
        # doit franchir le redémarrage : ressusciter au rebuild suivant un bingo
        # qu'on vient de lui demander de retirer serait pire que de l'oublier.
        if done:
            self._planifier_flush()
        return {"target": target, "cancelled": done}

    def _cancel_task(self, attr: str) -> None:
        """Coupe une clôture planifiée. Sans ça, le `sleep` en cours rouvrirait
        le dépouillement d'un sondage qu'on vient d'abandonner."""
        task = getattr(self, attr, None)
        if task is not None:
            task.cancel()
            setattr(self, attr, None)

    def current_state_block(self) -> str:
        """Ce qui tourne sur l'overlay, pour le prompt. Vide s'il n'y a rien.

        ⚠️ Perception PASSIVE, comme `StreamFeed` : aucun `notify_*` derrière,
        donc ce bloc ne réveille jamais la cadence vive ni une prise de parole.
        Un bingo ouvert ferait sinon parler Wally en boucle pendant tout le live.
        """
        if not self._live():
            return ""
        lines: list[str] = []
        if self._bingo:
            lines.append(self._bingo_context())
        if self._hangman:
            lines.append(self._hangman_context())
        if self._goal:
            goal = self._goal
            lines.append(f"Objectif « {goal['label']} » : {goal['count']}/{goal['target']}.")
        if self._poll:
            lines.append(f"Sondage en cours : « {self._poll['question']} ».")
        if lines:
            lines.append("Tu peux annuler ce qui traîne avec `cancel_overlay`.")
        if self.force_live_remaining() > 0:
            # Le seul cas où `stream_live` ment par omission : il dira « pas de
            # live », ce qui est vrai, et Wally en concluait que ses outils
            # d'overlay ne marchaient pas — il refusait d'afficher un clip sans
            # même appeler l'outil. En vrai live, cette ligne serait redondante.
            lines.insert(0, (
                "Mode test : aucun live ne tourne, mais ton overlay répond "
                "quand même et tes outils d'overlay marchent. Personne d'autre "
                "que ton créateur ne le voit — ne dis pas au chat qu'on est en "
                "stream."
            ))
        if not lines:
            return ""
        return "\n--- Sur ton overlay ---\n" + "\n".join(lines)

    def _bingo_context(self) -> str:
        """La grille en cours, case par case — pas seulement le score.

        Le bloc n'annonçait que « Bingo : 0/6 cases cochées ». Wally l'a dit
        lui-même en live le 13/08 : « je n'ai pas les cases du bingo en tête ».
        Sans le texte des cases, il ne peut RIEN cocher — trois lives d'affilée
        se sont terminés sur une grille ouverte et vierge.

        Même patron que `_hangman_context`, et même prudence : la consigne voyage
        COLLÉE à la donnée. Ici elle dit l'inverse du pendu — la grille est déjà à
        l'écran, il n'y a rien à cacher ; ce qu'il faut rappeler, c'est que cocher
        est un GESTE (l'outil `overlay` avec `check`), pas une phrase à dire.
        """
        bingo = self._bingo or {}
        cells, done = bingo.get("cells") or [], bingo.get("done") or []
        n = sum(1 for d in done if d)
        lignes = [
            f"Bingo en cours : {n}/{len(cells)} cases cochées. La grille, "
            "dans l'ordre (le numéro est celui à donner à `check`) :"
        ]
        for i, cell in enumerate(cells):
            lignes.append(f"  {i} [{'x' if done[i] else ' '}] {cell}")
        lignes.append(
            "Quand l'une de ces prédictions se réalise pour de vrai, coche-la "
            "toi-même : outil `overlay`, widget=bingo, check=<numéro ou quelques "
            "mots de la case>. Personne d'autre ne le fera. Une case déjà cochée "
            "ne se recoche pas, et on ne coche pas une case « pour voir »."
        )
        return "\n".join(lignes)

    def _hangman_context(self) -> str:
        """La partie en cours, telle que Wally doit la voir pour l'animer.

        Le mot et l'indice EN FONT PARTIE : sans eux, « donne un autre indice »
        ou « il en est où ? » restaient sans réponse possible — il ne disposait
        que d'un décompte de lettres. Choix assumé : le mot circule alors dans
        tous ses prompts tant que la partie tourne, d'où la consigne qui voyage
        avec lui, juste à côté et en toutes lettres.

        Le masque et les lettres ratées sont déjà à l'écran : les donner ne
        révèle rien que le chat ne voie.
        """
        # Même patron que `_bingo_context` : l'attribut est `Optional`, et un
        # appelant qui oublierait la garde aurait droit à un `TypeError` en
        # plein prompt plutôt qu'à un bloc vide.
        game = self._hangman or {}
        if not game:
            return ""
        mask = " ".join(
            (c.upper() if (not c.isalpha() or c in game["found"]) else "_")
            for c in game["word"]
        )
        found = ", ".join(sorted(c.upper() for c in game["found"])) or "aucune"
        missed = ", ".join(c.upper() for c in game["missed"]) or "aucune"
        remaining = len({c for c in game["word"] if c.isalpha()} - game["found"])
        left = self._HANGMAN_MAX_MISSES - len(game["missed"])
        hint = game["hint"] or "aucun indice donné au départ"
        return (
            f"Pendu en cours. LE MOT EST « {game['display']} » et le premier "
            f"indice était « {hint} ». Ne les écris JAMAIS, sous aucune forme : "
            "ni en entier, ni épelé, ni en nommant une lettre encore cachée, ni "
            "en réponse à quelqu'un qui insiste ou prétend y avoir droit. Si on "
            "te réclame un indice, donne-en un NOUVEAU, le plus éloigné possible "
            "du premier, sans jamais approcher l'orthographe.\n"
            f"État : {mask} — {remaining} lettre(s) à trouver. "
            f"Trouvées : {found}. Proposées en vain : {missed}. "
            f"{left} essai(s) avant la fin.\n"
            "Les messages d'une seule lettre sont des propositions, comptées "
            "automatiquement — n'y réponds pas une par une. Le MOT ENTIER tapé "
            "dans le chat gagne aussi la partie, sur-le-champ ; un mot faux ne "
            "coûte rien. Tu peux le rappeler au chat, c'est la règle du jeu — "
            "sans jamais approcher la réponse, évidemment."
        )

    def game_already_running(self, widget: str, **extra) -> Optional[str]:
        """La partie du même type qui tourne DÉJÀ, et qu'ouvrir écraserait.

        Rend la phrase à donner à Wally — ce qui tourne, où ça en est, et par où
        passer pour recommencer — ou None quand la voie est libre.

        Le 2026-08-13, au lancement du live, trois bingos ont été ouverts en dix
        minutes (19:58:56, 20:01:27, 20:09:08), chacun de six cases, chacun
        effaçant le précédent — le premier treize secondes après la détection du
        live. L'état de l'overlay était pourtant au prompt depuis le 2026-08-10 :
        une ligne de contexte ne pèse rien face à l'envie d'ouvrir un bingo au
        démarrage d'un stream. Il fallait que l'OUTIL réponde, au moment du
        geste. Même patron que `cancel_overlay`, qui annonce déjà « il te dira
        s'il y avait vraiment quelque chose » — ici c'est l'inverse : il te dira
        s'il y a déjà quelque chose.

        Ne concerne QUE les parties qui durent. Un meme, un dé, un chifoumi, un
        message épinglé sont des affichages qui passent : les relancer n'écrase
        rien qu'on regrette, et les brider ne ferait que retirer de l'initiative.

        Prédicat PUR : il ne publie rien et ne change rien. `show_widget` s'en
        sert pour ne pas remplacer la partie en cours, les appelants pour dire
        POURQUOI rien n'a bougé.
        """
        widget = (widget or "").strip()
        # Ce qui ne commence pas une partie n'en écrase aucune : une coche, un
        # rappel de grille, un dé. `ouverture_de_partie` porte ce critère pour
        # tout le module.
        if ouverture_de_partie(widget, **extra) is None:
            return None

        if widget == "bingo":
            if not self._bingo:
                return None
            done = sum(1 for d in self._bingo["done"] if d)
            return (
                f"Rien affiché : un bingo tourne DÉJÀ sur l'overlay — "
                f"{done}/{len(self._bingo['cells'])} cases cochées. Ta nouvelle "
                "grille n'a PAS remplacé la sienne, rien n'est perdu. Pour "
                "cocher une case qui vient de se réaliser, rappelle "
                "`show_overlay` avec `check` ; pour la remontrer, `show_overlay` "
                "widget=bingo tout court. Si tu veux vraiment repartir de zéro, "
                "appelle d'abord `cancel_overlay` target=bingo, puis relance."
            )

        if widget == "poll":
            if not self._poll:
                return None
            return (
                f"Rien affiché : un sondage tourne DÉJÀ — "
                f"« {self._poll['question']} », le chat est en train de voter. "
                "Ta question n'a PAS écrasé la sienne. Attends la clôture — le "
                "résultat t'arrivera dans ton flux du stream — ou appelle "
                "`cancel_overlay` target=sondage d'abord si tu veux vraiment "
                "l'abandonner, sans dépouillement."
            )

        if widget == "hangman":
            game = self._hangman
            if not game:
                return None
            # Ni le mot ni l'indice : ce message peut finir dans un contexte que
            # la partie en cours ne devrait pas polluer, et il n'apprendrait
            # rien que `_hangman_context` ne dise déjà, avec ses gardes.
            restantes = len({c for c in game["word"] if c.isalpha()} - game["found"])
            essais = self._HANGMAN_MAX_MISSES - len(game["missed"])
            return (
                f"Rien affiché : un pendu tourne DÉJÀ — {restantes} lettre(s) "
                f"encore à trouver, {essais} essai(s) avant la fin. Ton nouveau "
                "mot a été ignoré, la partie en cours est intacte. Pour "
                "remontrer la grille, `show_overlay` widget=hangman SANS `word`. "
                "Pour en lancer une autre, `cancel_overlay` target=pendu "
                "d'abord — mais n'abandonne pas une partie que le chat joue."
            )

        if widget == "goal":
            goal = self._goal
            if not goal:
                return None
            return (
                f"Rien affiché : un objectif tourne DÉJÀ — « {goal['label']} » : "
                f"{goal['count']}/{goal['target']}. Le tien n'a PAS remplacé le "
                "sien. Celui-là se remplit tout seul, il n'y a rien à rouvrir ; "
                "pour en changer, `cancel_overlay` target=objectif d'abord."
            )

        return None

    def refus_faute_de_demande(self, widget: str, **extra) -> Optional[str]:
        """Pourquoi ce jeu ne s'est pas ouvert : personne ne l'avait demandé.

        Le pendant de `game_already_running`, et pour la même raison : un refus
        muet se rejoue. Celui-ci nomme la règle ET donne la sortie — proposer
        d'abord, lancer si on lui dit oui. C'est ce qui garde l'envie de faire
        vivre le stream sans imposer une partie à personne.

        Prédicat PUR : il ne publie rien et ne change rien. Il ne dit pas si la
        partie a été refusée — l'appelant le sait — mais ce qu'il y avait à en
        dire si elle l'a été.

        Muet quand le refus vient d'AILLEURS (hors live, widget masqué sur
        toutes les scènes) : un motif plausible mais faux se retient et se
        rejoue, alors qu'un silence laisse au moins la question ouverte.
        """
        partie = ouverture_de_partie(widget, **extra)
        if partie is None:
            return None
        if not self._live() or not self._widget_affichable(widget):
            return None
        return (
            f"Rien affiché : un {partie} ne s'ouvre que si quelqu'un le demande. "
            "C'est une partie qui dure et qui occupe l'écran du live — la "
            "lancer sans qu'on l'ait réclamée, c'est décider à la place du "
            "streamer et de son chat. Propose-le plutôt : dis dans le chat que "
            f"tu as un {partie} sous le coude, et lance-le si on te dit oui. "
            "Tout le reste — un meme, un dé, la roue, un message épinglé — "
            "s'affiche quand tu veux, et tu peux toujours cocher, remontrer ou "
            "annuler une partie déjà ouverte."
        )

    def show_prediction(self, bet: str, *, outcome: str = "",
                        right: int = 0, total: int = 0) -> bool:
        """Montre un pari : à son ouverture, puis à son verdict.

        Contrairement aux compteurs, ce widget n'est PAS rationné : un pari est
        rare et c'est son verdict qui fait le sel. Le rater serait pire que de
        déranger.
        """
        if not self._live():
            return False
        self._last_event_at = time.monotonic()
        self._feed.widget("prediction", bet=str(bet)[:90], outcome=outcome,
                          right=int(right), total=int(total))
        return True

    def show_quote(self, author: str, text: str, *, age: str = "") -> bool:
        """Affiche une réplique citée. `age` situe le moment (« hier », « mardi »)."""
        if not self._live() or not text:
            return False
        self._last_event_at = time.monotonic()
        self._feed.widget("quote", author=str(author)[:24], text=str(text)[:160],
                          age=str(age)[:24], duration=12)
        return True

    # Paliers auxquels un compteur mérite un mot. Au-delà de 100, tous les 100 :
    # un gag qui atteint 300 n'a pas besoin d'être commenté à 310.
    _COUNTER_MILESTONES = (10, 25, 50, 100)

    @classmethod
    def is_counter_milestone(cls, count: int) -> bool:
        return count in cls._COUNTER_MILESTONES or (count > 100 and count % 100 == 0)

    async def on_counter_milestone(self, label: str, count: int) -> Optional[str]:
        """Fait commenter un compteur qui atteint un palier.

        Un chiffre qui monte tout seul finit par ne plus rien dire ; c'est la
        remarque qui fait le gag. Rare par construction — seulement aux paliers.

        Rationné par le budget des BULLES, pas par celui des événements : les
        appelants font `show_counter()` puis ce commentaire dans la foulée, or
        le compteur vient de consommer le budget événement. Le tester ici
        refusait le palier à tous les coups — sauf quand le compteur lui-même
        avait été refusé, exactement à l'envers.
        """
        if not self.is_counter_milestone(count) or not self._may_speak():
            return None
        # Réserve le créneau avant l'appel, comme `on_thought`.
        self._mark_spoken()
        entree = f"Le compteur « {label} » vient d'atteindre {count}."
        trace = new_trace_id("overlay")
        depart = time.monotonic()
        try:
            short = await self._condense(entree, system=_EVENT_SYSTEM,
                                         source="milestone", trace=trace)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("Overlay: commentaire de palier échoué: {e!r}", e=exc)
            self._journal("overlay_rejected", "milestone", entree, trace_id=trace,
                          motif=f"condensation en échec : {exc}")
            return None
        if not short:
            return None
        if self._is_repeat(short):
            logger.info("Overlay: palier écarté (déjà dit) — « {t} »", t=short)
            self._journal("overlay_rejected", "milestone", entree, trace_id=trace,
                          motif="déjà dit", candidat=short,
                          condense_ms=int((time.monotonic() - depart) * 1000))
            return None
        self._remember_bubble(short)
        self._feed.say(short, mode="speech")
        logger.info("Overlay: palier {n} sur « {l} » — {t}", n=count, l=label, t=short)
        self._journal_publication("milestone", entree, short, "speech", trace, depart)
        return short

    def maybe_remind_bingo(self, every_s: float = 600.0) -> bool:
        """Remontre la grille de temps en temps.

        Sans rappel, elle n'apparaît qu'aux cases cochées : les viewers arrivés
        entre-temps ne savent pas qu'une partie est en cours.
        """
        if not self._bingo or not self._may_react():
            return False
        now = time.monotonic()
        if now - self._bingo_reminded_at < every_s:
            return False
        self._bingo_reminded_at = now
        self._feed.widget("bingo", cells=self._bingo["cells"],
                          done=list(self._bingo["done"]), duration=10)
        return True

    # Ce qu'un objectif peut compter, et le nom qu'on lui donne à l'écran.
    _GOAL_KINDS = {"follow": "follows", "sub": "abonnements", "bits": "bits"}

    def open_goal(self, label: str, target: Any, kind: str) -> bool:
        """Ouvre un objectif alimenté par les vrais événements du live.

        `target` est déclaré `Any` parce que c'est la vérité : il arrive du
        modèle, par `extra.get("target")`, et vaut aussi bien `"50"` que `None`.
        La conversion et son échec sont traités ici — l'annoter `int` promettait
        un contrôle que personne n'exerce, et l'appel était rouge au type-check.
        """
        kind = (kind or "").strip().lower()
        try:
            vise = int(target)
        except (TypeError, ValueError):
            return False
        if kind not in self._GOAL_KINDS or vise < 1 or not self._live():
            return False
        self._goal = {"label": ecourter(label or "", 40) or self._GOAL_KINDS[kind],
                      "target": min(vise, 100000), "kind": kind, "count": 0}
        self._publish_goal()
        logger.info("Overlay: objectif « {l} » — {n} {k}",
                    l=self._goal["label"], n=vise, k=kind)
        self._planifier_flush()
        return True

    def record_goal_event(self, kind: str, amount: int = 1) -> bool:
        """Incrémente l'objectif si l'événement le concerne.

        Appelé depuis les événements Twitch : c'est ce qui remplit la jauge
        toute seule, au lieu d'un chiffre qu'il faudrait redonner à la main.
        """
        goal = self._goal
        if not goal or goal["kind"] != (kind or "").lower():
            return False
        goal["count"] += max(1, int(amount or 1))
        self._publish_goal()
        if goal["count"] >= goal["target"]:
            logger.info("Overlay: objectif « {l} » atteint", l=goal["label"])
            self._goal = None
        self._planifier_flush()
        return True

    def _publish_goal(self) -> None:
        goal = self._goal
        if not goal:
            return
        percent = min(100.0, goal["count"] * 100.0 / goal["target"])
        self._feed.widget(
            "gauge", percent=percent,
            label=f"{goal['label']} · {goal['count']}/{goal['target']}",
            duration=10,
        )

    def show_talkers(self, top: int = 3) -> Optional[dict]:
        """Classement des plus bavards du chat depuis le début du live.

        Purement mécanique : rien n'est interprété, donc rien ne peut être
        inventé. Sur demande seulement — un classement permanent inciterait au
        spam.
        """
        if not self._live() or not self._talkers:
            return None
        ranking = sorted(self._talkers.items(), key=lambda kv: (-kv[1], kv[0]))[:max(1, top)]
        # Même forme des deux côtés : l'exécuteur d'outil fait `str(v)` sur ce
        # qu'on renvoie, et Wally lisait « [('alice', 12), ...] ».
        rows = [{"name": n, "count": c} for n, c in ranking]
        self._feed.widget("talkers", rows=rows, duration=10)
        return {"widget": "talkers", "rows": rows}

    # Un embed n'est accepté que s'il vient bien de Twitch : cette URL part
    # dans le `src` d'une iframe côté navigateur.
    _CLIP_EMBED_PREFIX = "https://clips.twitch.tv/embed?"

    # Marge de chargement : sans elle, le widget s'efface au moment précis où la
    # vidéo finit — voire avant qu'elle n'ait démarré.
    _CLIP_LOAD_MARGIN_S = 3.0

    # Le fichier vidéo part dans un `<video src>` : on n'accepte que du https
    # servi par Twitch ou son CDN. Le nom de distribution CloudFront change
    # d'un clip à l'autre, d'où le suffixe plutôt qu'une liste figée.
    _CLIP_VIDEO_HOSTS = (".cloudfront.net", ".twitch.tv", ".twitchcdn.net")

    @classmethod
    def _is_clip_video(cls, url: str) -> bool:
        if not url.startswith("https://"):
            return False
        host = url[len("https://"):].split("/", 1)[0].split("?", 1)[0].lower()
        return any(host.endswith(suffix) for suffix in cls._CLIP_VIDEO_HOSTS)

    @classmethod
    def _clip_duration(cls, duration) -> float:
        """Temps d'affichage : la durée du clip, plus la marge de chargement."""
        try:
            seconds = float(duration)
        except (TypeError, ValueError):
            seconds = 0.0
        # Un clip Twitch fait 60 s au plus ; la borne protège d'une valeur
        # aberrante qui figerait l'overlay.
        return max(1.0, min(60.0, seconds or 30.0)) + cls._CLIP_LOAD_MARGIN_S

    def show_clip(self, title: str, author: str, *, embed_url: str = "",
                  video_url: str = "", duration: float = 0.0) -> bool:
        """Montre un clip. Trois niveaux, du meilleur au moins bon :

        1. `video_url` — le fichier vidéo, joué par une balise `<video muted>`.
           C'est le seul mode qui démarre TOUT SEUL : le player Twitch en
           iframe refuse l'autoplay dans un overlay (« style visibility »,
           faux positif non corrigé côté Twitch).
        2. `embed_url` — le player officiel. S'affiche, mais attend un clic.
           Sert de filet si l'API GraphQL non officielle change.
        3. la carte texte, quand on n'a ni l'un ni l'autre.

        Pas soumis au budget : clipper est un geste rare, et le signaler
        récompense celui qui l'a fait — c'est tout l'intérêt.
        """
        if not self._live():
            return False
        params: dict = {"title": ecourter(str(title), 80), "author": str(author)[:24]}
        embed_url = str(embed_url or "")
        video_url = str(video_url or "")
        if self._is_clip_video(video_url):
            params["video"] = video_url
            params["duration"] = self._clip_duration(duration)
        elif embed_url.startswith(self._CLIP_EMBED_PREFIX):
            params["embed"] = embed_url
            params["duration"] = self._clip_duration(duration)
        else:
            params["duration"] = 10
        self._last_event_at = time.monotonic()
        self._feed.widget("clip", **params)
        return True

    async def play_last_clip(
        self,
        creator: Optional[str] = None,
        *,
        query: Optional[str] = None,
        most_viewed: bool = False,
    ) -> Optional[dict]:
        """Rejoue un clip de la chaîne. None s'il n'y en a pas.

        Trois façons de le choisir : le plus récent (défaut), le plus vu
        (`most_viewed`), ou celui dont le titre colle à `query`.

        `creator` restreint au clippeur demandé — le filtrage appartient au
        fournisseur, seul à parler à Helix.

        Le fournisseur est injecté plutôt qu'appelé d'ici : `show_widget` est
        synchrone et n'a aucun moyen d'interroger une API externe, alors que
        « affiche le dernier clip » en dépend entièrement.
        """
        if self._last_clip is None or not self._live():
            return None
        try:
            clip = await self._last_clip(creator, query=query, most_viewed=most_viewed)
        except Exception as exc:  # noqa: BLE001 — une API muette ne casse rien
            logger.warning("Overlay: dernier clip introuvable : {e!r}", e=exc)
            return None
        if not clip:
            return None
        title = str(clip.get("title") or "un clip")
        author = str(clip.get("creator_name") or "quelqu'un")
        embed = str(clip.get("embed_url") or "")
        video = str(clip.get("video_url") or "")
        if not self.show_clip(title, author, embed_url=embed, video_url=video,
                              duration=clip.get("duration") or 0.0):
            return None
        # « joué » veut dire : ça démarre tout seul. L'iframe s'affiche mais
        # attend un clic — Wally ne doit pas annoncer une lecture dans ce cas.
        played = self._is_clip_video(video)
        logger.info(
            "Overlay: clip « {t} » de {a} — {m}", t=title, a=author,
            m="joué" if played else ("player en attente de clic" if embed else "carte seule"),
        )
        return {"widget": "clip", "title": title, "author": author,
                "played": played}

    async def show_top_clips(self, count: int = 5) -> Optional[dict]:
        """Le podium des clips les plus vus. None s'il n'y a rien à classer.

        Pas de vidéo ici : c'est un tableau qu'on lit, et enchaîner cinq clips
        monopoliserait l'écran plusieurs minutes.
        """
        if self._top_clips is None or not self._live():
            return None
        count = max(1, min(5, int(count or 5)))
        try:
            clips = await self._top_clips(count)
        except Exception as exc:  # noqa: BLE001 — une API muette ne casse rien
            logger.warning("Overlay: podium des clips indisponible : {e!r}", e=exc)
            return None
        rows = [
            {
                "title": ecourter(str(c.get("title") or "sans titre"), 48),
                "author": str(c.get("creator_name") or "?")[:20],
                "views": int(c.get("view_count") or 0),
            }
            for c in (clips or [])
        ]
        if not rows:
            return None
        self._feed.widget("clip_top", rows=rows, duration=float(6 + 2 * len(rows)))
        logger.info("Overlay: podium des clips ({n})", n=len(rows))
        return {"widget": "clip_top", "count": len(rows), "best": rows[0]["title"]}

    # Ce qu'un raid remercie : le nom passe en grand, il doit tenir sur la carte.
    _MAX_RAIDER_CHARS = 24

    def celebrate_raid(self, raider: str, viewers: int = 0) -> bool:
        """Accueille un raid à l'écran : le nom, le nombre, et des confettis.

        Volontairement HORS du budget `_may_react()`. Ce budget espace les
        événements pour ne pas saturer l'overlay, et il a raison de le faire
        pour un emote qui déferle — mais un raid arrive quand il arrive. Le
        rater parce qu'une vague d'emotes vient de passer coûte infiniment plus
        cher qu'un widget de trop : c'est le seul moment où des inconnus
        débarquent, et où quelqu'un mérite d'être remercié par son nom.

        Reste soumis au live : hors stream, personne ne regarde l'overlay.
        """
        if not self._live():
            return False
        self._last_event_at = time.monotonic()
        try:
            compte = max(0, int(viewers or 0))
        except (TypeError, ValueError):
            compte = 0        # Twitch a renvoyé n'importe quoi : on montre quand même
        self._feed.widget(
            "raid",
            raider=str(raider or "").strip()[:self._MAX_RAIDER_CHARS],
            viewers=compte,
            duration=10,
        )
        logger.info("Overlay: raid de {r} ({n} spectateurs)", r=raider or "?", n=compte)
        return True

    def show_emote_wave(self, emote: str) -> bool:
        """Signale que le chat spamme le même emote."""
        if not self._may_react():
            return False
        self._last_event_at = time.monotonic()
        self._feed.widget("wave", emote=str(emote)[:30], duration=6)
        return True

    # Le spam de popups « virus » — variante de l'avalanche, montée pour que
    # l'owner tranche entre les deux en les voyant tourner.
    #
    # Ces quatre nombres SONT ceux d'`overlay_virus.js` : le client génère les
    # ouvertures, le serveur dimensionne la carte qui doit toutes les contenir.
    # Deux écritures d'un même calcul, dont l'accord est tenu par un test plutôt
    # que par la discipline (`test_le_dossier_ENTIER_tient_dans_la_fenetre`).
    VIRUS_DEBUT_MS = 1000     # entre deux ouvertures, au démarrage
    VIRUS_FIN_MS = 100        # … et une fois en régime
    VIRUS_CRANS = 24          # ouvertures pour passer de l'un à l'autre
    VIRUS_PART_ALERTES = 0.4  # le reste va aux memes
    # Repli quand le dossier est illisible, et plancher : un spam de trois
    # secondes n'aurait le temps ni de monter en régime ni de faire rire.
    VIRUS_S = 23
    # Filet : le jour où le dossier passe à 5 000 memes, on ne confisque pas
    # l'écran vingt minutes.
    VIRUS_MAX_S = 180
    # L'écran bleu final, qui recouvre tout avant le retrait de la carte.
    VIRUS_BSOD_S = 2

    def _duree_virus(self) -> int:
        """Le temps qu'il faut pour ouvrir une fenêtre par meme, alertes
        comprises.

        « Y a pas tous les memes si ? » puis « on peut le faire durer plus
        longtemps si il faut afficher les autres memes » (owner) : une durée
        fixe plafonnait le dossier au tiers. C'est donc le stock qui commande.
        """
        library = self._memes
        stock = 0
        if library is not None:
            try:
                stock = len(library.list_medias())
            except Exception as exc:  # noqa: BLE001 — on lance quand même
                logger.warning("Spam virus : stock illisible ({e!r}) — durée par défaut",
                               e=exc)
                return self.VIRUS_S
        if stock <= 0:
            return self.VIRUS_S
        fenetres = ceil(stock / (1 - self.VIRUS_PART_ALERTES))
        # La montée en régime, puis le plateau — même progression que le client.
        raison = (self.VIRUS_FIN_MS / self.VIRUS_DEBUT_MS) ** (1 / (self.VIRUS_CRANS - 1))
        total_ms = 0.0
        pas = float(self.VIRUS_DEBUT_MS)
        for _ in range(fenetres - 1):
            total_ms += pas
            pas = max(self.VIRUS_FIN_MS, pas * raison)
        return max(self.VIRUS_S,
                   min(self.VIRUS_MAX_S, ceil(total_ms / 1000)))

    def show_virus_popups(self, seconds: int | None = None) -> bool:
        """Fait spammer l'écran de fausses fenêtres système. Vrai si c'est parti.

        Elles s'ouvrent de plus en plus vite, s'empilent — les plus anciennes se
        referment quand l'écran est saturé — puis un écran bleu recouvre tout.

        Un seul refus : l'écran éteint. Un dossier de memes vide n'en est PAS un
        — contrairement à l'avalanche, les alertes se suffisent, et refuser
        priverait d'un effet qui marche.
        """
        if not self._live():
            return False
        duree = int(seconds) if seconds else self._duree_virus()
        self._last_event_at = time.monotonic()
        self._feed.widget("virus_popup", seconds=duree,
                          duration=duree + self.VIRUS_BSOD_S + 1)
        logger.info("Overlay : spam de popups virus ({d} s)", d=duree)
        return True

    # Ce qui est déjà à l'écran, pour ne pas faire clignoter la même étiquette
    # quand cinq personnes demandent le titre en dix secondes.
    _dernier_morceau = ""

    def show_music(self, titre: str, artiste: str, *, joue: bool = True,
                   url: str = "") -> bool:
        """Affiche le morceau en cours. Vrai s'il est parti à l'écran.

        Il COHABITE : une étiquette de titre n'est pas un spectacle, elle
        n'efface ni l'avatar ni la bulle — contrairement à l'avalanche ou au
        spam de popups, qui prennent la scène.

        Refusé deux fois : hors live (rien à afficher) et sur le MÊME morceau
        que la dernière fois. Ce second refus ne rationne que l'AFFICHAGE — Wally
        répond quand même dans le chat à chacun de ceux qui demandent.

        `url` est l'adresse de la page où joue le morceau, telle que l'extension
        l'a rapportée. Elle ne part PAS à l'écran : seule la pochette qu'on en
        dérive le fait, et uniquement si l'adresse a passé la grille de
        `music.vignette()`. Sans pochette, l'overlay montre un disque neutre —
        la carte ne dépend pas d'elle.
        """
        titre = str(titre or "").strip()[:80]
        if not titre:
            return False          # une carte vide est pire que pas de carte
        if not self._live():
            return False
        artiste = str(artiste or "").strip()[:80]
        signature = f"{artiste}\u241f{titre}"
        if signature == self._dernier_morceau:
            return False
        self._dernier_morceau = signature
        self._last_event_at = time.monotonic()
        self._feed.widget("music_now", title=titre, artist=artiste,
                          playing=bool(joue), cover=vignette(url))
        logger.info("Overlay : morceau affiché — {a} — {t}", a=artiste, t=titre)
        return True

    def show_apex_kills(self, *, partie, total: int, parties: int,
                        rp: int | None = None) -> bool:
        """Le bilan d'une partie : ses kills, et le cumul du live. Vrai si parti.

        Refusé quand `partie` vaut `None` — une partie illisible (trackers
        dépinglés, Mixtape) ne donne pas « 0 kill » à l'écran, elle ne donne
        rien. Un zéro inventé est un mensonge, pas une valeur par défaut ; c'est
        la leçon du 2026-08-13, où 39 kills sont devenus 0 en direct.

        Un vrai zéro, lui, s'affiche : mourir sans tuer est une partie mesurée,
        et c'est même ce que le chat commentera le plus.

        `rp` est le gain (ou la perte) de points de rang, et il n'est rendu QUE
        s'il a bougé : un RP immobile veut dire « pas de classé », pas « zéro
        point » — l'afficher inventerait une partie classée blanche.
        """
        if not isinstance(partie, int) or isinstance(partie, bool) or partie < 0:
            return False
        if not self._live():
            return False
        self._last_event_at = time.monotonic()
        gagnes = rp if isinstance(rp, int) and not isinstance(rp, bool) and rp else None
        self._feed.widget("apex_kills", kills=int(partie), total=max(0, int(total)),
                          games=max(0, int(parties)), rp=gagnes)
        logger.info("Overlay : bilan de partie — {k} kill(s), {t} sur le live{r}",
                    k=partie, t=total,
                    r=f", {gagnes:+d} RP" if gagnes is not None else "")
        return True

    def show_counter(self, text: str) -> bool:
        """Montre un compteur qui vient de monter, si le budget le permet.

        Silencieux en cas de refus : le compteur a déjà été incrémenté en base,
        c'est l'AFFICHAGE qu'on rationne — un gag qui tombe dix fois en deux
        minutes ne doit pas monopoliser l'écran.
        """
        if not self._may_react():
            return False
        self._last_event_at = time.monotonic()
        self._feed.widget("counter", text=ecourter(str(text), 40))
        return True

    # ── bingo du stream (widget 20) ───────────────────────────────────────

    def start_bingo(self, cells: list[str]) -> bool:
        """Ouvre une grille de bingo pour le live.

        Jusqu'à 9 cases, en grille de trois colonnes : un widget occupe toute la
        zone et fait s'effacer l'avatar comme la bulle, il n'a personne à ménager.
        """
        cells = [str(c).strip()[:34] for c in (cells or []) if str(c).strip()][:9]
        if len(cells) < 2 or not self._live():
            return False
        self._bingo = {"cells": cells, "done": [False] * len(cells)}
        self._feed.widget("bingo", cells=cells, done=list(self._bingo["done"]))
        logger.info("Overlay: bingo ouvert ({n} cases)", n=len(cells))
        self._planifier_flush()
        return True

    def show_bingo(self) -> Optional[dict]:
        """Réaffiche la grille en cours, sur demande."""
        if not self._bingo or not self._live():
            return None
        self._bingo_reminded_at = time.monotonic()
        self._feed.widget("bingo", cells=self._bingo["cells"],
                          done=list(self._bingo["done"]), duration=10)
        return {"widget": "bingo", "cells": self._bingo["cells"]}

    def _bingo_index(self, needle) -> Optional[int]:
        """Retrouve une case par son numéro OU par son intitulé.

        Le modèle ne voit pas la grille : lui demander un index de mémoire est
        le meilleur moyen qu'il coche la mauvaise case.
        """
        bingo = self._bingo
        if not bingo:
            return None
        try:
            return int(needle)
        except (TypeError, ValueError):
            pass
        words = [w for w in self._fold(str(needle)).split() if len(w) > 2]
        if not words:
            return None
        for i, cell in enumerate(bingo["cells"]):
            folded = self._fold(cell)
            if all(w in folded for w in words):
                return i
        # À défaut d'une correspondance complète, la case qui partage le plus
        # de mots — « le ping » doit trouver « il blâme le ping ».
        scores = [(sum(1 for w in words if w in self._fold(c)), i)
                  for i, c in enumerate(bingo["cells"])]
        best, index = max(scores)
        return index if best else None

    def check_bingo(self, index) -> Optional[dict]:
        """Coche une case. Retourne None si rien n'a changé — le widget ne doit
        pas réapparaître pour une case déjà cochée."""
        bingo = self._bingo
        if not bingo:
            return None
        i = self._bingo_index(index)
        if i is None:
            return None
        if not 0 <= i < len(bingo["cells"]) or bingo["done"][i]:
            return None
        bingo["done"][i] = True
        full = all(bingo["done"])
        self._feed.widget("bingo", cells=bingo["cells"], done=list(bingo["done"]),
                          just=i, full=full, duration=12)
        logger.info("Overlay: bingo — « {c} » cochée{f}",
                    c=bingo["cells"][i], f=" (grille complète)" if full else "")
        coche = bingo["cells"][i]
        # Une grille complète est TERMINÉE. Elle restait pourtant en place :
        # injectée dans chaque prompt et réaffichée toutes les dix minutes pour
        # le reste du live, alors qu'il n'y a plus rien à y cocher.
        if full:
            self._bingo = None
            self._bingo_reminded_at = 0.0
        self._planifier_flush()
        return {"widget": "bingo", "checked": coche, "full": full}

    # ── pendu ─────────────────────────────────────────────────────────────

    _HANGMAN_MAX_MISSES = 6   # tête, corps, deux bras, deux jambes

    @staticmethod
    def _fold(text: str) -> str:
        """Minuscules sans accents : « FLÈCHE » et « fleche » sont le même mot."""
        text = unicodedata.normalize("NFD", (text or "").lower())
        return "".join(c for c in text if unicodedata.category(c) != "Mn")

    def _release_hangman_secret(self) -> None:
        """Lève le filet du pendu en cours, s'il y en a un.

        Point de levée UNIQUE, en regard du `guard_secret` unique de
        `start_hangman`. Les cinq chemins qui oublient une partie (victoire,
        défaite, abandon, remplacement, nouveau live) passent par ici : un
        sixième qui écrirait `self._hangman = None` tout seul rendrait le mot
        muet pour de bon, et la panne serait invisible.
        """
        if self._hangman:
            release_secret(self._hangman["display"])

    def start_hangman(self, word: str, hint: str = "") -> bool:
        """Ouvre une partie. Le mot n'est jamais publié — seules ses lettres le sont."""
        folded = self._fold(word)
        letters = [c for c in folded if c.isalpha()]
        if len(letters) < 3 or len(letters) > 16 or not self._live():
            return False
        # Une partie déjà ouverte est remplacée : lever son filet AVANT de
        # l'oublier, sinon son mot reste interdit en sortie pour toujours.
        self._release_hangman_secret()
        self._hangman = {
            "word": folded,
            "display": " ".join(word.split())[:40],
            "hint": " ".join((hint or "").split())[:60],
            "found": set(),
            "missed": [],
        }
        # Ceinture : le mot est dans son contexte pour qu'il puisse animer la
        # partie, un filtre l'empêche de le publier (bot/core/secret_guard.py).
        #
        # Posé sur `display`, jamais sur `word` : c'est `display` que TOUTES les
        # levées passent à `release_secret`. `_fold` normalise la casse et les
        # accents, pas les espaces — « rocket  league » posé et « rocket league »
        # levé sont deux clés différentes, et le `pop()` échouait sans un bruit.
        guard_secret(self._hangman["display"])
        self._publish_hangman()
        logger.info("Overlay: pendu ouvert ({n} lettres)", n=len(set(letters)))
        self._planifier_flush()
        return True

    def _count_hangman(self, author: str, text: str) -> None:
        """Une proposition = UNE lettre seule. Sinon tout message en contiendrait."""
        game = self._hangman
        if not game:
            return
        token = self._fold(text).strip()
        # Le MOT ENTIER, pour qui l'a trouvé : épeler les lettres qui restent
        # quand on a déjà la réponse n'est plus un jeu, c'est une formalité —
        # et le chat se faisait doubler par le premier qui tapait vite.
        #
        # SEULE l'égalité exacte compte. Un mot faux n'est pas une proposition
        # ratée, c'est un message ordinaire : le pénaliser ferait perdre la
        # partie à coups de phrases de chat, et il n'existe aucun moyen de
        # distinguer « chaussette » proposé de « chaussette » raconté.
        #
        # Les espaces sont recollés des DEUX côtés : `_fold` normalise la casse
        # et les accents, pas eux — « rocket  league » posé et « rocket league »
        # tapé sont le même mot, et l'un ne doit pas rater l'autre.
        if token and " ".join(token.split()) == " ".join(game["word"].split()):
            game["found"].update(c for c in game["word"] if c.isalpha())
            # Même ordre que la victoire lettre par lettre : le filet tombe
            # AVANT la publication qui révèle le mot, sinon l'écran affiche
            # « […] » à la place de ce qu'on vient de trouver.
            self._release_hangman_secret()
            self._publish_hangman(last=token, won=True)
            logger.info("Overlay: pendu gagné d'un coup par le chat ({w})",
                        w=game["display"])
            self._hangman = None
            self._planifier_flush()
            return
        if len(token) != 1 or not token.isalpha():
            return
        if token in game["found"] or token in game["missed"]:
            return
        if token in game["word"]:
            game["found"].add(token)
            won = all(c in game["found"] for c in game["word"] if c.isalpha())
            # Le secret est levé AVANT la publication finale : c'est cet
            # événement-là qui révèle le mot, et le filet de sortie le masquerait
            # (« […] »). La partie est finie, il n'y a plus rien à protéger.
            if won:
                self._release_hangman_secret()
            self._publish_hangman(last=token, won=won)
            if won:
                logger.info("Overlay: pendu gagné par le chat ({w})", w=game["display"])
                self._hangman = None
            # Chaque coup compte : reprendre la partie au redémarrage sans les
            # lettres déjà trouvées la ferait recommencer sous les yeux du chat.
            self._planifier_flush()
            return
        game["missed"].append(token)
        lost = len(game["missed"]) >= self._HANGMAN_MAX_MISSES
        if lost:
            self._release_hangman_secret()
        self._publish_hangman(last=token, lost=lost)
        if lost:
            logger.info("Overlay: pendu perdu ({w})", w=game["display"])
            self._hangman = None
        self._planifier_flush()

    def _publish_hangman(self, last: str = "", won: bool = False, lost: bool = False) -> None:
        game = self._hangman
        if not game:
            return
        # Le mot part lettre par lettre, masquée tant qu'elle n'est pas trouvée.
        mask = [
            (c if (not c.isalpha() or c in game["found"] or won or lost) else "")
            for c in game["word"]
        ]
        # L'indice est un SECOURS, pas une ouverture : le donner au lancement
        # (ce que faisait ce widget) revient à résoudre le pendu à la place du
        # chat. Il n'apparaît qu'à deux essais restants — ou à la fin, où il
        # n'aide plus personne mais dit ce qu'on cherchait.
        en_difficulte = len(game["missed"]) >= self._HANGMAN_MAX_MISSES - 2
        hint = game["hint"] if (en_difficulte or won or lost) else ""
        self._feed.widget(
            # Une partie en cours ne s'efface pas toute seule : dix secondes,
            # c'est la durée d'un résultat qu'on lit, pas d'un jeu qu'on joue.
            # Gagné ou perdu, elle redevient un résultat.
            "hangman", sticky=not (won or lost),
            mask=mask, missed=list(game["missed"]),
            misses=len(game["missed"]), max_misses=self._HANGMAN_MAX_MISSES,
            hint=hint, last=last, won=won, lost=lost,
            word=game["display"] if (won or lost) else "",
            duration=12 if (won or lost) else 10,
        )

    # ── chifoumi : un duel, Wally contre celui qui demande ────────────────

    _RPS_MOVES = _RPS_MOVES      # alias : les appels internes restent en `self.`
    # Ce que chaque coup bat : sert à trancher sans table de vérité à rallonge.
    _RPS_BEATS = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}

    def play_rps(self, opponent: str = "", move: str = "") -> Optional[dict]:
        """Un duel : les deux coups sont tirés, le vainqueur s'affiche.

        `move` impose celui de Wally — le tirage se fait ici et non dans le
        navigateur, c'est ce qui lui permet de tricher. `opponent` est la
        personne qui a demandé à jouer ; il vient de l'appelant, pas du modèle.
        """
        if not self._live():
            return None
        mine = move if move in self._RPS_MOVES else random.choice(self._RPS_MOVES)
        theirs = random.choice(self._RPS_MOVES)
        if mine == theirs:
            outcome = "draw"
        elif self._RPS_BEATS[mine] == theirs:
            outcome = "wally"
        else:
            outcome = "opponent"
        opponent = opponent or "le chat"
        self._feed.widget("rps", mine=mine, theirs=theirs, opponent=opponent,
                          outcome=outcome, duration=10)
        logger.info("Overlay: chifoumi — {o} {t} / Wally {m} → {r}",
                    o=opponent, t=theirs, m=mine, r=outcome)
        return {"widget": "rps", "mine": mine, "theirs": theirs,
                "opponent": opponent, "outcome": outcome}

    # ── sondage (widget 6) ────────────────────────────────────────────────

    def start_poll(
        self, question: str, options: list[str], seconds: int = _POLL_DEFAULT_S
    ) -> bool:
        """Ouvre un sondage : les viewers votent en tapant le numéro dans le chat."""
        question = (question or "").strip()
        options = [str(o).strip()[:24] for o in (options or []) if str(o).strip()][:4]
        if not question or len(options) < 2 or not self._live():
            return False
        # Clore celui d'avant avant de l'écraser : sinon ses votes partaient à la
        # poubelle sans gagnant, et `_last_poll` gardait le résultat de l'avant-
        # dernier — que `poll_result_line()` réinjecte dans le prompt. « Alors, ça
        # a donné quoi ? » répondait à côté.
        if self._poll is not None:
            self.close_poll()
        seconds = max(5, min(120, int(seconds or _POLL_DEFAULT_S)))
        self._poll = {
            "question": question[:80],
            "options": options,
            "votes": {},                      # votant → index (un vote par personne)
            "ends_at": time.monotonic() + seconds,
        }
        self._publish_poll(seconds)
        # Clôture planifiée : sans elle, le dépouillement s'effacerait sans
        # jamais annoncer de gagnant, et Wally ne saurait pas quoi répondre si on
        # lui demande le résultat.
        self._schedule_poll_close(seconds)
        # Rangé tout de suite : un sondage dure jusqu'à deux minutes, et un
        # rebuild tombe volontiers pile dedans.
        self._planifier_flush()
        return True

    def _schedule_poll_close(self, seconds: int) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._poll_task = None      # hors boucle (tests synchrones)
            return
        self._poll_task = loop.create_task(self._close_poll_after(seconds))

    async def _close_poll_after(self, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
            self.close_poll()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("Overlay: clôture du sondage en erreur: {e!r}", e=exc)

    def close_poll(self) -> Optional[dict]:
        """Termine le sondage : gagnant à l'écran, résultat retenu.

        Le résultat est aussi consigné dans le flux du stream, sans réveiller le
        narrateur : c'est ce qui le rend visible dans le prompt, donc répondable
        quand quelqu'un demande « alors, ça a donné quoi ? ».
        """
        poll = self._poll
        if not poll:
            return None
        tally = [0] * len(poll["options"])
        for index in poll["votes"].values():
            tally[index] += 1
        total = sum(tally)
        best = max(range(len(tally)), key=lambda i: tally[i]) if total else None
        # Égalité en tête : il n'y a pas de gagnant à désigner. La condition
        # porte sur `best` et non sur `total` — les deux disent la même chose
        # (pas de vote, pas de tête), mais celle-ci le dit là où on s'en sert.
        tied = best is not None and tally.count(tally[best]) > 1
        result = {
            "question": poll["question"],
            "options": list(poll["options"]),
            "tally": tally,
            "total": total,
            "winner": None if (best is None or tied) else poll["options"][best],
            "tied": tied,
        }
        self._last_poll = result
        self._poll = None
        self._feed.widget(
            "poll",
            question=poll["question"],
            options=poll["options"],
            tally=tally,
            seconds=0,
            final=True,
            winner=-1 if (best is None or tied) else best,
            duration=8,          # le résultat reste lisible avant de s'effacer
        )
        feed = self._stream_feed
        if feed is None:
            from bot.core.stream_feed import active_stream_feed
            feed = active_stream_feed()
        if feed is not None:
            try:
                feed.record(self.poll_result_line(), notify=False)
            except Exception as exc:  # noqa: BLE001 — jamais bloquant
                logger.debug("Overlay: résultat du sondage non consigné: {e!r}", e=exc)
        logger.info("Overlay: sondage clos — {r}", r=self.poll_result_line())
        # Le résultat est ce que Wally répondra à « ça a donné quoi ? » : il doit
        # survivre au rebuild autant que le sondage lui-même.
        self._planifier_flush()
        return result

    def poll_result_line(self) -> str:
        """Le dernier résultat, en une phrase — vide s'il n'y en a jamais eu."""
        r = self._last_poll
        if not r:
            return ""
        if not r["total"]:
            return f"Sondage « {r['question']} » : personne n'a voté."
        detail = ", ".join(
            f"{o} {n}" for o, n in zip(r["options"], r["tally"])
        )
        if r["tied"]:
            return f"Sondage « {r['question']} » : égalité ({detail})."
        return (f"Sondage « {r['question']} » : {r['winner']} l'emporte "
                f"({detail}, {r['total']} votes).")

    # Ce qu'on entend à l'oral pour un vote. Le chat tape « 1 » ; en vocal on dit
    # « un », « le premier », ou simplement « oui » / « non » sur deux options.
    _SPOKEN_NUMBERS = {
        "un": 1, "une": 1, "premier": 1, "premiere": 1, "oui": 1,
        "deux": 2, "second": 2, "seconde": 2, "deuxieme": 2, "non": 2,
        "trois": 3, "troisieme": 3,
        "quatre": 4, "quatrieme": 4,
    }

    def count_spoken_vote(self, author: str, text: str) -> bool:
        """Compte un vote entendu en VOCAL pendant un sondage.

        Plus permissif que le chat : une phrase parlée n'est jamais réduite à un
        chiffre (« bah moi je dis deux »), et la transcription accentue mal. On
        cherche donc un mot de vote dans la phrase, à condition qu'elle soit
        courte — au-delà, « deux » parle sûrement d'autre chose.
        """
        poll = self._poll
        if not poll or time.monotonic() > poll["ends_at"]:
            return False
        words = self._fold(text).split()
        if not words or len(words) > 8:
            return False
        index = None
        for word in words:
            if word.isdigit() and 1 <= int(word) <= len(poll["options"]):
                index = int(word) - 1
                break
            spoken = self._SPOKEN_NUMBERS.get(word)
            if spoken is not None and spoken <= len(poll["options"]):
                index = spoken - 1
                break
        if index is None:
            # Dernier recours : le libellé de l'option, prononcé tel quel.
            for i, option in enumerate(poll["options"]):
                folded = self._fold(option)
                if folded and folded in self._fold(text):
                    index = i
                    break
        if index is None:
            return False
        voter = author.lower()
        if poll["votes"].get(voter) == index:
            return False
        poll["votes"][voter] = index
        self._publish_poll(max(1, int(poll["ends_at"] - time.monotonic())))
        logger.info("Sondage : vote vocal de {a} → {n}", a=author, n=index + 1)
        self._planifier_flush()
        return True

    def _count_vote(self, author: str, text: str) -> None:
        poll = self._poll
        if not poll:
            return
        if time.monotonic() > poll["ends_at"]:
            self.close_poll()      # la tâche a pu être manquée : on clôt ici
            return
        # Un vote = le seul chiffre du message. « 1 » compte, « j'ai 2 chats » non.
        token = (text or "").strip()
        if not token.isdigit():
            return
        index = int(token) - 1
        if not 0 <= index < len(poll["options"]):
            return
        voter = author.lower()
        if poll["votes"].get(voter) == index:
            return  # déjà ce vote : rien de neuf à publier
        poll["votes"][voter] = index          # un changement d'avis remplace
        self._publish_poll(max(1, int(poll["ends_at"] - time.monotonic())))
        # Un vote perdu est un viewer qui a voté pour rien. L'écriture est bornée
        # par le sondage lui-même (deux minutes au plus), pas par le débit du
        # chat — les messages qui ne sont pas un vote sortent bien avant ici.
        self._planifier_flush()

    def _publish_poll(self, seconds_left: int) -> None:
        poll = self._poll
        if not poll:
            return
        tally = [0] * len(poll["options"])
        for index in poll["votes"].values():
            tally[index] += 1
        self._feed.widget(
            "poll",
            question=poll["question"],
            options=poll["options"],
            tally=tally,
            seconds=seconds_left,
            duration=seconds_left + 4,        # laisse le résultat à l'écran
        )

    def _uptime_label(self) -> Optional[str]:
        """« en live depuis 3h12 », calculé depuis le statut du stream.

        Un viewer demande la durée dans le chat, le compteur s'affiche quelques
        secondes puis disparaît — il n'est pas permanent à l'écran.
        """
        if self._stream_status is None:
            return None
        try:
            started = (self._stream_status() or {}).get("started_at")
        except Exception:  # noqa: BLE001
            return None
        if not started:
            return None
        try:
            begin = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - begin
        except (TypeError, ValueError):
            return None
        minutes = max(0, int(elapsed.total_seconds() // 60))
        if minutes < 60:
            return f"en live depuis {minutes} min"
        return f"en live depuis {minutes // 60}h{minutes % 60:02d}"

    async def _condense(self, text: str, system: Optional[str] = None,
                        *, source: str = "", trace: str = "") -> Optional[str]:
        depart = time.monotonic()
        # Rendu ICI et pas au chargement : ces prompts sont des constantes de
        # module, lues avant que l'identité ne soit posée (`render=False`). Le
        # modèle recevait donc « la réaction de {{BOT_NAME}} » en toutes
        # lettres — même patron que `emotion.py`, qui rend au moment de l'appel.
        from bot.intelligence.identity import render_identity

        raw = await self._llm.complete(
            render_identity(system or _CONDENSE_SYSTEM),
            [{"role": "user", "content": text}],
            purpose="overlay_thought",
        )
        # `nettoyer_decorations` retire aussi les backticks : le prompt épelle le
        # marqueur entre backticks, et le modèle les reprenait autour de sa PHRASE
        # — l'overlay ne rend pas le Markdown, ils s'affichaient tels quels.
        short = nettoyer_decorations(raw)
        # Le prompt répond RIEN quand la pensée n'a aucun intérêt pour un
        # spectateur — se taire est une réponse valide. Le marqueur se lit aussi
        # en FIN de texte : « C'est le genre de moment où l'on se tait. RIEN »
        # partait à l'écran, marqueur compris (12 fois en 5 jours).
        # En INFO : une pensée qui n'arrive jamais à l'écran est invisible dans
        # les logs, et on ne sait pas si c'est le budget, le « RIEN » ou la
        # longueur qui l'a retenue.
        condense_ms = int((time.monotonic() - depart) * 1000)
        if not short or marqueur_de_service(short, "RIEN"):
            logger.info("Overlay: pensée jugée sans intérêt pour le public (RIEN)")
            # Le motif seul ne dit RIEN du filtre : sans le texte écarté, on ne
            # peut pas savoir s'il jette le mordant et garde le fade. C'était
            # 424 lignes muettes en une journée.
            self._journal(
                "overlay_rejected", source, text, trace_id=trace,
                motif="sans intérêt pour le public (RIEN)" if short else "modèle muet",
                candidat=short, condense_ms=condense_ms,
            )
            return None
        if len(short) > _MAX_BUBBLE_CHARS:
            logger.info("Overlay: condensation trop longue ({n} car) : {t}",
                        n=len(short), t=short[:80])
            self._journal(
                "overlay_rejected", source, text, trace_id=trace,
                motif=f"condensation trop longue ({len(short)} car)",
                candidat=short, condense_ms=condense_ms,
            )
            return None
        return short
