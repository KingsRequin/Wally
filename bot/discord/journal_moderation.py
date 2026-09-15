"""Journal de modération — repris du bot Node `wally-discord`.

Une fiche Components V2 par geste dans le salon de logs : message supprimé,
message modifié, suppression en masse, salon vocal temporaire créé ou
supprimé. C'est un outil de MODÉRATION, pas de la perception : il couvre
aussi les messages de bots et les serveurs que la perception de Wally ignore
(`ignored_guilds`).

Le dépôt n'a plus aucun `discord.Embed` (chantier Components V2 clos le
2026-09-04) : le tronc commun est `bot/discord/fiches.py`.

Les `@` sont neutralisés ET les mentions coupées : un message supprimé qui
contenait `@everyone` ne doit pas notifier le serveur une seconde fois.

Les pièces jointes d'un message supprimé (ou retirées d'une édition) sont
retéléchargées via `Attachment.to_file(use_cached=True)` : ce chemin passe par
le `proxy_url`, encore servi un court moment après la suppression, là où l'URL
d'origine est déjà morte.

Publié sur PLUSIEURS salons de logs (`salon_ids`), potentiellement sur des
serveurs différents. Chaque salon est indépendant : un salon introuvable ou
un envoi en échec ne prive pas les autres. Les pièces jointes sont
téléchargées UNE fois (octets bruts) puis reconditionnées en `discord.File`
frais par salon — un `File` est consommé par un envoi (son tampon est lu puis
fermé), il en faut un NEUF à chaque `send()`.

Deux gardes de contenu sur les pièces jointes : celles d'un salon NSFW ne
sont JAMAIS republiées (le salon de logs n'a pas le même public), seulement
listées ; celles postées sous spoiler repartent sous spoiler.
"""
from __future__ import annotations

import io
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

import discord
from loguru import logger

from bot.core.temps import maintenant
from bot.discord.fiches import ACCENT_ALERTE, Piece, borner, fiche, url_avatar

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_COULEUR_VOCAL = 0x3498DB      # pas dans fiches.py : propre au journal
_MAX_CITATION = 1500           # budget V2 total (4000) réparti entre les blocs cités
_MAX_NON_RECUPEREES = 500      # budget de la liste des pièces non récupérées
_MAX_EXTRAIT = 120             # extrait par message d'une suppression en masse
_MAX_PIECES = 10                # plafond d'upload Discord pour un message
_PREFIXE_SPOILER = "SPOILER_"  # la convention de nom de Discord pour une pièce sous spoiler

# `discord.File.uri` l'exige (doc) : Discord traite le reste EN SILENCE côté
# serveur — un nom hors de cet alphabet rend un `attachment://` mort.
_CARACTERES_SURS = re.compile(r"[^A-Za-z0-9_.-]")


class _PieceRecuperee(NamedTuple):
    """Les octets d'une pièce jointe téléchargée UNE fois, avant reconditionnement par salon."""
    nom: str          # nom ENVOYÉ (assaini, préfixé `SPOILER_` si spoiler)
    origine: str      # nom d'origine, pour la liste des pièces non publiées
    donnees: bytes
    spoiler: bool


class _Telechargement(NamedTuple):
    recuperees: list[_PieceRecuperee]
    medias: list[Piece]                  # images → galerie
    autres: list[Piece]                  # le reste → composant `File`
    ratees: list[tuple[str, str]]        # (nom, motif)


_SANS_PIECE = _Telechargement([], [], [], [])


def _echapper(texte: str) -> str:
    return texte.replace("@", "@\u200b")


def _borner(texte: str, limite: int) -> str:
    borne = borner(texte, limite)
    # `_echapper` neutralise un `@` avec un zero-width space qui le SUIT :
    # couper pile entre les deux laisserait un `@` isolé, à nouveau ACTIF
    # (mention réelle) alors que le but de l'échappement était de l'éteindre.
    if borne != texte and borne[:-1].endswith("@"):
        borne = borne[:-2] + "…"
    return borne


def _recap(n: int) -> str:
    return f"… et {n} autre" if n == 1 else f"… et {n} autres"


