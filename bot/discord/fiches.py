"""Les fiches Discord de Wally, en Components V2.

Un `Container` accentué, un titre, un corps, un pied — la forme partagée par
`/status`, `/mood`, `/reload-persona` et les annonces de memes. Elle vit ici
parce que quatre appelants la voulaient identique le même jour ; sans ça,
chacun recopiait le même arbre à trois composants près.

⚠️ Un message en Components V2 plafonne à **4000 caractères pour TOUS les
`TextDisplay` réunis**, là où une description d'embed en tenait 4096 à elle
seule. Un corps qui vient de l'extérieur (liste de fichiers, rapport) se borne
AVANT d'arriver ici.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import discord

# Les accents des fiches. Ceux des émotions sont ceux du dashboard — une même
# couleur pour une même chose, à l'écran comme dans Discord.
ACCENT_NEUTRE = 0x5865F2      # blurple Discord
ACCENT_OK = 0x22C55E
ACCENT_ALERTE = 0xE67E22
ACCENTS_EMOTION = {
    "anger": 0xEF4444,
    "joy": 0xEAB308,
    "sadness": 0x3B82F6,
    "curiosity": 0x22C55E,
    "boredom": 0xA855F7,
}


class Piece(NamedTuple):
    """Une référence de `medias` / `fichiers` qui porte son drapeau spoiler.

    Une simple chaîne reste acceptée partout : elle vaut `Piece(url)`.
    """
    url: str
    spoiler: bool = False


def borner(texte: str, limite: int) -> str:
    """Tronque `texte` à `limite` caractères AU PLUS, « … » compris.

    Le tronc commun des bornages de corps venus de l'extérieur (cf. le
    plafond de 4000 ci-dessus). Chaque appelant garde son étape propre —
    échappement Markdown, `@` neutralisés — autour de cet appel.
    """
    if len(texte) <= limite:
        return texte
    return texte[: limite - 1] + "…"


def _piece(ref: str | Piece) -> Piece:
    return ref if isinstance(ref, Piece) else Piece(ref)


def fiche(titre: str, corps: Sequence[str], *, accent: int = ACCENT_NEUTRE,
          vignette: str | None = None, pied: str | None = None,
          medias: Sequence[str | Piece] = (),
          fichiers: Sequence[str | Piece] = ()) -> discord.ui.LayoutView:
    """Une fiche à un seul conteneur.

    `corps` est une liste de BLOCS : chacun devient un `TextDisplay`, séparés
    d'un trait. Les blocs vides sont ignorés — un rapport dont une section est
    absente ne doit pas laisser un trait sur du vide.

    `vignette` place le titre en `Section` avec l'image en accessoire (avatar,
    aperçu). `medias` pose une galerie sous le corps : jusqu'à dix images, ce
    qu'un embed ne savait pas faire.

    ⚠️ En Components V2, une pièce jointe que RIEN ne référence n'est pas
    affichée du tout — elle ne tombe pas en bas du message comme avant, elle
    disparaît. Tout fichier envoyé avec la fiche doit donc passer par `medias`
    (galerie d'images) ou par `fichiers` (composant `File`, pour ce qu'une
    galerie ne montre pas : vidéos, archives). `Thumbnail` et galerie ne
    prennent que des images — la doc Discord l'écrit pour la vignette.

    Une entrée `Piece(url, spoiler=True)` pose l'image ou le fichier SOUS
    SPOILER : le drapeau vit dans le composant, pas seulement dans le nom
    du fichier envoyé.
    """
    blocs = [b for b in corps if b]
    contenu: list[discord.ui.Item] = []
    if vignette:
        contenu.append(discord.ui.Section(
            discord.ui.TextDisplay(f"## {titre}"),
            accessory=discord.ui.Thumbnail(vignette),
        ))
    else:
        contenu.append(discord.ui.TextDisplay(f"## {titre}"))
    for bloc in blocs:
        contenu.append(discord.ui.Separator())
        contenu.append(discord.ui.TextDisplay(bloc))
    if medias:
        galerie: discord.ui.MediaGallery = discord.ui.MediaGallery()
        for media in map(_piece, medias):
            galerie.add_item(media=media.url, spoiler=media.spoiler)
        contenu.append(galerie)
    for fichier in map(_piece, fichiers):
        contenu.append(discord.ui.File(fichier.url, spoiler=fichier.spoiler))
    if pied:
        contenu.append(discord.ui.TextDisplay(f"-# {pied}"))

    vue = discord.ui.LayoutView(timeout=None)
    vue.add_item(discord.ui.Container(*contenu, accent_colour=discord.Colour(accent)))
    return vue


def url_avatar(utilisateur: object) -> str | None:
    """L'avatar d'un membre, ou None si l'objet n'en porte pas de lisible.

    Un `Thumbnail` construit sur autre chose qu'une chaîne part à l'API et
    revient en 400 : ce garde est ce qui permet d'appeler `fiche()` sans savoir
    si l'utilisateur est complet (un bot pas encore connecté n'a pas de `user`).
    """
    url = getattr(getattr(utilisateur, "display_avatar", None), "url", None)
    return url if isinstance(url, str) else None
