# Multi-instance — Sous-projet 2 (SP2) : activation de l'identité de Cindy — Design

**Date :** 2026-06-30
**Statut :** validé en brainstorming, en attente de relecture utilisateur
**Branche :** `feat/site-redesign-arcade`
**Prérequis :** SP1 (paramétrisation multi-instance) — TERMINÉ + présent dans l'image courante `wally-ai-wally`.

## Contexte

SP1 a rendu l'identité de Wally (nom, créateur, owner Discord, garde de self-modif) entièrement
pilotée par `config.yaml` + `persona/`, sans aucune valeur en dur dans le code. SP2 en est
l'aboutissement côté ops : **faire de Cindy un vrai bot distinct** (sa propre identité, son owner)
en exploitant cette paramétrisation.

État réel constaté le 2026-06-30 (vérifié contre les conteneurs en cours) :

- Cindy tourne sur l'**image partagée** `wally-ai-wally` avec des bind-mounts
  (`config.yaml`, `.env`, `bot/persona/`, `public-ui/`). Ce n'est **pas** un clone git.
- Le conteneur `wally-cindy` n'a **jamais été recréé depuis le 2 avril 2026** → il tourne une
  image vieille de ~3 mois, **sans SP1** ni aucune amélioration depuis (cognition, mémoire V2,
  site arcade). Vérifié : `identity.py` absent, `render_identity` absent, front périmé.
- Le `config.yaml` de Cindy **ne contient aucune** des clés d'identité SP1 (`name`,
  `creator_name`, `owner_discord_id`, `self_modify_enabled`). Elle tourne donc sur les **défauts**
  du dataclass `BotConfig` → elle s'appelle encore « **Wally** » dans ses étiquettes mémoire,
  le titre de son journal et `/mood`.
- Son persona bind-monté (`bot/persona/IDENTITY.md`, `SOUL.md`…) dit bien « Tu es **Cindy** » au
  LLM : l'identité *vue par le LLM* est correcte ; c'est l'identité *runtime hors-persona* qui est
  fausse.

**Décision produit (cette session) :** Cindy **ne s'auto-modifie pas**. Cela retire toute la
lourdeur d'infra initialement envisagée pour SP2 (2ᵉ daemon `cindy-bridge`, compte Claude Code
séparé) : ces éléments n'existaient **que** pour permettre l'auto-modification.

## Décisions

1. **Modèle de déploiement = image partagée + bind-mounts** (statu quo conservé). Pas de clone
   git, pas d'image dédiée, pas de GHCR pour Cindy. Sans self-modif, l'image dédiée n'apporte
   aucun bénéfice que Cindy utilise (YAGNI). SP1 ayant rendu l'identité 100 % config/persona,
   l'image partagée suffit.
2. **`self_modify_enabled: false` pour Cindy** (explicite dans son `config.yaml`). L'outil
   `code_fix` reste absent, aucun DM créateur de self-modif, bridge non câblé.
3. **Owner Discord de Cindy = mrmakkx** (`521849789797761035`) → bouton ADMIN de son site + DM
   créateur pointent vers lui.
4. **`creator_name` de Cindy = `KingsRequin`** : exact, son persona la décrit comme
   « la femme de KingsRequin » ; KingsRequin l'a créée et la déploie.
5. **Tokens persona `{key=value}`** (ex. `{bot_name=Cindy}`, `{creator_name=KingsRequin}` dans
   `IDENTITY.md`) **laissés tels quels** : pré-existants, partent verbatim au LLM mais
   fonctionnent en pratique (le LLM lit la valeur), c'est le persona propre de Cindy. Hors
   périmètre.
6. **Site de Cindy : personnalisable, mais design custom = chantier séparé APRÈS SP2.** SP2 met
   son front à niveau **API** (câblage JS courant) ; un design visuel propre se posera ensuite en
   couche thème, sur une base saine.

## Identité cible de Cindy

Section `bot:` à compléter dans `/opt/stacks/wally-instances/cindy/config.yaml` (bind-monté, hors
image) :

```yaml
bot:
  name: "Cindy"
  creator_name: "KingsRequin"
  owner_discord_id: "521849789797761035"   # mrmakkx
  self_modify_enabled: false
  # … (les clés existantes de Cindy restent inchangées)
```

