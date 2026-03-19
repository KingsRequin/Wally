# Réactions emoji contextuelles — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wally réagit avec des emoji — passivement sur les messages non-trigger (règles), et en complément de ses réponses texte (LLM via tag `[react:]`).

**Architecture:** Réaction passive via keyword matching + random dans `handle_message`. Réaction complémentaire via instruction SOUL.md + parsing regex dans `_respond`. Config probabilité dans DiscordConfig.

**Tech Stack:** Python 3.11+, pytest, discord.py 2.x, re

**Spec:** `docs/superpowers/specs/2026-03-19-emoji-reactions-design.md`

---

### Task 1: Config + helpers emoji + tests

**Files:**
- Modify: `bot/config.py` (DiscordConfig)
- Modify: `config.yaml`
- Create: `tests/test_emoji_reactions.py`
- Modify: `bot/discord/handlers.py` (ajouter fonctions helper)

- [ ] **Step 1: Créer les tests**

Créer `tests/test_emoji_reactions.py` :

```python
# tests/test_emoji_reactions.py
import re

import pytest


# ── Parse react tag ───────────────────────────────────────────────────────

def test_parse_react_tag_extracts_emoji():
    from bot.discord.handlers import _parse_react_tag
    emoji, text = _parse_react_tag("[react:😂] c'est drôle")
    assert emoji == "😂"
    assert text == "c'est drôle"


def test_parse_react_tag_no_tag():
    from bot.discord.handlers import _parse_react_tag
    emoji, text = _parse_react_tag("texte normal")
    assert emoji is None
    assert text == "texte normal"


def test_parse_react_tag_strips_whitespace():
    from bot.discord.handlers import _parse_react_tag
    emoji, text = _parse_react_tag("[react:🔥]  texte avec espaces")
    assert emoji == "🔥"
    assert text == "texte avec espaces"


def test_parse_react_tag_skull():
    from bot.discord.handlers import _parse_react_tag
    emoji, text = _parse_react_tag("[react:💀] mort de rire")
    assert emoji == "💀"
    assert text == "mort de rire"


# ── Passive reaction rules ────────────────────────────────────────────────

def test_passive_reaction_matches_laugh_keywords():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("mdr c'est trop drôle", curiosity=0.0)
    assert emoji in ("😂", "💀")


def test_passive_reaction_matches_positive_keywords():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("gg bravo c'était propre", curiosity=0.0)
    assert emoji in ("🔥", "👏")


def test_passive_reaction_matches_negative_keywords():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("putain c'est nul", curiosity=0.0)
    assert emoji in ("😤", "💀")


def test_passive_reaction_matches_curiosity_question():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("comment ça marche exactement ?", curiosity=0.5)
    assert emoji == "🤔"


def test_passive_reaction_no_signal_returns_none():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("je vais au magasin", curiosity=0.0)
    assert emoji is None


def test_passive_reaction_curiosity_below_threshold():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("c'est quoi ?", curiosity=0.2)
    assert emoji is None  # curiosity < 0.4
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `python3 -m pytest tests/test_emoji_reactions.py -v`
Expected: FAILED (fonctions n'existent pas)

- [ ] **Step 3: Ajouter le champ config**

Dans `bot/config.py`, ajouter dans `DiscordConfig` après `channel_blacklist` :

```python
emoji_reaction_probability: float = 0.05
```

Dans `config.yaml`, sous `discord:`, ajouter :

```yaml
emoji_reaction_probability: 0.05
```

- [ ] **Step 4: Implémenter les fonctions helper dans handlers.py**

Au début de `bot/discord/handlers.py`, après les imports existants, ajouter :

```python
import re as _re
```

Après la constante `TIMEOUT_REACTIONS`, ajouter :

```python
_REACT_TAG_RE = _re.compile(r"^\[react:(.+?)\]\s*")

_LAUGH_WORDS = {"mdr", "lol", "ptdr", "xd", "haha", "😂", "🤣"}
_POSITIVE_WORDS = {"gg", "bravo", "trop bien", "bien joué", "incroyable"}
_NEGATIVE_WORDS = {"merde", "putain", "nul", "chier"}

