# Paramétrisation multi-instance de Wally — Plan d'implémentation (SP1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre l'identité du bot (nom, créateur, owner Discord) et la self-modification entièrement configurables via `config.yaml`, sans changer le comportement de Wally.

**Architecture:** Section `bot:` étendue dans `config.yaml`. Un module `identity.py` (état posé une fois au boot) rend les **prompts** via sentinelles `{{BOT_NAME}}`/`{{CREATOR_NAME}}`/`{{OWNER_ID}}`. Le code **runtime** (owner ACL, étiquettes) lit directement l'objet `config` déjà accessible. La self-modif est gardée par un flag.

**Tech Stack:** Python 3.11, asyncio, dataclasses, FastAPI, pytest, JS vanilla.

## Global Constraints

- Logging : `loguru` uniquement, jamais `print`/`logging`.
- **Aucun changement de comportement pour Wally** : son `config.yaml` garde ses valeurs actuelles (name=Wally, creator=KingsRequin, owner=610550333042589752, self_modify=true).
- Sentinelles de prompt : `{{BOT_NAME}}`, `{{CREATOR_NAME}}`, `{{OWNER_ID}}` — **jamais** `str.format` sur un prompt (JSON `{...}` présent).
- `self_modify_enabled` défaut `False` ; owner vide ⇒ fonctions créateur désactivées proprement.
- Deux dossiers de prompts : `bot/persona/prompts/` (bind-mount Cindy) **et** `bot/intelligence/persona/prompts/` (image). Traiter les deux.
- Miroir obligatoire : toute modif de `bot/dashboard/static/public-starter/` → recopier dans `public-ui/`.
- Baseline tests : `pytest -q` ≈ 1010 verts, 2 échecs préexistants (spam + cost) tolérés.
- Commits fréquents, un par tâche.

---

## Phase 1 — Couche config + helper identité

### Task 1 : Étendre `BotConfig` + `config.yaml`

**Files:**
- Modify: `bot/config.py` (dataclass `BotConfig`, lignes 8-43)
- Modify: `config.yaml` (section `bot:`)
- Test: `tests/test_config_bot_identity.py` (créer)

**Interfaces:**
- Produces: `BotConfig.name: str`, `BotConfig.creator_name: str`, `BotConfig.owner_discord_id: str`, `BotConfig.self_modify_enabled: bool` (tous avec défauts).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_config_bot_identity.py
from bot.config import BotConfig, Config

def test_botconfig_identity_defaults():
    c = BotConfig(
        trigger_names=["wally"], language_default="fr",
        context_window_size=20, context_token_threshold=3000,
        journal_time="21:00",
    )
    assert c.name == "Wally"
    assert c.creator_name == "KingsRequin"
    assert c.owner_discord_id == ""
    assert c.self_modify_enabled is False

def test_config_load_save_roundtrip_identity(tmp_path):
    import yaml
    src = "config.yaml"
    raw = yaml.safe_load(open(src, encoding="utf-8"))
    raw["bot"]["name"] = "Cindy"
    raw["bot"]["owner_discord_id"] = "123"
    raw["bot"]["self_modify_enabled"] = False
    p = tmp_path / "c.yaml"
    yaml.safe_dump(raw, open(p, "w", encoding="utf-8"))
    cfg = Config.load(str(p))
    assert cfg.bot.name == "Cindy"
    assert cfg.bot.owner_discord_id == "123"
    assert cfg.bot.self_modify_enabled is False
```

- [ ] **Step 2 : Lancer le test (échoue)**

Run: `pytest tests/test_config_bot_identity.py -v`
Expected: FAIL (`name` n'existe pas sur BotConfig, ou `Config.load` signature).
> Vérifier d'abord la signature réelle de `Config.load` (chemin positionnel vs défaut) et adapter l'appel `Config.load(str(p))` si besoin.

- [ ] **Step 3 : Ajouter les 4 champs à `BotConfig`**

Dans `bot/config.py`, à la fin de la dataclass `BotConfig` (après `update_image`, ligne ~34) :

```python
    # --- identité multi-instance ---
    name: str = "Wally"
    creator_name: str = "KingsRequin"
    owner_discord_id: str = ""
    self_modify_enabled: bool = False
```

- [ ] **Step 4 : Renseigner `config.yaml`** (section `bot:`)

```yaml
bot:
  # ... clés existantes ...
  name: Wally
  creator_name: KingsRequin
  owner_discord_id: '610550333042589752'
  self_modify_enabled: true
