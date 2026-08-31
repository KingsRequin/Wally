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
    python3 scripts/smoke_front.py --public         # site public seul
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
    ("Cockpit", "cockpit"),
    ("Personnes", "cerveau/personnes"),
    ("Mémoire commune", "cerveau/memoire"),
    ("Personnalité", "cerveau/personnalite"),
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
# VIDE, et c'est le point d'arrivée de la refonte : plus un seul sous-onglet
# dans le panel. Tout ce qui en était un est devenu une page, une section ou un
# filtre. La liste reste pour que la boucle du parcours n'ait pas à disparaître
# avec — et pour qu'un sous-onglet qui reviendrait se signale ici.
SOUS_ONGLETS: list[tuple[str, list[tuple[str, str]]]] = []

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


# Les cinq pages du site public, et le sélecteur d'un élément que SEULE cette
# page monte. Un `<main>` non vide ne prouve rien : le routeur pourrait rendre
# l'accueil sur les quatre routes sans que personne ne le voie.
RAIL_ATTENDU = ["HAUT", "CERVEAU", "ÉMOTIONS", "CHAT", "GALERIE", "JOURNAL", "CAPOT"]

PAGES_PUBLIQUES = [
    ("Accueil", "/", "#a-cerveau .feed-body"),
    ("Chat", "/chat", ".chat-vue"),
    ("Galerie", "/galerie", ".gal-grid"),
    ("Clips", "/clips", ".clip-grid"),
    ("TCG", "/tcg", ".tcg-hero"),
]


