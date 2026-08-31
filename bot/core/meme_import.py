# bot/core/meme_import.py
"""Faire entrer une image dans la banque de memes.

Toute la logique d'import vit ici, hors de Discord : la commande contextuelle et
`scripts/rattraper_memes.py` n'en sont que deux appelants, et le module se teste
sans réseau ni bot.

La conversion WebP y a été déplacée depuis `scripts/convertir_memes_webp.py`,
qui l'importe désormais. Le piège qu'elle existe pour éviter : convertir un GIF
animé « à la Pillow » perd l'animation sur un fichier sur trois — la sortie ne
garde qu'une frame et pèse 99 % de moins, ce qui ressemble à s'y méprendre à une
réussite. Deux copies de cette garde finiraient par diverger.
"""
from __future__ import annotations

import hashlib
import re
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from PIL import Image, ImageSequence

# Importés plutôt que recopiés : deux plafonds qui divergent, c'est un meme qui
# disparaît de la bibliothèque sans que personne ne comprenne pourquoi. Ce
# commentaire s'était perdu à l'extraction du module, et le raisonnement a
# dérapé aussitôt — un plafond appliqué aux seules images laissait entrer des
# vidéos que `list_medias()` écartait ensuite en silence.
from bot.core.memes import (
    _EXTENSIONS_MEDIA,
    _MAX_BYTES,
    chemin_description,
    description_ecrite,
    tronquer_description,
)

A_CONVERTIR = frozenset({".gif", ".png"})

# Une animation supporte le lossy sans qu'on le voie — c'est ce qui donne les
# 70 % de gain. Une image fixe de meme, c'est d'abord du texte : sans perte.
QUALITE_ANIMEE = 80

_NUMERO = re.compile(r"^meme(\d+)\.", re.IGNORECASE)

# Garde de TÉLÉCHARGEMENT, distincte du plafond d'affichage : on coupe le flux
# plutôt que d'avaler ce qu'un CDN veut bien envoyer. Elle est deux fois plus
# haute que `_MAX_BYTES` parce que la conversion peut faire redescendre le
# fichier sous le plafond — −89 % sur un PNG, −75 % sur un GIF. Ce qui reste
# au-dessus après conversion est refusé plus bas, dans `importer()`.
MAX_TELECHARGEMENT = 16 * 1024 * 1024


@dataclass
class ResultatImport:
    """Ce qu'il est advenu d'une tentative d'import."""

    ok: bool
    nom: str = ""
    raison: str = ""
    doublon: str = ""
    converti: bool = False
    octets: int = 0


def convertir_si_avantageux(octets: bytes, suffixe: str) -> tuple[bytes, str]:
    """Rend `(octets, suffixe)` en WebP si l'échange fait gagner, tels quels sinon.

    Passe par des fichiers temporaires plutôt que de travailler en mémoire : la
    vérification relit le WebP écrit pour compter ses frames et lire leurs
    durées dans les chunks ANMF. La réécrire sur des octets, c'est reprendre une
    garde éprouvée pour rien.
    """
    if suffixe.lower() not in A_CONVERTIR:
        return octets, suffixe
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"src{suffixe}"
        dst = Path(tmp) / "dst.webp"
        src.write_bytes(octets)
        try:
            convertir(src, dst)
            if verifier_conversion(src, dst):
                return octets, suffixe
        except Exception as e:  # noqa: BLE001 — un format exotique ne fait pas échouer l'import
            logger.warning("conversion de {suffixe} échouée : {err!r}", suffixe=suffixe, err=e)
            return octets, suffixe
        return dst.read_bytes(), ".webp"


