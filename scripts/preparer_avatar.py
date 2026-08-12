#!/usr/bin/env python3
"""Prépare l'avatar animé de l'overlay à partir de sa source.

Pourquoi ce script existe : l'avatar servi jusqu'au 2026-08-12 avait été recadré
à la main sur la boîte englobante de sa **première image**. Tout ce qui montait
plus haut ensuite — la pointe de la flamme, les étincelles — était tranché net
par le bord du cadre, sur 239 images sur 601. Personne ne pouvait le refaire
correctement sans refaire la mesure à la main, et rien ne disait d'où venait le
fichier. Il se régénère maintenant d'une commande.

Trois choses que ce script fait et qu'un `ffmpeg crop` à la main ne fait pas :

* **le cadre est mesuré sur toutes les images conservées**, pas sur la première,
  et une marge est ajoutée — un dessin qui affleure le bord se lit comme coupé
  même quand il ne l'est pas ;
* **le point de bouclage est cherché**, pas subi. La source contient 3,6 tours
  d'un cycle : sa dernière image ne raccorde pas la première, d'où le saut. On
  garde le plus long segment dont les extrémités se rejoignent sous un pas
  d'animation, écart mesuré sur plusieurs images pour que le *mouvement*
  raccorde et pas seulement la pose ;
* **les horodatages repartent de zéro et s'arrêtent net**. La source commence à
  0,128 s et déclare 0,96 s de plus que sa dernière image : ce sont deux gels
  qui s'ajoutent à chaque tour de boucle.

Le script **refuse d'écrire** si l'un de ces trois points n'est pas tenu.

La source est versionnée dans `assets/avatar/wally-source.webm` — c'est de sa
perte qu'est venu le problème : plus personne ne pouvait refaire la découpe.

Usage. `ffmpeg` n'existe que dans l'image Docker, et seul `data/` y est monté en
écriture, d'où le passage par ce dossier :

    mkdir -p data/avatar && cp assets/avatar/wally-source.webm data/avatar/
    docker exec -i wally-bot python3 - \\
        /app/data/avatar/wally-source.webm /app/data/avatar/wally.webm \\
        < scripts/preparer_avatar.py
    cp data/avatar/wally.webm bot/dashboard/static/avatar/wally.webm

`bot/dashboard/static` est monté dans le conteneur : aucun rebuild n'est requis
pour que le nouvel avatar soit servi. `tests/test_avatar_overlay.py` relit le
fichier produit et refuse les trois défauts ci-dessus.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

CADENCE = 60
MARGE = 3  # px d'air conservés autour du dessin, sur les quatre bords
FENETRE = 8  # images sur lesquelles le raccord de boucle doit tenir
MIN_IMAGES = 120  # on ne descend pas sous 2 s d'animation
SEUIL_RACCORD = 1.0  # en multiples d'un pas d'animation normal


def _run(*args: str) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode:
        raise SystemExit(f"échec de {args[0]} :\n{proc.stderr.strip()[-2000:]}")


def extraire(source: Path, dossier: Path) -> list[Path]:
    """Décode la source en PNG RGBA. `-vcodec libvpx-vp9` est requis : sans lui
    ffmpeg choisit un décodeur qui jette la couche alpha en silence."""
    dossier.mkdir(parents=True, exist_ok=True)
    _run(
        "ffmpeg", "-hide_banner", "-v", "error",
        "-vcodec", "libvpx-vp9", "-i", str(source),
        "-an", "-vsync", "0", "-pix_fmt", "rgba",
        str(dossier / "f%05d.png"),
    )
    images = sorted(dossier.glob("*.png"))
    if not images:
        raise SystemExit("aucune image décodée")
    return images


def charger(images: list[Path]) -> np.ndarray:
    """Empile les images en prémultipliant par l'alpha.

    Sans prémultiplication, deux images identiques à l'œil mais dont les pixels
    transparents portent des couleurs différentes se comparent comme distinctes.

    La pile reste en `uint8` : en float32 elle pèse 2,4 Go pour cette source, ce
    que le conteneur ne tient pas. L'arrondi coûte moins d'un demi-niveau sur
    des écarts qui se comptent en dizaines.
    """
    pile = []
    for chemin in images:
        a = np.asarray(Image.open(chemin).convert("RGBA"), dtype=np.uint16)
        premultiplie = (a[..., :3] * a[..., 3:4] + 127) // 255
        pile.append(np.concatenate([premultiplie, a[..., 3:4]], -1).astype(np.uint8))
    return np.stack(pile)


def _ecart(a: np.ndarray, b: np.ndarray) -> float:
    """Écart moyen entre deux images ou deux paquets d'images.

    Le passage par int16 est obligatoire : soustraire deux `uint8` boucle par en
    dessous et rendrait 255 pour un écart de 1.
    """
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def chercher_boucle(pile: np.ndarray) -> tuple[int, int, float, float]:
    """Rend (début, fin exclue, écart du raccord, pas normal).

    La recherche se fait sur des miniatures : à pleine résolution la matrice des
    distances coûte des heures, et le classement des candidats ne change pas.
    Les finalistes sont ensuite départagés à pleine résolution.
    """
    n = len(pile)
    petites = np.stack([
        np.asarray(
            Image.fromarray(img, "RGBA").resize((64, 64), Image.BILINEAR), dtype=np.float32
        ).ravel()
        for img in pile
    ])
    pas = float(np.median(np.abs(petites[1:] - petites[:-1]).mean(1)))

    distances = np.empty((n, n), dtype=np.float32)
    for i in range(n):
        distances[i] = np.abs(petites[i][None, :] - petites).mean(1)

    m = n - FENETRE
    glissante = np.zeros((m, m), dtype=np.float32)
    for k in range(FENETRE):
        glissante += distances[k : m + k, k : m + k]
    glissante /= FENETRE

    candidats = []
    for i in range(m):
        j0 = i + MIN_IMAGES
        if j0 >= m:
            break
        j = int(np.argmin(glissante[i, j0:])) + j0
        candidats.append((float(glissante[i, j]), i, j))
    candidats.sort()

    # À pleine résolution, on préfère le segment le PLUS LONG parmi ceux dont le
    # raccord reste sous le seuil : moins de répétition à l'écran.
    pas_reel = float(np.median([_ecart(pile[k + 1], pile[k]) for k in range(n - 1)]))
    retenu = None
    for _, i, j in candidats[:40]:
        ecart = _ecart(pile[j : j + FENETRE], pile[i : i + FENETRE])
        saut = _ecart(pile[j], pile[i])
        if max(ecart, saut) > SEUIL_RACCORD * pas_reel:
            continue
        if retenu is None or (j - i) > (retenu[1] - retenu[0]):
            retenu = (i, j, max(ecart, saut))
    if retenu is None:
        raise SystemExit("aucun point de bouclage acceptable dans cette source")
    return retenu[0], retenu[1], retenu[2], pas_reel


def cadrer(pile: np.ndarray, debut: int, fin: int) -> tuple[int, int, int, int]:
    """Boîte englobante du dessin sur les images conservées, marge comprise.

    Les dimensions sont ramenées à des nombres pairs : VP9 en 4:2:0 sous-échantillonne
    la chrominance d'un facteur deux, et une dimension impaire fait recadrer ffmpeg
    tout seul — ce qui rognerait la marge qu'on vient d'ajouter.
    """
    masque = pile[debut:fin, ..., 3] > 16
    ys, xs = np.where(masque.any(0))
    hauteur_totale, largeur_totale = pile.shape[1], pile.shape[2]
    x0 = max(0, int(xs.min()) - MARGE)
    y0 = max(0, int(ys.min()) - MARGE)
    x1 = min(largeur_totale, int(xs.max()) + 1 + MARGE)
    y1 = min(hauteur_totale, int(ys.max()) + 1 + MARGE)
    if (x1 - x0) % 2:
        x1 = x1 + 1 if x1 < largeur_totale else x0 - 1
    if (y1 - y0) % 2:
        y1 = y1 + 1 if y1 < hauteur_totale else y0 - 1
    return x0, y0, x1, y1


def verifier_marges(pile: np.ndarray, debut: int, fin: int, cadre: tuple[int, int, int, int]) -> None:
    """Refuse un cadre qui tranche le dessin — le défaut qu'on est en train de réparer."""
    x0, y0, x1, y1 = cadre
    coupe = pile[debut:fin, y0:y1, x0:x1, 3] > 16
    bords = {
        "haut": coupe[:, 0, :].any(),
        "bas": coupe[:, -1, :].any(),
        "gauche": coupe[:, :, 0].any(),
        "droite": coupe[:, :, -1].any(),
    }
    touches = [nom for nom, touche in bords.items() if touche]
    if touches:
        raise SystemExit(f"le dessin touche le bord {', '.join(touches)} : cadre trop petit")