def _borner_lignes(lignes: list[str], limite: int) -> str:
    """Borne une liste de lignes par lignes ENTIÈRES.

    `_borner` coupe au caractère près : sur `**auteur** : extrait`, la
    coupure peut tomber au milieu du marqueur `**`, laissant tout le RESTE du
    message en gras. Les lignes qui ne tiennent plus deviennent une seule
    ligne récapitulative « … et N autre(s) ».
    """
    texte = "\n".join(lignes)
    if len(texte) <= limite:
        return texte
    gardees: list[str] = []
    longueur = 0
    for i, ligne in enumerate(lignes):
        reste = len(lignes) - i
        recap = _recap(reste)
        # Marge pour la ligne récapitulative SI cette ligne ne complète pas
        # la liste — la toute dernière ligne n'a besoin d'aucune marge.
        marge = len(recap) + 1 if reste > 1 else 0
        ajout = len(ligne) + (1 if gardees else 0)
        if longueur + ajout + marge > limite:
            gardees.append(recap)
            return "\n".join(gardees)
        gardees.append(ligne)
        longueur += ajout
    return "\n".join(gardees)


def _citer(texte: str, *, limite: int = _MAX_CITATION) -> str:
    """Cite un texte ligne par ligne (`> `), `@` neutralisés.

    Le budget se borne APRÈS citation : sur un texte à nombreuses lignes
    courtes, le préfixe `> ` peut presque doubler la taille — border le texte
    d'origine laissait passer un bloc deux fois plus gros que prévu (message
    Discord refusé, entrée de journal perdue).
    """
    texte = _echapper(texte)
    cite = "\n".join(f"> {ligne}" for ligne in texte.splitlines())
    return _borner(cite, limite)


def _bloc_cite(titre: str, texte: str) -> str:
    corps = _citer(texte) if texte.strip() else "*aucun texte*"
    return f"**{titre}**\n{corps}"


def _bloc_non_recuperees(ratees: list[tuple[str, str]]) -> str:
    lignes = "\n".join(f"- {nom} ({motif})" for nom, motif in ratees)
    return _borner(f"**Pièces jointes non récupérées**\n{lignes}", _MAX_NON_RECUPEREES)


def _mention_salon(salon_id: int, salon: Any) -> str:
    """`<#id>` suivi du nom lisible du salon.

    Les salons de logs vivent parfois sur un AUTRE serveur que le salon
    observé : là, `<#id>` seul s'affiche « salon inconnu ». Le nom (échappé)
    le rend lisible partout ; à défaut de nom, l'id.
    """
    nom = getattr(salon, "name", None)
    if isinstance(nom, str) and nom:
        return f"<#{salon_id}> (#{discord.utils.escape_markdown(nom)})"
    return f"<#{salon_id}> ({salon_id})"


def _salon_nsfw(salon: Any) -> bool:
    """Le drapeau NSFW du salon d'origine ; inconnu → non NSFW.

    Un fil hérite du drapeau de son parent : `Thread.is_nsfw()` le lit déjà
    sur le parent dans discord.py.
    """
    est_nsfw = getattr(salon, "is_nsfw", None)
    return bool(est_nsfw()) if callable(est_nsfw) else False


def _est_spoiler(piece: Any) -> bool:
    est_spoiler = getattr(piece, "is_spoiler", None)
    if callable(est_spoiler) and est_spoiler():
        return True
    return str(piece.filename).startswith(_PREFIXE_SPOILER)


def _assainir(nom: str) -> str:
    """ASCII alphanumérique + `_-.` uniquement, extension préservée, jamais vide."""
    base, point, ext = nom.rpartition(".")
    if not point:
        base, ext = nom, ""
    base_saine = _CARACTERES_SURS.sub("_", base) or "fichier"
    ext_saine = _CARACTERES_SURS.sub("_", ext)
    return f"{base_saine}.{ext_saine}" if ext_saine else base_saine


