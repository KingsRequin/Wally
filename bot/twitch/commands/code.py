# bot/twitch/commands/code.py
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from bot.core.temps import aujourdhui

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# État quotidien en mémoire — { channel_name: {"code": str|None, "date": "YYYY-MM-DD"} }
_daily_codes: dict[str, dict] = {}


# L'organisation des parties — la règle des demandes d'ami. Elle vivait dans
# `pp.js` (PhantomBot), qui ne l'a jamais dite : le script enregistre ses
# commandes sous `./custom/pp.js` alors qu'il vit dans `./custom/custom/pp.js`,
# donc PhantomBot ne les associe à aucun script et se tait. Zéro occurrence dans
# ses logs de chat de février à août 2026. Personne ne l'a donc jamais lue.
_PP_MSG = (
    "Les game viewers ou parties privées se font tous les samedis, n'hésitez pas "
    "à dire si vous voulez jouer ! Vous devez demander azrael_ttv en amis pour "
    "jouer avec (sauf pour les parties privées). /!\\ [ATTENTION] la demande "
    "d'ami est uniquement pour les games viewers, vous serez supprimé une fois "
    "terminé. /!\\"
)


def _code_display_msg(code: str) -> str:
    return (
        f"ON DIT BONJOUR AVANT DE METTRE LE CODE, "
        f"Le code est {code}, RAPPEL : si votre niveau est trop élevé "
        "donnez-vous des défis ou lâchez cette vilaine manette, "
        "on est pas là pour rouler sur la commu."
    )


async def _annoncer_sur_discord(bot: "WallyTwitch", code: str) -> None:
    """Pousse l'annonce de partie privée dans le salon Discord, rôle pingué.

    Pas de webhook, contrairement à `pp.js` : Wally est déjà dans la guilde, donc
    aucun secret à porter ni à révoquer le jour où PhantomBot s'éteint.

    Best-effort de bout en bout : l'annonce est un bonus, le chat Twitch est la
    fonction. Une guilde injoignable ne doit pas priver le live de son code.
    """
    cfg = bot.config.bot
    salon_id, role_id = cfg.partie_privee_channel_id, cfg.partie_privee_role_id
    discord_bot = getattr(bot, "discord_bot", None)
    if not salon_id or discord_bot is None:
        return
    try:
        import discord

        salon = discord_bot.get_channel(salon_id)
        if salon is None:
            salon = await discord_bot.fetch_channel(salon_id)
        if salon is None:
            logger.warning("Annonce partie privée : salon {sid} introuvable", sid=salon_id)
            return
        ping = f"<@&{role_id}> " if role_id else ""
        # Le garde global du projet pose `roles=False` : sans autorisation
        # explicite, le `<@&…>` s'afficherait sans notifier personne — et le ping
        # est justement ce qui fait venir ceux qui ne regardent pas le live.
        # Restreint à CE rôle : ni @everyone, ni les membres cités.
        mentions = discord.AllowedMentions(
            everyone=False,
            users=False,
            roles=[discord.Object(id=role_id)] if role_id else False,
        )
        await salon.send(
            f"# {ping}Une partie privée est organisée chez "
            f"[Azrael](https://www.twitch.tv/azrael_ttv) ! Le code est : `{code}`",
            allowed_mentions=mentions,
        )
        logger.info("Annonce de partie privée publiée sur Discord (code {code})", code=code)
    except Exception as e:  # noqa: BLE001 — best-effort, le chat Twitch prime
        logger.warning("Annonce partie privée échouée: {e!r}", e=e)


async def handle_pp_command(bot: "WallyTwitch", channel_name: str) -> None:
    """Gère `!pp` — rappelle comment les parties s'organisent."""
    await _repondre(bot, channel_name, _PP_MSG)


