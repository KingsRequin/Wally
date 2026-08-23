#!/usr/bin/env python3
"""Le front MONTE-T-IL vraiment ? La seule question que les tests ne posaient pas.

Pourquoi ce script existe. Les 5872 tests du projet ne chargent aucune page :
les tests « front » lisent les fichiers JavaScript en TEXTE, et affirment qu'une
chaîne s'y trouve. Un fichier peut donc être vert de bout en bout et lever une
`ReferenceError` à la première ligne exécutée. C'est arrivé deux fois le même
jour, dans du code qui tournait en production :

  · `app.js` — `_renderParametresVoice()` appelait `makeFormRow()`, définie dans
    trois AUTRES fonctions. Le panneau Paramètres → Vocal se vidait puis levait,
    sans un mot. Ce script le voit : 0 caractère et `makeFormRow is not defined`.
  · `overlay_admin.js` — un bloc greffé dans la mauvaise fonction, `r` indéfini.

Ce que le script vérifie, et qui n'était vérifiable nulle part ailleurs :
  1. l'overlay charge, ses 37 éléments sont dans le DOM, aucune erreur JS ;
  2. les sept onglets du dashboard admin s'ouvrent sans erreur ;
  3. les sous-onglets de Paramètres — dont Vocal — rendent du CONTENU.

Le « sans erreur » ne suffit pas seul : un panneau peut rester vide en silence.
On mesure donc aussi ce qui est écrit dedans.

Rien à rebuilder : `bot/dashboard/static/` est bind-monté, le navigateur voit le
fichier du disque. Le script s'adresse à `127.0.0.1:8080`, pas au tunnel.

Prérequis (hôte seulement, JAMAIS dans l'image — 115 Mo de navigateur) :
    pip install --break-system-packages playwright
    python3 -m playwright install chromium

Usage :
    python3 scripts/smoke_front.py                 # tout
    python3 scripts/smoke_front.py --overlay        # overlay seul
    python3 scripts/smoke_front.py --captures /tmp  # écrit les PNG
"""
from __future__ import annotations

import argparse
import pathlib
import sys

BASE = "http://127.0.0.1:8080"
_RACINE = pathlib.Path(__file__).resolve().parent.parent

# Les sept de la sidebar, dans l'ordre où ils apparaissent.
ONGLETS = ["Paramètres", "Mémoire", "Actions", "Prompts",
           "Mise en scène", "Système", "Vocal"]

# Sous-onglets de Paramètres et l'id du panneau qu'ils remplissent. C'est ici
# que vivait le défaut : un sous-onglet peut être le seul cassé des quatre.
SOUS_PARAMETRES = [
    ("Émotions", "parametres-sub-emotions"),
    ("LLM", "parametres-sub-llm"),
    ("Images", "parametres-sub-images"),
    ("Vocal", "parametres-sub-vocal"),
]

# Un panneau qui rend moins que ça n'a rien monté : même vide de données, il
# porte son titre et ses libellés.
_CONTENU_MIN = 40

# Attente MAXIMALE avant de déclarer un panneau vide — et non une pause fixe.
# Une pause fixe a rendu ce script instable dès sa première exécution : le
# panneau LLM interroge les providers et met parfois plus de deux secondes, il
# est sorti « 0 caractère » alors qu'il en rendait 3456. Un smoke test qui crie
# à tort est pire qu'aucun smoke test : on finit par ignorer ses rouges, et le
# jour où le panneau est vraiment mort, personne ne regarde.
_ATTENTE_PANNEAU_MS = 15000


def _token() -> str:
    import yaml
    cfg = yaml.safe_load((_RACINE / "config.yaml").read_text(encoding="utf-8"))
    jeton = (cfg.get("bot") or {}).get("dashboard_token")
    if not jeton:
        raise SystemExit("❌ `bot.dashboard_token` absent de config.yaml")
    return jeton


class Rapport:
    def __init__(self) -> None:
        self.echecs: list[str] = []

    def dire(self, ok: bool, libelle: str, detail: str = "") -> None:
        print(f"  {'✅' if ok else '❌'} {libelle}{'  — ' + detail if detail else ''}")
        if not ok:
            self.echecs.append(f"{libelle} : {detail}")


def _brancher_erreurs(page) -> list[str]:
    """Collecte les erreurs JS. Les deux canaux comptent : une exception non
    rattrapée arrive par `pageerror`, un `console.error` par `console`."""
    vues: list[str] = []
    page.on("pageerror", lambda e: vues.append(str(e)))
    page.on("console", lambda m: vues.append(m.text) if m.type == "error" else None)
    return vues


