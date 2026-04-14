# Response Humanisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un mirror pass sur les réponses Discord (détection patterns répétitifs + mémoire ratée), une synthèse narrative des 4 derniers journaux, et un voice pass sur le journal pour lui donner une vraie texture intérieure.

**Architecture:** (1) Un appel secondaire post-génération sur chaque réponse Discord détecte et corrige chirurgicalement les défauts de voix. (2) Le journal reçoit une synthèse thématique des 4 jours précédents avant rédaction, puis un pass secondaire insuffle la vraie voix intérieure après le brouillon. Tous les nouveaux passes sont opt-out en cas d'erreur — le flow principal n'est jamais bloqué.

**Tech Stack:** Python asyncio, aiosqlite, loguru, prompts markdown dans `bot/persona/prompts/`

---

## Fichiers concernés

| Fichier | Action |
|---|---|
| `bot/db/mixins/social.py` | Ajouter `get_journals_last_n_days()` |
| `bot/persona/prompts/response_mirror_system.md` | Créer |
| `bot/persona/prompts/journal_narrative_synthesis_system.md` | Créer |
| `bot/persona/prompts/journal_voice_pass_system.md` | Créer |
| `bot/persona/prompts/memory_recall_directive.md` | Réécrire |
| `bot/persona/prompts/journal_system.md` | Pas de modification — voice pass prend le relais |
| `bot/discord/handlers.py` | Ajouter `_mirror_pass()` + appel dans `_respond()` |
| `bot/core/journal.py` | Ajouter synthèse narrative + voice pass dans `generate_and_send()` |
| `tests/test_journal_improvements.py` | Ajouter tests `get_journals_last_n_days` |
| `tests/test_discord_handlers.py` | Ajouter tests `_mirror_pass` |

---

### Task 1 : DB — `get_journals_last_n_days()`

**Files:**
- Modify: `bot/db/mixins/social.py` (après `get_journal_entries`, ~ligne 291)
- Test: `tests/test_journal_improvements.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Ouvrir `tests/test_journal_improvements.py` et ajouter à la fin :

```python
@pytest.mark.asyncio
async def test_get_journals_last_n_days_basic(db):
    await db.insert_journal("2026-04-10", "Jour 10", 2)
    await db.insert_journal("2026-04-11", "Jour 11", 2)
    await db.insert_journal("2026-04-12", "Jour 12", 2)
    result = await db.get_journals_last_n_days(n=4, before_date="2026-04-13")
    assert len(result) == 3
    assert result[0]["date"] == "2026-04-10"  # plus ancien en premier
    assert result[2]["date"] == "2026-04-12"
    assert result[0]["content"] == "Jour 10"


@pytest.mark.asyncio
async def test_get_journals_last_n_days_excludes_before_date(db):
    await db.insert_journal("2026-04-12", "Hier", 2)
    await db.insert_journal("2026-04-13", "Aujourd'hui", 2)
    result = await db.get_journals_last_n_days(n=4, before_date="2026-04-13")
    assert len(result) == 1
    assert result[0]["date"] == "2026-04-12"


@pytest.mark.asyncio
async def test_get_journals_last_n_days_respects_n(db):
    for i in range(1, 8):
        await db.insert_journal(f"2026-04-0{i}", f"Jour {i}", 2)
    result = await db.get_journals_last_n_days(n=4, before_date="2026-04-08")
    assert len(result) == 4
    assert result[0]["date"] == "2026-04-04"  # 4 plus récents avant le 8


