# Journal intime plus naturel — Spec

**Date :** 2026-03-31
**Statut :** Approuvé

---

## Problème

Le journal intime de Wally est trop structuré et trop littéraire. La structure en 3 chapitres
imposés ("Les rencontres du jour", "Comment je me suis senti·e", "Pensée du soir") rend le
texte mécanique. La voix ne ressemble pas assez à Wally — trop poli, trop rapport introspectif,
pas assez "quelqu'un qui écrit pour lui-même sans se relire".

La section "Pensée du soir" fonctionne bien et est conservée.

---

## Solution

Deux changements coordonnés :

### 1. Réécriture de `bot/persona/prompts/journal_system.md`

**Suppression :** Les chapitres "Les rencontres du jour" et "Comment je me suis senti·e" disparaissent
comme sections imposées.

**Conservation :** `## Pensée du soir` reste le seul ancrage fixe, toujours en dernière position.

**Nouveaux principes de voix :**
- Ton "c'est pour moi, personne lira ça" — pas de relecture, pas de plan
- Commencer par n'importe quoi : "Bon.", "Pfff.", ou directement dans le vif
- Phrases incomplètes bienvenues : "Enfin.", "Bah voilà.", "Je sais même pas pourquoi j'écris ça."
- Auto-interruptions : "...non c'est pas ça", "enfin bref"
- Parenthèses irritées : "(comme d'habitude)", "(encore)"
- Longueur organique : si la journée était nulle → court ; si y'a des trucs → aller au bout
- Si l'arc émotionnel est plat ou absent : écrire quand même, honnêtement, sans gonfler

**Format :** Un seul bloc de texte libre, puis `## Pensée du soir` obligatoire en fin.
Le reste est un flux de conscience orienté par le contexte reçu, pas par des sections.

---

### 2. Signal de format émotionnel dans `bot/core/journal.py`

**Nouvelle fonction :** `_emotion_tone_hint(emotions: dict) -> str`

Détecte l'émotion dominante parmi les 5 (anger, joy, sadness, curiosity, boredom).
Si la valeur dépasse 0.30, retourne une directive de ton en une phrase.
Sinon retourne `""` (aucun signal).

| Émotion dominante | Directive |
|---|---|
| anger | "Ce soir ta colère domine (X%) — entrée courte, cassante, quelques lignes suffisent." |
| joy | "Ce soir tu es plutôt joyeux (X%) — tu peux te laisser aller, plus léger et spontané." |
| sadness | "Ce soir ta tristesse domine (X%) — écriture plus lente, introspective, quelques silences." |
| curiosity | "Ce soir ta curiosité domine (X%) — laisse-toi partir dans les digressions si l'envie t'en prend." |
| boredom | "Ce soir c'est l'ennui qui domine (X%) — t'as pas forcément grand chose à dire, et c'est ok. Court et honnête." |

**Injection :** Dans `generate_and_send()`, juste avant la ligne `"Écris ton journal intime pour aujourd'hui."`,
le hint est ajouté comme section `sections.append(hint)` si non vide.

---

## Fichiers modifiés

| Fichier | Changement |
|---|---|
| `bot/persona/prompts/journal_system.md` | Réécriture complète |
| `bot/core/journal.py` | Ajout `_emotion_tone_hint()` + injection dans `generate_and_send()` |

## Fichiers inchangés

- `journal_chunk_system.md` — résumé factuel, pas de voix à modifier
- `journal_final_system.md` — synthèse narrative, déjà correcte
- Structure de données / DB / callbacks — rien à toucher

---

## Ce qui ne change pas

- L'arc émotionnel, les pics, la météo comparative, le journal de la veille, la galerie,
  les visites Twitch — tout reste injecté dans le contexte, le LLM y fait référence librement
- Le formatage Markdown Discord
- La logique de summarisation multi-pass pour les longues journées
