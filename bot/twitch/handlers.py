# bot/twitch/handlers.py
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import TYPE_CHECKING

from loguru import logger

from bot.intelligence.prompts import assemble_memory_context, build_session_recall_block
# Le duel Apex ne vit que sur la chaîne maison : son outil n'est offert que
# par ce chemin, et son exécution reste ici plutôt que dans `discord/handlers`.
from bot.intelligence.overlay_narrator import DUEL_TOOL_SPEC as _DUEL_TOOL
from bot.core.apex.tool import APEX_OVERLAY_TOOL as _APEX_OVERLAY_TOOL
from bot.core.conversation_log import new_trace_id
from bot.core.emote_wave import EmoteWaveDetector
from bot.core.secret_guard import redact
from bot.core.text_clean import strip_stage_directions
from bot.discord.handlers import (
    _check_spontaneous_trigger, _NOTE_TOOLS, _third_party_mention_context,
    _canonical_uid, _apex_account_context,
    _OVERLAY_TOOL, _overlay_narrator, run_overlay_tool,
    _OVERLAY_CANCEL_TOOL, run_overlay_cancel_tool,
    _LAST_CLIP_TOOL, run_apex_overlay_tool, run_last_clip_tool,
    PLANNING_TOOL_SPEC, run_planning_tool,
    _consume_open_question, _note_open_question,
    _TALLY_TOOLS, run_tally_tool, _PREDICT_TOOL, run_predict_tool,
    _QUOTE_TOOL, run_quote_tool,
)

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

from bot.twitch.commands import dispatch_command


# Une relance en attente par (canal, personne) → instant de la réponse de Wally.
#
# Le cooldown existe pour qu'un inconnu ne mitraille pas une chaîne publique. Il
# ne devrait pas manger la SUITE d'un échange : vu en live, « @WallyTeBully
# encore une partie » six secondes après une réponse tombait dans le vide, sans
# même une ligne de log. La mention était pourtant là.
#
# Une seule relance par réponse, consommée à l'usage : un spammeur double sa
# cadence au pire, il ne supprime pas le cooldown. Chaque réponse de Wally en
# rouvre une, donc une vraie conversation reste fluide aussi longtemps qu'elle
# dure.
_relances: dict[tuple[str, str], float] = {}
_RELANCE_WINDOW_S = 60.0


def _note_reply_sent(channel: str, user_id: str) -> None:
    """Wally vient de répondre : la prochaine relance de cette personne passe."""
    now = time.monotonic()
    # Purge paresseuse — le process tourne des semaines.
    for key, at in list(_relances.items()):
        if now - at > _RELANCE_WINDOW_S:
            del _relances[key]
    _relances[(str(channel), str(user_id))] = now


def _consume_relance(channel: str, user_id: str) -> bool:
    """Vrai si ce message prolonge un échange — et referme la fenêtre."""
    at = _relances.pop((str(channel), str(user_id)), None)
    return at is not None and (time.monotonic() - at) <= _RELANCE_WINDOW_S


# Bots Twitch présents sur à peu près toutes les chaînes. Socle non
# configurable : il ne dépend d'aucun réglage et vaut partout. Au niveau MODULE
# — il était reconstruit à chaque ligne de chat.
_KNOWN_BOTS: frozenset[str] = frozenset({
    "nightbot", "streamlabs", "streamelements", "moobot", "fossabot",
    "wizebot", "supibot", "botrixoficial", "sery_bot", "electricallongboard",
    "streamlabsbot", "commanderroot", "soundalerts", "elbierro", "tangiabot",
    "kofistreambot", "own3d", "streamelementsbot",
})


def is_ignored_chatter(author: str, ignored: list[str] | None) -> bool:
    """Vrai si ce compte ne doit pas être écouté.

    `ignored` vient de `config.twitch.ignored_users` : les bots croisés sur une
    chaîne invitée changent d'une chaîne à l'autre, les câbler demanderait un
    rebuild par pseudo.

    Comparaison en minuscules et sans espaces : Twitch affiche « WZBot » quand
    le login est « wzbot », et une liste saisie à la main traîne des espaces.
    """
    nom = (author or "").strip().lower()
    if not nom:
        return False
    if nom in _KNOWN_BOTS:
        return True
    return any(nom == (i or "").strip().lower() for i in (ignored or []))


def _badge_ids(badges: list) -> set[str]:
    """Les identifiants des badges d'un message, quel qu'en soit le porteur.

    twitchio rend des objets (`.id`), l'EventSub brut des dicts (`set_id`) : le
    même test traînait recopié à deux endroits, sans couvrir la seconde forme.
    """
    ids = set()
    for b in badges or []:
        if isinstance(b, dict):
            ids.add(str(b.get("set_id") or b.get("id") or ""))
        else:
            # `.id` D'ABORD : c'est la forme que twitchio rend et que ce fichier
            # lisait déjà. L'inverse ferait basculer la lecture sur un attribut
            # jamais vérifié en production.
            ids.add(str(getattr(b, "id", None) or getattr(b, "set_id", None) or b))
    return ids


def auteur_du_message(badges: list) -> dict:
    """L'identité de contrôle d'un message, telle que le CODE la lira.

    Normalisée ici, au bord : `peut_controler()` (duel) n'a pas à connaître les
    trois formes qu'un badge peut prendre. Et surtout, cette identité vient du
    message RÉEL — jamais d'un argument que le modèle remplirait lui-même.
    """
    return {"badges": [{"set_id": b} for b in _badge_ids(badges) if b]}


def _resolve_twitch_roles(badges: list) -> list[str]:
    """Map Twitch badges to the action permission hierarchy."""
    roles = ["everyone"]
    badge_names = _badge_ids(badges)
    if "subscriber" in badge_names:
        roles.append("subscriber")
    if "vip" in badge_names:
        roles.append("vip")
    if "moderator" in badge_names:
        roles.append("moderator")
    if "broadcaster" in badge_names:
        roles.append("admin")
    return roles

# Strong references to fire-and-forget tasks to prevent GC cancellation.
_bg_tasks: set[asyncio.Task] = set()
# Tâches détachées de l'overlay (salut + comptage de votes).
_overlay_chat_tasks: set[asyncio.Task] = set()
_spontaneous_cooldowns: dict[str, float] = {}
# Détecteur de vagues d'emotes, partagé par tous les messages du chat.
_emote_waves = EmoteWaveDetector()


