"""Outils LLM pour le contexte vocal (join_voice / leave_voice)."""
import asyncio
import contextvars
import json

from loguru import logger

from bot.core.apex.tool import APEX_OVERLAY_TOOL
from bot.core.music_tool import MUSIC_TOOL, run_music_tool
from bot.core.surnoms import REFUS as REFUS_SURNOM, detecter as detecter_surnom
from bot.core.web_search import WEB_SEARCH_TOOL
from bot.discord.voice.brain import generate_search_filler
from bot.intelligence.overlay_narrator import (
    CANCEL_TOOL_SPEC as OVERLAY_CANCEL_TOOL,
    LAST_CLIP_TOOL_SPEC as LAST_CLIP_TOOL,
    spec_overlay_pour,
)

VOICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "join_voice",
            "description": (
                "Quand quelqu'un te demande de venir/rejoindre le salon vocal "
                "(ex: 'viens en vocal', 'rejoins-nous'). Tu rejoins le salon vocal de la personne."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leave_voice",
            "description": (
                "Quand on te demande de quitter/partir du salon vocal "
                "(ex: 'quitte le vocal', 'tu peux partir', 'dégage du vocal')."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ── Faire dire quelque chose à Wally, à voix haute ──────────────────────────
#
# Demandé depuis le CHAT TWITCH, par un modérateur ou le streamer : « wally dis
# à Azra qu'il a plus de balles ». Wally le dit dans le salon vocal.
#
# Il REFORMULE plutôt que de répéter : c'est lui qui parle, avec sa voix et son
# caractère, pas un haut-parleur. Le modèle écrit donc `text` à sa sauce — la
# description ci-dessous le lui dit, et c'est le seul endroit où ça se joue.
SAY_IN_VOICE_TOOL = {
    "type": "function",
    "function": {
        "name": "say_in_voice",
        "description": (
            "Quand un MODÉRATEUR ou le streamer te demande depuis le chat de "
            "dire quelque chose à voix haute dans le salon vocal — par exemple "
            "« wally dis à Azra qu'il a plus de balles », « préviens-les que le "
            "raid arrive ». Tu le dis DANS LE VOCAL, avec tes mots à toi : "
            "reformule, ne récite pas. N'appelle cet outil que si on te demande "
            "de PARLER en vocal ; pour répondre dans le chat, réponds "
            "normalement."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Ce que tu vas dire à voix haute, formulé par toi. "
                        "Court : on est en plein live."
                    ),
                },
            },
            "required": ["text"],
        },
    },
}

# Les RÔLES qui donnent ce droit, dans le vocabulaire de `_resolve_twitch_roles`
# — où le broadcaster est « admin » et non « moderator ». L'oublier aurait
# refusé la fonction à la seule personne qui ne peut pas se la voir refuser.
_ROLES_AUTORISES = {"moderator", "admin"}


