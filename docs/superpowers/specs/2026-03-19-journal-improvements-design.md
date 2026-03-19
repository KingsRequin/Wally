# Spec — Amélioration du journal quotidien de Wally

> Date : 2026-03-19
> Approche : enrichissement incrémental du pipeline existant (Approche A)

---

## Contexte

Le journal quotidien est généré chaque soir par `DailyJournal.generate_and_send()`. Il résume
la journée de conversations via un pipeline multi-pass (chunks → synthèse → prompt LLM → envoi Discord).

Le système actuel fonctionne mais produit des journaux génériques : longueur fixe, pas de stats,
pas de continuité d'un jour à l'autre, pseudos perdus dans les résumés, pics émotionnels noyés
dans le résumé lossy.

---

## Features

### F1 — Longueur dynamique

**Objectif :** Adapter la longueur du journal au volume d'activité de la journée.

**Mécanisme :**
- Compter le nombre de messages du jour (`len(all_messages)`)
- Trois paliers :
  - < 50 messages → "150 à 250 mots"
  - 50–150 messages → "250 à 400 mots"
  - > 150 messages → "400 à 600 mots"
- La fourchette est injectée dynamiquement dans le prompt user, remplaçant la valeur fixe
  "200 à 350 mots" du template `journal_system.md`

**Fichiers impactés :**
- `bot/core/journal.py` : calcul du palier, injection dans le prompt user
- `bot/persona/prompts/journal_system.md` : retirer la fourchette fixe, ajouter un placeholder
  ou laisser le code l'overrider via le message user

---

### F2 — Résumés intermédiaires plus riches

**Objectif :** Donner plus de matière narrative au LLM en augmentant la taille des résumés.

**Changements :**
- `_CHUNK_SIZE` : 20 → 30 messages par chunk
- Prompt `journal_chunk_system.md` : "3 à 6 lignes" → "5 à 10 lignes"
- Prompt `journal_final_system.md` : "6 à 10 lignes" → "10 à 20 lignes"

**Fichiers impactés :**
- `bot/core/journal.py` : constante `_CHUNK_SIZE`
- `bot/persona/prompts/journal_chunk_system.md`
- `bot/persona/prompts/journal_final_system.md`

---

### F3 — Préserver les pseudos

**Objectif :** Forcer la mention des noms dans les résumés au lieu de "un utilisateur".

**Changements :**
- Ajouter dans `journal_chunk_system.md` :
  "Mentionne toujours qui a dit ou fait quoi par son pseudo exact — jamais 'un utilisateur',
  'quelqu'un', ou 'une personne'."
- Même ajout dans `journal_final_system.md`

**Fichiers impactés :**
- `bot/persona/prompts/journal_chunk_system.md`
- `bot/persona/prompts/journal_final_system.md`

---

### F4 — Statistiques injectées

**Objectif :** Donner au LLM un contexte quantitatif pour enrichir le journal.

**Données collectées :**
- Nombre total de messages
- Nombre de participants uniques
- Plages horaires actives (ex: "14h-16h, 20h-23h")
- Répartition par plateforme (si F7 implémentée)

**Injection :** Bloc texte structuré injecté dans le prompt user avant le résumé des conversations.

Format :
```
Statistiques de la journée :
- Messages : 127
- Participants : 8
- Activité : 14h-16h, 20h-23h
- Plateformes : Discord (95), Twitch (32)
```

**Fichiers impactés :**
- `bot/core/journal.py` : nouvelle méthode `_build_stats_block(messages)`

---

### F5 — Moments forts taggés (pics émotionnels)

**Objectif :** Logger les pics émotionnels en temps réel et les injecter directement dans le
prompt journal, sans passer par le résumé lossy.

**Nouvelle table `emotion_peaks` :**
```sql
CREATE TABLE IF NOT EXISTS emotion_peaks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    emotion TEXT NOT NULL,
    value REAL NOT NULL,
    trigger_user TEXT,
    trigger_message TEXT,
    channel_id TEXT,
    platform TEXT
);
CREATE INDEX IF NOT EXISTS idx_emotion_peaks_ts ON emotion_peaks(timestamp);
```

