"""Ce que Wally FAIT quand une action planifiée arrive à échéance.

Extrait de `bot/main.py` le 2026-08-23, où ces trois handlers étaient des
closures dans un `main()` de mille lignes — donc du comportement qu'aucun test
ne pouvait exécuter. Le seul « test » qui les visait lisait le SOURCE de
`main.py` et y cherchait des bouts de phrase :

    assert "guildes = [guilde_origine]" in corps
    assert "for guild in discord_bot.guilds:" not in corps

Cela couvrait une correction de SÉCURITÉ — un ping de masse cross-serveur — en
vérifiant la présence d'une chaîne de caractères. Le test serait resté vert
devant n'importe quelle logique contenant ces mots.

Les dépendances sont des paramètres nommés, à lier par `functools.partial` au
moment de l'enregistrement. Le registre appelle `handler(payload, target)` :
ces deux-là restent donc positionnels.
"""
from __future__ import annotations

from functools import partial
from typing import Any

from loguru import logger

from bot.core.llm.base import FALLBACK_RESPONSE


async def reminder_handler(
    payload: dict,
    target: dict,
    *,
    prompts: Any,
    emotion: Any,
    persona: Any,
    secondary_llm: Any,
) -> str:
    """Le rappel, reformulé par Wally — persona, humeur, directives du jour.

    Le texte brut sert de repli à chaque étape. Un rappel qui n'arrive pas est
    pire qu'un rappel mal tourné : la tâche `once`, elle, est consommée.
    """
    raw_msg = payload.get("message", "Rappel!")
    creator_id = target.get("creator_id")
    platform = target.get("platform", "")

    try:
        system_prompt = prompts.build_system_prompt(
            emotion_state=emotion.get_state(),
            situation={"platform": platform, "datetime": True},
            persona_block=persona.build_prompt_block(),
            emotion_directives=persona.emotion_directives,
            weekday_directives=persona.weekday_directives,
            composite_directives=persona.composite_directives,
        )
        user_content = (
            f"[INSTRUCTION SYSTÈME, NE PAS CITER]\n"
            f"Tu dois envoyer un rappel à un utilisateur. "
            f"Voici le contenu du rappel : \"{raw_msg}\"\n"
            f"Formule ce rappel avec ta personnalité, ton humeur actuelle, "
            f"et ton style habituel. Sois bref (1-2 phrases max). "
            f"Ne mets PAS de mention (@), elle sera ajoutée automatiquement."
        )
        reply = await secondary_llm.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="reminder",
            user_id=creator_id,
        )
        reply = reply.strip()
        # `complete()` ne lève pas : il rend FALLBACK_RESPONSE. Sans ce test,
        # l'utilisateur recevait « Je rencontre un problème technique » à la
        # place de son rappel — et la tâche `once` était consommée quand même :
        # le rappel ne repartait jamais.
        if not reply or reply == FALLBACK_RESPONSE:
            logger.warning("Rappel : génération en repli, on envoie le texte demandé")
            reply = raw_msg
    except Exception as e:
        logger.warning("Reminder LLM generation failed, using raw message: {e!r}", e=e)
        reply = raw_msg

    if platform == "discord" and creator_id:
        return f"<@{creator_id}> {reply}"
    return reply


async def join_twitch_channel_handler(
    payload: dict,
    target: dict,
    *,
    twitch_bot: Any,
) -> str:
    channel = payload.get("channel", "").lower().strip()
    if not channel:
        return "Nom de chaîne manquant."
    if twitch_bot is None:
        return "Twitch non disponible."
    result = await twitch_bot.add_guest_channel(channel)
    if result == "already_added":
        return f"Je suis déjà dans la chaîne {channel}."
    if result is None:
        return f"Impossible de rejoindre {channel}, chaîne introuvable ou API indisponible."
    return f"J'ai rejoint la chaîne {channel}."