```

- [ ] **Step 5 : Lancer le test (passe)**

Run: `pytest tests/test_config_bot_identity.py -v`
Expected: PASS

- [ ] **Step 6 : Non-régression config**

Run: `pytest tests/ -k config -q`
Expected: pas de nouvelle régression.

- [ ] **Step 7 : Commit**

```bash
git add bot/config.py config.yaml tests/test_config_bot_identity.py
git commit -m "feat(config): champs identité multi-instance (name/creator/owner/self_modify)"
```

---

### Task 2 : Module `identity.py` (set + render)

**Files:**
- Create: `bot/intelligence/identity.py`
- Test: `tests/intelligence/test_identity.py` (créer)

**Interfaces:**
- Produces: `set_identity(cfg) -> None`, `render_identity(text: str) -> str`, `bot_name() -> str`, `owner_id() -> str`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/intelligence/test_identity.py
from bot.intelligence import identity
from bot.config import BotConfig

def _cfg(**kw):
    base = dict(trigger_names=["x"], language_default="fr",
                context_window_size=20, context_token_threshold=3000,
                journal_time="21:00")
    base.update(kw)
    return BotConfig(**base)

def test_render_replaces_sentinels():
    identity.set_identity(_cfg(name="Cindy", creator_name="Bob", owner_discord_id="42"))
    out = identity.render_identity("Tu es {{BOT_NAME}}, créé par {{CREATOR_NAME}} ({{OWNER_ID}}).")
    assert out == "Tu es Cindy, créé par Bob (42)."

def test_render_leaves_json_braces_intact():
    identity.set_identity(_cfg(name="Cindy"))
    out = identity.render_identity('Réponds {"user_id": "x"} pour {{BOT_NAME}}.')
    assert '{"user_id": "x"}' in out
    assert "Cindy" in out

def test_defaults_before_set(monkeypatch):
    monkeypatch.setattr(identity, "_NAME", "Wally")
    assert "Wally" in identity.render_identity("{{BOT_NAME}}")
```

- [ ] **Step 2 : Lancer le test (échoue)**

Run: `pytest tests/intelligence/test_identity.py -v`
Expected: FAIL (`No module named bot.intelligence.identity`)

- [ ] **Step 3 : Créer `bot/intelligence/identity.py`**

```python
# bot/intelligence/identity.py
"""Identité d'instance (nom, créateur, owner) injectée dans les prompts.

Posée une seule fois au démarrage via set_identity(), puis render_identity()
remplace les sentinelles {{BOT_NAME}} / {{CREATOR_NAME}} / {{OWNER_ID}} dans
les templates de prompt. On évite str.format : les prompts contiennent du JSON
littéral ({...}) qui casserait.
"""
from __future__ import annotations

_NAME: str = "Wally"
_CREATOR: str = "KingsRequin"
_OWNER: str = ""


def set_identity(cfg) -> None:
    """Pose l'identité depuis un BotConfig. Appelé 1× au boot après Config.load."""
    global _NAME, _CREATOR, _OWNER
    _NAME = (getattr(cfg, "name", "") or "Wally")
    _CREATOR = (getattr(cfg, "creator_name", "") or "KingsRequin")
    _OWNER = (getattr(cfg, "owner_discord_id", "") or "")


def bot_name() -> str:
    return _NAME


def owner_id() -> str:
    return _OWNER


def render_identity(text: str) -> str:
    return (text
            .replace("{{BOT_NAME}}", _NAME)
            .replace("{{CREATOR_NAME}}", _CREATOR)
            .replace("{{OWNER_ID}}", _OWNER))
```

- [ ] **Step 4 : Lancer le test (passe)**

Run: `pytest tests/intelligence/test_identity.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/identity.py tests/intelligence/test_identity.py
git commit -m "feat(identity): module set_identity/render_identity (sentinelles prompt)"
```

---

### Task 3 : Poser `set_identity` au démarrage

**Files:**
- Modify: `bot/main.py` (après `Config.load()`)
- Test: `tests/test_main_set_identity.py` (créer, léger)

**Interfaces:**
- Consumes: `identity.set_identity` (Task 2), `Config.load` (Task 1).

- [ ] **Step 1 : Localiser l'appel `Config.load()` dans `main.py`**

Run: `grep -n "Config.load\|config =" bot/main.py`
> Repérer la variable `config` résultante (ex: `config = Config.load(...)`).

- [ ] **Step 2 : Écrire le test qui échoue**

```python
# tests/test_main_set_identity.py
import bot.intelligence.identity as identity
from bot.config import BotConfig

def test_set_identity_applies(monkeypatch):
    cfg = BotConfig(trigger_names=["x"], language_default="fr",
                    context_window_size=20, context_token_threshold=3000,
                    journal_time="21:00", name="Cindy")
    identity.set_identity(cfg)
    assert identity.bot_name() == "Cindy"
```