@dataclass
class Bilan:
    """Ce qu'est devenu un lot d'imports, et le compte rendu qui va avec.

    Un seul format de rapport pour les trois chemins d'import — le message
    contextuel, le ratissage d'un salon, le dépôt au fil de l'eau. Deux
    rédactions qui divergent, c'est un « 7 rangés » qui ne veut pas dire la
    même chose selon la commande qui le rend.

    Les refus sont NOMMÉS : un compte seul laisse chercher dans le dossier ce
    qui manque, là où « 9,4 Mo après conversion » l'explique sur place.
    """

    ranges: list[str] = field(default_factory=list)
    doublons: list[str] = field(default_factory=list)
    refus: list[str] = field(default_factory=list)
    muets: int = 0
    interrompu: bool = False

    @classmethod
    def depuis(cls, resultats: list[ResultatImport]) -> "Bilan":
        bilan = cls()
        for r in resultats:
            bilan.ajouter(r)
        return bilan

    def ajouter(self, resultat: ResultatImport, decrit: bool = True) -> None:
        if resultat.ok:
            self.ranges.append(resultat.nom)
            if not decrit:
                self.muets += 1
        elif resultat.doublon:
            self.doublons.append(resultat.doublon)
        else:
            self.refus.append(resultat.raison)

    def texte(self, refus_montres: int = 3) -> str:
        def _n(quoi: str, combien: int) -> str:
            return f"{combien} {quoi}{'s' if combien > 1 else ''}"

        bouts = [f"**{_n('rangé', len(self.ranges))}**"]
        if self.doublons:
            bouts.append(_n("doublon", len(self.doublons)))
        if self.refus:
            bouts.append(_n("refusé", len(self.refus)))
        if self.muets:
            bouts.append(f"{self.muets} sans description")
        lignes = [", ".join(bouts) + "."]
        if self.ranges:
            lignes.append(" ".join(f"`{n}`" for n in self.ranges))
        lignes += [f"· {r}" for r in self.refus[:refus_montres]]
        if len(self.refus) > refus_montres:
            lignes.append(f"· … et {len(self.refus) - refus_montres} autre(s)")
        if self.interrompu:
            lignes.append("_Limite atteinte : relance la commande pour la suite._")
        return "\n".join(lignes)


@dataclass
class Preparation:
    """Une image passée au crible, prête à écrire — ou déjà refusée.

    Ce qui justifie ce temps séparé : la conversion WebP tranche la question du
    doublon (un `.png` reposté est rangé sous forme de `.webp`, donc son
    empreinte d'origine ne dit rien) ET celle du poids. Les deux doivent être
    connues AVANT de décrire l'image, sans quoi l'import en masse paye une
    vision par doublon — quelques secondes chacune, sur un salon qui en compte
    la moitié. Convertir ici puis ranger ces octets-là, c'est aussi ne convertir
    qu'une fois.
    """

    octets: bytes = b""
    suffixe: str = ""
    converti: bool = False
    doublon: str = ""
    raison: str = ""

    @property
    def refusee(self) -> bool:
        return bool(self.doublon or self.raison)

    def resultat(self) -> ResultatImport:
        """Le refus, sous la forme que rend `importer()`."""
        return ResultatImport(False, raison=self.raison or "déjà rangé", doublon=self.doublon)