def _nom_disponible(nom: str, pris: set[str]) -> str:
    """Rend `nom` s'il est libre, sinon le préfixe d'un index jusqu'à l'être.

    La boucle teste contre `pris` (tous les noms déjà attribués), pas contre
    un dict par nom D'ORIGINE : un renommage précédent (`1_photo.png`) peut
    lui-même être le nom BRUT d'une pièce suivante, et doit donc être vu par
    la vérification de collision.
    """
    if nom not in pris:
        return nom
    n = 1
    while f"{n}_{nom}" in pris:
        n += 1
    return f"{n}_{nom}"


def _salons_cibles(bot: "WallyDiscord", guild_id: int | None, salon_source_id: int | None) -> list[Any]:
    """Résout les salons de logs CONFIGURÉS, ou [] si rien à publier.

    `salon_ids` vide → désactivé ; guild hors `guild_ids` → rien. Un salon
    introuvable ne bloque pas les autres : WARNING nommant son id, la
    résolution continue sur le reste.

    Un événement né DANS un salon de logs ne se journalise pas : un salon de
    logs peut vivre dans un serveur observé, et supprimer une fiche (ou
    purger le salon) la republiait aussitôt dans chaque salon de logs — une
    fiche qu'on ne pouvait plus jamais effacer.
    """
    cfg = bot.config.discord.journal_moderation
    if not cfg.salon_ids or guild_id not in cfg.guild_ids:
        return []
    if salon_source_id is not None and salon_source_id in cfg.salon_ids:
        return []
    salons: list[Any] = []
    for salon_id in cfg.salon_ids:
        # `bot.get_channel` rend un type large (salon texte, catégorie, DM…) ;
        # les salons de logs sont configurés par l'owner comme des salons
        # textuels.
        salon: Any = bot.get_channel(salon_id)
        if salon is None:
            logger.warning("journal de modération : salon {c} introuvable", c=salon_id)
            continue
        salons.append(salon)
    return salons


async def _telecharger_pieces(salons: list[Any], pieces: list[Any], *, nsfw: bool) -> _Telechargement:
    """Retélécharge au plus 10 pièces jointes, UNE fois pour tous les salons.

    Le plafond de poids utilise la PLUS PETITE limite d'upload parmi les
    salons joignables : le même jeu de fichiers part partout, donc toutes les
    destinations doivent l'accepter. Le budget est CUMULÉ sur tout le
    message (pas testé fichier par fichier) : dix pièces chacune sous la
    limite peuvent quand même représenter dix fois la limite en mémoire.

    Les images vont en galerie (`medias`), le reste en composant `File`
    (`autres`) — en Components V2, une pièce jointe que rien ne référence
    n'apparaît pas du tout.

    `nsfw` : rien n'est téléchargé, tout est listé « salon NSFW ». Une pièce
    sous spoiler repart sous spoiler (nom `SPOILER_` ET composant marqué).
    """
    if nsfw:
        return _Telechargement([], [], [], [(p.filename, "salon NSFW") for p in pieces])
    limites = [
        lim for lim in (getattr(getattr(s, "guild", None), "filesize_limit", None) for s in salons)
        if lim is not None
    ]
    restant = min(limites) if limites else None
    tele = _Telechargement([], [], [], [])
    pris: set[str] = set()
    for index, piece in enumerate(pieces):
        if index >= _MAX_PIECES:
            tele.ratees.append((piece.filename, "au-delà de 10"))
            continue
        if restant is not None and piece.size > restant:
            tele.ratees.append((piece.filename, "trop lourde"))
            continue
        spoiler = _est_spoiler(piece)
        try:
            fichier = await piece.to_file(use_cached=True, spoiler=spoiler)
        except Exception as e:  # noqa: BLE001 — attendu : Discord a déjà purgé la pièce
            logger.info("journal de modération : pièce {n} indisponible : {e!r}", n=piece.filename, e=e)
            tele.ratees.append((piece.filename, "plus disponible"))
            continue
        donnees = fichier.fp.read()
        if restant is not None:
            restant -= piece.size
        # Le préfixe est retiré AVANT l'assainissement et le dédoublonnage,
        # puis reposé : un `1_SPOILER_x.png` ne serait plus un spoiler.
        base = _nom_disponible(_assainir(fichier.filename.removeprefix(_PREFIXE_SPOILER)), pris)
        pris.add(base)
        nom = f"{_PREFIXE_SPOILER}{base}" if spoiler else base
        tele.recuperees.append(_PieceRecuperee(nom=nom, origine=piece.filename,
                                               donnees=donnees, spoiler=spoiler))
        ref = Piece(f"attachment://{nom}", spoiler=spoiler)
        image = (piece.content_type or "").startswith("image/")
        (tele.medias if image else tele.autres).append(ref)
    return tele


