#!/usr/bin/env python3
"""Fabrique les illustrations du TCG servies par le site, depuis les sources.

Les sources (PNG de 1 à 2 Mo, exportés du projet Claude Design) vivent hors du
dépôt, dans `/opt/design-tcg/`. Ce script en tire les AVIF et les WebP de
`public-ui/assets/`, aux dimensions que le site affiche réellement.

    python3 scripts/generer_illustrations_tcg.py            # dernier zip déposé
    python3 scripts/generer_illustrations_tcg.py --zip X.zip
    python3 scripts/generer_illustrations_tcg.py --liste    # sans rien écrire

🚨 Deux choses se jouent ici, et les deux ont déjà coûté :

1. **La largeur cible dérive du CADRAGE, pas de la source.** Chaque couche
   occupe une fraction propre de la carte de 340×476 (`heroCote` l'élargit ou
   la rétrécit, `heroEchelle` l'agrandit au survol). Servir la source native,
   c'est payer jusqu'à deux fois les pixels qu'un écran peut montrer ; servir
   moins que la cible, c'est le FLOU au survol — payé le 2026-09-07 avec un
   héros à 900 px pour un besoin de 975.

2. **Chaque image sort en DEUX formats.** L'AVIF pèse deux fois et demie moins
   qu'un WebP de même qualité, mais Safari ne le lit que depuis 16.4 : sans le
   repli, un téléphone plus vieux n'affiche RIEN. `tcg-carte-hero.js` sert la
   paire et ne télécharge que l'AVIF quand il est compris.

Le tableau ci-dessous doit rester en phase avec les cadrages de
`public-ui/pages/tcg-collection.js` : c'est LUI qui décide de la netteté.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from PIL import Image

RACINE = pathlib.Path(__file__).resolve().parent.parent
SOURCES = pathlib.Path("/opt/design-tcg")
CIBLE = RACINE / "public-ui" / "assets"

# La carte fait 340 × 476 px CSS.
CARTE_L = 340

# Marge au-dessus du strict nécessaire : un cadrage se retouche d'une version à
# l'autre, et repasser sous la cible se voit tout de suite alors que 15 % de
# pixels en trop ne se voient jamais.
MARGE = 1.15
# Les écrans des téléphones et des portables récents. Au-delà, le gain est
# invisible et le poids, lui, ne l'est pas.
DPR = 2

# fichier source · nom servi · largeur relative à la carte · échelle au survol
#
# « largeur relative » = ce que le CSS donne à la couche :
#   héros    : 1 − 2 × heroCote        (heroCote négatif ⇒ la couche déborde)
#   pieds    : avantPlanLargeur
#   fond     : 1 + 2 × 18 % puis × 1.06 (`inset: -18%` et `scale(1.06)`)
# « échelle au survol » = heroEchelle pour un calque qui grandit, 1 sinon.
PLAN = [
    # Azraël — un seul visuel, au repos comme au survol (heroCote -14 %).
    ("hero-azrael.png", "tcg-azrael-hero", 1.28, 1.12, 74),
    ("fond-explosion.png", "tcg-azrael-fond", 1.44, 1.06, 70),
    # ClakerNoJutsu — visuel unique cadré serré (5 %), plus ses pieds en
    # avant-plan (pleine largeur, agrandis de 16 % au survol).
    ("claker-hero.png", "tcg-claker-hero", 0.90, 1.10, 74),
    ("claker-pieds.png", "tcg-claker-pieds", 1.00, 1.16, 74),
    ("claker-fond.png", "tcg-claker-fond", 1.44, 1.06, 70),
    # rhae___ — DEUX visuels : le portrait assis au repos (cadré à 8 %, jamais
    # agrandi) et le bond griffes en avant au survol (−26 %, donc bien plus
    # large que la carte, et agrandi de 12 %).
    ("rhae-hero-2d.png", "tcg-rhae-hero-2d", 0.84, 1.00, 74),
    ("rhae-hero-3d.png", "tcg-rhae-hero-3d", 1.52, 1.12, 74),
    ("rhae-fond.png", "tcg-rhae-fond", 1.44, 1.06, 70),
]

QUALITE_WEBP = 88


def dernier_zip() -> pathlib.Path:
    """Le zip le plus récemment déposé dans `/opt/design-tcg/`."""
    zips = sorted(SOURCES.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        raise SystemExit(f"Aucun zip dans {SOURCES} — cf. son LISEZ-MOI.md")
    return zips[-1]


def largeur_cible(part_de_carte: float, echelle: float) -> int:
    return round(CARTE_L * part_de_carte * echelle * DPR * MARGE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", type=pathlib.Path, help="archive à utiliser")
    ap.add_argument("--liste", action="store_true", help="montrer sans écrire")
    args = ap.parse_args()

    archive = args.zip or dernier_zip()
    print(f"source : {archive.name}")

    import tempfile
    import zipfile

    total_avif = 0
    total_webp = 0
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        assets = pathlib.Path(tmp) / "assets"
        if not assets.is_dir():
            raise SystemExit(f"{archive.name} n'a pas de dossier `assets/`")

        for nom, base, part, echelle, q_avif in PLAN:
            src = assets / nom
            if not src.exists():
                print(f"  ⚠  {nom} absent de l'archive — ignoré")
                continue
            im = Image.open(src)
            cible = largeur_cible(part, echelle)
            note = ""
            if im.width > cible:
                im = im.resize((cible, round(im.height * cible / im.width)),
                               Image.LANCZOS)
            else:
                note = f"  (source {im.width} < cible {cible} : servie telle quelle)"
            im = im if im.mode == "RGBA" else im.convert("RGB")

            if args.liste:
                print(f"  {base:20} {im.size}  avif q{q_avif}{note}")
                continue

            avif = CIBLE / f"{base}.avif"
            webp = CIBLE / f"{base}.webp"
            im.save(avif, "AVIF", quality=q_avif)
            im.save(webp, "WEBP", quality=QUALITE_WEBP, method=6)
            total_avif += avif.stat().st_size
            total_webp += webp.stat().st_size
            print(f"  {base:20} {str(im.size):14} "
                  f"avif {avif.stat().st_size // 1024:>4} ko · "
                  f"webp {webp.stat().st_size // 1024:>4} ko{note}")

    if not args.liste:
        print(f"\ntotal servi : {total_avif // 1024} ko "
              f"(repli webp {total_webp // 1024} ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