class SessionImport:
    """Une suite d'imports dans le même dossier, index chargé UNE fois.

    `importer()` seul relit tout le dossier à chaque appel : aujourd'hui 268
    fichiers et 44 Mo. Ranger 300 images d'un salon, c'était donc treize
    gigaoctets de lecture pour en écrire quarante mégaoctets — et surtout deux
    appels qui se chevauchent tirent le MÊME `prochain_numero()`, le second
    écrasant le premier sans une ligne de log.

    La session tient l'index et le compteur en mémoire et les met à jour à
    chaque rangement. La dédup vaut donc aussi À L'INTÉRIEUR du lot, ce dont un
    salon de memes a besoin : la même image y est repostée deux fois.

    Elle n'est pas sûre entre threads — l'appelant sérialise ses rangements.
    """

    def __init__(self, dossier: Path) -> None:
        self.dossier = dossier
        self._index = empreintes(dossier)
        self._numero = prochain_numero(dossier)

    def preparer(self, octets: bytes, suffixe: str) -> Preparation:
        """Valide, convertit, et confronte l'image à ce qui est déjà rangé.

        N'écrit rien : tout refus laisse le dossier intact.
        """
        suffixe = suffixe.lower()
        if suffixe not in _EXTENSIONS_MEDIA:
            admis = " ".join(sorted(_EXTENSIONS_MEDIA))
            return Preparation(raison=f"format {suffixe} non admis, attendus : {admis}")
        if len(octets) > MAX_TELECHARGEMENT:
            return Preparation(
                raison=f"{len(octets) / 1e6:.1f} Mo, au-delà de la limite de téléchargement"
            )

        depuis = self._connu(octets)
        if depuis:
            return Preparation(doublon=depuis)

        finaux, suffixe_final = convertir_si_avantageux(octets, suffixe)
        converti = suffixe_final != suffixe
        if converti:
            depuis = self._connu(finaux)
            if depuis:
                return Preparation(doublon=depuis)

        # Le plafond vaut pour TOUT média, vidéos comprises : `list_medias()`,
        # celle qui sert le rotateur, l'applique aussi — avec un log DEBUG, donc
        # muet en production. Le borner aux seules images laissait entrer un
        # .mp4 de 12 Mo annoncé « rangé », que plus rien ensuite ne montrait ni
        # ne signalait.
        if len(finaux) > _MAX_BYTES:
            return Preparation(
                raison=(
                    f"{len(finaux) / 1e6:.1f} Mo après conversion, au-dessus du plafond de "
                    f"{_MAX_BYTES / 1e6:.0f} Mo, il serait rangé puis jamais montré"
                )
            )
        # L'empreinte de l'ORIGINAL voyage avec la préparation : c'est elle que
        # l'index retiendra en plus de celle du fichier écrit, pour qu'un
        # deuxième post du même `.png` soit reconnu sans repayer sa conversion.
        return Preparation(octets=finaux, suffixe=suffixe_final, converti=converti)

    def ranger(self, prepare: Preparation, description: str,
               origine: bytes = b"") -> ResultatImport:
        """Écrit une préparation acceptée. `origine` : les octets d'avant conversion."""
        if prepare.refusee:
            return prepare.resultat()

        # L'index a pu bouger DEPUIS la préparation : quatre images sont
        # préparées en parallèle pendant qu'aucune n'est encore rangée, et un
        # aperçu attend jusqu'à deux minutes avant qu'on clique. Sans ce
        # second regard, deux fois la même image dans un paquet donnait deux
        # fichiers — la préparation ne pouvait pas voir ce que le rangement
        # écrirait. `ranger()` est sérialisé : c'est ici, et nulle part
        # ailleurs, que la question se tranche pour de bon.
        depuis = self._connu(prepare.octets) or (self._connu(origine) if origine else "")
        if depuis:
            return ResultatImport(False, doublon=depuis, raison="déjà rangé")

        nom = f"meme{self._numero}{prepare.suffixe}"
        chemin = self.dossier / nom
        chemin.write_bytes(prepare.octets)
        # Écrire au-delà de ce que `_describe` relira, c'est écrire une phrase
        # que personne ne lira jusqu'au bout : la lecture coupe à
        # `MAX_DESCRIPTION`.
        texte = tronquer_description(description)
        if texte:
            try:
                chemin_description(chemin).write_text(texte, encoding="utf-8")
            except Exception:
                # Le sidecar est le second temps d'une écriture en deux temps :
                # s'il échoue, l'image ne doit pas rester seule en rayon — un
                # meme sans description n'a que son nom de fichier à offrir à
                # l'antenne. Le dossier doit revenir à son état d'avant l'appel,
                # comme sur tout autre chemin de refus.
                chemin.unlink(missing_ok=True)
                raise

        # Après l'écriture seulement : un refus ne consomme ni numéro ni entrée
        # d'index. Les deux empreintes sont retenues — l'original autant que le
        # fichier écrit — pour que le même `.png` reposté plus loin dans le lot
        # soit écarté sans repasser par la conversion.
        for empreinte in (origine, prepare.octets):
            if empreinte:
                self._index.setdefault(hashlib.sha256(empreinte).hexdigest(), nom)
        self._numero += 1
        return ResultatImport(
            True, nom=nom, converti=prepare.converti, octets=len(prepare.octets)
        )

    def importer(self, octets: bytes, suffixe: str, description: str) -> ResultatImport:
        """Range une image dans la banque. N'écrit rien si elle est refusée."""
        return self.ranger(self.preparer(octets, suffixe), description, origine=octets)

    def _connu(self, octets: bytes) -> str:
        return self._index.get(hashlib.sha256(octets).hexdigest(), "")