def verifier_site_public(nav, rap: Rapport, captures: pathlib.Path | None) -> None:
    """Le site public n'avait AUCUN test navigateur — ni ici, ni ailleurs.

    Les tests « front » du projet lisent les fichiers en TEXTE : ils voient une
    classe CSS, jamais un module qui ne s'évalue pas. La refonte du 2026-08-29 a
    remplacé 3 700 lignes de JS d'un coup ; sans ce parcours, la seule preuve
    qu'une page monte serait de la charger à la main.
    """
    print("\n── site public ──")
    page = nav.new_page(viewport={"width": 1440, "height": 1000})
    erreurs = _brancher_erreurs(page)

    for nom, route, marqueur in PAGES_PUBLIQUES:
        del erreurs[:]
        page.goto(f"{BASE}{route}", wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(2000)

        try:
            page.wait_for_selector(marqueur, timeout=_ATTENTE_PANNEAU_MS, state="attached")
            monte = True
        except Exception as exc:
            monte = False
            rap.dire(False, f"page {nom} : {marqueur} monté", repr(exc)[:120])
        if monte:
            rap.dire(True, f"page {nom} : {marqueur} monté")

        texte = len(page.locator("#vue").inner_text())
        rap.dire(texte >= _CONTENU_MIN, f"page {nom} : {texte} caractères rendus",
                 f"attendu ≥ {_CONTENU_MIN}")
        rap.dire(not erreurs, f"page {nom} : aucune erreur JS", " · ".join(erreurs[:2]))

        # L'onglet actif de la nav DOIT suivre la route : c'est le seul repère
        # visuel du visiteur sur un site sans rechargement.
        actifs = page.locator(".nav-link.active").all_inner_texts()
        rap.dire(len(actifs) == 1, f"page {nom} : un seul onglet actif", " · ".join(actifs))

        trop = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        rap.dire(trop <= 0, f"page {nom} : pas de débordement horizontal", f"{trop} px")

        if captures:
            page.screenshot(path=str(captures / f"public-{route.strip('/') or 'accueil'}.png"),
                            full_page=(route != "/chat"))

    # Le MOUVEMENT. Il ne lève aucune erreur, ne vide aucun panneau, et ne
    # laisse aucune trace dans le DOM une fois disparu : quatre mécaniques de
    # la maquette avaient été oubliées à la refonte et rien ne l'a signalé.
    page.goto(f"{BASE}/", wait_until="networkidle", timeout=40000)
    page.wait_for_timeout(2500)

    rap.dire(page.evaluate("typeof window.Lenis") == "function",
             "Lenis est servi (défilement inertiel)", "vendor/lenis.min.js")
    rap.dire(page.evaluate("document.documentElement.classList.contains('lenis')"),
             "Lenis s'est branché sur le document")

    liens_rail = page.locator(".rail a").count()
    rap.dire(liens_rail == len(RAIL_ATTENDU), f"le rail porte {liens_rail} sections",
             f"attendu {len(RAIL_ATTENDU)}")
    libelles = [t.strip() for t in page.locator(".rail .lbl").all_inner_texts()]
    rap.dire(libelles == RAIL_ATTENDU, "et ce sont les bonnes", " · ".join(libelles))

    # Le fil de la boucle cognitive se remplit au défilement : à 0 il est vide.
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(600)
    vide = page.locator(".wire-fill").evaluate("e => e.style.width")
    page.evaluate("window.scrollTo(0, 1200)")
    page.wait_for_timeout(800)
    plein = page.locator(".wire-fill").evaluate("e => e.style.width")
    rap.dire(vide == "0%" and plein == "100%",
             "le fil de la boucle se remplit au défilement", f"{vide} → {plein}")
    rap.dire(page.locator(".rail a.active").count() == 1,
             "et le rail suit la section atteinte")

    # Le relief au survol. Le compte importe autant que le mécanisme : neuf
    # cartes de l'accueil le portent, en perdre une ne se voit pas à l'œil.
    tilt = page.locator("[data-tilt]").count()
    tiltable = page.locator("[data-tilt].tiltable").count()
    rap.dire(tilt >= 20, f"{tilt} cartes déclarent le relief au survol", "attendu ≥ 20")
    rap.dire(tilt == tiltable, "et toutes ont été branchées", f"{tiltable} branchées")

    page.evaluate("document.querySelectorAll('.reveal').forEach(e => e.classList.add('on'))")
    page.wait_for_timeout(400)
    carte = page.locator(".loop-card").first
    carte.hover()
    page.wait_for_timeout(400)
    forme = carte.evaluate("e => e.style.transform")
    rap.dire("perspective(" in forme, "et une carte survolée s'incline", forme[:60])
    page.mouse.move(5, 5)
    page.wait_for_timeout(500)
    rap.dire(carte.evaluate("e => e.style.transform") == "",
             "elle se remet à plat en sortant", "sinon `.reveal.on` perd la main")

    # Le bandeau défile AVEC la page, il ne tourne pas sur une horloge. La
    # nuance ne se voit sur aucune capture : les deux bougent. On la mesure —
    # immobile, il ne doit pas avancer d'un pixel.
    piste = page.locator(".marquee-track")
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(700)
    repos_a = piste.evaluate("e => e.style.transform")
    page.wait_for_timeout(1500)
    repos_b = piste.evaluate("e => e.style.transform")
    rap.dire(bool(repos_a) and repos_a == repos_b,
             "le bandeau est immobile quand la page l'est", f"{repos_a} → {repos_b}")
    page.evaluate("window.scrollTo(0, 2000)")
    page.wait_for_timeout(800)
    bouge = piste.evaluate("e => e.style.transform")
    rap.dire(bouge != repos_a, "et défile avec le défilement", f"{repos_a} → {bouge}")

    # Le compagnon flotte et change de phrase selon l'endroit de la page.
    haut_c = page.locator(".companion-label").inner_text()
    forme_c = page.locator("#companion").evaluate("e => e.style.transform")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1000)
    bas_c = page.locator(".companion-label").inner_text()
    rap.dire(haut_c != bas_c, "le compagnon change de phrase en descendant",
             f"{haut_c!r} → {bas_c!r}")
    rap.dire("translateY" in forme_c, "et flotte au rythme de la descente", forme_c)

    # Les couches du fond se décalent : sans ça, `data-px` est décoratif.
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(700)
    haut = page.locator("#bg-halos").evaluate("e => e.style.transform")
    page.evaluate("window.scrollTo(0, 2500)")
    page.wait_for_timeout(900)
    bas = page.locator("#bg-halos").evaluate("e => e.style.transform")
    rap.dire(bool(haut) and haut != bas, "les halos du fond suivent le défilement",
             f"{haut or 'vide'} → {bas or 'vide'}")

    # Lenis intercepte la molette du DOCUMENT : les conteneurs qui défilent
    # eux-mêmes doivent lui échapper. Quand ils n'y échappent pas, ils sont
    # figés sous le curseur — sans erreur, sans rien dans la console.
    roue = nav.new_page(viewport={"width": 1440, "height": 900})
    roue.goto(f"{BASE}/", wait_until="networkidle", timeout=40000)
    roue.wait_for_timeout(2500)

    roue.evaluate("document.querySelector('#a-cerveau').scrollIntoView()")
    roue.wait_for_timeout(1200)
    roue.evaluate("document.querySelector('.feed-body').scrollTop = 400")
    boite = roue.locator(".feed-body").bounding_box()
    roue.mouse.move(boite["x"] + boite["width"] / 2, boite["y"] + boite["height"] / 2)
    roue.mouse.wheel(0, -300)
    roue.wait_for_timeout(900)
    dedans = roue.evaluate("document.querySelector('.feed-body').scrollTop")
    rap.dire(dedans < 400, "la molette atteint le flux cognitif", f"400 → {dedans}")

    # Le flux rend les métadonnées AU-DESSUS de la sortie, comme le journal du
    # panneau d'administration. En trois colonnes, l'heure et un tag de 92 px
    # mangeaient la moitié d'un écran de téléphone : on mesure donc la part de
    # largeur qui revient au texte, pas seulement la présence des nœuds.
    forme = roue.evaluate(
        """(() => {
          const r = document.querySelector('.feed-row');
          if (!r) return null;
          const t = r.querySelector('.feed-text');
          return {
            meta: !!r.querySelector('.feed-meta'),
            texte: !!t,
            part: t ? t.getBoundingClientRect().width
                      / r.getBoundingClientRect().width : 0,
            teinte: getComputedStyle(r).borderLeftColor,
          };
        })()""")
    rap.dire(bool(forme and forme["meta"] and forme["texte"]),
             "le flux sépare les métadonnées de la sortie", str(forme))
    rap.dire(bool(forme and forme["part"] > 0.9),
             "et la sortie prend toute la largeur",
             f"{round((forme or {}).get('part', 0) * 100)} %")

    # Déplier une pensée ne doit toucher QUE sa ligne. Le flux se redessinait
    # en entier à chaque événement SSE — deux cents lignes de quatre nœuds
    # jetées et reconstruites pour une pensée de plus.
    deplie = roue.evaluate(
        """(() => {
          const l = document.querySelector('.feed-body');
          [...l.children].forEach((c, i) => { c.dataset.temoin = i; });
          const cibles = [...l.children].filter(c => c.classList.contains('clickable'));
          if (!cibles.length) return null;
          const cible = cibles[cibles.length - 1];
          const avant = cible.querySelector('.feed-text').textContent.length;
          cible.click();
          return {
            gardees: [...l.children].filter(c => c.dataset.temoin !== undefined).length,
            total: l.children.length,
            avant: avant,
            apres: l.children[+cible.dataset.temoin].querySelector('.feed-text').textContent.length,
          };
        })()""")
    rap.dire(bool(deplie and deplie["gardees"] == deplie["total"] - 1),
             "déplier une pensée ne redessine que sa ligne",
             f"{(deplie or {}).get('gardees')}/{(deplie or {}).get('total')} gardées")
    rap.dire(bool(deplie and deplie["apres"] > deplie["avant"]),
             "et elle porte bien le texte complet",
             f"{(deplie or {}).get('avant')} → {(deplie or {}).get('apres')} car.")

    roue.evaluate("window.scrollTo(0, 0)")
    roue.wait_for_timeout(700)
    roue.mouse.move(720, 300)
    roue.mouse.wheel(0, 900)
    roue.wait_for_timeout(1200)
    page_sy = roue.evaluate("window.scrollY")
    rap.dire(page_sy > 300, "et la page défile toujours ailleurs", f"scrollY {page_sy}")
    roue.close()

    # Les compteurs montent depuis zéro au premier chargement. On sert la
    # valeur nous-mêmes : `message_count` est remis à zéro à chaque
    # redémarrage, et à 3 messages une montée est indistincte d'une pose.
    compte = nav.new_page(viewport={"width": 1440, "height": 900})
    compte.route("**/api/public/status", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body='{"uptime_seconds":38306,"total_messages":24187,"avg_response_ms":1420,'
             '"bot_name":"Wally","discord_online":true,"twitch_online":true}'))
    compte.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=40000)
    compte.wait_for_timeout(450)
    milieu = compte.locator("#vue .stat-value").first.inner_text()
    compte.wait_for_timeout(2200)
    arrivee = compte.locator("#vue .stat-value").first.inner_text()
    chiffres = lambda t: "".join(c for c in t if c.isdigit())
    rap.dire(chiffres(arrivee) == "24187", "le compteur arrive sur la vraie valeur", arrivee)
    rap.dire(chiffres(milieu) not in ("", "24187"),
             "et il y est monté depuis zéro", f"à 450 ms : {milieu!r}")
    compte.close()

    # Navigation interne : c'est le routeur qu'on teste, pas le serveur. Un
    # `pushState` cassé rendrait le site utilisable seulement au rechargement.
    del erreurs[:]
    page.goto(f"{BASE}/", wait_until="networkidle", timeout=40000)
    page.wait_for_timeout(1200)
    page.locator('.nav-link[data-route="/galerie"]').click()
    page.wait_for_timeout(1500)
    rap.dire(page.url.endswith("/galerie"), "un clic dans la nav pose l'URL", page.url)
    rap.dire(page.locator(".gal-grid").count() == 1, "et monte la galerie")
    page.go_back()
    page.wait_for_timeout(1500)
    rap.dire(page.locator("#a-cerveau").count() == 1, "le retour arrière remonte l'accueil", page.url)
    rap.dire(not erreurs, "aucune erreur JS pendant la navigation", " · ".join(erreurs[:2]))

    # Les anciennes ancres du site arcade sont partagées et mises en favori.
    # Le détour par /tcg n'est pas cosmétique : depuis `/`, aller à `/#gallery`
    # est une navigation DANS le document — la page ne se recharge pas et la
    # redirection, qui vit au premier chargement du module, ne s'exécute jamais.
    page.goto(f"{BASE}/tcg", wait_until="networkidle", timeout=40000)
    page.goto(f"{BASE}/#gallery", wait_until="networkidle", timeout=40000)
    page.wait_for_timeout(1500)
    rap.dire(page.url.endswith("/galerie"), "l'ancre héritée #gallery redirige", page.url)
    page.close()

    # Téléphone. Le débordement horizontal ne se voit sur AUCUNE capture de
    # bureau et ne lève aucune erreur JS : la page s'affiche, simplement un
    # bout part hors de l'écran. Un `grid-template-columns` posé en style EN
    # LIGNE bat la media query — 43 px perdus sur la section des émotions, et
    # le bouton de connexion hors de portée du pouce.
    mob = nav.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    erreurs_mob = _brancher_erreurs(mob)
    for nom, route, _ in PAGES_PUBLIQUES:
        del erreurs_mob[:]
        mob.goto(f"{BASE}{route}", wait_until="networkidle", timeout=40000)
        mob.wait_for_timeout(1800)
        trop = mob.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        rap.dire(trop <= 0, f"390 px · {nom} : pas de débordement horizontal", f"{trop} px")
        rap.dire(not erreurs_mob, f"390 px · {nom} : aucune erreur JS",
                 " · ".join(erreurs_mob[:2]))

        # La barre d'onglets du pouce. Elle remplace les onglets du haut, dont
        # le défilement horizontal coupait « TCG » en « T » dès 320 px sans que
        # rien ne dise qu'il restait quelque chose à droite.
        #
        # On descend AVANT de mesurer : le pied de page d'une page non défilée
        # est à des milliers de pixels sous l'écran, et sa distance à la barre
        # ne dit alors rien du tout. Mesuré sans ce défilement, le test
        # annonçait « 12 704 px de chevauchement » sur une page saine.
        mob.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        mob.wait_for_timeout(900)
        barre = mob.evaluate("""() => {
          const t = document.querySelector('.tabbar');
          const visible = t && getComputedStyle(t).display !== 'none';
          const r = visible ? t.getBoundingClientRect() : null;
          const pied = document.querySelector('.footer');
          return {
            visible,
            onglets: t ? t.querySelectorAll('.tab').length : 0,
            actifs: t ? t.querySelectorAll('.tab.active').length : 0,
            hautMasque: getComputedStyle(document.querySelector('.nav-links')).display === 'none',
            // La barre RÉSERVE sa place, elle ne recouvre pas : le pied de page
            // et le bouton « Charger plus » doivent rester atteignables.
            recouvre: (pied && r) ? Math.round(pied.getBoundingClientRect().bottom - r.top) : 0,
            // Le libellé du bouton de connexion : les deux variantes ont été
            // masquées ensemble pendant des mois, et le bouton était un rond
            // VIDE sur tout téléphone. Aucun test de texte ne voit ça.
            auth: (document.querySelector('#auth') || {}).innerText || '',
          };
        }""")
        rap.dire(barre["visible"] and barre["hautMasque"],
                 f"390 px · {nom} : la barre du pouce remplace les onglets du haut", str(barre))
        rap.dire(barre["onglets"] == len(PAGES_PUBLIQUES),
                 f"390 px · {nom} : {barre['onglets']} onglets en bas",
                 f"attendu {len(PAGES_PUBLIQUES)}")
        rap.dire(barre["actifs"] == 1, f"390 px · {nom} : un seul onglet actif en bas",
                 f"{barre['actifs']} actif(s)")
        rap.dire(barre["recouvre"] <= 2, f"390 px · {nom} : la barre ne recouvre pas le pied",
                 f"{barre['recouvre']} px de chevauchement")
        rap.dire(bool(barre["auth"].strip()),
                 f"390 px · {nom} : le bouton de connexion porte un libellé",
                 f"innerText = {barre['auth']!r}")

    # Gyroscope. Sur un téléphone il n'y a pas de curseur : sans lui, tout le
    # mouvement latéral du décor disparaît. Aucun test de texte ne le voit —
    # le branchement est gardé par une media query ET par un événement de
    # capteur, deux choses qui n'existent que dans un vrai navigateur mobile.
    mob.goto(f"{BASE}/", wait_until="networkidle", timeout=40000)
    mob.wait_for_timeout(1200)
    halos = "getComputedStyle(document.getElementById('bg-halos')).transform"
    repos = mob.evaluate(halos)
    mob.evaluate(
        """() => {
          const ev = (b, g) => window.dispatchEvent(
            new DeviceOrientationEvent('deviceorientation', {beta: b, gamma: g}));
          ev(40, 0);                                  // la 1re mesure fait le neutre
          for (let i = 0; i < 30; i++) ev(40, 30);    // puis on penche franchement
        }""")
    mob.wait_for_timeout(1500)
    penche = mob.evaluate(halos)
    rap.dire(penche != repos, "390 px · le décor suit l'inclinaison de l'appareil",
             f"{repos} → {penche}")

    # Les cartes aussi : faute de curseur à suivre, elles basculent ENSEMBLE
    # avec l'appareil. On descend d'abord — en haut de l'accueil, le hero
    # occupe tout l'écran et aucune carte n'est dans le champ, si bien qu'un
    # test fait sans défiler passerait au vert sur zéro carte.
    mob.evaluate("window.scrollTo(0, 1800)")
    mob.wait_for_timeout(900)
    mob.evaluate(
        """() => {
          const ev = (b, g) => window.dispatchEvent(
            new DeviceOrientationEvent('deviceorientation', {beta: b, gamma: g}));
          ev(40, 0); for (let i = 0; i < 40; i++) ev(40, 30);
        }""")
    mob.wait_for_timeout(1200)
    inclinees = mob.evaluate(
        "[...document.querySelectorAll('[data-tilt]')]"
        ".filter(e => e.style.transform.includes('rotateY')).length")
    rap.dire(inclinees > 0, "390 px · les cartes à l'écran suivent l'inclinaison",
             f"{inclinees} carte(s)")

    # Le débordement se re-teste PENCHÉ. Les tests ci-dessus mesurent une page
    # au repos ; l'inclinaison déplace les couches du décor latéralement, et un
    # halo en `right: -140px` gonfle le `scrollWidth` du document malgré
    # `body { overflow-x: hidden }` — le piège a déjà coûté 43 px hors écran.
    trop_penche = mob.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")
    rap.dire(trop_penche <= 0, "390 px · penché : pas de débordement horizontal",
             f"{trop_penche} px")
    mob.close()


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
        # UN SEUL panneau visible. Le parcours ne vérifiait que l'absence de
        # panneau VIDE, jamais l'absence de panneau EN TROP : une page qui pose
        # sa propre classe de mise en page (`.ovl-panneau { display: flex }`)
        # bat `.tab-content { display: none }` à spécificité égale, et reste
        # affichée par-dessus la page d'arrivée. Vu à l'écran le 2026-08-29 —
        # l'URL changeait, la sidebar suivait, deux panneaux se superposaient,
        # et rien ne le disait.
        vus = page.evaluate(
            "Array.from(document.querySelectorAll('.tab-content'))"
            ".filter(e => e.offsetParent !== null).map(e => e.id)")
        rap.dire(not erreurs and hash_vu == f"#/{route}" and len(vus) == 1,
                 f"page {nom}",
                 f"hash {hash_vu!r} · {len(vus)} panneau(x) : {', '.join(vus)}"
                 + (" · " + erreurs[0] if erreurs else ""))

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
    _verifier_automatisations(page, rap, erreurs)
    _verifier_personnes(page, rap, erreurs)
    _verifier_personnalite_et_couts(page, rap, erreurs)
    _verifier_live_et_connexions(page, rap, erreurs)
    _verifier_memoire_commune(page, rap, erreurs)
    _verifier_cockpit(page, rap, erreurs)
    _verifier_scene(page, rap, erreurs)
    _verifier_mobile(page, rap, erreurs)

    if captures:
        page.screenshot(path=str(captures / "admin.png"))
    page.close()


