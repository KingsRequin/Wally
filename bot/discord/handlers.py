# bot/discord/handlers.py
from __future__ import annotations

import asyncio
import difflib
import json
import random
import re
import time
from collections import deque
from typing import TYPE_CHECKING

import discord
from loguru import logger

from bot.core.notes_tool import run_save_note_tool
from bot.core.surnoms import REFUS as REFUS_SURNOM, detecter as _detecter_surnom
from bot.core.audit_log import observe_event
from bot.core.history_search import DEFAULT_LIMIT as HISTORY_SEARCH_DEFAULT_LIMIT
from bot.core.llm import FALLBACK_RESPONSE
from bot.core.follow_tool import FOLLOW_TOOL, api_twitch, run_follow_tool
from bot.core.music_tool import MUSIC_TOOL, run_music_tool
from bot.core.secret_guard import redact
from bot.core.text_clean import strip_stage_directions
from bot.discord.message_split import split_for_discord
from bot.intelligence import pending_question, thread_sense
from bot.intelligence.prompts import (
    assemble_memory_context,
    build_session_recall_block,
    load_prompt,
    marqueur_de_service,
)
from bot.intelligence.self_fix import UpgradeRequest

try:
    from bot.discord.voice.tools import (
        SAY_IN_VOICE_TOOL, VOICE_TOOLS, run_say_in_voice_tool,
    )
    _VOCAL_DISPO = True
except ImportError:
    # Sans la brique vocale, la liste est vide et rien ne doit être proposé. Un
    # DRAPEAU plutôt qu'un `= None` sur chaque symbole : réassigner un nom
    # importé lui fait perdre son type, et un `None` glissé dans la liste
    # d'outils ferait échouer TOUS les appels, même sans rapport avec le vocal.
    VOICE_TOOLS = []
    _VOCAL_DISPO = False

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

TIMEOUT_REACTIONS = ["💩", "⛔", "😤", "🙅", "😒"]

# Emojis jugés assez marquants pour être signalés à Wally quand ils sont posés
# sur le message d'un AUTRE membre (les réactions sur ses propres messages sont
# toujours signalées, peu importe l'emoji).
NOTABLE_REACTION_EMOJIS = {
    "😂", "🤣", "❤️", "❤", "🔥", "💀", "😭", "👏", "💯",
    "😱", "🤯", "👀", "😡", "🤮", "💩", "⛔", "😤",
}

_NOTE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_persistent_note",
            "description": (
                "Quand quelqu'un te demande de retenir, noter ou mémoriser quelque chose "
                "qui concerne tout le serveur ou la communauté (un événement, une règle, "
                "une info partagée, un engagement que tu prends), utilise cet outil. "
                "La note sera injectée dans TOUTES tes futures conversations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre court et unique de la note"},
                    "content": {"type": "string", "description": "Contenu de la note"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_persistent_note",
            "description": "Supprimer une note persistante par son titre",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre exact de la note à supprimer"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_user_memory",
            "description": (
                "Quand quelqu'un te demande de retenir, noter ou mémoriser quelque chose "
                "qui le concerne personnellement (préférence, fait biographique, opinion, "
                "habitude, info privée), utilise cet outil. Le souvenir sera associé "
                "uniquement à cet utilisateur."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Fait ou information à retenir sur cet utilisateur, formulé comme une phrase factuelle courte",
                    },
                },
                "required": ["content"],
            },
        },
    },
]

# Overlay du stream, dans une conversation. La définition vit avec le narrateur :
# le chemin vocal l'utilise aussi, et deux copies divergeraient.
from bot.core.apex.tool import APEX_OVERLAY_TOOL as _APEX_OVERLAY_TOOL
from bot.intelligence.overlay_narrator import (
    CANCEL_TARGETS,
    CANCEL_TOOL_SPEC as _OVERLAY_CANCEL_TOOL,
    LAST_CLIP_TOOL_SPEC as _LAST_CLIP_TOOL,
    planning_url,
    spec_overlay_pour as _spec_overlay_pour,
)


PLANNING_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "show_planning",
        "description": (
            "Donne le planning des streams — les jours et horaires où le "
            "streamer est en live. Appelle-le dès qu'on demande quand est le "
            "prochain stream, les horaires, le programme de la semaine. Il te "
            "rend le LIEN de l'image : donne-le tel quel, Discord en fait un "
            "aperçu tout seul. Si un live est en cours, l'image s'affiche EN "
            "PLUS sur l'overlay — l'outil te dit si ça a été le cas. Ne "
            "prétends jamais l'avoir affichée s'il te dit le contraire, et "
            "n'invente jamais d'horaires : tu ne connais que cette image."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "comment": {
                    "type": "string",
                    "description": "Ta réplique, quelques mots. Optionnelle.",
                },
            },
        },
    },
}