def importer(
    octets: bytes, suffixe: str, description: str, dossier: Path
) -> ResultatImport:
    """Range une image dans la banque. N'écrit rien si elle est refusée.

    Une session à usage unique : le contrat de la commande contextuelle et de
    `scripts/rattraper_memes.py` ne bouge pas.
    """
    return SessionImport(dossier).importer(octets, suffixe, description)


def prochain_numero(dossier: Path) -> int:
    """Le maximum trouvé plus un — jamais le premier trou.

    Les sidecars comptent : un `meme9.webp.txt` resté seul réserve le 9, sinon
    le numéro est réattribué et cette vieille description se retrouve collée à
    une image qui n'a rien à voir.
    """
    numeros = [
        int(m.group(1))
        for p in dossier.iterdir()
        if p.is_file() and (m := _NUMERO.match(p.name))
    ]
    return max(numeros, default=0) + 1


def empreintes(dossier: Path) -> dict[str, str]:
    """SHA-256 → nom, pour les médias du dossier. Les `.txt` sont ignorés."""
    index: dict[str, str] = {}
    for p in sorted(dossier.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _EXTENSIONS_MEDIA:
            continue
        index.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(), p.name)
    return index


def durees_gif(im: Image.Image) -> list[int]:
    return [f.info.get("duration", im.info.get("duration", 100))
            for f in ImageSequence.Iterator(im)]


def durees_webp(path: Path) -> list[int]:
    """Durée de chaque frame, lue dans les chunks ANMF du fichier.

    Pillow ne relit pas cette information (`frame.info["duration"]` vaut None à
    la lecture d'un WebP), et c'est justement ce qu'il faut vérifier : une
    animation reconstruite à la mauvaise cadence est un défaut invisible au
    comptage de frames.
    """
    data = path.read_bytes()
    out: list[int] = []
    i = 12  # après l'en-tête RIFF/WEBP
    while i + 8 <= len(data):
        fourcc = data[i:i + 4]
        taille = struct.unpack("<I", data[i + 4:i + 8])[0]
        if fourcc == b"ANMF":
            # ANMF : x(3) y(3) largeur(3) hauteur(3) durée(3) drapeaux(1)
            d = data[i + 20:i + 23]
            out.append(d[0] | d[1] << 8 | d[2] << 16)
        i += 8 + taille + (taille & 1)
    return out


def convertir(src: Path, dst: Path) -> None:
    im = Image.open(src)
    if getattr(im, "n_frames", 1) > 1:
        # Les frames sont aplaties une à une : passer l'image d'origine à
        # `save_all` laisse Pillow se débrouiller avec les modes de disposition
        # du GIF, et c'est là qu'il perd l'animation.
        frames = [f.convert("RGBA") for f in ImageSequence.Iterator(im)]
        frames[0].save(
            dst, "WEBP", save_all=True, append_images=frames[1:],
            duration=durees_gif(Image.open(src)), loop=im.info.get("loop", 0),
            quality=QUALITE_ANIMEE, method=4, minimize_size=True,
        )
        return
    transparent = im.mode in ("RGBA", "LA") or "transparency" in im.info
    im.convert("RGBA" if transparent else "RGB").save(
        dst, "WEBP", lossless=True, quality=100, method=4,
    )