async def run_say_in_voice_tool(bot, args: dict, *, roles=None,
                                maison: bool = True) -> str:
    """Fait dire `text` à Wally dans le salon vocal. Rend ce que le modèle lira.

    `roles` vient de l'APPELANT — `_resolve_twitch_roles()` sur les badges du
    message réel —, jamais du modèle : c'est ce qui empêche un viewer de se
    faire passer pour un modérateur en le prétendant dans son message. Absents
    (chemin vocal, appel interne), la personne est traitée comme un viewer
    ordinaire — le refus est le défaut sûr, comme pour le duel.

    Des RÔLES et non des badges bruts : un badge twitchio est un objet (`.id`),
    l'EventSub en rend un dict (`set_id`), et lire une seule de ces formes a
    déjà cassé ici — `'_ChatBadge' object has no attribute 'get'`, en direct, au
    premier essai. La normalisation appartient au bord Twitch, qui la fait déjà.
    """
    texte = str((args or {}).get("text") or "").strip()
    if not texte:
        return "Refusé : aucun texte à dire."
    # Même garde que l'overlay : le salon vocal appartient au stream maison. Sans
    # elle, un modérateur d'une chaîne INVITÉE ferait parler Wally chez Azraël,
    # devant ses viewers.
    if not maison:
        return ("Refusé : le salon vocal appartient à la chaîne maison, on ne le "
                "commande pas depuis une chaîne invitée. Dis-le simplement.")
    if not (set(roles or ()) & _ROLES_AUTORISES):
        # Le refus DIT quoi en faire : sans consigne, Wally répondrait par un
        # « non » plat, alors que l'owner veut qu'il charrie la personne.
        return ("Refusé : cette personne n'est ni modérateur ni le streamer, "
                "elle n'a pas le droit de te faire parler en vocal. Moque-toi "
                "gentiment d'elle dans le chat, en une phrase.")
    # Des DEUX côtés, comme `_overlay_narrator`. `bot.discord_bot` est la
    # référence CROISÉE, posée sur le bot TWITCH ; `voice_service` n'existe en
    # propre que sur `WallyDiscord`. Appelé depuis un MP Discord, `bot` EST déjà
    # le bot Discord : la seule recherche croisée rendait None, et Wally
    # répondait « je ne suis plus dans le salon vocal » depuis un salon où il
    # était assis (vécu le 2026-08-25, premier essai de l'owner).
    #
    # On retient celui qui est CONNECTÉ, pas le premier attribut trouvé : c'est
    # un salon vocal actif qu'on cherche, et la question se pose à l'identique
    # des deux côtés.
    service = next(
        (s for s in (getattr(bot, "voice_service", None),
                     getattr(getattr(bot, "discord_bot", None), "voice_service", None))
         if s is not None and getattr(s, "is_connected", False)),
        None,
    )
    if service is None:
        return ("Impossible : tu n'es pas dans un salon vocal en ce moment. "
                "Dis-le à la personne.")
    try:
        # `malgre_ecoute` : pendant un live, Wally est en écoute seule et
        # `speak()` refuse de parler pour ne pas couvrir le streamer. C'est
        # justement le moment où cette fonction sert, et la demande est
        # explicite — donc elle passe. Seule la récompense « im out » le fait
        # aussi, et pour la même raison.
        #
        # Le retour est LU. Il ne l'était pas : `speak()` se taisait en silence
        # sur cinq chemins (salon perdu entre-temps, texte réduit à rien par le
        # nettoyage de style, timeout du TTS, panne Azure), et cette fonction
        # répondait quand même « c'est dit à voix haute » — Wally confirmait au
        # modérateur une phrase que personne n'avait entendue.
        sortie = await service.speak(texte, malgre_ecoute=True)
    except Exception as e:  # noqa: BLE001 — une panne du vocal ne casse pas le chat
        logger.warning("say_in_voice a échoué: {e!r}", e=e)
        return "Impossible : la parole n'est pas sortie. Dis-le à la personne."
    if not sortie:
        logger.warning("say_in_voice : la parole n'est pas sortie — « {t} »", t=texte[:80])
        return "Impossible : la parole n'est pas sortie. Dis-le à la personne."
    logger.info("voice: dit à voix haute sur demande d'un modo — « {t} »", t=texte[:80])
    return f"C'est dit à voix haute dans le vocal : « {texte} ». Confirme-le en une phrase."


async def build_voice_tools(bot) -> list[dict]:
    """Liste des outils proposés en vocal, selon ce qui est disponible."""
    from bot.discord.handlers import _NOTE_TOOLS, _overlay_narrator

    tools = list(VOICE_TOOLS)
    web = getattr(bot, "web_search", None)
    if web is not None and web.available and not await web.is_quota_exceeded():
        tools.append(WEB_SEARCH_TOOL)
    tools.extend(_NOTE_TOOLS)
    # La musique d'Azraël, en LECTURE : « c'est quoi ce son ? » se pose autant à
    # voix haute qu'à l'écrit, et le §10 veut la réponse ouverte à tout le monde.
    # Le pilotage, lui, reste au chat Twitch — un salon vocal ne porte aucun
    # badge de modérateur, et `pilotable=False` l'ORIENTE plutôt que de refuser.
    if getattr(bot, "music", None) is not None:
        tools.append(MUSIC_TOOL)
    action_service = getattr(bot, "action_service", None)
    if action_service is not None:
        tools.extend(action_service.get_tool_definitions())
    # L'overlay, exactement comme au chat : « affiche un mème », « montre le
    # dernier clip » se demandent autant à voix haute qu'à l'écrit. Ces outils
    # manquaient ICI et nulle part ailleurs — Wally répondait poliment sans rien
    # afficher, trois fois de suite en direct le 2026-08-25, jusqu'au « il a pas
    # l'air de vouloir afficher quoi que ce soit » d'Azraël.
    #
    # Pas de garde `maison` à poser, contrairement au chat : un salon vocal
    # Discord n'est jamais une chaîne Twitch invitée. Le refus hors live, lui,
    # est déjà tenu par `run_overlay_tool` via `narrateur.is_active()`.
    narrateur = _overlay_narrator(bot)
    if narrateur is not None:
        # L'enum est relu ICI, juste avant que Wally décide : un widget masqué
        # sur TOUTES les scènes ne doit pas lui être proposé, sinon il l'affiche
        # et annonce « c'est à l'écran » devant un écran où rien n'apparaît.
        tools.append(await spec_overlay_pour(narrateur))
        tools.append(OVERLAY_CANCEL_TOOL)
        tools.append(LAST_CLIP_TOOL)
        if getattr(bot, "apex_api", None) is not None:
            tools.append(APEX_OVERLAY_TOOL)
    return tools