_LAUGH_EMOJIS = ("😂", "💀")
_POSITIVE_EMOJIS = ("🔥", "👏")
_NEGATIVE_EMOJIS = ("😤", "💀")


def _parse_react_tag(text: str) -> tuple[str | None, str]:
    """Parse un tag [react:emoji] au début du texte.
    Retourne (emoji, texte_nettoyé) ou (None, texte_original).
    """
    m = _REACT_TAG_RE.match(text)
    if m:
        return m.group(1), text[m.end():].strip()
    return None, text


def _pick_passive_emoji(text: str, curiosity: float) -> str | None:
    """Choisit un emoji de réaction passive basé sur le contenu du message.
    Retourne None si aucun signal détecté.
    """
    text_lower = text.lower()
    if any(w in text_lower for w in _LAUGH_WORDS):
        return random.choice(_LAUGH_EMOJIS)
    if any(w in text_lower for w in _POSITIVE_WORDS):
        return random.choice(_POSITIVE_EMOJIS)
    if any(w in text_lower for w in _NEGATIVE_WORDS):
        return random.choice(_NEGATIVE_EMOJIS)
    if curiosity >= 0.4 and "?" in text:
        return "🤔"
    return None
```

- [ ] **Step 5: Vérifier que les tests passent**

Run: `python3 -m pytest tests/test_emoji_reactions.py -v`
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add bot/config.py config.yaml bot/discord/handlers.py tests/test_emoji_reactions.py
git commit -m "feat(discord): add emoji reaction helpers and config"
```

---

### Task 2: Intégration dans handle_message + _respond

**Files:**
- Modify: `bot/discord/handlers.py` (handle_message + _respond)
- Modify: `bot/persona/SOUL.md`
- Modify: `bot/twitch/handlers.py` (strip react tag)

- [ ] **Step 1: Ajouter l'instruction [react:] dans SOUL.md**

Dans `bot/persona/SOUL.md`, ajouter après le bloc d'adaptation du registre :

```
Si le message auquel tu réponds mérite une réaction emoji en plus
de ta réponse, commence ta réponse par [react:emoji] (un seul
emoji, pas de texte dans le tag). Utilise-le quand c'est naturel
— un truc drôle, impressionnant, ou une connerie monumentale.
Ne le mets pas systématiquement, seulement quand ça ajoute
quelque chose. Si tu n'as pas de réaction, commence directement
ta réponse sans tag.
```

- [ ] **Step 2: Réaction passive dans `handle_message`**

Dans `handle_message()`, remplacer le bloc :

```python
    if not triggered:
        return
```

Par :

```python
    if not triggered:
        # Passive emoji reaction on non-trigger messages (Discord only)
        if channel_allowed and random.random() < bot.config.discord.emoji_reaction_probability:
            curiosity = bot.emotion.get_state().get("curiosity", 0.0)
            passive_emoji = _pick_passive_emoji(message.content, curiosity)
            if passive_emoji:
                try:
                    await message.add_reaction(passive_emoji)
                except Exception:
                    pass
        return
```

- [ ] **Step 3: Parsing [react:] dans `_respond`**

Dans `_respond()`, après que `reply` est obtenu (après le bloc `async with message.channel.typing():`) et AVANT le `try: await message.remove_reaction("🔍"...)`, ajouter :

```python
        # Parse optional [react:emoji] tag from LLM response
        react_emoji, reply = _parse_react_tag(reply)
```

Puis après les `remove_reaction` et AVANT `_send_in_parts`, ajouter :

```python
        if react_emoji:
            try:
                await message.add_reaction(react_emoji)
            except Exception:
                pass
```

- [ ] **Step 4: Strip react tag dans Twitch handler**

Dans `bot/twitch/handlers.py`, après que `reply` est obtenu et AVANT le truncation `if len(reply) > 480:`, ajouter :

```python
        # Strip [react:] tag (no emoji reactions on Twitch)
        if reply.startswith("[react:"):
            import re as _re
            reply = _re.sub(r"^\[react:.+?\]\s*", "", reply)
```

- [ ] **Step 5: Lancer tous les tests**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add bot/discord/handlers.py bot/persona/SOUL.md bot/twitch/handlers.py
git commit -m "feat(discord): passive emoji reactions + LLM react tag parsing"
```
