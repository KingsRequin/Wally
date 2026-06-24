# bot/main.py
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "<level>{message}</level>"
        ),
    )

    log_dir = Path("logs") / datetime.now().strftime("%Y-%m-%d")
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_dir / "app.log"),
        rotation="100 MB",
        retention="30 days",
        level="INFO",
        encoding="utf-8",
        format="{time:HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    )
    logger.add(
        str(log_dir / "error.log"),
        rotation="100 MB",
        retention="30 days",
        level="ERROR",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    )


async def main() -> None:
    setup_logging()
    logger.info("Wally starting...")

    from bot.config import Config
    from bot.db.database import Database
    from bot.bootstrap import build_core_services

    # ── Load config and database ──────────────────────────────────────────────
    config = Config.load(os.getenv("CONFIG_PATH", "config.yaml"))
    logger.info(
        "Config loaded — primary: {provider}/{model}, secondary: {s_provider}/{s_model}, triggers: {triggers}",
        provider=config.llm.primary.provider,
        model=config.llm.primary.model,
        s_provider=config.llm.secondary.provider,
        s_model=config.llm.secondary.model,
        triggers=config.bot.trigger_names,
    )

    db_path = os.getenv("DB_PATH", "data/wally.db")
    db = await Database.create(db_path)
    logger.info("Database ready at {path}", path=db_path)
    await db.cleanup_old_emotion_history(days=30)
    logger.info("Old emotion history cleaned up")

    # ── Conversation logger ───────────────────────────────────────────────────
    from bot.core.conversation_log import ConversationLogger
    conv_log = ConversationLogger()
    conv_log.start()

    # ── Core services ─────────────────────────────────────────────────────────
    svc = await build_core_services(config, db)
    emotion          = svc.emotion
    memory           = svc.memory
    primary_llm      = svc.primary_llm
    secondary_llm    = svc.secondary_llm
    image_client     = svc.image_client
    vision           = svc.vision
    prompts          = svc.prompts
    language         = svc.language
    persona          = svc.persona
    journal          = svc.journal
    action_registry  = svc.action_registry
    action_executor  = svc.action_executor
    action_scheduler = svc.action_scheduler
    action_service   = svc.action_service
    fact_extractor   = svc.fact_extractor
    reaction_tracker = svc.reaction_tracker
    web_search       = svc.web_search
    scrape           = svc.scrape
    apex_api         = svc.apex_api
    shared_scheduler = svc.shared_scheduler

    from bot.intelligence.actions import ActionDefinition

    # ── Discord adapter ───────────────────────────────────────────────────────
    from bot.discord.bot import WallyDiscord

    discord_bot = WallyDiscord(config, db, emotion, memory, primary_llm, secondary_llm, image_client, prompts, language, persona)
    discord_bot.journal = journal
    discord_bot.fact_extractor = fact_extractor
    discord_bot.web_search = web_search
    discord_bot.scrape = scrape
    discord_bot.apex_api = apex_api
    discord_bot.vision = vision
    discord_bot.reaction_tracker = reaction_tracker
    discord_bot.conv_log = conv_log
    fact_extractor.conv_log = conv_log

    # ── UpdateChecker ─────────────────────────────────────────────────────────
    update_checker = None
    if config.bot.update_image:
        from bot.core.update_checker import UpdateChecker
        update_checker = UpdateChecker(config.bot.update_image)
        logger.info("UpdateChecker configured — image={}", config.bot.update_image)
    else:
        logger.info("UpdateChecker disabled — set bot.update_image in config.yaml to enable")
    discord_bot.update_checker = update_checker

    @discord_bot.event
    async def on_message(message):
        from bot.discord.handlers import handle_message
        await handle_message(discord_bot, message)

    async def journal_send_cb(text: str, file=None) -> None:
        channel_id = config.bot.journal_channel_id
        if channel_id:
            ch = discord_bot.get_channel(channel_id)
            if ch:
                if file and not text:
                    import discord as _discord
                    await ch.send(file=_discord.File(file, filename="emotions_jour.png"))
                elif file:
                    import discord as _discord
                    await ch.send(text, file=_discord.File(file, filename="emotions_jour.png"))
                else:
                    await ch.send(text)

    journal.set_send_callback(journal_send_cb)

    async def journal_history_cb() -> list[dict]:
        """Lit l'historique de tous les canaux Discord autorisés depuis minuit."""
        from bot.discord.handlers import _is_channel_allowed, _author_label
        from datetime import datetime
        from zoneinfo import ZoneInfo
        midnight = datetime.now(ZoneInfo("Europe/Paris")).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        messages: list[dict] = []
        if not discord_bot.guilds:
            logger.warning("Journal history callback: discord_bot.guilds is empty, skipping")
            return []
        for guild in discord_bot.guilds:
            for channel in guild.text_channels:
                if not _is_channel_allowed(config, channel.id):
                    continue
                try:
                    async for msg in channel.history(after=midnight, limit=2000):
                        if not msg.content.strip():
                            continue
                        # Include all messages (humans + Wally) — journal reflects the full conversation
                        messages.append({
                            "author": _author_label(msg.author),
                            "content": msg.content,
                            "timestamp": msg.created_at.timestamp(),
                        })
                except Exception as exc:
                    logger.debug(
                        "Journal history: cannot read channel {ch}: {e}",
                        ch=channel.id, e=exc,
                    )
        messages.sort(key=lambda m: m["timestamp"])
        return messages

    journal.set_history_callback(journal_history_cb)
    logger.info("Discord adapter configured")

    # ── Twitch adapter ────────────────────────────────────────────────────────
    from bot.twitch.bot import WallyTwitch
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.twitch.events import register_events

    env_path = Path(__file__).parent.parent / ".env"
    token_manager = TwitchTokenManager.load(env_path)
    await token_manager.startup_validate()

    discord_token = os.getenv("DISCORD_TOKEN", "")

    twitch_bot = None
    twitch_api = None

    tasks = [discord_bot.start(discord_token)]
    if token_manager.bot_token:
        twitch_api = TwitchAPI(
            token_manager=token_manager,
            client_id=os.getenv("TWITCH_CLIENT_ID", ""),
            bot_id=os.getenv("TWITCH_BOT_ID", ""),
            broadcaster_id=os.getenv("TWITCH_BROADCASTER_ID", ""),
        )
        twitch_bot = WallyTwitch(
            config, db, emotion, memory, primary_llm, secondary_llm, prompts, language,
            token_manager=token_manager,
            twitch_api=twitch_api,
            persona=persona,
        )
        twitch_bot.fact_extractor = fact_extractor
        twitch_bot.web_search = web_search
        twitch_bot.scrape = scrape
        twitch_bot.apex_api = apex_api
        twitch_bot.reaction_tracker = reaction_tracker
        twitch_bot.conv_log = conv_log
        # Expose twitch_bot sur discord_bot avant setup_hook pour que CognitiveLoop
        # puisse rediriger ses SPEAKs vers Twitch quand le stream est live.
        discord_bot._twitch_bot = twitch_bot
        register_events(twitch_bot)
        tasks.append(twitch_bot.start())
        logger.info("Twitch adapter configured and included in gather")
    else:
        logger.warning(
            "Twitch bot skipped — set BOT_ACCESS_TOKEN (or BOT_REFRESH_TOKEN + "
            "TWITCH_CLIENT_ID/SECRET) to enable"
        )

    # ── Action service wiring ────────────────────────────────────────────────
    discord_bot.action_service = action_service
    if twitch_bot is not None:
        twitch_bot.action_service = action_service

    # Late injection of bots into executor (twitch_bot may be None)
    action_executor.set_bots(discord_bot, twitch_bot)

    # Register built-in actions
    async def _reminder_handler(payload: dict, target: dict) -> str:
        raw_msg = payload.get("message", "Rappel!")
        creator_id = target.get("creator_id")
        platform = target.get("platform", "")

        # Build a full system prompt so the LLM speaks in Wally's voice + current mood
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
                f"[INSTRUCTION SYSTÈME — NE PAS CITER]\n"
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
        except Exception as e:
            logger.warning("Reminder LLM generation failed, using raw message: {}", e)
            reply = raw_msg

        if platform == "discord" and creator_id:
            return f"<@{creator_id}> {reply}"
        return reply

    await action_registry.register("reminder", ActionDefinition(
        name="reminder",
        description="Envoyer un message de rappel",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        handler=_reminder_handler,
    ))
    await action_registry.register("reminder_recurring", ActionDefinition(
        name="reminder_recurring",
        description="Envoyer un message de rappel récurrent",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        handler=_reminder_handler,
    ))

    async def _join_twitch_channel_handler(payload: dict, target: dict) -> str:
        channel = payload.get("channel", "").lower().strip()
        if not channel:
            return "Nom de chaîne manquant."
        if twitch_bot is None:
            return "Twitch non disponible."
        result = await twitch_bot.add_guest_channel(channel)
        if result == "already_added":
            return f"Je suis déjà dans la chaîne {channel}."
        if result is None:
            return f"Impossible de rejoindre {channel} — chaîne introuvable ou API indisponible."
        return f"J'ai rejoint la chaîne {channel}."

    await action_registry.register("join_twitch_channel", ActionDefinition(
        name="join_twitch_channel",
        description="Rejoindre une chaîne Twitch en tant qu'invité",
        parameters={"type": "object", "properties": {"channel": {"type": "string"}}, "required": ["channel"]},
        handler=_join_twitch_channel_handler,
    ))

    async def _send_message_to_channel_handler(payload: dict, target: dict) -> str:
        message = payload.get("message", "").strip()
        channel = payload.get("channel", "").strip()
        platform = payload.get("platform", target.get("platform", "discord")).lower()
        if not message:
            return "Message vide."
        if not channel:
            return "Salon cible non spécifié."
        if platform == "discord":
            channel_id = None
            if channel.isdigit():
                channel_id = channel
            else:
                ch_name = channel.lstrip("#").lower()
                for guild in discord_bot.guilds:
                    for text_channel in guild.text_channels:
                        if text_channel.name.lower() == ch_name:
                            channel_id = str(text_channel.id)
                            break
                    if channel_id:
                        break
            if not channel_id:
                return f"Salon Discord '{channel}' introuvable."
            await action_executor.deliver(message, "discord", channel_id)
        elif platform == "twitch":
            await action_executor.deliver(message, "twitch", channel.lower())
        else:
            return f"Plateforme '{platform}' non reconnue."
        return f"Message envoyé dans {channel}."

    await action_registry.register("send_message_to_channel", ActionDefinition(
        name="send_message_to_channel",
        description="Envoyer un message dans un salon Discord ou une chaîne Twitch spécifique",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "channel": {"type": "string", "description": "Nom du salon (#général) ou ID numérique Discord, ou nom de la chaîne Twitch"},
                "platform": {"type": "string", "enum": ["discord", "twitch"]},
            },
            "required": ["message", "channel"],
        },
        handler=_send_message_to_channel_handler,
    ))

    journal.start(scheduler=shared_scheduler)
    await action_scheduler.reload_all()
    shared_scheduler.start()
    logger.info("Shared scheduler started (journal + actions)")

    # ── Dashboard ─────────────────────────────────────────────────────────────
    from bot.dashboard.app import create_dashboard_app
    from bot.dashboard.state import AppState
    import uvicorn

    _twitch_bot_ref = twitch_bot if token_manager.bot_token else None
    _twitch_api_ref = twitch_api if token_manager.bot_token else None

    from bot.core.notifications import NotificationService
    notification_service = NotificationService(config, discord_bot)

    dashboard_state = AppState(
        config=config,
        db=db,
        emotion=emotion,
        memory=memory,
        persona=persona,
        primary_llm=primary_llm,
        secondary_llm=secondary_llm,
        image_client=image_client,
        token_manager=token_manager,
        twitch_api=_twitch_api_ref,
        discord_bot=discord_bot,
        twitch_bot=_twitch_bot_ref,
        prompts=prompts,
        fact_extractor=fact_extractor,
        notifications=notification_service,
        action_service=action_service,
        update_checker=update_checker,
        cognitive_feed=getattr(discord_bot, "cognitive_feed", None),
    )

    dashboard_state.overlay_visible = config.web_chat.overlay_visible

    if update_checker:
        update_checker.start()

    discord_bot.dashboard_state = dashboard_state
    if _twitch_bot_ref is not None:
        _twitch_bot_ref.dashboard_state = dashboard_state

    dashboard_app = create_dashboard_app(dashboard_state)
    dashboard_server = uvicorn.Server(
        uvicorn.Config(
            dashboard_app,
            host="0.0.0.0",
            port=8080,
            log_config=None,   # loguru gère les logs — désactiver uvicorn's logging
            access_log=False,
        )
    )
    tasks.append(dashboard_server.serve())
    logger.info("Dashboard server added to gather on port 8080")

    try:
        await asyncio.gather(*tasks)
    finally:
        if update_checker:
            await update_checker.stop()
        await conv_log.stop()


if __name__ == "__main__":
    asyncio.run(main())