async def _search_aloud(bot, service, query: str) -> str:
    """Cherche sur le web en « parlant tout haut » : amorce + bruits pendant l'attente."""
    filler_task = asyncio.create_task(generate_search_filler(bot, query))
    search_task = asyncio.create_task(bot.web_search.search(query, platform="discord"))
    try:
        filler = await filler_task
        await service.speak(filler.get("amorce") or "")
        for bruit in filler.get("bruits") or []:
            if search_task.done():
                break
            await service.speak(bruit)
    except Exception as e:  # noqa: BLE001
        logger.warning("_search_aloud filler a échoué: {e!r}", e=e)
    return await search_task


# Qui parle DANS CE TOUR-CI. Une `ContextVar` et non un champ du service : chaque
# `asyncio.Task` reçoit sa propre copie du contexte, donc une transcription qui
# arrive pendant qu'on répond ne peut plus écraser l'identité du tour en cours.
#
# Le service exposait `_current_speaker_id`, un champ unique écrit à chaque
# transcription entendue. Deux façons de le rendre faux :
#   1. course — pendant l'attente du LLM pour A, la parole de B arrive dans une
#      autre tâche et écrase le champ ; l'outil appelé pour A voit B ;
#   2. déterministe — `_maybe_respond` défile la file des paroles en attente et
#      appelle `_respond_once(sid, …)` sans jamais réécrire le champ. Toute
#      parole défilée était donc traitée sous l'identité du dernier locuteur
#      ENTENDU, pas de celui qu'on traite.
# `leave_voice` vérifiait donc son autorisation contre la mauvaise personne, et
# `create_action_task` / `cancel_action_task` s'exécutaient avec les rôles
# Discord d'un autre membre — une escalade de privilèges silencieuse si ce
# membre est admin.
_CURRENT_SPEAKER: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "voice_current_speaker", default=None,
)


def set_current_speaker(user_id: str | None):
    """Déclare le locuteur du tour de parole en cours. Rend le jeton de reset."""
    return _CURRENT_SPEAKER.set(str(user_id) if user_id else None)


def reset_current_speaker(token) -> None:
    _CURRENT_SPEAKER.reset(token)


