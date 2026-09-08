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

# La carte fait 680 px de large là où elle est REGARDÉE : sur l'overlay OBS,
# où l'owner l'a dimensionnée à ~680 × 952 le 2026-09-08, et sur le site à
# 340 px CSS × DPR 2. Le même chiffre des deux côtés, ce n'est pas une
# coïncidence heureuse — c'est `--chero-k: 2` qui l'aligne.
CARTE_L = 680

# Marge au-dessus du strict nécessaire : un cadrage se retouche d'une version à
# l'autre, et repasser sous la cible se voit tout de suite alors que 15 % de
# pixels en trop ne se voient jamais.
MARGE = 1.10
# 1 : `CARTE_L` est déjà exprimé en pixels PHYSIQUES (680, cf. ci-dessus). Le
# facteur était compté deux fois, et toutes les illustrations sortaient deux
# fois trop grandes.
DPR = 1

# 🚨 Deux qualités, et la différence n'est pas cosmétique.
#
# Les HÉROS sont regardés : ce sont eux qu'on reconnaît. Les FONDS sont
# recouverts d'une trame de points, assombris par une vignette, et parcourus
# par un reflet — personne ne les lit en détail. Les servir à la qualité d'un
# portrait, c'est payer deux fois pour un décor.
#
# Mesuré le 2026-09-08 : à q52 l'écart avec q74 est de 2,4/255 en moyenne, soit
# 1 % — imperceptible sur une illustration à aplats — pour 37 % de poids en
# moins. Un jeu de 45 cartes passe de 11 Mo à 4.
QUALITE_HEROS = 56
QUALITE_FOND = 48
# Le fond est en plus servi RÉDUIT : sous la trame et la vignette, sa
# définition ne se voit pas. 65 % de la largeur utile.
PART_FOND = 0.65

# fichier source · nom servi · largeur relative à la carte · échelle au survol
#
# « largeur relative » = ce que le CSS donne à la couche :
#   héros    : 1 − 2 × heroCote        (heroCote négatif ⇒ la couche déborde)
#   pieds    : avantPlanLargeur
#   fond     : 1 + 2 × 18 % puis × 1.06 (`inset: -18%` et `scale(1.06)`)
# « échelle au survol » = heroEchelle pour un calque qui grandit, 1 sinon.
PLAN = [
    # Azraël — un seul visuel, au repos comme au survol (heroCote -14 %).
    ("hero-azrael.png", "tcg-azrael-hero", 1.28, 1.12),
    ("fond-explosion.png", "tcg-azrael-fond", 1.44, 1.06),
    # ClakerNoJutsu — visuel unique cadré serré (5 %), plus ses pieds en
    # avant-plan (pleine largeur, agrandis de 16 % au survol).
    ("claker-hero.png", "tcg-claker-hero", 0.90, 1.10),
    ("claker-pieds.png", "tcg-claker-pieds", 1.00, 1.16),
    ("claker-fond.png", "tcg-claker-fond", 1.44, 1.06),
    # rhae___ — DEUX visuels : le portrait assis au repos (cadré à 8 %, jamais
    # agrandi) et le bond griffes en avant au survol (−26 %, donc bien plus
    # large que la carte, et agrandi de 12 %).
    ("rhae-hero-2d.png", "tcg-rhae-hero-2d", 0.84, 1.00),
    ("rhae-hero-3d.png", "tcg-rhae-hero-3d", 1.52, 1.12),
    ("rhae-fond.png", "tcg-rhae-fond", 1.44, 1.06),
    # Lilith — ailes déployées : l'illustration fait presque DEUX fois la
    # largeur de la carte (`heroCote: -40%`). Au repos les pointes d'ailes sont
    # rognées, au survol elles sortent du cadre.
    ("lilith-hero.png", "tcg-lilith-hero", 1.80, 1.08),
    ("lilith-fond.png", "tcg-lilith-fond", 1.44, 1.06),
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

        for nom, base, part, echelle in PLAN:
            # Un fond se reconnaît à son nom : c'est le seul endroit du plan
            # où la distinction héros/décor a besoin d'être faite.
            est_fond = base.endswith("-fond")
            q_avif = QUALITE_FOND if est_fond else QUALITE_HEROS
            src = assets / nom
            if not src.exists():
                print(f"  ⚠  {nom} absent de l'archive — ignoré")
                continue
            im = Image.open(src)
            cible = largeur_cible(part, echelle)
            if est_fond:
                cible = round(cible * PART_FOND)
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