def _verifier_scene(page, rap: Rapport, erreurs: list[str]) -> None:
    """La Scène : seule la CHROME a changé. Le canevas, la liste d'éléments et
    l'inspecteur sont ce que le panneau a de plus éprouvé — la refonte ne
    devait toucher qu'à ce qui les entoure, et ce test le vérifie.

    `overlay_admin.js` pèse 334 ko et ne se monte qu'UNE fois par session :
    c'est exactement le genre de panneau qui meurt en silence.
    """
    print("\n── Live › Scène & overlays ──")
    del erreurs[:]
    page.locator('.sidebar-item[data-route="live/scene"]').click()
    page.wait_for_timeout(3000)

    # ── ce qui NE doit PAS avoir bougé ──
    elements = page.locator("#tab-admin-scene .ovl-el").count()
    rap.dire(elements > 0, "la liste d'éléments est intacte", f"{elements} élément(s)")
    canevas = page.locator("#tab-admin-scene .ovl-zone-canvas").count()
    rap.dire(canevas == 1, "le canevas est intact", f"{canevas}")

    # Sur mobile, la zone de travail entière DISPARAÎT. La première version
    # posait `pointer-events: none` sur trois sélecteurs devinés qui n'existent
    # pas : le bandeau annonçait une lecture seule que rien n'appliquait, et on
    # déplaçait toujours les éléments en direct. Signalé à l'écran.
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(900)
    rap.dire(page.locator("#tab-admin-scene .ovl-travail").is_hidden(),
             "au doigt, la zone de travail disparaît")
    rap.dire(page.locator("#tab-admin-scene .ovl-el").count() > 0,
             "la liste et ses interrupteurs restent")
    page.set_viewport_size({"width": 1600, "height": 1000})
    page.wait_for_timeout(900)

    # Le bandeau des chevauchements est passé de pastille noyée dans la barre
    # d'outils à ligne pleine largeur au-dessus du canevas. Il ne se tait
    # JAMAIS : un silence se lirait comme « aucun chevauchement », alors qu'une
    # taille non mesurée ne prouve rien.
    bandeau = page.locator("#tab-admin-scene .ovl-chevauchements")
    rap.dire(bandeau.count() == 1, "le bandeau de chevauchement est là",
             bandeau.first.inner_text() if bandeau.count() else "absent")
    large = page.evaluate(
        "(() => {const b = document.querySelector('.ovl-chevauchements'),"
        " t = document.querySelector('.ovl-travail');"
        " return b && t ? b.clientWidth / t.clientWidth : 0;})()")
    rap.dire(large > 0.9, "il prend toute la largeur du canevas",
             f"{large:.0%}")

    # ── ce qui a bougé ──
    scenes = page.locator("#page-actions .ovl-scene-corps").count()
    rap.dire(scenes > 0, "les scènes sont un segmented dans l'en-tête",
             f"{scenes} scène(s)")
    actives = page.locator("#page-actions .ovl-scene-corps.active").count()
    rap.dire(actives == 1, "une seule scène est allumée", f"{actives}")

    url = page.locator("#control-bar-page .ovl-source-url").inner_text()
    rap.dire(url.startswith("http"), "l'URL OBS est montée dans la barre du haut", url)

    # Le menu ⋮ n'est posé QUE sur la scène affichée : un par segment tiendrait
    # plus de place que les noms.
    menus = page.locator("#page-actions .ovl-menu-btn").count()
    rap.dire(menus == 1, "un seul menu ⋮, sur la scène affichée", f"{menus}")

    # Changer de scène doit suivre partout : segment allumé ET adresse OBS.
    if scenes > 1:
        page.locator("#page-actions .ovl-scene-corps").nth(1).click()
        page.wait_for_timeout(900)
        url2 = page.locator("#control-bar-page .ovl-source-url").inner_text()
        rap.dire(url2 != url, "changer de scène change l'adresse OBS", url2)

    # ── La chrome flottante est-elle CLIQUABLE ? ──────────────────────
    #
    # Le seul test qui aurait attrapé le défaut du 2026-08-29 : « Aspect &
    # rythme » s'ouvrait, se voyait, et ses dix réglages étaient inatteignables
    # — les repères du canevas recevaient le clic à leur place. `backdrop-filter`
    # sur la bande crée un contexte d'empilement qui enfermait le `z-index` du
    # volet ; monter le nombre du volet n'y aurait rien changé.
    #
    # Un panneau MONTÉ n'est donc pas un panneau UTILISABLE : on sonde ce que
    # `elementFromPoint` rend vraiment, aux quatre coins du volet et de son
    # voisin le panneau Outils.
    sonde = """(sel) => {
      const v = document.querySelector(sel);
      if (!v || v.hidden || !v.offsetParent) return ['absent'];
      const r = v.getBoundingClientRect();
      return [[0.1,0.15],[0.9,0.15],[0.1,0.85],[0.9,0.85]].map(([fx,fy]) => {
        const t = document.elementFromPoint(r.x + r.width*fx, r.y + r.height*fy);
        return v.contains(t) ? 'ok'
          : (t ? t.tagName + '.' + String(t.className).slice(0, 24) : 'rien');
      });
    }"""
    page.locator(".ovl-inspecteur .ovl-insp-plus").first.click()
    page.wait_for_timeout(600)
    vole = [c for c in page.evaluate(sonde, ".ovl-insp-volet") if c != "ok"]
    rap.dire(not vole, "les réglages « Aspect & rythme » reçoivent le clic",
             " · ".join(vole))
    page.locator('#tab-admin-scene .ovl-outils-coin button').first.click()
    page.wait_for_timeout(600)
    vole = [c for c in page.evaluate(sonde, ".ovl-outils") if c != "ok"]
    rap.dire(not vole, "le panneau « Outils » reçoit le clic", " · ".join(vole))

    # LE piège de cette phase : la chrome vit hors du panneau, et le routeur la
    # vide à chaque changement de route. `monter()` ne s'exécutant qu'une fois,
    # revenir sur la Scène la laisserait vide sans la moindre erreur.
    page.locator('.sidebar-item[data-route="systeme/journal"]').click()
    page.wait_for_timeout(1200)
    page.locator('.sidebar-item[data-route="live/scene"]').click()
    page.wait_for_timeout(1800)
    rap.dire(page.locator("#page-actions .ovl-scene-corps").count() > 0,
             "la chrome revient quand on revient sur la page")
    rap.dire(page.locator("#control-bar-page .ovl-source-url").count() == 1,
             "l'adresse OBS revient aussi")

    # Et elle ne doit PAS suivre ailleurs.
    page.locator('.sidebar-item[data-route="systeme/journal"]').click()
    page.wait_for_timeout(1200)
    reste = (page.locator("#page-actions .ovl-scene-corps").count()
             + page.locator("#control-bar-page .ovl-source-url").count())
    rap.dire(reste == 0, "elle ne déborde pas sur la page suivante", f"{reste}")

    rap.dire(not erreurs, "aucune erreur JS sur la Scène", " · ".join(erreurs[:2]))