_TALLY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "start_counting",
            "description": (
                "Ouvrir un compteur quand on te demande de compter quelque chose "
                "(« compte combien de fois Azra dit qu'il a pas rechargé »). Tu "
                "traduis la demande en FORMULATIONS : les tournures exactes qu'on "
                "entendra vraiment. C'est le seul moment où tu réfléchis — ensuite "
                "le comptage est automatique, y compris d'un live à l'autre. "
                "Relancer un compteur existant reprend son total, il ne repart pas "
                "de zéro."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Nom court et parlant, ex. « pas rechargé »."},
                    "keywords": {
                        "type": "array", "items": {"type": "string"},
                        "description": (
                            "2 à 8 tournures réellement prononcées, sans ponctuation : "
                            "« pas recharge », « plus de balles », « chargeur vide ». "
                            "Évite les mots trop courts ou trop communs, ils compteraient à tort."
                        ),
                    },
                    "target": {"type": "string", "description": "Qui est visé, si c'est quelqu'un en particulier."},
                },
                "required": ["label", "keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_counting",
            "description": "Arrêter un compteur. Son total reste consultable, il n'est pas effacé.",
            "parameters": {
                "type": "object",
                "properties": {"label": {"type": "string", "description": "Le nom du compteur."}},
                "required": ["label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_counters",
            "description": (
                "Lister ce que tu comptes et où en sont les totaux. À utiliser dès "
                "qu'on te demande « tu comptes quoi ? » ou « ça en est où ? » — "
                "n'invente jamais un total de mémoire."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


_PREDICT_TOOL = {
    "type": "function",
    "function": {
        "name": "predict",
        "description": (
            "Parier sur l'issue d'une partie, puis trancher quand tu la connais. "
            "Sans `outcome`, tu ouvres un pari (`bet`). Avec `outcome`, tu tranches "
            "celui en cours : « right » si tu avais vu juste, « wrong » sinon. "
            "AUCUNE source ne te dit si une partie est gagnée — c'est toi qui "
            "constates, en écoutant le vocal et en lisant le chat. Tranche quand tu "
            "es sûr, et assume : ton score cumulé se voit à l'écran. Ne t'attribue "
            "jamais un point sans avoir parié avant. ⚠️ Un seul pari à la fois : en "
            "ouvrir un nouveau ABANDONNE celui en cours, qui ne comptera plus — "
            "l'outil te dira lequel tu viens de perdre. Tranche avant d'en relancer un."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bet": {"type": "string", "description": "Ton pronostic, court, ex. « on finit top 3 »."},
                "outcome": {
                    "type": "string", "enum": ["right", "wrong"],
                    "description": "Pour trancher le pari en cours.",
                },
            },
        },
    },
}


async def run_predict_tool(bot, args: dict) -> str:
    """Ouvre ou tranche un pari. Le score vient de la base, jamais du modèle."""
    predictions = getattr(bot, "predictions", None)
    narrator = _overlay_narrator(bot)
    if predictions is None:
        return json.dumps({"status": "unavailable",
                           "message": "Les paris ne sont pas disponibles."})
    try:
        outcome = (args.get("outcome") or "").strip()
        if outcome in ("right", "wrong"):
            row = await predictions.resolve(outcome == "right")
            if row is None:
                return json.dumps({"status": "no_bet", "message": (
                    "Tu n'as aucun pari en cours — tu ne peux pas trancher."
                )})
            # Retour vérifié : hors live rien ne s'affiche, et l'annoncer serait
            # une hallucination (cf. `show_quote`).
            shown = narrator is not None and narrator.show_prediction(
                row["bet"], outcome=outcome, right=row["right"], total=row["total"])
            verdict = "vu juste" if outcome == "right" else "planté"
            return json.dumps({"status": "ok", "message": (
                f"Pari tranché : tu t'es {verdict}. Score : {row['right']}/{row['total']}. "
                + ("Annonce-le." if shown else "Rien à l'écran (pas de live).")
            )})
        row = await predictions.open(args.get("bet", ""))
        if row is None:
            return json.dumps({"status": "rejected", "message": "Il faut un pronostic."})
        score = await predictions.score()
        shown = narrator is not None and narrator.show_prediction(
            row["bet"], right=score["right"], total=score["total"])
        # Un pari en remplace un autre : le DIRE. Sans ça Wally continuait de
        # défendre un pronostic déjà classé sans suite — il n'avait aucun moyen
        # de savoir qu'il venait de l'abandonner lui-même.
        abandonne = str(row.get("voided") or "")
        return json.dumps({"status": "ok", "message": (
            f"Pari ouvert : « {row['bet']} ». Tranche-le quand tu connaîtras l'issue."
            + (f" ⚠️ Ton pari précédent, « {abandonne} », est abandonné du même "
               "coup : il ne comptera pas, et tu ne pourras plus le trancher."
               if abandonne else "")
            + ("" if shown else " Rien à l'écran (pas de live).")
        )})
    except Exception as exc:  # noqa: BLE001 — un pari ne casse pas la réponse
        logger.warning("Prédiction a échoué : {e!r}", e=exc)
        return json.dumps({"status": "error", "message": "L'opération a échoué."})


# Assez haut pour qu'une absence de la liste VEUILLE dire quelque chose : à 8,
# le défaut de `roster()`, Wally aurait pris une troncature pour un départ.
_PRESENCE_LIMITE = 25

_PRESENCE_TOOL = {
    "type": "function",
    "function": {
        "name": "who_is_online",
        "description": (
            "Qui est connecté sur le Discord de la communauté, à l'instant : "
            "leur statut (en ligne, absent, ne pas déranger) et ce qu'ils font "
            "s'ils le partagent. Appelle-le quand on te demande qui est là, si "
            "quelqu'un est connecté, ou avant de proposer de déranger "
            "quelqu'un. Ne DEVINE jamais une présence de mémoire : quelqu'un "
            "qui a écrit il y a une heure peut être parti depuis."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


def _presence_service(bot):
    """Le service de présence, vu depuis l'une OU l'autre plateforme.

    `WallyDiscord` le porte ; `WallyTwitch` ne l'atteint que par `discord_bot`,
    comme il atteint déjà `voice_service` pour `say_in_voice`.
    """
    return (getattr(bot, "presence", None)
            or getattr(getattr(bot, "discord_bot", None), "presence", None))


def run_presence_tool(bot, args: dict) -> str:
    """Qui est en ligne. Lecture seule, jamais bloquant.

    `PresenceService` alimentait déjà `AttentionContext` — donc la COGNITION
    voyait les statuts, mais pas le chemin de RÉPONSE. D'où « je peux pas voir
    qui est en ligne, connecté, idle, tout ça » relevé dans les traces, dit par
    un bot qui recevait l'information à chaque tick.

    Le plafond est celui de `roster()` mais relevé : à 8, une absence de la
    liste ne prouvait rien, et Wally aurait conclu « il est pas là » d'une
    troncature. On dit explicitement quand la liste est coupée.
    """
    service = _presence_service(bot)
    if service is None or not service.enabled:
        return json.dumps({"status": "unavailable", "message": (
            "Je ne vois pas les présences du serveur en ce moment.")})
    lignes = service.roster(limit=_PRESENCE_LIMITE)
    if not lignes:
        return json.dumps({"status": "nothing", "message": (
            "Personne de connecté sur le serveur, ou je ne vois rien. "
            "Ne nomme personne.")})
    tronque = len(lignes) >= _PRESENCE_LIMITE
    fin = (" La liste est COUPÉE : ne conclus pas que quelqu'un est absent "
           "parce qu'il n'y figure pas." if tronque else
           " C'est la liste COMPLÈTE : qui n'y est pas est hors ligne.")
    return json.dumps({"status": "ok", "message": (
        "Connectés à l'instant — " + " · ".join(lignes) + "." + fin)})


_QUOTE_TOOL = {
    "type": "function",
    "function": {
        "name": "quote",
        "description": (
            "Retenir une réplique marquante entendue en vocal, ou en ressortir "
            "une d'avant. Sans `recall`, tu enregistres ET affiches ce que "
            "quelqu'un vient de dire — cite ses mots tels que tu les as ENTENDUS, "
            "n'invente jamais une phrase qu'on n'a pas prononcée. Avec "
            "`recall: true`, tu ressors une citation plus ancienne : c'est le "
            "décalage qui fait rire, surtout quand plus personne n'y pense."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "author": {"type": "string", "description": "Qui l'a dit."},
                "text": {"type": "string", "description": "Ses mots exacts, courts."},
                "recall": {"type": "boolean", "description": "Ressortir une ancienne citation."},
            },
        },
    },
}


async def run_quote_tool(bot, args: dict) -> str:
    """Enregistre ou ressort une citation. Le texte vient de ce que Wally a
    entendu — la base ne peut pas le vérifier, seul le prompt le lui rappelle."""
    book = getattr(bot, "quotes", None)
    if book is None:
        return json.dumps({"status": "unavailable",
                           "message": "Le carnet de citations n'est pas disponible."})
    narrator = _overlay_narrator(bot)
    try:
        asked_author = str(args.get("author") or "").strip()
        if args.get("recall"):
            row = await book.recall(asked_author)
            if row is None:
                # Deux cas distincts, deux messages : « rien de cette personne »
                # n'est pas « le carnet est vide », et les confondre faisait dire
                # à Wally qu'il n'avait rien retenu alors que la base était pleine.
                if asked_author and await book.count():
                    return json.dumps({"status": "empty", "message": (
                        f"Tu n'as rien retenu de {asked_author}."
                    )})
                return json.dumps({"status": "empty", "message": (
                    "Tu n'as encore retenu aucune citation."
                )})
            when = _quote_age(row.get("created_at"))
            # L'affichage est VÉRIFIÉ avant d'être annoncé : `show_quote` renvoie
            # False hors live. Sans ça Wally annonçait « à l'écran » pendant qu'un
            # DM n'affichait rien — et `shown_at`, marqué en amont, brûlait la
            # rotation des citations les moins vues.
            shown = narrator is not None and narrator.show_quote(
                row["author"], row["text"], age=when)
            if not shown:
                return json.dumps({"status": "offline", "message": (
                    f"Rien à l'écran (pas de live). Tu te souviens de : "
                    f"« {row['text']} » — {row['author']}, {when}."
                )})
            if row.get("id") is not None:
                await book.mark_shown(row["id"])
            return json.dumps({"status": "ok", "message": (
                f"À l'écran : « {row['text']} » — {row['author']}, {when}."
            )})
        row = await book.add(asked_author, str(args.get("text") or ""))
        if row is None:
            return json.dumps({"status": "rejected",
                               "message": "Il faut un auteur et une phrase."})
        shown = narrator is not None and narrator.show_quote(row["author"], row["text"])
        total = await book.count()
        return json.dumps({"status": "ok", "message": (
            f"Citation retenue ({total} en tout)"
            + (" et affichée." if shown else ", pas affichée : pas de live.")
        )})
    except Exception as exc:  # noqa: BLE001 — une citation ne casse pas la réponse
        logger.warning("Citation a échoué : {e!r}", e=exc)
        return json.dumps({"status": "error", "message": "L'opération a échoué."})


def _quote_age(created_at) -> str:
    """« tout à l'heure », « hier », « il y a 3 jours » — le décalage fait la blague."""
    try:
        delta = time.time() - float(created_at)
    except (TypeError, ValueError):
        return ""
    if delta < 3600:
        return "tout à l'heure"
    if delta < 86400:
        return "plus tôt aujourd'hui"
    days = int(delta // 86400)
    return "hier" if days == 1 else f"il y a {days} jours"


async def run_tally_tool(bot, name: str, args: dict) -> str:
    """Exécute un outil de comptage. Compte rendu honnête : les totaux viennent
    de la base, jamais du modèle."""
    tally = getattr(bot, "tally", None)
    if tally is None:
        return json.dumps({"status": "unavailable",
                           "message": "Les compteurs ne sont pas disponibles."})
    try:
        if name == "start_counting":
            row = await tally.start(
                args.get("label", ""), args.get("keywords") or [], args.get("target", "")
            )
            if row is None:
                return json.dumps({"status": "rejected", "message": (
                    "Compteur non créé : il faut un nom et au moins une tournure "
                    "d'au moins trois lettres."
                )})
            return json.dumps({"status": "ok", "message": (
                f"Je compte « {row['label']} » à partir de maintenant "
                f"(total actuel : {row['count']})."
            )})
        if name == "stop_counting":
            row = await tally.stop(args.get("label", ""))
            if row is None:
                return json.dumps({"status": "not_found",
                                   "message": "Aucun compteur de ce nom."})
            return json.dumps({"status": "ok", "message": (
                f"Compteur « {row['label']} » arrêté à {row['count']}."
            )})
        if name == "list_counters":
            rows = await tally.list()
            if not rows:
                return json.dumps({"status": "empty", "message": "Tu ne comptes rien pour l'instant."})
            listing = " · ".join(
                f"{r['label']} : {r['count']}" + ("" if r["active"] else " (arrêté)")
                for r in rows
            )
            return json.dumps({"status": "ok", "message": listing})
    except Exception as exc:  # noqa: BLE001 — un compteur ne casse pas la réponse
        logger.warning("Compteur '{n}' a échoué : {e!r}", n=name, e=exc)
        return json.dumps({"status": "error", "message": "L'opération a échoué."})
    return json.dumps({"status": "unknown_tool"})


def _overlay_narrator(bot):
    """Le narrateur vit sur le bot Discord ; le chemin Twitch y accède par
    référence croisée."""
    return getattr(bot, "overlay_narrator", None) or getattr(
        getattr(bot, "discord_bot", None), "overlay_narrator", None
    )


def _overlay_outcome(shown: dict) -> str:
    """Traduit le tirage en fait énonçable.

    Sans ça, l'outil répondait « c'est à l'écran » : Wally lançait le dé sans
    jamais savoir ce qu'il donnait, et ne pouvait donc pas l'annoncer.
    """
    widget = shown.get("widget")
    if widget == "coinflip":
        # heads/tails suit le rendu de l'overlay : P d'un côté, F de l'autre.
        return f"C'est tombé sur {'PILE' if shown.get('result') != 'tails' else 'FACE'}. Annonce-le."
    if widget == "dice":
        values = shown.get("results") or [shown.get("result")]
        if len(values) > 1:
            joined = " et ".join(str(v) for v in values)
            return f"Les dés donnent {joined} (total {sum(values)}). Annonce-le."
        return f"Le dé donne {values[0]}. Annonce-le."
    if widget == "wheel":
        options = shown.get("options") or []
        index = shown.get("index", 0)
        if 0 <= index < len(options):
            return f"La roue s'arrête sur « {options[index]} ». Annonce-le."
    if widget == "poll":
        return ("Le sondage est ouvert, le chat vote en tapant le numéro. Tu "
                "auras le résultat à la fin du décompte — ne l'invente pas d'ici là.")
    if widget == "countdown":
        return f"Compte à rebours lancé sur {shown.get('seconds')} secondes."
    if widget == "gauge":
        return f"Jauge affichée à {shown.get('percent')}%."
    if widget == "stats":
        return (f"Les stats de {shown.get('player') or 'ce joueur'} sont à l'écran. "
                "Commente-les — ne les répète pas telles quelles.")
    if widget == "versus":
        left, right = shown.get("left_value", 0), shown.get("right_value", 0)
        if left == right:
            return "La comparaison est à l'écran : égalité parfaite. Annonce-le."
        gagnant = shown.get("left_name") if left > right else shown.get("right_name")
        return f"La comparaison est à l'écran, {gagnant} devant. Annonce-le."
    # Les neuf widgets ci-dessous retombaient sur « c'est à l'écran » : Wally
    # affichait un podium ou tranchait un chifoumi sans jamais savoir le
    # résultat, et l'annonçait donc au hasard. Le chemin vocal, lui, recevait
    # tout — seul le chemin conversationnel était amputé.
    if widget == "talkers":
        rows = shown.get("rows") or []
        podium = ", ".join(f"{r['name']} ({r['count']})" for r in rows)
        return f"Le podium est à l'écran : {podium}. Annonce-le." if podium else \
               "Le podium est à l'écran."
    if widget == "rps":
        adversaire = shown.get("opponent") or "le chat"
        verdict = {"wally": "tu gagnes", "opponent": f"{adversaire} gagne",
                   "draw": "égalité"}.get(shown.get("outcome"), "")
        return (f"Chifoumi tranché : {adversaire} a joué {shown.get('theirs')}, "
                f"toi {shown.get('mine')} — {verdict}. Annonce-le.")
    if widget == "bingo":
        # `done` n'est renvoyé par AUCUN des trois retours possibles, et le
        # troisième — la coche d'une case — ne renvoie même pas `cells` : il
        # rend `checked` (le libellé coché) et `full`, que personne ne lisait.
        # Après un `check`, l'outil annonçait donc « 0/0 cases cochées » alors
        # qu'une case venait d'être validée, et ne disait jamais que la grille
        # était complète. Chaque forme est maintenant traitée pour ce qu'elle est.
        if "checked" in shown:
            fin = " La grille est complète, annonce-le." if shown.get("full") else ""
            return f"Case « {shown['checked']} » cochée sur le bingo.{fin}"
        cells = shown.get("cells") or []
        return f"La grille de bingo est à l'écran : {len(cells)} cases, aucune cochée."
    if widget == "hangman":
        return (f"Le pendu est lancé, {shown.get('letters', '?')} lettres à "
                "deviner. Le chat propose une lettre par message.")
    if widget == "goal":
        return (f"L'objectif « {shown.get('label')} » est à l'écran : "
                f"{shown.get('count', 0)}/{shown.get('target')}. Il se remplit tout seul.")
    if widget == "meme":
        return f"Le meme « {shown.get('description') or shown.get('name')} » est à l'écran."
    if widget == "pinned":
        auteur = shown.get("author") or "quelqu'un"
        return f"Le message de {auteur} est épinglé à l'écran."
    if widget == "counter":
        return f"« {shown.get('text')} » est à l'écran."
    return f"'{widget}' est à l'écran."


# « KingsRequin (@kingsrequin) » — l'étiquette que le vocal et Discord donnent
# d'un locuteur. Les DEUX pseudos sont utiles au prompt, où Wally doit pouvoir
# relier les deux ; à l'écran c'est du bruit, et le bornage à 24 caractères la
# coupait en plein milieu (« KingsRequin (@kingsrequi », vu en live).
_AUTHOR_LABEL_RE = re.compile(r"^(.+?)\s*\(@[^)\s]+\)$")


def _display_only(label: str) -> str:
    """Le pseudo affichable d'une étiquette de locuteur.

    Seule la forme `(@username)` est retirée : « Bob (le vrai) » n'est pas une
    étiquette technique et reste intact.
    """
    m = _AUTHOR_LABEL_RE.match((label or "").strip())
    return m.group(1).strip() if m else (label or "").strip()


def run_overlay_tool(bot, args: dict, requester: str = "") -> str:
    """Exécute `show_overlay` et rend un compte rendu HONNÊTE.

    Un refus doit être explicite : sinon Wally annonce « c'est affiché » alors
    que rien n'est monté à l'écran.

    `requester` est le nom de qui parle, tel que le chat le connaît. Il vient de
    l'appelant, JAMAIS du modèle : c'est le nom affiché sous la main adverse du
    chifoumi, et Wally ne doit pas pouvoir faire jouer quelqu'un d'autre.
    """
    narrator = _overlay_narrator(bot)
    if narrator is None:
        return json.dumps({"status": "unavailable",
                           "message": "L'overlay n'est pas branché en ce moment."})
    widget = str(args.get("widget") or "").strip()
    extra = {k: v for k, v in args.items()
             if k not in ("widget", "comment", "result") and v is not None}
    if widget == "rps":
        extra["opponent"] = _display_only(requester)
    extra.pop("sollicite", None)   # le drapeau vient d'ici, jamais du modèle
    try:
        shown = narrator.show_widget(
            widget, str(args.get("comment") or ""), result=args.get("result"),
            # Quelqu'un a PARLÉ à Wally pour en arriver là : c'est exactement ce
            # que veut dire ce drapeau, et c'est ce qui autorise l'ouverture
            # d'un bingo, d'un sondage, d'un pendu ou d'un objectif.
            sollicite=True, **extra
        )
    except Exception as exc:  # noqa: BLE001 — un widget raté ne casse pas la réponse
        logger.warning("show_overlay a échoué : {e!r}", e=exc)
        return json.dumps({"status": "error", "message": "L'affichage a échoué."})
    if shown:
        return json.dumps({"status": "ok", "message": _overlay_outcome(shown)})
    if not narrator.is_active():
        return json.dumps({"status": "offline", "message": (
            "Rien affiché : il n'y a pas de live en cours, l'overlay ne s'affiche "
            "que pendant un stream. Dis-le simplement."
        )})
    # Le refus d'écraser une partie en cours doit être DIT, pas avalé : sans ça
    # Wally lisait « widget inconnu ou données manquantes » et rouvrait un bingo
    # trente secondes plus tard. L'état n'a pas bougé depuis `show_widget` — le
    # garde a justement refusé d'y toucher — donc la phrase est encore juste.
    occupe = narrator.game_already_running(widget, **extra)
    if occupe:
        return json.dumps({"status": "busy", "message": occupe})
    # Le motif vient de l'endroit qui a refusé, pas d'une phrase écrite ici :
    # une seule sait ce qui manque, et une phrase générique disait la contrainte
    # de la ROUE devant un pendu sans mot. Lu juste après l'appel, sans `await`
    # entre les deux — c'est ce que promet `dernier_refus_widget`.
    motif = narrator.dernier_refus_widget()
    return json.dumps({"status": "rejected", "message": (
        f"Rien affiché : {motif}" if motif
        else f"Rien affiché : '{widget}' n'a pas pu s'afficher."
    )})


def run_planning_tool(bot, args: dict, *, overlay: bool = True) -> str:
    """Rend le lien du planning, et l'affiche sur l'overlay si un live tourne.

    Le lien est rendu DANS TOUS LES CAS — hors live, sans overlay branché, quoi
    qu'il arrive. C'est ce qui justifie un outil dédié plutôt qu'un simple
    widget : `show_widget` ne répond rien hors direct, et Wally n'aurait alors
    aucune réponse à « c'est quand les streams ? » le reste du temps.

    `overlay=False` depuis une chaîne Twitch INVITÉE : donner le lien y est
    inoffensif, mais l'overlay appartient au stream maison — le même garde que
    pour les autres widgets.
    """
    affiche = False
    narrator = _overlay_narrator(bot) if overlay else None
    if narrator is not None:
        try:
            affiche = narrator.show_widget(
                "planning", str(args.get("comment") or "")
            ) is not None
        except Exception as exc:  # noqa: BLE001 — l'affichage rate, le lien reste
            logger.warning("show_planning : l'affichage a échoué : {e!r}", e=exc)
    return json.dumps({
        "status": "ok",
        "url": planning_url(),
        "affiche_sur_l_overlay": affiche,
        "message": (
            "Le planning est à l'écran, et voici le lien à donner."
            if affiche else
            "Donne ce lien. (Rien à l'écran : pas de live en cours.)"
        ),
    })


def _clip_en_texte(clip: dict, quoi: str) -> str:
    """Un clip rendu SANS écran : titre, clippeur, lien Twitch.

    C'est le repli quand l'overlay n'est pas là — hors live, ou depuis Discord
    qui n'en a jamais eu. Le lien vient du champ `url` de Helix ; on ne le
    fabrique pas à partir du slug, Twitch le donne déjà.
    """
    titre = clip.get("title") or "sans titre"
    clippeur = clip.get("creator_name") or "un anonyme"
    return json.dumps({"status": "texte", "message": (
        f"{quoi} : « {titre} », clippé par {clippeur} "
        f"({int(clip.get('view_count') or 0)} vues). "
        f"Donne ce lien tel quel : {clip.get('url') or ''} — il n'y a pas "
        "d'écran là, donc ne dis PAS que tu l'as affiché. Tu ne l'as pas vu "
        "non plus : commente le titre, jamais le contenu."
    )})


async def _clip_sans_ecran(bot, args: dict) -> str:
    """`show_clip` quand aucun overlay ne peut le jouer.

    Les trois modes utiles survivent sans écran parce que l'API sait déjà tout
    faire seule (`get_last_clip`, `find_clip`, `get_top_clips`) : le narrateur
    n'était qu'un intermédiaire. Seul l'affichage vidéo se perd.
    """
    from bot.core.follow_tool import api_twitch

    api = api_twitch(bot)
    if api is None:
        return json.dumps({"status": "unavailable",
                           "message": "Je n'ai pas accès aux clips en ce moment."})
    mode = str(args.get("mode") or "dernier").strip().lower()
    auteur = str(args.get("author") or "").strip()[:40] or None
    try:
        if mode == "top":
            clips = await api.get_top_clips(days=30, first=min(int(args.get("count") or 5), 5))
            if not clips:
                return json.dumps({"status": "nothing", "message": (
                    "Aucun clip à classer. Dis-le, n'invente pas de podium.")})
            lignes = " · ".join(
                f"« {c.get('title')} » par {c.get('creator_name')} "
                f"({int(c.get('view_count') or 0)} vues)" for c in clips)
            return json.dumps({"status": "texte", "message": (
                f"Podium des plus vus : {lignes}. Pas d'écran ici — ne dis pas "
                "que tu l'as affiché.")})
        if mode == "titre":
            clip = await api.find_clip(str(args.get("query") or "").strip()[:80], days=30)
            quoi = "Le clip qui colle le mieux"
        elif mode == "plus_vu":
            tops = await api.get_top_clips(days=30, first=1)
            clip, quoi = (tops[0] if tops else None), "Le clip le plus vu du mois"
        else:
            clip = await api.get_last_clip(days=30, creator=auteur)
            quoi = "Le dernier clip"
    except Exception as exc:  # noqa: BLE001 — un clip raté ne casse pas la réponse
        logger.warning("show_clip sans écran a échoué : {e!r}", e=exc)
        return json.dumps({"status": "error", "message": "La recherche a échoué."})
    if clip:
        return _clip_en_texte(clip, quoi)
    if auteur:
        # Les deux vides ne se disent pas pareil, ici comme sur le chemin écran.
        return json.dumps({"status": "nothing", "message": (
            f"Aucun clip récent clippé par {auteur} sur la chaîne. Dis-le, "
            "n'en invente pas un et ne le mets pas sur le dos d'un autre.")})
    return json.dumps({"status": "nothing", "message": (
        "Aucun clip récent sur la chaîne. Dis-le, n'en invente pas un.")})


async def run_last_clip_tool(bot, args: dict) -> str:
    """Exécute `show_clip` et rend un compte rendu HONNÊTE.

    Deux chemins, et c'est l'ÉCRAN qui tranche, pas la plateforme : overlay
    actif → la vidéo part dessus ; sinon → le clip revient en texte avec son
    lien. Jusqu'au 2026-08-27 le second n'existait pas, et « je peux pas lancer
    de clip, on est pas en live » répondait à des gens qui voulaient juste
    savoir lequel c'était.
    """
    narrator = _overlay_narrator(bot)
    if narrator is None or not narrator.is_active():
        return await _clip_sans_ecran(bot, args)
    auteur = str(args.get("author") or "").strip()[:40] or None
    mode = str(args.get("mode") or "dernier").strip().lower()
    try:
        if mode == "top":
            podium = await narrator.show_top_clips(int(args.get("count") or 5))
            if podium is None:
                return json.dumps({"status": "nothing", "message": (
                    "Aucun clip à classer. Dis-le, n'invente pas de podium."
                )})
            return json.dumps({"status": "ok", "message": (
                f"Podium affiché — {podium['count']} clips, en tête « {podium['best']} »."
            )})
        shown = await narrator.play_last_clip(
            auteur,
            query=str(args.get("query") or "").strip()[:80] or None,
            most_viewed=(mode == "plus_vu"),
        )
    except Exception as exc:  # noqa: BLE001 — un clip raté ne casse pas la réponse
        logger.warning("show_clip a échoué : {e!r}", e=exc)
        return json.dumps({"status": "error", "message": "La lecture a échoué."})
    if shown:
        # « joué » ou « affiché » : Wally ne doit pas annoncer une vidéo quand
        # seule la carte est passée (embed refusé, cf. le `parent` de Twitch).
        quoi = "Le clip est lancé" if shown["played"] else "La carte du clip est affichée"
        return json.dumps({"status": "ok", "message": (
            f"{quoi} : « {shown['title']} », clippé par {shown['author']}. "
            "Tu ne l'as pas vu — ne raconte pas ce qu'il contient."
        )})
    if auteur:
        # Distinguer les deux vides : « la chaîne n'a aucun clip » ferait dire
        # n'importe quoi alors que seule cette personne n'a rien clippé.
        return json.dumps({"status": "nothing", "message": (
            f"Aucun clip récent clippé par {auteur} sur la chaîne. Dis-le, "
            "n'en invente pas un et ne le mets pas sur le dos d'un autre."
        )})
    return json.dumps({"status": "nothing", "message": (
        "Aucun clip récent sur la chaîne. Dis-le, n'en invente pas un."
    )})

async def run_apex_overlay_tool(bot, args: dict, requester: str | None = None) -> str:
    """Exécute `show_apex` et rend un compte rendu HONNÊTE.

    Même exigence que `show_last_clip` : quand rien ne s'est affiché, Wally doit
    le dire au lieu de raconter un panneau qui n'existe pas.
    """
    narrator = _overlay_narrator(bot)
    if narrator is None:
        return json.dumps({"status": "unavailable",
                           "message": "L'overlay n'est pas branché en ce moment."})
    try:
        shown = await narrator.show_apex(
            str(args.get("panel") or "").strip(),
            str(args.get("player") or "").strip()[:32],
            str(args.get("comment") or ""),
            requester=requester,
            period=str(args.get("period") or "live").strip() or "live",
        )
    except Exception as exc:  # noqa: BLE001 — un panneau raté ne casse pas la réponse
        logger.warning("show_apex a échoué : {e!r}", e=exc)
        return json.dumps({"status": "error", "message": "L'affichage a échoué."})
    if shown:
        return json.dumps({"status": "ok", "message": (
            f"Panneau « {shown['widget']} » affiché à l'écran."
        )})
    if not narrator.is_active():
        # Le message d'échec ORDONNE la suite au lieu de la suggérer. Nommer
        # l'outil qui reste ne suffit pas : le 2026-08-12, ce refus commençait
        # par « Dis-le simplement » — une consigne de PAROLE — et présentait
        # l'alternative en complément. Wally a obéi à la lettre et répondu
        # « je peux te la sortir en image », sans jamais appeler l'outil.
        # Troisième fois que ce chemin se termine par une promesse.
        if str(args.get("panel") or "").strip() == "progress":
            message = (
                "Rien affiché : il n'y a pas de live en cours. Mais la personne "
                "veut la DONNÉE, pas l'écran du stream : appelle `apex_legends` "
                "action=progression MAINTENANT — elle joint la courbe en image "
                "et marche hors live — puis commente le résultat. N'annonce "
                "surtout pas que tu peux le faire : fais-le."
            )
        else:
            message = "Rien affiché : il n'y a pas de live en cours. Dis-le simplement."
        return json.dumps({"status": "offline", "message": message})
    # Pour la courbe, la donnée manquante a une cause précise et rattrapable :
    # le compte visé n'a pas assez de relevés. Le dire évite qu'on annonce une
    # absence de mesures qui ne concerne pas la personne dont on parle.
    precision = (
        " Le compte visé n'a pas assez de relevés sur cette période — si tu "
        "visais quelqu'un d'autre que la personne à qui tu réponds, recommence "
        "en remplissant `player`."
        if str(args.get("panel") or "").strip() == "progress" else ""
    )
    return json.dumps({"status": "nothing", "message": (
        "Rien affiché : la donnée Apex n'est pas disponible. Dis-le, "
        "ne prétends pas l'avoir montré." + precision
    )})


# Ce qu'on annonce pour chaque cible annulée. Le mot exact compte : « abandonné »
# et non « clos », parce qu'aucun résultat n'est dépouillé.
_CANCEL_LABELS = {
    "ecran": "l'écran est nettoyé",
    "bingo": "le bingo est abandonné",
    "pendu": "le pendu est abandonné",
    "sondage": "le sondage est abandonné, sans dépouillement",
    # Pas de « chifoumi » : il ne figure pas dans `CANCEL_TARGETS`, qui sert à la
    # fois d'enum au schéma de l'outil et de garde dans `cancel()`. Le libellé
    # était donc inatteignable, tout en laissant croire que l'annulation d'un
    # chifoumi était prévue — alors que la demande est refusée par
    # « 'chifoumi' ne veut rien dire ici ». Un chifoumi est un affichage
    # instantané : il n'y a rien à annuler.
    "objectif": "l'objectif est retiré",
}


def run_overlay_cancel_tool(bot, args: dict) -> str:
    """Exécute `cancel_overlay` et rend un compte rendu HONNÊTE.

    Même exigence que `run_overlay_tool` : quand il n'y avait rien à annuler, il
    faut le DIRE. Sans ça Wally répond « c'est annulé » à qui lui demande de
    couper un bingo qui n'a jamais existé.
    """
    narrator = _overlay_narrator(bot)
    if narrator is None:
        return json.dumps({"status": "unavailable",
                           "message": "L'overlay n'est pas branché en ce moment."})
    target = str(args.get("target") or "").strip().lower()
    try:
        result = narrator.cancel(target)
    except Exception as exc:  # noqa: BLE001 — une annulation ratée ne casse pas la réponse
        logger.warning("cancel_overlay a échoué : {e!r}", e=exc)
        return json.dumps({"status": "error", "message": "L'annulation a échoué."})

    if result.get("unknown"):
        return json.dumps({"status": "rejected", "message": (
            f"'{target}' ne veut rien dire ici. Cibles possibles : "
            + ", ".join(CANCEL_TARGETS) + "."
        )})
    done = result.get("cancelled") or []
    if not done:
        return json.dumps({"status": "nothing", "message": (
            f"Rien à annuler : aucun {target} n'était en cours. Dis-le "
            "simplement, ne prétends pas l'avoir retiré."
        )})
    return json.dumps({"status": "ok", "message": (
        "C'est fait — " + ", ".join(_CANCEL_LABELS.get(d, d) for d in done) + "."
    )})


# Outil de self-modification — exposé UNIQUEMENT au créateur (voir l'assemblage des
# tools). Quand le créateur demande explicitement d'ajouter/corriger une capacité,
# Wally route vers le flux Claude Code : une demande d'autorisation 🧠 (✅/❌) est
# envoyée en DM, et sur ✅ Claude Code écrit le code puis le bot se rebuild.
_SELF_MODIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "request_self_modification",
        "description": (
            "Demande une modification de ton PROPRE code source. À utiliser UNIQUEMENT "
            "quand ton créateur te demande explicitement d'ajouter, corriger ou changer "
            "une de tes capacités/fonctionnalités (ex. « ajoute la lecture des réactions "
            "emoji »). Tu décris le BUT recherché — pas le comment, Claude Code écrira le "
            "code. Ton créateur recevra une demande d'autorisation 🧠 en DM (✅/❌) ; sur ✅, "
            "Claude Code modifie le code et le bot redémarre. N'utilise JAMAIS "
            "save_persistent_note pour ça, et ne prétends jamais avoir « envoyé la demande » "
            "sans appeler cet outil. Réservé à ton créateur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": (
                        "Le but de la modification, rédigé PROPREMENT : un BUT clair et "
                        "concret (le comportement voulu, pas les détails techniques), le "
                        "périmètre exact (Discord/Twitch, DM ou serveur), UNE seule "
                        "intention. Ne suppose JAMAIS l'état du code : ne prétends pas "
                        "qu'une fonction ou un fichier 'existe déjà' — Claude vérifiera."
                    ),
                },
            },
            "required": ["goal"],
        },
    },
}


def _resolve_discord_roles(member) -> list[str]:
    """Return member's actual Discord role IDs plus 'everyone' and 'admin' if applicable.

    En MP, `message.author` est un `discord.User` : ni `roles`, ni
    `guild_permissions`. L'AttributeError était rattrapée par la boucle de
    tool-calling et rendue au modèle en « Tool error » — donc TOUT rappel
    demandé en message privé échouait sans être créé, et Wally pouvait
    répondre qu'il l'avait noté. Le MP est le canal principal de l'owner.
    """
    roles = ["everyone"]
    membre_roles = getattr(member, "roles", None)
    if membre_roles is None:
        return roles
    roles.extend(str(r.id) for r in membre_roles if not r.is_default())
    perms = getattr(member, "guild_permissions", None)
    if perms is not None and perms.administrator:
        roles.append("admin")
    return roles

def _roles_discord_effectifs(bot, author) -> list[str]:
    """Les rôles de `author`, plus « admin » si la config le dit.

    `_resolve_discord_roles` lit la GUILDE : en message privé, `author` est un
    `discord.User` sans rôles ni permissions, et il rend `["everyone"]`. C'est
    exactement le canal principal de l'owner — sans cette couche, tout pouvoir
    réservé aux admins lui était refusé dans son propre MP.
    """
    roles = _resolve_discord_roles(author)
    connus = {str(a) for a in getattr(bot.config, "admin_ids", [])}
    proprio = str(getattr(bot.config.bot, "owner_discord_id", "") or "")
    if proprio:
        connus.add(proprio)
    if str(getattr(author, "id", "")) in connus and "admin" not in roles:
        roles.append("admin")
    return roles


_REACT_TAG_RE = re.compile(r"^\[react:(.+?)\]\s*")

_LAUGH_WORDS = {"mdr", "lol", "ptdr", "xd", "haha", "😂", "🤣"}
_POSITIVE_WORDS = {"gg", "bravo", "trop bien", "bien joué", "incroyable"}
_NEGATIVE_WORDS = {"merde", "putain", "nul", "chier"}

_LAUGH_EMOJIS = ("😂", "💀")
_POSITIVE_EMOJIS = ("🔥", "👏")
_NEGATIVE_EMOJIS = ("😤", "💀")


def _parse_react_tag(text: str) -> tuple[str | None, str]:
    """Parse un tag [react:emoji] au début du texte.
    Retourne (emoji, texte_nettoyé) ou (None, texte_original).
    """
    m = _REACT_TAG_RE.match(text)
    if m:
        return m.group(1), text[m.end():].strip()
    return None, text


def _author_label(member: discord.Member | discord.User) -> str:
    """Format author label for LLM context: 'display_name (@username)' if different, else just display_name."""
    display = member.display_name
    username = member.name
    if username and username != display:
        return f"{display} (@{username})"
    return display


_USER_MENTION_RE = re.compile(r"<@!?(\d+)>")


def _resolve_mentions(message: "discord.Message", content: str) -> str:
    """Remplace les mentions brutes ``<@id>`` du texte par le pseudo lisible.

    discord.py laisse les mentions sous forme d'identifiant nu dans
    ``message.content`` ; sans cette résolution, le LLM ne voit qu'un nombre
    (« <@792842038332358656> ») au lieu du pseudo de la personne pingée. On
    s'appuie sur ``message.mentions`` (objets déjà résolus), avec repli sur le
    cache du serveur. Lecture seule, ne casse jamais : un id introuvable est
    laissé tel quel."""
    if not content or "<@" not in content:
        return content
    by_id = {m.id: m for m in getattr(message, "mentions", []) or []}
    guild = getattr(message, "guild", None)

    def _sub(match: "re.Match") -> str:
        uid = int(match.group(1))
        member = by_id.get(uid)
        if member is None and guild is not None:
            member = guild.get_member(uid)
        if member is None:
            return match.group(0)
        return f"@{member.display_name}"

    return _USER_MENTION_RE.sub(_sub, content)


# Mentions autorisées sur les messages que Wally envoie : il peut ping des
# membres (<@id>) mais JAMAIS @everyone/@here ni un rôle entier — garde-fou
# contre un ping de masse depuis un bot autonome. replied_user=True conserve
# le ping de l'auteur sur les réponses (comportement discord.py par défaut).
_ALLOWED_MENTIONS = discord.AllowedMentions(
    everyone=False, roles=False, users=True, replied_user=True
)

# Borne le nombre de membres listés dans l'annuaire de mentions pour ne pas
# gonfler le prompt sur un gros serveur.
_MENTION_DIRECTORY_MAX = 80


def _build_mention_directory(
    message: discord.Message, *, max_members: int = _MENTION_DIRECTORY_MAX
) -> str:
    """Annuaire des membres mentionnables du serveur, pour le LLM.

    Permet à Wally de ping correctement n'importe quel membre via la syntaxe
    Discord ``<@id>``. Sans cet annuaire, le LLM ignore les identifiants et
    écrit au mieux un texte « @pseudo » qui ne notifie personne.

    Lecture seule, jamais bloquant : toute erreur (DM, intent members absent,
    cache vide…) renvoie une chaîne vide. L'auteur du message courant est listé
    en premier (le plus susceptible d'être mentionné)."""
    guild = getattr(message, "guild", None)
    if guild is None:
        return ""
    try:
        members = list(getattr(guild, "members", []) or [])
    except Exception:
        return ""

    ordered: list = []
    seen: set[int] = set()

    author = getattr(message, "author", None)
    if (
        author is not None
        and not getattr(author, "bot", False)
        and getattr(author, "id", None) is not None
    ):
        ordered.append(author)
        seen.add(author.id)

    for m in members:
        mid = getattr(m, "id", None)
        if mid is None or mid in seen or getattr(m, "bot", False):
            continue
        ordered.append(m)
        seen.add(mid)

    lines = [f"- {_author_label(m)} → <@{m.id}>" for m in ordered[:max_members]]
    if not lines:
        return ""

    return (
        "\n--- Membres du serveur (pour les mentionner) ---\n"
        "Pour notifier (ping) un membre, insère son identifiant au format "
        "<@id> dans ta réponse (ex : « salut <@123456> »). Le simple texte "
        "« @pseudo » ne notifie personne. N'écris JAMAIS @everyone ni @here.\n"
        + "\n".join(lines)
    )


def _presence_line(bot: "WallyDiscord", user_id: str, display_name: str) -> str:
    """Présence en direct de l'interlocuteur (statut + activité) ou "".

    Lecture seule, serveur principal uniquement. Ne casse jamais une réponse :
    toute erreur renvoie une chaîne vide."""
    svc = getattr(bot, "presence", None)
    if svc is None or not getattr(svc, "enabled", False):
        return ""
    try:
        line = svc.describe(user_id, display_name)
        if line:
            return line
        # Pas de donnée de présence : on l'annonce explicitement au lieu de
        # laisser un vide que le LLM comblerait en inventant un statut.
        return (
            f"Tu ne vois aucun statut ni activité pour {display_name} là "
            "(hors ligne, invisible, ou hors du serveur principal) — ne l'invente pas."
        )
    except Exception:
        return ""


def _channel_origin(channel) -> str:
    """Libellé lisible du lieu d'un message Discord, pour la provenance mémoire.

    Ex. « Discord #discussions », « Discord MP ». Sert d'`origin` aux faits."""
    if isinstance(channel, discord.DMChannel):
        return "Discord MP"
    name = getattr(channel, "name", None)
    return f"Discord #{name}" if name else "Discord"


def _format_reactions(
    emoji: str, target_label: str, target_content: str, on_own_message: bool
) -> str:
    """Construit la phrase de contexte décrivant une réaction emoji.

    Retourne uniquement la partie « contenu » (sans le pseudo de l'auteur de la
    réaction) : elle est injectée dans la fenêtre de contexte avec ce pseudo en
    tête, rendu ensuite « [pseudo]: a réagi 😂 à ton message « ... » ».
    """
    snippet = (target_content or "").strip().replace("\n", " ")
    if len(snippet) > 120:
        snippet = snippet[:120].rstrip() + "…"
    if on_own_message:
        head = f"a réagi {emoji} à ton message"
    else:
        head = f"a réagi {emoji} au message de {target_label}"
    return f"{head} « {snippet} »" if snippet else head


# Plafonds du relevé de réactions : chaque emoji d'un message coûte un appel API
# (``reaction.users()``), on borne donc ce qu'on résout et ce qu'on injecte.
MAX_REACTION_EMOJIS = 6
MAX_REACTORS_PER_EMOJI = 8


async def _reaction_roster(bot: "WallyDiscord", message: "discord.Message") -> str:
    """Décrit QUI a réagi et avec quel emoji sur un message, pas seulement combien.

    Rend « 😂 Alice, Bob · 👍 Carol » : savoir qui approuve qui est une donnée
    sociale que Wally devait deviner tant qu'il ne voyait que des compteurs.
    Renvoie "" quand le message ne porte aucune réaction — cas très majoritaire,
    et alors aucun appel réseau n'est fait. Ne lève jamais.
    """
    try:
        reactions = list(getattr(message, "reactions", None) or [])
    except TypeError:  # objet non itérable (message factice / partiel)
        return ""
    if not reactions:
        return ""

    self_id = bot.user.id if getattr(bot, "user", None) else None
    self_name = bot.config.bot.name
    parts: list[str] = []
    for reaction in reactions[:MAX_REACTION_EMOJIS]:
        emoji = str(reaction.emoji)
        names: list[str] = []
        try:
            async for user in reaction.users(limit=MAX_REACTORS_PER_EMOJI):
                names.append(self_name if user.id == self_id else _author_label(user))
        except Exception as e:  # noqa: BLE001 — une réaction illisible n'annule pas les autres
            logger.debug("Réacteurs illisibles pour {emoji} : {e!r}", emoji=emoji, e=e)
        count = getattr(reaction, "count", 0) or 0
        if names:
            hidden = count - len(names)
            parts.append(f"{emoji} {', '.join(names)}" + (f" +{hidden}" if hidden > 0 else ""))
        elif count:
            # Identités inaccessibles : mieux vaut le compte nu que rien.
            parts.append(f"{emoji} ×{count}")
    extra_emojis = len(reactions) - MAX_REACTION_EMOJIS
    if extra_emojis > 0:
        parts.append(f"+{extra_emojis} autre(s) emoji(s)")
    return " · ".join(parts)


def _with_reactions(content: str, roster: str) -> str:
    """Suffixe un contenu de message par son relevé de réactions, s'il y en a."""
    if not roster:
        return content
    tag = f"[réactions : {roster}]"
    return f"{content} {tag}" if content else tag


async def _reactions_context(bot: "WallyDiscord", payload: discord.RawReactionActionEvent) -> None:
    """Injecte une réaction emoji dans le contexte du canal pour que Wally la perçoive.

    Couvre (A) les réactions sur les messages de Wally et (B) les réactions
    marquantes sur les messages des autres membres. Ne touche pas au tracking
    émotionnel (ReactionTracker), qui reste géré séparément.
    """
    if getattr(bot, "memory", None) is None or bot.user is None:
        return
    if payload.user_id == bot.user.id:
        return
    if payload.guild_id and payload.guild_id in bot.config.discord.ignored_guilds:
        return
    # Le filtrage par canal manquait sur ce chemin : du contenu de salons
    # explicitement exclus (whitelist/blacklist) entrait dans le contexte et
    # dans la cognition par le biais des réactions.
    if not _is_channel_allowed(bot.config, payload.channel_id, payload.guild_id):
        return
    member = payload.member
    if member is not None and member.bot:
        return

    channel = bot.get_channel(payload.channel_id)
    if channel is None:
        # En MP (et pour les canaux non encore mis en cache), get_channel renvoie
        # None : on récupère le canal directement auprès de l'API.
        try:
            channel = await bot.fetch_channel(payload.channel_id)
        except Exception as e:
            logger.debug("Réaction ignorée (fetch_channel échoué) : {e!r}", e=e)
            return
    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception as e:
        logger.debug("Réaction ignorée (fetch_message échoué) : {e!r}", e=e)
        return

    on_own_message = message.author.id == bot.user.id
    emoji = str(payload.emoji)

    if not on_own_message:
        # Cas B : on ne signale que les réactions marquantes sur les messages
        # d'autres humains (pas les bots, pas les auto-réactions).
        if message.author.bot:
            return
        if payload.user_id == message.author.id:
            return
        if emoji not in NOTABLE_REACTION_EMOJIS:
            return

    reactor = member or bot.get_user(payload.user_id)
    if reactor is None:
        # En MP, payload.member est None et l'utilisateur peut ne pas être caché.
        try:
            reactor = await bot.fetch_user(payload.user_id)
        except Exception:
            return

    self_name = bot.config.bot.name
    target_label = self_name if on_own_message else _author_label(message.author)
    notice = _format_reactions(emoji, target_label, message.content, on_own_message)
    channel_id = str(payload.channel_id)
    reactor_label = _author_label(reactor)
    bot.memory.append_message(channel_id, reactor_label, notice, platform="discord")
    logger.debug(
        "Réaction injectée dans le contexte : {who} {notice} (canal {ch})",
        who=reactor_label, notice=notice, ch=channel_id,
    )

    # Perception cognitive (#A2) : le « cerveau » V2 ne voyait pas les réactions.
    # Une réaction sur un message de Wally est un feedback social qui le concerne
    # (cadence vive) ; une réaction marquante ailleurs reste une perception passive.
    if getattr(bot, "cognitive_loop", None) is not None:
        try:
            bot.cognitive_loop.notify_event(
                channel_id=payload.channel_id,
                description=f"{reactor_label} {notice}",
                relevant=on_own_message,
            )
        except Exception as e:  # noqa: BLE001 — jamais bloquant
            logger.warning("cognitive_loop.notify_event (réaction) a échoué: {e!r}", e=e)


async def _member_join_context(bot: "WallyDiscord", member) -> None:
    """Perception cognitive (#A2) d'une arrivée de membre sur un serveur.

    Le « cerveau » V2 ne percevait que le texte ; un nouveau venu était invisible.
    On pousse l'événement dans le flux perçu (perception passive) : la cognition
    décide seule si elle souhaite la bienvenue. Le canal proposé est le canal
    système du serveur (lieu naturel d'accueil) ; à défaut, l'id du serveur sert
    de simple contexte.
    """
    if getattr(member, "bot", False):
        return
    guild = getattr(member, "guild", None)
    if guild is not None and guild.id in bot.config.discord.ignored_guilds:
        return
    cl = getattr(bot, "cognitive_loop", None)
    if cl is None:
        return
    sys_channel = getattr(guild, "system_channel", None) if guild else None
    channel_id = sys_channel.id if sys_channel is not None else (guild.id if guild else 0)
    guild_name = getattr(guild, "name", "") if guild else ""
    suffix = f" {guild_name}".rstrip()
    try:
        cl.notify_event(
            channel_id=channel_id,
            description=f"{_author_label(member)} vient de rejoindre le serveur{suffix}",
            relevant=False,
        )
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.warning("cognitive_loop.notify_event (arrivée membre) a échoué: {e!r}", e=e)


_MOT_RE = re.compile(r"\w+", re.UNICODE)


def _pick_passive_emoji(text: str, curiosity: float) -> str | None:
    """Choisit un emoji de réaction passive basé sur le contenu du message.
    Retourne None si aucun signal détecté.
    """
    text_lower = text.lower()
    # Sur les MOTS, pas sur les sous-chaînes : « gg » matchait « suggestion »,
    # « aggro », « jogging » ; « nul » matchait « annuler » et « nulle part ».
    # Wally collait donc un 🔥 sur « j'ai une suggestion » et un 😤 sur « c'est
    # annulé », dans tous les salons autorisés. Les entrées multi-mots
    # (« bien joué ») restent testées en sous-chaîne, faute de frontière simple.
    mots = set(_MOT_RE.findall(text_lower))

    def _touche(vocabulaire: set[str]) -> bool:
        simples = {w for w in vocabulaire if " " not in w and w.isalnum()}
        autres = vocabulaire - simples
        return bool(mots & simples) or any(w in text_lower for w in autres)

    if _touche(_LAUGH_WORDS):
        return random.choice(_LAUGH_EMOJIS)
    if _touche(_POSITIVE_WORDS):
        return random.choice(_POSITIVE_EMOJIS)
    if _touche(_NEGATIVE_WORDS):
        return random.choice(_NEGATIVE_EMOJIS)
    if curiosity >= 0.4 and "?" in text:
        return "🤔"
    return None


# Emoji d'humeur — pour laisser un signe quand Wally choisit de NE PAS répondre :
# il réagit quand même, avec un emoji qui dit son humeur / pourquoi il se tait.
_MOOD_EMOJIS = {
    "anger":     ["😒", "😤", "🙄"],
    "boredom":   ["🥱", "😴", "😑"],
    "sadness":   ["😔", "😞"],
    "curiosity": ["🤔", "👀"],
    "joy":       ["🙂", "😏"],
}


def _mood_emoji(emotion_state: dict[str, float]) -> str:
    """Emoji reflétant l'émotion dominante de Wally. Résout TOUJOURS."""
    dominant, value = max(emotion_state.items(), key=lambda x: x[1], default=("", 0.0))
    if value < 0.15 or dominant not in _MOOD_EMOJIS:
        return random.choice(["😶", "🤷", "💭"])
    return random.choice(_MOOD_EMOJIS[dominant])


def _resolve_emoji(raw: str, bot: "WallyDiscord"):
    """Résout l'emoji renvoyé par le LLM en quelque chose que add_reaction accepte.

    - Emote custom (nom, ":nom:" ou "<:nom:id>") cherchée dans TOUS les serveurs du
      bot (`bot.emojis`, animées incluses) → l'objet discord.Emoji (Nitro-like).
    - Sinon, emoji Unicode standard → la chaîne telle quelle.
    """
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("<") and raw.endswith(">"):
        return raw  # déjà au format custom <:nom:id> / <a:nom:id>
    name = raw.strip(":")
    if name:
        match = discord.utils.get(bot.emojis, name=name)
        if match is not None:
            return match
    return raw


_PASSION_KEYWORDS = {
    "bouchon", "bouchons", "silice", "chariot", "chariots",
    "néon", "néons", "ticket de caisse", "notice pliée",
    "feuille morte", "feuilles mortes",
}
_AVERSION_KEYWORDS = {
    "ananas", "pizza ananas", "ketchup", "croque-monsieur",
    "c'est juste un jeu", "on part sur", "eau tiède",
    "clavier mécanique", "applaudir",
}
_SPONTANEOUS_KEYWORDS = _PASSION_KEYWORDS | _AVERSION_KEYWORDS


def _check_spontaneous_trigger(
    text: str, curiosity: float, anger: float, boredom: float,
) -> str | None:
    """Check if a message should trigger a spontaneous intervention.
    Returns 'passion' (higher prob), 'emotion' (lower prob), or None.
    """
    text_lower = text.lower()
    if any(kw in text_lower for kw in _SPONTANEOUS_KEYWORDS):
        return "passion"
    if curiosity >= 0.6 or anger >= 0.7 or boredom >= 0.7:
        return "emotion"
    return None


# Strong references to fire-and-forget tasks to prevent GC cancellation.
_bg_tasks: set[asyncio.Task] = set()
# Questions que Wally vient de poser : (channel_id, user_id) → instant.
# Sans ça, il pose « entre quoi et quoi ? » puis ignore la réponse, qui ne
# contient ni son nom ni de mention — un dialogue qui s'interrompt tout seul.
_open_questions: dict[tuple, float] = {}

# Au-delà, ce n'est plus une réponse à sa question mais une nouvelle conversation.
_OPEN_QUESTION_WINDOW_S = 180.0


def _note_open_question(channel_id, user_id, text: str) -> None:
    """Retient qu'une question attend une réponse de cette personne."""
    if "?" not in (text or ""):
        return
    now = time.monotonic()
    # Purge des questions jamais honorées : sans elle, le dict grandit tant que
    # le process tourne (des semaines).
    for key, asked_at in list(_open_questions.items()):
        if now - asked_at > _OPEN_QUESTION_WINDOW_S:
            del _open_questions[key]
    _open_questions[(channel_id, user_id)] = now


def _consume_open_question(channel_id, user_id) -> bool:
    """Vrai si ce message répond à une question en attente — et la referme.

    Consommée à la première réponse : Wally ne doit pas s'accrocher au fil
    indéfiniment, seulement ne pas laisser sa propre question sans suite.
    """
    asked_at = _open_questions.pop((channel_id, user_id), None)
    return asked_at is not None and (time.monotonic() - asked_at) <= _OPEN_QUESTION_WINDOW_S


_spontaneous_cooldowns: dict[str, float] = {}  # channel_id → last spontaneous timestamp
# Au-delà de ce nombre de couples suivis, on balaie les inactifs (cf. plus bas).
# Outils de recherche externe, coupés quand le rappel RSS couvre déjà l'actualité.
# UNE constante pour les deux usages : le filtre de l'offre omettait
# `image_search`, que le refus d'exécution listait pourtant. Le modèle pouvait
# donc appeler un outil qu'on lui proposait, et ne recevoir qu'un refus parlant
# d'articles — un tour de tool-calling gaspillé.
# Les outils qu'un recall RSS positif rend inutiles : ils iraient chercher
# dehors ce que Wally a déjà sous la main.
#
# `apex_legends` n'en fait PAS partie, et c'est le fond du problème vécu le
# 2026-08-12. Le recall RSS couvre les patch notes et les articles ; l'outil
# Apex ne rend que de la donnée de jeu en direct — rang, stats, progression,
# rotation de map, statut des serveurs. Aucune de ses six actions ne peut être
# couverte par un article, donc le recall ne se substitue jamais à lui. Le
# couper laissait le refus de `show_apex` renvoyer vers un outil absent de
# l'offre, et Wally promettait une courbe qu'il ne pouvait plus produire.
_LOOKUP_TOOLS = ("web_search", "image_search", "scrape_url")

async def build_chat_tools(bot, author_id: str) -> list[dict]:
    """Les outils offerts au LLM pour un message Discord.

    Extraite de `handle_message` pour être comparable à son jumeau Twitch
    (`bot.twitch.handlers.build_chat_tools`). Les deux listes doivent diverger
    seulement là où la plateforme l'impose, et `tests/test_parite_plateformes.py`
    tient l'inventaire de ces écarts : une divergence non prévue échoue.

    C'est la panne qu'on ne voit pas autrement — un outil branché d'un côté et
    oublié de l'autre ne casse rien, ne journalise rien, et rend simplement
    Wally incapable sur une plateforme de ce qu'il sait faire sur l'autre.
    """
    tools: list[dict] = []
    web_search = getattr(bot, "web_search", None)
    if web_search and web_search.available and not await web_search.is_quota_exceeded():
        tools.extend(web_search.get_tool_definitions())
    scrape = getattr(bot, "scrape", None)
    if scrape and scrape.available and not await scrape.daily_limit_reached():
        tools.extend(scrape.get_tool_definitions())
    apex_api = getattr(bot, "apex_api", None)
    if apex_api and apex_api.available:
        tools.append(apex_api.get_tool_definition())
    action_service = getattr(bot, "action_service", None)
    if action_service:
        tools.extend(action_service.get_tool_definitions())
    # DISCORD SEULEMENT, et c'est délibéré : `HistorySearchService` fouille les
    # JSONL de conversation Discord. L'offrir sur Twitch permettrait au chat
    # public d'exhumer ce qui s'est dit sur le serveur Discord.
    history_search = getattr(bot, "history_search", None)
    if history_search and history_search.available:
        tools.extend(history_search.get_tool_definitions())
    tools.extend(_NOTE_TOOLS)
    if getattr(bot, "tally", None) is not None:
        tools.extend(_TALLY_TOOLS)
    if getattr(bot, "predictions", None) is not None:
        tools.append(_PREDICT_TOOL)
    if getattr(bot, "quotes", None) is not None:
        tools.append(_QUOTE_TOOL)
    if _presence_service(bot) is not None:
        tools.append(_PRESENCE_TOOL)
    # L'ancienneté d'un follower de la chaîne d'Azraël. Offert ici AUSSI : la
    # communauté est la même des deux côtés, et l'outil prend un pseudo Twitch —
    # il ne dépend donc pas de l'identité de la plateforme où on le questionne.
    if api_twitch(bot) is not None:
        tools.append(FOLLOW_TOOL)
    # Le planning est offert INCONDITIONNELLEMENT : il rend un lien, pas un
    # affichage. Le conditionner à l'overlay priverait Wally de réponse hors
    # live — le moment où on demande justement quand est le prochain stream.
    tools.append(PLANNING_TOOL_SPEC)
    # La musique d'Azraël : ici pour la LECTURE seule (« c'est quoi la
    # musique ? »), que le §10 veut ouverte à tout le monde. Le pilotage exige
    # un badge de modérateur Twitch, qu'un salon Discord ne porte pas —
    # `pilotable=False` à l'exécution le dit et ORIENTE vers le chat du live,
    # au lieu de charrier quelqu'un qui n'a rien tenté de louche.
    if getattr(bot, "music", None) is not None:
        tools.append(MUSIC_TOOL)
    # Overlay : seulement s'il est branché — un outil mort ferait promettre
    # un affichage qui n'arriverait jamais.
    if _overlay_narrator(bot) is not None:
        # L'enum est relu ICI, juste avant que Wally décide : un widget masqué
        # sur TOUTES les scènes ne doit pas lui être proposé, sinon il l'affiche
        # et annonce « c'est à l'écran » devant un écran où rien n'apparaît. Le
        # même appel rafraîchit le cache dont se sert le refus d'exécution.
        tools.append(await _spec_overlay_pour(_overlay_narrator(bot)))
        tools.append(_OVERLAY_CANCEL_TOOL)
        if getattr(bot, "apex_api", None) is not None:
            tools.append(_APEX_OVERLAY_TOOL)
    # Hors du bloc overlay, comme côté Twitch : depuis Discord il n'y a JAMAIS
    # d'écran, et c'est pourtant là qu'on demande le plus les clips passés.
    if api_twitch(bot) is not None:
        tools.append(_LAST_CLIP_TOOL)
    # DISCORD SEULEMENT : le vocal est un salon Discord, ces outils n'ont aucun
    # sens depuis un chat Twitch.
    #
    # `getattr` et non `bot.voice_service`, bien que l'attribut soit déclaré
    # depuis `de0af7d0` : cette fonction doit tenir avec un bot dont AUCUN
    # service n'est branché — c'est une propriété testée
    # (`test_l_outil_est_offert_sur_les_deux_plateformes`), et elle sert au
    # démarrage comme sur une instance minimale. mypy réclame l'accès direct ;
    # l'architecture le refuse, et c'est elle qui a raison ici.
    _vs = getattr(bot, "voice_service", None)
    if _vs is not None:
        tools += VOICE_TOOLS
    # Faire parler Wally à voix haute, depuis l'écrit — et notamment depuis un
    # MP. C'était réservé au chat Twitch, au motif que l'autorisation se lit sur
    # un badge de modérateur ; mais l'owner écrit surtout en message privé, et
    # il y a plus de droits que n'importe quel modérateur.
    #
    # Offert seulement s'il est DANS un salon, comme sur Twitch : le proposer
    # alors qu'il n'y est pas mène au cul-de-sac d'un refus qui nomme un outil
    # inutilisable. Pas conditionné aux droits — la garde est à l'exécution,
    # c'est elle qui permet de charrier celui qui essaie.
    if _VOCAL_DISPO and _vs is not None and getattr(_vs, "is_connected", False):
        tools.append(SAY_IN_VOICE_TOOL)
    # DISCORD SEULEMENT : la self-modification est réservée au créateur, qui est
    # identifié par son id Discord. Un pseudo Twitch ne prouve rien.
    if author_id == bot.config.bot.owner_discord_id and getattr(bot, "self_fix", None) is not None:
        tools.append(_SELF_MODIFY_TOOL)
    return tools


_SPAM_TRACKER_PURGE_AT = 500
_spam_tracker: dict[tuple[str, str], deque] = {}
_processed_message_ids: dict[int, float] = {}  # message_id → timestamp (dedup Discord replays)
_scrape_cooldowns: dict[str, float] = {}  # channel_id → last auto-scrape timestamp
_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def _fire(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)

    def _done(task: asyncio.Task) -> None:
        _bg_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.opt(exception=task.exception()).error("Tâche de fond échouée")

    t.add_done_callback(_done)
    return t


async def _mirror_pass(
    bot: "WallyDiscord",
    channel_id: str,
    draft: str,
    mem_context: str,
) -> str:
    """Pass secondaire : détecte et corrige patterns répétitifs ou mémoire ratée.

    Retourne le draft inchangé en cas d'erreur ou si aucun défaut n'est trouvé.
    Skippé si la réponse est trop courte (monosyllabes intentionnels).
    """
    if len(draft) < 30:
        return draft

    system = load_prompt("response_mirror_system")
    if not system:
        return draft

    try:
        self_name = bot.config.bot.name
        current_prelude = bot.memory.get_prelude(channel_id)
        recent_wally = [
            m["content"] for m in current_prelude
            if m.get("author") == self_name
        ][-3:]

        parts: list[str] = []
        if recent_wally:
            parts.append(f"Dernières réponses de {self_name} dans ce canal :\n" + "\n---\n".join(recent_wally))
        if mem_context:
            parts.append(f"Souvenirs connus sur l'utilisateur :\n{mem_context}")
        parts.append(f"Réponse à analyser :\n{draft}")

        user_msg = "\n\n".join(parts)

        corrected = await bot.llm_secondary.complete(
            system,
            [{"role": "user", "content": user_msg}],
            purpose="response_mirror",
        )
        corrected = corrected.strip()
        # Même famille que le « RIEN » de l'overlay : `OK` est un mot de service,
        # et le prompt l'épelle entre backticks (« réponds uniquement `OK` »). Une
        # égalité stricte laissait passer « `OK` » ou « Rien à corriger. OK » —
        # publié tel quel dans le salon, marqueur compris.
        if not corrected or marqueur_de_service(corrected, "OK") or corrected == FALLBACK_RESPONSE:
            return draft
        return corrected

    except Exception as exc:
        logger.warning("Mirror pass failed: {e!r}", e=exc)
        return draft


async def _fetch_discord_history(
    channel, limit: int, exclude_id: int | None = None, bot: "WallyDiscord | None" = None,
) -> list[dict]:
    """Fallback cold start : récupère l'historique Discord via API.
    Retourne les messages en ordre chronologique (plus ancien en premier).
    Retourne [] en cas d'erreur (permissions, etc.).
    Note : dicts sans 'timestamp' — utilisés uniquement pour le prompt,
    non stockés dans _prelude_windows.
    Quand ``bot`` est fourni, chaque message retenu est annoté de ses réactions
    (qui a mis quoi) : c'est le seul endroit où Wally revoit des messages posés
    avant son arrivée, donc le seul où ces réactions lui sont encore visibles."""
    try:
        msgs = []
        async for m in channel.history(limit=limit + (1 if exclude_id is not None else 0)):
            if m.id == exclude_id:
                continue
            # Include Wally's own messages for context awareness
            msgs.append(m)
        msgs.reverse()  # Discord renvoie du plus récent au plus ancien
        kept = msgs[-limit:] if len(msgs) > limit else msgs
        out = []
        for m in kept:
            content = _resolve_mentions(m, m.content)
            if bot is not None:
                content = _with_reactions(content, await _reaction_roster(bot, m))
            out.append({"author": _author_label(m.author), "content": content})
        return out
    except Exception as e:
        logger.warning("channel.history() fallback failed: {e!r}", e=e)
        return []


def _is_channel_allowed(config, channel_id: int, guild_id: int | None = None) -> bool:
    """Vérifie si Wally peut répondre dans ce canal selon le mode de filtrage."""
    if guild_id is None:
        # DM channel — toujours autorisé (Wally peut lui-même initier des DM,
        # les réponses doivent donc être traitées quel que soit le filtrage de guild).
        return True
    pgw = config.discord.per_guild_channel_whitelist
    guild_key = str(guild_id)
    if guild_key in pgw:
        guild_wl = pgw[guild_key]
        if guild_wl is None:  # null dans config = tous les canaux autorisés
            return True
        return channel_id in guild_wl
    mode = config.discord.channel_filter_mode
    if mode == "whitelist":
        wl = config.discord.channel_whitelist
        return not wl or channel_id in wl
    if mode == "blacklist":
        bl = config.discord.channel_blacklist
        return channel_id not in bl
    return True  # mode "none" ou inconnu : tout autorisé


async def _check_spam(bot: "WallyDiscord", message: discord.Message) -> bool:
    """Track message rate and trigger spam mute if threshold exceeded.
    Returns True if spam was detected and handled (caller should return early).
    """
    cfg = bot.config.discord.spam_detection
    if not cfg.enabled:
        return False
    if not message.guild:
        return False
    channel_id = message.channel.id
    if channel_id in cfg.exempt_channels:
        return False

    user_id = str(message.author.id)
    if bot.persona.is_beloved("discord", user_id):
        return False
    key = (user_id, str(channel_id))
    now = time.time()
    cutoff = now - cfg.window_seconds

    dq = _spam_tracker.get(key)
    if dq is None:
        dq = deque()
        _spam_tracker[key] = dq

    # Purge old timestamps
    while dq and dq[0] < cutoff:
        dq.popleft()
    dq.append(now)
    _spam_tracker[key] = dq

    # Purge RÉELLE : le retrait de la clé vide était immédiatement annulé trois
    # lignes plus bas par sa réinscription — un no-op, alors que le commentaire
    # annonçait un nettoyage. On balaie donc les couples (utilisateur, salon)
    # devenus inactifs, sinon le dict grossit d'une entrée par couple jamais vu
    # et ne se vide jamais de tout le process (des semaines).
    if len(_spam_tracker) > _SPAM_TRACKER_PURGE_AT:
        for cle in [k for k, d in _spam_tracker.items() if not d or d[-1] < cutoff]:
            _spam_tracker.pop(cle, None)

    if len(dq) < cfg.max_messages:
        return False

    # --- Spam detected ---
    guild_id = str(message.guild.id)
    username = _author_label(message.author)
    anger = bot.emotion.get_state().get("anger", 0.0)

    # Generate LLM warning
    system = load_prompt("spam_warning_system", "Dis à l'utilisateur de se calmer.")
    user_msg = (
        f"L'utilisateur {username} a envoyé {len(dq)} messages "
        f"en {cfg.window_seconds} secondes."
    )
    try:
        warning = await bot.llm_secondary.complete(
            system_prompt=system,
            messages=[{"role": "user", "content": user_msg}],
            purpose="spam_warning",
            user_id=user_id,
        )
        await message.channel.send(warning)
    except Exception as e:
        logger.error("Spam warning LLM failed: {e!r}", e=e)
        await message.channel.send(f"{username}, calme-toi un peu. 😤")

    # Mute user
    await bot.db.add_timeout(user_id, guild_id, cfg.mute_minutes, anger)

    # Store memory fact
    try:
        self_name = bot.config.bot.name
        await bot.memory.add(
            "discord", user_id,
            f"{self_name} a coupé {username} pour spam — trop de messages en peu de temps. "
            f"Il en a eu marre et a arrêté de lui répondre.",
            username=username,
            origin=_channel_origin(message.channel),
        )
    except Exception as e:
        logger.warning("Failed to store spam memory: {e!r}", e=e)

    # Reset tracker for this user/channel
    dq.clear()
    _spam_tracker.pop(key, None)

    logger.info(
        "Spam detected: {user} in channel {ch} — muted {min}min",
        user=username, ch=channel_id, min=cfg.mute_minutes,
    )
    return True


# Exposants Unicode pour les marqueurs de citation (mêmes que WebSearchService).
_RSS_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"

# Marqueurs d'une question d'ACTUALITÉ (sous-chaînes, insensibles à la casse).
# Quand le message en contient un ET que le recall RSS a matché, on coupe les
# outils de lookup : Wally répond avec les articles qu'il a déjà, au lieu
# d'aller chercher ailleurs.
#
# « derni » a été RETIRÉ le 2026-08-12. Il visait « les dernières actus » et
# « le dernier patch », mais « dernier » est un mot ordinaire : « la courbe du
# dernier stream », « la dernière fois qu'il a joué », « les 10 dernières
# minutes » se faisaient couper leurs outils. Rien n'est perdu — ces vraies
# questions d'actu portent toutes un autre marqueur (« actus », « patch »).
#
# Leçon du même jour : un marqueur en SOUS-CHAÎNE doit porter le sens à lui
# seul. Un fragment fréquent attrape des phrases qui n'ont rien à voir.
_RSS_NEWS_MARKERS = (
    "actu", "news", "nouveaut", "nouvelle", "quoi de neuf",
    "maj", "mise à jour", "mise a jour", "patch", "sortie", "roadmap", "annonce",
)


def _is_news_query(text: str | None) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _RSS_NEWS_MARKERS)


def _rss_age(article: dict) -> str:
    """« (paru il y a 6 jours) », ou "" si l'article n'est pas daté.

    Rendu en âge relatif plutôt qu'en date absolue : Wally n'a pas à calculer un
    écart pour savoir si « le 22 juin » est récent ou pas, et il peut restituer
    l'information telle quelle à l'oral comme à l'écrit.
    """
    ts = article.get("published_ts") or article.get("fetched_at")
    if not ts:
        return ""
    jours = int((time.time() - float(ts)) // 86400)
    if jours <= 0:
        return "(paru aujourd'hui) "
    if jours == 1:
        return "(paru hier) "
    if jours < 30:
        return f"(paru il y a {jours} jours) "
    mois = jours // 30
    return f"(paru il y a {mois} mois) " if mois > 1 else "(paru il y a 1 mois) "


async def _rss_ancre_connaissance(bot) -> str:
    """« Jusqu'où va ce que je sais », et le droit de répondre « rien ».

    Deux phrases, et chacune corrige une moitié du défaut. La première borne sa
    connaissance dans le temps : sans elle, une absence d'information ne se
    distingue pas d'un bord de base. La seconde autorise la conclusion négative,
    qui ne va pas de soi — devant des extraits qui parlent du sujet demandé, un
    modèle parle du sujet demandé, même s'ils datent de deux mois.
    """
    lecteur = getattr(getattr(bot, "db", None), "rss_dernier_knowledge_ts", None)
    if lecteur is None:
        return ""
    try:
        ts = await lecteur()
    except Exception as e:  # noqa: BLE001 — jamais bloquant pour la réponse
        logger.warning("rss_knowledge: ancre indisponible: {!r}", e)
        return ""
    if not ts:
        return ""
    # `_rss_age` rend « paru il y a 6 jours » : on garde la formule telle quelle
    # et on l'enchaîne avec « est ». La découper pour reconstruire une phrase
    # donnait « date de il y a 6 jours ».
    age = _rss_age({"published_ts": ts}).strip().strip("()") or "de date inconnue"
    return (
        f"IMPORTANT — le patch note le plus RÉCENT que tu connaisses est {age}. "
        "Ta connaissance s'arrête là, et elle est à jour jusque-là. Donc si on te "
        "demande un changement récent sur une arme ou une légende et que rien "
        "ci-dessous n'en parle dans un patch récent, la réponse est qu'il n'y a EU "
        "AUCUN changement depuis — dis-le franchement, en précisant de quand date le "
        "dernier que tu connaisses sur ce sujet. Ne présente jamais un vieux patch "
        "comme une nouveauté : « ça remonte à telle date, et depuis, rien » est une "
        "bonne réponse."
    )


async def _rss_knowledge_context(bot, text: str, *, citations: bool = True) -> str | None:
    """Recall RSS « knowledge » : si le message parle d'un sujet couvert par un
    flux knowledge (ex. Apex, le jeu du serveur), remonte les articles récents
    pertinents (FTS BM25) — AVANT que le LLM ne songe à chercher sur le web.

    Réutilise la convention de web_search : `[¹](<url>)`, URL entre chevrons pour
    neutraliser l'aperçu de lien Discord. Retourne None si rien de pertinent.

    `citations=False` pour un chat en TEXTE BRUT — Twitch. Le markdown n'y est
    pas rendu : le viewer lit `[²](<https://steamstore-a.akamaihd.net/…>)` en
    toutes lettres, au milieu d'une phrase déjà tronquée à 480 caractères.
    Constaté par l'owner le 2026-08-26 sur les patch notes Apex. On ne demande
    donc pas de marqueur, et on ne sert pas d'URL à coller — le contenu suffit,
    c'est lui qu'on est venu chercher.
    """
    cfg = getattr(bot.config, "rss", None)
    if not cfg or not cfg.enabled:
        return None
    if not any(getattr(f, "role", "") == "knowledge" and f.enabled for f in cfg.feeds):
        return None
    if not text or len(text.strip()) < 4:
        return None
    try:
        # Avec synthèse : les résultats pertinents PLUS la vue d'ensemble du patch le
        # plus récent, que BM25 ne remonte jamais de lui-même (cf.
        # `rss_derniere_synthese`).
        articles = await bot.db.rss_search_knowledge_avec_synthese(
            text, limit=3, max_age_seconds=cfg.knowledge_max_age_days * 86400
        )
    except Exception as e:  # noqa: BLE001 — jamais bloquant pour la réponse
        logger.warning("rss_knowledge: recherche échouée: {!r}", e)
        return None
    if not articles:
        return None
    consigne_citation = (
        "Quand tu t'appuies sur l'une, colle son marqueur cliquable juste après "
        "la phrase concernée, ex. « ... [¹](<url>) ». Garde les chevrons <>. "
        "N'invente jamais d'URL ni de numéro :"
        if citations else
        "Ne colle AUCUN lien ni marqueur de source : ce chat affiche le texte "
        "brut, une URL y est illisible. Dis l'info, c'est tout :"
    )
    lines = [
        "Actus que tu CONNAIS DÉJÀ sur ce sujet — inutile de chercher sur le web, tu "
        "as l'info ci-dessous. Elles sont classées par PERTINENCE, pas par date : "
        "l'âge de chacune est indiqué, fie-toi à lui et pas à l'ordre. Pour un "
        "« dernier patch note », prends donc le plus récent du lot, et dis de quand il "
        "date. " + consigne_citation
    ]
    # L'ANCRE de sa connaissance, et l'autorisation de conclure à l'absence.
    #
    # Sans elles : « le Wingman a eu un buff ? » lui tendait deux extraits vieux
    # de deux mois, et il répondait « oui, récemment, c'est encore d'actualité ».
    # Il n'avait aucun moyen de savoir si le silence venait du jeu ou du bord de
    # sa base — et rien ne lui disait qu'« il ne s'est rien passé » est une
    # réponse recevable. Un modèle à qui l'on tend trois extraits sur le Wingman
    # répond sur le Wingman.
    if ancre := await _rss_ancre_connaissance(bot):
        lines.append(ancre)
    for i, a in enumerate(articles, start=1):
        title = a.get("title") or ""
        summary = a.get("summary") or ""
        # L'âge, explicitement : le bloc prétendait un classement chronologique que le
        # tri BM25 ne respecte pas, et n'affichait aucune date. Wally présentait donc
        # un patch de sept semaines comme « le dernier » sans pouvoir s'en apercevoir.
        # Le marqueur n'est servi que là où il est cliquable : tendre une URL à un
        # modèle, c'est lui donner l'idée de la recopier.
        marqueur = f"[{_RSS_SUPERSCRIPTS[i]}](<{a.get('link') or ''}>) " if citations else "· "
        lines.append(f"{marqueur}{_rss_age(a)}{title} : {summary}")
    return "\n".join(lines)


async def _canonical_uid(bot, platform: str, user_id: str) -> str:
    """UID canonique `platform:raw_id` pour le ResponseGate.

    Le fact store est indexé sur la forme préfixée (convention CLAUDE.md).
    Avec l'id nu, le gate lisait 0 fait de relation et écrivait ses traces
    d'ignorance dans un espace mort — 73 faits orphelins au 2026-08-10.
    Passer par `_user_id()` résout aussi les alias vers l'uid canonique.
    """
    memory = getattr(bot, "memory", None)
    if memory is None:
        return f"{platform}:{user_id}"
    try:
        return memory._user_id(platform, user_id)
    except Exception as e:  # noqa: BLE001 — le gate ne doit jamais bloquer un message
        logger.warning("Gate : résolution de l'uid échouée pour {u} : {e!r}", u=user_id, e=e)
        return f"{platform}:{user_id}"


async def _apex_account_context(bot, platform: str, user_id: str) -> str:
    """« Compte Apex : Keychka (PC) », ou "" si la personne n'en a pas déclaré.

    Sans ce bloc, le compte lié ne servait QU'AU moment où l'outil était appelé :
    Wally ignorait qu'il parlait à quelqu'un qui joue, et « j'ai fait un 20 bombe
    hier » ne lui donnait aucune raison d'aller regarder ses stats.

    Le repli sur l'uid CANONIQUE n'est pas un luxe : le panneau admin ne lie
    qu'une identité à la fois, et sans lui la même personne serait inconnue dès
    qu'elle passe du Discord au chat Twitch.

    Importée par `twitch/handlers.py` — un bloc de contexte branché d'un seul
    côté rend Wally amnésique sur l'autre, sans erreur ni trace.
    """
    db = getattr(bot, "db", None)
    if db is None:
        return ""
    try:
        # `for_person` et non `get_account` : la liaison peut être posée sur
        # l'identité Twitch de quelqu'un qui écrit depuis Discord.
        compte = await db.apex_account_for_person(f"{platform}:{user_id}")
        if compte is None:
            canonique = await _canonical_uid(bot, platform, user_id)
            if canonique != f"{platform}:{user_id}":
                compte = await db.apex_account_for_person(canonique)
    except Exception as e:  # noqa: BLE001 — un bloc optionnel ne casse pas une réponse
        logger.warning("Apex : compte de la personne illisible : {e!r}", e=e)
        return ""
    if compte is None or not compte["apex_name"]:
        return ""
    return f"Compte Apex : {compte['apex_name']} ({compte['apex_platform'] or 'PC'})"


async def _third_party_mention_context(
    bot,
    platform: str,
    author_user_id: str,
    prelude: list[dict],
    context_messages: list[dict],
) -> str:
    """Detect mentions of third-party users and inject their memories."""
    # Gather text from recent messages.
    #
    # Le CONTENU seul : l'étiquette d'auteur était versée ici aussi, si bien que
    # le simple fait qu'Alice ait écrit dans les quinze derniers messages
    # injectait un bloc « Souvenirs sur Alice » dans le prompt de la
    # conversation de Bob — sans qu'elle ait été nommée par personne. Wally
    # pouvait alors ressortir à Bob des faits privés d'Alice. La fonction dit
    # « detect mentions » : quelqu'un qui parle ne se mentionne pas lui-même.
    texts = []
    for msg in (prelude or []):
        texts.append(msg.get("content", ""))
    for msg in (context_messages or []):
        content = msg.get("content", "")
        if isinstance(content, str):
            texts.append(content)

    full_text = " ".join(texts)
    words = re.findall(r"[A-Za-z0-9_À-ÿ]{3,}", full_text)

    # Build candidate set: starts with uppercase or in alias map
    alias_cache = bot.memory._alias_cache
    known_nicknames = {
        k[len("nickname:"):] for k in alias_cache
        if k.startswith("nickname:")
    }

    candidates = set()
    for word in words:
        if word[0].isupper() or word.lower() in known_nicknames:
            candidates.add(word)

    if not candidates:
        return ""

    # Load known users for fuzzy matching
    try:
        users = await bot.db.list_memory_users()
    except Exception:
        users = []
    known_usernames = {u["username"].lower(): u for u in users if u.get("username")}

    # Remove the current author by user_id AND by their username (for Discord snowflake IDs)
    author_lower = author_user_id.lower()
    author_username_lower = None
    for u in users:
        uid = u.get("user_id", "")
        if uid == author_user_id or uid.endswith(":" + author_user_id):
            author_username_lower = (u.get("username") or "").lower()
            break
    candidates = {
        c for c in candidates
        if c.lower() != author_lower
        and (author_username_lower is None or c.lower() != author_username_lower)
    }

    parts = []
    processed = 0

    for token in sorted(candidates):  # sorted for determinism
        if processed >= 2:
            break

        token_lower = token.lower()
        cache_key = f"nickname:{token_lower}"

        if cache_key in alias_cache:
            # Exact alias match
            canonical_uid = alias_cache[cache_key]  # e.g. "twitch:mkszedd"
            uid_parts = canonical_uid.split(":", 1)
            if len(uid_parts) == 2:
                third_platform, third_raw_id = uid_parts
                try:
                    memories_text = await bot.memory.search(third_platform, third_raw_id, query=token)
                    if memories_text:
                        # Find username for display
                        display = third_raw_id
                        for u in users:
                            if u.get("user_id") == canonical_uid:
                                display = u.get("username", third_raw_id)
                                break
                        parts.append(f"--- Souvenirs sur {display} ---\n{memories_text}")
                        processed += 1
                # Un tiers illisible ne doit pas emporter les AUTRES : la boucle continue
                # avec les suivants. Journalisé parce qu'ici on perd du CONTEXTE, pas un
                # emoji — Wally répondra sans savoir ce qu'il sait de cette personne, et
                # rien d'autre ne le dirait.
                except Exception as exc:  # noqa: BLE001 — un tiers ne casse pas les autres
                    logger.warning("Souvenirs d'un tiers illisibles ({u}) : {e!r}", u=third_raw_id, e=exc)
        else:
            # Fuzzy match against known usernames
            best_ratio = 0.0
            best_username = None
            for uname_lower, udata in known_usernames.items():
                ratio = difflib.SequenceMatcher(None, token_lower, uname_lower).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_username = udata.get("username", uname_lower)

            if best_ratio >= 0.75 and best_username:
                pct = int(best_ratio * 100)
                parts.append(
                    f"Note interne : '{token}' ressemble à {best_username} (confiance {pct}%) "
                    f"— si c'est bien lui, mentionne-le naturellement"
                )
                processed += 1

    return "\n\n".join(parts)


def _conv_channel(message: discord.Message) -> str:
    """Segment de chemin pour le log de conversation : ``guild/canal`` (ou ``dm``)."""
    guild = getattr(getattr(message, "guild", None), "name", None)
    chan = getattr(message.channel, "name", None) or "dm"
    return f"{guild}/{chan}" if guild else chan


def _clog(bot: "WallyDiscord", channel: str, event_type: str, **fields) -> None:
    """Journalise un événement de conversation si le logger est câblé (no-op sinon)."""
    clog = getattr(bot, "conv_log", None)
    if clog is not None:
        clog.log("discord", channel, event_type, **fields)
    # Observateurs en mémoire (signal de réception, trace de ses propres actes) :
    # ce point voit passer TOUS les événements du salon, et il est le seul.
    # Ne lève jamais.
    observe_event(clog, "discord", channel, event_type, fields)


def maybe_clear_owner_gate(gate, config, author_id: str, is_dm: bool) -> None:
    """Libère le fil de sollicitation owner quand l'owner répond en DM."""
    if gate is None or not is_dm:
        return
    if str(author_id) == str(getattr(getattr(config, "bot", None), "owner_discord_id", "")):
        gate.clear()


async def handle_message(bot: "WallyDiscord", message: discord.Message) -> None:
    logger.debug("on_message: author={} bot={} guild={} channel={}", message.author, message.author.bot, getattr(message.guild, 'id', 'dm'), message.channel.id)
    if message.author.bot:
        return

    # Utilisateur banni depuis l'admin → Wally l'ignore totalement (aucune réponse, aucune mémoire)
    if await bot.db.is_chat_user_banned(str(message.author.id)):
        logger.debug("Ignoring banned user {}", message.author.id)
        return

    # Ignore entièrement les guilds blacklistés (ex: serveurs de test/notification)
    if message.guild and message.guild.id in bot.config.discord.ignored_guilds:
        return

    # Dedup: Discord can replay events on WebSocket reconnect — skip already-processed messages
    _now = time.time()
    if message.id in _processed_message_ids:
        logger.debug("Duplicate on_message event for id={}, skipping", message.id)
        return
    _processed_message_ids[message.id] = _now
    # Purge entries older than 120s to avoid unbounded growth
    for _mid in [k for k, v in _processed_message_ids.items() if _now - v > 120]:
        del _processed_message_ids[_mid]

    # Dashboard message counter
    if getattr(bot, "dashboard_state", None) is not None:
        bot.dashboard_state.message_count += 1
        bot.dashboard_state.message_count_discord += 1

    user_id = str(message.author.id)
    # DMs et always_trigger_channels : tout message est un trigger
    _is_dm = message.guild is None
    # L'owner répond en DM → libère le fil de sollicitation (un seul à la fois).
    maybe_clear_owner_gate(
        getattr(bot, "owner_gate", None), bot.config,
        author_id=user_id, is_dm=_is_dm,
    )
    _is_always_trigger = _is_dm or message.channel.id in getattr(bot.config.discord, "always_trigger_channels", [])
    channel_allowed = _is_always_trigger or _is_channel_allowed(bot.config, message.channel.id, message.guild.id if message.guild else None)

    # Contenu enrichi : inclut un tag [image] si des images sont jointes
    _has_images = any(
        a.content_type and a.content_type.startswith("image/")
        for a in message.attachments
    )
    _enriched_content = _resolve_mentions(message, message.content or "")
    if _has_images and not _enriched_content:
        n = sum(1 for a in message.attachments if a.content_type and a.content_type.startswith("image/"))
        _enriched_content = f"[a envoyé {'une image' if n == 1 else f'{n} images'}]"
    elif _has_images:
        n = sum(1 for a in message.attachments if a.content_type and a.content_type.startswith("image/"))
        _enriched_content += f" [+ {'une image' if n == 1 else f'{n} images'}]"

    # Un message qui arrive en direct n'a jamais de réaction ; un message rejoué
    # au rattrapage, si. Dans ce cas le contexte dit qui a réagi et avec quoi.
    # Le contenu brut reste celui donné à la mémoire, aux faits et aux logs.
    _reaction_note = await _reaction_roster(bot, message) if channel_allowed else ""
    _context_content = _with_reactions(_enriched_content, _reaction_note)

    # Capture passive + récupération prelude AVANT d'ajouter le message courant
    if channel_allowed:
        prelude = bot.memory.get_prelude(str(message.channel.id))
        author_label = _author_label(message.author)
        bot.memory.append_prelude(
            str(message.channel.id), author_label, _context_content
        )
        # Enregistrement dans la session active du canal (tous les messages)
        if getattr(bot, "fact_extractor", None) is not None:
            bot.fact_extractor.record_message(
                str(message.channel.id), "discord", user_id,
                author_label, _enriched_content,
                is_reply=message.reference is not None,
                origin=_channel_origin(message.channel),
            )
        _clog(
            bot, _conv_channel(message), "message_in",
            trace_id=str(message.id), author=author_label, author_id=user_id,
            content=_enriched_content, is_reply=message.reference is not None,
            has_images=_has_images,
        )
    else:
        prelude = []

    # Reaction tracking: detect positive replies to Wally's messages
    tracker = getattr(bot, "reaction_tracker", None)
    if tracker and message.reference and message.reference.message_id:
        tracker.record_discord_reply(
            message.reference.message_id, message.content, message.author.bot,
        )

    # Spam detection — track all messages in allowed channels
    if channel_allowed and message.guild:
        if await _check_spam(bot, message):
            return

    # Perception cognitive : le « cerveau » perçoit TOUS les messages des salons
    # autorisés (pas seulement ceux qui mentionnent Wally), afin de pouvoir
    # intervenir spontanément quand c'est pertinent sans avoir besoin d'être ping.
    # Aligné sur le comportement Twitch (cf. twitch/handlers.py). La boucle
    # cognitive applique ses propres garde-fous (cooldowns, anti-rumination,
    # conscience sociale) avant tout SPEAK.
    if channel_allowed and getattr(bot, "cognitive_loop", None) is not None:
        try:
            # « Pertinent » = le message vise Wally (@mention ou nom déclencheur)
            # → cadence cognitive vive. Le DM est géré par is_dm. Le reste =
            # perception passive (Phase 2c).
            _trigger_names = getattr(getattr(bot.config, "bot", None), "trigger_names", []) or []
            _content_lower = (message.content or "").lower()
            _relevant = (bot.user in message.mentions) or any(
                n.lower() in _content_lower for n in _trigger_names
            )
            bot.cognitive_loop.notify_activity(
                channel_id=message.channel.id,
                author=str(message.author.display_name),
                content=_with_reactions(
                    _resolve_mentions(message, message.content or ""), _reaction_note
                ),
                message_id=str(message.id),
                is_dm=message.guild is None,
                relevant=_relevant,
                user_key=f"discord:{message.author.id}",
            )
        except Exception as e:
            logger.warning("cognitive_loop.notify_activity failed: {e!r}", e=e)

    content_lower = message.content.lower()
    mentioned = bot.user in message.mentions
    always_trigger = _is_always_trigger
    # Une question de Wally restée en suspens vaut invitation à répondre : sa
    # propre relance ne doit pas exiger qu'on le renomme.
    answers_question = channel_allowed and _consume_open_question(
        message.channel.id, message.author.id
    )
    triggered = always_trigger or mentioned or answers_question or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )
    logger.debug("triggered={} mentioned={} always={} channel={}", triggered, mentioned, always_trigger, message.channel.id)
    if not triggered:
        # Motif du silence, affiné au fil des gardes traversées. Même parité que
        # Twitch : le silence est une décision, et il ne laissait aucune trace.
        _silence = "non interpellé"
        # Se taire n'est pas ne rien voir. La description d'une image ne se
        # faisait que dans `_post_process`, donc SEULEMENT quand Wally répondait :
        # 23 faits en mémoire pour 230 messages avec image. D'une œuvre postée
        # dans un salon où il n'a rien à dire, il ne gardait que « Untel a envoyé
        # une image » — de quoi remercier la bonne personne, jamais de quoi dire
        # ce qu'elle a fait. Les deux chemins s'excluent, il n'y a pas de double
        # appel : `_post_process` ne tourne que sur une réponse.
        if channel_allowed and _has_images:
            _fire(_memoriser_image(
                bot,
                platform="discord",
                user_id=user_id,
                display_name=message.author.display_name,
                image_urls=[
                    a.url for a in message.attachments
                    if a.content_type and a.content_type.startswith("image/")
                ][:4],
                caption=message.content or "",
                origin=_channel_origin(message.channel),
            ))
        # Passive emoji reaction on non-trigger messages (Discord only)
        if channel_allowed and random.random() < bot.config.discord.emoji_reaction_probability:
            curiosity = bot.emotion.get_state().get("curiosity", 0.0)
            passive_emoji = _pick_passive_emoji(message.content, curiosity)
            if passive_emoji:
                try:
                    await message.add_reaction(passive_emoji)
                    _clog(
                        bot, _conv_channel(message), "reaction",
                        trace_id=str(message.id), emoji=passive_emoji, passive=True,
                    )
                # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
                # qui ne nous regardent pas : message supprimé entre-temps, permissions du
                # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
                # réponse déjà écrite pour un emoji absent serait le pire échange possible.
                except Exception:
                    pass
        # Spontaneous intervention
        if channel_allowed and bot.config.bot.spontaneous_discord_enabled:
            state = bot.emotion.get_state()
            trigger_type = _check_spontaneous_trigger(
                message.content,
                curiosity=state.get("curiosity", 0.0),
                anger=state.get("anger", 0.0),
                boredom=state.get("boredom", 0.0),
            )
            chan_id = str(message.channel.id)
            now = time.time()
            cooldown = bot.config.bot.spontaneous_cooldown_seconds
            cooldown_ok = now - _spontaneous_cooldowns.get(chan_id, 0) >= cooldown

            if trigger_type and cooldown_ok:
                prob = (
                    bot.config.bot.spontaneous_passion_probability
                    if trigger_type == "passion"
                    else bot.config.bot.spontaneous_probability
                )
                if random.random() < prob:
                    _spontaneous_cooldowns[chan_id] = now
                    _clog(
                        bot, _conv_channel(message), "gate_decision",
                        trace_id=str(message.id), triggered=False, spontaneous=True,
                        trigger_type=trigger_type, decision="spontaneous",
                    )
                    _fire(_spontaneous_respond(bot, message, prelude_snapshot=prelude))
                    return
                _silence = f"tirage spontané perdu ({trigger_type}, p={prob})"
            elif trigger_type:
                _silence = "spontané en cooldown"
        # Une question posée au salon entre au registre ; le balayage d'après
        # lui laisse le temps d'être relevée par quelqu'un d'autre.
        if channel_allowed and message.guild is not None:
            _fire(_veiller_questions(bot, message, prelude_snapshot=prelude))
        # Journalisé sur le MÊME périmètre que `message_in` ci-dessus : hors
        # salon autorisé, rien n'entre, donc rien à expliquer.
        if channel_allowed:
            _clog(
                bot, _conv_channel(message), "gate_decision",
                trace_id=str(message.id), triggered=False, spontaneous=False,
                decision="silence", reason=_silence,
            )
        return

    if not channel_allowed:
        logger.info(
            "Triggered by {user} but channel #{ch} (guild {g}) not allowed — skipping",
            user=message.author.display_name,
            ch=message.channel.id,
            g=message.guild.id if message.guild else "dm",
        )
        return

    guild_id = str(message.guild.id) if message.guild else "dm"

    if await bot.db.is_muted(user_id, guild_id) and not bot.persona.is_beloved("discord", user_id):
        emoji = random.choice(TIMEOUT_REACTIONS)
        # Le SEUL `add_reaction` du fichier qui n'était pas protégé. Un
        # `discord.Forbidden` — permission « Ajouter des réactions » absente —
        # remontait hors de `handle_message`, et la ligne suivante était sautée :
        # la colère cessait de monter pendant le mute, comportement pourtant
        # documenté, dans tout salon où Wally n'a pas cette permission.
        try:
            await message.add_reaction(emoji)
        except Exception as exc:  # noqa: BLE001 — réagir est un bonus, pas le sujet
            logger.debug("Réaction de mute impossible: {e!r}", e=exc)
        # Appliqué INDÉPENDAMMENT du succès de la réaction.
        if bot.config.discord.spam_detection.enabled:
            bot.emotion.apply_delta("anger", bot.config.discord.spam_detection.spam_anger_delta)
        return

    first_contact = not await bot.db.is_welcomed(user_id, guild_id)

    # Gate : Wally décide s'il répond (RESPOND), se tait (IGNORE/DEFER) ou
    # réagit juste en emoji (REACT) — même sur un trigger. Le silence est un
    # choix autonome. Fallback RESPOND si le gate est absent ou échoue : jamais
    # de blocage silencieux dû à une panne.
    gate = getattr(bot, "response_gate", None)
    decision, gate_reason, gate_emoji = "RESPOND", None, None
    if gate is not None:
        try:
            from bot.intelligence.memory.facts import FactCategory
            _store = gate._fact_store  # même paquet : accès interne assumé
            _gate_uid = await _canonical_uid(bot, "discord", user_id)
            _rel = await _store.get_by_user(_gate_uid, categories=[FactCategory.REL])
            _desires = await _store.get_by_user("wally:self", categories=[FactCategory.DESIRE])
            _last = getattr(bot, "_wally_recent_speaks", {}).get(message.channel.id)
            # Toutes les emotes de TOUS les serveurs du bot (Nitro-like), dédupliquées.
            _guild_emojis = list(dict.fromkeys(e.name for e in bot.emojis))
            # Notes d'usage apprises ("nom → quand l'utiliser") → guide le choix.
            _emote_notes = await _store.get_by_user("wally:emotes", categories=[FactCategory.PREF])
            _emoji_usage = [f.content for f in _emote_notes]
            _thread = []
            try:
                _thread = bot.memory.get_context(str(message.channel.id))[-5:]
            except Exception:
                _thread = []
            _gd = await gate.decide(
                message_content=_resolve_mentions(message, message.content or ""),
                author_user_id=_gate_uid,
                emotion_state=bot.emotion.get_state(),
                relationship_facts=_rel,
                active_desires=_desires,
                is_mentioned=mentioned,
                is_triggered=True,
                is_dm=message.guild is None,
                wally_last_message=_last,
                available_emojis=_guild_emojis,
                emoji_usage=_emoji_usage,
                recent_messages=_thread,
                thread_depth=thread_sense.profondeur(str(message.channel.id), user_id),
            )
            decision, gate_reason, gate_emoji = _gd.decision, _gd.reason, _gd.emoji
        except Exception as e:
            logger.warning("gate.decide() failed, fallback RESPOND: {e!r}", e=e)

    _clog(
        bot, _conv_channel(message), "gate_decision",
        trace_id=str(message.id), triggered=True, mentioned=mentioned,
        always_trigger=always_trigger, spontaneous=False,
        decision=decision.lower(), reason=gate_reason,
    )

    # Non-réponse (IGNORE / DEFER / REACT) : Wally se tait MAIS laisse toujours un
    # emoji — son humeur, ou pourquoi il ne répond pas. Le gate fournit l'emoji
    # contextuel ; à défaut, fallback sur l'émotion dominante (résout toujours).
    if decision in ("IGNORE", "DEFER", "REACT"):
        # Le commentaire promet « il laisse TOUJOURS un emoji ». Or
        # `_resolve_emoji` rend la chaîne BRUTE du gate quand aucune emote custom
        # ne correspond : « thinking » ou tout mot inventé par le modèle partait
        # tel quel à `add_reaction`, qui lève un 400. Sans repli ni log, Wally ne
        # laissait alors AUCUNE trace — l'utilisateur voyait un silence pur, et
        # rien n'indiquait que le gate avait pourtant répondu.
        _raw = gate_emoji or _mood_emoji(bot.emotion.get_state())
        try:
            await message.add_reaction(_resolve_emoji(_raw, bot))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Emoji du gate refusé ({r}) — repli sur l'humeur : {e!r}",
                         r=_raw, e=exc)
            try:
                await message.add_reaction(_mood_emoji(bot.emotion.get_state()))
            except Exception:  # noqa: BLE001 — le silence total reste le pire cas
                pass
        return

    await _respond(bot, message, user_id, guild_id, prelude, first_contact=first_contact, enriched_content=_enriched_content)


