# Design — Humanisation des réponses et du journal

**Date :** 2026-04-14
**Statut :** Approuvé

---

## Contexte et problème

Wally est déjà doté d'un système de persona riche (SOUL/IDENTITY/VOICE/EMOTIONS/WEEKDAYS/SECONDARIES/COMPOSITES), d'une mémoire long-terme (Qdrant), d'un graphe social (Graphiti/Neo4j) et d'un journal quotidien élaboré. Malgré cela, trois problèmes persistent :

**a) Patterns répétitifs dans les réponses** — Wally a tendance à répéter les mêmes structures d'ouverture, les mêmes tournures ou les mêmes blagues sur des réponses consécutives. Le LLM n'a aucun feedback loop sur ses propres habitudes dans une session.

**b) Mémoire sous-exploitée** — Wally a des souvenirs sur les utilisateurs mais les utilise de façon passive, souvent uniquement quand on lui pose une question directe. Il ne les tisse pas spontanément dans la conversation comme le ferait quelqu'un qui "connaît vraiment" les gens.

**c) Journal sans âme intérieure** — Le journal résume les faits proprement mais manque de texture humaine : pas assez d'auto-interruptions, flux trop linéaire, pas de continuité narrative entre les jours.

---

## Architecture générale

Deux axes indépendants, chacun avec son propre mécanisme secondaire.

```
RÉPONSES (problèmes A + B)
─────────────────────────
message → [build system prompt + contexte] → LLM principal → draft
                                                                 ↓
                                              LLM secondaire (mirror pass)
                                              ← dernières 3 réponses de Wally
                                              ← draft actuel
                                              ← souvenirs connus sur l'utilisateur
                                              → "OK" ou correction chirurgicale
                                                                 ↓
                                                         réponse envoyée


JOURNAL (problème C)
────────────────────
cron 21h → build contexte (existant)
         + synthèse narrative 4 derniers jours  ← NOUVEAU
         → LLM principal → brouillon
                               ↓
              LLM secondaire (voice pass)       ← NOUVEAU
              → brouillon avec vraie voix intérieure
                               ↓
                      journal archivé + envoyé
```

---

## Composant 1 — Mirror Pass (réponses)

### Déclenchement

Après chaque génération de réponse dans `handle_message`, avant l'envoi.

**Skippé si :**
- Réponse de moins de 30 caractères (monosyllabes intentionnels — ne pas corriger)
- Réponse issue d'un tool call (save_memory, etc.)
- Échec du secondaire (fallback silencieux sur le draft original)

### Input du secondaire

```
[Dernières 3 réponses de Wally dans ce canal]
[Draft actuel]
[Souvenirs connus sur l'utilisateur]
```

Les 3 dernières réponses de Wally sont extraites depuis la fenêtre de contexte existante (mémoire RAM des conversations).

### Nouveau prompt : `response_mirror_system.md`

Le secondaire vérifie **3 critères dans l'ordre**, s'arrête au premier problème trouvé :

1. **Pattern d'ouverture** — Les 3 dernières réponses et le draft commencent-ils par la même structure (même interjection, même formule) ? Si oui, réécrire uniquement la première phrase pour varier.

2. **Formule répétée** — Une expression ou tournure identique apparaît-elle dans les réponses récentes ET dans le draft ? Si oui, remplacer par une variation.

3. **Mémoire ratée** — Y a-t-il un souvenir connu sur l'utilisateur directement pertinent au message en cours, qui n'a pas été évoqué, et dont l'évocation aurait été naturelle ? Si oui, l'intégrer subtilement (une phrase max).

**Format de retour :** soit `OK` (aucune correction), soit directement le texte corrigé — aucun JSON, aucune explication.

**Règle critique :** corriger uniquement le défaut identifié. Jamais "améliorer pour améliorer". Le pass est chirurgical, pas éditorial.

### Points d'intégration

- `bot/discord/handlers.py` — après la génération du draft, avant `_parse_react_tag` et envoi
- `purpose="response_mirror"` pour le tracing Langfuse

---

## Composant 2 — Réécriture de `memory_recall_directive.md`

### Problème actuel

Le prompt actuel est trop passif : il dit à Wally qu'il *peut* utiliser ses souvenirs sans préciser *quand* ni *comment*.

### Nouvelle logique : 3 déclencheurs concrets

**Déclencheur objet/sujet** — Si la conversation mentionne un sujet qui apparaît dans les souvenirs de l'utilisateur (hobby, préférence, fait biographique), Wally y fait référence comme une anecdote naturelle. Exemple : quelqu'un parle de cuisine → "t'as toujours pas réessayé les pâtes depuis la catastrophe ?"

