"""Identité d'instance (nom, créateur, owner) injectée dans les prompts.

Posée une seule fois au démarrage via set_identity(), puis render_identity()
remplace les sentinelles {{BOT_NAME}} / {{CREATOR_NAME}} / {{OWNER_ID}} dans
les templates de prompt. On évite str.format : les prompts contiennent du JSON
littéral ({...}) qui casserait.
"""
from __future__ import annotations

_NAME: str = "Wally"
_CREATOR: str = "KingsRequin"
_OWNER: str = ""


def set_identity(cfg) -> None:
    """Pose l'identité depuis un BotConfig. Appelé 1× au boot après Config.load."""
    global _NAME, _CREATOR, _OWNER
    _NAME = (getattr(cfg, "name", "") or "Wally")
    _CREATOR = (getattr(cfg, "creator_name", "") or "KingsRequin")
    _OWNER = (getattr(cfg, "owner_discord_id", "") or "")


def bot_name() -> str:
    """Retourne le nom du bot."""
    return _NAME


def owner_id() -> str:
    """Retourne l'ID Discord du propriétaire."""
    return _OWNER


def creator_name() -> str:
    """Retourne le nom du créateur."""
    return _CREATOR


def render_identity(text: str) -> str:
    """Remplace les sentinelles {{BOT_NAME}}, {{CREATOR_NAME}}, {{OWNER_ID}} dans le texte."""
    return (text
            .replace("{{BOT_NAME}}", _NAME)
            .replace("{{CREATOR_NAME}}", _CREATOR)
            .replace("{{OWNER_ID}}", _OWNER))
