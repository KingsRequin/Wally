"""Journal de modération — repris du bot Node `wally-discord`.

Une fiche Components V2 par geste dans le salon de logs : message supprimé,
message modifié, suppression en masse. C'est un outil de MODÉRATION, pas de
la perception : il couvre aussi les messages de bots et les serveurs que la
perception de Wally ignore (`ignored_guilds`).

Ce module est aussi le TRONC COMMUN du reste du journal : `salons_cibles`,
`publier_partout`, `horodatage` et `pied_utilisateur` sont partagés par
`bot/discord/journal_vocal.py` (salon vocal temporaire créé/supprimé,
mouvements vocaux), qui les importe au lieu de les réimplémenter.

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

La carte d'un message SUPPRIMÉ part en tâche de fond : elle attend deux
secondes avant de lire le journal d'audit du serveur (Discord n'y écrit pas à
l'instant de la suppression), et cette attente ne doit retarder qu'elle —
jamais les autres événements du bot.
"""
from __future__ import annotations

import asyncio
import difflib
import io
import re
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple

import discord
from loguru import logger

from bot.core.temps import maintenant
from bot.discord.fiches import ACCENT_ALERTE, Piece, borner, fiche, url_avatar

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_MAX_CITATION = 1500           # budget V2 total (4000) réparti entre les blocs cités
_MAX_NON_RECUPEREES = 500      # budget de la liste des pièces non récupérées
_MAX_EXTRAIT = 120             # extrait par message d'une suppression en masse
_MAX_PIECES = 10                # plafond d'upload Discord pour un message
_PREFIXE_SPOILER = "SPOILER_"  # la convention de nom de Discord pour une pièce sous spoiler

# `discord.File.uri` l'exige (doc) : Discord traite le reste EN SILENCE côté
# serveur — un nom hors de cet alphabet rend un `attachment://` mort.
_CARACTERES_SURS = re.compile(r"[^A-Za-z0-9_.-]")

_DELAI_AUDIT = 2.0             # Discord n'écrit pas dans l'audit à l'instant du geste
_FENETRE_AUDIT = 10.0          # au-delà, une entrée n'est plus « la nôtre » par sa seule fraîcheur
_ENTREES_AUDIT_LUES = 10       # les dernières entrées lues à chaque recoupement
_MAX_COMPTEURS_AUDIT = 50      # compteurs mémorisés PAR SERVEUR (borne de la mémoire)
_GHOST_PING_SECONDES = 300.0   # au-delà, un message mentionnant n'est plus un ghost ping
_MAX_MENTIONS = 400            # budget du bloc « Mentionnait »

# Une rafale de gestes du même (serveur, action) — suppressions en masse,
# plusieurs bans en quelques secondes — partage la lecture d'audit au lieu
# d'une lecture d'API PAR ÉVÉNEMENT. Quelques secondes seulement : c'est le
# délai qu'on accepte de vivre avec un train d'entrées légèrement périmé.
_FENETRE_CACHE_LECTURE = 2.0
_MAX_CACHE_LECTURE = 100       # bornage du cache, même famille que _MAX_COMPTEURS_AUDIT

#: Le dernier `extra.count` vu pour chaque entrée d'audit, par serveur :
#: `{guild_id: {entry_id: count}}`. En RAM seulement — le perdre au
#: redémarrage coûte au pire une fausse négative (« l'auteur ou un bot » là
#: où un modo avait supprimé). Borné par serveur, les plus anciennes entrées
#: évincées les premières : sans borne, un serveur actif ferait croître ce
#: dictionnaire pour la durée de vie du process.
_compteurs_audit: dict[int, OrderedDict[int, int]] = {}

#: Les serveurs dont le journal d'audit nous est refusé et qui ont déjà été
#: signalés : un WARNING par suppression noierait les logs.
_audit_refuse: set[int] = set()

#: La dernière lecture d'audit par `(guild_id, action)` : `(entrées, instant
#: de la lecture)`. Partagée par tous les appels d'`entree_audit()` qui
#: tombent dans `_FENETRE_CACHE_LECTURE` — jamais un VERDICT, seulement la
#: liste brute (cf. la docstring d'`entree_audit`). Bornée en LRU, même
#: famille que `_compteurs_audit`.
_cache_lecture: "OrderedDict[tuple[int, Any], tuple[list[Any], datetime]]" = OrderedDict()


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