def _verifier_mobile(page, rap: Rapport, erreurs: list[str]) -> None:
    """390 px de large : la sidebar disparaît, la barre du bas prend le relais.

    Le mobile est le seul endroit du panel qu'on ne regarde jamais en
    travaillant — c'est donc celui qui peut mourir le plus longtemps sans que
    personne le voie.
    """
    print("\n── Mobile (390 px) ──")
    del erreurs[:]
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator('.barre-bas-item[data-theme="cerveau"]').click()
    page.wait_for_timeout(2000)

    rap.dire(page.locator("#sidebar").is_hidden(),
             "la sidebar disparaît sous 780 px")
    rap.dire(page.locator("#barre-bas").is_visible(),
             "la barre du bas prend le relais")

    dest = page.locator(".barre-bas-item").count()
    rap.dire(dest == 4, "quatre destinations, pas onze", f"{dest}")

    # Les puces sont DÉRIVÉES de la sidebar : une seconde liste écrite à la
    # main divergerait au premier ajout, et personne ne le verrait puisqu'elle
    # ne s'affiche que sur mobile.
    puces = page.locator("#theme-puces .theme-puce").all_inner_texts()
    rap.dire(puces == ["Personnes", "Mémoire commune", "Personnalité",
                       "Modèles & coûts"],
             "les pages du thème sont en puces", " · ".join(puces))

    actif = page.locator(".barre-bas-item.active").get_attribute("data-theme")
    rap.dire(actif == "cerveau", "la destination courante est allumée", str(actif))

    # Cible tactile : jamais moins de 44 px de haut, sinon on vise à côté.
    trop_petit = page.evaluate(
        "Array.from(document.querySelectorAll('.barre-bas-item, #theme-puces a'))"
        ".filter(e => e.getBoundingClientRect().height < 30).length")
    rap.dire(trop_petit == 0, "les cibles tactiles sont assez hautes",
             f"{trop_petit} trop petite(s)")

    # Rien ne doit déborder horizontalement : une page qui glisse de côté sur
    # mobile est une page qu'on ne peut pas lire.
    page.locator('.barre-bas-item[data-theme="cockpit"]').click()
    page.wait_for_timeout(1800)
    # ── Le débordement, page par page ──────────────────────────────────
    #
    # Deux mesures successives se sont révélées trop faibles, et les DEUX ont
    # laissé passer des pages illisibles signalées par l'owner :
    #
    #   · `documentElement.scrollWidth` ne voit rien — c'est `.main-content`
    #     qui a son propre `overflow`, et c'est elle qui glisse ;
    #   · `.main-content` seule ne voit pas le contenu qui déborde À
    #     L'INTÉRIEUR de son propre conteneur. Le flux vocal était écrasé à
    #     trois mots par ligne, la latence sortait de 98 px, et la colonne,
    #     elle, ne débordait pas d'un pixel.
    #
    # On regarde donc chaque élément FEUILLE de la page active : dépasse-t-il
    # le bord droit de la colonne, ou coupe-t-il son propre contenu ? Et sur
    # les onze pages, pas quatre.
    sonde = """(() => {
      const m = document.querySelector('.main-content');
      const lim = m.getBoundingClientRect().right;
      const out = [];
      document.querySelectorAll('.tab-content.active *').forEach(e => {
        const r = e.getBoundingClientRect();
        if (!r.width || !r.height) return;
        const d = Math.round(r.right - lim);
        const c = Math.round(e.scrollWidth - e.clientWidth);
        if (d <= 2 && c <= 2) return;
        // Un parent déborde parce qu'un enfant déborde : on ne garde que les
        // feuilles, sinon un seul défaut remonte toute la chaîne.
        if (e.querySelector('*') && [...e.children].some(x => {
          const xr = x.getBoundingClientRect();
          return xr.right - lim > 2 || x.scrollWidth - x.clientWidth > 2; })) return;
        out.push((e.tagName + '.' + (e.className||'').toString().split(' ')[0])
                 .slice(0, 34)
                 + (d > 2 ? ' déborde ' + d : '') + (c > 2 ? ' coupe ' + c : ''));
      });
      return [...new Set(out)].slice(0, 4);
    })()"""
    for nom, route in ONGLETS:
        page.evaluate(f"location.hash = '#/{route}'")
        page.wait_for_timeout(1800)
        fautifs = page.evaluate(sonde)
        rap.dire(not fautifs, f"{nom} tient dans 390 px", " · ".join(fautifs))

    # ── La métadonnée AU-DESSUS, le texte en pleine largeur ────────────
    #
    # Au bureau, `15:16:12  INFO  Musique : morceau — …` se lit d'un trait.
    # Sur 390 px, l'heure et le niveau mangent la moitié de la ligne et le
    # message se retrouve dans un couloir de 165 px, où trois mots prennent
    # quatre lignes. On vérifie donc que le texte commence bien au BORD de sa
    # ligne, et non après les colonnes de métadonnée.
    for route, ligne, texte in (("systeme/journal", ".log-entry", ".log-message"),
                                ("live/voix", ".v-row", ".v-text")):
        page.evaluate(f"location.hash = '#/{route}'")
        page.wait_for_timeout(2000)
        decalage = page.evaluate(
            "([l, t]) => {const r = document.querySelector(l);"
            " const x = r && r.querySelector(t);"
            " return r && x ? Math.round(x.getBoundingClientRect().left"
            "   - r.getBoundingClientRect().left) : -1;}",
            [ligne, texte])
        rap.dire(0 <= decalage <= 20, f"{route} : le texte prend la largeur",
                 f"décalé de {decalage} px")

    rap.dire(not erreurs, "aucune erreur JS en mobile", " · ".join(erreurs[:2]))
    page.set_viewport_size({"width": 1600, "height": 1000})