_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)]) ")


def _is_list_item(line: str) -> bool:
    return bool(_LIST_RE.match(line))



async def _send_in_parts(
    message: discord.Message, text: str, file: "discord.File | None" = None
) -> tuple[int | None, int]:
    """Split text on newlines, group consecutive list items, send as separate messages.

    Retourne ``(id du premier message envoyé, nombre de parts)`` — le compte de
    parts alimente l'event ``message_out`` (un reply découpé en N messages).

    `file` est joint au PREMIER message : une courbe de progression accompagne
    la phrase qui la commente, elle n'arrive pas trois messages plus loin.
    """
    text = redact(text)   # un mot en jeu (pendu) ne sort pas, même par ce chemin
    # Dernier filet avant l'envoi : le modèle glisse parfois une didascalie de
    # roleplay (« (je hausse les épaules) ») malgré la consigne de VOICE.md.
    text = strip_stage_directions(text)
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return None, 0

    # Group lines: consecutive list items are bundled into one message
    groups: list[str] = []
    current: list[str] = []
    in_list = False
    for line in lines:
        if _is_list_item(line):
            if not in_list:
                if current:
                    groups.append("\n".join(current))
                current = []
                in_list = True
            current.append(line)
        else:
            if in_list:
                groups.append("\n".join(current))
                current = []
                in_list = False
            current.append(line)
    if current:
        groups.append("\n".join(current))

    # Un groupe (paragraphe/bloc de liste) peut dépasser la limite Discord de
    # 2000 car. — on le redécoupe alors proprement en sous-parts.
    parts: list[str] = []
    for group in groups:
        parts.extend(split_for_discord(group))
    if not parts:
        # Une courbe sans texte n'aurait aucun sens : le graphe illustre une
        # phrase, il ne la remplace pas.
        return None, 0

    first_msg = await message.reply(
        parts[0], file=file, allowed_mentions=_ALLOWED_MENTIONS
    ) if file is not None else await message.reply(
        parts[0], allowed_mentions=_ALLOWED_MENTIONS
    )
    for part in parts[1:]:
        await asyncio.sleep(random.uniform(0.6, 1.8))
        await message.channel.send(part, allowed_mentions=_ALLOWED_MENTIONS)
    _note_open_question(message.channel.id, message.author.id, " ".join(parts))
    return first_msg.id, len(parts)