def _epoch(dt: datetime) -> int:
    """L'epoch Unix d'un datetime CONSCIENT du fuseau.

    `dt` DOIT porter son `tzinfo` — sinon `ValueError` : un datetime naïf ne
    dit pas à quel fuseau se réfère l'epoch calculé, et mieux vaut lever que
    publier une heure fausse en silence. `bot/core/temps.py::maintenant()` et
    les horodatages `created_at` / `edited_at` de discord.py le sont déjà.
    """
    if dt.tzinfo is None:
        raise ValueError("un horodatage Discord exige un datetime conscient du fuseau (tzinfo posé)")
    return int(dt.timestamp())


def horodatage(dt: datetime) -> str:
    """Horodatage Discord natif : absolu puis relatif, dans le fuseau du LECTEUR.

    `<t:unix:f>` (date et heure complètes) suivi de `<t:unix:R>` (« il y a
    2 minutes ») entre parenthèses — Discord les rend dans le fuseau de
    chaque personne qui lit le salon, là où un `strftime` figeait l'heure de
    Wally (Europe/Paris) pour tout le monde. Fabrique partagée par toutes
    les cartes du tronc commun (T1-T4) : suppression, édition, suppression
    en masse, salon vocal créé/supprimé, à venir membres et mouvements
    vocaux.

    `dt` DOIT être conscient du fuseau (`tzinfo` posé) — sinon `ValueError` :
    un datetime naïf ne dit pas à quel fuseau se réfère l'epoch calculé,
    mieux vaut lever que publier une heure fausse en silence.
    `bot/core/temps.py::maintenant()` et les horodatages `created_at` /
    `edited_at` de discord.py le sont déjà.
    """
    epoch = _epoch(dt)
    return f"<t:{epoch}:f> (<t:{epoch}:R>)"


def _relatif(dt: datetime) -> str:
    """Horodatage Discord RELATIF seul : « il y a 3 minutes ».

    L'âge d'un message supprimé se lit d'un coup d'œil sous cette forme, là
    où la date complète de `horodatage()` ferait doublon avec l'heure de
    suppression affichée juste à côté.
    """
    return f"<t:{_epoch(dt)}:R>"


def pied_utilisateur(user: Any) -> str:
    """Le pied de fiche « id utilisateur », en code inline copiable au clic.

    Remplace l'ancien pied « Supprimé à HHhMM » : une fiche qui vise un
    utilisateur précis (auteur d'un message, créateur d'un salon vocal) porte
    désormais son id BRUT en pied — les backticks en font un bloc de code que
    Discord laisse copier d'un clic, utile pour recouper avec `/ban`, une
    recherche mémoire, etc. Fabrique partagée avec T2-T4 : toute carte future
    qui vise un utilisateur unique s'en sert au lieu de réinventer le format.

    Pas de fiche pour un événement sans utilisateur SEUL et identifié
    (suppression en masse, salon vocal supprimé) : mieux vaut l'absence de
    pied qu'un id inventé.
    """
    return f"ID `{user.id}`"


def _echapper(texte: str) -> str:
    return texte.replace("@", "@\u200b")


def _borner(texte: str, limite: int) -> str:
    borne = borner(texte, limite)
    tronque = borne != texte
    # `_echapper` neutralise un `@` avec un zero-width space qui le SUIT :
    # couper pile entre les deux laisserait un `@` isolé, à nouveau ACTIF
    # (mention réelle) alors que le but de l'échappement était de l'éteindre.
    if tronque and borne[:-1].endswith("@"):
        borne = borne[:-2] + "…"
    # `escape_markdown` protège un délimiteur avec un `\` qui le PRÉCÈDE :
    # couper pile juste après ce backslash le laisserait seul devant
    # l'ellipse, sans rien à échapper — même geste que ci-dessus, pour un
    # backslash mort plutôt qu'une mention ressuscitée.
    elif tronque and borne[:-1].endswith("\\"):
        borne = borne[:-2] + "…"
    return borne


def _recap(n: int) -> str:
    return f"… et {n} autre" if n == 1 else f"… et {n} autres"