def make_voice_tool_executor(bot, service, current_speaker_id):
    """Construit l'exécuteur d'outils pour le contexte vocal.

    Args:
        bot: instance discord.Bot
        service: VoiceService
        current_speaker_id: callable() -> str | None — repli si le tour de parole
            n'a pas déclaré son locuteur (ne devrait plus arriver).
    """

    def _speaker() -> str | None:
        sid = _CURRENT_SPEAKER.get()
        if sid is not None:
            return sid
        # Repli BRUYANT : c'est exactement la lecture qui attribuait les outils
        # au mauvais membre. Si elle resurgit, elle doit se voir dans les logs.
        sid = current_speaker_id()
        logger.warning(
            "voice tool: locuteur du tour non déclaré, repli sur le dernier "
            "entendu ({sid}) — l'autorisation peut viser la mauvaise personne",
            sid=sid,
        )
        return sid

    def _membre_du_locuteur(sid: str | None = None):
        """Le membre Discord de qui parle, s'il est bien dans le salon.

        `sid` déjà connu se passe en argument : `_speaker()` journalise un
        WARNING quand le tour n'a pas déclaré son locuteur, et l'appeler deux
        fois de suite doublerait la ligne sans rien apprendre.
        """
        if sid is None:
            sid = _speaker()
        salon = getattr(service, "_channel", None)
        if salon is None or sid is None:
            return None
        return next((m for m in salon.members if str(m.id) == str(sid)), None)

    def _nom_du_locuteur() -> str:
        """L'étiquette AFFICHABLE du locuteur, telle que le chat la connaît.

        Elle part en `requester` vers `show_overlay`, où elle nomme la main
        adverse du chifoumi. Elle vient d'ICI et jamais du modèle : sinon Wally
        ferait jouer quelqu'un d'autre que celui qui lui a parlé.
        """
        from bot.discord.handlers import _author_label
        membre = _membre_du_locuteur()
        return _author_label(membre) if membre is not None else ""

    def _identite_du_locuteur() -> str | None:
        """L'IDENTIFIANT du locuteur — « discord:123 », comme au chat.

        `show_apex` porte le même nom de paramètre que `show_overlay` et n'en
        attend pas du tout la même chose : `requester` y descend jusqu'à
        `_resolve_uid`, qui cherche le compte Apex LIÉ à cette personne. Un
        pseudo affichable n'y résout rien, et le panneau sort sans le compte du
        demandeur — sans que rien n'échoue.
        """
        sid = _speaker()
        return f"discord:{sid}" if sid is not None else None

    async def _executer(name: str, arguments: str) -> str:
        try:
            _ = json.loads(arguments or "{}")
        except Exception:  # noqa: BLE001
            pass

        if name == "leave_voice":
            speaker = _speaker()
            # `int()` gardé : `current_speaker_id()` est alimenté par
            # `str(user.id)` mais AUSSI par un `speaker_id` venu du serveur STT
            # distant, qui n'est pas garanti numérique. Un ValueError cassait
            # alors l'appel d'outil au milieu de `complete_with_tools` : le
            # modèle ne recevait aucun résultat et enchaînait souvent sur un
            # « ok je pars » sans partir.
            try:
                sid = int(speaker) if speaker is not None else None
            except (TypeError, ValueError):
                sid = None
            if sid is None or sid not in service.members_in_channel():
                logger.info("voice tool: leave_voice refusé — locuteur absent du salon")
                return json.dumps(
                    {"status": "denied", "message": "Seul un membre du salon peut me faire partir."}
                )
            await service.speak("ok, je vous laisse")
            await service.leave()
            logger.info("voice tool: leave_voice exécuté")
            return json.dumps({"status": "ok", "message": "Quitté le salon vocal."})

        if name == "join_voice":
            # En contexte vocal, Wally est déjà connecté ; le join réel se fait côté texte (Task 7).
            return json.dumps({"status": "ok", "message": "Déjà en vocal."})

        if name == "web_search":
            args = {}
            try:
                args = json.loads(arguments or "{}")
            except Exception:  # noqa: BLE001
                pass
            query = (args.get("query") or "").strip()
            if not query:
                return json.dumps({"status": "error", "message": "Requête vide."})
            return await _search_aloud(bot, service, query)

        if name == "music_control":
            args = {}
            try:
                args = json.loads(arguments or "{}")
            except Exception:  # noqa: BLE001 — un JSON tordu vaut une demande vide
                pass
            return await run_music_tool(bot, args, roles=None, pilotable=False)

        if name == "save_persistent_note":
            a = json.loads(arguments or "{}")
            # `.get()` et non `a["title"]` : le champ est `required` au schéma,
            # ce qui ne garantit rien — un modèle qui l'omet levait un KeyError
            # au milieu de `complete_with_tools`, le tour de parole partait sans
            # résultat d'outil et Wally enchaînait sur un « c'est noté » qui
            # n'avait rien noté. Exactement le défaut déjà payé sur `int()` dans
            # `leave_voice`.
            titre = str(a.get("title") or "").strip()
            contenu = str(a.get("content") or "").strip()
            if not titre or not contenu:
                return json.dumps({"status": "error", "message": (
                    "Il me faut un titre ET un contenu pour noter. Redemande-les."
                )})
            await bot.db.upsert_persistent_note(titre, contenu)
            return json.dumps({"status": "ok", "message": f"Note '{titre}' sauvegardée."})

        if name == "delete_persistent_note":
            a = json.loads(arguments or "{}")
            titre = str(a.get("title") or "").strip()
            if not titre:
                return json.dumps({"status": "error", "message": (
                    "Il me faut le titre de la note à supprimer."
                )})
            deleted = await bot.db.delete_persistent_note(titre)
            if deleted:
                return json.dumps({"status": "ok", "message": f"Note '{titre}' supprimée."})
            return json.dumps({"status": "not_found", "message": f"Note '{titre}' introuvable."})

        if name == "save_user_memory":
            # Proposé au vocal depuis toujours via `_NOTE_TOOLS`, jamais routé :
            # « retiens que… » dit à voix haute rendait « Outil inconnu », et
            # Wally répondait « c'est noté » sans rien avoir noté. Le souvenir
            # appartient à qui PARLE, pas au dernier entendu.
            a = json.loads(arguments or "{}")
            contenu = str(a.get("content") or "").strip()
            if not contenu:
                return json.dumps({"status": "error",
                                   "message": "Il me faut ce que je dois retenir."})
            refus = detecter_surnom(contenu)
            if refus is not None:
                logger.info("voice tool: souvenir refusé ({r}) : « {c} »",
                            r=refus, c=contenu[:120])
                return json.dumps({"status": "denied", "message": REFUS_SURNOM})
            # Pas `sid` : le nom porte déjà un `int | None` dans `leave_voice`,
            # et mypy type une locale à sa PREMIÈRE assignation.
            locuteur = _speaker()
            if locuteur is None:
                return json.dumps({"status": "error", "message": (
                    "Je ne sais pas de qui vient cette demande, je préfère ne rien "
                    "retenir. Dis-le simplement."
                )})
            from bot.discord.handlers import _author_label, _channel_origin
            membre = _membre_du_locuteur(locuteur)
            salon = getattr(service, "_channel", None)
            # `user_id` BRUT : `memory.add` construit « platform:user_id » lui-même.
            await bot.memory.add(
                "discord", str(locuteur), contenu,
                username=_author_label(membre) if membre is not None else None,
                origin=_channel_origin(salon) if salon is not None else "Discord vocal",
            )
            logger.info("voice tool: souvenir retenu pour {sid}", sid=locuteur)
            return json.dumps({"status": "ok", "message": "Souvenir sauvegardé."})

        if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
            from bot.discord.handlers import _resolve_discord_roles
            a = json.loads(arguments or "{}")
            speaker_id = _speaker()
            channel = getattr(service, "_channel", None)
            member = _membre_du_locuteur(speaker_id)
            user_roles = _resolve_discord_roles(member) if member is not None else []
            admin_ids = [str(x) for x in getattr(bot.config, "admin_ids", [])]
            if speaker_id is not None and str(speaker_id) in admin_ids:
                user_roles.append("admin")
            # Création → besoin d'un salon cible (la chambre). Refus propre sinon.
            if name == "create_action_task":
                bedroom = getattr(bot.config.bot, "bedroom_channel_id", None)
                if bedroom is None:
                    return json.dumps({"status": "denied",
                                       "message": "Je ne sais pas encore où poster tes rappels."})
                channel_id = str(bedroom)
            else:
                channel_id = None
            guild_id = str(channel.guild.id) if channel is not None and getattr(channel, "guild", None) else None
            result = await bot.action_service.execute_tool(
                name, a, user_id=str(speaker_id), platform="discord",
                user_roles=user_roles, channel_id=channel_id, guild_id=guild_id,
            )
            return json.dumps(result)

        if name in ("show_overlay", "cancel_overlay", "show_clip", "show_apex"):
            # Import LOCAL : `handlers` importe `VOICE_TOOLS` d'ici, un import
            # de module serait circulaire. Les exécuteurs sont pris tels quels —
            # ils ne connaissent du chat que `bot` et `args`, et rendent déjà le
            # compte rendu honnête (refus hors live, partie déjà en cours).
            from bot.discord import handlers as chat
            try:
                a = json.loads(arguments or "{}")
            except Exception:  # noqa: BLE001 — un JSON tordu vaut une demande vide
                a = {}
            if name == "cancel_overlay":
                return chat.run_overlay_cancel_tool(bot, a)
            if name == "show_clip":
                return await chat.run_last_clip_tool(bot, a)
            if name == "show_apex":
                return await chat.run_apex_overlay_tool(
                    bot, a, requester=_identite_du_locuteur())
            return chat.run_overlay_tool(bot, a, requester=_nom_du_locuteur())

        return json.dumps({"status": "error", "message": f"Outil inconnu: {name}"})

    async def executor(name: str, arguments: str) -> str:
        """Le filet : un outil qui lève ne doit pas casser le tour de parole.

        Sans lui, l'exception remonte dans `complete_with_tools`, le modèle ne
        reçoit AUCUN résultat pour son appel, et il enchaîne le plus souvent sur
        un « c'est fait » portant sur un geste qui n'a pas eu lieu. Deux fois
        déjà : le `ValueError` d'un `speaker_id` non numérique dans
        `leave_voice`, le `KeyError` d'un champ de note absent.
        """
        try:
            return await _executer(name, arguments)
        except Exception as exc:  # noqa: BLE001 — un outil raté ne casse pas la parole
            logger.warning("voice tool: « {n} » a levé — {e!r}", n=name, e=exc)
            return json.dumps({"status": "error", "message": (
                f"L'outil « {name} » a échoué. Ne prétends pas l'avoir fait."
            )})

    return executor
