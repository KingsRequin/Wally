# Paramétrisation multi-instance de Wally — Design (Sous-projet 1)

**Date :** 2026-06-25
**Statut :** validé en brainstorming, en attente de relecture utilisateur
**Branche :** `feat/site-redesign-arcade`

## Contexte

Wally a une seconde instance, **Cindy** (`/opt/stacks/wally-instances/cindy/`), qui tourne
sur l'image partagée `wally-ai-wally` + un dossier de config/persona à elle. Or l'identité du
bot (nom « Wally », ID Discord du créateur `610550333042589752`, nom « KingsRequin ») et le
pont de self-modification sont **codés en dur** à de nombreux endroits. Conséquences pour Cindy
aujourd'hui : elle se nomme « Wally » dans son journal/mémoire/`/mood`, ses DM de créateur et
l'admin de son site pointent vers le propriétaire de Wally, et le bridge ne sait rebuild que
`wally`.

L'objectif global (décidé avec l'utilisateur) : faire de Cindy un **fork upstream-tracking**
(son propre repo cloné de wally-ai en remote `upstream`, sa propre image, son propre daemon +
compte Claude Code). Pour que ce fork reste **mergeable sans conflits** à chaque
`git pull upstream`, l'identité doit vivre dans `config.yaml` + `persona/`, **pas** dans des
éditions de code éparpillées. Ce sous-projet livre cette paramétrisation. Il bénéficie aussi
à toute publication GitHub publique (autres utilisateurs).

## Périmètre

**Dans ce sous-projet (SP1) — code dans `wally-ai` :**
- Nouvelle section `bot:` dans `config.yaml` + dataclass `BotConfig`.
- Remplacer l'ID owner en dur par la valeur de config (backend + frontend).
- Remplacer le nom « Wally » par le nom configuré, **identité fonctionnelle seulement**
  (prompts vus par le LLM, étiquettes mémoire, `/mood`, journal, reasoning). Logs et
  commentaires internes : **inchangés** (hors périmètre, zéro impact comportemental).
- Remplacer « KingsRequin » (nom du créateur) par la valeur de config dans le prompt cœur.
- Rendre le **bridge** paramétrable (socket, secret, service à rebuild, `REPO_ROOT`,
  `ALLOWED_SERVICES`) côté bot **et** daemon.
- Garde `self_modify_enabled` (bool) : câblage de `self_fix`/`self_upgrade` conditionné.

**Hors de ce sous-projet (→ Sous-projet 2, infra/ops, spec séparé) :**
- Création du clone git de Cindy, son image, son `docker-compose.yml`.
- 2ᵉ daemon `cindy-bridge.service`, compte Claude `/root/.claude-cindy`.
- Remplissage du `config.yaml` de Cindy (name=Cindy, son owner, `self_modify_enabled: true`).

## Décisions (issues du brainstorming)

1. **`self_modify_enabled` = `false` par défaut.** Off pour GitHub et toute instance tierce.
   Wally l'active explicitement (`true`) dans son propre `config.yaml`.
2. **Nom du bot : identité fonctionnelle uniquement.** On ne touche ni aux logs ni aux
   commentaires (« Wally starting… » reste).
3. **Owner ID vide ⇒ fonctions « créateur » désactivées proprement** (DM créateur, bouton
   admin du site, self-modif). Pas de fallback codé en dur.
4. **Fork de Cindy = upstream-tracking** (`git pull upstream` pour les MAJ), pas divergence
   totale.
5. **Source de vérité = `config.yaml`** pour l'identité (l'utilisateur veut « tout dans
   config.yaml pour ce qui peut l'être »). Les secrets/tokens restent en `.env`.

## Schéma de config

Nouvelle section dans `config.yaml` :

```yaml
bot:
  name: "Wally"                      # nom fonctionnel ; défaut "Wally"
  creator_name: "KingsRequin"        # nom du créateur cité dans le prompt cœur
  owner_discord_id: "610550333042589752"   # vide ⇒ fonctions créateur désactivées
  self_modify_enabled: true          # Wally=true ; instances tierces=false (défaut)
```

**`BotConfig` existe DÉJÀ** dans `bot/config.py` (lignes 8-43, il porte `trigger_names`,
`journal_time`, params spontanés…). On l'**ÉTEND** avec 4 champs (avec défauts, donc append en
fin de dataclass) :

```python
    # --- identité multi-instance (ajout) ---
    name: str = "Wally"
    creator_name: str = "KingsRequin"
    owner_discord_id: str = ""
    self_modify_enabled: bool = False
```

- `Config.load()` construit déjà `bot=BotConfig(**raw["bot"])` (ligne ~408) — l'ajout de champs
  à défaut est rétro-compatible (un `bot:` sans ces clés prend les défauts).
- `Config.save()` sérialise déjà via `asdict(self.bot)` (ligne ~442) → round-trip automatique.
- `config.yaml` (section `bot:` existante) : ajouter `name`, `creator_name`, `owner_discord_id`,
  `self_modify_enabled` avec les valeurs de Wally.