def _fichiers_frais(pieces: list[_PieceRecuperee]) -> list[discord.File]:
    """Un `discord.File` neuf par pièce : un `File` déjà envoyé est consommé."""
    return [discord.File(io.BytesIO(p.donnees), filename=p.nom, spoiler=p.spoiler) for p in pieces]


def _sans_fichiers(tele: _Telechargement) -> _Telechargement:
    """La même fiche, pièces récupérées déplacées dans la liste des non publiées."""
    refusees = [(p.origine, "envoi des fichiers refusé") for p in tele.recuperees]
    return _Telechargement([], [], [], tele.ratees + refusees)


async def _publier_partout(salons: list[Any], construire: Callable[[_Telechargement], discord.ui.LayoutView],
                           tele: _Telechargement = _SANS_PIECE) -> None:
    vue = construire(tele)
    for salon in salons:
        try:
            await salon.send(view=vue, files=_fichiers_frais(tele.recuperees),
                             allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden as e:
            if not tele.recuperees:
                logger.warning("journal de modération : envoi refusé dans {c} : {e!r}",
                               c=getattr(salon, "id", "?"), e=e)
                continue
            # Le cas courant : le salon accepte le texte mais pas les pièces
            # jointes. Sans ce repli, chaque suppression avec image perdait sa
            # fiche entière dans ce salon, à chaque fois.
            logger.warning("journal de modération : {c} refuse les fichiers (permission « Joindre des "
                           "fichiers » manquante ?), fiche renvoyée sans pièces : {e!r}",
                           c=getattr(salon, "id", "?"), e=e)
            try:
                await salon.send(view=construire(_sans_fichiers(tele)),
                                 allowed_mentions=discord.AllowedMentions.none())
            except Exception as e2:  # noqa: BLE001 — un salon en échec ne prive pas les autres
                logger.warning("journal de modération : envoi sans pièces impossible dans {c} : {e!r}",
                               c=getattr(salon, "id", "?"), e=e2)
        except Exception as e:  # noqa: BLE001 — un salon en échec ne prive pas les autres
            logger.warning("journal de modération : envoi impossible dans {c} : {e!r}",
                           c=getattr(salon, "id", "?"), e=e)


async def message_supprime(bot: "WallyDiscord", payload: Any) -> None:
    try:
        salons = _salons_cibles(bot, payload.guild_id, payload.channel_id)
        if not salons:
            return
        msg = payload.cached_message
        source: Any = bot.get_channel(payload.channel_id)
        if msg is not None:
            source = source or msg.channel
            auteur = msg.author
            meta_auteur = f"<@{auteur.id}> ({discord.utils.escape_markdown(auteur.name)})"
            vignette = url_avatar(auteur)
            contenu = (msg.content or "").strip()
            bloc_contenu = _citer(contenu) if contenu else "*aucun texte*"
            pieces = list(msg.attachments)
        else:
            meta_auteur = "inconnu"
            vignette = None
            bloc_contenu = "*contenu non disponible*"
            pieces = []
        meta = (f"**Auteur** {meta_auteur} · **Salon** {_mention_salon(payload.channel_id, source)} · "
               f"**Message** {payload.message_id}")
        tele = await _telecharger_pieces(salons, pieces, nsfw=_salon_nsfw(source))
        heure = maintenant().strftime("%Hh%M")

        def construire(t: _Telechargement) -> discord.ui.LayoutView:
            corps = [meta, bloc_contenu]
            if t.ratees:
                corps.append(_bloc_non_recuperees(t.ratees))
            return fiche("🗑️ Message supprimé", corps, accent=ACCENT_ALERTE, vignette=vignette,
                         medias=t.medias, fichiers=t.autres, pied=f"Supprimé à {heure}")

        await _publier_partout(salons, construire, tele)
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
        salons = _salons_cibles(bot, guild_id, after.channel.id)
        if not salons:
            return
        auteur = after.author
        meta = (f"**Auteur** <@{auteur.id}> ({discord.utils.escape_markdown(auteur.name)}) · "
               f"**Salon** {_mention_salon(after.channel.id, after.channel)} · "
               f"**Message** {after.id} · [aller au message]({after.jump_url})")
        tele = await _telecharger_pieces(salons, retirees, nsfw=_salon_nsfw(after.channel))

        def construire(t: _Telechargement) -> discord.ui.LayoutView:
            corps = [meta, _bloc_cite("Avant", avant), _bloc_cite("Après", apres)]
            if t.ratees:
                corps.append(_bloc_non_recuperees(t.ratees))
            return fiche("✏️ Message modifié", corps, accent=ACCENT_ALERTE, vignette=url_avatar(auteur),
                         medias=t.medias, fichiers=t.autres)

        await _publier_partout(salons, construire, tele)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : modification non journalisée : {e!r}", e=e)


async def messages_supprimes_en_masse(bot: "WallyDiscord", payload: Any) -> None:
    """Purge ou historique effacé par un ban : `on_raw_bulk_message_delete`.

    Pas de téléchargement de pièces jointes ici — un pan entier d'historique
    d'un coup, ce n'est plus une pièce à récupérer mais un événement à
    signaler. La liste des auteurs/extraits ne porte que les messages en
    cache (`cached_messages`), bornée pour tenir dans le budget V2.
    """
    try:
        salons = _salons_cibles(bot, payload.guild_id, payload.channel_id)
        if not salons:
            return
        source = bot.get_channel(payload.channel_id)
        meta = (f"**Salon** {_mention_salon(payload.channel_id, source)} · "
                f"**Messages** {len(payload.message_ids)}")
        lignes = []
        for msg in payload.cached_messages:
            auteur = discord.utils.escape_markdown(getattr(msg.author, "name", "inconnu"))
            contenu = _echapper((msg.content or "").strip())
            extrait = _borner(contenu, _MAX_EXTRAIT) if contenu else "*aucun texte*"
            lignes.append(f"**{auteur}** : {extrait}")
        corps = [meta]
        if lignes:
            corps.append(_borner_lignes(lignes, _MAX_CITATION))
        vue = fiche("🧹 Suppression en masse", corps, accent=ACCENT_ALERTE)
        await _publier_partout(salons, lambda _t: vue)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : suppression en masse non journalisée : {e!r}", e=e)


async def vocal_cree(bot: "WallyDiscord", member: Any, salon: Any) -> None:
    try:
        cibles = _salons_cibles(bot, salon.guild.id, None)
        if not cibles:
            return
        meta = f"**Par** <@{member.id}> · **Salon** {salon.name} · **ID** {salon.id}"
        vue = fiche("🔊 Canal vocal créé", [meta], accent=_COULEUR_VOCAL)
        await _publier_partout(cibles, lambda _t: vue)
    except Exception as e:  # noqa: BLE001 — jamais lever, appelé depuis salons_temporaires
        logger.warning("journal de modération : création vocale non journalisée : {e!r}", e=e)


async def vocal_supprime(bot: "WallyDiscord", salon: Any) -> None:
    try:
        cibles = _salons_cibles(bot, salon.guild.id, None)
        if not cibles:
            return
        meta = f"**Salon** {salon.name} · **ID** {salon.id}"
        vue = fiche("🔇 Canal vocal supprimé", [meta], accent=_COULEUR_VOCAL)
        await _publier_partout(cibles, lambda _t: vue)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : suppression vocale non journalisée : {e!r}", e=e)
