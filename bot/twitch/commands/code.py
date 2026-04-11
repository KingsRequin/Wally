# bot/twitch/commands/code.py
from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# État quotidien en mémoire — { channel_name: {"code": str|None, "date": "YYYY-MM-DD"} }
_daily_codes: dict[str, dict] = {}


def _code_display_msg(code: str) -> str:
    return (
        f"ON DIT BONJOUR AVANT DE METTRE LE CODE — "
        f"Le code est {code} — RAPPEL : si votre niveau est trop élevé "
        "donnez-vous des défis ou lâchez cette vilaine manette, "
        "on est pas là pour rouler sur la commu."
    )


async def handle_code_command(
    bot: "WallyTwitch",
    channel_name: str,
    author: str,
    args: str,
    badges: list,
) -> None:
    """Gère la commande !code — définir ou afficher le code du jour."""
    today = str(date.today())
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
    else:
        if state["code"]:
            code_msg = _code_display_msg(state["code"])
        else:
            code_msg = "Pas de code pour le moment, rendez-vous samedi matin pour y participer !"

    if channel_name in bot._channel_ids:
        irc_channel = bot.get_channel(channel_name)
        if irc_channel:
            await irc_channel.send(code_msg)
    else:
        await bot.twitch_api.send_message(text=code_msg)
