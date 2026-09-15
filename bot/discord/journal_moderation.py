"""Journal de modération — repris du bot Node `wally-discord`.

Une fiche Components V2 par geste dans le salon de logs : message supprimé,
message modifié, salon vocal temporaire créé ou supprimé. C'est un outil de
MODÉRATION, pas de la perception : il couvre aussi les messages de bots et les
serveurs que la perception de Wally ignore (`ignored_guilds`).

Le dépôt n'a plus aucun `discord.Embed` (chantier Components V2 clos le
2026-09-04) : le tronc commun est `bot/discord/fiches.py`.

Les `@` sont neutralisés ET les mentions coupées : un message supprimé qui
contenait `@everyone` ne doit pas notifier le serveur une seconde fois.

Les pièces jointes d'un message supprimé (ou retirées d'une édition) sont
retéléchargées via `Attachment.to_file(use_cached=True)` : ce chemin passe par
le `proxy_url`, encore servi un court moment après la suppression, là où l'URL
d'origine est déjà morte.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from loguru import logger

from bot.core.temps import maintenant
from bot.discord.fiches import ACCENT_ALERTE, fiche, url_avatar

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_COULEUR_VOCAL = 0x3498DB      # pas dans fiches.py : propre au journal
_MAX_CITATION = 1500           # budget V2 total (4000) réparti entre les blocs cités
_MAX_PIECES = 10                # plafond d'upload Discord pour un message


def _echapper(texte: str) -> str:
    return texte.replace("@", "@\u200b")


def _citer(texte: str) -> str:
    """Cite un texte ligne par ligne (`> `), borné et `@` neutralisés."""
    texte = _echapper(texte)
    if len(texte) > _MAX_CITATION:
        texte = texte[:_MAX_CITATION] + "…"
    return "\n".join(f"> {ligne}" for ligne in texte.splitlines())


def _bloc_cite(titre: str, texte: str) -> str:
    corps = _citer(texte) if texte.strip() else "*aucun texte*"
    return f"**{titre}**\n{corps}"


def _bloc_non_recuperees(ratees: list[tuple[str, str]]) -> str:
    lignes = "\n".join(f"- {nom} ({motif})" for nom, motif in ratees)
    return f"**Pièces jointes non récupérées**\n{lignes}"


def _salon_cible(bot: "WallyDiscord", guild_id: int | None) -> Any:
    """Résout le salon de logs, ou None si rien à publier.

    Centralise les garde-fous inchangés depuis la version embeds : `salon_id`
    None → rien ; guild hors `guild_ids` → rien ; salon introuvable → WARNING.
    """
    cfg = bot.config.discord.journal_moderation
    if cfg.salon_id is None or guild_id not in cfg.guild_ids:
        return None
    # `bot.get_channel` rend un type large (salon texte, catégorie, DM…) ; le
    # salon de logs est configuré par l'owner comme un salon textuel.
    salon: Any = bot.get_channel(cfg.salon_id)
    if salon is None:
        logger.warning("journal de modération : salon {c} introuvable", c=cfg.salon_id)
    return salon


async def _telecharger_pieces(
    salon: Any, pieces: list[Any],
) -> tuple[list[discord.File], list[str], list[str], list[tuple[str, str]]]:
    """Retélécharge au plus 10 pièces jointes pour les rattacher au log.

    Rend `(fichiers_discord, refs_medias, refs_fichiers, non_recuperees)`. Les
    images vont en galerie (`refs_medias`), le reste en composant `File`
    (`refs_fichiers`) — en Components V2, une pièce jointe que rien ne
    référence n'apparaît pas du tout.
    """
    fichiers: list[discord.File] = []
    medias: list[str] = []
    autres: list[str] = []
    ratees: list[tuple[str, str]] = []
    limite = getattr(getattr(salon, "guild", None), "filesize_limit", None)
    noms_utilises: dict[str, int] = {}
    for index, piece in enumerate(pieces):
        if index >= _MAX_PIECES:
            ratees.append((piece.filename, "au-delà de 10"))
            continue
        if limite is not None and piece.size > limite:
            ratees.append((piece.filename, "trop lourde"))
            continue
        try:
            fichier = await piece.to_file(use_cached=True)
        except Exception as e:  # noqa: BLE001 — attendu : Discord a déjà purgé la pièce
            logger.info("journal de modération : pièce {n} indisponible : {e!r}", n=piece.filename, e=e)
            ratees.append((piece.filename, "plus disponible"))
            continue
        nom = fichier.filename
        if nom in noms_utilises:
            noms_utilises[nom] += 1
            nom = f"{noms_utilises[nom]}_{nom}"
            fichier.filename = nom
        else:
            noms_utilises[nom] = 0
        fichiers.append(fichier)
        ref = f"attachment://{nom}"
        if (piece.content_type or "").startswith("image/"):
            medias.append(ref)
        else:
            autres.append(ref)
    return fichiers, medias, autres, ratees


async def _envoyer(salon: Any, vue: discord.ui.LayoutView, fichiers: list[discord.File]) -> None:
    try:
        await salon.send(view=vue, files=fichiers, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:  # noqa: BLE001 — un journal ne casse pas ce qu'il observe
        logger.warning("journal de modération : envoi impossible dans {c} : {e!r}",
                       c=getattr(salon, "id", "?"), e=e)


async def message_supprime(bot: "WallyDiscord", payload: Any) -> None:
    try:
        salon = _salon_cible(bot, payload.guild_id)
        if salon is None:
            return
        msg = payload.cached_message
        if msg is not None:
            auteur = msg.author
            meta_auteur = f"<@{auteur.id}> ({auteur.name})"
            vignette = url_avatar(auteur)
            contenu = (msg.content or "").strip()
            bloc_contenu = _citer(contenu) if contenu else "*aucun texte*"
            pieces = list(msg.attachments)
        else:
            meta_auteur = "inconnu"
            vignette = None
            bloc_contenu = "*contenu non disponible*"
            pieces = []
        meta = (f"**Auteur** {meta_auteur} · **Salon** <#{payload.channel_id}> · "
               f"**Message** {payload.message_id}")
        fichiers, medias, autres, ratees = await _telecharger_pieces(salon, pieces)
        corps = [meta, bloc_contenu]
        if ratees:
            corps.append(_bloc_non_recuperees(ratees))
        heure = maintenant().strftime("%Hh%M")
        vue = fiche("🗑️ Message supprimé", corps, accent=ACCENT_ALERTE, vignette=vignette,
                   medias=medias, fichiers=autres, pied=f"Supprimé à {heure}")
        await _envoyer(salon, vue, fichiers)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : suppression non journalisée : {e!r}", e=e)


async def message_modifie(bot: "WallyDiscord", before: Any, after: Any) -> None:
    try:
        if after.author.bot:
            return
        avant, apres = before.content or "", after.content or ""
        apres_ids = {p.id for p in after.attachments}
        retirees = [p for p in before.attachments if p.id not in apres_ids]
        if avant == apres and not retirees:
            return          # embed de lien, épinglage : rien n'a bougé
        guild_id = after.guild.id if after.guild is not None else None
        salon = _salon_cible(bot, guild_id)
        if salon is None:
            return
        auteur = after.author
        meta = (f"**Auteur** <@{auteur.id}> ({auteur.name}) · **Salon** <#{after.channel.id}> · "
               f"**Message** {after.id} · [aller au message]({after.jump_url})")
        fichiers, medias, autres, ratees = await _telecharger_pieces(salon, retirees)
        corps = [meta, _bloc_cite("Avant", avant), _bloc_cite("Après", apres)]
        if ratees:
            corps.append(_bloc_non_recuperees(ratees))
        vue = fiche("✏️ Message modifié", corps, accent=ACCENT_ALERTE, vignette=url_avatar(auteur),
                   medias=medias, fichiers=autres)
        await _envoyer(salon, vue, fichiers)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : modification non journalisée : {e!r}", e=e)


async def vocal_cree(bot: "WallyDiscord", member: Any, salon: Any) -> None:
    cible = _salon_cible(bot, salon.guild.id)
    if cible is None:
        return
    meta = f"**Par** <@{member.id}> · **Salon** {salon.name} · **ID** {salon.id}"
    vue = fiche("🔊 Canal vocal créé", [meta], accent=_COULEUR_VOCAL)
    await _envoyer(cible, vue, [])


async def vocal_supprime(bot: "WallyDiscord", salon: Any) -> None:
    cible = _salon_cible(bot, salon.guild.id)
    if cible is None:
        return
    meta = f"**Salon** {salon.name} · **ID** {salon.id}"
    vue = fiche("🔇 Canal vocal supprimé", [meta], accent=_COULEUR_VOCAL)
    await _envoyer(cible, vue, [])