def _salon_discord_par_nom(discord_bot: Any, nom: str, origine: Any) -> str | None:
    """L'id du salon portant ce nom, cherché DANS LE SERVEUR D'ORIGINE seulement.

    La recherche balayait `discord_bot.guilds` en entier. La permission était
    validée sur le serveur d'où venait la tâche, puis le message pouvait partir
    dans n'importe quel salon de n'importe quel AUTRE serveur portant le même
    nom — « #général » en porte un partout. Combiné à l'envoi sans
    `allowed_mentions`, cela permettait un ping de masse cross-serveur.

    Sans salon d'origine identifiable, on retombe sur tous les serveurs : c'est
    le comportement des tâches créées hors d'un salon, et le resserrer casserait
    l'envoi légitime. Le bornage porte sur le cas qui était exploitable.
    """
    cible = nom.lstrip("#").lower()
    guildes = discord_bot.guilds
    if origine:
        try:
            salon_origine = discord_bot.get_channel(int(origine))
        except (TypeError, ValueError):
            salon_origine = None
        guilde_origine = getattr(salon_origine, "guild", None)
        if guilde_origine is not None:
            guildes = [guilde_origine]
    for guild in guildes:
        for text_channel in guild.text_channels:
            if text_channel.name.lower() == cible:
                return str(text_channel.id)
    return None


async def send_message_to_channel_handler(
    payload: dict,
    target: dict,
    *,
    discord_bot: Any,
    action_executor: Any,
) -> str:
    message = payload.get("message", "").strip()
    channel = payload.get("channel", "").strip()
    platform = payload.get("platform", target.get("platform", "discord")).lower()
    if not message:
        return "Message vide."
    if not channel:
        return "Salon cible non spécifié."

    if platform == "discord":
        channel_id = channel if channel.isdigit() else _salon_discord_par_nom(
            discord_bot, channel, target.get("channel_id"))
        if not channel_id:
            return f"Salon Discord '{channel}' introuvable."
        await action_executor.deliver(message, "discord", channel_id)
    elif platform == "twitch":
        await action_executor.deliver(message, "twitch", channel.lower())
    else:
        return f"Plateforme '{platform}' non reconnue."
    return f"Message envoyé dans {channel}."


async def enregistrer_actions(
    registry: Any,
    *,
    prompts: Any,
    emotion: Any,
    persona: Any,
    secondary_llm: Any,
    twitch_bot: Any,
    discord_bot: Any,
    action_executor: Any,
) -> None:
    """Déclare les quatre actions intégrées et lie leurs dépendances.

    Ici et pas dans `main.py` pour une raison précise : le CÂBLAGE est
    exactement ce qui n'était testé nulle part. Le défaut du 2026-08-23 était de
    cette famille — une fonction de module qui rangeait sa tâche dans une locale
    de `main()`, `NameError` au premier appel réel, invisible aux 5872 tests.

    Un test qui recopierait ces `partial()` de son côté prouverait que SA copie
    marche. En appelant cette fonction, il prouve que la vraie marche.

    Le rappel est lié UNE fois : `reminder` et `reminder_recurring` partagent le
    même handler, `ActionService.create()` routant vers l'un ou l'autre selon
    `schedule.type`.
    """
    from bot.intelligence.actions.registry import ActionDefinition

    rappel = partial(reminder_handler, prompts=prompts, emotion=emotion,
                     persona=persona, secondary_llm=secondary_llm)
    for nom, description in (
        ("reminder", "Envoyer un message de rappel"),
        ("reminder_recurring", "Envoyer un message de rappel récurrent"),
    ):
        await registry.register(nom, ActionDefinition(
            name=nom,
            description=description,
            parameters={"type": "object", "properties": {"message": {"type": "string"}}},
            handler=rappel,
        ))

    await registry.register("join_twitch_channel", ActionDefinition(
        name="join_twitch_channel",
        description="Rejoindre une chaîne Twitch en tant qu'invité",
        parameters={"type": "object",
                    "properties": {"channel": {"type": "string"}},
                    "required": ["channel"]},
        handler=partial(join_twitch_channel_handler, twitch_bot=twitch_bot),
    ))

    await registry.register("send_message_to_channel", ActionDefinition(
        name="send_message_to_channel",
        description="Envoyer un message dans un salon Discord ou une chaîne Twitch spécifique",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "channel": {"type": "string",
                            "description": "Nom du salon (#général) ou ID numérique "
                                           "Discord, ou nom de la chaîne Twitch"},
                "platform": {"type": "string", "enum": ["discord", "twitch"]},
            },
            "required": ["message", "channel"],
        },
        handler=partial(send_message_to_channel_handler,
                        discord_bot=discord_bot, action_executor=action_executor),
    ))
