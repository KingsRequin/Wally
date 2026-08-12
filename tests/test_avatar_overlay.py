"""L'avatar de l'overlay : un dessin entier, une boucle sans saccade.

Le fichier servi le 2026-08-12 portait trois défauts visibles à l'écran, et
aucun n'était détectable autrement qu'à l'œil :

1. le cadre (170x238) était plus court que le dessin (161x255 mesuré sur toute
   l'animation) : 239 images sur 601 avaient de la matière tranchée pile sur la
   ligne du haut — la pointe de la flamme et les étincelles qui montent ;
2. le flux commençait à 0,128 s et déclarait 11,084 s pour une dernière image à
   10,128 s : près d'une seconde d'image figée à chaque tour de boucle ;
3. la dernière image ne raccordait pas la première (16 fois l'écart de deux
   images consécutives), d'où le saut.

`ffprobe` n'existe que dans l'image Docker, donc ces contrôles lisent le
conteneur Matroska à la main : ils tournent partout, y compris sur l'hôte.
Le raccord de boucle (défaut 3) demande un décodeur VP9 et n'est pas vérifiable
ici — il l'est par `scripts/preparer_avatar.py`, qui refuse de produire un
fichier dont le raccord dépasse un pas d'animation.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

AVATAR = Path(__file__).resolve().parents[1] / "bot/dashboard/static/avatar/wally.webm"

# Mesurés sur la source 500x500 le 2026-08-12, sur les 601 images : le dessin
# occupe x 169..329 et y 69..323. Un cadre plus étroit que ça tranche forcément
# quelque chose — c'est exactement ce qui s'était produit.
DESSIN_L, DESSIN_H = 161, 255

CADENCE = 60.0  # images par seconde de la source

# ── Lecture EBML/Matroska, réduite aux quelques éléments utiles ──────────────

ID_SEGMENT = 0x18538067
ID_INFO = 0x1549A966
ID_TIMECODE_SCALE = 0x2AD7B1
ID_DUREE = 0x4489
ID_TRACKS = 0x1654AE6B
ID_TRACK_ENTRY = 0xAE
ID_NUMERO_PISTE = 0xD7
ID_VIDEO = 0xE0
ID_LARGEUR = 0xB0
ID_HAUTEUR = 0xBA
ID_ALPHA = 0x53C0
ID_CLUSTER = 0x1F43B675
ID_TIMECODE = 0xE7
ID_SIMPLE_BLOCK = 0xA3
ID_BLOCK_GROUP = 0xA0
ID_BLOCK = 0xA1

CONTENEURS = {ID_SEGMENT, ID_INFO, ID_TRACKS, ID_TRACK_ENTRY, ID_VIDEO, ID_CLUSTER, ID_BLOCK_GROUP}


def _lire_vint(buf: bytes, pos: int, *, garder_marqueur: bool) -> tuple[int, int]:
    """Rend (valeur, position suivante). Les identifiants gardent leur marqueur."""
    premier = buf[pos]
    longueur = 1
    while longueur <= 8 and not premier & (0x80 >> (longueur - 1)):
        longueur += 1
    if longueur > 8:
        raise ValueError(f"vint illisible à l'octet {pos}")
    brut = buf[pos : pos + longueur]
    valeur = int.from_bytes(brut, "big")
    if not garder_marqueur:
        valeur &= (1 << (7 * longueur)) - 1
    return valeur, pos + longueur


def _parcourir(buf: bytes, debut: int, fin: int):
    """Itère (identifiant, début du contenu, fin du contenu) sur un niveau."""
    pos = debut
    while pos < fin:
        ident, pos = _lire_vint(buf, pos, garder_marqueur=True)
        taille, pos = _lire_vint(buf, pos, garder_marqueur=False)
        # Taille inconnue (tous les bits à 1) : le contenu court jusqu'au bout.
        if taille == (1 << (7 * (pos - debut))) - 1 or pos + taille > fin:
            taille = fin - pos
        yield ident, pos, pos + taille
        pos += taille


def _chercher(buf: bytes, debut: int, fin: int, chemin: tuple[int, ...]):
    """Descend un chemin d'identifiants et rend (début, fin) du contenu."""
    for ident, d, f in _parcourir(buf, debut, fin):
        if ident != chemin[0]:
            continue
        return (d, f) if len(chemin) == 1 else _chercher(buf, d, f, chemin[1:])
    return None


def _entier(buf: bytes, debut: int, fin: int) -> int:
    return int.from_bytes(buf[debut:fin], "big")


def _flottant(buf: bytes, debut: int, fin: int) -> float:
    octets = buf[debut:fin]
    return struct.unpack(">f" if len(octets) == 4 else ">d", octets)[0]