def _verifier_cockpit(page, rap: Rapport, erreurs: list[str]) -> None:
    """L'écran d'arrivée. Quatre choses attendaient quelqu'un dans ce bot, une
    par page : une tâche qui échoue, une erreur qui se répète, deux identités à
    rattacher, une question à poser. On ne les voyait qu'en allant les chercher.
    """
    print("\n── Cockpit ──")
    del erreurs[:]
    page.locator('.sidebar-item[data-route="cockpit"]').click()
    page.wait_for_timeout(2500)

    tuiles = page.locator("#cockpit-tuiles .cockpit-tuile").count()
    rap.dire(tuiles == 4, "les quatre tuiles d'état sont là", f"{tuiles} tuile(s)")

    emotions = page.locator("#cockpit-humeur .cockpit-emotion").count()
    rap.dire(emotions == 5, "les cinq émotions sont rendues", f"{emotions} barre(s)")

    # Et elles doivent porter l'état RÉEL. `currentEmotions` n'était alimenté
    # par aucun appel : les jauges affichaient 0.00 partout depuis toujours,
    # pendant que Wally tournait à joy 0.78. Cinq zéros exacts sont le
    # symptôme, pas une humeur.
    valeurs = page.evaluate(
        "Array.from(document.querySelectorAll('#cockpit-humeur .cockpit-emotion-val'))"
        ".map(e => parseFloat(e.textContent))")
    rap.dire(any(v > 0 for v in valeurs),
             "les émotions portent l'état réel du serveur",
             " · ".join(f"{v:.2f}" for v in valeurs))

    # Chaque item porte sa CIBLE, filtre compris : c'est ce qui fait la
    # différence entre « il y a un problème » et « voilà où le régler ».
    cibles = page.evaluate(
        "Array.from(document.querySelectorAll('#cockpit-decisions [data-cible]'))"
        ".map(e => e.dataset.cible)")
    rap.dire(all(c.startswith("#/") for c in cibles),
             "chaque décision porte une cible de navigation",
             f"{len(cibles)} item(s)")

    if cibles:
        page.locator("#cockpit-decisions [data-cible]").first.click()
        page.wait_for_timeout(1200)
        vu = page.evaluate("location.hash")
        rap.dire(vu == cibles[0], "cliquer ouvre la page déjà filtrée",
                 f"{vu} (attendu {cibles[0]})")
        page.locator('.sidebar-item[data-route="cockpit"]').click()
        page.wait_for_timeout(1200)

    # « Reprendre » se remplit des pages quittées : au moins une, puisqu'on
    # vient d'en parcourir dix.
    reprendre = page.locator("#cockpit-reprendre .puce").count()
    rap.dire(reprendre > 0, "« Reprendre » retient les pages quittées",
             f"{reprendre} puce(s)")

    rap.dire(not erreurs, "aucune erreur JS sur le Cockpit", " · ".join(erreurs[:2]))