**Déclencheur temporel** — Si la dernière interaction de cet utilisateur date de plusieurs jours (visible dans les souvenirs), Wally commente le retour une fois, naturellement. Exemple : "tiens, ça faisait un bail."

**Déclencheur contradiction** — Si ce que dit l'utilisateur contredit un souvenir connu, Wally le relève avec son sarcasme habituel. Exemple : "attends, t'avais pas dit que tu détestais les MMO ?"

**Ce qu'on n'impose pas :** si aucun déclencheur n'est présent, Wally ne force rien. La règle "une référence subtile vaut mieux qu'un gag répété" de SOUL.md s'applique toujours.

---

## Composant 3 — Journal : fenêtre 4 jours

### Nouvelle méthode DB

`get_journals_last_n_days(n: int, before_date: str) -> list[dict]`

Retourne les `n` dernières entrées archivées dans `journals` avant `before_date`, ordonnées du plus ancien au plus récent.

### Synthèse narrative

Le secondaire reçoit les 4 derniers journaux et produit un bloc de 8-12 lignes en texte brut — pas un résumé factuel, une narrative thématique :
- Qui est apparu souvent / qui a disparu
- Thèmes récurrents (tensions, sujets qui reviennent)
- Ce que Wally avait dit/ressenti qui mérite un écho aujourd'hui
- Questions ou réflexions laissées en suspens

Ce bloc est injecté dans le contexte du journal sous le label `"Ce que tu as vécu cette semaine"`, avant le résumé de la journée.

**Skip :** si moins de 2 journaux archivés, section absente (pas d'erreur).

### Nouveau prompt : `journal_narrative_synthesis_system.md`

Instructions pour le secondaire : produire une narrative thématique en 8-12 lignes, texte brut, qui donne à Wally matière à écho, continuité et réaction — pas un compte-rendu.

### Points d'intégration

- `bot/core/journal.py` — dans `generate_and_send()`, entre la récupération des messages et la construction du user_msg
- `purpose="journal_narrative_synthesis"` pour Langfuse

---

## Composant 4 — Journal : Voice Pass

### Déclenchement

Après que le LLM principal a généré le brouillon, avant archivage et envoi.

**Skippé si :**
- Brouillon vide ou erreur de génération
- Échec du secondaire (fallback sur le brouillon principal)

### Nouveau prompt : `journal_voice_pass_system.md`

Le secondaire relit le brouillon et vérifie **uniquement la voix**, pas les faits :

1. Le journal commence-t-il directement dans le vif, ou avec une introduction trop propre ?
2. Y a-t-il des auto-interruptions, phrases sans verbe, parenthèses irritées ? Sinon, en ajouter aux bons endroits.
3. Le flux est-il trop linéaire ? Un vrai journal intime bifurque, se contredit, revient en arrière.
4. La "Pensée du soir" est-elle honnête et inattendue, ou générique ?

**Format de retour :** le journal réécrit directement. Le voice pass ne change jamais les faits — uniquement la texture de l'écriture.

### Points d'intégration

- `bot/core/journal.py` — dans `generate_and_send()`, après `journal_text = await self._llm.complete(...)`, avant `formatted = ...`
- `purpose="journal_voice_pass"` pour Langfuse

---

## Gestion d'erreur

| Composant | En cas d'échec | Logging |
|---|---|---|
| Mirror pass réponse | Envoyer le draft original | `WARNING` |
| Synthèse narrative journal | Générer sans ce bloc | `WARNING` |
| Voice pass journal | Envoyer le brouillon principal | `WARNING` |

Principe : aucun nouveau pass ne bloque le flow principal. Tout est opt-in et degradable.

---

## Fichiers à créer / modifier

| Fichier | Action |
|---|---|
| `bot/persona/prompts/response_mirror_system.md` | Créer |
| `bot/persona/prompts/journal_narrative_synthesis_system.md` | Créer |
| `bot/persona/prompts/journal_voice_pass_system.md` | Créer |
| `bot/persona/prompts/memory_recall_directive.md` | Réécrire |
| `bot/persona/prompts/journal_system.md` | Améliorer la section Voix |
| `bot/discord/handlers.py` | Ajouter mirror pass après génération |
| `bot/core/journal.py` | Ajouter synthèse narrative + voice pass |
| `bot/db/database.py` | Ajouter `get_journals_last_n_days()` |

---

## Critères de succès

- Les réponses consécutives de Wally dans un même canal varient leurs ouvertures
- Wally fait spontanément référence à des souvenirs pertinents sans qu'on lui demande
- Le journal lit comme un flux de pensées intérieur, pas un compte-rendu
- Le journal fait écho à des événements/réflexions des jours précédents
- Aucune régression sur les tests existants
- Aucun nouveau pass ne bloque le flow en cas d'erreur
