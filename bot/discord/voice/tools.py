"""Outils LLM pour le contexte vocal (join_voice / leave_voice)."""
import asyncio
import contextvars
import json

from loguru import logger

from bot.core.web_search import WEB_SEARCH_TOOL
from bot.discord.voice.brain import generate_search_filler

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

# Les badges Twitch qui donnent ce droit. Le broadcaster ne porte PAS le badge
# `moderator` — l'oublier aurait refusé la fonction à la seule personne qui ne
# peut pas se la voir refuser.
_BADGES_AUTORISES = {"moderator", "broadcaster"}


async def run_say_in_voice_tool(bot, args: dict, *, badges=None,
                                maison: bool = True) -> str:
    """Fait dire `text` à Wally dans le salon vocal. Rend ce que le modèle lira.

    Les badges viennent de l'APPELANT, jamais du modèle : c'est ce qui empêche
    un viewer de se faire passer pour un modérateur en le prétendant dans son
    message. Absents (chemin vocal, appel interne), la personne est traitée
    comme un viewer ordinaire — le refus est le défaut sûr, comme pour le duel.
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
    noms = {str((b or {}).get("set_id") or "") for b in (badges or [])}
    if not (noms & _BADGES_AUTORISES):
        # Le refus DIT quoi en faire : sans consigne, Wally répondrait par un
        # « non » plat, alors que l'owner veut qu'il charrie la personne.
        return ("Refusé : cette personne n'est ni modérateur ni le streamer, "
                "elle n'a pas le droit de te faire parler en vocal. Moque-toi "
                "gentiment d'elle dans le chat, en une phrase.")
    service = getattr(getattr(bot, "discord_bot", None), "voice_service", None)
    if service is None or not getattr(service, "is_connected", False):
        return ("Impossible : tu n'es pas dans un salon vocal en ce moment. "
                "Dis-le à la personne.")
    try:
        # `malgre_ecoute` : pendant un live, Wally est en écoute seule et
        # `speak()` refuse de parler pour ne pas couvrir le streamer. C'est
        # justement le moment où cette fonction sert, et la demande est
        # explicite — donc elle passe. Aucun autre chemin de parole ne le fait.
        await service.speak(texte, malgre_ecoute=True)
    except Exception as e:  # noqa: BLE001 — une panne du vocal ne casse pas le chat
        logger.warning("say_in_voice a échoué: {e}", e=e)
        return "Impossible : la parole n'est pas sortie. Dis-le à la personne."
    logger.info("voice: dit à voix haute sur demande d'un modo — « {t} »", t=texte[:80])
    return f"C'est dit à voix haute dans le vocal : « {texte} ». Confirme-le en une phrase."


async def build_voice_tools(bot) -> list[dict]:
    """Liste des outils proposés en vocal, selon ce qui est disponible."""
    tools = list(VOICE_TOOLS)
    web = getattr(bot, "web_search", None)
    if web is not None and web.available and not await web.is_quota_exceeded():
        tools.append(WEB_SEARCH_TOOL)
    from bot.discord.handlers import _NOTE_TOOLS
    tools.extend(_NOTE_TOOLS)
    action_service = getattr(bot, "action_service", None)
    if action_service is not None:
        tools.extend(action_service.get_tool_definitions())
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
        logger.warning("_search_aloud filler a échoué: {e}", e=e)
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

    async def executor(name: str, arguments: str) -> str:
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

        if name == "save_persistent_note":
            a = json.loads(arguments or "{}")
            await bot.db.upsert_persistent_note(a["title"], a["content"])
            return json.dumps({"status": "ok", "message": f"Note '{a['title']}' sauvegardée."})

        if name == "delete_persistent_note":
            a = json.loads(arguments or "{}")
            deleted = await bot.db.delete_persistent_note(a["title"])
            if deleted:
                return json.dumps({"status": "ok", "message": f"Note '{a['title']}' supprimée."})
            return json.dumps({"status": "not_found", "message": f"Note '{a['title']}' introuvable."})

        if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
            from bot.discord.handlers import _resolve_discord_roles
            a = json.loads(arguments or "{}")
            speaker_id = _speaker()
            channel = getattr(service, "_channel", None)
            member = None
            if channel is not None and speaker_id is not None:
                member = next((m for m in channel.members if str(m.id) == str(speaker_id)), None)
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

        return json.dumps({"status": "error", "message": f"Outil inconnu: {name}"})

    return executor