async def _apex_chart_file(bot, requester: str) -> "discord.File | None":
    """La courbe de progression Apex en attente pour `requester`, ou None.

    Rien à faire quand personne n'a demandé de progression : le service ne rend
    un graphe que si l'action `progression` vient de tourner pour cette
    personne, et il ne le rend qu'une fois.
    """
    api = getattr(bot, "apex_api", None)
    if api is None or not hasattr(api, "derniere_courbe"):
        return None
    try:
        buf = await api.derniere_courbe(requester)
    except Exception as exc:  # noqa: BLE001 — un graphe raté ne retient pas la réponse
        logger.warning("Apex: courbe indisponible: {e!r}", e=exc)
        return None
    if buf is None:
        return None
    return discord.File(buf, filename="progression.png")


async def _fetch_referenced_message(
    message: discord.Message,
) -> "discord.Message | None":
    """Récupère le message auquel `message` répond (resolved ou fetch), ou None.

    Sert à la fois à enrichir la recherche mémoire (chercher les faits liés au
    contenu cité) et à injecter le contexte de la citation dans le prompt.
    """
    ref = message.reference
    if not (ref and ref.message_id):
        return None
    try:
        ref_msg = ref.resolved
        if ref_msg is None:
            ref_msg = await message.channel.fetch_message(ref.message_id)
        if isinstance(ref_msg, discord.Message):
            return ref_msg
    except Exception as e:
        logger.debug("Failed to fetch referenced message: {e!r}", e=e)
    return None


