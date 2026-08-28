# Refonte du panel admin — plan

**Date** : 2026-08-28
**Source** : handoff Claude Design `a5f004f3-fe28-404b-ad1f-273434a9101a`,
rapatrié dans `design_handoff_panel_admin/` (README + 2 maquettes `.dc.html`).
**Branche** : `feat/site-redesign-arcade`

Ce document porte les arbitrages. La maquette porte le pixel : pour toute
question de couleur, d'espacement ou de hiérarchie, c'est
`design_handoff_panel_admin/Panel Wally - Ecrans finaux.dc.html` qui tranche,
pas ce fichier.

## Ce qui change, en une phrase

Le panel passe de **7 sections × jusqu'à 7 sous-onglets × parfois un troisième
niveau** à **3 thèmes × 11 pages plates**. Tout ce qui était un sous-onglet
d'état devient un filtre dans l'URL.

## Arbitrages rendus

### Pas de rôles (2026-08-28, owner)

> « accès au panel via le mot de passe donne accès à tout. modo ou admin ont les
> mêmes droits »

L'écran 13 du handoff (« Système › Accès & rôles ») **est abandonné**.
`dashboard/auth.py` garde son jeton unique. Aucune matrice de droits, aucun
journal d'accès, aucun filtrage de sidebar par rôle. Les états « droits
insuffisants » décrits dans le handoff n'ont donc pas lieu d'être.

Conséquence : 11 pages au lieu de 12 + 1.

### La typo ne bouge pas

Les maquettes sont en IBM Plex Sans. On garde **Inter**, déjà chargé. On porte
l'échelle typographique, pas la police. En revanche la monospace se généralise
partout où la valeur est technique (horodatages, ids, trust/love, clés
d'éléments, tailles, coûts, en-têtes de section).

### La sidebar bureau est en texte seul

La maquette retenue n'a **pas d'icône** dans la sidebar bureau : des libellés
groupés sous des en-têtes en mono majuscules. Les SVG existants de
`index.html` sont réemployés pour la **barre du bas mobile** (4 destinations),
pas pour la sidebar.

## Nouvelle architecture

| Route | Page | Vient de |
|---|---|---|
| `#/cockpit` | Cockpit | nouveau |
| `#/cerveau/personnes` | Personnes | Mémoire › Utilisateurs + Comptes Apex + Ignorés + Notes du bot |
| `#/cerveau/personnes/{id}` | Personnes › fiche | nouveau |
| `#/cerveau/memoire` | Mémoire commune | Mémoire › Mémoire communautaire + Questions + Dans la tête de Wally |
| `#/cerveau/personnalite` | Personnalité | Paramètres › Émotions + onglet Prompts |
| `#/cerveau/modeles` | Modèles & coûts | Paramètres › LLM |
| `#/live/scene` | Scène & overlays | Mise en scène + Système › Overlay |
| `#/live/voix` | Voix | onglet Vocal + Paramètres › Vocal |
| `#/live/medias` | Médias & sons | Paramètres › Images + galerie + sons du chat |
| `#/live/automatisations` | Automatisations | Actions (Tâches + Terminées + Permissions) |
| `#/systeme/journal` | Journal | Système › Logs (3 niveaux aplatis) |
| `#/systeme/connexions` | Connexions | barre du haut + Système › Twitch |

## API à créer

| Route | Pour | Phase |
|---|---|---|
| `GET /api/admin/person/{id}` | Fiche Personne agrégée : identités liées, mémoires, notes, comptes Apex, trust/love, dernières apparitions | 4 |
| ✅ `GET /api/admin/journal/erreurs` | Lignes ERROR regroupées : message, compteur, dernière occurrence, plus le compte par niveau | 2 |
| `GET /api/admin/decisions` | File « demande une décision » du cockpit : tâches en échec, chevauchements de scène, identités à rattacher, questions en attente — type, libellé, cible de navigation | 8 |

Pas d'API de rôles (arbitrage ci-dessus). La fusion d'identités s'expose depuis
ce que fait déjà `scripts/rattacher_identites_inconnues.py`.

## Phases

Chaque phase ≤ 5 fichiers, vérifiée avant la suivante. `overlay_admin.js`
(334 ko) est touché **en dernier** et seulement pour sa chrome.

| # | Phase | Fichiers | Vérification |
|---|---|---|---|
| 1 | ✅ Coquille : sidebar groupée, routage par hash, tokens de design | `index.html`, `style.css`, `app.js`, `smoke_front.py`, tests | ✅ `f38843b6` — les 11 routes montent, hash juste, 14 sous-panneaux rendent |
| 2 | ✅ Journal — 3 barres d'onglets → 1 ligne de filtres, erreurs groupées | `app.js`, `routes/sse.py`, `style.css`, `index.html`, `smoke_front.py`, tests | ✅ filtres dans l'URL et au rechargement, 15 puces dérivées, sommaire d'ancres |
| 3 | Automatisations + sommaire d'ancres | `app.js`, `style.css`, tests | Motif « filtre au lieu d'onglet » validé |
| 4 | API personne agrégée + Personnes + fiche | `routes/memory.py`, nouveau `routes/person.py`, `app.js`, tests | Une requête rend toute la fiche |
| 5 | Personnalité + Modèles & coûts | `app.js`, `style.css`, tests | Prompts absorbés, sauvegarde conditionnelle |
| 6 | Médias & sons, Connexions, Voix | `app.js`, `style.css`, tests | Les deux « Vocal » fusionnés |
| 7 | Mémoire commune | `app.js`, tests | Questions de Wally + doublons |
| 8 | Cockpit + API décisions | nouveau `routes/decisions.py`, `app.js`, tests | Chaque item ouvre sa page déjà filtrée |
| 9 | Scène & overlays — chrome seule | `overlay_admin.js`, `app.js` | Canevas, liste et inspecteur intacts |
| 10 | Mobile + responsive | `style.css`, `index.html`, `app.js` | Barre du bas, scène en lecture seule |

## Pièges connus de la zone

- Un `throw` dans un `mount()` casse tous les montages suivants ; `node --check`
  ne voit pas les TDZ. **Seul `scripts/smoke_front.py` exécute le JavaScript.**
- `_renderPanelOnce` existe parce que deux appels rapprochés montaient un
  panneau en double, avec des `id` en double et un réglage sauvegardé depuis la
  mauvaise copie. Le routage par hash multiplie les chemins d'entrée dans une
  page : **la garde reste obligatoire**.
- Le sommaire d'ancres ne doit **pas** utiliser `scrollIntoView` : la colonne de
  contenu a son propre `overflow`, c'est elle qu'il faut faire défiler.
- Les onglets legacy (`admin-config`, `admin-logs`, `admin-overlay`,
  `admin-twitch`) redirigent déjà ; les anciens hash doivent continuer de tomber
  sur la bonne page neuve.