- [ ] **Step 3 : Lancer (passe déjà — vérifie juste le contrat de Task 2)**

Run: `pytest tests/test_main_set_identity.py -v`
Expected: PASS

- [ ] **Step 4 : Câbler dans `main.py`**

Juste après la ligne `config = Config.load(...)` :

```python
    from bot.intelligence import identity as _identity
    _identity.set_identity(config.bot)
```

- [ ] **Step 5 : Vérifier l'import (smoke)**

Run: `python -c "import bot.main"`
Expected: pas d'ImportError.

- [ ] **Step 6 : Commit**

```bash
git add bot/main.py tests/test_main_set_identity.py
git commit -m "feat(identity): pose set_identity(config.bot) au démarrage"
```

---

## Phase 2 — Owner ID backend + garde self-modif

### Task 4 : `self_fix.py` — owner via config + garde + prompt rendu

**Files:**
- Modify: `bot/intelligence/self_fix.py` (lignes 9, 19, 74, 211, 219)
- Test: `tests/intelligence/core/test_self_fix.py` (existant — adapter)

**Interfaces:**
- Consumes: `self._bot.config.bot.owner_discord_id`, `identity.render_identity` (Task 2).

- [ ] **Step 1 : Lire l'état du test existant**

Run: `grep -n "OWNER_ID\|owner\|config\|fetch_user" tests/intelligence/core/test_self_fix.py | head`
> Le test fixe `OWNER_ID = "610550333042589752"` et `user.id = 610550333042589752`. Il faudra que le mock `bot` expose `bot.config.bot.owner_discord_id`.

- [ ] **Step 2 : Écrire/adapter le test (échoue)**

Ajouter un helper qui équipe le mock bot d'un config :
```python
def _equip_owner(bot, owner="610550333042589752"):
    import types
    bot.config = types.SimpleNamespace(bot=types.SimpleNamespace(owner_discord_id=owner))
    return bot
```
Adapter les tests existants pour appeler `_equip_owner(bot)` avant les assertions qui touchent l'owner, et garder `OWNER_ID = "610550333042589752"`.

Run: `pytest tests/intelligence/core/test_self_fix.py -v`
Expected: FAIL (le code lit encore la constante module, pas `self._bot.config`).

- [ ] **Step 3 : Modifier `self_fix.py`**

Remplacer la constante (ligne 9) par un helper lisant le bot, et remplacer chaque usage :

```python
# supprimer:  OWNER_DISCORD_ID = "610550333042589752"
# ajouter (haut du module):
from bot.intelligence.identity import render_identity

# dans la classe, ajouter:
    def _owner_id(self) -> str:
        cfg = getattr(self._bot, "config", None)
        return getattr(getattr(cfg, "bot", None), "owner_discord_id", "") or ""
```

Usages :
- ligne 74 : `owner = await self._bot.fetch_user(int(self._owner_id()))` (gardé : si `not self._owner_id(): return`).
- ligne 211 (`_notify`) : idem, early-return si owner vide.
- ligne 219 (`_await_reaction.check`) : `str(user.id) == self._owner_id()`.
- ligne 19 (cadrage prompt) : `"Wally"` → `"{{BOT_NAME}}"` dans la constante, puis envelopper le prompt final envoyé au LLM par `render_identity(...)` à son point d'usage.

- [ ] **Step 4 : Lancer (passe)**

Run: `pytest tests/intelligence/core/test_self_fix.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/self_fix.py tests/intelligence/core/test_self_fix.py
git commit -m "refactor(self_fix): owner via config.bot + nom via sentinelle"
```

---

### Task 5 : `self_upgrade.py` — owner via config

**Files:**
- Modify: `bot/intelligence/self_upgrade.py` (lignes 7, 36, 65)
- Test: `tests/intelligence/core/test_self_upgrade.py` (existant — adapter)

**Interfaces:**
- Consumes: `self._bot.config.bot.owner_discord_id`.

- [ ] **Step 1 : Adapter le test (échoue)**