async def _auto_scrape_block(bot: "WallyDiscord", message: "discord.Message") -> str:
    """Scrape le 1er lien web d'un message (cooldown par canal). Retourne un bloc ou ""."""
    scrape = getattr(bot, "scrape", None)
    if not scrape or not scrape.available:
        return ""
    if not bot.config.firecrawl.auto_scrape_links:
        return ""

    match = _URL_RE.search(message.content or "")
    if not match:
        return ""
    url = match.group(0).rstrip(").,;")
    if not scrape.is_scrapable_url(url):
        return ""

    channel_id = str(message.channel.id)
    now = time.time()
    last = _scrape_cooldowns.get(channel_id, 0.0)
    if now - last < bot.config.firecrawl.auto_scrape_cooldown_s:
        return ""
    _scrape_cooldowns[channel_id] = now

    try:
        content = await scrape.scrape(url)
    except Exception as exc:
        logger.warning("Auto-scrape failed for {u}: {e!r}", u=url, e=exc)
        return ""
    if not content:
        return ""
    return f"--- Page web ---\n{content}\n"


async def _respond(
    bot: "WallyDiscord",
    message: discord.Message,
    user_id: str,
    guild_id: str,
    prelude: list[dict],
    first_contact: bool = False,
    enriched_content: str = "",
) -> None:
    try:
        # Hors du `try` global : celui-ci se contente de logger et de sortir.
        # Dans un salon où Wally peut écrire mais pas réagir, un 403 sur cette
        # ligne le rendait TOTALEMENT muet quand on le mentionnait, sans autre
        # trace qu'un « 403 Forbidden ».
        try:
            await message.add_reaction("🔍")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Réaction 🔍 refusée dans {c} : {e!r}", c=message.channel.id, e=exc)

        platform = "discord"
        trust = await bot.db.get_trust_score(platform, user_id)

        # Si c'est une réponse à un message, on récupère le message cité tôt :
        # son contenu enrichit la recherche mémoire (sinon Wally cherche sur
        # "j'ai po la ref" → 0 fait → il comble le vide en inventant) et sert
        # plus bas à injecter la citation dans le prompt.
        # Mentions <@id> → pseudo lisible, pour que le LLM voie QUI est pingé
        # (recherche mémoire, citation, texte courant) au lieu d'un identifiant nu.
        resolved_content = _resolve_mentions(message, message.content or "")
        ref_msg = await _fetch_referenced_message(message)
        replied_quote = (
            _resolve_mentions(ref_msg, ref_msg.content or "").strip() if ref_msg else ""
        )
        search_query = (
            f"{resolved_content}\n{replied_quote}".strip()
            if replied_quote else resolved_content
        )

        mem_context = await bot.memory.search(platform, user_id, search_query, context_messages=prelude)

        # Temporal activity: inject absence note if user hasn't been seen in 7+ days
        try:
            last_seen = await bot.db.get_last_interaction(f"{platform}:{user_id}")
            if last_seen:
                days_ago = int((time.time() - last_seen) / 86400)
                if days_ago >= 7:
                    absence_note = f"\nDernière interaction avec cet utilisateur : il y a {days_ago} jours."
                    mem_context = (mem_context + absence_note) if mem_context else absence_note.strip()
        except Exception as exc:  # noqa: BLE001 — bloc optionnel
            logger.warning("Mémoire : bloc « note d'absence » ignoré : {e!r}", e=exc)

        # ── Fetch context messages early (needed for priority 6) ──────
        context_messages = await bot.memory.get_context_summarized_if_needed(
            str(message.channel.id)
        )

        # ── Assemble memory context with token budget ──────────────────
        max_tokens = bot.config.bot.memory_context_max_tokens
        memory_parts: list[tuple[int, str, str]] = []

        # Priority 1: Semantic memories (already fetched)
        if mem_context:
            memory_parts.append((1, mem_context, "souvenirs"))

        # Priority 2: Résumés de sessions précédentes (cross-session recall)
        try:
            summaries = await bot.db.get_recent_session_summaries(
                platform, str(message.channel.id), limit=3
            )
            recall_block = build_session_recall_block(summaries)
            if recall_block:
                memory_parts.append((2, recall_block, "recall-session"))
        except Exception as exc:  # noqa: BLE001 — bloc optionnel
            logger.warning("Mémoire : bloc « recall de session » ignoré : {e!r}", e=exc)

        # Priorité 3 : la question de suivi en attente. Retirée par accident le
        # 2026-06-20 (`ad975eb3`) — la place est restée VIDE entre 2 et 4
        # pendant deux mois, et Wally n'a plus jamais posé de question.
        try:
            question_block = await bot.memory.get_pending_question_directive(
                platform, user_id)
            if question_block:
                memory_parts.append((3, question_block, "question"))
        except Exception as exc:  # noqa: BLE001 — un bonus ne fait pas tomber un tour
            logger.warning("Mémoire : question en attente ignorée : {e!r}", e=exc)

        # Priority 4: Recent successful jokes for this channel
        try:
            recent_jokes = await bot.db.get_recent_jokes(str(message.channel.id), limit=3)
            if recent_jokes:
                jokes_block = "--- Tes blagues récentes qui ont bien marché dans ce salon ---"
                for j in recent_jokes:
                    jokes_block += f'\n- "{j}"'
                memory_parts.append((4, jokes_block, "blagues"))
        except Exception as exc:  # noqa: BLE001 — bloc optionnel
            logger.warning("Mémoire : bloc « blagues récentes » ignoré : {e!r}", e=exc)

        # Priority 5: Community topics (sujets de communauté enrichis)
        try:
            topics = await bot.db.get_topics(limit=5)
            if topics:
                topics_block = "--- Sujets de la communauté ---"
                for t in topics:
                    names = ", ".join(p["name"] for p in t["participants"]) if t["participants"] else ""
                    who = f" — {names} en parlent" if names else ""
                    topics_block += f'\n- {t["name"]}{who} — ton avis : "{t["opinion"]}"'
                memory_parts.append((5, topics_block, "topics"))
        except Exception as exc:  # noqa: BLE001 — bloc optionnel
            logger.warning("Mémoire : bloc « sujets de la communauté » ignoré : {e!r}", e=exc)

        # Priority 6: Third-party mentions
        try:
            third_party_ctx = await _third_party_mention_context(
                bot, platform, user_id, prelude, context_messages
            )
            if third_party_ctx:
                memory_parts.append((6, third_party_ctx, "tiers"))
        except Exception as exc:  # noqa: BLE001 — bloc optionnel
            logger.warning("Mémoire : bloc « mentions de tiers » ignoré : {e!r}", e=exc)

        mem_context = assemble_memory_context(memory_parts, max_tokens)

        # Recall RSS knowledge (ex. Apex) : injecté HORS budget mémoire pour que
        # les marqueurs de citation [¹](<url>) survivent à la troncature. Placé
        # avant les tools → le LLM a l'actu sous les yeux plutôt que de web_search.
        rss_block = None
        try:
            rss_block = await _rss_knowledge_context(bot, message.content or "")
            if rss_block:
                mem_context = f"{mem_context}\n\n{rss_block}" if mem_context else rss_block
        except Exception as e:  # noqa: BLE001 — jamais bloquant pour la réponse
            logger.warning("rss_knowledge: injection ignorée: {!r}", e)
        # Question d'actu + recall RSS positif → Wally a déjà l'info. On coupe les
        # outils de lookup (offre ET exécution) : DeepSeek hallucine parfois un
        # appel web_search même non offert, donc filtrer la liste ne suffit pas.
        _suppress_lookup = bool(rss_block) and _is_news_query(message.content)

        # Trust/love go in separate relationship_context (outside token budget)
        love = await bot.db.get_love_score(platform, user_id, bot.config.bot.love_decay_lambda)
        relationship_context = f"Niveau de confiance : {trust:.2f}/1.0\nNiveau d'affection : {love:.2f}/1.0"

        # Portrait de la personne (user model) — non-fatal.
        # Via `_user_id()` : le portrait est écrit sous l'uid CANONIQUE (le
        # modeler lit les user_id du fact store). Concaténer `platform:raw_id`
        # privait de leur portrait les 22 comptes Twitch liés à un Discord.
        person_context = ""
        try:
            _pid = await _canonical_uid(bot, platform, user_id)
            person_context = await bot.db.get_user_profile(_pid) or ""
        except Exception as exc:  # noqa: BLE001 — bloc optionnel
            logger.warning("Mémoire : bloc « portrait de la personne » ignoré : {e!r}", e=exc)
        # Le compte Apex déclaré, s'il y en a un : un fait, pas une déduction du
        # portrait nocturne. Il rejoint le portrait plutôt que le budget mémoire
        # — c'est une propriété de la personne, pas un souvenir en concurrence
        # avec d'autres.
        if apex_compte := await _apex_account_context(bot, platform, user_id):
            person_context = f"{person_context}\n{apex_compte}" if person_context else apex_compte

        # Fallback cold start si prelude vide
        if not prelude:
            prelude = await _fetch_discord_history(
                message.channel, bot.config.bot.prelude_window_size,
                exclude_id=message.id, bot=bot,
            )

        # Persistent notes
        try:
            persistent_notes = await bot.db.get_persistent_notes()
        except Exception as exc:  # noqa: BLE001 — bloc optionnel
            logger.warning("Mémoire : bloc « notes persistantes » ignoré : {e!r}", e=exc)
            persistent_notes = []

        situation: dict = {"platform": "Discord"}
        if message.guild:
            situation["server"] = message.guild.name
        if isinstance(message.channel, discord.TextChannel):
            situation["channel"] = f"#{message.channel.name}"

        presence_context = _presence_line(bot, user_id, message.author.display_name)

        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=mem_context,
            situation=situation,
            presence_context=presence_context,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            relationship_context=relationship_context,
            person_context=person_context,
            persistent_notes=persistent_notes or None,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
            user_directive=bot.persona.user_directive("discord", user_id),
            # Même mesure que sur Twitch : c'est le même Wally, il doit voir sa
            # propre insistance et ses propres tics des deux côtés.
            thread_context=thread_sense.bloc_fil(
                str(message.channel.id), user_id,
                nom_personne=message.author.display_name,
                paliers=bot.persona.fil_directives,
            ),
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_messages)

        # Extraction des images (message courant)
        image_urls = [
            a.url for a in message.attachments
            if a.content_type and a.content_type.startswith("image/")
        ][:4]

        author_label = _author_label(message.author)

        # `ref_msg` (message cité) a déjà été récupéré plus haut pour la recherche
        # mémoire. On l'utilise ici pour injecter la citation + ses images dans le
        # prompt, afin que Wally sache à QUOI on répond, même hors fenêtre de contexte.
        replied_image_context = ""
        replied_text_context = ""
        if ref_msg is not None:
            try:
                # Texte du message cité (tronqué) — auteur attribué explicitement
                ref_text = " ".join(_resolve_mentions(ref_msg, ref_msg.content or "").split())
                if ref_text:
                    if len(ref_text) > 300:
                        ref_text = ref_text[:300] + "…"
                    ref_who = (
                        f"toi ({bot.config.bot.name})" if ref_msg.author.id == bot.user.id
                        else _author_label(ref_msg.author)
                    )
                    replied_text_context = (
                        f"\n↪ [{author_label} répond à ce message de {ref_who}] : "
                        f"« {ref_text} »\n"
                    )
                # Images du message référencé — seulement si le message courant
                # n'en contient pas déjà
                if not image_urls:
                    _img_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp")
                    ref_images = [
                        a.url for a in ref_msg.attachments
                        if (a.content_type and a.content_type.startswith("image/"))
                        or a.filename.lower().endswith(_img_exts)
                    ]
                    # Images dans les embeds (URLs CDN uniquement, pas attachment://)
                    if not ref_images:
                        for embed in ref_msg.embeds:
                            if embed.image and embed.image.url and not embed.image.url.startswith("attachment://"):
                                ref_images.append(embed.image.url)
                    image_urls = ref_images[:4]
                    if image_urls:
                        # Contexte sur l'image référencée
                        is_wally_image = ref_msg.author.id == bot.user.id
                        ref_desc = ""
                        for embed in ref_msg.embeds:
                            if embed.title:
                                ref_desc += f" Titre: {embed.title}."
                            if embed.description:
                                ref_desc += f" Prompt: {embed.description}"
                        if is_wally_image:
                            replied_image_context = (
                                f"[L'utilisateur répond à une image que TU as générée avec /imagine."
                                f"{ref_desc} Tu es l'auteur de cette image.]\n"
                            )
                        else:
                            replied_image_context = (
                                f"[L'utilisateur répond à un message contenant une image."
                                f"{ref_desc}]\n"
                            )
            except Exception as e:
                logger.debug("Failed to process referenced message: {e!r}", e=e)

        # Texte à envoyer — ajoute un marqueur image si texte+image pour que le LLM traite l'image
        if image_urls and resolved_content:
            n = len(image_urls)
            img_tag = "[Image jointe]" if n == 1 else f"[{n} images jointes]"
            text_content = f"{resolved_content}\n{img_tag}"
        elif image_urls:
            text_content = "Regarde cette image."
        else:
            text_content = resolved_content

        # ── Vision : le LLM principal est AVEUGLE (DeepSeek ignore image_urls).
        # On analyse réellement l'image via VisionService et on injecte les faits
        # dans le contexte texte, pour que Wally commente l'image au lieu d'inventer.
        # L'analyse est réutilisée plus bas par _post_process (mémoire) sans 2e appel.
        image_analysis: str | None = None
        image_analysis_context = ""
        if image_urls:
            vision = getattr(bot, "vision", None)
            if vision is not None and vision.available:
                async with message.channel.typing():
                    image_analysis = await vision.analyze(
                        image_urls, caption=resolved_content
                    )
                if image_analysis:
                    image_analysis_context = (
                        "\n[ANALYSE VISUELLE de l'image jointe — ce que tu VOIS "
                        "réellement, des faits vérifiés ; commente-les, n'invente "
                        f"rien d'autre] :\n{image_analysis}\n"
                    )
                    _clog(
                        bot, _conv_channel(message), "image_analysis",
                        trace_id=str(message.id), analysis=image_analysis[:500],
                    )

        target_notice = (
            f"\n⚠️ Tu réponds à {author_label}. "
            "Le contexte ci-dessus contient des messages de PLUSIEURS personnes — "
            "attribue chaque propos à son auteur (indiqué entre crochets). "
            "Ne confonds JAMAIS les propos d'un utilisateur avec ceux d'un autre. "
            f"Si tu nommes ton interlocuteur, appelle-le par SON pseudo exact ({author_label}) — "
            "n'utilise JAMAIS le nom d'une autre personne présente dans le contexte à sa place. "
            "Réponds UNIQUEMENT avec ton propre texte — ne répète jamais le message auquel tu réponds."
        )
        auto_scrape_block = await _auto_scrape_block(bot, message)
        mention_block = _build_mention_directory(message)
        user_content = (
            prelude_block
            + auto_scrape_block
            + context_block
            + target_notice
            + mention_block
            + replied_text_context
            + replied_image_context
            + image_analysis_context
            + f"\n[{author_label}]: {text_content}"
        )

        if first_contact:
            user_content = (
                f"[CONTEXTE: C'est la première fois que {_author_label(message.author)} "
                f"t'adresse la parole sur ce serveur. Commence ta réponse par une "
                f"bienvenue chaleureuse en une phrase courte, puis réponds à son message.]\n\n"
                + user_content
            )

        openai_messages = [{"role": "user", "content": user_content}]

        tools = await build_chat_tools(bot, str(message.author.id))

        # Les services que l'exécuteur ci-dessous appelle. Ils étaient auparavant
        # les variables locales de la construction des outils : celle-ci est
        # partie dans `build_chat_tools`, l'exécution reste ici.
        web_search = getattr(bot, "web_search", None)
        scrape = getattr(bot, "scrape", None)
        apex_api = getattr(bot, "apex_api", None)
        action_service = getattr(bot, "action_service", None)
        history_search = getattr(bot, "history_search", None)

        _reaction_emojis: set[str] = set()

        async def _tool_executor_impl(name: str, arguments: str) -> str:
            _clog(
                bot, _conv_channel(message), "tool_called",
                trace_id=str(message.id), tool=name, args=arguments,
            )
            # Actu déjà couverte par le RSS : on refuse tout lookup externe, même
            # si le modèle l'a appelé par réflexe (hallucination de tool non offert).
            if _suppress_lookup and name in _LOOKUP_TOOLS:
                logger.info("RSS: appel '{}' bloqué (actu déjà dans le contexte)", name)
                return (
                    "Inutile de chercher : tu as DÉJÀ les dernières actus dans ton "
                    "contexte, section « Actus que tu CONNAIS DÉJÀ sur ce sujet ». Réponds directement avec "
                    "ces articles et colle leur marqueur de source [¹](<url>)."
                )
            args = json.loads(arguments)
            if name == "quote":
                return await run_quote_tool(bot, args)
            if name == "who_is_online":
                return run_presence_tool(bot, args)
            if name == "follow_date":
                return await run_follow_tool(
                    bot, args, platform="discord", user_id=str(message.author.id),
                    author=str(message.author.display_name))
            if name == "predict":
                return await run_predict_tool(bot, args)
            if name in ("start_counting", "stop_counting", "list_counters"):
                return await run_tally_tool(bot, name, args)
            if name == "music_control":
                return await run_music_tool(bot, args, roles=None,
                                            pilotable=False)
            if name == "show_planning":
                return run_planning_tool(bot, args)
            if name == "show_overlay":
                return run_overlay_tool(
                    bot, args, requester=message.author.display_name
                )
            if name == "cancel_overlay":
                return run_overlay_cancel_tool(bot, args)
            if name == "show_clip":
                return await run_last_clip_tool(bot, args)
            if name == "show_apex":
                return await run_apex_overlay_tool(
                    bot, args, requester=f"discord:{message.author.id}"
                )
            if name == "save_persistent_note":
                return await run_save_note_tool(bot.db, args)
            if name == "delete_persistent_note":
                titre = str(args.get("title") or "").strip()
                if not titre:
                    return json.dumps({"status": "error", "message": (
                        "Il me faut le titre de la note à supprimer."
                    )})
                deleted = await bot.db.delete_persistent_note(titre)
                if deleted:
                    return json.dumps({"status": "ok", "message": f"Note '{titre}' supprimée."})
                return json.dumps({"status": "not_found", "message": f"Note '{titre}' introuvable."})
            if name == "say_in_voice":
                # Les rôles viennent du MESSAGE, jamais du modèle : ce sont eux
                # qui décident si la personne a le droit de faire parler Wally.
                # `maison=True` : un salon Discord n'est pas une chaîne invitée.
                return await run_say_in_voice_tool(
                    bot, args,
                    roles=_roles_discord_effectifs(bot, message.author),
                    maison=True)
            if name == "save_user_memory":
                contenu = str(args.get("content") or "").strip()
                if not contenu:
                    return json.dumps({"status": "error",
                                       "message": "Il me faut ce que je dois retenir."})
                # Le refus est DIT, pas avalé : le store refuserait de toute
                # façon d'écrire, mais en silence — Wally répondrait « c'est
                # noté » sur un souvenir qui n'existe pas.
                refus = _detecter_surnom(contenu, f"discord:{user_id}")
                if refus is not None:
                    logger.info("save_user_memory refusé ({r}) : « {c} »",
                                r=refus, c=contenu[:120])
                    return json.dumps({"status": "denied", "message": REFUS_SURNOM})
                await bot.memory.add("discord", user_id, contenu, username=_author_label(message.author),
                                     origin=_channel_origin(message.channel))
                return json.dumps({"status": "ok", "message": "Souvenir sauvegardé."})

            if name in ("web_search", "image_search"):
                if "🌐" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🌐")
                        _reaction_emojis.add("🌐")
                    # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
                    # qui ne nous regardent pas : message supprimé entre-temps, permissions du
                    # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
                    # réponse déjà écrite pour un emoji absent serait le pire échange possible.
                    except Exception:
                        pass
                if name == "image_search":
                    return await web_search.search_images(args["query"])
                return await web_search.search(args["query"], platform="discord")
            if name == "scrape_url":
                if "🌐" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🌐")
                        _reaction_emojis.add("🌐")
                    # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
                    # qui ne nous regardent pas : message supprimé entre-temps, permissions du
                    # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
                    # réponse déjà écrite pour un emoji absent serait le pire échange possible.
                    except Exception:
                        pass
                return await scrape.scrape(args["url"])
            if name == "search_history":
                # L'outil n'est pas offert sans logs : le modèle l'invente parfois.
                if history_search is None or not history_search.available:
                    return "L'historique des conversations n'est pas consultable."
                if "🔎" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🔎")
                        _reaction_emojis.add("🔎")
                    # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
                    # qui ne nous regardent pas : message supprimé entre-temps, permissions du
                    # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
                    # réponse déjà écrite pour un emoji absent serait le pire échange possible.
                    except Exception:
                        pass
                return await history_search.search(
                    args.get("query", ""),
                    author=args.get("author"),
                    channel=args.get("channel"),
                    after=args.get("after"),
                    before=args.get("before"),
                    limit=args.get("limit", HISTORY_SEARCH_DEFAULT_LIMIT),
                )
            if name == "apex_legends":
                if "🔫" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🔫")
                        _reaction_emojis.add("🔫")
                    # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
                    # qui ne nous regardent pas : message supprimé entre-temps, permissions du
                    # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
                    # réponse déjà écrite pour un emoji absent serait le pire échange possible.
                    except Exception:
                        pass
                return await apex_api.execute(
                    args.get("action", ""),
                    player_name=args.get("player_name", ""),
                    platform=args.get("platform", "PC"),
                    remember=bool(args.get("remember")),
                    legend=args.get("legend", "") or "",
                    uid=args.get("uid", "") or "",
                    period=args.get("period", "live") or "live",
                    notion=args.get("notion", "kills") or "kills",
                    # Discord porte les pièces jointes : la courbe voyagera
                    # avec la réponse, le modèle n'a pas à inventer de lien.
                    peut_joindre_image=True,
                    # L'identité vient d'ICI, jamais du modèle : c'est ce qui
                    # empêche de déclarer le compte Apex de quelqu'un d'autre.
                    requester=f"discord:{message.author.id}",
                    requester_name=message.author.display_name,
                )
            if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
                if "⏱️" not in _reaction_emojis:
                    try:
                        await message.add_reaction("⏱️")
                        _reaction_emojis.add("⏱️")
                    # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
                    # qui ne nous regardent pas : message supprimé entre-temps, permissions du
                    # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
                    # réponse déjà écrite pour un emoji absent serait le pire échange possible.
                    except Exception:
                        pass
                user_roles = _resolve_discord_roles(message.author)
                # Check config admin list too
                admin_ids = getattr(bot.config, "admin_ids", [])
                if str(message.author.id) in [str(a) for a in admin_ids]:
                    user_roles.append("admin")
                guild_id = str(message.guild.id) if message.guild else None
                result = await action_service.execute_tool(
                    name, args,
                    user_id=str(message.author.id),
                    platform="discord",
                    user_roles=user_roles,
                    channel_id=str(message.channel.id),
                    guild_id=guild_id,
                )
                return json.dumps(result)
            if name == "request_self_modification":
                if str(message.author.id) != bot.config.bot.owner_discord_id or getattr(bot, "self_fix", None) is None:
                    return json.dumps({"status": "refused", "message": "Réservé au créateur, et mécanisme indisponible."})
                goal = (args.get("goal") or "").strip()
                if not goal:
                    return json.dumps({"status": "error", "message": "Précise le but de la modification que tu veux."})
                # Demande explicite du créateur → force=True (outrepasse un refus précédent).
                # request_upgrade attend la réaction ✅/❌ (jusqu'à 1h) → tâche de fond.
                _fire(bot.self_fix.request_upgrade(UpgradeRequest(goal=goal), force=True))
                return json.dumps({
                    "status": "ok",
                    "message": "Je t'envoie une demande d'autorisation 🧠 en DM avec le but reformulé — réagis ✅ pour que Claude Code s'en charge, ❌ pour annuler.",
                })
            if name == "join_voice":
                voice = getattr(message.author, "voice", None)
                if voice is None or voice.channel is None:
                    return json.dumps({"status": "denied", "message": "Tu n'es dans aucun salon vocal."})
                await bot.voice_service.join(
                    voice.channel, inviter=getattr(message.author, "display_name", None)
                )
                return json.dumps({"status": "ok", "message": f"Rejoint {voice.channel.name}."})
            if name == "leave_voice":
                if getattr(bot, "voice_service", None) and bot.voice_service.is_connected:
                    await bot.voice_service.leave()
                    return json.dumps({"status": "ok", "message": "Quitté le vocal."})
                return json.dumps({"status": "ok", "message": "Pas en vocal."})
            return json.dumps({"status": "no_such_tool", "message": (
                f"L'outil '{name}' n'existe pas. N'invente pas d'outil : "
                "utilise ceux qu'on te donne, ou réponds simplement — ton texte est déjà envoyé dans la conversation."
            )})

        async def _tool_executor(name: str, arguments: str) -> str:
            result = await _tool_executor_impl(name, arguments)
            _clog(
                bot, _conv_channel(message), "tool_result",
                trace_id=str(message.id), tool=name, result=str(result)[:500],
            )
            return result

        # Question d'actu + recall RSS positif → on retire les outils de lookup de
        # l'offre (web_search / apex_legends / scrape_url). L'exécution est de toute
        # façon bloquée dans _tool_executor_impl (le modèle en hallucine parfois un).
        if _suppress_lookup:
            _before = len(tools)
            tools = [
                t for t in tools
                if t.get("function", {}).get("name") not in _LOOKUP_TOOLS
            ]
            if len(tools) != _before:
                logger.info("RSS: {} outil(s) de lookup retiré(s) de l'offre (actu couverte)",
                            _before - len(tools))

        _llm_t0 = time.monotonic()
        async with message.channel.typing():
            if tools:
                reply, tools_called = await bot.llm.complete_with_tools(
                    system_prompt, openai_messages, tools, _tool_executor,
                    purpose="discord_response",
                    image_urls=image_urls or None,
                    user_id=f"discord:{message.author.id}",
                )
            else:
                reply = await bot.llm.complete(
                    system_prompt, openai_messages, purpose="discord_response",
                    image_urls=image_urls or None,
                    user_id=f"discord:{message.author.id}",
                )
                tools_called = []

        _emo = bot.emotion.get_state()
        _dom = max(_emo, key=_emo.get) if _emo else None
        _clog(
            bot, _conv_channel(message), "llm_call",
            trace_id=str(message.id),
            model=getattr(bot.llm, "_model", "?"),
            dominant_emotion=_dom,
            emotion_value=round(_emo.get(_dom, 0.0), 3) if _dom else None,
            tools_offered=[t.get("function", {}).get("name") for t in tools],
            tools_called=tools_called,
            latency_ms=int((time.monotonic() - _llm_t0) * 1000),
            system_prompt=system_prompt,
            user_content=user_content,
            raw_reply=reply,
        )

        # Le tag est extrait AVANT la passe miroir. Dans l'autre ordre, le
        # brouillon envoyé au LLM secondaire commençait par « [react:😂] … » et
        # toute réécriture le faisait disparaître — l'emoji choisi par le modèle
        # principal était perdu dès que le miroir corrigeait quelque chose, et
        # le markup pouvait même finir publié tel quel si le miroir le recopiait
        # ailleurs qu'en tête (le motif est ancré). `_spontaneous_respond`
        # procédait déjà dans ce sens : les deux chemins divergeaient.
        reply = strip_stage_directions(reply)
        react_emoji, reply = _parse_react_tag(reply)

        # Mirror pass — detect and fix repetitive patterns or missed memories
        _mirror_before = reply
        reply = await _mirror_pass(bot, str(message.channel.id), reply, mem_context)
        if reply != _mirror_before:
            _clog(
                bot, _conv_channel(message), "mirror_pass",
                trace_id=str(message.id),
                before=_mirror_before[:400], after=reply[:400],
            )

        # Après le miroir : c'est le texte qui part réellement qu'on mesure, et
        # le miroir peut lui-même recoller un marqueur en réécrivant.
        reply = thread_sense.retirer_tic(str(message.channel.id), reply)

        try:
            await message.remove_reaction("🔍", bot.user)
        # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
        # qui ne nous regardent pas : message supprimé entre-temps, permissions du
        # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
        # réponse déjà écrite pour un emoji absent serait le pire échange possible.
        except Exception:
            pass
        for emoji in _reaction_emojis:
            try:
                await message.remove_reaction(emoji, bot.user)
            # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
            # qui ne nous regardent pas : message supprimé entre-temps, permissions du
            # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
            # réponse déjà écrite pour un emoji absent serait le pire échange possible.
            except Exception:
                pass

        if react_emoji:
            try:
                await message.add_reaction(react_emoji)
            # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
            # qui ne nous regardent pas : message supprimé entre-temps, permissions du
            # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
            # réponse déjà écrite pour un emoji absent serait le pire échange possible.
            except Exception:
                pass

        self_name = bot.config.bot.name
        # Une progression Apex vient d'être calculée pour cette personne ? Sa
        # courbe part avec la réponse. Rendue seulement maintenant : inutile de
        # payer une seconde de tracé si le modèle n'a finalement rien répondu.
        reply_msg_id, _parts = await _send_in_parts(
            message, reply, file=await _apex_chart_file(bot, f"discord:{message.author.id}")
        )
        _clog(
            bot, _conv_channel(message), "message_out",
            trace_id=str(message.id), author=self_name, content=reply,
            parts=_parts, sent_msg_id=str(reply_msg_id) if reply_msg_id else None,
            react_emoji=react_emoji,
            # À qui il vient de répondre — lu par la trace de ses propres actes
            # (`self_trace`), qui n'en garde que le nom, jamais le contenu.
            target=_author_label(message.author),
        )
        # Signale à la boucle cognitive que le bot a déjà répondu ici → pas de SPEAK
        # proactif redondant dans la foulée.
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(message.channel.id, content=reply)
        _speaks = getattr(bot, "_wally_recent_speaks", None)
        if _speaks is not None:
            _speaks[message.channel.id] = reply
        # Ce qu'il vient de dire, et à qui : de quoi savoir au message suivant
        # qu'il en est au dixième aller-retour, et qu'il finit tout pareil.
        thread_sense.note_reponse(str(message.channel.id), user_id, reply)
        if reply_msg_id and getattr(bot, "reaction_tracker", None):
            bot.reaction_tracker.track_discord_message(reply_msg_id, reply_text=reply, channel_id=str(message.channel.id))

        if first_contact:
            await bot.db.mark_welcomed(user_id, guild_id)
            _clog(
                bot, _conv_channel(message), "welcome",
                trace_id=str(message.id), user=_author_label(message.author),
            )

        bot.memory.append_message(
            str(message.channel.id), _author_label(message.author), enriched_content or message.content, platform="discord"
        )
        bot.memory.append_prelude(str(message.channel.id), self_name, reply)
        bot.memory.append_message(str(message.channel.id), self_name, reply, platform="discord")

        # Persiste le display_name pour que le dashboard coûts affiche un nom lisible
        await bot.db.upsert_memory_user(
            f"discord:{message.author.id}", "discord",
            username=message.author.display_name,
        )

        _fire(_post_process(
            bot, text_content, platform, user_id, guild_id, trust, context_messages,
            image_urls=image_urls or None,
            image_analysis=image_analysis,
            channel_id=str(message.channel.id),
            display_name=message.author.display_name,
            trace_id=str(message.id),
            conv_channel=_conv_channel(message),
            origin=_channel_origin(message.channel),
        ))

    except Exception as e:
        logger.error("Error handling Discord message: {e!r}", e=e)
        try:
            await message.remove_reaction("🔍", bot.user)
        # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
        # qui ne nous regardent pas : message supprimé entre-temps, permissions du
        # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
        # réponse déjà écrite pour un emoji absent serait le pire échange possible.
        except Exception:
            pass