async def _repondre(bot: "WallyTwitch", channel_name: str, message: str) -> None:
    """Répond sur la chaîne : IRC pour les invitées, API pour la maison.

    Message ORDINAIRE, jamais une annonce. Le code de la partie privée est fait
    pour être ÉPINGLÉ le temps de la session — et Twitch n'épingle pas les
    annonces. Sorti en annonce, il tenait quelques secondes sur son fond violet
    puis remontait avec le reste du chat, et personne n'y avait plus accès ;
    l'owner l'a dit le 2026-09-05 (« je vais repasser son message normal et pas
    en annonce alors »).

    L'épinglage AUTOMATIQUE, lui, n'est pas possible : `POST
    /helix/chat/messages/pin` rend 404 (essayé le 2026-09-05 sur le token en
    service) et Twitch a confirmé sur son forum en février 2024 qu'aucune API
    n'épingle un message. Seule la main d'un modérateur le fait.

    Et c'est de toute façon le bon poids : `!code` et `!pp` RÉPONDENT à
    quelqu'un qui a tapé une commande. L'annonce colorée est faite pour ce que
    personne n'a demandé.
    """
    if channel_name in bot._channel_ids:
        irc_channel = bot.get_channel(channel_name)
        if irc_channel:
            await irc_channel.send(message)
    else:
        await bot.twitch_api.send_message(message)


async def handle_code_command(
    bot: "WallyTwitch",
    channel_name: str,
    author: str,
    args: str,
    badges: list,
) -> None:
    """Gère la commande !code — définir ou afficher le code du jour."""
    # La date de PARIS, pas celle de l'horloge machine (l'hôte est en UTC) :
    # le code du jour changeait à 01 h ou 02 h du matin heure locale.
    today = str(aujourdhui())
    db_key = f"twitch_code:{channel_name}"

    if channel_name not in _daily_codes:
        try:
            raw = await bot.db.get_persistent_note(db_key)
            if raw:
                _daily_codes[channel_name] = json.loads(raw)
            else:
                _daily_codes[channel_name] = {"code": None, "date": today}
        except Exception:
            _daily_codes[channel_name] = {"code": None, "date": today}

    state = _daily_codes[channel_name]
    # Rempli si un code vient d'être posé — l'annonce Discord part APRÈS le chat
    # Twitch : le live ne doit pas attendre un aller-retour vers une guilde.
    code_a_annoncer: str | None = None

    if state["date"] != today:
        state["code"] = None
        state["date"] = today
        await bot.db.upsert_persistent_note(db_key, json.dumps(state))

    if args:
        badge_ids = {b.id if hasattr(b, "id") else str(b) for b in badges}
        is_privileged = bool(badge_ids & {"moderator", "broadcaster"})
        if not is_privileged:
            code_msg = "Seuls les modérateurs peuvent définir le code. LUL"
        else:
            state["code"] = args
            state["date"] = today
            await bot.db.upsert_persistent_note(db_key, json.dumps(state))
            code_msg = _code_display_msg(args)
            logger.info("!code défini par {user} sur {ch} : {code}", user=author, ch=channel_name, code=args)
            # Annoncé seulement à la POSE, et seulement depuis la chaîne maison :
            # `!code` répond aussi sur les chaînes invitées, où un modérateur
            # pingerait le Discord d'Azraël pour SA partie privée. Même réflexe
            # que `!image` et les outils d'overlay.
            from bot.twitch.handlers import est_chaine_home

            if est_chaine_home(bot, channel_name):
                code_a_annoncer = args
    else:
        if state["code"]:
            code_msg = _code_display_msg(state["code"])
        else:
            # La règle des demandes d'ami est la partie utile quand il n'y a pas
            # encore de code : sans elle, Wally renvoyait à samedi sans dire ce
            # qu'il fallait préparer d'ici là.
            code_msg = (
                "Pas de code pour le moment, rendez-vous samedi matin pour y "
                f"participer ! {_PP_MSG}"
            )

    await _repondre(bot, channel_name, code_msg)

    if code_a_annoncer is not None:
        await _annoncer_sur_discord(bot, code_a_annoncer)
