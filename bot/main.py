# bot/main.py
import asyncio
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from bot.intelligence.actions.handlers import enregistrer_actions
from bot.core.music import MusicService
from bot.discord.journal_feed import JournalDiscord

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
                    "Discord: login impossible après {} tentatives ({!r}) — abandon",
                    attempt, e,
                )
                raise
            delay = min(base_delay * 2 ** (attempt - 1), 30.0)
            logger.warning(
                "Discord: échec réseau au login (tentative {}/{}): {!r} — "
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

# Tâches de fond lancées par les fonctions de MODULE (hors `main()`). Le set de
# `main()` est une variable locale : y toucher depuis ici lève un `NameError`.
# Sans référence forte, asyncio ramasse la tâche en plein vol.
_TACHES_MODULE: set[asyncio.Task] = set()


def _afficher_bilan_partie(discord_bot, bilan: dict) -> None:
    """Pousse le bilan d'une partie Apex sur l'overlay, si un écran écoute.

    Silencieux quand le narrateur n'est pas là (Discord pas encore connecté) :
    une partie non affichée n'est pas une panne, et lever ici casserait la sonde.
    """
    narrateur = getattr(discord_bot, "overlay_narrator", None)
    if narrateur is None:
        return
    narrateur.show_apex_kills(partie=bilan.get("partie"),
                              total=bilan.get("total") or 0,
                              parties=bilan.get("parties") or 0,
                              rp=bilan.get("rp"))


def _solder_pari_sur_partie(twitch_bot, bilan: dict) -> None:
    """Résout le pari en cours avec le bilan de la partie (§13).

    Lancé en tâche de fond : la sonde Apex est synchrone à cet endroit, et
    l'attendre retarderait le relevé suivant. Une prédiction sans pari ouvert ne
    fait rien du tout.
    """
    suivi = getattr(twitch_bot, "prediction_kills", None)
    if suivi is None or suivi.en_cours is None:
        return
    tache = asyncio.create_task(suivi.sur_bilan(twitch_bot, bilan))
    _TACHES_MODULE.add(tache)
    tache.add_done_callback(_TACHES_MODULE.discard)


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
    # La musique d'Azraël (§10). Créé ici, au même endroit que les autres
    # services partagés : la route de l'extension le nourrit, l'outil du chat
    # Twitch le lit — deux instances auraient divergé au premier battement.
    music_service    = MusicService()


    # ── Discord adapter ───────────────────────────────────────────────────────
    from bot.discord.bot import WallyDiscord

    discord_bot = WallyDiscord(config, db, emotion, memory, primary_llm, secondary_llm, image_client, prompts, language, persona)
    discord_bot.journal = journal
    # La MÊME instance que côté Twitch : la route de l'extension la nourrit, les
    # deux adaptateurs la lisent. Ici pour la LECTURE seule — « c'est quoi la
    # musique ? », que le §10 veut ouverte à tout le monde ; le pilotage exige un
    # badge de modérateur qu'un salon Discord ne porte pas, et `pilotable=False`
    # le dit à l'exécution. Sans cette ligne, `handlers.py` ne proposait tout
    # simplement JAMAIS l'outil sur Discord, alors que `CAPABILITIES.md` promet
    # de savoir répondre à qui demande.
    discord_bot.music = music_service
    discord_bot.fact_extractor = fact_extractor
    discord_bot.web_search = web_search
    discord_bot.scrape = scrape
    discord_bot.apex_api = apex_api
    discord_bot.vision = vision
    discord_bot.reaction_tracker = reaction_tracker
    discord_bot.conv_log = conv_log
    fact_extractor.conv_log = conv_log

    # Le morceau d'Azraël qui change s'affiche sans qu'on le demande (arbitré
    # avec l'owner le 2026-08-19) — en plus du chemin « c'est quoi la
    # musique ? », qui garde ses propres règles. Le narrateur est relu À CHAQUE
    # ANNONCE et non capturé ici : il naît avec la connexion Discord, bien après
    # ce câblage. Les refus (hors live, même morceau qu'à l'écran) sont les
    # siens, on ne les redouble pas.
    def _morceau_a_l_ecran(morceau: dict) -> None:
        narrateur = getattr(discord_bot, "overlay_narrator", None)
        if narrateur is None:
            return
        narrateur.show_music(morceau.get("titre") or "",
                             morceau.get("artiste") or "",
                             joue=bool(morceau.get("joue")),
                             url=morceau.get("url") or "")

    music_service.ecouter_les_morceaux(_morceau_a_l_ecran)

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

    # Les deux tuyaux Discord du journal — ce qu'il lit, ce qu'il publie.
    # Sortis de `main()` le 2026-08-23 : ils portent la borne à minuit HEURE
    # DE PARIS (l'hôte est en UTC) et la tolérance aux salons illisibles, que
    # rien ne vérifiait. Voir `tests/test_journal_feed.py`.
    JournalDiscord(discord_bot=discord_bot, config=config).brancher(journal)

    logger.info("Discord adapter configured")

    # ── Twitch adapter ────────────────────────────────────────────────────────
    from bot.twitch.bot import WallyTwitch
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.twitch.clip_announce import VeilleDesClips
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
        # La route de l'extension le NOURRIT, l'outil du chat le LIT : une
        # seconde instance aurait divergé au premier battement, et Wally aurait
        # répondu « je ne sais pas » à côté d'un service plein.
        twitch_bot.music = music_service
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
            # AVANT le garde ci-dessous : la fin du live le touche même sans
            # salon « chambre » configuré. C'est la leçon déjà tirée pour
            # `PresenceDeStream`, qui a dû être séparée pour la même raison.
            if bool(old.get("live")) and not bool(new.get("live")):
                emotion.world_event("stream_ended", platform="twitch")

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

        # Twitch n'émet aucun événement à la création d'un clip : on interroge.
        # Sortie de `main()` le 2026-08-23 avec ses deux arbitrages payés en
        # prod — mémoire BORNÉE des clips déjà vus, annonce en tâche de fond.
        # Voir `tests/test_clip_watch.py`.
        veille_clips = VeilleDesClips(discord_bot=discord_bot, twitch_bot=twitch_bot)

        # StreamFeed : flux PASSIF de ce qui se passe pendant le live (jeu, titre,
        # audience, raids/subs/bits, chat). Alimenté par le watcher et les events
        # Twitch, restitué au prompt comme contexte d'ambiance. Aucun réveil
        # cognitif, aucune prise de parole — Wally voit, il ne commente pas.
        from bot.core.stream_feed import StreamFeed
        from bot.core.voice_transcript import VoiceTranscriptFeed
        from bot.discord.voice.stream_presence import PresenceDeStream

        _streamer_name = os.getenv("TWITCH_BROADCASTER_LOGIN", "") or "Azrael_TTV"
        stream_feed = StreamFeed(streamer_name=_streamer_name)
        stream_feed.activate()
        twitch_bot.stream_feed = stream_feed

        # Conversation vocale : ce que Wally entend dans le salon vocal, remis au
        # prompt de ses réponses ÉCRITES. La captation ne s'ouvre que pendant le
        # live et sur le salon d'où l'on streame (`PresenceDeStream` plus bas) —
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

        # Qui rejoint le vocal du live, et QUAND la captation s'ouvre. Sorti de
        # `main()` le 2026-08-23 : c'étaient deux closures de plus dans une
        # fonction de mille lignes, donc du comportement qu'aucun test ne
        # pouvait atteindre — alors que c'est lui qui décide si un vocal privé
        # peut ressortir à l'écrit. Voir `tests/test_stream_presence.py`.
        presence_stream = PresenceDeStream(
            discord_bot=discord_bot, db=db, config=config,
            voice_transcript=voice_transcript,
        )

        def _transition_du_stream(old: dict, new: dict) -> None:
            """Les DEUX conséquences d'une bascule live↔offline.

            Une `lambda` ne tient qu'une expression : l'enchaînement se faisait
            par un tuple `(a(), b())`, construit pour être aussitôt jeté. mypy
            le signalait — « ne retourne rien » — et le lecteur devait deviner
            que cette virgule était un enchaînement, pas une valeur.
            """
            _on_stream_transition(old, new)
            presence_stream.on_transition(old, new)

        stream_watcher = StreamWatcher(
            twitch_api,
            streamer_name=_streamer_name,
            on_transition=_transition_du_stream,
            on_poll=lambda status: setattr(twitch_bot, "_stream_info", status),
            on_event=stream_feed.record,
        )
        # Après coup : le watcher se construit en prenant la présence en
        # paramètre, l'un des deux doit bien naître en premier.
        presence_stream.brancher_watcher(stream_watcher)
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

            def _fin_de_partie_apex(bilan: dict) -> None:
                """Ce qu'une fin de partie déclenche : l'écran, puis le pari.

                Le bilan part TOUT SEUL à l'écran (choix de l'owner), et le
                même bilan solde le pari en cours s'il y en a un. Le narrateur
                est résolu au moment de l'appel : il naît dans le `setup_hook`
                de Discord, donc APRÈS ce watcher.
                """
                _afficher_bilan_partie(discord_bot, bilan)
                _solder_pari_sur_partie(twitch_bot, bilan)

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
                # Le bilan de fin de partie part TOUT SEUL à l'écran (choix de
                # l'owner). Le narrateur est résolu au moment de l'appel : il
                # naît dans le setup_hook de Discord, donc APRÈS ce watcher.
                on_partie=_fin_de_partie_apex,
            )
            apex_watcher.activate()
            _apex_task = asyncio.create_task(apex_watcher.run())
            _stream_voice_tasks.add(_apex_task)
            _apex_task.add_done_callback(_stream_voice_tasks.discard)
            twitch_bot.apex_watcher = apex_watcher
            logger.info("ApexWatcher démarré pour {a}", a=_apex_conf.streamer_account)

        # Duel Apex payé en points de chaîne. Câblé ICI et non dans
        # `bootstrap.py` : il lui faut le bot Twitch (API de chat pour les
        # annonces, remboursement des redemptions), qui n'existe qu'à ce stade —
        # même raison que l'`ApexWatcher` juste au-dessus.
        _duel_conf = getattr(_apex_conf, "duel", None) if _apex_conf else None
        # `available` et pas seulement « le service existe » : sans clé Apex,
        # chaque relevé échoue et le duel n'est jamais mesurable — mais la
        # récompense, elle, serait bel et bien créée sur la chaîne.
        if (apex_api is not None and apex_api.available and _apex_conf is not None
                and _duel_conf is not None and _duel_conf.active):
            from bot.core.apex.duel_runner import DuelRunner, armer_le_duel
            from bot.core.apex.seed import uid_declare
            from bot.twitch.duel_announce import DuelAnnonceur

            _azrael_uid = uid_declare(
                getattr(config.voice, "requesters", []), _apex_conf.streamer_account
            )
            if not _azrael_uid:
                logger.warning(
                    "Duel Apex indisponible : aucun uid déclaré pour {a} dans "
                    "voice.requesters (apex_uid)", a=_apex_conf.streamer_account,
                )
            else:
                try:
                    # LE client Apex, celui du service — pas un second. Le
                    # limiteur de débit (`_MIN_INTERVAL`, 5 req/s mesurées) vit
                    # PAR INSTANCE : deux clients porteraient le plafond réel à
                    # 10 req/s et les deux prendraient un 429, le duel ratant
                    # ses relevés en silence. Le seul intérêt d'un client dédié
                    # — ne pas peupler le cache partagé — est déjà obtenu par le
                    # `sans_cache=True` que `_profil()` passe à chaque relevé.
                    # `_client` est privé faute d'accesseur public sur le
                    # service, hors périmètre de cette tâche.
                    _duel_runner = DuelRunner(
                        client=apex_api._client,
                        db=db,
                        api=twitch_bot.twitch_api,
                        annoncer=DuelAnnonceur(twitch_bot,
                                               channel=_streamer_name.lower(),
                                               # Le mode annoncé vient de la
                                               # config, et de là seulement : le
                                               # code le collait en dur ET le
                                               # registre persona le répétait.
                                               mode_jeu=_duel_conf.mode_jeu),
                        # La trace de fin de duel (§11 ter) : une revanche a
                        # besoin d'un précédent, et le journal quotidien lit
                        # déjà la mémoire.
                        memory=memory,
                        azrael_uid=_azrael_uid,
                        plateforme=_apex_conf.streamer_platform,
                        cadence_s=float(_duel_conf.cadence_s),
                        manches=int(_duel_conf.manches),
                        attente_squad_s=float(_duel_conf.attente_squad_min) * 60,
                        plafond_kills_manche=int(_duel_conf.plafond_kills_manche),
                        # Bornée par le runner : 39 s entre un retour au lobby
                        # et le lancement suivant est une contrainte dure, et le
                        # debounce anti-hoquet en consomme déjà une part.
                        marge_lobby_s=float(_duel_conf.marge_lobby_s),
                        api_muette_max_s=float(_duel_conf.api_muette_max_s),
                        # Le stream coupé rembourse (§8 de la spec). Le statut
                        # est déjà tenu à jour toutes les 60 s par le
                        # `StreamWatcher` — même source que l'`ApexWatcher`
                        # juste au-dessus, aucune requête de plus. `None` tant
                        # qu'aucun relevé n'est passé : le défaut `live: False`
                        # n'est pas un stream éteint, et un duel repris d'un
                        # rebuild ne doit pas être soldé là-dessus.
                        stream_en_ligne=lambda: (
                            bool(twitch_bot._stream_info.get("live"))
                            if stream_watcher.a_sonde else None
                        ),
                    )
                    # Reprise de l'état, récompense, source globale : l'ordre
                    # des trois est dans `armer_le_duel`, où il se teste.
                    _reward_id = await armer_le_duel(
                        _duel_runner, titre=_duel_conf.titre,
                        cout=int(_duel_conf.cout), prompt=_duel_conf.prompt,
                    )
                    # En DERNIER : tant que le runner n'est pas attaché, un achat
                    # de récompense est remboursé par `events/redemptions.py` au
                    # lieu d'ouvrir un duel à moitié armé.
                    twitch_bot.duel_runner = _duel_runner
                    logger.info(
                        "Duel Apex armé (uid {u}, récompense {r})",
                        u=_azrael_uid, r=_reward_id or "INDISPONIBLE",
                    )
                except Exception as exc:  # noqa: BLE001 — un duel raté ne bloque pas le boot
                    # Même règle que le canari : un bot qui tourne sans duel vaut
                    # mieux qu'un bot qui refuse de démarrer.
                    logger.error("Duel Apex non armé : {e!r}", e=exc)
        else:
            # JAMAIS de silence : c'est ici qu'un démarrage rate le plus
            # souvent, et une capacité absente sans un mot est indétectable.
            # Le drapeau `active` est LU — c'est ce qui permet de couper le duel
            # sans supprimer la récompense de la chaîne.
            if _duel_conf is None:
                _raison = "aucune section apex.duel dans config.yaml"
            elif not _duel_conf.active:
                _raison = "coupé en configuration (apex.duel.active: false)"
            elif apex_api is None or not apex_api.available:
                _raison = "APEX_API_KEY absente — aucun relevé ne serait mesurable"
            else:
                _raison = "aucune section apex dans config.yaml"
            logger.info("Duel Apex non armé : {r}", r=_raison)

        # Attaque de virus : une seconde récompense de points de chaîne, sans
        # rapport avec Apex — elle ne dépend que de l'overlay et du dossier de
        # memes, donc elle vit HORS du bloc ci-dessus (qui est conditionné à
        # l'API Apex). Armée ici pour la même raison que le duel : Twitch ne
        # laisse rembourser qu'à l'application qui a CRÉÉ la récompense.
        try:
            from bot.twitch.events.virus_popups import (
                CLE_RECOMPENSE as _CLE_VIRUS, COUT as _COUT_VIRUS,
                PROMPT as _PROMPT_VIRUS, RECHARGE_S as _RECHARGE_VIRUS,
                SAISIE_REQUISE as _SAISIE_VIRUS, TITRE as _TITRE_VIRUS,
            )
            from bot.twitch.recompenses import assurer_recompense

            _virus_id = await assurer_recompense(
                twitch_api, db, cle_etat=_CLE_VIRUS,
                titre=_TITRE_VIRUS, cout=_COUT_VIRUS,
                prompt=_PROMPT_VIRUS, libelle="attaque de meme",
                saisie_requise=_SAISIE_VIRUS, cooldown_s=_RECHARGE_VIRUS,
            )
            logger.info("Attaque de meme armée (récompense {r})",
                        r=_virus_id or "INDISPONIBLE")
        except Exception as exc:  # noqa: BLE001 — jamais bloquant pour le boot
            logger.error("Attaque de meme non armée : {e!r}", e=exc)

        # Le pari sur les kills, repris s'il en restait un ouvert. Créé ICI et
        # non à la demande : l'objet naissait dans `run_prediction_tool`, donc
        # seulement quand quelqu'un ouvrait un pari. Après un redémarrage,
        # `twitch_bot.prediction_kills` n'existait plus — `_solder_pari_sur_partie`
        # sortait à la première ligne et le pari restait ouvert chez Twitch
        # indéfiniment, mises des viewers bloquées dedans.
        try:
            from bot.core.prediction_kills import PredictionKills

            _paris = PredictionKills(db)
            await _paris.charger()
            twitch_bot.prediction_kills = _paris
        except Exception as exc:  # noqa: BLE001 — jamais bloquant pour le boot
            logger.error("Pari sur les kills non repris : {e!r}", e=exc)

        # « im out » : la voix de Wally aux points de chaîne. Comme l'attaque de
        # meme, elle ne dépend ni d'Apex ni de l'overlay — seulement du vocal —,
        # donc elle vit hors des blocs conditionnés plus haut. Armée ici pour la
        # même raison que ses voisines : Twitch ne laisse rembourser qu'à
        # l'application qui a CRÉÉ la récompense.
        try:
            from bot.twitch.events.im_out import (
                CLE_RECOMPENSE as _CLE_IMOUT, COUT as _COUT_IMOUT,
                PROMPT as _PROMPT_IMOUT, SAISIE_REQUISE as _SAISIE_IMOUT,
                TITRE as _TITRE_IMOUT,
            )
            from bot.twitch.recompenses import assurer_recompense

            _imout_id = await assurer_recompense(
                twitch_api, db, cle_etat=_CLE_IMOUT,
                titre=_TITRE_IMOUT, cout=_COUT_IMOUT,
                prompt=_PROMPT_IMOUT, libelle="im out",
                saisie_requise=_SAISIE_IMOUT,
            )
            logger.info("Récompense « im out » armée ({r})",
                        r=_imout_id or "INDISPONIBLE")
        except Exception as exc:  # noqa: BLE001 — jamais bloquant pour le boot
            logger.error("Récompense « im out » non armée : {e!r}", e=exc)

        # Forcer une humeur (§14) : DEUX récompenses, une par intensité — le
        # coût est fixe par récompense côté Twitch, il en faut donc une pour
        # 50 % et une pour 100 %. Chacune avec sa clé : partagées, l'une
        # deviendrait irremboursable et l'autre appliquerait la mauvaise valeur.
        try:
            from bot.twitch.events.humeur import (
                CLE_50 as _CLE_H50, CLE_100 as _CLE_H100,
                COUT_50 as _COUT_H50, COUT_100 as _COUT_H100,
                PROMPT as _PROMPT_H,
                TITRE_50 as _TITRE_H50, TITRE_100 as _TITRE_H100,
            )
            from bot.twitch.recompenses import assurer_recompense

            for _cle, _titre, _cout in ((_CLE_H50, _TITRE_H50, _COUT_H50),
                                        (_CLE_H100, _TITRE_H100, _COUT_H100)):
                _id = await assurer_recompense(
                    twitch_api, db, cle_etat=_cle, titre=_titre, cout=_cout,
                    prompt=_PROMPT_H, libelle=f"humeur {_cout} pts",
                )
                logger.info("Humeur {c} pts armée (récompense {r})",
                            c=_cout, r=_id or "INDISPONIBLE")
        except Exception as exc:  # noqa: BLE001 — jamais bloquant pour le boot
            logger.error("Récompenses d'humeur non armées : {e!r}", e=exc)

        # Rattrapage permanent : redémarrage en plein live, crash, kick.
        _watch_task = asyncio.create_task(presence_stream.veiller())
        _stream_voice_tasks.add(_watch_task)
        _watch_task.add_done_callback(_stream_voice_tasks.discard)
        _clip_task = asyncio.create_task(veille_clips.veiller())
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

        # Les fins de partie (sondage dépouillé, pendu gagné ou perdu) partent
        # dans le chat en ANNONCE colorée. Câblé ICI pour la même raison que le
        # duel : il faut le bot Twitch, qui n'existe qu'à ce stade, alors que le
        # narrateur naît côté Discord. Le narrateur calcule le résultat, cette
        # sortie décide comment il se publie.
        _narrateur_fin = getattr(discord_bot, "overlay_narrator", None)
        if _narrateur_fin is not None:
            from bot.twitch.jeu_announce import JeuAnnouncer

            _annonceur_jeu = JeuAnnouncer(twitch_bot, _streamer_name.lower())
            _narrateur_fin.set_annonceur_fin(_annonceur_jeu.annoncer)
            logger.info("Fins de partie annoncées dans le chat de {c}",
                        c=_streamer_name.lower())

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

    # Les quatre actions intégrées, déclarées ET liées par le module qui les
    # implémente : le câblage y est testé (`tests/test_action_handlers.py`),
    # alors qu'ici il ne l'était pas — c'est exactement la famille de défaut du
    # `NameError` de ce matin.
    await enregistrer_actions(
        action_registry,
        prompts=prompts, emotion=emotion, persona=persona,
        secondary_llm=secondary_llm, twitch_bot=twitch_bot,
        discord_bot=discord_bot, action_executor=action_executor,
    )

    journal.start(scheduler=shared_scheduler)
    rss_feed.start(shared_scheduler)
    await action_scheduler.reload_all()

    # Les réglages d'affichage de la galerie quittent `config.yaml` pour le
    # layout, où ils se règlent PAR SCÈNE comme ceux de tous les autres widgets.
    # Une fois, au boot : `charger_layout` est sur le chemin public (chaque
    # ouverture de page, chaque redimensionnement de la source OBS), et deux
    # requêtes simultanées pourraient y jouer la migration deux fois.
    from bot.core.overlay_layout_store import semer_reglages_image
    await semer_reglages_image(db, config)
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
        # Construit ici, partagé par la route de l'extension (qui le nourrit) et
        # par l'outil du chat Twitch (qui le lit). Deux instances auraient
        # divergé au premier battement.
        music=music_service,
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
                logger.warning("Fermeture EventSub échouée: {e!r}", e=exc)
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
                logger.debug("Fermeture {c} partielle: {e!r}", c=label, e=exc)
            except Exception as exc:  # noqa: BLE001 — ne jamais bloquer l'arrêt
                logger.warning("Fermeture {c} échouée: {e!r}", c=label, e=exc)

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
            logger.warning("Arrêt du scheduler échoué: {e!r}", e=exc)
        await conv_log.stop()
        # L'état émotionnel attend dans un debounce de 5 s, sans cesse repoussé
        # tant que des messages arrivent. Rien ne le forçait à l'arrêt : la tâche
        # était simplement annulée avec la boucle, et tout ce qui n'avait pas eu
        # sa fenêtre de calme était perdu.
        try:
            await emotion.flush()
        except Exception as exc:  # noqa: BLE001 — ne jamais bloquer l'arrêt
            logger.warning("Flush émotionnel échoué: {e!r}", e=exc)
        # Dernier : tout le reste écrit encore en base jusqu'ici.
        try:
            await db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fermeture de la base échouée: {e!r}", e=exc)
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
                logger.warning("Fermeture EventSub au démarrage échouée: {e!r}", e=exc)
        raise


if __name__ == "__main__":
    asyncio.run(_demarrer())