Équiper le mock `bot` avec `bot.config.bot.owner_discord_id="610550333042589752"` (même helper qu'en Task 4).
Run: `pytest tests/intelligence/core/test_self_upgrade.py -v`
Expected: FAIL.

- [ ] **Step 2 : Modifier `self_upgrade.py`**

```python
# supprimer: OWNER_DISCORD_ID = "610550333042589752"
# ajouter dans la classe:
    def _owner_id(self) -> str:
        cfg = getattr(self._bot, "config", None)
        return getattr(getattr(cfg, "bot", None), "owner_discord_id", "") or ""
```
- ligne 36 (`_propose`) : `if not self._owner_id(): return` puis `fetch_user(int(self._owner_id()))`.
- ligne 65 (`check`) : `str(user.id) == self._owner_id()`.

- [ ] **Step 3 : Lancer (passe)**

Run: `pytest tests/intelligence/core/test_self_upgrade.py -v`
Expected: PASS

- [ ] **Step 4 : Commit**

```bash
git add bot/intelligence/self_upgrade.py tests/intelligence/core/test_self_upgrade.py
git commit -m "refactor(self_upgrade): owner via config.bot"
```

---

### Task 6 : `action_dispatcher.py` — owner + étiquettes nom

**Files:**
- Modify: `bot/intelligence/action_dispatcher.py` (lignes 107, 123, 124, 171)
- Test: `tests/intelligence/core/test_action_dispatcher.py` (existant — adapter)

**Interfaces:**
- Consumes: `self._bot.config.bot.owner_discord_id`, `self._bot.config.bot.name`.

- [ ] **Step 1 : Adapter le test (échoue)**

Le test (`OWNER_ID = "610550333042589752"`) doit équiper `bot.config.bot.owner_discord_id` + `bot.config.bot.name="Wally"`.
Run: `pytest tests/intelligence/core/test_action_dispatcher.py -v`
Expected: FAIL.

- [ ] **Step 2 : Modifier `action_dispatcher.py`**

Ajouter deux helpers :
```python
    def _owner_id(self) -> str:
        for b in (self._bot, self._twitch_bot):
            cfg = getattr(b, "config", None)
            oid = getattr(getattr(cfg, "bot", None), "owner_discord_id", "")
            if oid:
                return oid
        return ""

    def _self_name(self) -> str:
        for b in (self._bot, self._twitch_bot):
            cfg = getattr(b, "config", None)
            nm = getattr(getattr(cfg, "bot", None), "name", "")
            if nm:
                return nm
        return "Wally"
```
- ligne 171 : `owner_id = self._owner_id()` ; si vide → `logger.warning("DM impossible: owner non configuré"); return`.
- lignes 107, 123, 124 : `author="Wally"` → `author=self._self_name()`.

- [ ] **Step 3 : Lancer (passe)**

Run: `pytest tests/intelligence/core/test_action_dispatcher.py -v`
Expected: PASS

- [ ] **Step 4 : Commit**

```bash
git add bot/intelligence/action_dispatcher.py tests/intelligence/core/test_action_dispatcher.py
git commit -m "refactor(action_dispatcher): owner + étiquettes nom via config.bot"
```

---

### Task 7 : `chat_auth.py` — owner via app state

**Files:**
- Modify: `bot/dashboard/routes/chat_auth.py` (lignes 21, 232)
- Test: `tests/dashboard/test_chat_auth_owner.py` (créer)

**Interfaces:**
- Consumes: `request.app.state.wally.config.bot.owner_discord_id`.

- [ ] **Step 1 : Écrire le test (échoue)**

Tester que `admin-token` refuse un `discord_id` ≠ owner et accepte l'owner, avec `app.state.wally.config.bot.owner_discord_id` mocké. (S'aligner sur les patterns de tests dashboard existants ; si aucun n'existe pour cette route, tester la fonction de garde extraite.)
Run: `pytest tests/dashboard/test_chat_auth_owner.py -v`
Expected: FAIL.

- [ ] **Step 2 : Modifier `chat_auth.py`**

- Supprimer `OWNER_DISCORD_ID = "610550333042589752"` (ligne 21).
- Ligne 232 : `owner = request.app.state.wally.config.bot.owner_discord_id` puis
  `if not owner or str(payload.get("discord_id")) != owner: <refus 403>`.

- [ ] **Step 3 : Lancer (passe)**

Run: `pytest tests/dashboard/test_chat_auth_owner.py -v`
Expected: PASS

- [ ] **Step 4 : Commit**

```bash
git add bot/dashboard/routes/chat_auth.py tests/dashboard/test_chat_auth_owner.py
git commit -m "refactor(chat_auth): owner via app.state.config.bot"
```

---

### Task 8 : Garde `self_modify_enabled` au câblage

**Files:**
- Modify: `bot/discord/bot.py` (lignes 183-190)
- Test: `tests/discord/test_self_modify_gate.py` (créer)

**Interfaces:**
- Consumes: `self.config.bot.self_modify_enabled`, `self.config.bot.owner_discord_id`.

- [ ] **Step 1 : Écrire le test (échoue)**

Vérifier que `self.self_fix`/`self.self_upgrade` restent absents (ou None) quand `config.bot.self_modify_enabled=False`, et présents quand `True` (avec socket/secret/cognitive_loop mockés). Extraire si besoin la condition dans une petite fonction testable.
Run: `pytest tests/discord/test_self_modify_gate.py -v`
Expected: FAIL.

- [ ] **Step 2 : Modifier la condition (`bot/discord/bot.py:185`)**

```python
        if (_bridge_socket and _bridge_secret and self.cognitive_loop is not None
                and self.config.bot.self_modify_enabled
                and self.config.bot.owner_discord_id):
            _bridge = HostBridgeClient(_bridge_socket, _bridge_secret)
            self.self_fix = SelfFix(_bridge, self)
            ...
```

- [ ] **Step 3 : Lancer (passe)**

Run: `pytest tests/discord/test_self_modify_gate.py -v`
Expected: PASS

- [ ] **Step 4 : Commit**

```bash
git add bot/discord/bot.py tests/discord/test_self_modify_gate.py
git commit -m "feat(self_modify): garde self_modify_enabled + owner au câblage"
```

---

## Phase 3 — Prompts (les deux dossiers) + journal

### Task 9 : `bot/persona/prompts/*.md` (15) + rendu aux sites `load_prompt`

**Files:**
- Modify: 15 fichiers `bot/persona/prompts/*.md`
- Modify: sites d'appel `load_prompt(...)` (journal.py, fact_extractor.py, et autres consommateurs)
- Test: `tests/intelligence/test_prompt_identity_render.py` (créer)

**Interfaces:**
- Consumes: `identity.render_identity` (Task 2).

- [ ] **Step 1 : Lister les fichiers + consommateurs**

Run: `grep -rli wally bot/persona/prompts/`
Run: `grep -rn "load_prompt(" bot/ --include=*.py`
> Pour chaque consommateur, le rendu s'applique au moment où le prompt part au LLM.

- [ ] **Step 2 : Écrire le test (échoue)**

```python
# tests/intelligence/test_prompt_identity_render.py
from bot.intelligence import identity
from bot.intelligence.prompts import load_prompt

def test_persona_prompts_use_sentinel_not_literal():
    import pathlib, glob
    for f in glob.glob("bot/persona/prompts/*.md"):
        txt = pathlib.Path(f).read_text(encoding="utf-8")
        assert "Wally" not in txt, f"{f} contient encore 'Wally' littéral"

def test_loaded_prompt_renders_to_name():
    identity.set_identity_NAME = None  # garde-fou
```
> Adapter la 2e assertion à un prompt précis une fois les sentinelles posées.

- [ ] **Step 3 : Remplacer dans les 15 `.md`**

Pour chaque fichier : `Wally` → `{{BOT_NAME}}` (vérifier le sens — c'est toujours le nom du bot dans ces prompts).
Run de vérif : `grep -rl "Wally" bot/persona/prompts/` doit être vide.

- [ ] **Step 4 : Envelopper les sites d'usage**

À chaque endroit qui envoie un de ces prompts au LLM, appliquer `render_identity(prompt)` (cf. Task 11 pour journal). Pour les autres consommateurs (fact_extractor, image, session, response_mirror, memory_*) : importer `render_identity` et l'appliquer sur la string système juste avant `complete(...)`.

- [ ] **Step 5 : Lancer (passe) + non-régression**

Run: `pytest tests/intelligence/test_prompt_identity_render.py tests/ -k "fact or journal or memory or prompt" -q`
Expected: PASS / pas de régression.

- [ ] **Step 6 : Commit**

```bash
git add bot/persona/prompts/ bot/intelligence/ tests/intelligence/test_prompt_identity_render.py
git commit -m "refactor(prompts): persona/prompts → sentinelle {{BOT_NAME}} + rendu"
```

---

### Task 10 : `bot/intelligence/persona/prompts/*.md` (V2) + rendu à la construction

**Files:**
- Modify: `gate_system.md`, `reasoning_system.md`, `meta_agent_system.md`, `inner_monologue_system.md`, `memory_arbiter.md`, `memory_extract.md`
- Modify: loaders (`gate.py:_load_system`, `reasoning_agent.py:68`, et les composants chargeant les autres)
- Test: étendre `tests/intelligence/test_prompt_identity_render.py`

**Interfaces:**
- Consumes: `identity.render_identity` (Task 2). Dépend de `set_identity` posé avant construction (Task 3).

- [ ] **Step 1 : Remplacer sentinelles dans les 6 `.md`**

- `Wally` → `{{BOT_NAME}}` (partout)
- `KingsRequin` → `{{CREATOR_NAME}}` (reasoning_system.md)
- `610550333042589752` → `{{OWNER_ID}}` (reasoning_system.md ligne ~89)

Vérif : `grep -rlE "Wally|KingsRequin|610550333042589752" bot/intelligence/persona/prompts/` doit être vide.

- [ ] **Step 2 : Envelopper le chargement par `render_identity`**

- `bot/intelligence/reasoning_agent.py:68` :
  `self._system = render_identity((Path(prompts_dir) / "reasoning_system.md").read_text(encoding="utf-8"))`
- `bot/intelligence/gate.py:_load_system` : appliquer `render_identity(...)` sur le texte chargé.
- Idem pour `inner_monologue`, `meta_agent`, `memory_arbiter`, `memory_extract` à leur point de chargement (les localiser : `grep -rn "memory_arbiter\|memory_extract\|inner_monologue_system\|meta_agent_system" bot/intelligence/*.py`).
- Importer `from bot.intelligence.identity import render_identity` dans chaque module concerné.

- [ ] **Step 3 : Test (échoue puis passe)**

Étendre le test pour scanner aussi `bot/intelligence/persona/prompts/*.md` (aucun littéral `Wally`/`KingsRequin`/owner).
Run: `pytest tests/intelligence/test_prompt_identity_render.py -v`

- [ ] **Step 4 : Non-régression cognitive**

Run: `pytest tests/ -k "gate or reasoning or monologue or meta or memory" -q`
Expected: pas de régression.

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/persona/prompts/ bot/intelligence/*.py tests/intelligence/test_prompt_identity_render.py
git commit -m "refactor(prompts V2): gate/reasoning/... → sentinelles + rendu à la construction"
```

---

### Task 11 : `journal.py` — fallbacks + f-strings nom

**Files:**
- Modify: `bot/intelligence/journal.py` (lignes 35-79 fallbacks, 529/636/647 usages, 553, 599-605)
- Test: `tests/test_journal_identity.py` (créer ou étendre un test journal existant)

**Interfaces:**
- Consumes: `identity.render_identity`, `self._config.bot.name`.

- [ ] **Step 1 : Test (échoue)**

Vérifier que `_form_opinions`/`generate_and_send` produisent un system prompt contenant le nom configuré (mock `set_identity(name="Cindy")` + `self._config.bot.name="Cindy"`), pas « Wally ».
Run: `pytest tests/test_journal_identity.py -v`
Expected: FAIL.

- [ ] **Step 2 : Modifier `journal.py`**

- Fallbacks (35-79) : `Wally` → `{{BOT_NAME}}`.
- Sites d'usage (529, 636, 647) : envelopper la constante par `render_identity(...)`, ex :
  `await self._llm.complete(render_identity(_JOURNAL_SYSTEM), ...)`.
- Ligne 553 : `f"# Journal de {self._config.bot.name} — {display_date}\n\n{journal_text}"`.
- Lignes 599-605 (`_form_opinions`) : remplacer les 2 « Wally » par `{self._config.bot.name}` (f-string).
- Importer `from bot.intelligence.identity import render_identity`.

- [ ] **Step 3 : Lancer (passe)**

Run: `pytest tests/test_journal_identity.py tests/ -k journal -q`
Expected: PASS

- [ ] **Step 4 : Commit**

```bash
git add bot/intelligence/journal.py tests/test_journal_identity.py
git commit -m "refactor(journal): nom via config.bot.name + render_identity"
```

---

## Phase 4 — Étiquettes runtime Twitch + mood

### Task 12 : `twitch/handlers.py` — étiquettes mémoire

**Files:**
- Modify: `bot/twitch/handlers.py` (412, 422, 423, 560, 561, 642, 643)
- Test: `tests/twitch/test_handlers_author_name.py` (créer ou étendre un test twitch existant)

**Interfaces:**
- Consumes: `bot.config.bot.name`.

- [ ] **Step 1 : Test (échoue)**

Avec un `bot` mock dont `bot.config.bot.name="Cindy"`, vérifier qu'un message sortant est étiqueté `"Cindy"` dans `append_prelude`/`append_message` (mock memory, asserter l'arg author).
Run: `pytest tests/twitch/test_handlers_author_name.py -v`
Expected: FAIL.

- [ ] **Step 2 : Modifier `handlers.py`**

Remplacer chaque `author="Wally"` et `append_prelude/append_message(channel_id, "Wally", ...)` par `bot.config.bot.name`. Définir une variable locale en tête de fonction : `self_name = bot.config.bot.name`.

- [ ] **Step 3 : Lancer (passe)**

Run: `pytest tests/twitch/test_handlers_author_name.py tests/ -k twitch -q`
Expected: PASS

- [ ] **Step 4 : Commit**

```bash
git add bot/twitch/handlers.py tests/twitch/test_handlers_author_name.py
git commit -m "refactor(twitch): étiquettes mémoire via config.bot.name"
```

---

### Task 13 : `twitch/bot.py` visit summary + `commands/mood.py`

**Files:**
- Modify: `bot/twitch/bot.py` (318-323)
- Modify: `bot/twitch/commands/mood.py` (19)
- Test: étendre `tests/twitch/test_handlers_author_name.py` ou un test mood existant

**Interfaces:**
- Consumes: `render_identity` (visit summary), `bot.config.bot.name` (mood).

- [ ] **Step 1 : Test (échoue)**

Tester `handle_mood_command` : avec `bot.config.bot.name="Cindy"`, le texte envoyé commence par `"Humeur de Cindy —"` (mock `bot.send`/IRC).
Run: `pytest tests/twitch/ -k mood -v`
Expected: FAIL.

- [ ] **Step 2 : Modifier**

- `commands/mood.py:19` : `mood_text = f"Humeur de {bot.config.bot.name} — " + " | ".join(parts)`.
- `bot/twitch/bot.py:318-323` : dans le `.md` `twitch_visit_summary.md`, `Wally`→`{{BOT_NAME}}` ; après `load_prompt(...)`, ajouter `system_prompt = render_identity(system_prompt)` ; le fallback inline utilise `f"Tu es {self.config.bot.name}…"` (éviter le double-brace avec `.format(channel=…)`). Importer `render_identity`.

- [ ] **Step 3 : Lancer (passe)**

Run: `pytest tests/twitch/ -q`
Expected: PASS

- [ ] **Step 4 : Commit**

```bash
git add bot/twitch/bot.py bot/twitch/commands/mood.py bot/persona/prompts/twitch_visit_summary.md tests/twitch/
git commit -m "refactor(twitch): visit summary + mood via nom configuré"
```

---

## Phase 5 — Bridge paramétrable

### Task 14 : service à rebuild paramétrable (bot + daemon)

**Files:**
- Modify: `bot/intelligence/host_bridge.py` (`docker_rebuild`, `docker_restart`)
- Modify: `bot/intelligence/self_fix.py:151`, `bot/intelligence/self_upgrade.py:49` (passent le service)
- Modify: `scripts/host_bridge_daemon.py` (`ALLOWED_SERVICES` depuis env)
- Test: `tests/intelligence/core/test_host_bridge.py` (existant — adapter)

**Interfaces:**
- Produces: `docker_rebuild(service)` / `docker_restart(service)` sans défaut implicite « wally » côté appel.
- Consumes: nom du service depuis `config.bot.name.lower()` ou env `COMPOSE_PROJECT_NAME` (au choix dans l'implémentation, documenté).

- [ ] **Step 1 : Adapter le test (échoue)**

Les tests asserent `docker_rebuild("wally")`. Les rendre paramétriques : asserter que le service passé = celui dérivé du config (ex: `"wally"` quand name=Wally). 
Run: `pytest tests/intelligence/core/test_host_bridge.py tests/intelligence/core/test_self_fix.py -v`
Expected: FAIL.

- [ ] **Step 2 : Déterminer le service côté appelants**

Dans `self_fix.py:151` et `self_upgrade.py:49`, remplacer `"wally"` par un service dérivé :
```python
    def _service(self) -> str:
        cfg = getattr(self._bot, "config", None)
        name = getattr(getattr(cfg, "bot", None), "name", "") or "wally"
        return name.lower()
```
puis `await self._bridge.docker_rebuild(self._service())` / `docker_restart(self._service())`.

> Garder `docker_rebuild(self, service: str = "wally")` côté `host_bridge.py` (signature inchangée, défaut conservé pour compat tests bas niveau).

- [ ] **Step 3 : Daemon — `ALLOWED_SERVICES` depuis env**

`scripts/host_bridge_daemon.py:24` :
```python
ALLOWED_SERVICES: set[str] = set(
    s.strip() for s in os.environ.get("ALLOWED_SERVICES", "wally").split(",") if s.strip()
)
```
(REPO_ROOT, BRIDGE_SOCKET, BRIDGE_SECRET, CLAUDE_BIN sont déjà env-driven.)

- [ ] **Step 4 : Lancer (passe)**

Run: `pytest tests/intelligence/core/test_host_bridge.py tests/intelligence/core/test_self_fix.py tests/intelligence/core/test_self_upgrade.py -v`
Expected: PASS

- [ ] **Step 5 : Commit**

```bash
git add bot/intelligence/host_bridge.py bot/intelligence/self_fix.py bot/intelligence/self_upgrade.py scripts/host_bridge_daemon.py tests/intelligence/core/
git commit -m "feat(bridge): service à rebuild dérivé du config + ALLOWED_SERVICES env"
```

---

## Phase 6 — Frontend (owner via endpoint)

### Task 15 : exposer owner + bot_name au frontend

**Files:**
- Modify: `bot/dashboard/routes/status.py` (dict de retour de `/status`)
- Modify: `bot/dashboard/static/public-starter/app.js` (lignes 157, 196)
- Modify (miroir): `public-ui/app.js`
- Test: `tests/dashboard/test_status_owner.py` (créer)

**Interfaces:**
- Produces: `/api/public/status` renvoie `owner_discord_id` et `bot_name`.

- [ ] **Step 1 : Test (échoue)**

```python
# tests/dashboard/test_status_owner.py
# Appeler get_status avec un request mock dont app.state.wally.config.bot.owner_discord_id="42"
# et name="Cindy" ; asserter que le dict contient owner_discord_id="42" et bot_name="Cindy".
```
Run: `pytest tests/dashboard/test_status_owner.py -v`
Expected: FAIL.

- [ ] **Step 2 : Modifier `status.py`**

Ajouter au dict de retour :
```python
        "owner_discord_id": state.config.bot.owner_discord_id,
        "bot_name": state.config.bot.name,
```

- [ ] **Step 3 : Modifier `app.js` (public-starter)**

- Supprimer `const OWNER_DISCORD_ID = '610550333042589752';` (ligne 159).
- Récupérer l'owner depuis l'API au chargement et l'utiliser dans `renderAuth` :
```javascript
let OWNER_DISCORD_ID = '';
async function loadOwnerId() {
  try {
    const r = await fetch('/api/public/status');
    if (r.ok) { const d = await r.json(); OWNER_DISCORD_ID = String(d.owner_discord_id || ''); }
  } catch (_) {}
}
// appeler loadOwnerId() avant/au moment de renderAuth(), puis re-render
```
- Le test `if (OWNER_DISCORD_ID && String(p.discord_id) === OWNER_DISCORD_ID)` (owner vide ⇒ pas de bouton admin).

- [ ] **Step 4 : Miroir `public-ui/`**

Run: `cp bot/dashboard/static/public-starter/app.js public-ui/app.js`

- [ ] **Step 5 : Lancer (passe) + vérif navigateur**

Run: `pytest tests/dashboard/test_status_owner.py -v`
Vérif navigateur : bouton ADMIN visible pour l'owner uniquement.

- [ ] **Step 6 : Commit**

```bash
git add bot/dashboard/routes/status.py bot/dashboard/static/public-starter/app.js public-ui/app.js tests/dashboard/test_status_owner.py
git commit -m "feat(frontend): owner_discord_id + bot_name via /api/public/status"
```

---

## Vérification finale (après toutes les phases)

- [ ] `pytest -q` — comparer à la baseline (≈1010 verts, 2 échecs préexistants tolérés).
- [ ] `grep -rn "610550333042589752" bot/ --include=*.py --include=*.md --include=*.js` — ne reste que dans les tests (valeur de Wally injectée).
- [ ] `grep -rli "wally" bot/persona/prompts/ bot/intelligence/persona/prompts/` — vide (sauf éventuels usages légitimes non-identité à valider à la main).
- [ ] Lancer le bot localement avec le `config.yaml` de Wally → comportement identique (nom, DM créateur, admin site).
- [ ] Le SP1 est livré ; le fork de Cindy (SP2) fera l'objet d'un spec/plan distinct.

## Self-Review (couverture spec)

- Config `bot:` étendu → Task 1. ✅
- `identity.py` set/render → Task 2, posé au boot → Task 3. ✅
- Owner backend (self_fix, self_upgrade, action_dispatcher, chat_auth) → Tasks 4-7. ✅
- Garde self_modify → Task 8. ✅
- Prompts 2 dossiers + journal → Tasks 9-11. ✅
- Étiquettes runtime (twitch, mood, journal f-strings) → Tasks 11-13. ✅
- Bridge paramétrable → Task 14. ✅
- Frontend owner → Task 15. ✅
