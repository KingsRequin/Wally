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
  2. les onze pages du dashboard admin s'ouvrent sans erreur ;
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

# Les pages de la sidebar, dans l'ordre où elles apparaissent. Depuis la
# refonte du 2026-08-28 (docs/plans/2026-08-28-refonte-panel-admin-plan.md), ce
# sont des ROUTES : cliquer l'entrée pose `#/cerveau/personnes` et le routeur
# monte la page. Le parcours vaut donc aussi comme test du routeur.
# On clique l'entrée par sa ROUTE, pas par son libellé : depuis la refonte,
# « Mémoire commune » et « Voix » nomment aussi des titres et des pilules à
# l'intérieur des panneaux, et un clic par texte visait un `<h2>` caché.
ONGLETS = [
    ("Personnes", "cerveau/personnes"),
    ("Mémoire commune", "cerveau/memoire"),
    ("Personnalité", "cerveau/personnalite"),
    ("Textes de référence", "cerveau/textes"),
    ("Modèles & coûts", "cerveau/modeles"),
    ("Scène & overlays", "live/scene"),
    ("Voix", "live/voix"),
    ("Médias & sons", "live/medias"),
    ("Automatisations", "live/automatisations"),
    ("Journal", "systeme/journal"),
    ("Connexions", "systeme/connexions"),
]

# Sous-onglets, et l'id du panneau que chacun remplit. C'est ici que vivait le
# défaut : un sous-onglet peut être le seul cassé de sa famille, l'onglet parent
# s'ouvrant sans erreur.
#
# Mémoire manquait entièrement à ce parcours — sept panneaux, dont ceux qui
# portent les gens et leur mémoire, montaient sans qu'aucun outil ne le vérifie.
# Le premier terme est la PAGE par laquelle on arrive sur l'ancien panneau —
# la refonte se fait par étapes, ces sous-onglets vivent encore derrière leur
# nouvelle route. Ils disparaîtront panneau par panneau, chacun avec sa phase.
SOUS_ONGLETS = [
    ("cerveau/personnalite", [
        ("Émotions", "parametres-sub-emotions"),
        ("LLM", "parametres-sub-llm"),
        ("Images", "parametres-sub-images"),
        ("Vocal", "parametres-sub-vocal"),
    ]),
    ("cerveau/personnes", [
        ("Utilisateurs", "memoire-sub-users"),
        ("Mémoire communautaire", "memoire-sub-global"),
        ("Questions", "memoire-sub-dashboard"),
        ("Notes du bot", "memoire-sub-notes"),
        ("Comptes Apex", "memoire-sub-apex"),
        ("Dans la tête de Wally", "memoire-sub-self"),
        ("Ignorés", "memoire-sub-ignores"),
    ]),
    ("systeme/connexions", [
        ("Twitch", "systeme-sub-twitch"),
        ("Overlay", "systeme-sub-overlay"),
    ]),
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

    for nom, route in ONGLETS:
        del erreurs[:]
        cible = page.locator(f'.sidebar-item[data-route="{route}"]')
        if cible.count() == 0:
            rap.dire(False, f"page {nom}", "introuvable dans la sidebar")
            continue
        cible.click()
        page.wait_for_timeout(1800)
        # Le clic doit avoir posé le hash : c'est LUI qui rend l'URL
        # partageable et le rechargement fidèle. Un `onclick` qui monte le
        # panneau sans toucher l'URL passerait le reste du test sans broncher.
        hash_vu = page.evaluate("location.hash")
        rap.dire(not erreurs and hash_vu == f"#/{route}",
                 f"page {nom}",
                 f"hash {hash_vu!r}" + (" · " + erreurs[0] if erreurs else ""))

    for route, enfants in SOUS_ONGLETS:
        print(f"\n── sous-onglets derrière {route} ──")
        page.locator(f'.sidebar-item[data-route="{route}"]').click()
        page.wait_for_timeout(1200)
        for nom, ident in enfants:
            del erreurs[:]
            # La pilule est visée par son `data-subtab`, dans le panneau ACTIF.
            # Le nom seul ne suffit plus : « Mémoire communautaire » désigne
            # aussi une entrée de sidebar et un titre de panneau.
            sous = ident.split("-sub-", 1)[1]
            page.locator(
                f'.tab-content.active .mem-subnav-pill[data-subtab="{sous}"]'
            ).first.click()
            taille = _attendre_contenu(page, ident)
            # Les deux conditions, pas une : sans erreur mais vide reste un
            # panneau mort, et c'est exactement la forme qu'avait le défaut.
            rap.dire(not erreurs and taille >= _CONTENU_MIN,
                     f"{route} → {nom}",
                     f"{taille} car." + (" · " + erreurs[0] if erreurs else ""))

    _verifier_journal(page, rap, erreurs)

    if captures:
        page.screenshot(path=str(captures / "admin.png"))
    page.close()


def _verifier_journal(page, rap: Rapport, erreurs: list[str]) -> None:
    """Le Journal est la première page vraiment REFAITE par la refonte.

    Ses trois barres d'onglets sont devenues des filtres, et l'état de ces
    filtres vit dans l'URL. Rien de tout ça n'est visible d'un test qui lit les
    fichiers en texte : il faut cliquer, et regarder ce que le hash devient.
    """
    print("\n── Système › Journal ──")
    del erreurs[:]
    page.locator('.sidebar-item[data-route="systeme/journal"]').click()
    page.wait_for_timeout(1500)

    lignes = page.locator("#log-stream .log-entry").count()
    rap.dire(lignes > 0, "le flux porte des lignes", f"{lignes} ligne(s)")

    # Une puce de sous-système n'est PAS listée en dur : elle apparaît parce
    # qu'un module a parlé. Zéro puce sur un flux garni veut dire que la source
    # des lignes s'est reperdue en route — le défaut que cette phase corrige.
    puces = page.locator("#journal-puces .puce").count()
    rap.dire(puces > 0, "les sous-systèmes sont dérivés des lignes", f"{puces} puce(s)")

    page.locator('#journal-niveaux [data-niveau="ERROR"]').click()
    page.wait_for_timeout(400)
    hash_vu = page.evaluate("location.hash")
    rap.dire("niveau=error" in hash_vu, "le filtre part dans l'URL", hash_vu)

    visibles = page.locator("#log-stream .log-entry:not(.hidden)").count()
    non_err = page.locator(
        "#log-stream .log-entry:not(.hidden):not(.ERROR):not(.CRITICAL)").count()
    rap.dire(non_err == 0, "le filtre ne laisse que les erreurs",
             f"{visibles} visible(s), dont {non_err} hors ERROR")

    # Rechargement à la même URL : la page doit revenir dans le même état.
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(2000)
    actif = page.locator("#journal-niveaux .active").inner_text().strip()
    rap.dire(actif == "Error", "le filtre survit au rechargement", f"actif : {actif!r}")

    ancres = page.locator("#page-rail .rail-ancre").count()
    rap.dire(ancres == 4, "le sommaire d'ancres est rendu", f"{ancres} ancre(s)")

    page.locator('#journal-niveaux [data-niveau="ALL"]').click()
    page.wait_for_timeout(300)
    rap.dire(not erreurs, "aucune erreur JS sur le Journal", " · ".join(erreurs[:2]))


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