async def _memoriser_image(
    bot: "WallyDiscord",
    *,
    platform: str,
    user_id: str,
    display_name: str,
    image_urls: list[str],
    caption: str = "",
    origin: str = "",
    analysis: str | None = None,
) -> bool:
    """Range en mémoire ce que MONTRE une image, attribué à qui l'a envoyée.

    Le LLM principal est aveugle : sans ce passage par `VisionService`, il ne
    reste de l'image que le marqueur « [a envoyé une image] ». Wally sait alors
    QUI a posté, jamais QUOI — et ne peut ni en reparler, ni féliciter l'auteur
    d'une œuvre dans #artworks.

    Point d'écriture UNIQUE : appelé après une réponse (où l'analyse est déjà
    calculée, donc zéro appel de plus) comme sur le chemin silencieux (où il
    faut la calculer). Les deux sont exclusifs — `_post_process` ne tourne que
    si Wally a répondu.
    """
    if not image_urls:
        return False
    try:
        if not analysis:
            vision = getattr(bot, "vision", None)
            if vision is None or not vision.available:
                return False
            analysis = await vision.analyze(image_urls, caption=caption)
        if not analysis:
            return False
        summary = " ".join(analysis.split())
        if not summary:
            # Une analyse blanche donnait « Rhao a envoyé une image : » — un fait
            # creux qui occupe le budget mémoire sans rien apprendre.
            return False
        if len(summary) > 240:
            summary = summary[:240].rstrip() + "…"
        fact = f"{display_name} a envoyé une image : {summary}"
        await bot.memory.add(platform, user_id, fact, username=display_name,
                             source="image", origin=origin or None)
        logger.info("Image décrite et mémorisée pour {u}", u=display_name)
        return True
    except Exception as e:  # noqa: BLE001 — décrire une image ne casse jamais un message
        logger.warning("Image analysis (memory) failed: {e!r}", e=e)
        return False