def _attendre_contenu(page, ident: str) -> int:
    """Le nombre de caractères rendus dans ce panneau, une fois qu'il en a.

    On attend que le contenu ARRIVE plutôt que de dormir un temps arbitraire :
    les panneaux qui interrogent le réseau (LLM va chercher les providers) sont
    lents de façon imprévisible. Rend 0 si rien n'est venu dans le délai — et
    c'est alors un vrai panneau mort, pas une course perdue.
    """
    mesure = ("(id) => (document.getElementById(id)||{}).innerText?.trim().length || 0")
    try:
        page.wait_for_function(
            "([id, mini]) => ((document.getElementById(id)||{}).innerText?.trim().length || 0) >= mini",
            arg=[ident, _CONTENU_MIN], timeout=_ATTENTE_PANNEAU_MS)
    except Exception:
        # Délai dépassé : on retombe sur la mesure brute, qui dira 0 ou presque.
        # Pas de `raise` — l'appelant veut le CHIFFRE pour son rapport, pas une
        # exception qui interromprait les panneaux suivants.
        pass
    return page.evaluate(mesure, ident)


def verifier_overlay(nav, rap: Rapport, captures: pathlib.Path | None) -> None:
    print("\n── overlay OBS ──")
    page = nav.new_page(viewport={"width": 1920, "height": 1080})
    erreurs = _brancher_erreurs(page)
    page.goto(f"{BASE}/static/overlay.html", wait_until="networkidle", timeout=40000)
    page.wait_for_timeout(2500)

    rap.dire(page.title() == "Wally Overlay", "la page se charge", page.title())
    n = page.locator("[data-element]").count()
    # 37, comme les 37 éléments du panneau de mise en scène. En trouver moins
    # veut dire qu'un widget n'est plus plaçable, sans que rien ne le dise.
    rap.dire(n >= 37, f"{n} éléments dans le DOM", "attendu ≥ 37")
    rap.dire(not erreurs, "aucune erreur JS", " · ".join(erreurs[:2]))

    if captures:
        page.screenshot(path=str(captures / "overlay.png"))
    page.close()


def verifier_admin(nav, rap: Rapport, captures: pathlib.Path | None) -> None:
    print("\n── dashboard admin ──")
    page = nav.new_page(viewport={"width": 1600, "height": 1000})
    page.add_init_script(f"localStorage.setItem('wally_token', {_token()!r});")
    erreurs = _brancher_erreurs(page)
    page.goto(f"{BASE}/static/index.html", wait_until="networkidle", timeout=40000)
    page.wait_for_timeout(2500)
    rap.dire(not erreurs, "le SPA se monte sans erreur", " · ".join(erreurs[:2]))

    for nom in ONGLETS:
        del erreurs[:]
        cible = page.get_by_text(nom, exact=True).first
        if cible.count() == 0:
            rap.dire(False, f"onglet {nom}", "introuvable dans la sidebar")
            continue
        cible.click()
        page.wait_for_timeout(1800)
        rap.dire(not erreurs, f"onglet {nom}", " · ".join(erreurs[:2]))

    print("\n── sous-onglets de Paramètres ──")
    page.get_by_text("Paramètres", exact=True).first.click()
    page.wait_for_timeout(1200)
    for nom, ident in SOUS_PARAMETRES:
        del erreurs[:]
        page.get_by_text(nom, exact=True).last.click()
        taille = _attendre_contenu(page, ident)
        # Les deux conditions, pas une : sans erreur mais vide reste un panneau
        # mort, et c'est exactement la forme qu'avait le défaut.
        rap.dire(not erreurs and taille >= _CONTENU_MIN,
                 f"Paramètres → {nom}",
                 f"{taille} car." + (" · " + erreurs[0] if erreurs else ""))

    if captures:
        page.screenshot(path=str(captures / "admin.png"))
    page.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--overlay", action="store_true", help="overlay seulement")
    ap.add_argument("--admin", action="store_true", help="dashboard seulement")
    ap.add_argument("--captures", metavar="DOSSIER", help="y écrire les PNG")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        # Outil absent ≠ front sain. On le DIT et on rend 1, même règle que
        # pour les quatre cliquets.
        print("❌ playwright absent — `pip install --break-system-packages playwright`\n"
              "   puis `python3 -m playwright install chromium`", file=sys.stderr)
        return 1

    captures = pathlib.Path(args.captures) if args.captures else None
    tout = not (args.overlay or args.admin)
    rap = Rapport()

    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--no-sandbox"])
        try:
            if tout or args.overlay:
                verifier_overlay(nav, rap, captures)
            if tout or args.admin:
                verifier_admin(nav, rap, captures)
        finally:
            nav.close()

    print()
    if rap.echecs:
        print(f"❌ {len(rap.echecs)} vérification(s) en échec :", file=sys.stderr)
        for e in rap.echecs:
            print(f"   · {e}", file=sys.stderr)
        return 1
    print("✅ le front monte — overlay et dashboard, sans erreur JS ni panneau vide")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