**Logique de détection :**
- Dans `EmotionEngine.update()` ou `process_message()` : après calcul du delta, si
  `new_value > threshold` ET `delta > 0` (pic montant, pas stagnation), insert dans la table
- Seuil par défaut : 0.7, configurable via `config.yaml` (`bot.emotion_peak_threshold`)
- Anti-spam : pas de nouveau pic pour la même émotion si le dernier date de < 5 minutes

**Injection dans le journal :**
- `db.get_emotion_peaks_today()` retourne les pics du jour
- Format injecté dans le prompt user :
  ```
  Moments forts émotionnels :
  - 15h32 — pic de joie (85%) déclenché par KingsRequin : "PTDR LA VANNE"
  - 21h15 — pic de colère (78%) déclenché par TrollUser42 : "wally t'es nul"
  ```

**Fichiers impactés :**
- `bot/db/database.py` : table + méthodes `insert_emotion_peak()`, `get_emotion_peaks_today()`
- `bot/core/emotion.py` : détection et logging des pics (nécessite accès à `db`)
- `bot/core/journal.py` : injection dans le prompt

---

### F6 — Continuité narrative (journal de la veille)

**Objectif :** Permettre à Wally de faire référence à ce qu'il a écrit hier.

**Nouvelle table `journal_archive` :**
```sql
CREATE TABLE IF NOT EXISTS journal_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
```

**Logique :**
- Après envoi réussi du journal → `db.insert_journal(date, content, word_count)`
- Au moment de générer → `db.get_yesterday_journal()` retourne le contenu de la veille
- Injecté **en entier** dans le prompt user (pas de troncation — le modèle a largement la
  capacité, ~300-500 tokens pour un journal)
- Si pas de journal hier → section omise

**Fichiers impactés :**
- `bot/db/database.py` : table + méthodes
- `bot/core/journal.py` : récupération + injection + archivage après envoi

---

### F7 — Distinction multi-plateforme

**Objectif :** Distinguer Discord et Twitch dans les stats et le journal.

**Migration `daily_log` :**
- Ajouter colonne `platform TEXT DEFAULT 'discord'` à `daily_log`
- Mettre à jour `log_daily_message()` pour accepter et stocker la plateforme
- Mettre à jour `append_message()` dans `MemoryService` pour passer la plateforme

**Impact sur les stats (F4) :**
- Répartition par plateforme dans le bloc statistiques

**Fichiers impactés :**
- `bot/db/database.py` : migration + méthode mise à jour
- `bot/core/memory.py` : `append_message()` accepte `platform`
- `bot/core/journal.py` : stats groupées par plateforme
- `bot/discord/handlers.py` + `bot/twitch/handlers.py` : passer `platform` à `append_message()`

---

### F8 — Top participants du jour

**Objectif :** Identifier les utilisateurs les plus actifs pour que Wally les mentionne.

**Mécanisme :**
- Compter les messages par auteur dans `all_messages`
- Top 5, format : "KingsRequin (42 msgs), Alice (28 msgs), Bob (15 msgs)"
- Injecté dans le bloc statistiques (F4)

**Fichiers impactés :**
- `bot/core/journal.py` : intégré dans `_build_stats_block()`

---

### F9 — Météo émotionnelle comparative

**Objectif :** Comparer les émotions du jour avec la moyenne de la semaine.

**Mécanisme :**
- `db.get_emotion_snapshots_since(7_jours)` → moyenne par émotion sur la semaine
- `db.get_emotion_snapshots_since(24h)` → moyenne du jour
- Comparaison : delta significatif (> 10%) → mentionné
- Format : "Comparé à la semaine : joie plus haute que d'habitude (+15%), ennui en baisse (-12%)"
- Injecté dans le prompt user après l'arc émotionnel

**Fichiers impactés :**
- `bot/db/database.py` : méthode `get_emotion_averages(since)` si pas déjà existante
- `bot/core/journal.py` : calcul comparatif + injection

---

### F10 — Graphique émotionnel visuel

**Objectif :** Générer un graphique des 5 émotions sur 24h, envoyé comme image Discord.