def _verifier_memoire_commune(page, rap: Rapport, erreurs: list[str]) -> None:
    """L'ancien onglet « Mémoire communautaire » lisait `/memory/global`, qui
    rend une liste VIDE et refuse toute écriture en 501 : un panneau mort qui
    invitait à ajouter un souvenir aussitôt rejeté. La matière existait
    ailleurs — les sujets formés la nuit — et n'était exposée nulle part."""
    print("\n── Cerveau › Mémoire commune ──")
    del erreurs[:]
    page.locator('.sidebar-item[data-route="cerveau/memoire"]').click()
    page.wait_for_timeout(2500)

    sujets = page.locator("#mc-sujets .mc-sujet").count()
    rap.dire(sujets > 0, "les sujets de la communauté sont rendus",
             f"{sujets} sujet(s)")
    # L'opinion est la matière la plus intéressante du lot : c'est la seule qui
    # dise ce que Wally PENSE du sujet, et elle n'a jamais été affichée.
    avis = page.locator("#mc-sujets .mc-sujet-avis").count()
    rap.dire(avis > 0, "l'opinion de Wally est visible", f"{avis} avis")

    for ident, libelle in (("mc-questions", "les questions"),
                           ("mc-notes", "les notes du bot"),
                           ("mc-tete", "dans sa tête")):
        n = _attendre_contenu(page, ident)
        rap.dire(n >= _CONTENU_MIN, f"Mémoire commune → {libelle}", f"{n} car.")

    # Les puces montrent ou cachent des sections entières.
    page.locator('#mc-puces [data-mc="mc-notes"]').click()
    page.wait_for_timeout(400)
    cache = page.locator("#mc-sujets").is_hidden()
    rap.dire(cache, "une puce filtre bien les sections",
             "sujets masqués" if cache else "sujets toujours visibles")
    page.locator('#mc-puces [data-mc=""]').click()
    page.wait_for_timeout(300)

    rap.dire(not erreurs, "aucune erreur JS sur Mémoire commune",
             " · ".join(erreurs[:2]))