- Défaut sûr pour GitHub : owner vide ⇒ fonctions créateur off, `self_modify_enabled=False`.

## Mécanisme d'injection de l'identité dans les prompts

**Contrainte :** certains prompts contiennent du JSON littéral (`{"user_id": …}`) → on **ne peut
pas** utiliser `str.format`. **Contrainte 2 :** plusieurs prompts sont chargés au **niveau
module** (`_JOURNAL_SYSTEM = load_prompt(...)`), avant que le config soit prêt.

**Solution — deux mécanismes, domaines distincts :**

**(a) Rendu des prompts → `identity.py` (état module, posé une fois au démarrage).**
```python
# bot/intelligence/identity.py
_NAME, _CREATOR, _OWNER = "Wally", "KingsRequin", ""

def set_identity(cfg) -> None:          # appelé 1× au boot, après Config.load
    global _NAME, _CREATOR, _OWNER
    _NAME = cfg.name or "Wally"
    _CREATOR = cfg.creator_name or "KingsRequin"
    _OWNER = cfg.owner_discord_id or ""

def render_identity(text: str) -> str:  # appliqué à CHAQUE template de prompt
    return (text.replace("{{BOT_NAME}}", _NAME)
                .replace("{{CREATOR_NAME}}", _CREATOR)
                .replace("{{OWNER_ID}}", _OWNER))
```
- Justification : les prompts sont chargés au **niveau module** (`journal.py`) ou à la
  **construction** (`reasoning_agent`, `gate`) — le config n'y est pas toujours injecté.
  `set_identity()` est posé une fois au boot (avant toute boucle), puis `render_identity()`
  s'applique partout où un template part au LLM. Cohérent avec les globals déjà utilisés par
  `load_prompt`.
- Sentinelles `{{...}}` ⇒ pas de collision avec le JSON `{...}` des prompts (et **pas** de
  `str.format`).

**(b) Owner ID & nom dans le code runtime → lecture directe de l'objet config (pas de global).**
- `self_fix`/`self_upgrade`/`action_dispatcher` reçoivent déjà le `bot` → `self._bot.config.bot.owner_discord_id`.
- `chat_auth` : `request.app.state.wally.config.bot.owner_discord_id` (le fichier lit déjà
  `…config.bot.dashboard_token`).
- Étiquettes mémoire / `/mood` / `Journal de …` : `bot.config.bot.name` (config accessible sur
  place).

## Changements par composant

### 5a — Couche config
- `bot/config.py` : `BotConfig`, champ `bot`, parsing dans `load()`, sérialisation dans `save()`.
- `config.yaml` : section `bot:` (valeurs actuelles de Wally).
- `bot/intelligence/identity.py` : nouveau, `render_identity()`.

### 5b — Owner ID
- `bot/intelligence/self_fix.py` : const `OWNER_DISCORD_ID` → lue depuis config injecté.
- `bot/intelligence/self_upgrade.py` : idem.
- `bot/dashboard/routes/chat_auth.py` : idem (via `request.app.state` / config).
- `bot/intelligence/action_dispatcher.py:171` : `os.getenv(...)` → `config.bot.owner_discord_id`.
- `bot/intelligence/persona/prompts/reasoning_system.md:89` : `610550…`→`{{OWNER_ID}}`.
- Frontend : exposer `owner_discord_id` (Discord ID = non secret) via endpoint public ;
  `bot/dashboard/static/public-starter/app.js:157` lit l'endpoint au lieu de la const.
  Miroir requis vers `public-ui/` (cf. CLAUDE.md).
- **Owner vide ⇒** chaque fonction créateur court-circuite proprement (early-return / feature off).

### 5c — Nom du bot (identité fonctionnelle)
**Prompts (sentinelle + `render_identity` au point d'usage/chargement) :**
- `bot/persona/prompts/*.md` — **15 fichiers** à `Wally` → `{{BOT_NAME}}` ; rendu au site
  d'appel des `load_prompt(...)` (journal, fact_extractor, image, session, response_mirror,
  memory_*).
- `bot/intelligence/persona/prompts/*.md` — **6 fichiers** : `gate_system.md` (13×),
  `reasoning_system.md` (3× + owner+créateur), `meta_agent_system.md` (2×),
  `inner_monologue_system.md`, `memory_arbiter.md`, `memory_extract.md`. `Wally`→`{{BOT_NAME}}`,
  `KingsRequin`→`{{CREATOR_NAME}}`, `610550…`→`{{OWNER_ID}}`. Chargés à la construction de
  `gate.py` (`_load_system`), `reasoning_agent.py` (`self._system = …read_text()`), etc. →
  envelopper le `read_text()` par `render_identity(...)`.