async def _post_process(
    bot: "WallyDiscord",
    text: str,
    platform: str,
    user_id: str,
    guild_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
    image_urls: list[str] | None = None,
    image_analysis: str | None = None,
    channel_id: str = "",
    display_name: str = "",
    trace_id: str = "",
    conv_channel: str = "",
    origin: str = "",
) -> None:
    try:
        _beloved = bot.persona.is_beloved(platform, user_id, display_name)
        _emo_before = bot.emotion.get_state()
        llm_deltas = await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            image_urls=image_urls,
            trigger_user=user_id, channel_id=channel_id, platform="discord",
            user_id=user_id,
            beloved=_beloved,
        )
        _emo_after = bot.emotion.get_state()
        if trace_id:
            _emo_deltas = {
                _k: round(_emo_after.get(_k, 0.0) - _emo_before.get(_k, 0.0), 3)
                for _k in ("anger", "joy", "sadness", "curiosity", "boredom")
            }
            if any(_v != 0 for _v in _emo_deltas.values()):
                _clog(
                    bot, conv_channel, "emotion_change",
                    trace_id=trace_id,
                    deltas=_emo_deltas,
                    after={_k: round(_emo_after.get(_k, 0.0), 3) for _k in _emo_deltas},
                )

        if llm_deltas:
            if not (_beloved and llm_deltas["trust_delta"] < 0):
                await bot.db.update_trust_score(platform, user_id, llm_deltas["trust_delta"])
            if llm_deltas["love_delta"] > 0:
                await bot.db.update_love_score(
                    platform, user_id, llm_deltas["love_delta"],
                    bot.config.bot.love_decay_lambda,
                )
        else:
            # Fallback: simple heuristic when LLM unavailable
            insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
            if any(w in text.lower() for w in insult_words):
                if not _beloved:
                    await bot.db.update_trust_score(platform, user_id, -0.05)
            else:
                await bot.db.update_trust_score(platform, user_id, 0.01)

        if llm_deltas and llm_deltas.get("user_facts"):
            for _fact in llm_deltas["user_facts"]:
                await bot.memory.add(platform, user_id, _fact, username=display_name,
                                     source="post_process", origin=origin or None)

        # Stocke une description visuelle VÉRIDIQUE en mémoire long-terme.
        # Le LLM principal/secondaire (DeepSeek) est aveugle → on s'appuie sur
        # VisionService. On réutilise l'analyse déjà calculée dans _respond si
        # disponible (zéro appel supplémentaire), sinon on la calcule ici.
        if image_urls:
            await _memoriser_image(
                bot, platform=platform, user_id=user_id, display_name=display_name,
                image_urls=image_urls, caption=text or "", origin=origin,
                analysis=image_analysis,
            )

        anger = bot.emotion.get_state().get("anger", 0.0)
        if anger >= 0.8 and not _beloved:
            # Always record the anger trigger (duration=0 → tracking only, not a real mute)
            await bot.db.add_timeout(user_id, guild_id, 0, anger)
            count = await bot.db.count_recent_triggers(user_id, guild_id)
            if count >= bot.config.discord.anger_trigger_threshold:
                await bot.db.add_timeout(
                    user_id,
                    guild_id,
                    bot.config.discord.timeout_minutes,
                    anger,
                )
                logger.info(
                    "User {uid} muted for {m} minutes",
                    uid=user_id,
                    m=bot.config.discord.timeout_minutes,
                )
                _clog(
                    bot, conv_channel, "moderation",
                    trace_id=trace_id, action="timeout",
                    minutes=bot.config.discord.timeout_minutes,
                    anger=round(anger, 3),
                )

        if trace_id:
            _clog(
                bot, conv_channel, "post_process",
                trace_id=trace_id,
                facts_extracted=len(llm_deltas.get("user_facts", [])) if llm_deltas else 0,
                image_described=bool(image_urls),
                trust_delta=round(llm_deltas["trust_delta"], 3) if llm_deltas else None,
                anger=round(anger, 3),
            )
    except Exception as e:
        logger.error("Post-process error: {e!r}", e=e)