**Propagation automatique (acquise via SP1, aucune édition fichier-par-fichier) :**
- Au boot, `identity.set_identity(config.bot)` pose l'identité module.
- Les prompts à sentinelles `{{BOT_NAME}}` / `{{CREATOR_NAME}}` / `{{OWNER_ID}}` des **deux**
  dossiers — `bot/persona/prompts/` (monté RO depuis le repo Wally) et
  `bot/intelligence/persona/prompts/` (dans l'image) — rendent « Cindy » via `render_identity`.
- Les étiquettes runtime (mémoire, titre de journal, `/mood`) lisent `config.bot.name`.

## Migration sur l'image à jour (partie à risque)

Cindy passe de l'image du 2 avril à l'image courante. Montée de ~3 mois → vérifications
**avant** bascule :

1. **Schéma `config.yaml`.** Charger le `config.yaml` de Cindy avec le `Config.load()` courant et
   lister les clés/sous-sections manquantes critiques (ex. `bot.spam_detection`, `llm:`,
   `voice:`). `Config.load()` applique des défauts → attendu rétro-compatible, mais à confirmer.
2. **Schéma DB (`data/`).** La mémoire V2 (FTS5/SQLite : `atomic_facts`, `thoughts`,
   `session_analyses`, `user_profiles`, `topics`…) n'existait pas en avril. L'init de schéma au
   boot doit créer les tables manquantes **sans détruire** les données existantes. **Backup
   obligatoire** de `data/` avant bascule.
3. **`.env`.** Lister les variables absentes vs `.env.example` du repo (Azure voice, Tavily,
   Firecrawl, bridge…). Effet attendu : ces features se désactivent proprement (gardes SP1 +
   best-effort). Décision par défaut : **ne rien renseigner** (Cindy n'a besoin ni du vocal ni de
   la self-modif).
4. **Caveat mémoire « Wally ».** Les anciens messages de Cindy en DB sont étiquetés « Wally ».
   Après bascule `name=Cindy`, le filtre self (`author == self_name`) ne reconnaîtra plus ces
   vieux messages comme étant d'elle. Impact **mineur et décroissant** (fenêtre glissante
   récente). **Documenté, pas de migration de données.**

## Site & dashboard de Cindy

Le `public-ui/` de Cindy (son dossier bind-monté, seedé en avril) est périmé : il ignore les
endpoints/SSE du backend courant. Action SP2 : **mise à niveau API** du front de Cindy à partir de
la source de vérité `bot/dashboard/static/public-starter/` (repo Wally à jour), **en préservant la
place de son design propre** (le design custom viendra ensuite, en couche thème, pour résister aux
futures MAJ d'image).

Une fois à niveau :
- **Bouton ADMIN** visible pour mrmakkx (lecture de `owner_discord_id` via `/api/public/status`,
  plus de const en dur — acquis SP1).
- **Flux cognitif arcade + SSE** présents ; **aucun** event `CODEFIX` ne sera jamais émis par
  Cindy (self-modif off) → code front inoffensif chez elle.
- Auth Discord OAuth du site fonctionne avec ses propres clés (`.env` bind-monté).
- Vérifier que le `dashboard_token` existant de Cindy reste valide avec le code d'auth admin
  courant.

## Périmètre

**Dans SP2 :**
- Remplir la section `bot:` du `config.yaml` de Cindy (4 champs d'identité).
- Recréer le conteneur de Cindy sur l'image `wally-ai-wally` courante.
- Vérifications pré-bascule (config, schéma DB, `.env`).
- Mise à niveau **API** du front de Cindy (base `public-starter` courante), design propre préservé.
- Documentation : caveat mémoire, procédure bascule + rollback, stratégie de MAJ future.

**Hors SP2 (explicite) :**
- ❌ Auto-modification de Cindy (daemon `cindy-bridge`, compte Claude séparé).
- ❌ Clone git / image dédiée / GHCR pour Cindy.
- ❌ Design visuel custom du site de Cindy (chantier séparé après SP2).
- ❌ Nettoyage des tokens `{key=value}` du persona de Cindy.

## Stratégie de vérification

Ce SP2 est **opérationnel** (ops/config), pas du nouveau code applicatif : pas de TDD code.
Livrable = un **runbook de migration** vérifiable.

**Avant la bascule :**
- `cp -a data/ data.bak/` dans le déploiement de Cindy (rollback des données).
- Charger le `config.yaml` de Cindy avec le `Config.load()` courant → lister clés manquantes.
- Diff `.env` de Cindy vs `.env.example` du repo → lister variables absentes.

**Bascule :**
- Éditer `config.yaml` (section `bot:`).
- `docker compose up -d --force-recreate cindy`.

**Après (smoke tests) :**
- Logs de boot : « ready », **zéro** erreur de schéma DB.
- Message Discord à Cindy → réponse dans son ton, **étiquetée Cindy** en mémoire (vérif DB :
  nouveaux faits avec author = Cindy, pas Wally).
- `/mood` → « Humeur de **Cindy** » ; titre du journal → « Journal de **Cindy** ».
- Site de Cindy : bouton **ADMIN** visible pour mrmakkx ; SSE cognitif vivant ; **aucun** event
  CODEFIX.
- Outil `code_fix` **absent** (garde self-modif off).

**Rollback :** recréer le conteneur de Cindy sur l'ancienne image (`efa76f665a6c`) + restaurer
`data.bak/`.

## Risques & points d'attention

- **Montée de ~3 mois d'un coup** : le risque principal. Les backups (`data/`) et les vérifs
  pré-bascule l'encadrent. Bascule réversible.
- **Schéma DB** : si l'init au boot ne migre pas proprement les vieilles bases d'avril, restaurer
  le backup et traiter la migration de schéma comme une sous-tâche dédiée.
- **Front périmé** : ne pas écraser un éventuel design custom existant de Cindy ; ici son
  `public-ui` est le seed d'avril (pas de custom à préserver pour l'instant), mais la règle vaut
  pour l'avenir.
- **`config.bot.name` vs persona** : les deux doivent dire « Cindy » ; le persona le fait déjà,
  la config le fera après SP2.
- Ce SP **n'active rien de nouveau pour Wally** : seul le déploiement de Cindy change.