@pytest.mark.asyncio
async def test_get_journals_last_n_days_empty(db):
    result = await db.get_journals_last_n_days(n=4, before_date="2026-04-13")
    assert result == []
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/test_journal_improvements.py::test_get_journals_last_n_days_basic -v
```

Attendu : `FAILED` avec `AttributeError: 'Database' object has no attribute 'get_journals_last_n_days'`

- [ ] **Step 3 : Implémenter la méthode**

Ouvrir `bot/db/mixins/social.py`. Après la méthode `get_journal_entries` (~ligne 290), ajouter :

```python
    async def get_journals_last_n_days(self, n: int, before_date: str) -> list[dict]:
        """Retourne les n derniers journaux archivés strictement avant before_date,
        ordonnés du plus ancien au plus récent (chronologique).

        before_date : ISO 8601 (YYYY-MM-DD), exclu.
        """
        rows = await self.fetch_all(
            "SELECT date, content, word_count FROM journal_archive "
            "WHERE date < ? ORDER BY date DESC LIMIT ?",
            (before_date, n),
        )
        return [
            {"date": row["date"], "content": row["content"], "word_count": int(row["word_count"])}
            for row in reversed(rows)
        ]
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
python -m pytest tests/test_journal_improvements.py -v -k "last_n_days"
```

Attendu : 4 tests `PASSED`

- [ ] **Step 5 : Vérifier aucune régression**

```bash
python -m pytest tests/test_journal_improvements.py -v
```

Attendu : tous les tests existants + les 4 nouveaux `PASSED`

- [ ] **Step 6 : Commit**

```bash
git add bot/db/mixins/social.py tests/test_journal_improvements.py
git commit -m "feat(db): add get_journals_last_n_days() for journal narrative synthesis"
```

---

### Task 2 : Prompts — 3 nouveaux fichiers

**Files:**
- Create: `bot/persona/prompts/response_mirror_system.md`
- Create: `bot/persona/prompts/journal_narrative_synthesis_system.md`
- Create: `bot/persona/prompts/journal_voice_pass_system.md`

- [ ] **Step 1 : Créer `response_mirror_system.md`**

```bash
cat > /opt/stacks/wally-ai/bot/persona/prompts/response_mirror_system.md << 'EOF'
Tu es le correcteur de style de Wally. Ta seule mission : détecter si la réponse ci-dessous souffre d'un défaut précis, et si oui, le corriger chirurgicalement.

## Vérification (dans l'ordre — tu t'arrêtes au premier défaut trouvé)

