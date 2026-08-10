# bot/twitch/commands/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

from bot.twitch.commands.code import handle_code_command
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
                img_payload = {
                    "image_url": f"/api/public/gallery/{image['id']}/image",
                    "title": image.get("title") or "",
                    "username": image["username"],
                    "display_duration": overlay_cfg.display_duration,
                    "animation_in": overlay_cfg.animation_in,
                    "animation_out": overlay_cfg.animation_out,
                    "animation_duration": overlay_cfg.animation_duration,
                }
                channel_id = f"twitch:{channel_name}"
                _fire(_announce_overlay_image(bot, channel_name, channel_id, image, ds, img_payload))
        return True

    if content_lower == "!mood":
        await handle_mood_command(bot, channel_name)
        return True

    if content_lower.startswith("!code"):
        args = content_stripped[len("!code"):].strip()
        badges = getattr(payload, "badges", []) or []
        await handle_code_command(bot, channel_name, author, args, badges)
        return True

    return False
