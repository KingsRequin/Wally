# bot/core/apex/__init__.py
"""Accès à l'API Apex Legends Status.

`client` parle au réseau, `reader` interprète, `service` rend en texte.
"""
from bot.core.apex.client import ApexClient
from bot.core.apex.service import ApexLegendsService
from bot.core.apex.tool import APEX_LEGENDS_TOOL

__all__ = ["ApexClient", "ApexLegendsService", "APEX_LEGENDS_TOOL"]
