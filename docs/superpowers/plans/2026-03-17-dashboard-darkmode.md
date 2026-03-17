# Dashboard Dark Mode Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir `bot/dashboard/static/style.css` en dark mode permanent (palette Catppuccin Mocha) en conservant l'esthétique Neo-Brutalism et les cartes colorées.

**Architecture:** Modification CSS uniquement — aucun changement HTML ni JS. Les CSS custom properties (variables `:root`) sont déjà utilisées massivement, ce qui rend la migration propre : on remplace les valeurs dans `:root`, on corrige les quelques couleurs hardcodées, et on ajoute des règles de surcharge pour les éléments textuels sur cartes colorées.

**Tech Stack:** CSS vanilla, Neo-Brutalism, Catppuccin Mocha palette.

---

## Fichiers concernés

| Fichier | Action |
|---|---|
| `bot/dashboard/static/style.css` | Modifier — seul fichier à toucher |

Pas de nouveaux fichiers. Pas de tests automatisés (CSS pur — vérification visuelle dans le navigateur).

---

### Task 1 : Mettre à jour les variables `:root`

**Files:**
- Modify: `bot/dashboard/static/style.css` (bloc `:root`, lignes 9–43)

Remplacer le bloc `:root` complet. Toutes les valeurs actuelles → nouvelles valeurs Catppuccin Mocha.

- [ ] **Step 1 : Ouvrir le dashboard dans le navigateur**

  Ouvrir `http://<host-ip>:<PORT>` (port du dashboard Wally, voir `config.yaml`).
  État attendu : dashboard en mode clair (blanc/beige).

- [ ] **Step 2 : Remplacer le bloc `:root` dans `style.css`**

  Remplacer intégralement le bloc `:root` existant (lignes 9–43) par :

  ```css
  :root {
    --bg: #1e1e2e;
    --bg-alt: #181825;
    --card: #313244;
    --border: #cdd6f4;
    --shadow: 4px 4px 0px #cdd6f4;
    --shadow-sm: 2px 2px 0px #cdd6f4;
    --shadow-btn: 3px 3px 0px #cdd6f4;
    --text: #cdd6f4;
    --text-muted: #6c7086;
    --font: 'Courier New', Courier, monospace;
    --radius: 14px;
    --radius-sm: 8px;
    --radius-btn: 10px;
    --radius-tab: 6px;
    --radius-xs: 4px;

    /* Emotion colors — Catppuccin Mocha */
    --c-anger:    #f38ba8;
    --c-joy:      #f9e2af;
    --c-curiosity:#a6e3a1;
    --c-sadness:  #89b4fa;
    --c-boredom:  #585b70;

    /* Card accent colors — Catppuccin pastel */
    --card-pink:   #f38ba8;
    --card-teal:   #94e2d5;
    --card-yellow: #f9e2af;
    --card-aqua:   #89dceb;
    --card-mint:   #a6e3a1;

    /* Status */
    --c-online:  #a6e3a1;
    --c-offline: #f38ba8;
  }
  ```

- [ ] **Step 3 : Vérifier visuellement**

  Recharger la page. État attendu :
  - Fond bleu-nuit `#1e1e2e`
  - Cartes avec fond `#313244`
  - Bordures et ombres lavande
  - Cartes colorées pastélisées (rose pâle, teal doux, jaune crème…)

- [ ] **Step 4 : Commit**

  ```bash
  git add bot/dashboard/static/style.css
  git commit -m "style(dashboard): update CSS variables to Catppuccin Mocha dark palette"
  ```

---

### Task 2 : Corriger les couleurs hardcodées dans les règles existantes

**Files:**
- Modify: `bot/dashboard/static/style.css`

Ces couleurs sont inscrites en dur dans des règles CSS (elles ignorent les variables). Modifier chacune.

- [ ] **Step 1 : Corriger `.tab-btn`**

  Trouver : `border-right: 1px solid #ddd;`
  Remplacer par : `border-right: 1px solid rgba(205,214,244,0.15);`

- [ ] **Step 2 : Corriger `.tab-btn:hover:not(.active)`**

  Trouver : `background: #eee;`
  Remplacer par : `background: #313244;`

  Trouver (dans le même bloc) : `color: var(--text);`
  → inchangé (déjà correct).

- [ ] **Step 3 : Corriger `.tab-btn.disabled`**

  Trouver : `color: #bbb;`
  Remplacer par : `color: #45475a;`

- [ ] **Step 4 : Corriger `.gauge-track`**

  Trouver : `background: rgba(0, 0, 0, 0.12);`
  Remplacer par : `background: rgba(255,255,255,0.08);`

  Trouver : `border: 1.5px solid rgba(0, 0, 0, 0.15);`
  Remplacer par : `border: 1.5px solid rgba(255,255,255,0.12);`

- [ ] **Step 5 : Corriger `.emotion-summary`**

  Trouver : `color: rgba(0, 0, 0, 0.55);`
  Remplacer par : `color: rgba(205,214,244,0.6);`

- [ ] **Step 6 : Corriger `.btn-danger`**

  Trouver : `background: #fee2e2;` (dans la règle `.btn-danger`)
  Remplacer par : `background: #3d1522;`

  Note : `border-color` et `color` de `.btn-danger` utilisent déjà `var(--c-offline)` → inchangés.