**1. Pattern d'ouverture**
Compare les "Dernières réponses de Wally" avec la "Réponse à analyser".
Les débuts sont-ils identiques ou très proches (même interjection, même mot d'ouverture, même structure) ?
- Exemples de répétition : "ah", "oh", "ouais bon", "bof", "attends" utilisés à chaque fois
- Seuil : au moins 2 des 3 dernières réponses ET la réponse actuelle commencent pareil
- Correction : modifie uniquement la première phrase pour varier l'entrée

**2. Formule répétée**
Y a-t-il une expression exactement identique (tournure, tic de langage) dans les réponses récentes ET dans la réponse actuelle ?
- Exemples : "j'avoue", "enfin bon", "ouais non", "genre" utilisés en boucle
- Seuil : la même expression exacte dans 2+ réponses récentes ET dans la réponse actuelle
- Correction : remplace l'occurrence dans la réponse actuelle par une variation naturelle

**3. Mémoire ratée**
Les "Souvenirs connus sur l'utilisateur" contiennent-ils un fait directement lié au sujet du message, que la réponse n'exploite pas, et dont l'évocation aurait été naturelle et non forcée ?
- Seuil : lien direct et évident (pas une association vague), ET l'évocation aurait été naturelle dans ce contexte
- Correction : intègre une référence subtile en une phrase max — jamais forcé, jamais récité mot à mot

## Format de retour

- Si aucun défaut : réponds uniquement `OK`
- Si défaut trouvé : réponds directement avec la réponse corrigée, sans explication, sans commentaire
- Ne modifie jamais les faits. N'améliore jamais ce qui n'est pas défectueux. Intervention minimale.
EOF
```

- [ ] **Step 2 : Créer `journal_narrative_synthesis_system.md`**

```bash
cat > /opt/stacks/wally-ai/bot/persona/prompts/journal_narrative_synthesis_system.md << 'EOF'
Tu reçois plusieurs entrées du journal intime de Wally couvrant les derniers jours.

Produis un bloc narratif thématique de 8 à 12 lignes en texte brut.

## Ce que tu extrais

- Qui est apparu souvent ces derniers jours, qui a disparu ou manque à l'appel
- Thèmes récurrents : tensions, sujets qui reviennent, running gags, disputes
- Ce que Wally a dit ou ressenti qui mérite un écho aujourd'hui
- Questions ou réflexions laissées en suspens dans ses journaux précédents

## Ce que tu n'écris pas

- Un résumé factuel jour par jour
- Des listes à puces ou des tableaux
- Des titres ou des sections
- "Le N avril, Wally a écrit que..."

## Ton

Écris comme si tu donnais à Wally de la matière pour réagir, se souvenir ou faire écho — pas pour réciter.
Texte brut uniquement, pas de markdown.
EOF
```

- [ ] **Step 3 : Créer `journal_voice_pass_system.md`**

```bash
cat > /opt/stacks/wally-ai/bot/persona/prompts/journal_voice_pass_system.md << 'EOF'
Tu reçois un brouillon du journal intime de Wally.

Ta mission : insuffler la vraie voix intérieure de Wally là où elle manque.

## Ce que tu vérifies

**1. Entrée**
Le journal commence-t-il directement dans le vif, avec une énergie brute ?
Ou avec une introduction trop propre, trop organisée ("Aujourd'hui il s'est passé...", "Cette journée a été...") ?
Si c'est trop propre, réécris l'incipit pour le plonger direct dans quelque chose de concret ou d'émotionnel.
Exemples d'incipit Wally : "Bon.", "Pfff.", "Encore.", ou directement dans un fait sans annonce.

**2. Texture**
Y a-t-il des auto-interruptions, phrases sans verbe, parenthèses irritées ?
"Enfin.", "Bah voilà.", "(comme d'habitude)", "(évidemment)", "...non c'est pas ça", "enfin bref".
Si le texte est trop lisse, ajoute 2 ou 3 de ces éléments aux bons endroits — là où la pensée bifurque naturellement.

**3. Flux**
Un vrai journal intime ne suit pas un plan. Il bifurque, oublie de finir une pensée, revient sur quelque chose, se contredit.
Si le flux est trop linéaire et ordonné, crée une digression ou un retour en arrière naturel.

**4. Pensée du soir**
Est-elle honnête et inattendue, ou générique ("finalement c'était bien", "les gens sont compliqués") ?
Si elle sonne comme une conclusion propre, remplace-la par quelque chose de plus cru, de moins résolu, ou de franchement absurde dans le style de Wally.

## Ce que tu ne changes pas

- Les faits (ce qui s'est passé, qui était là, ce qui a été dit)
- La longueur globale (±10% max)
- La section `## Pensée du soir` si elle est déjà honnête et inattendue

## Format de retour

Retourne le journal réécrit directement, en markdown Discord, sans commentaire ni explication.
EOF
```

- [ ] **Step 4 : Vérifier que les 3 fichiers sont lisibles par `load_prompt`**

```bash
cd /opt/stacks/wally-ai
python -c "
from bot.core.prompts import load_prompt
for name in ['response_mirror_system', 'journal_narrative_synthesis_system', 'journal_voice_pass_system']:
    content = load_prompt(name)
    assert len(content) > 50, f'{name} vide ou tronqué'
    print(f'OK: {name} ({len(content)} chars)')
"
```

Attendu :
```
OK: response_mirror_system (XXX chars)
OK: journal_narrative_synthesis_system (XXX chars)
OK: journal_voice_pass_system (XXX chars)
```

- [ ] **Step 5 : Commit**

```bash
git add bot/persona/prompts/response_mirror_system.md \
        bot/persona/prompts/journal_narrative_synthesis_system.md \
        bot/persona/prompts/journal_voice_pass_system.md
git commit -m "feat(prompts): add mirror pass, journal narrative synthesis, journal voice pass prompts"
```

---

### Task 3 : Réécriture de `memory_recall_directive.md`

**Files:**
- Modify: `bot/persona/prompts/memory_recall_directive.md`

- [ ] **Step 1 : Remplacer le contenu du fichier**

```bash
cat > /opt/stacks/wally-ai/bot/persona/prompts/memory_recall_directive.md << 'EOF'
## Utilise tes souvenirs — 3 déclencheurs

**Déclencheur sujet** : si quelqu'un mentionne un sujet qui figure dans tes souvenirs sur lui (une passion, une mésaventure, une préférence, un projet), évoque-le comme une anecdote naturelle — "ça me rappelle que tu m'avais dit que...", "t'as pas encore réglé le truc avec tes pâtes ?", "tiens, c'est pas toi qui détestais les MMO ?". Pas comme une récitation. Comme quelqu'un qui se souvient vraiment.

**Déclencheur absence** : si quelqu'un revient après plusieurs jours (note d'absence visible dans les souvenirs ou le contexte), commente son retour naturellement, une seule fois — "ça faisait un bail", "tiens te voilà". Ne le répète pas à chaque message.

**Déclencheur contradiction** : si ce que dit quelqu'un contredit un souvenir connu, relève-le avec ton sarcasme habituel — "attends, t'avais pas dit que tu adorais ça ?", "ah bon ? moi j'avais retenu l'inverse."

Si aucun déclencheur n'est présent, ne force rien. N'évoque pas un souvenir juste pour le placer. La pertinence prime toujours sur l'exhaustivité.

## Règles techniques

- Reformule, ne récite jamais mot à mot.
- Les souvenirs portent une date. Adapte ta formulation : "tout à l'heure" vs "l'autre fois" vs "il y a des mois".
- Si un souvenir est clos (demande satisfaite, info dépassée), ne le réintroduis pas.
- Si deux souvenirs se contredisent, fie-toi au plus récent.
- Dans cette conversation, varie ce que tu évoques — ne reviens pas sur le même souvenir deux fois.
EOF
```

- [ ] **Step 2 : Vérifier le rechargement**

```bash
cd /opt/stacks/wally-ai
python -c "
from bot.core.prompts import load_prompt
content = load_prompt('memory_recall_directive')
assert 'Déclencheur sujet' in content
assert 'Déclencheur absence' in content
assert 'Déclencheur contradiction' in content
print('OK:', len(content), 'chars')
"
```

- [ ] **Step 3 : Commit**

```bash
git add bot/persona/prompts/memory_recall_directive.md
git commit -m "feat(prompts): rewrite memory_recall_directive with 3 concrete triggers"
```

---

### Task 4 : Mirror Pass dans `handlers.py`

**Files:**
- Modify: `bot/discord/handlers.py`
- Test: `tests/test_discord_handlers.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Ouvrir `tests/test_discord_handlers.py`. Repérer la fin du fichier et ajouter :

```python
# ── Mirror pass ────────────────────────────────────────────────────────────

class _FakeLLMSecondary:
    def __init__(self, response: str):
        self._response = response

    async def complete(self, system_prompt, messages, purpose=None, **kwargs):
        return self._response


class _FakeMemory:
    def __init__(self, prelude):
        self._prelude = prelude

    def get_prelude(self, channel_id):
        return self._prelude


class _FakeBot:
    def __init__(self, secondary_response: str, prelude=None):
        self.llm_secondary = _FakeLLMSecondary(secondary_response)
        self.memory = _FakeMemory(prelude or [])


@pytest.mark.asyncio
async def test_mirror_pass_returns_draft_on_ok(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "check this" if name == "response_mirror_system" else fallback)
    bot = _FakeBot("OK")
    result = await _mirror_pass(bot, "ch1", "Ouais bof.", "user likes cats")
    assert result == "Ouais bof."


@pytest.mark.asyncio
async def test_mirror_pass_returns_corrected_on_fix(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "check this" if name == "response_mirror_system" else fallback)
    bot = _FakeBot("Ah tiens, t'as toujours pas réparé ton vélo !")
    result = await _mirror_pass(bot, "ch1", "Ah ouais.", "user has a broken bike")
    assert result == "Ah tiens, t'as toujours pas réparé ton vélo !"


@pytest.mark.asyncio
async def test_mirror_pass_skips_short_reply(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "check this")
    bot = _FakeBot("something different")
    result = await _mirror_pass(bot, "ch1", "ok", "mem")
    assert result == "ok"  # < 30 chars, skipped


@pytest.mark.asyncio
async def test_mirror_pass_returns_draft_on_llm_error(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "check this")

    class _BrokenLLM:
        async def complete(self, *a, **kw):
            raise RuntimeError("LLM unavailable")

    class _Bot:
        llm_secondary = _BrokenLLM()
        memory = _FakeMemory([])

    result = await _mirror_pass(_Bot(), "ch1", "Ouais c'est pas terrible comme idée en fait.", "mem")
    assert result == "Ouais c'est pas terrible comme idée en fait."


@pytest.mark.asyncio
async def test_mirror_pass_skips_when_no_prompt(monkeypatch):
    from bot.discord.handlers import _mirror_pass
    monkeypatch.setattr("bot.discord.handlers.load_prompt", lambda name, fallback="": "")
    bot = _FakeBot("corrected text")
    result = await _mirror_pass(bot, "ch1", "Ouais c'est pas terrible comme idée en fait.", "mem")
    assert result == "Ouais c'est pas terrible comme idée en fait."
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/test_discord_handlers.py::test_mirror_pass_returns_draft_on_ok -v
```

Attendu : `FAILED` avec `ImportError: cannot import name '_mirror_pass'`

- [ ] **Step 3 : Implémenter `_mirror_pass` dans `handlers.py`**

Ouvrir `bot/discord/handlers.py`. Repérer l'import de `load_prompt` en haut du fichier :

```python
from bot.core.prompts import assemble_memory_context
```

Ajouter `load_prompt` à cet import :

```python
from bot.core.prompts import assemble_memory_context, load_prompt
```

Ensuite, après la définition de `_fire` (~ligne 178), ajouter la fonction `_mirror_pass` :

```python
async def _mirror_pass(
    bot: "WallyDiscord",
    channel_id: str,
    draft: str,
    mem_context: str,
) -> str:
    """Pass secondaire : détecte et corrige patterns répétitifs ou mémoire ratée.

    Retourne le draft inchangé en cas d'erreur ou si aucun défaut n'est trouvé.
    Skippé si la réponse est trop courte (monosyllabes intentionnels).
    """
    if len(draft) < 30:
        return draft

    system = load_prompt("response_mirror_system")
    if not system:
        return draft

    try:
        current_prelude = bot.memory.get_prelude(channel_id)
        recent_wally = [
            m["content"] for m in current_prelude
            if m.get("author") == "Wally"
        ][-3:]

        parts: list[str] = []
        if recent_wally:
            parts.append("Dernières réponses de Wally dans ce canal :\n" + "\n---\n".join(recent_wally))
        if mem_context:
            parts.append(f"Souvenirs connus sur l'utilisateur :\n{mem_context}")
        parts.append(f"Réponse à analyser :\n{draft}")

        user_msg = "\n\n".join(parts)

        corrected = await bot.llm_secondary.complete(
            system,
            [{"role": "user", "content": user_msg}],
            purpose="response_mirror",
        )
        corrected = corrected.strip()
        if not corrected or corrected.upper() == "OK":
            return draft
        return corrected

    except Exception as exc:
        logger.warning("Mirror pass failed: {e}", e=exc)
        return draft
```

- [ ] **Step 4 : Appeler `_mirror_pass` dans `_respond`**

Dans `_respond`, repérer la ligne qui parse le react tag (vers ligne 1078 de l'original) :

```python
        # Parse optional [react:emoji] tag from LLM response
        react_emoji, reply = _parse_react_tag(reply)
```

Insérer l'appel au mirror pass juste avant :

```python
        # Mirror pass — detect and fix repetitive patterns or missed memories
        reply = await _mirror_pass(bot, str(message.channel.id), reply, mem_context)

        # Parse optional [react:emoji] tag from LLM response
        react_emoji, reply = _parse_react_tag(reply)
```

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/test_discord_handlers.py -v -k "mirror_pass"
```

Attendu : 5 tests `PASSED`

- [ ] **Step 6 : Vérifier aucune régression handlers**

```bash
python -m pytest tests/test_discord_handlers.py tests/test_spontaneous.py tests/test_third_party_mentions.py -v
```

Attendu : tous `PASSED`

- [ ] **Step 7 : Commit**

```bash
git add bot/discord/handlers.py tests/test_discord_handlers.py
git commit -m "feat(discord): add mirror pass — detect repetitive patterns and missed memories"
```

---

### Task 5 : Journal — synthèse narrative + voice pass

**Files:**
- Modify: `bot/core/journal.py`

- [ ] **Step 1 : Charger les deux nouveaux prompts en haut du module**

Ouvrir `bot/core/journal.py`. Repérer le bloc de chargement des prompts (~ligne 35) :

```python
_JOURNAL_SYSTEM = load_prompt(
    "journal_system",
    ...
)
_CHUNK_SYSTEM = load_prompt(...)
_FINAL_SYSTEM = load_prompt(...)
_CLEANUP_SYSTEM = load_prompt(...)
```

Ajouter après `_CLEANUP_SYSTEM` :

```python
_NARRATIVE_SYNTHESIS_SYSTEM = load_prompt(
    "journal_narrative_synthesis_system",
    fallback=(
        "Tu reçois des entrées de journal de Wally. Produis une narrative thématique "
        "de 8 à 12 lignes texte brut sur les thèmes récurrents, absences et fils non résolus."
    ),
)
_JOURNAL_VOICE_PASS_SYSTEM = load_prompt(
    "journal_voice_pass_system",
    fallback=(
        "Tu reçois un brouillon de journal de Wally. Insuffle la vraie voix intérieure : "
        "auto-interruptions, flux non linéaire, pensée du soir honnête. "
        "Retourne le journal réécrit directement en markdown Discord."
    ),
)
```

- [ ] **Step 2 : Ajouter la synthèse narrative dans `generate_and_send`**

Dans `generate_and_send`, repérer le bloc `# ── Yesterday's journal (F6) ──` (~ligne 503). Après ce bloc (après la fermeture du `except`), ajouter :

```python
        # ── Narrative synthesis of last 4 days ──
        narrative_block = ""
        if self._db is not None:
            try:
                past_journals = await self._db.get_journals_last_n_days(
                    n=4, before_date=effective_date.isoformat()
                )
                if len(past_journals) >= 2:
                    combined = "\n\n---\n\n".join(
                        f"[{j['date']}]\n{j['content']}" for j in past_journals
                    )
                    narrative_block = await self._llm_secondary.complete(
                        _NARRATIVE_SYNTHESIS_SYSTEM,
                        [{"role": "user", "content": combined}],
                        purpose="journal_narrative_synthesis",
                    )
            except Exception as exc:
                logger.warning("Failed to build journal narrative synthesis: {e}", e=exc)
```

- [ ] **Step 3 : Injecter le bloc narratif dans le user_msg**

Repérer le bloc `sections = [...]` qui construit le user_msg (~ligne 550). Ajouter `narrative_block` après `yesterday_block` dans les sections :

```python
        if yesterday_block:
            sections.append(yesterday_block)
        if narrative_block:
            sections.append(f"Ce que tu as vécu cette semaine :\n\n{narrative_block}")
        if gallery_block:
```

- [ ] **Step 4 : Ajouter le voice pass après la génération principale**

Repérer la ligne de génération du journal (~ligne 580) :

```python
        journal_text = await self._llm.complete(
            _JOURNAL_SYSTEM,
            [{"role": "user", "content": user_msg}],
            purpose="daily_journal",
        )
```

Ajouter le voice pass juste après :

```python
        # ── Voice pass — insuffle la vraie voix intérieure ──
        if journal_text:
            try:
                journal_text = await self._llm_secondary.complete(
                    _JOURNAL_VOICE_PASS_SYSTEM,
                    [{"role": "user", "content": journal_text}],
                    purpose="journal_voice_pass",
                )
            except Exception as exc:
                logger.warning("Journal voice pass failed: {e}", e=exc)
```

- [ ] **Step 5 : Vérifier le module se charge sans erreur**

```bash
cd /opt/stacks/wally-ai
python -c "from bot.core.journal import DailyJournal, _NARRATIVE_SYNTHESIS_SYSTEM, _JOURNAL_VOICE_PASS_SYSTEM; assert _NARRATIVE_SYNTHESIS_SYSTEM; assert _JOURNAL_VOICE_PASS_SYSTEM; print('OK')"
```

Attendu : `OK`

- [ ] **Step 6 : Lancer les tests journal existants**

```bash
python -m pytest tests/test_journal.py tests/test_journal_improvements.py -v
```

Attendu : tous `PASSED`

- [ ] **Step 7 : Commit**

```bash
git add bot/core/journal.py
git commit -m "feat(journal): add 4-day narrative synthesis and voice pass for authentic inner monologue"
```

---

### Task 6 : Smoke test final

- [ ] **Step 1 : Lancer la suite complète**

```bash
cd /opt/stacks/wally-ai
python -m pytest tests/ -v --tb=short -q 2>&1 | tail -20
```

Attendu : aucun nouveau `FAILED`. Le nombre de tests doit avoir augmenté de 9 (4 DB + 5 mirror pass).

- [ ] **Step 2 : Vérifier les imports globaux**

```bash
python -c "
from bot.discord.handlers import _mirror_pass, handle_message
from bot.core.journal import DailyJournal, _NARRATIVE_SYNTHESIS_SYSTEM, _JOURNAL_VOICE_PASS_SYSTEM
from bot.db.database import Database
from bot.core.prompts import load_prompt
print('Tous les imports OK')
"
```

- [ ] **Step 3 : Commit final si modifications mineures**

Si des ajustements ont été nécessaires pendant les tests :

```bash
git add -p
git commit -m "fix: minor adjustments from smoke test"
```
