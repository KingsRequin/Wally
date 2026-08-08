# bot/core/apex/__init__.py
"""Accès à l'API Apex Legends Status.

`client` parle au réseau, `reader` interprète, `service` rend en texte.
"""
from bot.core.apex.client import ApexClient

__all__ = ["ApexClient"]
