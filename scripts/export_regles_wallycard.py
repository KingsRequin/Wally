#!/usr/bin/env python3
"""Exporte le livre des règles de Wallycard, de Notion vers le site.

Le sens INVERSE de `sync_tcg_notion.py` : lui pousse les YAML dans Notion, celui-ci
tire le texte des règles vers `public-ui/donnees/wallycard-regles.json`, que la page
`/wallycard/regles` lit. Le site ne lit jamais Notion en direct (arbitrage de l'owner,
spec `2026-09-13-wallycard-site-design.md` §4) : une page publique ne doit pas
dépendre d'une API tierce ni exposer le jeton.

Deux sources :
- la page « Wallycard : règles du jeu », chapitre par chapitre. Les sections
  « À trancher » et « Propositions » ne sont PAS publiées : le livre ne dit que ce
  qui est décidé ;
- le corps des fiches détaillées de la base (« Ce qu'elle fait », « Exemple »,
  « À savoir »), une par carte action ou passif.

🚨 Un type de bloc inconnu ARRÊTE l'export. Le rendre à moitié (bloc sauté)
publierait une règle amputée sans que personne ne le voie.

⚠️ L'intégration ne voit la page des règles que si elle lui est PARTAGÉE (dans
Notion : ••• → Connexions). Sans ce partage, l'API répond 404 : les chapitres déjà
exportés sont GARDÉS tels quels, les fiches sont rafraîchies, et le script le dit.

    python3 scripts/export_regles_wallycard.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.core.tcg_cartes_action import CARTES_ACTION  # noqa: E402
from scripts.sync_tcg_notion import API, VERSION_API, _appel, _jeton, _lire_base, _texte  # noqa: E402

PAGE_REGLES = "3dae93ddd54581428c3cd6b054371605"
SORTIE = Path(__file__).resolve().parent.parent / "public-ui" / "donnees" / "wallycard-regles.json"

# Un chapitre dont le titre commence par l'un de ces signes ouvre la partie NON
# décidée de la page : on s'arrête là.
DEBUT_NON_PUBLIE = ("❓", "💡")

_ID_NOTION = re.compile(r"([0-9a-f]{32})")

_BLOCS_TEXTE = {
    "heading_1": "h1",
    "heading_2": "h2",
    "heading_3": "h3",
    "paragraph": "p",
    "quote": "citation",
}
_LISTES = {"bulleted_list_item": "ul", "numbered_list_item": "ol"}


def _sans_tirets(identifiant: str) -> str:
    return identifiant.replace("-", "")


def _segments(rich_text: list[dict], cartes: dict[str, str]) -> list[dict]:
    """Le texte riche Notion, réduit à ce que la page sait afficher.

    `cartes` relie l'id (sans tirets) d'une ligne de la base à la clé de sa carte :
    une carte citée devient un lien vers sa fiche, où qu'elle soit citée.
    """
    sortie: list[dict] = []
    for morceau in rich_text:
        seg: dict[str, Any] = {"t": morceau["plain_text"]}
        notes = morceau.get("annotations") or {}
        if notes.get("bold"):
            seg["g"] = True
        if notes.get("italic"):
            seg["i"] = True
        cible = ""
        if morceau["type"] == "mention" and morceau["mention"].get("type") == "page":
            cible = _sans_tirets(morceau["mention"]["page"]["id"])
        elif morceau.get("href"):
            trouve = _ID_NOTION.search(_sans_tirets(morceau["href"]))
            cible = trouve.group(1) if trouve and "notion" in morceau["href"] else ""
            if not cible:
                seg["lien"] = morceau["href"]
        if cible in cartes:
            seg["carte"] = cartes[cible]
            if morceau["type"] == "mention":
                # Une mention porte le TITRE de la ligne Notion (« Quoi → FEUR ») ;
                # le livre nomme les cartes par leur nom court, comme la prose autour.
                seg["t"] = CARTES_ACTION[cartes[cible]].court
        sortie.append(seg)
    return sortie


def convertir_blocs(blocs: list[dict], cartes: dict[str, str], lire_enfants=None) -> list[dict]:
    """Les blocs Notion en blocs de page. Les puces consécutives forment UNE liste.

    `lire_enfants(id)` rend les lignes d'un tableau ; il n'est appelé que pour eux.
    """
    sortie: list[dict] = []
    for bloc in blocs:
        genre = bloc["type"]
        contenu = bloc[genre]
        if genre == "divider":
            continue
        if genre in _BLOCS_TEXTE:
            sortie.append({"type": _BLOCS_TEXTE[genre], "texte": _segments(contenu["rich_text"], cartes)})
        elif genre in _LISTES:
            liste = _LISTES[genre]
            if not sortie or sortie[-1]["type"] != liste:
                sortie.append({"type": liste, "items": []})
            sortie[-1]["items"].append(_segments(contenu["rich_text"], cartes))
        elif genre == "table" and lire_enfants is not None:
            lignes = [
                [_segments(cellule, cartes) for cellule in ligne["table_row"]["cells"]]
                for ligne in lire_enfants(bloc["id"])
            ]
            sortie.append({"type": "table", "entete": bool(contenu.get("has_column_header")), "lignes": lignes})
        else:
            raise ValueError(f"bloc Notion non géré : {genre} ({bloc.get('id')})")
        if bloc.get("has_children") and genre != "table":
            raise ValueError(f"bloc imbriqué non géré : {genre} ({bloc.get('id')})")
    return sortie


def decouper_chapitres(blocs: list[dict]) -> list[dict]:
    """Un chapitre par titre de niveau 1, jusqu'à la partie non décidée.

    Ce qui précède le premier titre (l'avertissement de la page Notion, qui
    renvoie aux sections « À trancher ») n'est pas publié : il parle de la page de
    travail, pas du jeu.
    """
    chapitres: list[dict] = []
    for bloc in blocs:
        if bloc["type"] == "h1":
            titre = "".join(s["t"] for s in bloc["texte"]).strip()
            if titre.startswith(DEBUT_NON_PUBLIE):
                break
            chapitres.append({"titre": titre, "blocs": []})
        elif chapitres:
            chapitres[-1]["blocs"].append(bloc)
    return chapitres


def _enfants(jeton: str, bloc_id: str) -> list[dict] | None:
    """Tous les blocs enfants, pagination comprise. `None` si l'intégration ne voit pas le bloc."""
    blocs: list[dict] = []
    curseur = ""
    while True:
        chemin = f"/blocks/{bloc_id}/children?page_size=100" + (f"&start_cursor={curseur}" if curseur else "")
        requete = urllib.request.Request(
            f"{API}{chemin}",
            headers={"Authorization": f"Bearer {jeton}", "Notion-Version": VERSION_API},
        )
        try:
            with urllib.request.urlopen(requete, timeout=30) as reponse:
                page = json.loads(reponse.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        blocs.extend(page["results"])
        if not page.get("has_more"):
            return blocs
        curseur = page["next_cursor"]


def main() -> int:
    jeton = _jeton()
    lignes = _lire_base(jeton)
    cartes: dict[str, str] = {}
    for ligne in lignes:
        cle = _texte(ligne["properties"].get("Clé"))
        if cle in CARTES_ACTION:
            cartes[_sans_tirets(ligne["id"])] = cle

    def lire(bloc_id: str) -> list[dict]:
        blocs = _enfants(jeton, bloc_id)
        if blocs is None:
            sys.exit(f"Bloc {bloc_id} invisible pour l'intégration")
        return blocs

    fiches = []
    for id_ligne, cle in cartes.items():
        blocs = convertir_blocs(lire(id_ligne), cartes, lire)
        if blocs:
            carte = CARTES_ACTION[cle]
            fiches.append({"cle": cle, "court": carte.court, "nom": carte.nom, "type": carte.type, "blocs": blocs})
    fiches.sort(key=lambda f: f["court"])
    sans_fiche = sorted(set(CARTES_ACTION) - {f["cle"] for f in fiches})

    ancien = json.loads(SORTIE.read_text(encoding="utf-8")) if SORTIE.is_file() else {}
    blocs_regles = _enfants(jeton, PAGE_REGLES)
    if blocs_regles is None:
        chapitres = ancien.get("chapitres", [])
        print("⚠️ Page des règles invisible pour l'intégration (404) : chapitres GARDÉS de l'export précédent.")
        print("   À faire dans Notion : page « Wallycard : règles du jeu » → ••• → Connexions → l'intégration.")
    else:
        chapitres = decouper_chapitres(convertir_blocs(blocs_regles, cartes, lire))

    contenu = {"chapitres": chapitres, "fiches": fiches}
    # La date ne bouge que si le TEXTE a bougé : un export relancé à vide ne
    # produit aucun diff, et la date affichée reste celle du dernier changement.
    if {k: ancien.get(k) for k in contenu} == contenu and "exporte_le" in ancien:
        print(f"Aucun changement : {len(chapitres)} chapitres, {len(fiches)} fiches.")
        return 0
    contenu = {"exporte_le": datetime.now(timezone.utc).strftime("%Y-%m-%d"), **contenu}
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(contenu, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"✅ {SORTIE.name} : {len(chapitres)} chapitres, {len(fiches)} fiches.")
    if sans_fiche:
        print(f"⚠️ {len(sans_fiche)} carte(s) sans fiche : {', '.join(sans_fiche)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