def verifier_conversion(src: Path, dst: Path) -> str:
    """Renvoie la raison du refus, ou une chaîne vide si la copie est fidèle.

    Sur une animation, on compare la DURÉE TOTALE et non la liste des frames :
    l'encodeur fusionne légitimement deux frames identiques qui se suivent (une
    de 50 ms et une de 150 ms deviennent une de 200 ms), ce qui ne change rien à
    ce qu'on voit. Exiger l'égalité stricte refusait ces fichiers-là ; la durée
    totale, elle, s'effondre dès que l'animation est vraiment perdue.
    """
    avant, apres = Image.open(src), Image.open(dst)
    if avant.size != apres.size:
        return f"taille {avant.size} devenue {apres.size}"
    if getattr(avant, "n_frames", 1) > 1:
        if getattr(apres, "n_frames", 1) < 2:
            return "animation perdue (une seule frame)"
        attendu, obtenu = sum(durees_gif(avant)), sum(durees_webp(dst))
        if attendu != obtenu:
            return f"animation de {attendu} ms devenue {obtenu} ms"
    poids = dst.stat().st_size
    if poids >= src.stat().st_size:
        return "plus lourd que l'original"
    if poids > _MAX_BYTES:
        return f"toujours au-dessus du plafond ({poids / 1e6:.1f} Mo)"
    return ""


def memes_sans_description(
    dossier: Path, formats: frozenset[str] = _EXTENSIONS_MEDIA
) -> list[Path]:
    """Les médias dont aucun `.txt` ne parle.

    Leur description retombe alors sur le nom du fichier — « meme80 » : ils sont
    introuvables par `pick(hint)`, qui cherche dans les descriptions, et Wally
    les commente à l'aveugle quand le tirage les sort.

    Les deux formes de sidecar comptent : `meme3.jpg.txt` et `meme3.txt`.

    `formats` restreint le balayage. Par défaut tous les médias, ce dont le
    rattrapage a besoin pour dire d'une vidéo qu'il la laisse ; le canari, lui,
    passe `_EXTENSIONS` — le sidecar d'un `.mp4` n'est lu par personne, alerter
    dessus produirait un cri qu'on ne peut pas faire taire.
    """
    muets: list[Path] = []
    for p in sorted(dossier.iterdir()):
        if not p.is_file() or p.suffix.lower() not in formats:
            continue
        if sidecar_de(p) is None and not p.with_suffix(".txt").is_file():
            muets.append(p)
    return muets


def memes_a_citation_coupee(
    dossier: Path, formats: frozenset[str] = _EXTENSIONS_MEDIA
) -> list[Path]:
    """Les médias dont la description s'arrête au milieu d'une citation.

    L'ancien plafond de `MAX_DESCRIPTION` — 160 avant le 2026-08-31 — coupait à
    l'ÉCRITURE du sidecar : le texte au-delà n'existe nulle part, et seule une
    nouvelle analyse peut le rendre.

    Le signe retenu est un guillemet ouvert jamais refermé, parce qu'il ne se
    trompe pas. Deux critères plus larges ont été essayés et écartés :

    · La LONGUEUR seule (≥ 140 caractères) désignait 120 des 167 descriptions,
      dont des descriptions entières. Re-décrire l'une d'elles a produit une
      REGRESSION — le modèle a perdu le format « bébé sceptique » identifié par
      la version d'avant et recopié une infobulle Apex sans intérêt sur trois
      cents caractères. Un remède qui abîme les deux tiers du corpus pour en
      réparer un tiers n'en est pas un.
    · « ne finit pas par une ponctuation » accusait des fins normales : le
      prompt demande de clore la phrase à nu sur le sujet, donc
      « … BESOIN D'UN BUFF… » Apex » se termine bien.

    Reste que ce critère ne voit PAS une coupe survenue hors citation. C'est
    assumé : on ne sait pas distinguer celles-là d'une description complète, et
    le coût d'une régression dépasse celui d'une description un peu courte.
    """
    coupees: list[Path] = []
    for p in sorted(dossier.iterdir()):
        if not p.is_file() or p.suffix.lower() not in formats:
            continue
        texte = description_ecrite(p)
        if texte.count("«") != texte.count("»") or texte.count('"') % 2:
            coupees.append(p)
    return coupees


def sidecar_de(path: Path) -> Path | None:
    """Le `.txt` collé à l'extension, s'il existe.

    La forme sans extension (`meme1.txt`) suit le nom de base et survit à la
    conversion : rien à faire pour elle.
    """
    voisin = chemin_description(path)
    return voisin if voisin.is_file() else None
