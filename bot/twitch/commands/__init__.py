# bot/twitch/commands/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

from bot.twitch.commands.code import handle_code_command, handle_pp_command
from bot.twitch.commands.mood import handle_mood_command

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


async def dispatch_command(
    bot: "WallyTwitch",
    payload,
    content: str,
    author: str,
    channel_name: str,
) -> bool:
    """Tente de matcher une commande !. Retourne True si une commande a été traitée."""
    content_stripped = content.strip()
    content_lower = content_stripped.lower()

    # Overlay image command — chaîne MAISON uniquement : l'overlay est celui du
    # stream d'Azraël. Depuis une chaîne invitée, n'importe qui pouvait y
    # projeter une image, alors que `_scan_tally`, `_emote_waves` et le salut
    # ont tous été explicitement restreints.
    from bot.twitch.handlers import est_chaine_home

    overlay_cfg = bot.config.overlay_image
    if (overlay_cfg.enabled and content_lower == overlay_cfg.command.lower()
            and est_chaine_home(bot, channel_name)):
        from bot.twitch.handlers import _fire, _announce_overlay_image
        ds = getattr(bot, "dashboard_state", None)
        if ds is not None:
            image = await bot.db.get_random_gallery_image(overlay_cfg.random_filter)
            if image:
                from bot.core.overlay_feed import payload_image_galerie
                # Sans `scene` : une vraie demande du chat s'affiche sur toutes
                # les pages d'overlay, quelle que soit la scène à l'antenne.
                img_payload = payload_image_galerie(image, overlay_cfg)
                channel_id = f"twitch:{channel_name}"
                _fire(_announce_overlay_image(bot, channel_name, channel_id, image, ds, img_payload))
        return True

    # Le rébus : chaîne MAISON seulement, comme `!image` et les sons. Les
    # réponses, elles, se ramassent dans `handle_message` — on devine en
    # écrivant le mot, pas en tapant une commande.
    if content_lower == "!rebus" and est_chaine_home(bot, channel_name):
        from bot.twitch.commands.rebus import handle_rebus_command
        await handle_rebus_command(bot, channel_name)
        return True

    if content_lower == "!mood":
        await handle_mood_command(bot, channel_name)
        return True

    if content_lower == "!pp":
        await handle_pp_command(bot, channel_name)
        return True

    if content_lower.startswith("!code"):
        args = content_stripped[len("!code"):].strip()
        badges = getattr(payload, "badges", []) or []
        await handle_code_command(bot, channel_name, author, args, badges)
        return True

    # Les sons du chat, EN DERNIER : le dossier `data/sons/commande/` décide de
    # ce qui existe, et rien n'empêche l'owner d'y déposer un `mood.mp3`. Placé
    # ici, il ne pourra jamais éclipser une commande écrite en dur au-dessus.
    #
    # Chaîne MAISON uniquement, comme `!image` et `!code` : l'overlay est celui
    # du stream d'Azraël, et un viewer d'une chaîne invitée n'a pas à y faire
    # du bruit.
    if (content_lower.startswith("!") and " " not in content_lower
            and est_chaine_home(bot, channel_name)):
        from bot.twitch.commands.sons import handle_son_command
        if await handle_son_command(bot, content_lower[1:]):
            return True

    return False