**Technique :**
- `matplotlib` avec style dark (fond `#1a1a1a`, grille subtile `#333333`)
- 5 courbes avec les couleurs du dashboard :
  - Anger : `#ff3333`
  - Joy : `#ffdd00`
  - Curiosity : `#00ccff`
  - Sadness : `#7777ff`
  - Boredom : `#888888`
- Axe X : heures (0h–23h), Axe Y : 0%–100%
- Légende en français (noms traduits)
- Rendu en mémoire (`BytesIO`) → `discord.File("emotions_jour.png")`
- Envoyé dans le canal journal **avant** le texte du journal
- Pas de fichier temporaire sur disque

**Dépendance :** `matplotlib` ajouté à `requirements.txt`

**Fichiers impactés :**
- `bot/core/journal.py` : nouvelle méthode `_generate_emotion_chart(snapshots) -> BytesIO`
- `bot/core/journal.py` : `set_send_callback` doit supporter l'envoi de fichiers
  (nouvelle callback `set_send_file_callback`)
- `requirements.txt` : ajouter `matplotlib`

---

### F11 — Modèle principal pour la génération finale

**Objectif :** Utiliser le modèle principal (`gpt-5.1`) pour la génération du journal final,
produisant une prose plus riche.

**Changement :**
- `generate_and_send()` : remplacer `complete_secondary()` par `complete()` pour l'appel
  final de génération du journal
- Les résumés intermédiaires (chunks, synthèse) restent sur `complete_secondary()` (travail mécanique)

**Fichiers impactés :**
- `bot/core/journal.py` : un seul appel modifié

---

### F12 — Commande `/test journal`

**Objectif :** Permettre de tester la génération du journal sans polluer les données.

**Slash command :**
- `/test` avec un select menu (options futures possibles, pour l'instant : "Journal")
- Sélection "Journal" → modal ou paramètre pour l'ID du canal cible
- Admin-only (même permissions que `/wally journal`)

**Comportement :**
- Génère le journal normalement (mêmes sources, mêmes prompts)
- Envoie dans le canal choisi par l'utilisateur
- **Ne l'archive PAS** dans `journal_archive`
- **Ne modifie aucune donnée** — Wally fait comme si ce journal n'a jamais existé
- Message préfixé `[TEST]` pour le distinguer visuellement

**Fichiers impactés :**
- Nouveau fichier : `bot/discord/commands/test.py` (cog)
- `bot/discord/bot.py` : charger le cog
- `bot/core/journal.py` : paramètre `archive=True/False` sur `generate_and_send()`

---

## Tables SQL ajoutées/modifiées

| Table | Action | Colonnes |
|---|---|---|
| `emotion_peaks` | CREATE | id, timestamp, emotion, value, trigger_user, trigger_message, channel_id, platform |
| `journal_archive` | CREATE | id, date, content, word_count, created_at |
| `daily_log` | ALTER | + platform TEXT DEFAULT 'discord' |

---

## Dépendances ajoutées

| Package | Raison |
|---|---|
| `matplotlib` | Graphique émotionnel (F10) |

---

## Prompts modifiés

| Fichier | Changements |
|---|---|
| `journal_system.md` | Retirer fourchette fixe de mots, ajouter instruction d'utiliser la fourchette fournie dans le contexte + instruction sur le journal de la veille |
| `journal_chunk_system.md` | 5-10 lignes, préserver les pseudos |
| `journal_final_system.md` | 10-20 lignes, préserver les pseudos |

---

## Ordre d'implémentation suggéré

1. **DB** : tables `emotion_peaks`, `journal_archive`, migration `daily_log.platform`
2. **F2 + F3** : prompts mis à jour (changement isolé, testable immédiatement)
3. **F7** : propagation `platform` dans `daily_log` + `append_message()`
4. **F5** : détection + logging des pics émotionnels dans `EmotionEngine`
5. **F4 + F8** : bloc statistiques + top participants
6. **F9** : météo émotionnelle comparative
7. **F1** : longueur dynamique
8. **F6** : archive journal + continuité narrative
9. **F11** : modèle principal pour génération finale
10. **F10** : graphique matplotlib
11. **F12** : commande `/test journal`