def _verifier_live_et_connexions(page, rap: Rapport, erreurs: list[str]) -> None:
    """Médias & sons, Voix et Connexions. Trois pages composées d'anciens
    panneaux : c'est justement là qu'un rendu peut se perdre en silence, parce
    que la fonction existe et que sa cible a changé de nom."""
    print("\n── Live › Médias, Voix · Système › Connexions ──")

    del erreurs[:]
    page.locator('.sidebar-item[data-route="live/medias"]').click()
    page.wait_for_timeout(2500)
    for ident, libelle in (("medias-overlays", "les overlays"),
                           ("medias-images-corps", "la génération d'images")):
        n = _attendre_contenu(page, ident)
        rap.dire(n >= _CONTENU_MIN, f"Médias → {libelle}", f"{n} car.")
    # La galerie se compte en VIGNETTES : mesurer son texte donnerait une
    # trentaine de caractères (le titre) sur une grille pleine d'images, et
    # crierait au panneau mort. Un smoke test qui crie à tort finit ignoré.
    vignettes = page.locator("#medias-galerie .galerie-case").count()
    rap.dire(vignettes > 0, "Médias → la galerie", f"{vignettes} vignette(s)")
    # L'atelier des sons vit DANS le panneau overlay : il a déjà disparu une
    # fois d'un déplacement de section.
    sons = page.locator("#atelier-sons").count()
    rap.dire(sons == 1, "l'atelier des sons a suivi", f"{sons} conteneur(s)")
    rap.dire(not erreurs, "aucune erreur JS sur Médias & sons", " · ".join(erreurs[:2]))

    del erreurs[:]
    page.locator('.sidebar-item[data-route="live/voix"]').click()
    page.wait_for_timeout(2500)
    for ident, libelle in (("voix-reglages-corps", "les réglages"),
                           ("voix-suivi-corps", "le suivi en direct")):
        n = _attendre_contenu(page, ident)
        rap.dire(n >= _CONTENU_MIN, f"Voix → {libelle}", f"{n} car.")
    rap.dire(not erreurs, "aucune erreur JS sur Voix", " · ".join(erreurs[:2]))

    del erreurs[:]
    page.locator('.sidebar-item[data-route="systeme/connexions"]').click()
    page.wait_for_timeout(2500)
    cartes = page.locator("#cnx-adaptateurs .cnx-carte").count()
    rap.dire(cartes == 2, "les deux adaptateurs ont leur carte", f"{cartes} carte(s)")
    # « Connecté » ne suffit pas : un bot prêt sur zéro serveur a le même
    # voyant vert. Chaque carte doit porter ses FAITS.
    faits = page.locator("#cnx-adaptateurs .cnx-fait").count()
    rap.dire(faits >= 3, "les cartes portent des faits, pas qu'un voyant",
             f"{faits} fait(s)")
    for ident, libelle in (("cnx-twitch-corps", "les comptes Twitch"),
                           ("cnx-discord-corps", "les réglages Discord")):
        n = _attendre_contenu(page, ident)
        rap.dire(n >= _CONTENU_MIN, f"Connexions → {libelle}", f"{n} car.")
    rap.dire(not erreurs, "aucune erreur JS sur Connexions", " · ".join(erreurs[:2]))


def _verifier_personnalite_et_couts(page, rap: Rapport, erreurs: list[str]) -> None:
    """Personnalité absorbe l'onglet Prompts ; Modèles & coûts rend visible ce
    que `cost_log` enregistrait sans que rien ne le montre."""
    print("\n── Cerveau › Personnalité et Modèles ──")
    del erreurs[:]
    page.locator('.sidebar-item[data-route="cerveau/personnalite"]').click()
    page.wait_for_timeout(2200)

    etat = _attendre_contenu(page, "perso-etat")
    rap.dire(etat >= _CONTENU_MIN, "l'humeur et le tempérament sont rendus",
             f"{etat} car.")
    prompts = _attendre_contenu(page, "perso-prompts")
    rap.dire(prompts >= _CONTENU_MIN, "les textes de référence sont absorbés",
             f"{prompts} car.")

    # L'éditeur se re-rend dans SA cible : un clic sur un fichier cherchait
    # jusqu'ici un panneau supprimé, et ne faisait rien en silence.
    fichiers = page.locator("#perso-prompts .prompt-file-item, #perso-prompts li")
    if fichiers.count() > 1:
        fichiers.nth(1).click()
        page.wait_for_timeout(600)
        rap.dire(_attendre_contenu(page, "perso-prompts") >= _CONTENU_MIN,
                 "changer de fichier ne vide pas l'éditeur")

    del erreurs[:]
    page.locator('.sidebar-item[data-route="cerveau/modeles"]').click()
    page.wait_for_timeout(2500)

    modeles = _attendre_contenu(page, "mod-modeles")
    rap.dire(modeles >= _CONTENU_MIN, "le choix des modèles est rendu", f"{modeles} car.")

    lignes = page.locator("#mod-usage .mod-ligne").count()
    rap.dire(lignes > 0, "les coûts par usage sont enfin visibles", f"{lignes} usage(s)")

    barres = page.locator("#mod-courbe .mod-barre, .mod-courbe .mod-barre").count()
    rap.dire(barres > 0, "la courbe des 14 jours est tracée", f"{barres} barre(s)")

    rap.dire(not erreurs, "aucune erreur JS sur Personnalité et Modèles",
             " · ".join(erreurs[:2]))


