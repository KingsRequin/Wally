# Public UI — Refonte multi-onglets

**Date :** 2026-04-03  
**Statut :** Approuvé  

---

## Contexte

Le `public-ui/` actuel est une page unique (statut + émotions + galerie réduite). L'objectif est de le refondre en une SPA multi-onglets avec glassmorphisme, animations, et accès à toutes les fonctionnalités publiques de Wally.

---

## Décisions de design

| Sujet | Décision |
|---|---|
| Navigation | Onglets horizontaux en haut |
| Chat | Connexion Discord OAuth obligatoire |
| À propos | Pipeline interactif cliquable |
| Architecture code | Réécriture vanilla JS modulaire (pas de framework) |

---

## Structure des fichiers

```
public-ui/
├── index.html          # Shell HTML, onglets, blobs de fond
├── style.css           # Variables, reset, layout, composants partagés
├── app.js              # Router hash-based, init, SSE emotions
└── tabs/
    ├── status.js       # Onglet Statut
    ├── chat.js         # Onglet Chat
    ├── gallery.js      # Onglet Galerie
    ├── journal.js      # Onglet Journal
    └── about.js        # Onglet À propos
```

---

## Style — Glassmorphisme dark

- **Fond** : `#0a0a0f` + blobs de couleur animés (cyan, violet) pour la texture derrière les cartes
- **Cartes** : `background: rgba(255,255,255,0.04)` + `backdrop-filter: blur(20px)` + `border: 1px solid rgba(255,255,255,0.09)`
- **Border-radius** : 14–16px
- **Accent** : `#06b6d4` (cyan)
- **Couleurs émotions** : anger `#ef4444`, joy `#eab308`, curiosity `#22c55e`, sadness `#3b82f6`, boredom `#a855f7`
- **Animations** : fade-in, slide-in, scale au hover — toutes en CSS transitions/keyframes

---

## Onglet Statut

**APIs :** `GET /api/public/status`, `GET /api/public/twitch/stream`, SSE `/api/public/sse/emotions`

**Contenu :**
- Carte connexions : dot Discord + dot Twitch + uptime formaté
- Carte messages traités : total + breakdown Discord/Web
- Carte humeur en direct : 5 barres animées via SSE, émotion dominante
- Carte stream Azrael : statut live, jeu, titre, viewers

**Refresh :** SSE pour émotions (temps réel), polling 30s pour statut + stream.

---

## Onglet Chat

**Auth :** Connexion Discord OAuth obligatoire. Réutilise `bot/dashboard/routes/chat_auth.py` existant.

**Avant connexion :** Écran de login avec avatar Wally animé (pulse), bouton Discord OAuth, aperçu de l'interface flouté derrière.

**Après connexion — layout 3 colonnes :**

- **Colonne gauche — Wally (220px)** :
  - Avatar GIF animé identique à l'overlay OBS : `/static/avatar/emotions/{emotion}/{tier}.gif`
  - Même logique que `overlay.html` : émotion dominante > 0.2, tier = low/mid/high (seuils 0.4/0.7)
  - Mis à jour via SSE `/api/public/sse/emotions`
  - Émotion dominante affichée en texte sous l'avatar
  - 5 mini-barres d'émotions en temps réel
  - Dot "En ligne"

- **Colonne centrale — Messages** :
  - Bulles bot (cyan) + bulles user (indigo), animation `msgIn` au chargement
  - Indicateur de frappe (3 points animés)
  - Barre utilisateur en haut (avatar Discord, nom, bouton déconnexion)

- **Colonne droite — Mémoire (240px)** :
  - Sections FAITS / PRÉFÉRENCES + scores relation (affinité, confiance)
  - Récupérés via `GET /api/public/memory/me` *(nouvel endpoint à créer, JWT requis)*

- **Input** : barre fixe en bas sur toute la largeur

**Transport :** WebSocket existant (`/ws/chat`).

---

## Onglet Galerie

**API :** `GET /api/public/gallery?limit=N&sort=date|votes`

**Contenu :**
- Barre de filtres : Toutes / Récentes / Populaires
- Grille `auto-fill minmax(140px, 1fr)`, animation `fadeIn` en cascade (delay par index)
- Hover : scale + overlay avec prompt et compteur de votes
- "Charger plus" en bas
- Modal lightbox au clic sur une image

---

## Onglet Journal

**API :** `GET /api/public/journal` *(nouvel endpoint à créer — lit `journal_archive` en DB)*

**Structure :**
- **Frise chronologique** : ligne horizontale + points cliquables (un par entrée)
  - Point actif : cyan + glow
  - Date sous chaque point
  - Dernier point actif par défaut
- **Entrée sélectionnée** affichée sous la frise :
  - Header : date, nombre de mots, badges émotions colorés
  - Corps : texte complet du journal
  - Animation `fadeIn` au changement d'entrée

---

## Onglet À propos

**Contenu statique (pas d'API).**

**Sections :**

1. **Pipeline interactif** — 6 étapes cliquables (Message → Mémoire → Émotions → Personnalité → LLM → Réponse). Clic sur une étape = affichage d'une description dans un panneau en dessous. Chaque étape a sa couleur.

2. **Les piliers de Wally** — grille 2×2 de cartes : Mémoire, Émotions, Personnalité, Journal. Animation `fadeUp` en cascade.

---

## Nouveaux endpoints à créer

| Route | Description |
|---|---|
| `GET /api/public/journal?limit=N` | Liste les N dernières entrées de `journal_archive` (date, content, word_count) |
| `GET /api/public/memory/me` | Retourne les souvenirs + scores relation de l'utilisateur connecté (JWT requis) |

---

## Router (hash-based)

```js
// app.js
const TABS = { status, chat, gallery, journal, about };

window.addEventListener('hashchange', route);
function route() {
  const tab = location.hash.slice(1) || 'status';
  TABS[tab]?.mount(document.getElementById('tab-content'));
}
```

Chaque module `tabs/*.js` exporte `{ mount(el) }` — injecte son HTML dans `el`, attache ses événements, lance ses requêtes. `unmount()` optionnel pour nettoyer SSE/WS.

---

## Animations globales

- Blobs de fond : `radial-gradient` + `keyframes` translate, 8–13s, `ease-in-out infinite`
- Entrée onglet : `fadeIn` 0.3s sur `#tab-content`
- Cartes : `fadeUp` en cascade (delay × index)
- Galerie : `fadeIn` + `scale(0.95→1)` en cascade
- Journal : `fadeIn translateY(-8px→0)` au changement d'entrée
- Dots timeline : scale + glow au clic
- Barres émotions : `transition: width 0.6s ease`
- Bulle chat typing : 3 dots `translateY` en stagger
