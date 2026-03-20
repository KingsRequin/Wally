# Trois améliorations Wally — Design Spec

**Date:** 2026-03-20
**Scope:** Trust score initial, page login Discord, onglet Journal détaillé

---

## 1. Trust score initial à 0.0

### Contexte
Le trust score démarre actuellement à 0.5 (neutre). La confiance doit se mériter — on passe à 0.0.

### Changements

**`bot/db/database.py`**
- Schema SQL : `score REAL NOT NULL DEFAULT 0.0` (était `0.5`)
- Fallback Python dans `get_trust_score()` : `return 0.0` (était `0.5`)
- `COALESCE(t.score, 0.5)` dans `list_memory_users()` → `COALESCE(t.score, 0.0)`
- Migration au démarrage dans `_init_schema()` : `UPDATE trust_scores SET score = MAX(score - 0.5, 0.0)`
- Idempotence : `ALTER TABLE trust_scores ADD COLUMN trust_v2_migrated INTEGER DEFAULT 0` — si la colonne existe déjà, le UPDATE est skippé (même pattern que les migrations existantes avec try/except)

**`bot/core/emotion.py`**
- `trust_score: float = 0.5` (défauts des méthodes d'analyse) → `0.0` (2 occurrences)

**`bot/dashboard/routes/chat.py`**
- `trust: float = 0.5` dans `_post_process()` → `0.0`

### Impact
- Les nouveaux utilisateurs partent à 0.0
- Les utilisateurs existants perdent 0.5 de trust score (plancher à 0.0)
- À +0.01 par interaction positive, il faut ~50 interactions pour atteindre l'ancien défaut de 0.5 — c'est le comportement voulu (la confiance se mérite)
- Faire un backup de la base SQLite avant déploiement est recommandé

---

## 2. Page de connexion Discord enrichie

### Contexte
La page de login du chat web dit juste "Connecte-toi avec Discord pour discuter avec Wally en temps réel." — pas d'explication sur pourquoi Discord est nécessaire ni ce qu'on fait des données.

### Design validé : Page dédiée (Option B)

**Structure de la page (dans `renderChatTab()` quand non authentifié) :**

1. **Titre** : "Avant de te connecter..."
2. **Sous-titre** : "Wally a besoin de savoir qui tu es pour se souvenir de toi."
3. **Bloc central "Pourquoi Discord ?"** (bordure accent #5865F2) :
   - Texte : "Wally utilise ton compte Discord comme identifiant pour rattacher tes souvenirs à ton profil. C'est ce qui lui permet de te reconnaître et de se souvenir de tes échanges passés, que ce soit ici ou sur le serveur Discord."
4. **4 cartes en grille 2×2 :**
   - 🧠 **Ta mémoire personnelle** (accent curiosity #00ccff) — Au fil de vos échanges, Wally retient tes goûts, ton humour, tes sujets favoris. Chaque conversation devient plus naturelle.
   - 🔒 **Données minimales** (accent joy #ffdd00) — Seuls ton pseudo, ton ID et ton avatar Discord sont récupérés. Aucun accès à tes messages, serveurs ou liste d'amis.
   - 📦 **Hébergement local** (accent sadness #7777ff) — Tout est stocké sur le serveur de Wally. Rien ne transite par des services tiers. Tes données restent chez nous.
   - 🗑️ **Contrôle total** (accent anger #ff3333) — Tu peux consulter ou supprimer tous tes souvenirs à tout moment, directement depuis le chat.
5. **Bouton** : "Se connecter avec Discord" (même lien `/api/chat/auth/login`)

### Fichiers modifiés
- `bot/dashboard/static/app.js` — `renderChatTab()` : remplacement du bloc HTML non authentifié
- `bot/dashboard/static/style.css` — styles pour les cartes d'explication (si non couverts par le CSS existant)

---

## 3. Onglet "Journal détaillé"

### Contexte
Nouvel onglet public dans le dashboard expliquant le fonctionnement interne de Wally. Vulgarisation accessible avec accordéons "Aller plus loin" montrant le code source et des explications techniques poussées.

### Position dans le dashboard
Onglet public dans la sidebar, après "Roadmap" et avant "Chat". Icône : 📖 ou équivalent SVG.

### Structure : 6 sections

Chaque section suit le même pattern :
- Numéro coloré + titre
- Explication vulgarisée détaillée (4-6 phrases, accessible à tous, exemples concrets)
- Schéma visuel quand pertinent (pipeline, jauges, diagramme)
- Accordéon `<details>` "Aller plus loin" contenant :
  - Chemin du fichier source concerné
  - Extrait de code pertinent (simplifié/commenté)
  - Explication technique approfondie (formules, concepts, choix d'architecture)

#### Section 1 — Cycle de vie d'un message
- **Vulgarisation** : Quand quelqu'un écrit un message, Wally le reçoit, détecte la langue, analyse le ton émotionnel avec NRCLex, consulte ses souvenirs sur l'auteur via Qdrant, vérifie le trust score, construit un prompt personnalisé avec sa personnalité et son humeur actuelle, envoie tout à OpenAI, puis poste la réponse. En arrière-plan, il met à jour le trust score et logge le coût.
- **Schéma** : Pipeline horizontal (Message → Langue → Émotion → Mémoire → Prompt → OpenAI → Réponse)
- **Aller plus loin** : Code de `handle_message()` dans `bot/discord/handlers.py`, explication du pipeline async, `asyncio.to_thread()` pour NRCLex

#### Section 2 — Système émotionnel
- **Vulgarisation** : Wally ressent 5 émotions en permanence (colère, joie, tristesse, curiosité, ennui), chacune entre 0.0 et 1.0. Chaque message les fait bouger — un compliment booste la joie, une insulte monte la colère. Avec le temps, elles retombent naturellement vers zéro, comme un humain qui se calme. La vitesse de retombée est différente pour chaque émotion. Si la colère dépasse un seuil trop souvent avec le même utilisateur, Wally le mute temporairement.
- **Visuel** : 5 jauges statiques/décoratives avec les couleurs d'émotion (pas de données live — c'est de la documentation, pas un monitoring)
- **Aller plus loin** : Formule `E(t) = E₀ × e^(−λ × Δt)`, code `_apply_decay()`, analyse NRCLex, impact du trust score sur les deltas, mécanisme de timeout

#### Section 3 — Mémoire
- **Vulgarisation** : Deux types de mémoire. La mémoire courte = les derniers messages de la conversation en cours (sliding window). La mémoire longue = des faits extraits automatiquement au fil du temps et stockés dans une base vectorielle. Wally sait que tu aimes les crevettes, que tu joues à Apex, que tu détestes le lundi. Plus tu interagis, plus il te connaît. Chaque plateforme (Discord/Twitch) a sa propre mémoire.
- **Aller plus loin** : mem0 + Qdrant, namespace `{platform}:{user_id}`, FactExtractor et extraction par batch, trust score 0.0→1.0, recherche par similarité vectorielle, summarization quand la window dépasse le seuil de tokens

#### Section 4 — Personnalité
- **Vulgarisation** : La personnalité de Wally est définie dans des fichiers texte : son âme (qui il est fondamentalement), son identité (son histoire, ses goûts), sa voix (comment il parle), et des exemples de réponses. Ces fichiers sont assemblés en un bloc injecté dans chaque conversation. L'émotion dominante du moment ajoute une directive comportementale — si Wally est joyeux, il est plus bavard et taquin ; s'il est en colère, ses réponses sont courtes et impatientes.
- **Aller plus loin** : Fichiers SOUL.md/IDENTITY.md/VOICE.md/EXEMPLES.md, PersonaService, EMOTIONS.md parsé en directives par émotion, `PromptBuilder.build()`, `load_prompt()`

#### Section 5 — Journal quotidien
- **Vulgarisation** : Chaque soir, Wally écrit son journal de la journée. Il compile toutes les conversations, identifie les moments forts (pics d'émotion), note les statistiques (nombre de messages, participants actifs, heures d'activité), et rédige un résumé narratif de sa journée avec ses propres mots. Il génère aussi un graphe de l'évolution de ses émotions et forme des opinions sur les sujets récurrents.
- **Aller plus loin** : DailyJournal, sources multiples (daily_log → channel history → RAM → mem0), multi-pass summarization pour les grosses journées, graphe Matplotlib, archivage en base, formation d'opinions fire-and-forget

#### Section 6 — Architecture
- **Vulgarisation** : Wally est un programme Python unique qui gère Discord et Twitch en parallèle. Les deux plateformes partagent le même cerveau (émotions, mémoire, personnalité). Les souvenirs sont stockés dans Qdrant, une base de données spécialisée dans la recherche par similarité. Le tout tourne dans un seul conteneur Docker, avec Qdrant dans un second conteneur.
- **Schéma** : Diagramme d'architecture (Discord Bot + Twitch Bot → Core Services → Qdrant/SQLite/OpenAI)
- **Aller plus loin** : `asyncio.gather()`, injection de dépendances dans `main.py`, docker-compose, healthcheck Qdrant, config hot-reload

### Rendu
- Contenu 100% statique, généré en JS dans `renderJournalDetailTab()` — pas d'appel API
- Schémas en CSS/HTML inline (même approche que les SVG inline existants dans le dashboard)
- Grille 2×2 des cartes passe en colonne unique sur mobile (breakpoint existant `is-mobile`)
- Les `<details>` natifs HTML gèrent les accordéons — pas de JS custom nécessaire

### Engagement de maintenance
Cette page doit être mise à jour à chaque modification du bot qui impacte un des 6 sujets couverts. C'est une responsabilité continue.

### Tests
- Améliorations 2 et 3 sont purement frontend → test manuel suffisant
- Amélioration 1 (trust score) → mettre à jour les tests existants qui assertent sur le défaut 0.5

### Fichiers modifiés
- `bot/dashboard/static/index.html` — nouvel onglet dans la sidebar + conteneur `tab-journal-detail`
- `bot/dashboard/static/app.js` — fonction `renderJournalDetailTab()` avec les 6 sections
- `bot/dashboard/static/style.css` — styles pour les sections, accordéons, schémas, numéros colorés