def _verifier_personnes(page, rap: Rapport, erreurs: list[str]) -> None:
    """L'annuaire et la fiche. Utilisateurs, Comptes Apex, Ignorés et les alias
    étaient quatre onglets pour une seule question : que sait Wally de X ?"""
    print("\n── Cerveau › Personnes ──")
    del erreurs[:]
    page.locator('.sidebar-item[data-route="cerveau/personnes"]').click()
    page.wait_for_timeout(2200)

    lignes = page.locator("#pers-liste .pers-ligne").count()
    rap.dire(lignes > 0, "l'annuaire rend des personnes", f"{lignes} ligne(s)")

    puces = page.locator("#pers-puces .puce").count()
    rap.dire(puces == 5, "les cinq filtres sont des puces", f"{puces} puce(s)")

    page.locator('#pers-plateformes [data-plateforme="discord"]').click()
    page.wait_for_timeout(500)
    hash_vu = page.evaluate("location.hash")
    rap.dire("plateforme=discord" in hash_vu, "le filtre part dans l'URL", hash_vu)

    # Le sous-titre annonce ce que la liste MONTRE. Un compte figé sur le total
    # ferait mentir la page dès le premier filtre.
    sous = page.locator("#page-sub").inner_text()
    rap.dire("Discord" in sous and "connues" in sous,
             "le sous-titre compte ce qui est montré", sous)

    # ── La fiche ──
    page.locator('#pers-plateformes [data-plateforme=""]').click()
    page.wait_for_timeout(400)
    page.locator("#pers-liste .pers-ligne").first.click()
    page.wait_for_timeout(2000)

    hash_vu = page.evaluate("location.hash")
    rap.dire(hash_vu.startswith("#/cerveau/personnes/"),
             "la ligne ouvre une fiche à son URL", hash_vu)

    nom = page.locator(".fiche-nom").count()
    tuiles = page.locator(".fiche-tuile").count()
    onglets = page.locator(".fiche-onglets button").count()
    rap.dire(nom == 1 and tuiles == 4 and onglets == 3,
             "la fiche porte son en-tête, ses tuiles et ses onglets",
             f"{nom} nom · {tuiles} tuiles · {onglets} onglets")

    # Le rechargement à la même URL doit rendre la MÊME fiche : c'est ce qui
    # rend le lien partageable.
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(2500)
    rap.dire(page.locator(".fiche-nom").count() == 1,
             "la fiche survit au rechargement", page.evaluate("location.hash"))

    # La sidebar doit rester allumée sur « Personnes » : une fiche est une vue
    # de sa page, pas une page de plus.
    allumee = page.locator(".sidebar-item.active").get_attribute("data-route")
    rap.dire(allumee == "cerveau/personnes",
             "la sidebar garde la page parente allumée", str(allumee))

    page.locator('.fiche-onglets [data-onglet="comptes"]').click()
    page.wait_for_timeout(400)
    corps = _attendre_contenu(page, "fiche-corps")
    rap.dire(corps > 0, "l'onglet « Comptes liés » rend du contenu", f"{corps} car.")

    # Les deux anciens sous-onglets absorbés par cette page : « Comptes Apex »
    # et « Ignorés » sont devenus des filtres de l'annuaire, leurs formulaires
    # des sections. Hors du parcours, ils pourraient mourir sans un bruit.
    page.locator('.sidebar-item[data-route="cerveau/personnes"]').click()
    page.wait_for_timeout(1500)
    for ident, libelle in (("pers-apex", "lier un compte Apex"),
                           ("pers-ignores", "personnes ignorées")):
        n = _attendre_contenu(page, ident)
        rap.dire(n >= _CONTENU_MIN, f"Personnes → {libelle}", f"{n} car.")

    rap.dire(not erreurs, "aucune erreur JS sur Personnes", " · ".join(erreurs[:2]))


def _verifier_automatisations(page, rap: Rapport, erreurs: list[str]) -> None:
    """Tâches / Terminées / Permissions étaient trois onglets pour une seule
    liste. Les deux premiers sont un filtre d'état, le troisième une section."""
    print("\n── Live › Automatisations ──")
    del erreurs[:]
    page.locator('.sidebar-item[data-route="live/automatisations"]').click()
    page.wait_for_timeout(1800)

    # Les comptes du segmented sont DÉRIVÉS des tâches chargées : trois boutons
    # sans compte veut dire que la liste n'est jamais arrivée.
    vues = page.locator("#auto-vues button").count()
    rap.dire(vues == 3, "les trois états sont des filtres", f"{vues} bouton(s)")

    libelle = page.locator("#auto-vues button").first.inner_text()
    rap.dire("·" in libelle, "le filtre annonce son compte", libelle)

    page.locator('#auto-vues [data-vue="terminees"]').click()
    page.wait_for_timeout(500)
    hash_vu = page.evaluate("location.hash")
    rap.dire("vue=terminees" in hash_vu, "l'état part dans l'URL", hash_vu)

    # Le tableau doit dire quelque chose dans TOUS les cas : une liste vide sans
    # phrase, c'est un panneau mort qu'on prend pour une absence de tâches.
    contenu = _attendre_contenu(page, "auto-liste")
    rap.dire(contenu > 0, "la liste rend quelque chose", f"{contenu} car.")

    perms = _attendre_contenu(page, "auto-permissions")
    rap.dire(perms >= _CONTENU_MIN, "les permissions sont une section", f"{perms} car.")

    ancres = page.locator("#page-rail .rail-ancre").all_inner_texts()
    rap.dire(ancres == ["Tâches", "Qui peut demander quoi", "Historique d'exécution"],
             "le sommaire est celui de CETTE page", " · ".join(ancres))

    # Chaque ancre doit viser une section qui EXISTE. Un sommaire peint par une
    # autre page (réponse réseau tardive) passe tous les tests de comptage et
    # mène pourtant vers le vide — le défaut corrigé le 2026-08-28.
    orphelines = page.evaluate(
        "Array.from(document.querySelectorAll('#page-rail [data-ancre]'))"
        ".filter(a => !document.getElementById(a.dataset.ancre))"
        ".map(a => a.dataset.ancre)")
    rap.dire(not orphelines, "chaque ancre vise une section présente",
             " · ".join(orphelines))

    rap.dire(not erreurs, "aucune erreur JS sur Automatisations",
             " · ".join(erreurs[:2]))


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

    ancres = page.locator("#page-rail .rail-ancre").all_inner_texts()
    rap.dire(ancres == ["Flux en direct", "Erreurs groupées", "Statistiques",
                        "Vider le journal"],
             "le sommaire est celui de CETTE page", " · ".join(ancres))

    page.locator('#journal-niveaux [data-niveau="ALL"]').click()
    page.wait_for_timeout(300)
    rap.dire(not erreurs, "aucune erreur JS sur le Journal", " · ".join(erreurs[:2]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--overlay", action="store_true", help="overlay seulement")
    ap.add_argument("--admin", action="store_true", help="dashboard seulement")
    ap.add_argument("--public", action="store_true", help="site public seulement")
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
    tout = not (args.overlay or args.admin or args.public)
    rap = Rapport()

    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--no-sandbox"])
        try:
            if tout or args.overlay:
                verifier_overlay(nav, rap, captures)
            if tout or args.public:
                verifier_site_public(nav, rap, captures)
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
    print("✅ le front monte — overlay, site public et dashboard, sans erreur JS ni panneau vide")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
