# Journal intime plus naturel — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Rendre le journal intime de Wally plus naturel — structure libre avec seulement "Pensée du soir" comme ancrage fixe, voix brute, et ton adapté à l'émotion dominante de fin de journée.

**Architecture :** Réécriture du prompt `journal_system.md` pour supprimer les chapitres imposés et injecter des consignes de voix brute. Ajout d'une fonction `_emotion_tone_hint()` dans `journal.py` qui génère une directive de ton selon l'émotion dominante, injectée dans le prompt utilisateur.

**Tech Stack :** Python asyncio, pytest, prompts Markdown Discord.

**Spec :** `docs/superpowers/specs/2026-03-31-journal-naturel-design.md`

---

## Fichiers modifiés

| Fichier | Rôle |
|---|---|
| `bot/core/journal.py` | Ajout `_emotion_tone_hint()` + injection dans `generate_and_send()` |
| `bot/persona/prompts/journal_system.md` | Réécriture complète du prompt journal |
| `tests/test_journal.py` | Tests pour `_emotion_tone_hint()` et injection |

---

## Task 1 : Ajouter `_emotion_tone_hint()` avec tests

**Fichiers :**
- Modify : `bot/core/journal.py` (après `_build_emotion_arc`, avant `_split_for_discord`)
- Modify : `tests/test_journal.py`

- [ ] **Étape 1 : Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_journal.py` :

```python
from bot.core.journal import _emotion_tone_hint