- [ ] **Step 7 : Corriger `.stream-offline-badge`**

  Trouver : `background: #eee;` (dans `.stream-offline-badge`)
  Remplacer par : `background: #313244;`

  Trouver : `border: 2px solid #999;`
  Remplacer par : `border: 2px solid #45475a;`

- [ ] **Step 8 : Corriger les entrées de log**

  Trouver : `.log-entry.INFO    { color: #555; }`
  Remplacer par : `.log-entry.INFO    { color: #a6adc8; }`

  Trouver : `.log-entry.WARNING { color: #b45309; font-weight: 700; }`
  Remplacer par : `.log-entry.WARNING { color: #f9e2af; font-weight: 700; }`

  Note : `.log-entry.ERROR` utilise déjà `var(--c-offline)` → inchangé.

- [ ] **Step 9 : Corriger `.toast.error`**

  Trouver : `.toast.error   { background: #fee2e2; border-color: var(--c-offline); color: var(--c-offline); }`
  Remplacer par : `.toast.error   { background: #3d1522; border-color: var(--c-offline); color: var(--c-offline); }`

- [ ] **Step 10 : Corriger l'input background**

  Dans la règle `input[type="text"], input[type="number"], input[type="password"], select, textarea { ... }` :
  Trouver : `background: var(--card);`
  Remplacer par : `background: var(--bg-alt);`

  Note : `color: var(--text)` dans cette règle → inchangé, sera automatiquement `#cdd6f4`.

- [ ] **Step 11 : Vérifier visuellement**

  Recharger la page. Vérifier :
  - Tabs : hover sur un tab non-actif → fond sombre `#313244` (pas blanc `#eee`)
  - Tabs désactivés → couleur grise discrète
  - Jauges d'humeur → piste sombre (pas transparente noire)
  - Résumé d'humeur → texte lavande (pas gris foncé illisible)
  - Bouton RESET → fond rouge sombre avec texte rose
  - Badge OFFLINE → fond sombre avec bordure grise
  - Logs (admin) : INFO = gris clair, WARNING = jaune crème, ERROR = rose
  - Toast erreur → fond rouge sombre

- [ ] **Step 12 : Commit**

  ```bash
  git add bot/dashboard/static/style.css
  git commit -m "style(dashboard): fix hardcoded colors for dark mode"
  ```

---

### Task 3 : Ajouter les règles de surcharge pour cartes colorées et fond sombre

**Files:**
- Modify: `bot/dashboard/static/style.css` — ajouter des règles à la fin du fichier

Les cartes colorées (`.card-pink`, `.card-teal`, etc.) ont un fond pastel clair. Certains éléments textuels héritent maintenant de `--text` (lavande), ce qui est illisible sur fond clair. On ajoute des surcharges à la fin du fichier.

- [ ] **Step 1 : Ajouter les règles en fin de fichier**

  Ajouter le bloc suivant à la toute fin de `style.css` :

  ```css
  /* ── Dark mode overrides : texte sur cartes colorées ─────────────────────── */

  /* card-title et card-value sur cartes neutres sombres */
  .card:not(.card-pink):not(.card-teal):not(.card-yellow):not(.card-aqua):not(.card-mint) .card-title {
    color: rgba(205,214,244,0.55);
  }

  .card:not(.card-pink):not(.card-teal):not(.card-yellow):not(.card-aqua):not(.card-mint) .card-value {
    color: var(--text);
  }

  /* card-title dans le graph container (fond sombre) */
  .graph-container .card-title {
    color: rgba(205,214,244,0.55);
  }

  /* gauge-val sur cartes colorées (fond pastel clair → texte sombre) */
  .card-pink .gauge-val,
  .card-teal .gauge-val,
  .card-yellow .gauge-val,
  .card-aqua .gauge-val,
  .card-mint .gauge-val {
    color: #111;
  }

  /* emotion-label sur cartes colorées */
  .card-pink .emotion-label,
  .card-teal .emotion-label,
  .card-yellow .emotion-label,
  .card-aqua .emotion-label,
  .card-mint .emotion-label {
    color: #111;
  }

  /* emotion-summary sur cartes colorées */
  .card-pink .emotion-summary,
  .card-teal .emotion-summary,
  .card-yellow .emotion-summary,
  .card-aqua .emotion-summary,
  .card-mint .emotion-summary {
    color: rgba(0,0,0,0.55);
  }
  ```

- [ ] **Step 2 : Vérifier visuellement — onglet HUMEUR**

  Aller sur l'onglet 😤 HUMEUR. La carte jaune (`card-yellow`) contient les jauges.
  Vérifier :
  - Titre "HUMEUR EN DIRECT" → noir semi-transparent (lisible sur fond jaune)
  - Labels "ANGER", "JOY"… → noirs (pas lavande)
  - Valeurs "72%"… → noires (pas lavande)
  - Résumé d'humeur → texte sombre (pas lavande)

- [ ] **Step 3 : Vérifier visuellement — onglet STATUT**

  Aller sur l'onglet 📊 STATUT.
  Vérifier :
  - Carte UPTIME (card-pink) : titre et valeur → noirs (lisibles sur rose pâle)
  - Carte PLATEFORMES (card-teal) : texte → noir
  - Carte MESSAGES (card-mint) : texte → noir
  - Graphe "DERNIÈRES 24H" : titre → lavande (lisible sur fond sombre `#313244`)

- [ ] **Step 4 : Commit final**

  ```bash
  git add bot/dashboard/static/style.css
  git commit -m "style(dashboard): add dark mode overrides for text on colored/dark cards"
  ```