class Avatar:
    """Ce que le conteneur dit du fichier, sans décoder une seule image."""

    def __init__(self, chemin: Path) -> None:
        buf = chemin.read_bytes()
        self.octets = len(buf)
        segment = _chercher(buf, 0, len(buf), (ID_SEGMENT,))
        assert segment, "pas de Segment Matroska"
        s0, s1 = segment

        info = _chercher(buf, s0, s1, (ID_INFO,))
        assert info, "pas de bloc Info"
        echelle = _chercher(buf, *info, (ID_TIMECODE_SCALE,))
        self.echelle_ns = _entier(buf, *echelle) if echelle else 1_000_000
        duree = _chercher(buf, *info, (ID_DUREE,))
        self.duree = _flottant(buf, *duree) * self.echelle_ns / 1e9 if duree else 0.0

        # La piste vidéo n'est pas forcément la première : la source de Wally
        # traîne une piste audio Vorbis, dont les blocs fausseraient le compte.
        pistes = _chercher(buf, s0, s1, (ID_TRACKS,))
        assert pistes, "pas de bloc Tracks"
        video = numero = None
        for ident, t0, t1 in _parcourir(buf, *pistes):
            if ident != ID_TRACK_ENTRY:
                continue
            trouve = _chercher(buf, t0, t1, (ID_VIDEO,))
            if trouve:
                video = trouve
                numero = _entier(buf, *_chercher(buf, t0, t1, (ID_NUMERO_PISTE,)))
                break
        assert video and numero is not None, "pas de piste vidéo"
        self.piste = numero
        self.largeur = _entier(buf, *_chercher(buf, *video, (ID_LARGEUR,)))
        self.hauteur = _entier(buf, *_chercher(buf, *video, (ID_HAUTEUR,)))

        # `AlphaMode` est le champ de la spécification Matroska ; l'étiquette
        # texte `ALPHA_MODE` n'est écrite que par le multiplexeur de ffmpeg, et
        # manque donc sur les fichiers produits ailleurs.
        alpha = _chercher(buf, *video, (ID_ALPHA,))
        self.alpha = bool(alpha and _entier(buf, *alpha)) or b"ALPHA_MODE" in buf

        horodatages: list[float] = []
        for ident, c0, c1 in _parcourir(buf, s0, s1):
            if ident != ID_CLUSTER:
                continue
            tc = _chercher(buf, c0, c1, (ID_TIMECODE,))
            base = _entier(buf, *tc) if tc else 0
            for bid, b0, b1 in _parcourir(buf, c0, c1):
                if bid == ID_BLOCK_GROUP:
                    bloc = _chercher(buf, b0, b1, (ID_BLOCK,))
                    if not bloc:
                        continue
                    b0, b1 = bloc
                elif bid != ID_SIMPLE_BLOCK:
                    continue
                piste, apres = _lire_vint(buf, b0, garder_marqueur=False)
                if piste != numero:
                    continue
                relatif = struct.unpack(">h", buf[apres : apres + 2])[0]
                horodatages.append((base + relatif) * self.echelle_ns / 1e9)

        assert horodatages, "aucune image dans le fichier"
        self.horodatages = sorted(horodatages)
        self.images = len(horodatages)


@pytest.fixture(scope="module")
def avatar() -> Avatar:
    assert AVATAR.exists(), f"avatar absent : {AVATAR}"
    return Avatar(AVATAR)


def test_le_cadre_est_assez_grand_pour_le_dessin_entier(avatar: Avatar) -> None:
    """Un cadre plus court que le dessin tranche la flamme sur le bord haut.

    Le fichier fautif faisait 170x238 : il passait en largeur et échouait de
    17 px en hauteur, ce qui coupait tout ce qui monte au-dessus de la pose
    initiale. Le contrôle porte sur la hauteur ET la largeur : recadrer sur la
    première image est une erreur qui peut se refaire dans l'autre sens.
    """
    assert avatar.hauteur >= DESSIN_H, (
        f"cadre haut de {avatar.hauteur} px pour un dessin qui en fait {DESSIN_H} : "
        "les flammes qui montent sont tranchées par le bord"
    )
    assert avatar.largeur >= DESSIN_L, (
        f"cadre large de {avatar.largeur} px pour un dessin qui en fait {DESSIN_L}"
    )


def test_la_boucle_demarre_a_zero(avatar: Avatar) -> None:
    """Une première image en retard laisse un blanc à chaque tour.

    Le fichier fautif posait sa première image à 0,133 s : le lecteur repassait
    par 133 ms sans nouvelle image à chaque bouclage, ce qui se voit comme un
    gel juste avant le saut.
    """
    assert avatar.horodatages[0] == pytest.approx(0.0, abs=1e-6), (
        f"première image à {avatar.horodatages[0]:.3f} s au lieu de 0"
    )


def test_la_boucle_ne_traine_pas_apres_la_derniere_image(avatar: Avatar) -> None:
    """Une durée déclarée au-delà de la dernière image fige l'écran.

    Le fichier fautif annonçait 11,084 s alors que sa dernière image tombait à
    10,128 s : presque une seconde d'arrêt sur image avant le retour au début.
    On tolère une image, pas davantage.
    """
    fin = avatar.horodatages[-1]
    marge = 1.5 / CADENCE
    assert avatar.duree <= fin + marge, (
        f"durée déclarée {avatar.duree:.3f} s pour une dernière image à {fin:.3f} s : "
        f"{avatar.duree - fin:.3f} s d'image figée à chaque tour"
    )


def test_la_transparence_est_conservee(avatar: Avatar) -> None:
    """Sans alpha, l'avatar arrive sur un rectangle opaque dans OBS."""
    assert avatar.alpha, "le fichier ne déclare pas ALPHA_MODE"


def test_la_cadence_reste_reguliere(avatar: Avatar) -> None:
    """Un trou au milieu se verrait autant qu'un trou à la jointure."""
    ecarts = [b - a for a, b in zip(avatar.horodatages, avatar.horodatages[1:])]
    assert max(ecarts) <= 2.0 / CADENCE, (
        f"trou de {max(ecarts) * 1000:.0f} ms dans l'animation"
    )