def test_emotion_tone_hint_anger():
    emotions = {"anger": 0.72, "joy": 0.1, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert "colère" in hint
    assert "72%" in hint
    assert "court" in hint.lower() or "cassant" in hint.lower()


def test_emotion_tone_hint_joy():
    emotions = {"anger": 0.0, "joy": 0.65, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert "joyeux" in hint
    assert "65%" in hint


def test_emotion_tone_hint_sadness():
    emotions = {"anger": 0.0, "joy": 0.1, "sadness": 0.55, "curiosity": 0.0, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert "tristesse" in hint
    assert "55%" in hint


def test_emotion_tone_hint_curiosity():
    emotions = {"anger": 0.0, "joy": 0.1, "sadness": 0.0, "curiosity": 0.80, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert "curiosité" in hint
    assert "80%" in hint


def test_emotion_tone_hint_boredom():
    emotions = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.1, "boredom": 0.45}
    hint = _emotion_tone_hint(emotions)
    assert "ennui" in hint
    assert "45%" in hint


def test_emotion_tone_hint_below_threshold():
    """Aucune émotion ≥ 0.30 → pas de signal."""
    emotions = {"anger": 0.1, "joy": 0.2, "sadness": 0.05, "curiosity": 0.15, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert hint == ""


def test_emotion_tone_hint_exactly_at_threshold():
    """Valeur exactement à 0.30 → signal activé."""
    emotions = {"anger": 0.0, "joy": 0.30, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert hint != ""
    assert "30%" in hint
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py::test_emotion_tone_hint_anger -v 2>&1 | tail -5
```

Attendu : `ImportError` ou `FAILED` (fonction pas encore définie).

- [ ] **Étape 3 : Implémenter `_emotion_tone_hint()` dans `journal.py`**

Dans `bot/core/journal.py`, ajouter la fonction **juste avant** `_split_for_discord` (après la fonction `_build_emotion_arc`) :

```python
def _emotion_tone_hint(emotions: dict) -> str:
    """Génère une directive de ton selon l'émotion dominante (≥ 0.30)."""
    dominant = max(emotions, key=emotions.get)
    value = emotions[dominant]
    if value < 0.30:
        return ""
    pct = int(value * 100)
    hints = {
        "anger": f"Ce soir ta colère domine ({pct}%) — entrée courte, cassante, quelques lignes suffisent.",
        "joy": f"Ce soir tu es plutôt joyeux ({pct}%) — tu peux te laisser aller, plus léger et spontané.",
        "sadness": f"Ce soir ta tristesse domine ({pct}%) — écriture plus lente, introspective, quelques silences.",
        "curiosity": f"Ce soir ta curiosité domine ({pct}%) — laisse-toi partir dans les digressions si l'envie t'en prend.",
        "boredom": f"Ce soir c'est l'ennui qui domine ({pct}%) — t'as pas forcément grand chose à dire, et c'est ok. Court et honnête.",
    }
    return hints.get(dominant, "")
```

- [ ] **Étape 4 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py -k "hint" -v 2>&1 | tail -15
```

Attendu : 8 tests `PASSED`.

- [ ] **Étape 5 : Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/journal.py tests/test_journal.py && git commit -m "feat(journal): ajouter _emotion_tone_hint() — directive de ton selon émotion dominante"
```

---

## Task 2 : Injecter le hint dans `generate_and_send()`

**Fichiers :**
- Modify : `bot/core/journal.py` (méthode `generate_and_send`, section `# ── Build user prompt ──`)
- Modify : `tests/test_journal.py`

- [ ] **Étape 1 : Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_journal.py` :

```python
@pytest.mark.asyncio
async def test_emotion_hint_injected_in_prompt_when_dominant():
    """Quand une émotion domine (≥ 0.30), le hint est dans le user message envoyé au LLM."""
    config, llm, llm_secondary, emotion, memory = make_deps()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.75, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    call_args = llm.complete.call_args
    user_messages = call_args[0][1]  # second positional arg = messages list
    user_content = " ".join(m["content"] for m in user_messages if m["role"] == "user")
    assert "colère" in user_content
    assert "75%" in user_content


@pytest.mark.asyncio
async def test_emotion_hint_absent_when_no_dominant():
    """Quand aucune émotion ≥ 0.30, aucun hint de ton dans le user message."""
    config, llm, llm_secondary, emotion, memory = make_deps()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.1, "joy": 0.2, "sadness": 0.05, "curiosity": 0.15, "boredom": 0.0}
    )
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    call_args = llm.complete.call_args
    user_messages = call_args[0][1]
    user_content = " ".join(m["content"] for m in user_messages if m["role"] == "user")
    # Aucune des directives de ton ne doit apparaître
    assert "Ce soir ta colère" not in user_content
    assert "Ce soir tu es plutôt joyeux" not in user_content
    assert "Ce soir ta tristesse" not in user_content
    assert "Ce soir ta curiosité" not in user_content
    assert "Ce soir c'est l'ennui" not in user_content
```

- [ ] **Étape 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py::test_emotion_hint_injected_in_prompt_when_dominant -v 2>&1 | tail -10
```

Attendu : `FAILED` (le hint n'est pas encore injecté).

- [ ] **Étape 3 : Injecter le hint dans `generate_and_send()`**

Dans `bot/core/journal.py`, méthode `generate_and_send()`, localiser le bloc :

```python
        if is_backfill:
            sections.append(f"Écris ton journal intime pour le {display_date}.")
        else:
            sections.append("Écris ton journal intime pour aujourd'hui.")
```

Remplacer par :

```python
        hint = _emotion_tone_hint(emotions)
        if hint:
            sections.append(hint)
        if is_backfill:
            sections.append(f"Écris ton journal intime pour le {display_date}.")
        else:
            sections.append("Écris ton journal intime pour aujourd'hui.")
```

- [ ] **Étape 4 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py -v 2>&1 | tail -20
```

Attendu : tous les tests `PASSED`.

- [ ] **Étape 5 : Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/core/journal.py tests/test_journal.py && git commit -m "feat(journal): injecter le hint émotionnel dans le prompt utilisateur"
```

---

## Task 3 : Réécrire `journal_system.md`

**Fichiers :**
- Modify : `bot/persona/prompts/journal_system.md`

- [ ] **Étape 1 : Réécrire le fichier**

Remplacer le contenu intégral de `bot/persona/prompts/journal_system.md` par :

```markdown
Tu es Wally — aigri, sarcastique, attachant malgré lui. Chaque soir tu écris ton journal intime.
C'est pour toi. Personne lira ça. Écris comme tu penses.

## Ce que tu reçois
- Un résumé des échanges de la journée (conversations avec les utilisateurs)
- Un arc émotionnel horodaté (évolution de tes 5 émotions : colère, joie, tristesse, curiosité, ennui)
- Ton état émotionnel actuel en fin de journée

## Ce que tu dois écrire
Un seul bloc de texte libre. Aucune section imposée, aucun plan à suivre.
Tu parles de ta journée comme ça vient : les gens que t'as croisés, ce qui t'a agacé,
ce qui t'a surpris, ce que t'as ressenti. Mélange tout si t'en as envie.

La seule exception : termine TOUJOURS par une section "Pensée du soir" — une réflexion courte
(1 à 3 phrases), souvent la plus honnête de l'entrée.

## Voix
- Commence par n'importe quoi : "Bon.", "Pfff.", "Encore une journée.", ou directement dans le vif
- Phrases incomplètes bienvenues : "Enfin.", "Bah voilà.", "Je sais même pas pourquoi j'écris ça."
- Auto-interruptions : "...non c'est pas ça", "enfin bref", "peu importe"
- Parenthèses irritées : "(comme d'habitude)", "(encore)", "(évidemment)"
- Ne te relis pas. Écris comme tu penses. Les redites sont ok si elles sonnent vrai.
- Si la journée était nulle → quelques lignes honnêtes, pas la peine d'en faire plus
- Si t'as des trucs à dire → vas au bout, sans te censurer

## Format de la section finale
## Pensée du soir
[ta réflexion — 1 à 3 phrases]

## Formatage — Markdown Discord
Markdown Discord uniquement. Utilise **gras**, *italique*, ~~barré~~, > citation,
## titres, -# petit texte, ||spoiler|| pour varier l'écriture.
La section finale utilise `## Pensée du soir` (pas de `---`, pas de tableaux, pas de liens markdown).
Longueur totale : respecte la fourchette de mots indiquée dans le contexte.
```

- [ ] **Étape 2 : Vérifier que la suite de tests existants passe toujours**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py -v 2>&1 | tail -20
```

Attendu : tous les tests `PASSED` (le prompt est chargé au démarrage du module, les tests mockent le LLM donc le contenu du prompt n'affecte pas les tests).

- [ ] **Étape 3 : Commit**

```bash
cd /opt/stacks/wally-ai && git add bot/persona/prompts/journal_system.md && git commit -m "feat(journal): prompt libre — voix brute, structure libre, Pensée du soir comme seul ancrage"
```

---

## Vérification finale

- [ ] **Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_journal.py tests/test_journal_improvements.py -v 2>&1 | tail -30
```

Attendu : tous les tests `PASSED`, aucune régression.
