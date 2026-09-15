"""Fiche de bienvenue — repris du bot Node `wally-discord`, en Components V2.

Un message tiré au sort, un GIF, et une « fact » inutile traduite en français,
rendus via `bot/discord/fiches.py` (le dépôt n'a plus aucun `discord.Embed`,
chantier clos le 2026-09-04). La cognition perçoit AUSSI l'arrivée
(`_member_join_context`) : la fiche est donc consignée dans `self_trace`,
sans quoi Wally accueillerait une seconde fois en croyant être le premier.

La fact part dans une fiche, jamais dans un prompt : pas de `wrap_untrusted`.
Le jour où elle entre dans un prompt, elle y passe.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import discord
import httpx
from loguru import logger

from bot.core.self_trace import note_act
from bot.discord.fiches import borner, fiche, url_avatar

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_FACT_URL = "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en"
_TRADUCTION_URL = "https://api.mymemory.translated.net/get"
_TIMEOUT = 5.0
_ACCENT_BIENVENUE = 0x1AD5B6
_MAX_TEXTE_EXTERNE = 1000    # budget V2 (4000 pour toute la fiche) réparti par bloc
FACT_INDISPONIBLE = "Impossible de récupérer une fact."
TRADUCTION_INDISPONIBLE = "Traduction indisponible."


def _motif_traduction_invalide(data: dict[str, Any]) -> str | None:
    """MyMemory répond parfois 200 avec une erreur DANS LE CORPS : quota
    gratuit épuisé (`quotaFinished`), `responseStatus` interne différent de
    200 (int OU string selon les cas), ou un `translatedText` qui est en
    réalité un message d'avertissement (`MYMEMORY WARNING…`) ou vide. Aucune
    exception réseau ne le signale — seul le contenu trahit l'échec. Rend le
    motif (pour le WARNING) si la traduction est inutilisable, sinon None.
    """
    if data.get("quotaFinished"):
        return "quota MyMemory épuisé (quotaFinished=true)"
    statut = data.get("responseStatus")
    if statut is not None and str(statut) != "200":
        return f"responseStatus={statut!s}"
    traduction = (data.get("responseData") or {}).get("translatedText") or ""
    if not traduction:
        return "translatedText vide"
    if traduction.startswith("MYMEMORY WARNING"):
        return f"translatedText={traduction}"
    return None


async def _recuperer_fact(client: httpx.AsyncClient) -> tuple[str, str]:
    try:
        r = await client.get(_FACT_URL, timeout=_TIMEOUT)
        r.raise_for_status()
        fact = r.json()["text"]
    except Exception as e:  # noqa: BLE001 — repli affiché dans la fiche
        logger.warning("bienvenue : fact indisponible : {e!r}", e=e)
        return FACT_INDISPONIBLE, TRADUCTION_INDISPONIBLE
    try:
        r = await client.get(_TRADUCTION_URL, params={"q": fact, "langpair": "en|fr"}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001 — repli affiché dans la fiche
        logger.warning("bienvenue : traduction indisponible : {e!r}", e=e)
        return fact, TRADUCTION_INDISPONIBLE
    motif = _motif_traduction_invalide(data)
    if motif:
        logger.warning("bienvenue : traduction indisponible : {motif}", motif=motif)
        return fact, TRADUCTION_INDISPONIBLE
    return fact, data["responseData"]["translatedText"]


def _borner_externe(texte: str, limite: int = _MAX_TEXTE_EXTERNE) -> str:
    """Borne puis échappe le Markdown d'un texte VENU DE L'EXTÉRIEUR (fact, traduction).

    Tronquer AVANT d'échapper évite de couper une séquence d'échappement en
    deux (un `\\` isolé en fin de bloc) : `escape_markdown` ne fait qu'AJOUTER
    des caractères, il ne peut pas en joindre deux entre eux.
    """
    return discord.utils.escape_markdown(borner(texte, limite))


async def accueillir(bot: "WallyDiscord", member: Any) -> None:
    """Poste la fiche de bienvenue. Ne lève jamais.

    Tout — y compris la lecture de `cfg` et le garde bot/guild — vit DANS le
    try : lire un attribut absent sur un `member` incomplet ne doit pas
    laisser passer une exception, la garantie « ne lève jamais » doit tenir
    de bout en bout.
    """
    try:
        cfg = bot.config.discord.bienvenue
        if member.bot or member.guild.id not in cfg.guild_ids:
            return  # bot, ou serveur hors de la liste activée : rien à faire
        # `Any` : `get_channel` rend un type large (salon texte, catégorie,
        # DM…) — le salon d'accueil est configuré par l'owner comme un salon
        # textuel.
        salon: Any = bot.get_channel(cfg.salon_id) if cfg.salon_id is not None else None
        salon = salon or member.guild.system_channel
        if salon is None:
            logger.warning("bienvenue : aucun salon d'accueil pour le serveur {g}", g=member.guild.id)
            return
        async with httpx.AsyncClient() as client:
            fact, traduction = await _recuperer_fact(client)
        message = random.choice(cfg.messages) if cfg.messages else "Bienvenue !"
        corps = [
            f"### {message}\n\n{member.mention}",
            f"**français :** {_borner_externe(traduction)}",
            f"**original :** {_borner_externe(fact)}",
        ]
        vue = fiche(
            f"BIENVENUE A {discord.utils.escape_markdown(member.name)}",
            corps,
            accent=_ACCENT_BIENVENUE,
            vignette=url_avatar(member),
            pied="Le Purgatoire",
            medias=[random.choice(cfg.gifs)] if cfg.gifs else (),
        )
        # Une fact/traduction venue de l'extérieur ne doit jamais pinger :
        # seul le nouveau venu est autorisé (sa propre mention, `everyone`
        # et les rôles coupés).
        await salon.send(
            view=vue,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[member]),
        )
        note_act(f"tu as posté la fiche de bienvenue de {member.name} dans #{salon.name} (Discord)")
        logger.info("bienvenue : fiche postée pour {m}", m=member.name)
    except Exception as e:  # noqa: BLE001 — un accueil raté ne fait pas tomber le bot
        logger.warning("bienvenue : fiche non postée : {e!r}", e=e)