- `bot/intelligence/journal.py` : fallbacks inline `Tu es Wally…` → `{{BOT_NAME}}` ; aux sites
  d'usage (`self._llm.complete(_JOURNAL_SYSTEM…)`) envelopper par `render_identity(...)`.
- `bot/intelligence/self_fix.py:19` : cadrage prompt `« Wally »` → `render_identity`.
- `bot/twitch/bot.py:319` : `twitch_visit_summary` `Tu es Wally` → `render_identity`.

**Étiquettes/affichage runtime (lecture directe `config.bot.name`) :**
- `bot/twitch/handlers.py` : `author="Wally"` (×7 : 412, 422, 423, 560, 561, 642, 643) → `bot.config.bot.name`.
- `bot/intelligence/action_dispatcher.py` : `author="Wally"` (107, 123, 124) → nom depuis le bot dispo.
- `bot/intelligence/journal.py:553` : `f"# Journal de Wally —"` → `self._config.bot.name`.
- `bot/intelligence/journal.py:599-605` : `system_prompt` inline `Tu es Wally` → `self._config.bot.name`.
- `bot/twitch/commands/mood.py:19` : `Humeur de Wally` → `bot.config.bot.name`.

### 5d — Bridge paramétrable
- `bot/intelligence/host_bridge.py` : `docker_rebuild`/`docker_restart` reçoivent le **service
  cible** depuis le config (plus de défaut `"wally"` en dur côté appel).
- `scripts/host_bridge_daemon.py` : `ALLOWED_SERVICES` lue depuis env
  (`ALLOWED_SERVICES="wally"` par défaut) au lieu d'un set codé en dur. `REPO_ROOT`,
  `BRIDGE_SOCKET`, `BRIDGE_SECRET`, `CLAUDE_BIN` sont **déjà** env-driven (RAS).
- Côté bot : socket/secret du bridge déjà lus depuis l'environnement (à confirmer dans le plan).

### 5e — Garde `self_modify_enabled`
- Câblage réel dans **`bot/discord/bot.py:183-190`** (pas bootstrap) : `SelfFix`/`SelfUpgrade`
  sont construits si `_bridge_socket and _bridge_secret and self.cognitive_loop is not None`.
  Ajouter `and self.config.bot.self_modify_enabled and self.config.bot.owner_discord_id`.
- L'outil `code_fix` (ActionDispatcher) refusé quand la garde est off.

### 5f — `set_identity` au démarrage
- Appeler `identity.set_identity(config.bot)` une fois dans `main.py`, juste après
  `Config.load()` et **avant** la construction des agents/boucles qui chargent des prompts.

## Découpage en phases (≤5 fichiers, vérif entre chaque)

1. **Config** : `config.py`, `config.yaml`, `identity.py`. → tests config + `render_identity`.
2. **Owner backend** : `self_fix.py`, `self_upgrade.py`, `chat_auth.py`,
   `action_dispatcher.py`. → tests owner + garde self-modif.
3. **Prompts identité** : `reasoning_system.md`, `journal.py`, + les 15 `.md`
   (édition mécanique de sentinelles, regroupée). → tests journal/fact-extraction.
4. **Runtime nom** : `twitch/handlers.py`, `twitch/bot.py`, `commands/mood.py`. → tests twitch.
5. **Bridge** : `host_bridge.py`, `host_bridge_daemon.py`. → tests bridge.
6. **Frontend** : endpoint public + `app.js` + miroir `public-ui/`. → vérif navigateur.

## Stratégie de test

- **Nouveaux tests** : `render_identity` (sentinelles, JSON intact) ; `BotConfig` load/save
  round-trip ; garde self-modif off (outil absent, pas de DM) ; owner vide ⇒ fonctions off.
- **Tests existants** : `test_self_fix.py`, `test_self_upgrade.py`, `test_action_dispatcher.py`
  référencent `OWNER_ID = "610550333042589752"` → adapter pour injecter via config (la valeur
  reste celle de Wally en test).
- **Non-régression** : avec le `config.yaml` de Wally (valeurs actuelles), le comportement est
  identique à aujourd'hui. Baseline : `pytest` (≈1010 verts, 2 échecs préexistants spam+cost).
- Vérification finale : `pytest -q` + lancement local + revue navigateur du bouton admin.

## Risques & points d'attention

- **Deux dossiers prompts** : `bot/persona/prompts/` (bind-mount Cindy) **et**
  `bot/intelligence/persona/prompts/` (image only). Les deux doivent être paramétrés.
- **Chargement au niveau module** : ne jamais rendre l'identité au `load_prompt` (config pas
  prêt) — toujours au point d'usage.
- **Miroir `public-ui/`** : toute modif de `public-starter/` doit être recopiée (CLAUDE.md).
- **`asdict`/`save()`** : ne pas casser le round-trip de `config.yaml` (hot-reload).
- Ce SP **n'active rien de nouveau** pour Wally : mêmes valeurs, même comportement. Le fork de
  Cindy est un sous-projet distinct.