def borner_lignes(lignes: list[str], limite: int) -> str:
    """Borne une liste de lignes par lignes ENTIÈRES.

    `_borner` coupe au caractère près : sur `**auteur** : extrait`, la
    coupure peut tomber au milieu du marqueur `**`, laissant tout le RESTE du
    message en gras. Les lignes qui ne tiennent plus deviennent une seule
    ligne récapitulative « … et N autre(s) ».

    Publique : réutilisée par `bot/discord/journal_vocal.py` pour borner sa
    liste de participants (une mention par « ligne ») — pas de troisième
    fonction de bornage à écrire pour la même règle.
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


def _mots(texte: str) -> list[str]:
    """Tokenise en alternance mot / espace(s).

    La diff ne touche alors QUE les mots : les passages inchangés gardent
    leurs espaces et retours à la ligne d'origine, au lieu d'être reconstruits
    au mot près.
    """
    return re.findall(r"\S+|\s+", texte)


def _decouper_espaces(texte: str) -> tuple[str, str, str]:
    """Sépare `texte` en (espaces de tête, cœur, espaces de queue).

    Sert à l'empan APRÈS d'un changement : ses espaces de bord restent hors du
    gras (un espace À L'INTÉRIEUR de `**…**` casse le rendu Discord) sans être
    perdus. Cœur vide (texte fait QUE d'espaces) → tout part dans `tete`,
    `queue` reste vide.
    """
    coeur = texte.strip()
    if not coeur:
        return texte, "", ""
    tete = texte[: len(texte) - len(texte.lstrip())]
    queue = texte[len(texte.rstrip()):]
    return tete, coeur, queue


# Un délimiteur Markdown à VIF sur le bord d'un mot marqué (`~~mot~~` / `**mot**`)
# colle à notre propre marqueur et forme un run de 3+ caractères identiques que
# Discord (ou un lecteur humain) peut relire comme un AUTRE marqueur — même si
# ce délimiteur est lui-même échappé (`\*`) : le backslash n'échappe QUE le
# caractère qui le suit, pas ceux que NOUS lui accolons.
_DELIMITEURS_MARQUAGE = set("*~_|`")


# Tout ce que `str.splitlines()` coupe, avec les espaces qui l'entourent : la
# citation `> ` découpe le bloc par CES fins de ligne-là, et Discord ne porte ni
# le gras ni le barré d'une ligne citée à la suivante.
_SAUT_DE_LIGNE = re.compile(r"(\s*[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]\s*)")


def _marque(texte: str, marqueur: str) -> str:
    """Encadre `texte` (sans espace de bord) du `marqueur` (`~~`/`**`).

    Ligne par ligne : chaque segment reçoit sa propre paire de marqueurs, les
    sauts de ligne et les espaces qui les bordent restent dehors — un `**`
    ouvert sur une ligne et fermé sur la suivante s'afficherait en clair une
    fois le bloc cité. Les lignes vides, avalées par le séparateur, ne portent
    aucun marqueur. Sur chaque segment, un espace de largeur nulle s'intercale
    entre le marqueur et un bord qui est un délimiteur Markdown.
    """
    morceaux = _SAUT_DE_LIGNE.split(texte)
    for i in range(0, len(morceaux), 2):  # indices pairs : les segments
        segment = morceaux[i]
        debut = "\u200b" if segment[0] in _DELIMITEURS_MARQUAGE else ""
        fin = "\u200b" if segment[-1] in _DELIMITEURS_MARQUAGE else ""
        morceaux[i] = f"{marqueur}{debut}{segment}{fin}{marqueur}"
    return "".join(morceaux)


def _diff_mots(avant: str, apres: str) -> str | None:
    """Diff mot à mot : supprimé en `~~barré~~`, ajouté en `**gras**`, le
    reste tel quel. `avant`/`apres` doivent déjà être markdown- (et `@`-)
    échappés par l'appelant : poser les marqueurs sur du markdown non échappé
    romprait la mise en forme de Wally, pas celle de l'auteur du message.

    Rend `None` si l'édition réécrit plus de la MOITIÉ du texte — mesuré sur
    les MOTS seuls, les espaces étant exclus du ratio (des espaces identiques
    matcheraient presque toujours et gonfleraient artificiellement la
    similarité). L'appelant retombe alors sur des blocs Avant/Après complets,
    plus lisibles qu'un diff qui barre/regraisse la quasi-totalité du texte.

    Le rendu est le texte APRÈS, caractère pour caractère (espaces, tabulations
    et retours à la ligne compris), où les ajouts sont mis en gras et où chaque
    suppression est glissée comme un îlot `~~…~~` porteur de SON séparateur :
    un espace qui le précède, ou qui le suit s'il ouvre le message. Retirer ces
    îlots rend donc exactement l'APRÈS. Un changement d'espaces seuls ne porte
    aucun marqueur : on n'en garde que l'espacement APRÈS.
    """
    mots_avant, mots_apres = _mots(avant), _mots(apres)
    reels_avant = [m for m in mots_avant if m.strip()]
    reels_apres = [m for m in mots_apres if m.strip()]
    ratio = difflib.SequenceMatcher(None, reels_avant, reels_apres, autojunk=False).ratio()
    if ratio < 0.5:
        return None
    sm = difflib.SequenceMatcher(None, mots_avant, mots_apres, autojunk=False)
    resultat = ""
    # Fin de l'îlot qui ouvre le message, séparateur compris : un îlot suivant
    # ne remonte jamais en deçà, sinon les deux se disputeraient le même espace.
    plancher = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        empan_apres = "".join(mots_apres[j1:j2])
        if tag == "equal":
            resultat += empan_apres
            continue
        supprime = "".join(mots_avant[i1:i2]).strip()
        if supprime:
            # L'îlot se pose AVANT les espaces qui terminent déjà le rendu :
            # à sa gauche un mot, un marqueur ou le séparateur d'un îlot (ou
            # rien), à sa droite un espace (ou la suite de l'empan, qui
            # commence forcément par un espace — les tokens alternent mot /
            # espaces). Il ne touche ainsi jamais un autre caractère visible,
            # donc ni mot collé ni run `[*~]{3,}`.
            corps = resultat[:max(len(resultat.rstrip()), plancher)]
            barre = _marque(supprime, "~~")
            if corps:
                resultat = f"{corps} {barre}{resultat[len(corps):]}"
            else:
                # Rien à gauche : le séparateur passe à droite. Il y a
                # toujours une suite — sans aucun mot APRÈS, le ratio vaut 0
                # et on est déjà reparti sur le repli.
                resultat = f"{barre} {resultat}"
                plancher = len(barre) + 1
        tete, ajoute, queue = _decouper_espaces(empan_apres)
        # Cœur vide (changement d'espaces seuls, ou suppression pure) :
        # l'espacement APRÈS passe tel quel, sans marqueur.
        resultat += f"{tete}{_marque(ajoute, '**')}{queue}" if ajoute else empan_apres
    return resultat


def _citer_deja_echappe(texte: str, *, limite: int = _MAX_CITATION) -> str:
    """Comme `_citer`, sans rééchapper.

    Réservé aux blocs dont le texte est déjà markdown/`@`-échappé AVANT
    d'arriver ici — le diff d'édition (marqueurs `~~`/`**` posés par
    `_diff_mots`) et son repli Avant/Après, échappés du MÊME geste par
    l'appelant. Rééchapper ici doublerait le zero-width space posé après
    chaque `@`.
    """
    cite = "\n".join(f"> {ligne}" for ligne in texte.splitlines())
    borne = _borner(cite, limite)
    if borne == cite:
        return borne
    # La coupure au caractère près peut tomber DANS un marqueur du diff : un
    # `*`/`~` isolé ou un `**`/`~~` resté ouvert s'afficherait en clair sur la
    # dernière ligne. On recule jusqu'avant ce marqueur. Une séquence échappée
    # (`\*`, mais aussi `\\` suivi d'un vrai marqueur) est consommée d'abord,
    # et les marqueurs du diff ne s'imbriquent jamais : un seul reste ouvert.
    debut_ligne = borne.rfind("\n") + 1
    ligne = borne[debut_ligne:-1]
    ouvert: re.Match[str] | None = None
    for jeton in re.finditer(r"\\.|\*\*|~~|[*~]$", ligne):
        if jeton.group()[0] == "\\":
            continue
        if ouvert is None:
            ouvert = jeton
        elif jeton.group() == ouvert.group():
            ouvert = None
    if ouvert is not None:
        ligne = ligne[:ouvert.start()]
    return f"{borne[:debut_ligne]}{ligne}…"


def _bloc_deja_echappe(titre: str, texte: str) -> str:
    corps = _citer_deja_echappe(texte) if texte.strip() else "*aucun texte*"
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


def salons_cibles(bot: "WallyDiscord", guild_id: int | None, salon_source_id: int | None,
                  salon_source: Any = None) -> list[Any]:
    """Résout les salons de logs CONFIGURÉS, ou [] si rien à publier.

    Brique PUBLIQUE partagée par tout le tronc commun du journal (T1-T4) :
    `bot/discord/journal_vocal.py` et `bot/discord/journal_membres.py`
    l'importent au lieu de réimplémenter la résolution des salons.

    `salon_ids` vide → désactivé ; guild hors `guild_ids` → rien. Un salon
    introuvable ne bloque pas les autres : WARNING nommant son id, la
    résolution continue sur le reste.

    Un événement né DANS un salon de logs ne se journalise pas : un salon de
    logs peut vivre dans un serveur observé, et supprimer une fiche (ou
    purger le salon) la republiait aussitôt dans chaque salon de logs — une
    fiche qu'on ne pouvait plus jamais effacer. Un FIL ouvert sous un salon
    de logs compte pour ce salon : son id propre n'est pas dans `salon_ids`,
    celui de son parent (`salon_source.parent_id`) si.
    """
    cfg = bot.config.discord.journal_moderation
    if not cfg.salon_ids or guild_id not in cfg.guild_ids:
        return []
    parent_id = getattr(salon_source, "parent_id", None)
    if any(i is not None and i in cfg.salon_ids for i in (salon_source_id, parent_id)):
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


async def publier_partout(salons: list[Any], construire: Callable[[_Telechargement], discord.ui.LayoutView],
                          tele: _Telechargement = _SANS_PIECE) -> None:
    """Envoie la vue construite par `construire` sur chaque salon, sans jamais lever.

    Brique PUBLIQUE partagée par tout le tronc commun du journal (T1-T4) :
    `bot/discord/journal_vocal.py` et `bot/discord/journal_membres.py`
    l'importent pour leurs propres cartes au lieu de réimplémenter l'envoi
    multi-salons. Un salon en échec (permissions, pièces refusées) ne prive
    jamais les autres — cf. le détail des replis ci-dessous.
    """
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


class Recoupement(NamedTuple):
    """Ce qu'a rendu la lecture du journal d'audit.

    `lisible` sépare « le journal dit qu'il n'y a rien » de « on n'a pas pu
    le lire » : l'appelant se tait dans le second cas au lieu d'affirmer une
    absence qu'il n'a pas constatée.
    """
    entree: Any | None
    lisible: bool


async def entree_audit(guild: Any, action: Any, *, cible_id: int, salon_id: int | None = None,
                       fenetre: float = _FENETRE_AUDIT,
                       horloge: Callable[[], datetime] = maintenant) -> Recoupement:
    """Recoupe un geste de modération avec le journal d'audit du serveur.

    Discord ne relie AUCUNE entrée d'audit à l'objet touché (message, membre) :
    la seule méthode est de lire les dernières entrées de `action` et de
    retenir la plus récente qui vise `cible_id` (et `salon_id`, quand l'action
    en porte un) assez fraîchement pour être la nôtre. Deux critères, l'un OU
    l'autre :

    - l'entrée a été créée il y a moins de `fenetre` secondes ;
    - son `extra.count` a AUGMENTÉ depuis la dernière lecture. Discord
      REGROUPE en effet les suppressions de messages : un même modo qui
      supprime un deuxième message du même auteur dans le même salon n'ouvre
      pas de nouvelle entrée, il incrémente le compteur de la précédente —
      sans cette comparaison, la deuxième suppression paraîtrait non tracée
      dès que l'entrée a dépassé `fenetre`. Les actions sans compteur (kick,
      ban, modification de membre) ne jouent donc que sur la fraîcheur.

    Générique par construction : `action` et `cible_id` suffisent, `salon_id`
    ne filtre que si on le passe. L'appelant décide du délai d'attente avant
    l'appel — il n'est pas le même pour une suppression de message et pour un
    départ de membre.

    **Cache de lecture** (`_cache_lecture`) : une rafale de gestes du même
    `(guild, action)` en quelques secondes (suppressions en masse, plusieurs
    bans à la suite) ne déclenche qu'UNE lecture d'API, partagée par tous les
    appels qui tombent dans `_FENETRE_CACHE_LECTURE`. On cache la LISTE
    d'entrées brute, JAMAIS un verdict : deux appels de la fenêtre peuvent
    viser des `cible_id`/`salon_id` différents, et chacun rejoue SON PROPRE
    recoupement (et sa propre mise à jour de `_compteurs_audit`) sur ces mêmes
    entrées — l'heuristique de compteur ci-dessus reste donc correcte même à
    l'intérieur d'une fenêtre de cache. Un échec de lecture n'est jamais mis
    en cache : le prochain appel retente, comme avant.

    Ne lève JAMAIS. Journal illisible (permission « Voir les logs du serveur »
    manquante, serveur hors cache, API en panne) → `lisible=False`, et un seul
    WARNING par serveur pour la permission : un par geste noierait les logs.
    """
    if guild is None:
        return Recoupement(None, False)
    instant = horloge()
    cle_cache = (guild.id, action)
    en_cache = _cache_lecture.get(cle_cache)
    if en_cache is not None and (instant - en_cache[1]).total_seconds() < _FENETRE_CACHE_LECTURE:
        entrees = en_cache[0]
        _cache_lecture.move_to_end(cle_cache)
    else:
        entrees = []
        try:
            async for entree in guild.audit_logs(limit=_ENTREES_AUDIT_LUES, action=action):
                entrees.append(entree)
        except discord.Forbidden as e:
            if guild.id not in _audit_refuse:
                _audit_refuse.add(guild.id)
                logger.warning("journal de modération : journal d'audit refusé sur le serveur {g} "
                               "(permission « Voir les logs du serveur » manquante ?) — plus "
                               "d'avertissement pour ce serveur : {e!r}", g=guild.id, e=e)
            return Recoupement(None, False)
        except Exception as e:  # noqa: BLE001 — l'audit est un CONFORT, la carte part sans lui
            logger.warning("journal de modération : journal d'audit illisible sur le serveur {g} : {e!r}",
                           g=getattr(guild, "id", "?"), e=e)
            return Recoupement(None, False)
        _cache_lecture[cle_cache] = (entrees, instant)
        _cache_lecture.move_to_end(cle_cache)
        while len(_cache_lecture) > _MAX_CACHE_LECTURE:
            _cache_lecture.popitem(last=False)

    memoire = _compteurs_audit.setdefault(guild.id, OrderedDict())
    retenue: Any | None = None
    for entree in entrees:
        extra = getattr(entree, "extra", None)
        compte = getattr(extra, "count", None)
        connu = memoire.get(entree.id)
        if isinstance(compte, int):
            memoire[entree.id] = compte
            memoire.move_to_end(entree.id)   # vu le plus récemment : évincé en dernier
        # La boucle continue APRÈS une correspondance : les compteurs des
        # entrées suivantes doivent rester à jour, sinon la prochaine
        # suppression les croira toutes incrémentées.
        if retenue is not None or getattr(entree.target, "id", None) != cible_id:
            continue
        if salon_id is not None and getattr(getattr(extra, "channel", None), "id", None) != salon_id:
            continue
        fraiche = (instant - entree.created_at).total_seconds() < fenetre
        incremente = isinstance(compte, int) and connu is not None and compte > connu
        if fraiche or incremente:
            retenue = entree
    while len(memoire) > _MAX_COMPTEURS_AUDIT:
        memoire.popitem(last=False)
    return Recoupement(retenue, True)


def _ligne_supprime_par(recoupement: Recoupement) -> str:
    """Le fragment « · **Supprimé par** … » de la carte, ou "" si on ne sait rien.

    Journal illisible : aucune ligne — affirmer quoi que ce soit serait
    inventer. Lisible mais sans entrée : Discord ne journalise JAMAIS la
    suppression par l'auteur lui-même ni par un bot (discord-api-docs #656,
    #1611), et c'est en soi l'information.
    """
    if not recoupement.lisible:
        return ""
    if recoupement.entree is None:
        return " · **Supprimé par** l'auteur ou un bot (Discord ne le trace pas)"
    modo = getattr(recoupement.entree, "user", None)
    if modo is None:
        return ""   # entrée trouvée mais son auteur n'est plus résolvable : on ne nomme personne
    return f" · **Supprimé par** <@{modo.id}>"


def _mentions_rendues(msg: Any) -> str:
    """Les mentions d'un message supprimé, rendues sans notifier personne.

    `raw_mentions` / `raw_role_mentions` donnent les ids même quand le membre
    ou le rôle n'est plus résolvable en cache. `<@id>` et `<@&id>` s'affichent
    en clair chez le lecteur, et l'envoi passe déjà en `AllowedMentions.none()` :
    personne n'est notifié une seconde fois. `@everyone` / `@here` n'ont pas
    de forme d'id — ils partent en TEXTE, `@` neutralisé, parce qu'un
    `@everyone` à vif republié dans le salon de logs est exactement ce que
    l'échappement de ce module existe pour éviter.

    L'auteur sort de sa propre liste : Discord ne notifie PERSONNE quand on se
    mentionne soi-même, donc un message où l'auteur se cite n'a fait sonner
    personne — le titrer « ghost ping » serait une accusation sans victime.
    Les rôles restent, eux, même un rôle que l'auteur porte : il notifie tous
    les AUTRES membres de ce rôle.
    """
    rendues = [f"<@{uid}>" for uid in msg.raw_mentions if uid != msg.author.id]
    rendues += [f"<@&{rid}>" for rid in msg.raw_role_mentions]
    if msg.mention_everyone:
        # Le drapeau ne dit pas LEQUEL des deux ; le contenu, lui, le dit.
        contenu = msg.content or ""
        ici = "@here" in contenu and "@everyone" not in contenu
        rendues.append(_echapper("@here" if ici else "@everyone"))
    return _borner(" ".join(rendues), _MAX_MENTIONS)


async def message_supprime(bot: "WallyDiscord", payload: Any, *,
                           dormir: Callable[[float], Any] = asyncio.sleep,
                           horloge: Callable[[], datetime] = maintenant) -> None:
    """`on_raw_message_delete` : la carte d'un message supprimé.

    Message en CACHE : la carte est construite et envoyée par une TÂCHE DE
    FOND, parce qu'elle attend `_DELAI_AUDIT` avant de lire le journal d'audit
    du serveur — Discord n'y écrit pas à l'instant de la suppression. Cette
    attente ne doit retarder qu'elle, jamais l'événement suivant.

    Hors cache, il n'y a ni auteur ni contenu, donc rien à recouper : la carte
    part tout de suite, et sans ligne « Supprimé par ».

    `dormir` et `horloge` sont les deux seams des tests — aucune suite ne doit
    attendre deux secondes par suppression.
    """
    try:
        cfg = bot.config.discord.journal_moderation
        msg = payload.cached_message
        if msg is not None and msg.author.bot and not cfg.inclure_bots:
            return
        source: Any = bot.get_channel(payload.channel_id)
        if source is None and msg is not None:
            source = msg.channel
        salons = salons_cibles(bot, payload.guild_id, payload.channel_id, source)
        if not salons:
            return
        if msg is None:
            await _carte_hors_cache(payload, source, salons, horloge)
            return
        # Import tardif : `bot.discord.handlers` importe la moitié du bot et
        # ce module-ci est chargé par les événements — au niveau module, les
        # deux se mordraient la queue.
        from bot.discord.handlers import _fire
        _fire(_carte_suppression(bot, payload, msg, source, salons, dormir=dormir, horloge=horloge))
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : suppression non journalisée : {e!r}", e=e)


async def _carte_hors_cache(payload: Any, source: Any, salons: list[Any],
                            horloge: Callable[[], datetime]) -> None:
    """Le message n'était pas en cache : ni auteur, ni contenu, ni âge.

    Il n'y a donc rien à recouper avec le journal d'audit (la cible d'une
    entrée est un AUTEUR, pas un message), et aucune raison d'attendre.
    """
    meta = (f"**Auteur** inconnu · **Salon** {_mention_salon(payload.channel_id, source)} · "
            f"**Message** {payload.message_id} · **Supprimé** {horodatage(horloge())}")
    vue = fiche("🗑️ Message supprimé", [meta, "*contenu non disponible*"], accent=ACCENT_ALERTE)
    await publier_partout(salons, lambda _t: vue)


async def _carte_suppression(bot: "WallyDiscord", payload: Any, msg: Any, source: Any,
                             salons: list[Any], *, dormir: Callable[[float], Any],
                             horloge: Callable[[], datetime]) -> None:
    """La carte d'un message en cache, recoupement d'audit et ghost ping compris.

    Les pièces jointes sont retéléchargées AVANT l'attente : leur `proxy_url`
    est périssable, là où une entrée d'audit, elle, ne s'efface pas.

    Détachée de son gestionnaire d'événement (`_fire`), donc seule à pouvoir
    signaler son propre échec : elle ne lève jamais.
    """
    try:
        auteur = msg.author
        tele = await _telecharger_pieces(salons, list(msg.attachments), nsfw=_salon_nsfw(source))
        await dormir(_DELAI_AUDIT)
        recoupement = await entree_audit(bot.get_guild(payload.guild_id),
                                         discord.AuditLogAction.message_delete,
                                         cible_id=auteur.id, salon_id=payload.channel_id,
                                         horloge=horloge)
        contenu = (msg.content or "").strip()
        # Round 2 #B : un contenu supprimé peut porter une fence non fermée,
        # un `||spoiler||` ou toute autre construction Markdown — échappée
        # AVANT citation (même ordre que le diff d'édition), sinon elle déforme
        # ou MASQUE la fiche elle-même, pas seulement le message d'origine.
        bloc_contenu = _citer(discord.utils.escape_markdown(contenu)) if contenu else "*aucun texte*"
        meta = (f"**Auteur** <@{auteur.id}> ({discord.utils.escape_markdown(auteur.name)}) · "
                f"**Salon** {_mention_salon(payload.channel_id, source)} · "
                f"**Message** {payload.message_id} · **Posté** {_relatif(msg.created_at)} · "
                f"**Supprimé** {horodatage(horloge())}{_ligne_supprime_par(recoupement)}")
        mentions = _mentions_rendues(msg)
        # Ghost ping : mentionner puis effacer dans la foulée, pour que la
        # notification reste et pas le message. Passé cinq minutes, c'est une
        # suppression ordinaire d'un message qui mentionnait quelqu'un.
        ghost = bool(mentions) and (horloge() - msg.created_at).total_seconds() < _GHOST_PING_SECONDES
        titre = "👻 Ghost ping supprimé" if ghost else "🗑️ Message supprimé"

        def construire(t: _Telechargement) -> discord.ui.LayoutView:
            corps = [meta, bloc_contenu]
            if ghost:
                corps.append(f"**Mentionnait** {mentions}")
            if t.ratees:
                corps.append(_bloc_non_recuperees(t.ratees))
            return fiche(titre, corps, accent=ACCENT_ALERTE, vignette=url_avatar(auteur),
                         medias=t.medias, fichiers=t.autres, pied=pied_utilisateur(auteur))

        await publier_partout(salons, construire, tele)
    except Exception as e:  # noqa: BLE001 — tâche détachée : personne derrière pour rattraper
        logger.warning("journal de modération : suppression non journalisée : {e!r}", e=e)


async def message_modifie(bot: "WallyDiscord", before: Any, after: Any) -> None:
    try:
        cfg = bot.config.discord.journal_moderation
        if after.author.bot and not cfg.inclure_bots:
            return
        avant, apres = before.content or "", after.content or ""
        apres_ids = {p.id for p in after.attachments}
        retirees = [p for p in before.attachments if p.id not in apres_ids]
        if avant == apres and not retirees:
            return          # embed de lien, épinglage : rien n'a bougé
        guild_id = after.guild.id if after.guild is not None else None
        salons = salons_cibles(bot, guild_id, after.channel.id, after.channel)
        if not salons:
            return
        auteur = after.author
        meta = (f"**Auteur** <@{auteur.id}> ({discord.utils.escape_markdown(auteur.name)}) · "
               f"**Salon** {_mention_salon(after.channel.id, after.channel)} · "
               f"**Message** {after.id} · **Modifié** {horodatage(maintenant())} · "
               f"[aller au message]({after.jump_url})")
        tele = await _telecharger_pieces(salons, retirees, nsfw=_salon_nsfw(after.channel))
        # Échappés AVANT le diff : les marqueurs `~~`/`**` posés par `_diff_mots`
        # doivent rester les SEULS actifs (cf. sa docstring). Le repli
        # Avant/Après réutilise le MÊME texte échappé — les deux chemins
        # doivent rendre le markdown de l'auteur de façon identique.
        avant_echappe = _echapper(discord.utils.escape_markdown(avant))
        apres_echappe = _echapper(discord.utils.escape_markdown(apres))
        # Seul le texte a pu ne PAS bouger (une pièce jointe retirée, texte
        # identique) : aucun bloc de contenu dans ce cas, ni diff ni
        # Avant/Après — sinon la fiche affiche un « changement » sur du texte
        # inchangé.
        texte_identique = avant_echappe == apres_echappe
        diff = None if texte_identique else _diff_mots(avant_echappe, apres_echappe)

        def construire(t: _Telechargement) -> discord.ui.LayoutView:
            corps = [meta]
            if not texte_identique:
                if diff is None:
                    corps.append(_bloc_deja_echappe("Avant", avant_echappe))
                    corps.append(_bloc_deja_echappe("Après", apres_echappe))
                else:
                    corps.append(_bloc_deja_echappe("Modification", diff))
            if t.ratees:
                corps.append(_bloc_non_recuperees(t.ratees))
            return fiche("✏️ Message modifié", corps, accent=ACCENT_ALERTE, vignette=url_avatar(auteur),
                         medias=t.medias, fichiers=t.autres, pied=pied_utilisateur(auteur))

        await publier_partout(salons, construire, tele)
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
        cfg = bot.config.discord.journal_moderation
        source = bot.get_channel(payload.channel_id)
        salons = salons_cibles(bot, payload.guild_id, payload.channel_id, source)
        if not salons:
            return
        meta = (f"**Salon** {_mention_salon(payload.channel_id, source)} · "
                f"**Messages** {len(payload.message_ids)} · **Supprimé** {horodatage(maintenant())}")
        lignes = []
        for msg in payload.cached_messages:
            # Le TOTAL ci-dessus compte tout `message_ids` (bots compris) ;
            # seule la ligne de détail d'un bot est retirée par défaut.
            if getattr(msg.author, "bot", False) and not cfg.inclure_bots:
                continue
            auteur = discord.utils.escape_markdown(getattr(msg.author, "name", "inconnu"))
            # Round 2 #B : même ordre d'échappement que le contenu d'une
            # suppression simple (escape_markdown PUIS `_echapper`) — sinon
            # une fence ou un `||spoiler||` déforme la liste elle-même.
            contenu = _echapper(discord.utils.escape_markdown((msg.content or "").strip()))
            extrait = _borner(contenu, _MAX_EXTRAIT) if contenu else "*aucun texte*"
            lignes.append(f"**{auteur}** : {extrait}")
        corps = [meta]
        if lignes:
            corps.append(borner_lignes(lignes, _MAX_CITATION))
        vue = fiche("🧹 Suppression en masse", corps, accent=ACCENT_ALERTE)
        await publier_partout(salons, lambda _t: vue)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : suppression en masse non journalisée : {e!r}", e=e)
