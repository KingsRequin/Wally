#!/usr/bin/env python3
"""Synchronise le TCG entre la base Notion « 🃏 Cartes du Purgatoire » et les YAML.

⚖️ NOTION FAIT FOI — arbitrage de l'owner du 2026-09-12. Les YAML (`tcg/cartes.yaml`
pour les héros, `tcg/cartes_action.yaml` pour les cartes action/passif) sont ce que
le bot LIT au boot ; la base Notion est ce que l'owner ÉDITE. Ce script tient les
deux en phase.

🚨 Il ne sait aujourd'hui qu'un seul sens, POUSSER (YAML → Notion), et c'est
délibéré. Le retour demanderait de réécrire les YAML, qui portent ensemble plus de
cent lignes de commentaires expliquant chaque piège payé — `yaml.dump` les
effacerait toutes, en silence, et personne ne s'en apercevrait avant d'aller
chercher pourquoi une décision avait été prise. Il faudra `ruamel.yaml` en
round-trip, ou une réécriture ancrée symbole par symbole. En attendant, `--etat`
NOMME les écarts au lieu de les résoudre : un écart affiché se corrige à la main,
un écart appliqué de travers se découvre en prod.

Le secret vit dans `/root/.secrets/notion.env`, hors de tout dépôt.

    python3 scripts/sync_tcg_notion.py            # l'état, sans rien écrire
    python3 scripts/sync_tcg_notion.py --pousser  # YAML → Notion
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.core.tcg_cartes import CARTES  # noqa: E402
from bot.core.tcg_cartes_action import CARTES_ACTION, rendre_regle  # noqa: E402

CHEMIN_SECRET = Path("/root/.secrets/notion.env")
BASE = "eb3f9319-0b30-444c-b877-0728a6f40ac3"
API = "https://api.notion.com/v1"
VERSION_API = "2022-06-28"

# 🚨 Les trois cartes renommées avec l'owner le 2026-09-12 n'ont plus le titre
# sous lequel Notion les connaît. C'est précisément pour ça que la colonne `Clé`
# existe : cette table ne sert qu'au PREMIER appariement, celui qui la remplit.
# Une fois la clé posée, les renommages suivants ne cassent plus rien.
TITRES_HISTORIQUES = {
    "flatline_azrael": "Flatline",
    "push_3_teams": "Amitié",
    "lyly": "Lyly",
    "les_trois_chats": "Pika, Spiro et Lili",
    "rhum": "Le Rhum",
    "tunnel_rina": "Le tunnel de Rina",
    # Les héros sont rangés dans Notion sous le PSEUDO de la personne, pas sous
    # le nom de scène de la carte : « CLAKER » la carte, `ClakerNoJutsu` la
    # ligne. C'est voulu — la fiche sert aussi au point du consentement — et
    # c'est exactement ce qu'aucune normalisation de titre ne rattrapera.
    "claker": "ClakerNoJutsu",
    "lilith": "lilith220501",
    "rhae": "rhae___",
    "kingsrequin": "KingsRequin",
    "meliodas": "meliodas987_",
}


def _jeton() -> str:
    """Le jeton d'intégration, lu au moment de s'en servir et jamais stocké."""
    if not CHEMIN_SECRET.is_file():
        sys.exit(f"Secret absent : {CHEMIN_SECRET}")
    for ligne in CHEMIN_SECRET.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("NOTION_TOKEN="):
            return ligne.split("=", 1)[1].strip()
    sys.exit(f"NOTION_TOKEN absent de {CHEMIN_SECRET}")


def _appel(jeton: str, chemin: str, corps: dict | None = None,
           methode: str = "POST") -> dict:
    requete = urllib.request.Request(
        f"{API}{chemin}",
        data=json.dumps(corps).encode() if corps is not None else None,
        headers={
            "Authorization": f"Bearer {jeton}",
            "Notion-Version": VERSION_API,
            "Content-Type": "application/json",
        },
        method=methode,
    )
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            return json.loads(reponse.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        sys.exit(f"Notion {exc.code} sur {methode} {chemin} : {detail}")


def _lire_base(jeton: str) -> list[dict]:
    """Toutes les lignes de la base, pagination comprise.

    ⚠️ Sans la boucle sur `next_cursor`, on lirait 100 lignes et on croirait que
    c'est tout — la base en a 72 aujourd'hui, elle en aura plus.
    """
    lignes: list[dict] = []
    curseur: str | None = None
    while True:
        corps: dict[str, Any] = {"page_size": 100}
        if curseur:
            corps["start_cursor"] = curseur
        page = _appel(jeton, f"/databases/{BASE}/query", corps)
        lignes.extend(page["results"])
        if not page.get("has_more"):
            return lignes
        curseur = page["next_cursor"]


def _texte(propriete: dict | None) -> str:
    if not propriete:
        return ""
    morceaux = propriete.get("title") or propriete.get("rich_text") or []
    return "".join(m["plain_text"] for m in morceaux).strip()


def _normaliser(valeur: str) -> str:
    """Pour comparer deux titres écrits par deux mains différentes.

    Accents, casse et ponctuation sautent : « Quoi → FEUR » et « quoi feur »
    doivent s'apparier, sinon le premier passage laisse des orphelines qu'on
    apparie à la main une par une.
    """
    sans_accent = unicodedata.normalize("NFKD", valeur.lower())
    sans_accent = "".join(c for c in sans_accent if not unicodedata.combining(c))
    return "".join(c for c in sans_accent if c.isalnum())


def _attendu() -> dict[str, dict]:
    """Ce que les YAML disent de chaque carte, prêt à écrire dans Notion."""
    attendu: dict[str, dict] = {}
    for carte in CARTES_ACTION.values():
        attendu[carte.cle] = {
            "Titre": carte.court,
            "Sous-titre": carte.nom,
            # La règle RENDUE : Notion doit montrer ce que le joueur lit, pas
            # le gabarit `${degats}` que seul le lecteur sait résoudre.
            "Description": rendre_regle(carte),
            "Type": carte.type,
            "Catégorie": carte.categorie.replace("controle", "contrôle"),
            "Coût": carte.cout,
        }
    for heros in CARTES.values():
        attendu[heros.cle] = {
            "Titre": heros.nom,
            "Sous-titre": heros.ambiance,
            "Description": heros.description,
            "Type": "héros",
            "PV": heros.pv,
            "Attaque": heros.atk,
            "Aura": heros.aura,
            "Coût": heros.cout,
        }
    return attendu


def _apparier(lignes: list[dict]) -> tuple[dict[str, dict], list[dict], list[str]]:
    """Relie chaque clé YAML à sa ligne Notion.

    D'abord par la colonne `Clé`, qui est l'identifiant STABLE. À défaut par le
    titre — ce qui ne vaut que pour le premier passage, celui qui pose les clés.
    """
    attendu = _attendu()
    par_cle = {_texte(l["properties"].get("Clé")): l
               for l in lignes if _texte(l["properties"].get("Clé"))}
    par_titre: dict[str, dict] = {}
    for ligne in lignes:
        par_titre.setdefault(_normaliser(_texte(ligne["properties"].get("Carte"))), ligne)

    couples: dict[str, dict] = {}
    for cle, valeurs in attendu.items():
        ligne = par_cle.get(cle)
        if ligne is None:
            for candidat in (TITRES_HISTORIQUES.get(cle), valeurs["Titre"],
                             valeurs["Sous-titre"]):
                if candidat and (ligne := par_titre.get(_normaliser(candidat))):
                    break
        if ligne is not None:
            couples[cle] = ligne

    appariees = {l["id"] for l in couples.values()}
    orphelines = [l for l in lignes if l["id"] not in appariees]
    absentes = [cle for cle in attendu if cle not in couples]
    return couples, orphelines, absentes


def _ecart(ligne: dict, champ: str, voulu) -> tuple[str, str] | None:
    """Ce que Notion porte contre ce que le YAML dit, ou None s'ils s'accordent."""
    propriete = ligne["properties"].get(champ)
    if propriete is None:
        return None
    genre = propriete["type"]
    if genre in ("rich_text", "title"):
        actuel: Any = _texte(propriete)
    elif genre == "select":
        actuel = (propriete["select"] or {}).get("name", "")
        voulu = voulu or ""
    elif genre == "number":
        actuel = propriete["number"]
    else:
        return None
    return None if actuel == voulu else (str(actuel), str(voulu))


def _charge(champ: str, ligne: dict, valeur) -> dict:
    genre = ligne["properties"][champ]["type"]
    if genre == "select":
        return {"select": {"name": valeur} if valeur else None}
    if genre == "number":
        return {"number": valeur}
    return {"rich_text": [{"text": {"content": str(valeur)}}]}


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--pousser", action="store_true",
                           help="écrit Notion depuis les YAML")
    options = analyseur.parse_args()

    jeton = _jeton()
    lignes = _lire_base(jeton)
    attendu = _attendu()
    couples, orphelines, absentes = _apparier(lignes)

    print(f"{len(lignes)} lignes Notion · {len(attendu)} cartes YAML · "
          f"{len(couples)} appariées")
    if absentes:
        print(f"\n🚨 {len(absentes)} cartes YAML SANS ligne Notion — elles "
              f"n'existent que dans le repo :")
        for cle in absentes:
            print(f"   {cle}  ({attendu[cle]['Titre']})")
    if orphelines:
        print(f"\n⚠️ {len(orphelines)} lignes Notion sans carte YAML — fiches "
              f"sans carte, à écrire ou à retirer :")
        for ligne in orphelines:
            print(f"   {_texte(ligne['properties'].get('Carte'))}")

    a_ecrire: list[tuple[str, dict, dict]] = []
    for cle, ligne in couples.items():
        charges: dict[str, dict] = {}
        ecarts: list[str] = []
        if _texte(ligne["properties"].get("Clé")) != cle:
            charges["Clé"] = _charge("Clé", ligne, cle)
            ecarts.append("Clé → " + cle)
        for champ, valeur in attendu[cle].items():
            if (diff := _ecart(ligne, champ, valeur)) is not None:
                charges[champ] = _charge(champ, ligne, valeur)
                ecarts.append(f"{champ} : {diff[0]!r} → {diff[1]!r}")
        if charges:
            a_ecrire.append((cle, ligne, charges))
            print(f"\n{cle}")
            for ligne_ecart in ecarts:
                print(f"   {ligne_ecart}")

    if not a_ecrire:
        print("\n✅ Notion et les YAML disent la même chose.")
        return 0
    if not options.pousser:
        print(f"\n{len(a_ecrire)} lignes à mettre à jour. "
              f"`--pousser` pour les écrire.")
        return 0

    a_relire: list[str] = []
    for cle, ligne, charges in a_ecrire:
        _appel(jeton, f"/pages/{ligne['id']}", {"properties": charges},
               methode="PATCH")
        print(f"✅ {cle}")
        # 🚨 Le CORPS de la page (la fiche détaillée : « Ce qu'elle fait »,
        # « Exemple », « À savoir ») n'est pas synchronisé — il est rédigé, pas
        # dérivé. Quand la description change sous une fiche déjà écrite, la
        # fiche se met à mentir, et rien ne le signale. Vécu le 2026-09-12 sur
        # le care package : la fiche vendait « tu sais ce que tu piocheras
        # ensuite » après que la carte eut cessé de le permettre.
        if "Description" in charges and _appel(
                jeton, f"/blocks/{ligne['id']}/children?page_size=1",
                methode="GET")["results"]:
            a_relire.append(cle)
    print(f"\n{len(a_ecrire)} lignes écrites dans Notion.")
    if a_relire:
        print(f"\n⚠️ {len(a_relire)} fiche(s) détaillée(s) à RELIRE — leur "
              f"description vient de changer sous un texte déjà rédigé :")
        for cle in a_relire:
            print(f"   {cle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