async def _veiller_questions(
    bot: "WallyDiscord", message: discord.Message,
    prelude_snapshot: list[dict] | None = None,
) -> None:
    """Le pendant Discord de la veille des questions sans réponse.

    Le 13/08, 92 messages reçus sur Discord et UNE réponse — parce que presque
    personne n'y prononce son nom, alors que sur Twitch 16 % des messages le
    font. Même bot, deux présences opposées, et la seule différence était le
    comportement des gens. Un salon Discord pose exactement les mêmes questions
    en l'air qu'un chat de live ; elles doivent réveiller le même Wally.
    """
    cfg = bot.config.bot
    if not getattr(cfg, "unanswered_question_enabled", False):
        return
    try:
        chan_id = str(message.channel.id)
        pending_question.noter(
            chan_id, message.author.display_name,
            _resolve_mentions(message, message.content or ""), charge=message,
        )
        question = pending_question.relever(
            chan_id,
            delai_s=cfg.unanswered_question_delay_seconds,
            oubli_s=cfg.unanswered_question_forget_seconds,
        )
        if question is None:
            return
        maintenant = time.time()
        if maintenant - _spontaneous_cooldowns.get(chan_id, 0) < cfg.spontaneous_cooldown_seconds:
            _clog(bot, _conv_channel(message), "gate_decision",
                  triggered=False, spontaneous=True, decision="silence",
                  reason="question sans réponse — intervention en cooldown")
            return

        source = question.get("charge")
        if source is None:
            return
        prelude = prelude_snapshot if prelude_snapshot is not None else bot.memory.get_prelude(chan_id)
        _uid = await _canonical_uid(bot, "discord", str(source.author.id))
        repondre, motif = await pending_question.le_gate_veut_repondre(
            getattr(bot, "response_gate", None), question,
            auteur_uid=_uid,
            emotion_state=bot.emotion.get_state(),
            fil=prelude,
        )
        _clog(bot, _conv_channel(message), "gate_decision",
              trace_id=str(source.id), triggered=False, spontaneous=True,
              decision="question_relevee" if repondre else "silence",
              reason=motif or "question sans réponse — rien à apporter",
              question=question["texte"][:200], question_age_s=int(question.get("age_s", 0)))
        if not repondre:
            return
        _spontaneous_cooldowns[chan_id] = maintenant
        await _spontaneous_respond(
            bot, source, prelude_snapshot=prelude,
            consigne=(
                f"[CONTEXTE: Tu n'as PAS été mentionné. {question['auteur']} a posé "
                f"cette question dans le salon il y a {int(question.get('age_s', 0))} "
                f"secondes et personne n'y a répondu. Tu interviens parce que tu SAIS. "
                f"Donne l'information, court et direct — si finalement tu n'es sûr de "
                f"rien, dis-le en une ligne plutôt que d'inventer.]"
            ),
        )
    except Exception as exc:  # noqa: BLE001 — une veille qui casse ne casse pas le salon
        logger.warning("Veille des questions sans réponse (Discord) en échec : {e!r}", e=exc)


async def _spontaneous_respond(
    bot: "WallyDiscord", message: discord.Message,
    recall_memory: str | None = None,
    prelude_snapshot: list[dict] | None = None,
    consigne: str | None = None,
) -> None:
    """Generate and send a spontaneous (unsolicited) response.

    L'envoi part dans le canal où a lieu la discussion (en reply au message
    déclencheur) : Wally rejoint la conversation en cours plutôt que de la
    commenter tout seul ailleurs."""
    try:
        prelude = prelude_snapshot if prelude_snapshot is not None else bot.memory.get_prelude(str(message.channel.id))
        # Charger la mémoire de l'auteur si pas déjà fournie (#Q5).
        if recall_memory is None and message.content:
            user_id = str(message.author.id)
            ctx_msgs = [{"content": m.get("content", "")} for m in prelude[-3:]]
            recall_memory = await bot.memory.search(
                "discord", user_id, message.content[:200],
                context_messages=ctx_msgs,
            )
        situation: dict = {"platform": "Discord"}
        if message.guild:
            situation["server"] = message.guild.name
        if isinstance(message.channel, discord.TextChannel):
            situation["channel"] = f"#{message.channel.name}"

        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=recall_memory or "",
            situation=situation,
            presence_context=_presence_line(
                bot, str(message.author.id), message.author.display_name
            ),
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
            user_directive=bot.persona.user_directive("discord", str(message.author.id)),
            # Comme sur Twitch : le chemin spontané échappait à la mesure du fil
            # et pouvait recoller le tic que le chemin principal venait d'ôter.
            thread_context=thread_sense.bloc_fil(
                str(message.channel.id), str(message.author.id),
                nom_personne=message.author.display_name,
                paliers=bot.persona.fil_directives,
            ),
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        recall_block = ""
        if recall_memory:
            recall_block = (
                "\n--- Souvenir qui te revient ---\n"
                f"{recall_memory}\n"
                f"Tu viens de te rappeler quelque chose en lien avec ce que dit "
                f"{_author_label(message.author)}. Évoque-le naturellement.\n\n"
            )
        mention_block = _build_mention_directory(message)
        user_content = (
            (consigne or
             "[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément "
             "parce que le sujet t'intéresse ou te fait réagir. Réponds en une "
             "phrase courte et percutante, comme un commentaire lâché en passant.]")
            + "\n\n"
            + recall_block
            + prelude_block
            + mention_block
            + f"\n[{_author_label(message.author)}]: {_resolve_mentions(message, message.content or '')}"
        )

        target_channel = message.channel
        async with target_channel.typing():
            reply = await bot.llm.complete(
                system_prompt,
                [{"role": "user", "content": user_content}],
                purpose="discord_spontaneous",
            )
        _emo = bot.emotion.get_state()
        _dom = max(_emo, key=_emo.get) if _emo else None
        _clog(
            bot, _conv_channel(message), "llm_call",
            trace_id=str(message.id), kind="spontaneous",
            model=getattr(bot.llm, "_model", "?"),
            dominant_emotion=_dom,
            emotion_value=round(_emo.get(_dom, 0.0), 3) if _dom else None,
            system_prompt=system_prompt, user_content=user_content, raw_reply=reply,
        )

        # Parse and apply react tag if present
        react_emoji, reply = _parse_react_tag(reply)
        if react_emoji:
            try:
                await message.add_reaction(react_emoji)
            # Une réaction est COSMÉTIQUE, et l'API Discord la refuse pour dix raisons
            # qui ne nous regardent pas : message supprimé entre-temps, permissions du
            # salon, emoji d'un serveur qu'on a quitté, rate limit. Faire tomber une
            # réponse déjà écrite pour un emoji absent serait le pire échange possible.
            except Exception:
                pass

        # Correction ton/langue (#Q6)
        _mirror_before = reply
        reply = strip_stage_directions(reply)
        reply = await _mirror_pass(bot, str(message.channel.id), reply, recall_memory or "")
        if reply != _mirror_before:
            _clog(
                bot, _conv_channel(message), "mirror_pass",
                trace_id=str(message.id),
                before=_mirror_before[:400], after=reply[:400],
            )

        # Intervention spontanée → dans le canal de la discussion, en reply au
        # message qui l'a déclenchée.
        #
        # Ce chemin ne passait ni par `redact` ni par le découpage : le mot d'un
        # pendu en cours pouvait en sortir, et toute réponse de plus de 2 000
        # caractères était refusée par Discord — donc perdue en silence, après
        # avoir été payée et mémorisée.
        from bot.discord.message_split import split_for_discord

        reply = thread_sense.retirer_tic(str(message.channel.id), reply)
        reply = redact(reply)
        parts = split_for_discord(reply)
        await message.reply(
            parts[0], mention_author=False, allowed_mentions=_ALLOWED_MENTIONS
        )
        for part in parts[1:]:
            await message.channel.send(part, allowed_mentions=_ALLOWED_MENTIONS)
        # Une question posée en spontané doit attendre sa réponse, comme sur le
        # chemin normal : `_note_open_question` n'était armé que par
        # `_send_in_parts`. Or une intervention spontanée est par définition non
        # mentionnée — la réponse de l'utilisateur ne contient ni le nom de Wally
        # ni de mention, donc rien ne se déclenchait et le dialogue s'arrêtait
        # tout seul. C'est précisément le cas que ce mécanisme vise.
        _note_open_question(message.channel.id, message.author.id, reply)
        sent_channel_id = str(target_channel.id)
        self_name = bot.config.bot.name
        _clog(
            bot, _conv_channel(message), "message_out",
            trace_id=str(message.id), kind="spontaneous", author=self_name,
            content=reply, parts=len(parts), react_emoji=react_emoji,
        )
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(target_channel.id, content=reply)

        bot.memory.append_prelude(sent_channel_id, self_name, reply)
        bot.memory.append_message(
            sent_channel_id, self_name, reply, platform="discord"
        )
        thread_sense.note_reponse(sent_channel_id, str(message.author.id), reply)
        logger.info("Spontaneous intervention → #{ch}", ch=getattr(target_channel, 'name', 'dm'))
        if recall_memory:
            logger.info("Memory recall for {user}: {mem}", user=message.author.display_name, mem=recall_memory[:80])

    except Exception as e:
        logger.error("Spontaneous intervention error: {e!r}", e=e)