def _fire(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


async def _scan_tally(bot, tally, text: str) -> None:
    """Incrémente les compteurs touchés par une ligne de chat, et le montre."""
    try:
        touched = await tally.scan(text)
    except Exception as exc:  # noqa: BLE001 — un compteur ne casse pas le chat
        logger.warning("Tally (chat) en erreur : {e}", e=exc)
        return
    narrator = _overlay_narrator(bot)
    if narrator is None:
        return
    for row in touched:
        narrator.show_counter(f"{row['label']} : {row['count']}")
        if narrator.is_counter_milestone(row["count"]):
            await narrator.on_counter_milestone(row["label"], row["count"])


async def _envoyer_reponse_twitch(
    bot: "WallyTwitch",
    channel_name: str,
    texte: str,
    *,
    author: str,
    parent_msg_id: str | None,
) -> str:
    """Envoie la réponse et retourne le mode réellement employé.

    `helix` (chaîne home) · `irc_reply` (chaîne invitée, réponse chaînée) ·
    `irc_mention` (repli : « @pseudo texte ») · `perdu` (IRC déconnecté).

    Le chemin invité préfixait le pseudo pour SIMULER une réponse. Twitch sait
    pourtant chaîner en IRC, via le tag `@reply-parent-msg-id` sur le PRIVMSG — c'est
    twitchio 2 qui ne l'expose pas, la demande étant ouverte depuis 2020
    (PythonistaGuild/TwitchIO#119). On écrit donc le PRIVMSG taggé nous-mêmes.

    Les garde-fous de `Channel.send` sont refaits à l'identique : `check_content`
    valide le texte, `check_bucket` sollicite le rate-limiter IRC. Les sauter
    exposerait à un ban de la connexion, ce que le gain d'un fil de réponse ne vaut
    pas. Tout imprévu retombe sur la mention plutôt que d'avaler la réponse.
    """
    # Dernier filet, ICI plutôt que dans `TwitchAPI.send_message` : celui-ci ne
    # couvre que la chaîne HOME via Helix. Les trois sorties IRC — PRIVMSG
    # taggé, repli mention, chaîne invitée — envoyaient le texte brut. Or le mot
    # du pendu circule dans TOUS les prompts tant que la partie tourne, y
    # compris chez un invité : Wally pouvait le publier hors de portée de la
    # ceinture, et gâcher la partie pour tout le monde.
    texte = redact(texte)
    if channel_name not in getattr(bot, "_channel_ids", {}):
        # Le mode « perdu » existait mais n'était atteignable que sur IRC : ce
        # chemin-ci rendait « helix » même quand l'API avait refusé le message.
        # L'appelant posait alors un cooldown et versait au prélude comme à la
        # mémoire une réplique jamais publiée.
        publie = await bot.twitch_api.send_message(
            text=texte, reply_parent_message_id=parent_msg_id
        )
        if not publie:
            logger.warning("Twitch: publication Helix refusée sur {ch}", ch=channel_name)
            return "perdu"
        return "helix"

    canal = bot.get_channel(channel_name)
    if canal is None:
        logger.warning("IRC non connecté pour {ch}, réponse ignorée", ch=channel_name)
        return "perdu"

    if parent_msg_id:
        try:
            ws = canal._fetch_websocket()
            if ws is not None:
                canal.check_content(texte)
                canal.check_bucket(channel=channel_name)
                await ws.send(
                    f"@reply-parent-msg-id={parent_msg_id} "
                    f"PRIVMSG #{channel_name} :{texte}\r\n"
                )
                return "irc_reply"
        except Exception as exc:  # noqa: BLE001 — la réponse doit partir malgré tout
            logger.warning(
                "Twitch: réponse chaînée impossible sur {ch} ({e}) — repli sur la mention",
                ch=channel_name, e=exc,
            )

    await canal.send(f"@{author} {texte}")
    return "irc_mention"


def _build_situation(bot: "WallyTwitch", channel_name: str) -> dict:
    """Build situation dict with stream info if available."""
    situation: dict = {
        "platform": "Twitch",
        "streamer": channel_name,
        "channel": f"#{channel_name}",
    }
    # Il s'appelle « Wally », mais le chat l'interpelle par son login Twitch.
    # Sans cette ligne, il voyait passer des « @WallyTeBully » sans faire le
    # lien avec lui-même. Absente si non configuré : mieux vaut rien qu'une
    # ligne vide, qui inviterait le modèle à inventer un pseudo.
    if nick := os.getenv("TWITCH_BOT_NICK", "").strip():
        situation["self_handle"] = nick
    # `_stream_info` ne décrit QUE la chaîne maison : c'est le `StreamWatcher` du
    # broadcaster home qui l'alimente. Renseigné sans distinction, il faisait dire
    # à Wally, dans le chat d'une chaîne INVITÉE, le jeu, le titre et le nombre de
    # viewers du live d'Azraël — des faits sur un autre stream, affirmés au chat
    # de quelqu'un d'autre.
    #
    # Deuxième effet, plus discret : `prompts.py` se sert de `stream_live` comme
    # approximation de « on est sur la chaîne maison » (les commentaires le
    # disent). Chez un invité pendant un live maison, la conscience du stream
    # était donc supprimée à tort et le chat retiré du flux passif à tort.
    if channel_name not in getattr(bot, "_channel_ids", {}):
        stream = bot._stream_info
        if stream.get("live"):
            situation["stream_live"] = True
            situation["stream_category"] = stream.get("category")
            situation["stream_title"] = stream.get("title")
            situation["stream_viewers"] = stream.get("viewers", 0)
    return situation


def est_chaine_home(bot: "WallyTwitch", channel_name: str) -> bool:
    """La chaîne maison, par opposition à une chaîne invitée.

    Les invitées sont enregistrées dans `_channel_ids` à la souscription ; la
    home ne l'est pas. Le test traînait tel quel en plusieurs endroits — le
    nommer évite qu'un nouvel appelant l'oublie, ce qui est arrivé pour
    `!image` et les outils d'overlay.
    """
    return channel_name not in getattr(bot, "_channel_ids", {})


def _clog(bot: "WallyTwitch", channel: str, event_type: str, **fields) -> None:
    """Journalise un événement de conversation Twitch (no-op si logger absent)."""
    clog = getattr(bot, "conv_log", None)
    if clog is not None:
        clog.log("twitch", channel, event_type, **fields)


async def build_chat_tools(bot: "WallyTwitch", *, overlay: bool = True) -> list[dict]:
    """Les outils offerts au LLM sur le chemin Twitch.

    Extrait de `handle_message` pour que le chemin VOCAL offre exactement les
    mêmes. Deux listes séparées divergeraient au premier ajout — c'est
    précisément ce qui était arrivé à l'énumération du chifoumi.
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
    tools.extend(_NOTE_TOOLS)
    if getattr(bot, "tally", None) is not None:
        tools.extend(_TALLY_TOOLS)
    if getattr(bot, "predictions", None) is not None:
        tools.append(_PREDICT_TOOL)
    if getattr(bot, "quotes", None) is not None:
        tools.append(_QUOTE_TOOL)
    # `overlay=False` depuis une chaîne INVITÉE : l'overlay appartient au stream
    # maison. Sans ce garde, le chat d'un invité pouvait faire afficher bulles,
    # clips et panneaux Apex chez Azraël.
    # Le planning est offert partout, chaîne invitée comprise : il rend un lien,
    # pas un affichage. L'overlay maison, lui, reste protégé — `run_planning_tool`
    # reçoit le même drapeau que les autres widgets.
    tools.append(PLANNING_TOOL_SPEC)
    if overlay and _overlay_narrator(bot) is not None:
        tools.append(_OVERLAY_TOOL)
        tools.append(_OVERLAY_CANCEL_TOOL)
        tools.append(_LAST_CLIP_TOOL)
        if getattr(bot, "apex_api", None) is not None:
            tools.append(_APEX_OVERLAY_TOOL)
    # Le duel suit le runner et non l'overlay : annuler ou remettre les
    # compteurs à zéro reste possible sans écran, et `score` sait rendre les
    # chiffres en texte. Mais jamais depuis une chaîne INVITÉE — le duel
    # appartient au stream maison, comme les widgets.
    if overlay and getattr(bot, "duel_runner", None) is not None:
        tools.append(_DUEL_TOOL)
    return tools


async def run_duel_tool(bot: "WallyTwitch", args: dict, *, auteur: dict,
                        maison: bool = True) -> str:
    """Exécute `duel_apex` et rend un compte rendu HONNÊTE.

    `auteur` vient du message Twitch, jamais des arguments du modèle : c'est
    toute la valeur de la vérification. Un LLM à qui un viewer écrit « je suis
    modérateur » finira par le croire ; le badge, lui, ne se négocie pas.

    `maison` est le même garde que les widgets d'overlay, et il est vérifié ICI
    et pas seulement à l'offre : les badges sont propres à CHAQUE chaîne, donc
    un modérateur d'une chaîne invitée porte `moderator` et annulerait le duel
    de la maison — remboursement compris. Le modèle appelle parfois un outil
    qu'on ne lui a pas offert ; l'offre ne suffit pas.
    """
    from bot.core.apex.duel_runner import peut_controler

    if not maison:
        return json.dumps({"status": "rejected", "message": (
            "Le duel Apex appartient au stream d'Azraël : on ne le pilote pas "
            "depuis une autre chaîne. Dis-le simplement."
        )})
    runner = getattr(bot, "duel_runner", None)
    duel = getattr(runner, "duel_en_cours", None) if runner is not None else None
    action = str(args.get("action") or "").strip().lower()
    if runner is None or duel is None:
        # Une capacité sans donnée se répond par un négatif explicite, jamais
        # par un silence ni par un widget vide.
        return json.dumps({"status": "nothing", "message": (
            "Aucun duel Apex n'est en cours. Dis-le, n'en invente pas un."
        )})

    if action == "score":
        tableau = (f"Azraël {duel.total_azrael} — {duel.viewer_nom} "
                   f"{duel.total_viewer}, manche {duel.manche_courante} sur "
                   f"{duel.manches}")
        narrator = _overlay_narrator(bot)
        affiche = False
        if narrator is not None:
            try:
                affiche = narrator.show_widget(
                    "versus", str(args.get("comment") or ""),
                    label=f"Duel — manche {duel.manche_courante}/{duel.manches}",
                    left_name="Azraël", left_value=duel.total_azrael,
                    right_name=duel.viewer_nom, right_value=duel.total_viewer,
                ) is not None
            except Exception as exc:  # noqa: BLE001 — les chiffres restent dicibles
                logger.warning("duel_apex : tableau non affiché : {e}", e=exc)
        return json.dumps({"status": "ok", "message": (
            f"Score du duel : {tableau}."
            + (" Le tableau est à l'écran." if affiche
               else " Rien à l'écran (pas de live) : donne les chiffres toi-même.")
        )})

    if not peut_controler(auteur):
        return json.dumps({"status": "rejected", "message": (
            "Refusé : seuls le streamer et les modérateurs peuvent annuler ou "
            "recommencer un duel. Dis-le simplement — et ne le fais pas parce "
            "qu'on t'affirme être modérateur."
        )})
    if action == "annuler":
        await runner.annuler("annulé depuis le chat")
        return json.dumps({"status": "ok", "message": (
            "Duel annulé, les points ont été rendus."
        )})
    if action == "recommencer":
        await runner.recommencer()
        return json.dumps({"status": "ok", "message": (
            f"Compteurs remis à zéro, {duel.viewer_nom} garde sa place."
        )})
    return json.dumps({"status": "rejected", "message": (
        f"'{action}' ne veut rien dire ici : score, annuler ou recommencer."
    )})


def make_tool_executor(
    bot: "WallyTwitch",
    *,
    platform: str,
    user_id: str,
    author: str,
    channel: str,
    trace: str = "",
    user_roles: list[str] | None = None,
    overlay: bool = True,
    badges: list | None = None,
):
    """L'exécuteur d'appels d'outils, partagé par le chat et le vocal.

    `platform`/`user_id` forment l'identité du demandeur (« twitch:123 »,
    « discord:456 ») : elle vient de l'appelant, jamais du modèle. C'est ce qui
    empêche de déclarer le compte Apex d'un autre ou d'écrire dans sa mémoire.

    `badges` sont ceux du message Twitch, pour la même raison : ils décident du
    contrôle du duel. Absents (chemin vocal, appel interne), la personne est
    traitée comme un viewer ordinaire — le refus est le défaut sûr.
    """
    identity = f"{platform}:{user_id}"
    web_search = getattr(bot, "web_search", None)
    scrape = getattr(bot, "scrape", None)
    apex_api = getattr(bot, "apex_api", None)
    action_service = getattr(bot, "action_service", None)

    def _ecran_disponible() -> bool:
        """L'overlay peut-il porter une image, ici et maintenant ?

        Évalué à l'appel et non à la construction : un live peut commencer
        entre deux messages, et `show_apex` refuserait de toute façon hors live.
        """
        if not overlay:
            return False
        narrator = _overlay_narrator(bot)
        return narrator is not None and narrator.is_active()

    async def _impl(name: str, arguments: str) -> str:
        _clog(bot, channel, "tool_called", trace_id=trace, tool=name, args=arguments)
        args = json.loads(arguments)
        if name == "quote":
            return await run_quote_tool(bot, args)
        if name == "predict":
            return await run_predict_tool(bot, args)
        if name in ("start_counting", "stop_counting", "list_counters"):
            return await run_tally_tool(bot, name, args)
        if name == "show_planning":
            return run_planning_tool(bot, args, overlay=overlay)
        if name == "show_overlay":
            return run_overlay_tool(bot, args, requester=author)
        if name == "cancel_overlay":
            return run_overlay_cancel_tool(bot, args)
        if name == "show_clip":
            return await run_last_clip_tool(bot, args)
        if name == "show_apex":
            return await run_apex_overlay_tool(bot, args, requester=identity)
        if name == "duel_apex":
            return await run_duel_tool(
                bot, args, auteur=auteur_du_message(badges or []), maison=overlay)
        if name == "save_persistent_note":
            await bot.db.upsert_persistent_note(args["title"], args["content"])
            return json.dumps({"status": "ok", "message": f"Note '{args['title']}' sauvegardée."})
        if name == "delete_persistent_note":
            deleted = await bot.db.delete_persistent_note(args["title"])
            if deleted:
                return json.dumps({"status": "ok", "message": f"Note '{args['title']}' supprimée."})
            return json.dumps({"status": "not_found", "message": f"Note '{args['title']}' introuvable."})
        if name == "save_user_memory":
            await bot.memory.add(platform, user_id, args["content"], username=author,
                                 origin=f"Twitch/{channel}")
            return json.dumps({"status": "ok", "message": "Souvenir sauvegardé."})
        # Un outil peut être connu du modèle mais indisponible sur cette
        # instance (clé absente). La branche `no_such_tool` ne couvrait que
        # les noms INCONNUS : on tombait sur `None.search(...)`, et les
        # `args["query"]`/`args["url"]` levaient un KeyError si le modèle les
        # omettait. Les deux remontaient en « erreur technique » opaque.
        if name in ("web_search", "image_search"):
            if web_search is None:
                return json.dumps({"status": "unavailable",
                                   "message": "La recherche web n'est pas disponible."})
            query = str(args.get("query") or "").strip()
            if not query:
                return json.dumps({"status": "rejected", "message": "Il faut une requête."})
            if name == "image_search":
                return await web_search.search_images(query)
            return await web_search.search(query, platform="twitch")
        if name == "scrape_url":
            url = str(args.get("url") or "").strip()
            if scrape is None:
                return json.dumps({"status": "unavailable",
                                   "message": "La lecture de pages n'est pas disponible."})
            if not url:
                return json.dumps({"status": "rejected", "message": "Il faut une URL."})
            return await scrape.scrape(url)
        if name == "apex_legends":
            if apex_api is None:
                return json.dumps({"status": "unavailable",
                                   "message": "Les stats Apex ne sont pas disponibles."})
            return await apex_api.execute(
                args.get("action", ""),
                player_name=args.get("player_name", ""),
                platform=args.get("platform", "PC"),
                remember=bool(args.get("remember")),
                legend=args.get("legend", "") or "",
                uid=args.get("uid", "") or "",
                period=args.get("period", "live") or "live",
                notion=args.get("notion", "kills") or "kills",
                requester=identity,
                requester_name=author,
                # Le chat Twitch ne porte pas d'image, mais l'écran du stream
                # si — à condition d'être branché ET en live, et que la demande
                # ne vienne pas d'une chaîne invitée (`overlay`). Sans ça, le
                # modèle s'excuse de ne pas pouvoir montrer de courbe alors
                # qu'elle a sa place à l'écran, sous les yeux des spectateurs.
                ecran_disponible=_ecran_disponible(),
            )
        if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
            if action_service is None:
                return json.dumps({"status": "unavailable",
                                   "message": "Les tâches planifiées ne sont pas disponibles."})
            result = await action_service.execute_tool(
                name, args,
                user_id=user_id,
                platform=platform,
                user_roles=user_roles or ["everyone"],
                channel_id=channel,
            )
            return json.dumps(result)
        return json.dumps({"status": "no_such_tool", "message": (
            f"L'outil '{name}' n'existe pas. N'invente pas d'outil : "
            "utilise ceux qu'on te donne, ou réponds simplement — ton texte est déjà envoyé dans la conversation."
        )})

    async def _executor(name: str, arguments: str) -> str:
        result = await _impl(name, arguments)
        _clog(bot, channel, "tool_result", trace_id=trace, tool=name, result=str(result)[:500])
        return result

    return _executor


async def handle_message(bot: "WallyTwitch", payload) -> None:
    """Handle an incoming channel.chat.message EventSub payload."""
    # Dashboard message counter (tous les messages, pas seulement les triggers)
    if getattr(bot, "dashboard_state", None) is not None:
        bot.dashboard_state.message_count += 1
        bot.dashboard_state.message_count_twitch += 1

    content: str = payload.message.text
    content_lower = content.lower()
    author: str = payload.chatter.name
    user_id: str = str(payload.chatter.id)
    # Normalisé en minuscules — cohérent avec les clés de _channel_ids
    channel_name: str = payload.broadcaster.name.lower()
    channel_id = f"twitch:{channel_name}"

    # Filtres d'identité AVANT tout traitement. Ils étaient en aval de
    # `dispatch_command` et du compteur de visite : une réponse de Wally
    # commençant par `!code` atteignait son propre gestionnaire de commande, et
    # `msg_count` — qui alimente le résumé de visite — comptait les messages de
    # Wally et des bots comme de l'activité du salon.

    # Ignorer les propres messages de Wally qui reviennent via EventSub
    bot_id = str(getattr(bot.twitch_api, "_bot_id", ""))
    if bot_id and user_id == bot_id:
        return

    # Ignorer les bots — socle connu, liste de config, ou badge "bot"
    if is_ignored_chatter(author, getattr(bot.config.twitch, "ignored_users", None)):
        return
    badges = getattr(payload, "badges", []) or []
    badge_ids = _badge_ids(badges)
    if "bot" in badge_ids:
        return

    # Réponse d'un duelliste en attente de son uid Apex (Task 8bis) : AVANT
    # tout cooldown et tout appel LLM, sinon le message serait traité comme
    # un message ordinaire au lieu de résoudre le duel en attente.
    runner = getattr(bot, "duel_runner", None)
    if runner is not None and await runner.repondre_resolution(author, content):
        return

    # Utilisateur banni : le ban est keyé sur le discord_id. On l'applique sur
    # Twitch UNIQUEMENT si ce compte Twitch est lié à un discord banni (alias
    # accepté). Sans liaison, on ne peut pas savoir → non filtré.
    #
    # AVANT `dispatch_command`, avec les autres filtres d'identité. En aval, un
    # banni gardait `!image` — donc l'affichage d'une image sur l'overlay du live,
    # annoncée dans le chat par le LLM — et `!mood`. Le bannissement ne couvrait
    # en pratique que les réponses conversationnelles.
    canonical = bot.memory._user_id("twitch", user_id)
    if canonical.startswith("discord:") and await bot.db.is_chat_user_banned(canonical.split(":", 1)[1]):
        logger.debug("Ignoring banned user (twitch→{})", canonical)
        return

    # Incrémentation du compteur de messages pour les visites actives
    active_visits = getattr(bot, "_active_visits", {})
    if channel_name in active_visits:
        active_visits[channel_name]["msg_count"] += 1

    # Dispatch commandes ! (overlay, !mood, !code, …)
    if await dispatch_command(bot, payload, content, author, channel_name):
        return

    # Marquer la chaîne invitée comme "vue live" dès réception d'un message
    if channel_name in bot._channel_ids:
        bot._channel_was_live[channel_name] = True

    # Ancienneté du spectateur AVANT l'upsert ci-dessous, qui rafraîchit la date :
    # sans cette précaution, tout le monde paraîtrait « vu à l'instant » et
    # l'overlay ne saluerait plus jamais personne.
    _seen_days = None
    _narrator = getattr(getattr(bot, "discord_bot", None), "overlay_narrator", None)
    # C'est le narrateur qui tranche, pas `_stream_info` : lui seul connaît le
    # mode test hors live.
    _overlay_on = _narrator is not None and _narrator.is_active()
    if _overlay_on:
        try:
            _seen_days = await bot.db.days_since_viewer_seen(author)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("overlay: ancienneté spectateur indisponible: {e}", e=exc)

    # Persiste le login Twitch pour que le dashboard affiche un nom lisible
    await bot.db.upsert_memory_user(f"twitch:{user_id}", "twitch", username=author)

    # Flux passif du stream : pendant le live, les lignes du chat de la chaîne
    # home nourrissent le contexte d'ambiance de Wally — y compris quand il
    # raisonne ailleurs (Discord, cognition), où ce chat lui est invisible.
    # Chaîne invitée ou hors live : ce n'est pas « le stream », on n'enregistre pas.
    _stream_feed = getattr(bot, "stream_feed", None)
    if (
        _stream_feed is not None
        and channel_name not in bot._channel_ids
        and (getattr(bot, "_stream_info", None) or {}).get("live")
    ):
        try:
            _stream_feed.record_chat(author, content)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("StreamFeed: chat non enregistré : {e}", e=exc)

    # Overlay : compte les votes d'un sondage en cours et salue les nouveaux
    # venus / les revenants. Détaché — le salut demande un appel LLM. Chemin
    # distinct du flux passif ci-dessus : en mode test hors live, `_stream_info`
    # dit « pas de live » alors que l'overlay, lui, doit réagir.
    if _overlay_on and channel_name not in bot._channel_ids:
        _t = asyncio.create_task(
            _narrator.on_chat_message(author, content, days_since=_seen_days)
        )
        _overlay_chat_tasks.add(_t)
        _t.add_done_callback(_overlay_chat_tasks.discard)

    # Vagues d'emotes : quand plusieurs personnes spamment la même chose, c'est
    # le chat qui réagit ensemble — ça mérite l'écran. Détection mécanique.
    # Chaîne HOME seulement, comme les deux blocs ci-dessus : `_emote_waves` est
    # un détecteur unique sans notion de canal, donc quatre viewers répartis sur
    # trois chaînes invitées déclenchaient une vague sur l'overlay du live.
    if _overlay_on and channel_name not in bot._channel_ids:
        try:
            if emote := _emote_waves.feed(author, content):
                _narrator.show_emote_wave(emote)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("Vague d'emote non traitée : {e}", e=exc)

    # Compteurs à la demande : le chat compte autant que le vocal — une punchline
    # récurrente s'y répète tout autant. Détaché : le scan touche la base.
    # Home aussi : une punchline dite chez un invité incrémentait le compteur du
    # live d'Azraël et pouvait déclencher une bulle à l'antenne.
    _tally = getattr(bot, "tally", None)
    if _tally is not None and channel_name not in bot._channel_ids:
        _t = asyncio.create_task(_scan_tally(bot, _tally, content))
        _overlay_chat_tasks.add(_t)
        _t.add_done_callback(_overlay_chat_tasks.discard)

    # Capture passive : prelude AVANT d'ajouter le message courant
    prelude = bot.memory.get_prelude(channel_id)
    bot.memory.append_prelude(channel_id, author, content)
    if getattr(bot, "cognitive_loop", None) is not None:
        try:
            # « Pertinent » = le message vise Wally (mention @nick ou nom déclencheur)
            # → cadence cognitive vive ; sinon perception passive (Phase 2c).
            _tb_nick = os.getenv("TWITCH_BOT_NICK", "").lower()
            _relevant = bool(_tb_nick and f"@{_tb_nick}" in content_lower) or any(
                n.lower() in content_lower for n in bot.config.bot.trigger_names
            )
            bot.cognitive_loop.notify_activity(
                channel_id=channel_id,
                author=author,
                content=content,
                relevant=_relevant,
                user_key=f"twitch:{user_id}",
            )
        except Exception as exc:  # noqa: BLE001 — la perception ne casse pas le chat
            # C'est le SEUL point où le chat Twitch réveille la cadence
            # cognitive : un silence ici rendait Wally sourd à Twitch sans
            # qu'aucun log ne l'indique. « Une absence sans log = un `continue`
            # silencieux », déjà vu sur le congé vocal.
            logger.warning("Cognition : notify_activity (twitch) en échec : {e}", e=exc)
    if getattr(bot, "fact_extractor", None) is not None:
        bot.fact_extractor.record_message(channel_id, "twitch", user_id, author, content, is_reply=False,
                                          origin=f"Twitch/{channel_name}")

    # Reaction tracking: scan for positive reactions in Twitch window
    tracker = getattr(bot, "reaction_tracker", None)
    if tracker:
        tracker.check_twitch_message(channel_id, content)

    _trace = getattr(payload, "message_id", None) or new_trace_id("twitch")
    _clog(
        bot, channel_name, "message_in",
        trace_id=_trace, author=author, author_id=user_id, content=content,
    )

    # Trigger check — calculé AVANT le spontané : les deux chemins ne doivent
    # pas se cumuler. Le bloc spontané tournait sans aucune garde, alors que le
    # pendant Discord est enfermé dans un `if not triggered:` ; et
    # `_check_spontaneous_trigger` répond « emotion » sur le seul état interne,
    # quel que soit le contenu. Un message mentionnant Wally pendant que l'ennui
    # est haut déclenchait donc DEUX messages pour une seule sollicitation, le
    # spontané échappant en prime au cooldown utilisateur.
    bot_nick = os.getenv("TWITCH_BOT_NICK", "").lower()
    triggered = (bot_nick and f"@{bot_nick}" in content_lower) or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )

    # Spontaneous intervention (Twitch)
    if not triggered and bot.config.bot.spontaneous_twitch_enabled:
        import time as _time
        state = bot.emotion.get_state()
        trigger_type = _check_spontaneous_trigger(
            content,
            curiosity=state.get("curiosity", 0.0),
            anger=state.get("anger", 0.0),
            boredom=state.get("boredom", 0.0),
        )
        now = _time.time()
        cooldown = bot.config.bot.spontaneous_cooldown_seconds
        cooldown_ok = now - _spontaneous_cooldowns.get(channel_id, 0) >= cooldown

        if trigger_type and cooldown_ok:
            prob = (
                bot.config.bot.spontaneous_passion_probability
                if trigger_type == "passion"
                else bot.config.bot.spontaneous_probability
            )
            if random.random() < prob:
                _spontaneous_cooldowns[channel_id] = now
                _clog(
                    bot, channel_name, "gate_decision",
                    trace_id=_trace, triggered=False, spontaneous=True,
                    trigger_type=trigger_type, decision="spontaneous",
                )
                _fire(_spontaneous_respond_twitch(bot, channel_name, channel_id, author, content, prelude_snapshot=prelude))

    if not triggered:
        return

    # Le cooldown ne s'applique ni à la réponse d'une question que Wally vient
    # de poser, ni à la relance qui suit sa propre réponse : dans les deux cas
    # c'est LUI qui a ouvert le dialogue, et on enchaîne forcément dans les
    # secondes qui suivent. Sans ces exemptions, il demande « tu veux quoi au
    # juste ? » puis avale la réponse, ou lance un chifoumi et ignore le
    # « encore une partie » qui arrive six secondes plus tard.
    exempte = (_consume_open_question(channel_name, user_id)
               or _consume_relance(channel_name, user_id))
    if not exempte and bot.is_on_cooldown(user_id):
        # Journalisé : ce refus était muet, et un message avalé sans trace est
        # indiagnosticable — c'est ce qui a masqué le défaut du 2026-08-08.
        _clog(bot, channel_name, "gate_decision", trace_id=_trace,
              triggered=True, decision="cooldown")
        return

    _clog(bot, channel_name, "gate_decision", trace_id=_trace, triggered=True, decision="respond")

    try:
        self_name = bot.config.bot.name
        platform = "twitch"
        trust = await bot.db.get_trust_score(platform, user_id)

        mem_context = await bot.memory.search(platform, user_id, content, context_messages=prelude, username_hint=author)

        # Temporal activity: inject absence note if user hasn't been seen in 7+ days
        try:
            last_seen = await bot.db.get_last_interaction(f"{platform}:{user_id}")
            if last_seen:
                days_ago = int((time.time() - last_seen) / 86400)
                if days_ago >= 7:
                    absence_note = f"\nDernière interaction avec cet utilisateur : il y a {days_ago} jours."
                    mem_context = (mem_context + absence_note) if mem_context else absence_note.strip()
        except Exception:
            pass

        # ── Fetch context messages early (needed for priority 6) ──────
        context_msgs = await bot.memory.get_context_summarized_if_needed(channel_id)

        # ── Assemble memory context with token budget ──────────────────
        max_tokens = bot.config.bot.memory_context_max_tokens
        memory_parts: list[tuple[int, str]] = []

        # Priority 1: Semantic memories (already fetched)
        if mem_context:
            memory_parts.append((1, mem_context, "souvenirs"))

        # Priority 2: Résumés de sessions précédentes (cross-session recall)
        try:
            summaries = await bot.db.get_recent_session_summaries(platform, channel_id, limit=3)
            recall_block = build_session_recall_block(summaries)
            if recall_block:
                memory_parts.append((2, recall_block, "recall-session"))
        except Exception:
            pass

        # Priority 4: Recent successful jokes for this channel
        try:
            recent_jokes = await bot.db.get_recent_jokes(channel_id, limit=3)
            if recent_jokes:
                jokes_block = "--- Tes blagues récentes qui ont bien marché dans ce salon ---"
                for j in recent_jokes:
                    jokes_block += f'\n- "{j}"'
                memory_parts.append((4, jokes_block, "blagues"))
        except Exception:
            pass

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
        except Exception:
            pass

        # Priority 6: Third-party mentions
        try:
            third_party_ctx = await _third_party_mention_context(
                bot, platform, user_id, prelude, context_msgs
            )
            if third_party_ctx:
                memory_parts.append((6, third_party_ctx, "tiers"))
        except Exception:
            pass

        mem_context = assemble_memory_context(memory_parts, max_tokens)

        # Recall RSS knowledge (patch notes Apex) — HORS budget mémoire pour que les
        # marqueurs de citation [¹](<url>) survivent à la troncature, comme côté
        # Discord. Ce chemin en était privé : le mécanisme n'avait qu'un seul appelant
        # alors que c'est ICI qu'on parle d'Apex, pendant les lives. Wally répondait
        # « je sais pas », et il avait raison — il n'avait rien sous les yeux.
        try:
            from bot.discord.handlers import _rss_knowledge_context

            if rss_block := await _rss_knowledge_context(bot, content or ""):
                mem_context = f"{mem_context}\n\n{rss_block}" if mem_context else rss_block
        except Exception as e:  # noqa: BLE001 — jamais bloquant pour la réponse
            logger.warning("rss_knowledge (twitch): injection ignorée: {}", e)

        # Trust/love go in separate relationship_context (outside token budget)
        love = await bot.db.get_love_score(platform, user_id, bot.config.bot.love_decay_lambda)
        relationship_context = f"Niveau de confiance : {trust:.2f}/1.0\nNiveau d'affection : {love:.2f}/1.0"

        # Portrait de la personne (user model) — non-fatal.
        # Via `_user_id()` : sur Twitch le portrait vit sous l'uid Discord
        # canonique dès que les comptes sont liés (24 liaisons au 2026-08-10).
        person_context = ""
        try:
            _pid = await _canonical_uid(bot, platform, user_id)
            person_context = await bot.db.get_user_profile(_pid) or ""
        except Exception:
            pass
        # Même bloc que sur Discord : le compte Apex déclaré est une propriété
        # de la personne, elle vaut sur les deux plateformes.
        if apex_compte := await _apex_account_context(bot, platform, user_id):
            person_context = f"{person_context}\n{apex_compte}" if person_context else apex_compte

        # Persistent notes
        try:
            persistent_notes = await bot.db.get_persistent_notes()
        except Exception:
            persistent_notes = []

        situation = _build_situation(bot, channel_name)
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=mem_context,
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            relationship_context=relationship_context,
            person_context=person_context,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
            persistent_notes=persistent_notes or None,
            user_directive=bot.persona.user_directive("twitch", user_id, author),
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_msgs)
        target_notice = (
            f"\n⚠️ Tu réponds à **{author}**. "
            "Le contexte ci-dessus contient des messages de PLUSIEURS personnes — "
            "attribue chaque propos à son auteur (indiqué entre crochets). "
            "Ne confonds JAMAIS les propos d'un utilisateur avec ceux d'un autre. "
            f"Si tu nommes ton interlocuteur, appelle-le par SON pseudo exact ({author}) — "
            "n'utilise JAMAIS le nom d'une autre personne présente dans le contexte à sa place. "
            "Réponds UNIQUEMENT avec ton propre texte — ne répète jamais le message auquel tu réponds. "
            "Sois BREF : 1 à 2 phrases maximum, comme dans un vrai chat Twitch."
        )
        user_content = prelude_block + context_block + target_notice + f"\n[{author}]: {content}"

        openai_messages = [{"role": "user", "content": user_content}]

        # ── Outils et exécuteur : les mêmes que sur le chemin vocal ───────
        _est_home = est_chaine_home(bot, channel_name)
        tools = await build_chat_tools(bot, overlay=_est_home)
        _tool_executor = make_tool_executor(
            bot,
            platform="twitch",
            user_id=user_id,
            author=author,
            channel=channel_name,
            trace=_trace,
            user_roles=_resolve_twitch_roles(badges),
            # Les badges du message RÉEL : c'est eux qui décident du contrôle du
            # duel, jamais ce que le modèle croit de qui lui parle.
            badges=badges,
            overlay=_est_home,
        )

        _llm_t0 = time.monotonic()
        if tools:
            reply, _tools_called = await bot.llm.complete_with_tools(
                system_prompt, openai_messages, tools, _tool_executor,
                purpose="twitch_response",
                # L'ID numérique, comme partout ailleurs dans cette fonction
                # (l. 176, 247…) : le login change, l'ID non, et deux formes de
                # clé rendent les coûts inagrégeables.
                user_id=f"twitch:{user_id}",
            )
        else:
            reply = await bot.llm.complete(
                system_prompt, openai_messages,
                purpose="twitch_response",
                user_id=f"twitch:{user_id}",
            )
            _tools_called = []

        _emo = bot.emotion.get_state()
        _dom = max(_emo, key=_emo.get) if _emo else None
        _clog(
            bot, channel_name, "llm_call",
            trace_id=_trace,
            model=getattr(bot.llm, "_model", "?"),
            dominant_emotion=_dom,
            emotion_value=round(_emo.get(_dom, 0.0), 3) if _dom else None,
            tools_offered=[t.get("function", {}).get("name") for t in tools],
            tools_called=_tools_called,
            latency_ms=int((time.monotonic() - _llm_t0) * 1000),
            system_prompt=system_prompt,
            user_content=user_content,
            raw_reply=reply,
        )

        # Strip [react:] tag (no emoji reactions on Twitch)
        if reply.startswith("[react:"):
            import re as _re
            reply = _re.sub(r"^\[react:.+?\]\s*", "", reply)

        # Avant la troncature : une didascalie retirée après coup laisserait un
        # message coupé au mauvais endroit.
        reply = strip_stage_directions(reply)

        if len(reply) > 480:
            reply = reply[:477] + "..."

        # Réponse CHAÎNÉE sur les deux types de chaînes : Helix sur la home, PRIVMSG
        # taggé sur les invitées (cf. `_envoyer_reponse_twitch`).
        _send_mode = await _envoyer_reponse_twitch(
            bot, channel_name, reply,
            author=author,
            parent_msg_id=getattr(payload, "message_id", None) or None,
        )
        # Une réplique qui n'est jamais partie ne doit rien poser derrière elle :
        # ni cooldown (l'utilisateur n'a pas eu de réponse), ni question ouverte,
        # ni trace « Wally vient de lui parler ».
        publie = _send_mode != "perdu"
        if publie:
            bot.set_cooldown(user_id)
            _note_open_question(channel_name, user_id, reply)
            # Wally vient de parler à cette personne : sa prochaine relance ne sera
            # pas du spam, elle prolongera l'échange.
            _note_reply_sent(channel_name, user_id)
        _clog(
            bot, channel_name, "message_out",
            trace_id=_trace, author=self_name, content=reply, parts=1,
            # Mode RÉEL et non déduit du type de chaîne : c'est ce qui permet de voir
            # dans les logs qu'une réponse est retombée sur la mention faute d'id.
            send_mode=_send_mode,
        )
        if publie and getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(channel_id, content=reply)

        if publie and getattr(bot, "reaction_tracker", None):
            bot.reaction_tracker.track_twitch_response(channel_id, reply_text=reply)

        # Le message de l'utilisateur a bien eu lieu : il reste mémorisé quoi
        # qu'il arrive. Seule la réplique de Wally disparaît si elle n'est pas
        # partie — sinon il croirait avoir dit une chose que personne n'a lue.
        bot.memory.append_message(channel_id, author, content, platform="twitch")
        if publie:
            bot.memory.append_prelude(channel_id, self_name, reply)
            bot.memory.append_message(channel_id, self_name, reply, platform="twitch")

        _fire(_post_process(bot, content, platform, user_id, trust, context_msgs, channel_id=channel_id, username=author, trace_id=_trace, conv_channel=channel_name))

    except Exception as e:
        logger.error("Twitch message handling error: {e}", e=e)


async def _post_process(
    bot: "WallyTwitch",
    text: str,
    platform: str,
    user_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
    channel_id: str = "",
    username: str = "",
    trace_id: str = "",
    conv_channel: str = "",
) -> None:
    try:
        _beloved = bot.persona.is_beloved(platform, user_id, username)
        _emo_before = bot.emotion.get_state()
        llm_deltas = await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            trigger_user=user_id, channel_id=channel_id, platform="twitch",
            user_id=user_id,
            beloved=_beloved,
        )
        _emo_after = bot.emotion.get_state()
        if trace_id:
            _deltas = {
                k: round(_emo_after.get(k, 0.0) - _emo_before.get(k, 0.0), 3)
                for k in ("anger", "joy", "sadness", "curiosity", "boredom")
            }
            if any(v != 0 for v in _deltas.values()):
                _clog(
                    bot, conv_channel, "emotion_change",
                    trace_id=trace_id,
                    deltas=_deltas,
                    after={k: round(_emo_after.get(k, 0.0), 3) for k in ("anger", "joy", "sadness", "curiosity", "boredom")},
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
            await bot.memory.add(platform, user_id, "\n".join(llm_deltas["user_facts"]), username=username,
                                 origin=f"Twitch/{conv_channel}" if conv_channel else None)
        if trace_id:
            _clog(
                bot, conv_channel, "post_process",
                trace_id=trace_id,
                facts_extracted=len(llm_deltas.get("user_facts", [])) if llm_deltas else 0,
            )
    except Exception as e:
        logger.error("Twitch post-process error: {e}", e=e)


async def _announce_overlay_image(
    bot: "WallyTwitch", channel_name: str, channel_id: str, image: dict,
    dashboard_state, overlay_payload: dict,
) -> None:
    """Generate LLM message first, then send overlay image + chat message simultaneously."""
    try:
        self_name = bot.config.bot.name
        title = image.get("title") or "sans titre"
        creator = image.get("username") or "quelqu'un"
        prompt_text = image.get("prompt") or ""

        prelude = bot.memory.get_prelude(channel_id)
        context_msgs = await bot.memory.get_context_summarized_if_needed(channel_id)

        situation = _build_situation(bot, channel_name)
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_msgs)

        image_desc = f"Image affichée sur le stream : \"{title}\" par {creator}."
        if prompt_text:
            image_desc += f" Prompt original : \"{prompt_text}\""

        user_content = (
            "[CONTEXTE: Quelqu'un vient de déclencher !image sur le stream. "
            "Une image de la galerie s'affiche sur l'overlay. "
            "Présente cette image au chat en UNE phrase courte et naturelle. "
            "Mentionne le créateur de l'image.]\n\n"
            + prelude_block
            + context_block
            + f"\n[SYSTÈME]: {image_desc}"
        )

        # 1. Générer le message LLM (le plus lent)
        reply = await bot.llm.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="twitch_overlay_announce",
        )

        # Strip react tag
        if reply.startswith("[react:"):
            import re as _re
            reply = _re.sub(r"^\[react:.+?\]\s*", "", reply)
        reply = strip_stage_directions(reply)
        if len(reply) > 480:
            reply = reply[:477] + "..."

        # 2. Envoyer overlay + message chat en même temps
        dashboard_state.overlay_image_feed.publish(overlay_payload)

        # `redact` ici aussi : ces deux chemins n'appellent pas
        # `_envoyer_reponse_twitch`. Et un `if irc_channel:` SANS `else`
        # abandonnait le message en silence tout en le versant au prélude et à
        # la mémoire juste après — Wally croyait avoir dit ce que personne
        # n'avait lu. `_envoyer_reponse_twitch` gère ce cas depuis longtemps ;
        # ces deux-là ne l'avaient pas repris.
        reply = redact(reply)
        if channel_name in bot._channel_ids:
            irc_channel = bot.get_channel(channel_name)
            if irc_channel is None:
                logger.warning("IRC non connecté pour {ch}, message ignoré", ch=channel_name)
                return
            await irc_channel.send(reply)
        elif not await bot.twitch_api.send_message(text=reply):
            # Helix répond 200 sans rien publier quand AutoMod retient le
            # message ou que la chaîne filtre : même conclusion que l'IRC
            # déconnecté juste au-dessus. `send_message` a déjà dit pourquoi.
            return

        bot.memory.append_prelude(channel_id, self_name, reply)
        bot.memory.append_message(channel_id, self_name, reply, platform="twitch")
    except Exception as e:
        logger.error("Overlay image announce error: {e}", e=e)


async def _spontaneous_respond_twitch(
    bot: "WallyTwitch", channel_name: str, channel_id: str,
    author: str, content: str,
    recall_memory: str | None = None,
    prelude_snapshot: list[dict] | None = None,
) -> None:
    """Generate and send a spontaneous Twitch response."""
    try:
        self_name = bot.config.bot.name
        prelude = prelude_snapshot if prelude_snapshot is not None else bot.memory.get_prelude(channel_id)
        situation = _build_situation(bot, channel_name)
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=recall_memory or "",
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
            user_directive=bot.persona.user_directive("twitch", "", author),
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        recall_block = ""
        if recall_memory:
            recall_block = (
                "\n--- Souvenir qui te revient ---\n"
                f"{recall_memory}\n"
                f"Tu viens de te rappeler quelque chose en lien avec ce que dit "
                f"{author}. Évoque-le naturellement.\n\n"
            )
            logger.info("Memory recall for {user} on Twitch: {mem}", user=author, mem=recall_memory[:80])
        user_content = (
            "[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément "
            "parce que le sujet t'intéresse ou te fait réagir. Réponds en une "
            "phrase courte et percutante, comme un commentaire lâché en passant.]\n\n"
            + recall_block
            + prelude_block
            + f"\n[{author}]: {content}"
        )
        reply = await bot.llm.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="twitch_spontaneous",
        )
        _spont_trace = new_trace_id("twitch_spont")
        _emo = bot.emotion.get_state()
        _dom = max(_emo, key=_emo.get) if _emo else None
        _clog(
            bot, channel_name, "llm_call",
            trace_id=_spont_trace, kind="spontaneous",
            model=getattr(bot.llm, "_model", "?"),
            dominant_emotion=_dom,
            emotion_value=round(_emo.get(_dom, 0.0), 3) if _dom else None,
            system_prompt=system_prompt, user_content=user_content, raw_reply=reply,
        )
        # Strip react tag (no reactions on Twitch)
        if reply.startswith("[react:"):
            import re as _re
            reply = _re.sub(r"^\[react:.+?\]\s*", "", reply)
        if len(reply) > 480:
            reply = reply[:477] + "..."

        # `redact` ici aussi : ces deux chemins n'appellent pas
        # `_envoyer_reponse_twitch`. Et un `if irc_channel:` SANS `else`
        # abandonnait le message en silence tout en le versant au prélude et à
        # la mémoire juste après — Wally croyait avoir dit ce que personne
        # n'avait lu. `_envoyer_reponse_twitch` gère ce cas depuis longtemps ;
        # ces deux-là ne l'avaient pas repris.
        reply = redact(reply)
        if channel_name in bot._channel_ids:
            irc_channel = bot.get_channel(channel_name)
            if irc_channel is None:
                logger.warning("IRC non connecté pour {ch}, message ignoré", ch=channel_name)
                return
            await irc_channel.send(reply)
        elif not await bot.twitch_api.send_message(text=reply):
            # Refus d'Helix (AutoMod, réglage de chaîne, timeout) : ni journal,
            # ni cognition, ni mémoire. Un `message_out` écrit ici pour une
            # phrase jamais publiée fait chercher la panne du mauvais côté —
            # c'est ce qui s'est produit le 2026-08-11.
            return
        _clog(
            bot, channel_name, "message_out",
            trace_id=_spont_trace, kind="spontaneous", author=self_name,
            content=reply, parts=1,
        )
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(channel_id, content=reply)

        bot.memory.append_prelude(channel_id, self_name, reply)
        bot.memory.append_message(channel_id, self_name, reply, platform="twitch")
        logger.info("Spontaneous intervention in twitch:{ch}", ch=channel_name)

    except Exception as e:
        logger.error("Twitch spontaneous error: {e}", e=e)