def encoder(images: list[Path], debut: int, fin: int, cadre: tuple[int, int, int, int],
            travail: Path, sortie: Path) -> None:
    x0, y0, x1, y1 = cadre
    decoupe = travail / "coupe"
    decoupe.mkdir(parents=True, exist_ok=True)
    for rang, chemin in enumerate(images[debut:fin], start=1):
        Image.open(chemin).convert("RGBA").crop((x0, y0, x1, y1)).save(decoupe / f"f{rang:05d}.png")
    # `-auto-alt-ref 0` : les images de référence alternatives de libvpx sont
    # incompatibles avec la couche alpha, qui sortirait vide. `-an` : la source
    # traîne une piste audio dont l'overlay n'a que faire (la vidéo est muette).
    _run(
        "ffmpeg", "-hide_banner", "-v", "error", "-y",
        "-framerate", str(CADENCE), "-i", str(decoupe / "f%05d.png"),
        "-an", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
        "-auto-alt-ref", "0", "-lag-in-frames", "0",
        "-b:v", "0", "-crf", "26", "-row-mt", "1",
        str(sortie),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("sortie", type=Path)
    args = ap.parse_args()

    travail = Path(tempfile.mkdtemp(prefix="avatar-"))
    try:
        images = extraire(args.source, travail / "brut")
        pile = charger(images)
        print(f"source : {len(images)} images, {pile.shape[2]}x{pile.shape[1]}")

        debut, fin, ecart, pas = chercher_boucle(pile)
        print(f"boucle : images {debut + 1}..{fin} ({(fin - debut) / CADENCE:.2f} s), "
              f"raccord {ecart:.3f} = {ecart / pas * 100:.0f} % d'un pas")

        cadre = cadrer(pile, debut, fin)
        verifier_marges(pile, debut, fin, cadre)
        x0, y0, x1, y1 = cadre
        print(f"cadre  : {x1 - x0}x{y1 - y0} à partir de ({x0}, {y0}), marge {MARGE} px")

        encoder(images, debut, fin, cadre, travail, args.sortie)
        print(f"écrit  : {args.sortie} ({args.sortie.stat().st_size / 1024:.0f} Ko)")
    finally:
        shutil.rmtree(travail, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
