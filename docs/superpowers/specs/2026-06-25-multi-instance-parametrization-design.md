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

Dataclass dans `bot/config.py` :

```python
@dataclass
class BotConfig:
    name: str = "Wally"
    creator_name: str = "KingsRequin"
    owner_discord_id: str = ""
    self_modify_enabled: bool = False
```

- Ajout du champ `bot: BotConfig = field(default_factory=BotConfig)` à la dataclass `Config`.
- `Config.load()` : `bot=BotConfig(**raw.get("bot", {}))`.
- `Config.save()` / sérialisation (`asdict`) : inclure `"bot": asdict(self.bot)`.
- Défauts choisis pour préserver le comportement actuel de Wally **uniquement quand son
  `config.yaml` est renseigné** ; un `config.yaml` neuf (GitHub) démarre sûr : owner vide,
  self-modif off.

## Mécanisme d'injection de l'identité dans les prompts

**Contrainte :** certains prompts contiennent du JSON littéral (`{"user_id": …}`) → on **ne peut
pas** utiliser `str.format`. **Contrainte 2 :** plusieurs prompts sont chargés au **niveau
module** (`_JOURNAL_SYSTEM = load_prompt(...)`), avant que le config soit prêt.

**Solution :** un helper unique de rendu par **remplacement de sentinelles**, appliqué **au
moment de l'usage** (là où le config est disponible par DI), pas au chargement.

```python
# bot/intelligence/identity.py
def render_identity(text: str, bot_cfg: BotConfig) -> str:
    return (text
        .replace("{{BOT_NAME}}", bot_cfg.name)
        .replace("{{CREATOR_NAME}}", bot_cfg.creator_name)
        .replace("{{OWNER_ID}}", bot_cfg.owner_discord_id))
```

- Les templates `.md` et les fallbacks inline passent `Wally`→`{{BOT_NAME}}`,
  `KingsRequin`→`{{CREATOR_NAME}}`, `610550333042589752`→`{{OWNER_ID}}`.
- Les sentinelles `{{...}}` n'entrent pas en collision avec le JSON `{...}` des prompts.
- Au point d'envoi au LLM (méthodes qui ont déjà `self._config`/`config` injecté), on appelle
  `render_identity(template, config.bot)` juste avant de construire le message.
- Les étiquettes mémoire (`author="Wally"`) lisent directement `config.bot.name`.

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
- `bot/persona/prompts/*.md` (15 fichiers à `Wally`) : `Wally`→`{{BOT_NAME}}`.
- `bot/intelligence/persona/prompts/reasoning_system.md` : `Wally`→`{{BOT_NAME}}`,
  `KingsRequin`→`{{CREATOR_NAME}}`.
- `bot/intelligence/journal.py` : fallbacks inline `Tu es Wally…` → sentinelles + rendu.
- `bot/twitch/handlers.py` : `author="Wally"` (×7) → `config.bot.name`.
- `bot/intelligence/action_dispatcher.py` : `author="Wally"` (×2) → `config.bot.name`.
- `bot/twitch/bot.py:319` : prompt résumé de visite `Tu es Wally` → rendu.
- `bot/twitch/commands/mood.py:19` : `Humeur de Wally` → `config.bot.name`.
- `bot/intelligence/self_fix.py:19` : cadrage prompt `« Wally »` → rendu.

### 5d — Bridge paramétrable
- `bot/intelligence/host_bridge.py` : `docker_rebuild`/`docker_restart` reçoivent le **service
  cible** depuis le config (plus de défaut `"wally"` en dur côté appel).
- `scripts/host_bridge_daemon.py` : `ALLOWED_SERVICES` lue depuis env
  (`ALLOWED_SERVICES="wally"` par défaut) au lieu d'un set codé en dur. `REPO_ROOT`,
  `BRIDGE_SOCKET`, `BRIDGE_SECRET`, `CLAUDE_BIN` sont **déjà** env-driven (RAS).
- Côté bot : socket/secret du bridge déjà lus depuis l'environnement (à confirmer dans le plan).

### 5e — Garde `self_modify_enabled`
- Au câblage (bootstrap) : `self_fix`/`self_upgrade` ne sont instanciés/branchés que si
  `config.bot.self_modify_enabled and config.bot.owner_discord_id`.
- L'outil `code_fix` (ActionDispatcher) est masqué/refusé quand la garde est off.

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
