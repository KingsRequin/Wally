# bot/main.py
import asyncio
import os
import signal
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from bot.core.llm.base import FALLBACK_RESPONSE

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


async def _run_discord(
    bot, token: str, *, max_attempts: int = 8, base_delay: float = 2.0
) -> None:
    """Login Discord avec retry, puis connexion websocket.

    Équivaut à ``bot.start(token)`` (login + connect), mais réessaie le *login*
    tant qu'il échoue sur une erreur réseau transitoire (panne DNS après un
    redémarrage de l'hôte, coupure passagère). Sans ça, un unique échec au boot
    laissait le process en zombie (le ``gather`` n'est pas supervisé).

    ``setup_hook`` étant appelé en fin de ``login()`` réussi, il ne tourne
    qu'une seule fois. Après ``max_attempts`` échecs, on relève l'exception :
    le process s'arrête et Docker (``restart: unless-stopped``) relance le
    conteneur. Un token invalide (``LoginFailure``, pas une ``OSError``) n'est
    pas réessayé et remonte immédiatement.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            await bot.login(token)
            break
        except OSError as e:
            if attempt >= max_attempts:
                logger.error(
                    "Discord: login impossible après {} tentatives ({}) — abandon",
                    attempt, e,
                )
                raise
            delay = min(base_delay * 2 ** (attempt - 1), 30.0)
            logger.warning(
                "Discord: échec réseau au login (tentative {}/{}): {} — "
                "nouvel essai dans {:.0f}s",
                attempt, max_attempts, e, delay,
            )
            await asyncio.sleep(delay)
    await bot.connect(reconnect=True)
    # `connect(reconnect=True)` REND LA MAIN sans lever quand discord.py juge la
    # fermeture définitive. Le `gather` ne se réveille alors pas — le process
    # restait vivant, adaptateur Discord mort, sans code de sortie, et rien ne le
    # détectait (pas de healthcheck sur le conteneur, et le watchdog sonde le
    # dashboard, qui répond 200). C'est la classe de bug de `fa66572`, dont le
    # correctif ne traitait que l'échec de *login*. On lève : le `gather` remonte
    # et Docker relance.
    raise RuntimeError("Discord: connexion terminée — le process doit redémarrer")


# Objets créés en cours de démarrage qu'il faut rendre même si l'arrêt survient
# avant que le `finally` de la boucle principale ne soit atteignable.
_AU_DEMARRAGE: dict = {}


async def main() -> None:
    setup_logging()
    logger.info("Wally starting...")

    from bot.config import Config
    from bot.db.database import Database
    from bot.bootstrap import build_core_services

    # ── Load config and database ──────────────────────────────────────────────
    config = Config.load(os.getenv("CONFIG_PATH", "config.yaml"))
    from bot.intelligence import identity as _identity
    _identity.set_identity(config.bot)
    logger.info(
        "Config loaded — primary: {provider}/{model}, secondary: {s_provider}/{s_model}, triggers: {triggers}",
        provider=config.llm.primary.provider,
        model=config.llm.primary.model,
        s_provider=config.llm.secondary.provider,
        s_model=config.llm.secondary.model,
        triggers=config.bot.trigger_names,
    )

    # Handler d'arrêt posé TÔT. Il n'était installé qu'après tout le démarrage
    # (validation réseau des tokens Twitch, init DB, `reload_all()`) : un
    # `docker stop` pendant ces quelques secondes retombait sur le SIGTERM par
    # défaut, qui tue le process net — exactement ce que le handler existe pour
    # éviter. Il est remplacé plus bas par celui qui prévient uvicorn.
    _startup_task = asyncio.current_task()
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(_sig, _startup_task.cancel)
        except (NotImplementedError, RuntimeError):
            pass

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
    rss_feed         = svc.rss_feed
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

    # Compteurs à la demande : partagés par les deux plateformes, et alimentés
    # par ce que Wally entend en vocal comme par le chat.
    from bot.core.tally import TallyService
    tally = TallyService(db)
    discord_bot.tally = tally

    # Paris sur l'issue d'une partie : le score cumulé vit d'un live à l'autre.
    from bot.core.predictions import PredictionService
    predictions = PredictionService(db)
    discord_bot.predictions = predictions

    # Citations du vocal : leur intérêt est de ressortir PLUS TARD, d'où la base.
    from bot.core.quotes import QuoteBook
    quotes = QuoteBook(db)
    discord_bot.quotes = quotes

    # Recherche dans l'historique : même racine que le logger, pour ne jamais
    # fouiller un autre répertoire que celui où les conversations sont écrites.
    from bot.core.history_search import HistorySearchService
    discord_bot.history_search = HistorySearchService(conv_log.root)
    logger.info("HistorySearchService initialized → {root}", root=str(conv_log.root))

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
    from bot.twitch.clip_announce import announce_clip
    from bot.twitch.events import register_events

    env_path = Path(__file__).parent.parent / ".env"
    token_manager = TwitchTokenManager.load(env_path)
    await token_manager.startup_validate()

    discord_token = os.getenv("DISCORD_TOKEN", "")

    twitch_bot = None
    twitch_api = None

    tasks = [_run_discord(discord_bot, discord_token)]
    if token_manager.bot_token:
        twitch_api = TwitchAPI(
            token_manager=token_manager,
            client_id=os.getenv("TWITCH_CLIENT_ID", ""),
            # Même repli que `events/__init__.py`, qui fait déjà
            # `TWITCH_BOT_ID or broadcaster_id`. Sans lui, `bot_id` valait "" ici
            # et la garde de `handlers.py` (`if bot_id and user_id == bot_id`)
            # était désactivée : les propres messages de Wally, revenus par
            # EventSub, traversaient `dispatch_command`, le compteur de visite,
            # le prélude et le `fact_extractor` — il se mémorisait lui-même.
            bot_id=os.getenv("TWITCH_BOT_ID", "").strip()
            or os.getenv("TWITCH_BROADCASTER_ID", ""),
            broadcaster_id=os.getenv("TWITCH_BROADCASTER_ID", ""),
        )
        twitch_bot = WallyTwitch(
            config, db, emotion, memory, primary_llm, secondary_llm, prompts, language,
            token_manager=token_manager,
            twitch_api=twitch_api,
            persona=persona,
        )
        # Repéré par `_demarrer()` : un arrêt avant `await gathered` doit tout de
        # même rendre les transports WebSocket à Twitch.
        _AU_DEMARRAGE["twitch"] = twitch_bot
        twitch_bot.fact_extractor = fact_extractor
        twitch_bot.web_search = web_search
        twitch_bot.scrape = scrape
        twitch_bot.apex_api = apex_api
        twitch_bot.reaction_tracker = reaction_tracker
        twitch_bot.conv_log = conv_log
        twitch_bot.tally = tally
        twitch_bot.predictions = predictions
        twitch_bot.quotes = quotes
        # Expose twitch_bot sur discord_bot avant setup_hook pour que CognitiveLoop
        # puisse rediriger ses SPEAKs vers Twitch quand le stream est live.
        discord_bot._twitch_bot = twitch_bot
        # Référence inverse : le chemin Twitch a besoin du narrateur d'overlay,
        # construit plus tard dans le setup_hook de Discord — d'où l'accès
        # paresseux via cette référence plutôt qu'une injection directe.
        twitch_bot.discord_bot = discord_bot
        register_events(twitch_bot)

        # StreamWatcher : unique poller du statut live du streamer (Azrael = home
        # broadcaster). Alimente twitch_bot._stream_info (on_poll) ET la cognition
        # de Wally — awareness always-on (prompt) + notification sur transition.
        from bot.core.stream_watcher import StreamWatcher

        def _on_stream_transition(old: dict, new: dict) -> None:
            loop = getattr(discord_bot, "cognitive_loop", None)
            bedroom = config.bot.bedroom_channel_id
            if loop is None or not bedroom:
                return
            name = os.getenv("TWITCH_BROADCASTER_LOGIN", "") or "Azrael"
            if new.get("live"):
                cat = new.get("category") or "un jeu inconnu"
                desc = f"{name} vient de lancer son live Twitch (jeu : {cat}"
                if title := new.get("title"):
                    desc += f", titre : « {title} »"
                desc += ")."
            else:
                desc = f"{name} vient de terminer son live Twitch."
            loop.notify_event(bedroom, desc, relevant=True)

        _stream_voice_tasks: set[asyncio.Task] = set()
        # Référence forte : l'annonce d'un clip attend que Twitch l'ait préparé,
        # une tâche détachée serait ramassée par le GC entre-temps.
        _clip_tasks: set[asyncio.Task] = set()

        def _on_stream_voice(old: dict, new: dict) -> None:
            """Auto-join du salon vocal du stream, en écoute seule.

            Séparé de `_on_stream_transition` : celui-ci ne fait rien sans salon
            « chambre » configuré, et l'écoute n'a pas à en dépendre.
            """
            vs = getattr(discord_bot, "voice_service", None)
            if vs is None:
                return
            went_live = bool(new.get("live")) and not bool(old.get("live"))
            ended = bool(old.get("live")) and not bool(new.get("live"))

            async def _go() -> None:
                try:
                    if went_live:
                        from bot.discord.voice.channel_memory import resolve_voice_channel_id

                        channel_id = await resolve_voice_channel_id(
                            db, config.bot.stream_voice_channel_id
                        )
                        # Le vocal de CE salon part désormais dans le live : il
                        # cesse d'être privé, on peut le remettre au prompt.
                        # Ouvert avant le retour anticipé ci-dessous — Wally est
                        # souvent déjà dans le salon quand le live démarre.
                        voice_transcript.open_broadcast(channel_id)
                        if vs.is_connected:
                            return          # déjà en vocal : on ne le déplace pas
                        if not channel_id:
                            return
                        channel = discord_bot.get_channel(channel_id)
                        if channel is None:
                            logger.warning("voice: salon de stream {c} introuvable", c=channel_id)
                            return
                        await vs.join(channel, listen_only=True, only_if_free=True)
                    elif ended:
                        # Le live s'arrête : le vocal redevient privé, et ce qui
                        # y a été dit sort du contexte écrit.
                        voice_transcript.close_broadcast()
                        if vs.is_connected and vs.listen_only:
                            # Seulement s'il est là POUR le stream : une conversation
                            # vocale en cours ne doit pas être coupée.
                            await vs.leave()
                except Exception as e:  # noqa: BLE001 — jamais bloquant
                    logger.warning("voice: auto-join/leave du stream a échoué: {e}", e=e)

            if went_live or ended:
                # Référence forte : une tâche détachée peut être ramassée par le
                # GC avant la fin du join.
                t = asyncio.create_task(_go())
                _stream_voice_tasks.add(t)
                t.add_done_callback(_stream_voice_tasks.discard)

        async def _clip_watch() -> None:
            """Signale les clips créés pendant le live.

            Twitch n'émet AUCUN événement EventSub à la création d'un clip : la
            seule voie est d'interroger l'API régulièrement. Deux minutes
            suffisent — un clip signalé deux minutes après reste un moment
            frais, et on ne martèle pas l'API pour rien.
            """
            from datetime import datetime, timedelta, timezone

            # Bornée : les plus vieux IDs sortent un par un plutôt que tous
            # d'un coup (cf. commentaire plus bas).
            seen: deque[str] = deque(maxlen=200)
            while True:
                await asyncio.sleep(120)
                try:
                    narrator = getattr(discord_bot, "overlay_narrator", None)
                    if narrator is None or not narrator.is_active():
                        continue
                    since = (datetime.now(timezone.utc) - timedelta(minutes=5))
                    clips = await twitch_bot.twitch_api.get_recent_clips(
                        since.strftime("%Y-%m-%dT%H:%M:%SZ")
                    )
                    fresh = []
                    for clip in clips:
                        cid = str(clip.get("id") or "")
                        if not cid or cid in seen:
                            continue
                        fresh.append(cid)
                        # Le clip est REJOUÉ, pas seulement annoncé : muet, il
                        # occupe l'écran le temps de la vidéo. C'est l'URL du
                        # FICHIER qui le rend lisible tout seul ; sans elle,
                        # `show_clip` retombe sur le player puis sur la carte.
                        # L'annonce attend que Twitch ait fini de préparer le
                        # clip, donc en tâche de fond : sinon la veille resterait
                        # bloquée et les clips suivants passeraient à la trappe.
                        t = asyncio.create_task(
                            announce_clip(narrator, twitch_bot.twitch_api, clip)
                        )
                        _clip_tasks.add(t)
                        t.add_done_callback(_clip_tasks.discard)
                    seen.extend(fresh)
                    # `deque(maxlen=...)` plutôt qu'un `set` vidé d'un coup : le
                    # `clear()` oubliait TOUT alors que la fenêtre d'interrogation
                    # est de 5 min — jusqu'à 20 clips étaient réannoncés au tour
                    # suivant. Ici les plus vieux sortent un par un.
                except Exception as e:  # noqa: BLE001 — jamais bloquant
                    logger.warning("veille des clips en erreur: {e}", e=e)

        async def _stream_voice_watch() -> None:
            """Ramène Wally en vocal tant qu'un live tourne sans lui.

            La transition live↔offline ne se produit qu'UNE fois : après un
            redémarrage — ou un crash — en plein stream, plus rien ne déclenche
            son arrivée. Ce veilleur compare l'état réel du live à l'état réel de
            la connexion, il ne suppose aucun événement. Il couvre donc aussi la
            déconnexion réseau et le kick.
            """
            while True:
                await asyncio.sleep(30)
                try:
                    vs = getattr(discord_bot, "voice_service", None)
                    if vs is None:
                        continue
                    live = bool((stream_watcher.status or {}).get("live"))
                    if not live:
                        # Fin du live : il retrouve le droit de revenir au suivant.
                        vs.listen_optout = False
                        # Filet de la transition « fin de live » : elle ne se
                        # produit qu'une fois, et un flux qui la rate laisserait
                        # la captation ouverte sur un vocal redevenu privé.
                        voice_transcript.close_broadcast()
                        continue
                    from bot.discord.voice.channel_memory import resolve_voice_channel_id

                    channel_id = await resolve_voice_channel_id(
                        db, config.bot.stream_voice_channel_id
                    )
                    # Résolu AVANT le test de connexion : après un redémarrage en
                    # plein stream, aucune transition n'a eu lieu, donc personne
                    # n'a ouvert la captation — et Wally est peut-être déjà dans
                    # le salon, auquel cas les deux tests suivants sortent d'ici.
                    voice_transcript.open_broadcast(channel_id)
                    if vs.is_connected or vs.listen_optout:
                        continue
                    if not channel_id:
                        continue
                    channel = discord_bot.get_channel(channel_id)
                    if channel is None:
                        continue        # cache Discord pas encore prêt : au tour suivant
                    logger.info("voice: live en cours sans Wally → retour en écoute")
                    await vs.join(channel, listen_only=True, only_if_free=True)
                except Exception as e:  # noqa: BLE001 — jamais bloquant
                    logger.warning("voice: veilleur de stream en erreur: {e}", e=e)

        # StreamFeed : flux PASSIF de ce qui se passe pendant le live (jeu, titre,
        # audience, raids/subs/bits, chat). Alimenté par le watcher et les events
        # Twitch, restitué au prompt comme contexte d'ambiance. Aucun réveil
        # cognitif, aucune prise de parole — Wally voit, il ne commente pas.
        from bot.core.stream_feed import StreamFeed
        from bot.core.voice_transcript import VoiceTranscriptFeed

        _streamer_name = os.getenv("TWITCH_BROADCASTER_LOGIN", "") or "Azrael_TTV"
        stream_feed = StreamFeed(streamer_name=_streamer_name)
        stream_feed.activate()
        twitch_bot.stream_feed = stream_feed

        # Conversation vocale : ce que Wally entend dans le salon vocal, remis au
        # prompt de ses réponses ÉCRITES. La captation ne s'ouvre que pendant le
        # live et sur le salon d'où l'on streame (`_on_stream_voice` plus bas) —
        # hors de là, un vocal reste privé.
        voice_transcript = VoiceTranscriptFeed()
        voice_transcript.activate()

        def _voice_present() -> list[str]:
            """Les présents en vocal, lus au moment du rendu.

            Paresseux à dessein : le `VoiceService` n'existe pas encore ici (il
            naît dans le `setup_hook` de Discord), et les gens entrent et
            sortent du salon pendant toute la soirée.
            """
            vs = getattr(discord_bot, "voice_service", None)
            return vs.members_names() if vs is not None and vs.is_connected else []

        voice_transcript.set_presence_source(_voice_present)

        stream_watcher = StreamWatcher(
            twitch_api,
            streamer_name=_streamer_name,
            on_transition=lambda old, new: (
                _on_stream_transition(old, new), _on_stream_voice(old, new)
            ),
            on_poll=lambda status: setattr(twitch_bot, "_stream_info", status),
            on_event=stream_feed.record,
        )
        stream_watcher.activate()

        # Suivi passif du compte Apex du streamer. Voie SANS retour vers
        # l'action, comme StreamFeed : Wally SAIT qu'Azraël est en partie, il
        # n'en parle que si on l'y amène. Rien hors live.
        # Les comptes qu'on connaît déjà : Azraël et son créateur n'ont pas à se
        # présenter. Ce qui a été déclaré en direct n'est jamais écrasé.
        if apex_api is not None:
            from bot.core.apex.seed import seed_known_accounts

            await seed_known_accounts(db, getattr(config.voice, "requesters", []))

        _apex_conf = getattr(config, "apex", None)
        if apex_api is not None and _apex_conf and _apex_conf.streamer_account:
            from bot.core.apex.history import ApexHistory
            from bot.core.apex.watcher import ApexWatcher

            # Historique des totaux : partagé entre la sonde du streamer et les
            # consultations manuelles (« +124 kills depuis la dernière fois »),
            # qui sont le seul historique des comptes non sondés.
            apex_history = ApexHistory(db)
            apex_api.history = apex_history
            # Quand le live a commencé : c'est ce qui donne son sens à « la
            # courbe de ce stream ». Hors live, `started_at` est vide et le
            # service retombe sur le dernier bloc de relevés.
            from bot.core.apex.periode import epoch_depuis_iso

            apex_api.debut_du_live = lambda: epoch_depuis_iso(
                twitch_bot._stream_info.get("started_at")
                if twitch_bot._stream_info.get("live") else None
            )

            apex_watcher = ApexWatcher(
                apex_api,
                account=(_apex_conf.streamer_account, _apex_conf.streamer_platform),
                is_live=lambda: bool(twitch_bot._stream_info.get("live")),
                # Identité du live : le point de départ rangé en base n'en portait
                # aucune, donc un redémarrage entre deux lives faisait cumuler les
                # deux sessions dans les « +N kills depuis le début du live ».
                live_id=lambda: str(twitch_bot._stream_info.get("started_at") or ""),
                db=db,
                history=apex_history,
            )
            apex_watcher.activate()
            _apex_task = asyncio.create_task(apex_watcher.run())
            _stream_voice_tasks.add(_apex_task)
            _apex_task.add_done_callback(_stream_voice_tasks.discard)
            twitch_bot.apex_watcher = apex_watcher
            logger.info("ApexWatcher démarré pour {a}", a=_apex_conf.streamer_account)
        # Rattrapage permanent : redémarrage en plein live, crash, kick.
        _watch_task = asyncio.create_task(_stream_voice_watch())
        _stream_voice_tasks.add(_watch_task)
        _watch_task.add_done_callback(_stream_voice_tasks.discard)
        _clip_task = asyncio.create_task(_clip_watch())
        _stream_voice_tasks.add(_clip_task)
        _clip_task.add_done_callback(_stream_voice_tasks.discard)
        twitch_bot.stream_watcher = stream_watcher

        # Overlay de stream : les événements du live (raid, sub, changement de
        # jeu…) deviennent des bulles. Le hook de StreamFeed est synchrone alors
        # que la réaction demande un appel LLM — d'où la tâche détachée, avec
        # référence forte pour que le GC ne l'annule pas en vol.
        _overlay_event_tasks: set[asyncio.Task] = set()

        def _narrate_stream_event(description: str, kind: str = "") -> None:
            narrator = getattr(discord_bot, "overlay_narrator", None)
            if narrator is None:
                return
            task = asyncio.create_task(narrator.on_stream_event(description, kind=kind))
            _overlay_event_tasks.add(task)
            task.add_done_callback(_overlay_event_tasks.discard)

        stream_feed.set_observer(_narrate_stream_event)

        tasks.append(twitch_bot.start())
        tasks.append(stream_watcher.run())
        logger.info(
            "Twitch adapter + StreamWatcher + StreamFeed configured and included in gather"
        )
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
            # `complete()` ne lève pas : il rend FALLBACK_RESPONSE. Sans ce
            # test, l'utilisateur recevait « Je rencontre un problème
            # technique » à la place de son rappel — et la tâche `once`, elle,
            # était consommée : le rappel ne repartait jamais.
            if not reply or reply == FALLBACK_RESPONSE:
                logger.warning("Rappel : génération en repli, on envoie le texte demandé")
                reply = raw_msg
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
                # Recherche BORNÉE au serveur d'où vient la tâche. Elle balayait
                # `discord_bot.guilds` en entier : la permission était validée
                # sur le serveur d'origine, puis le message pouvait partir dans
                # n'importe quel salon de n'importe quel autre serveur portant
                # le même nom. Combiné à l'envoi sans `allowed_mentions`, cela
                # permettait un ping de masse cross-serveur.
                ch_name = channel.lstrip("#").lower()
                guildes = discord_bot.guilds
                origine = target.get("channel_id")
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
    rss_feed.start(shared_scheduler)
    await action_scheduler.reload_all()
    shared_scheduler.start()
    logger.info("Shared scheduler started (journal + actions + rss)")

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
        apex=apex_api,
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

    # `docker stop` envoie SIGTERM, dont le comportement par défaut tue le process
    # sur-le-champ : le `finally` ci-dessous ne s'exécutait jamais et l'écriture en
    # cours restait à moitié faite (lignes de log JSONL terminées en NUL bytes).
    # On le convertit en annulation asyncio pour fermer proprement.
    gathered = asyncio.gather(*tasks)

    def _request_stop() -> None:
        # Prévenir uvicorn avant d'annuler. Note : `cancel()` étant synchrone, il
        # n'a de toute façon pas le temps de lire le drapeau — starlette logue
        # donc un CancelledError depuis sa tâche `lifespan` à chaque arrêt. C'est
        # bénin (rien n'est perdu, aucun warning) ; le supprimer imposerait un
        # arrêt gracieux orchestré avec attente et timeout. Ne pas y revenir.
        dashboard_server.should_exit = True
        gathered.cancel()

    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(_sig, _request_stop)
        except (NotImplementedError, RuntimeError):  # plateforme sans support
            logger.warning("Arrêt propre indisponible pour le signal {s}", s=_sig)

    try:
        await gathered
    except asyncio.CancelledError:
        logger.info("Signal d'arrêt reçu — fermeture propre en cours")
    finally:
        # Rendre les transports WebSocket à Twitch : la limite est de 3 par
        # utilisateur, et un process tué sans fermeture les laisse occupés — deux
        # redémarrages rapprochés suffisaient alors à faire échouer les dernières
        # souscriptions (429 « websocket transports limit exceeded »).
        if twitch_bot is not None:
            try:
                from bot.twitch.events import close_eventsub_client
                await close_eventsub_client(twitch_bot)
            except Exception as exc:  # noqa: BLE001 — ne jamais bloquer l'arrêt
                logger.warning("Fermeture EventSub échouée: {e}", e=exc)
        dashboard_server.should_exit = True  # idempotent : couvre l'arrêt hors signal

        # Fermer les clients eux-mêmes, sinon leurs threads survivent à la boucle :
        # le heartbeat de discord.py appelait `loop.call_soon_threadsafe` après
        # fermeture (« RuntimeError: Event loop is closed » + coroutine jamais
        # attendue à chaque arrêt).
        for label, client in (("Discord", discord_bot), ("Twitch", twitch_bot)):
            if client is None:
                continue
            try:
                await client.close()
            except AttributeError as exc:
                # twitchio fait `self._keeper.cancel()` sans garde : `_keeper` est
                # None tant que la connexion IRC n'a pas été pleinement établie.
                # Bénin — EventSub est déjà fermé juste au-dessus.
                logger.debug("Fermeture {c} partielle: {e}", c=label, e=exc)
            except Exception as exc:  # noqa: BLE001 — ne jamais bloquer l'arrêt
                logger.warning("Fermeture {c} échouée: {e}", c=label, e=exc)

        if update_checker:
            await update_checker.stop()
        # APScheduler continuait de déclencher ses jobs (journal, actions, RSS)
        # pendant que Discord et Twitch se fermaient, sur une base qu'on
        # s'apprête à fermer. `wait=False` : on n'attend pas un job en cours,
        # l'arrêt est déjà en train de tout couper.
        try:
            if shared_scheduler.running:
                shared_scheduler.shutdown(wait=False)
        except Exception as exc:  # noqa: BLE001 — ne jamais bloquer l'arrêt
            logger.warning("Arrêt du scheduler échoué: {e}", e=exc)
        await conv_log.stop()
        # L'état émotionnel attend dans un debounce de 5 s, sans cesse repoussé
        # tant que des messages arrivent. Rien ne le forçait à l'arrêt : la tâche
        # était simplement annulée avec la boucle, et tout ce qui n'avait pas eu
        # sa fenêtre de calme était perdu.
        try:
            await emotion.flush()
        except Exception as exc:  # noqa: BLE001 — ne jamais bloquer l'arrêt
            logger.warning("Flush émotionnel échoué: {e}", e=exc)
        # Dernier : tout le reste écrit encore en base jusqu'ici.
        try:
            await db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fermeture de la base échouée: {e}", e=exc)
        logger.info("Arrêt terminé proprement")


async def _demarrer() -> None:
    """Enveloppe `main()` pour rendre les transports Twitch si l'arrêt tombe TÔT.

    Le handler d'arrêt précoce annule la tâche de démarrage, mais le `finally`
    qui rend les WebSockets EventSub vit sous le `await gathered` — inatteignable
    tant que le démarrage n'est pas fini (validation des tokens Twitch, init DB,
    `reload_all()`). Un `docker stop` dans cette fenêtre laissait donc les
    transports occupés : la limite est de 3 par utilisateur, et deux
    redémarrages rapprochés suffisaient à faire échouer les souscriptions
    (429 « websocket transports limit exceeded », vécu le 2026-08-05).
    """
    try:
        await main()
    except asyncio.CancelledError:
        twitch_bot = _AU_DEMARRAGE.get("twitch")
        if twitch_bot is not None:
            logger.info("Arrêt pendant le démarrage — on rend les transports EventSub")
            try:
                from bot.twitch.events import close_eventsub_client
                await close_eventsub_client(twitch_bot)
            except Exception as exc:  # noqa: BLE001 — ne jamais bloquer l'arrêt
                logger.warning("Fermeture EventSub au démarrage échouée: {e}", e=exc)
        raise


if __name__ == "__main__":
    asyncio.run(_demarrer())
