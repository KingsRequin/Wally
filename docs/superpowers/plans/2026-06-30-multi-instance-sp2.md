# SP2 Multi-instance — Migration & identité de Cindy — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire de Cindy un bot à identité propre (« Cindy », owner mrmakkx, sans self-modif) en la migrant du conteneur pré-SP1 du 2 avril vers l'image partagée `wally-ai-wally` courante, identité pilotée par son `config.yaml`.

**Architecture :** Modèle **image partagée + bind-mounts** conservé (pas de clone git, pas de daemon, pas de compte Claude — self-modif retirée). L'identité se propage automatiquement via SP1 (`set_identity`/`render_identity` + lecture `config.bot.name`). Le travail est **opérationnel** (ops/config) : backup → vérifs pré-bascule → édition config → mise à niveau front → recréation conteneur → smoke tests. Réversible.

**Tech Stack :** Docker Compose v2, image `wally-ai-wally`, SQLite/FTS5 (`data/`), bind-mounts.

## Global Constraints

- **Déploiement de Cindy :** `/opt/stacks/wally-instances/cindy/` (NON un repo git). Service compose : `cindy`. Conteneur : `wally-cindy`. Port hôte : `8081`.
- **Image cible :** tag `wally-ai-wally` (actuellement `0eb49483b730`, contient SP1). **Image de rollback :** `efa76f665a6c` (build du 2026-04-02, pré-SP1, image actuellement utilisée par Cindy).
- **Identité cible (config.yaml de Cindy, section `bot:`) :** `name: "Cindy"`, `creator_name: "KingsRequin"`, `owner_discord_id: "521849789797761035"` (mrmakkx), `self_modify_enabled: false`.
- **Source de vérité front :** `/opt/stacks/wally-ai/bot/dashboard/static/public-starter/` → miroir `/opt/stacks/wally-instances/cindy/public-ui/`.
- **`.env.example` de référence :** `/opt/stacks/wally-ai/.env.example`.
- **Toute commande `docker compose` pour Cindy s'exécute depuis `/opt/stacks/wally-instances/cindy/`.**
- **Réversibilité :** aucune étape destructive sans backup préalable. La bascule (Task 4) est réversible via le rollback (section finale).
- **Pas de changement côté Wally :** rien dans ce plan ne modifie le déploiement ni l'image de Wally.

---

### Task 1: Backup & vérifications pré-bascule (non destructif)

Recon pure, aucune modification de l'état de Cindy. Produit un backup et un rapport des écarts (clés config manquantes, variables `.env` absentes) qui informe les décisions des tâches suivantes.

**Files:**
- Create: `/opt/stacks/wally-instances/cindy/data.bak/` (copie de `data/`)
- Create: `/opt/stacks/wally-instances/cindy/config.yaml.bak`, `/opt/stacks/wally-instances/cindy/.env.bak`
- Read: `/opt/stacks/wally-instances/cindy/config.yaml`, `/opt/stacks/wally-instances/cindy/.env`
- Read: `/opt/stacks/wally-ai/.env.example`

**Interfaces:**
- Produces: un backup horodaté de `data/`, `config.yaml`, `.env` ; un rapport texte listant (a) les sous-sections/clés que `Config.load()` courant attend et qui manquent dans le `config.yaml` de Cindy, (b) les variables présentes dans `.env.example` et absentes du `.env` de Cindy.

- [ ] **Step 1 : Sauvegarder `data/`, `config.yaml`, `.env` de Cindy**

```bash
cd /opt/stacks/wally-instances/cindy
cp -a data/ data.bak/
cp -a config.yaml config.yaml.bak
cp -a .env .env.bak
ls -la data.bak/ config.yaml.bak .env.bak
```
Expected : les 3 backups existent ; `data.bak/` contient les mêmes fichiers que `data/`.

- [ ] **Step 2 : Lister les variables `.env` manquantes vs la référence du repo**

```bash
cd /opt/stacks/wally-instances/cindy
comm -23 \
  <(grep -oE '^[A-Z_][A-Z0-9_]*' /opt/stacks/wally-ai/.env.example | sort -u) \
  <(grep -oE '^[A-Z_][A-Z0-9_]*' .env | sort -u)
```
Expected : liste (possiblement vide) des noms de variables présentes dans `.env.example` mais absentes du `.env` de Cindy. **Noter cette liste.** Décision par défaut (cf. spec) : ne RIEN ajouter — les features concernées (vocal Azure, Tavily, Firecrawl, bridge self-modif) se désactivent proprement. N'ajouter une variable que si elle est requise au simple boot (à confirmer Step 3).

- [ ] **Step 3 : Tester que le `config.yaml` de Cindy se charge avec le code courant**

Charge la config de Cindy avec le `Config.load()` de l'image à jour, dans un conteneur jetable (ne touche pas le conteneur en service) :

```bash
cd /opt/stacks/wally-instances/cindy
docker run --rm \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/.env:/app/.env:ro" \
  -w /app wally-ai-wally \
  python -c "from bot.config import Config; c=Config.load(); print('OK name=', c.bot.name, 'self_modify=', getattr(c.bot,'self_modify_enabled', 'ABSENT'))"
```
Expected : `OK name= Wally self_modify= False` (Cindy est encore sur les défauts → `name=Wally`, c'est le bug qu'on corrige). **Si la commande lève une exception** (clé inattendue, schéma incompatible) : noter l'erreur — elle devient un prérequis bloquant à traiter avant la bascule (corriger la clé fautive dans `config.yaml`). Si OK, le schéma config est rétro-compatible.

- [ ] **Step 4 : Inspecter le schéma DB existant (faits/tables mémoire V2)**

```bash
cd /opt/stacks/wally-instances/cindy
for db in data/*.db data/*.sqlite data/*.sqlite3; do
  [ -f "$db" ] && echo "=== $db ===" && \
  docker run --rm -v "$PWD/data:/d:ro" wally-ai-wally \
    python -c "import sqlite3,sys; c=sqlite3.connect('/d/$(basename $db)'); print(sorted(r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")))"
done
```
Expected : la liste des tables actuelles de chaque base. **Noter** si les tables mémoire V2 (`atomic_facts`, `thoughts`, `session_analyses`, `user_profiles`, `topics`) sont absentes — c'est attendu (base d'avril) ; l'init de schéma au boot (Task 4) doit les créer sans toucher aux données existantes. Ce step ne fait qu'établir l'état de départ pour comparaison post-bascule.

- [ ] **Step 5 : Geler le rapport pré-bascule**

Consigner dans la note de session (ou un fichier `/opt/stacks/wally-instances/cindy/MIGRATION_NOTES.md`) : variables `.env` manquantes (Step 2), résultat du chargement config (Step 3), tables DB de départ (Step 4), et l'ID de l'image de rollback `efa76f665a6c`. Pas de commit (dossier hors git).

**Gate de revue :** backups présents, config se charge sans erreur, écarts notés. Si le chargement config a échoué → STOP, traiter avant Task 2.

---

### Task 2: Renseigner l'identité de Cindy dans son `config.yaml`

Édition ciblée de la section `bot:` du `config.yaml` bind-monté de Cindy. Aucune recréation de conteneur ici (l'effet sera pris au prochain boot, Task 4).

**Files:**
- Modify: `/opt/stacks/wally-instances/cindy/config.yaml` (section `bot:`)

**Interfaces:**
- Consumes: backup `config.yaml.bak` de Task 1.
- Produces: un `config.yaml` dont la section `bot:` porte les 4 clés d'identité cibles, qui se charge proprement (`name=Cindy`).

- [ ] **Step 1 : Ajouter les 4 clés d'identité sous `bot:`**

Dans `/opt/stacks/wally-instances/cindy/config.yaml`, ajouter ces 4 lignes à l'intérieur de la section `bot:` (à côté des clés existantes ; l'indentation YAML = 2 espaces) :

```yaml
  name: "Cindy"
  creator_name: "KingsRequin"
  owner_discord_id: "521849789797761035"
  self_modify_enabled: false
```

- [ ] **Step 2 : Vérifier que la config modifiée se charge et expose la bonne identité**

```bash
cd /opt/stacks/wally-instances/cindy
docker run --rm \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/.env:/app/.env:ro" \
  -w /app wally-ai-wally \
  python -c "from bot.config import Config; c=Config.load(); assert c.bot.name=='Cindy'; assert c.bot.owner_discord_id=='521849789797761035'; assert c.bot.self_modify_enabled is False; print('Identité OK:', c.bot.name, c.bot.owner_discord_id, c.bot.self_modify_enabled)"
```
Expected : `Identité OK: Cindy 521849789797761035 False`. Si l'assertion casse → corriger l'édition YAML (indentation/typo) et relancer.

**Gate de revue :** `config.yaml` charge `name=Cindy`, owner=mrmakkx, self_modify=False. Le conteneur en service tourne toujours l'ancienne image (non encore basculé) — normal.

---

### Task 3: Mettre le front `public-ui` de Cindy à niveau API

Le `public-ui/` de Cindy date d'avril → il ignore les endpoints/SSE courants. On le rafraîchit depuis la source de vérité `public-starter` à jour. **Aucun design custom à préserver** aujourd'hui (le seed d'avril n'a pas de personnalisation) ; un design propre se posera plus tard en couche thème.

**Files:**
- Backup: `/opt/stacks/wally-instances/cindy/public-ui.bak/`
- Modify (remplacer le contenu): `/opt/stacks/wally-instances/cindy/public-ui/`
- Source (read): `/opt/stacks/wally-ai/bot/dashboard/static/public-starter/`

**Interfaces:**
- Consumes: `public-starter/` courant (contient le câblage owner-via-endpoint SP1, le SSE cognitif, l'auth admin).
- Produces: un `public-ui/` de Cindy byte-identique à `public-starter/` courant.

- [ ] **Step 1 : Sauvegarder l'ancien `public-ui` de Cindy**

```bash
cd /opt/stacks/wally-instances/cindy
cp -a public-ui/ public-ui.bak/
ls public-ui.bak/
```
Expected : `public-ui.bak/` contient l'ancien front (rollback front possible).

- [ ] **Step 2 : Recopier le `public-starter` courant dans le `public-ui` de Cindy**

```bash
cd /opt/stacks/wally-instances/cindy
rsync -a --delete /opt/stacks/wally-ai/bot/dashboard/static/public-starter/ public-ui/
```
(Si `rsync` indisponible : `rm -rf public-ui/* && cp -a /opt/stacks/wally-ai/bot/dashboard/static/public-starter/. public-ui/`.)

- [ ] **Step 3 : Vérifier que le front à jour lit l'owner via endpoint (SP1)**

```bash
cd /opt/stacks/wally-instances/cindy
grep -c "owner_discord_id" public-ui/app.js
grep -rc "CODEFIX" public-ui/tabs/status.js
```
Expected : `app.js` contient ≥1 occurrence de `owner_discord_id` (lecture via endpoint) et `status.js` contient le rendu CODEFIX (≥1) — preuve que le front est bien la version courante. (Cindy n'émettra jamais d'event CODEFIX, c'est juste du code mort inoffensif.)

**Gate de revue :** `public-ui/` de Cindy = version courante, owner lu via endpoint. Backup front présent.

---

### Task 4: Bascule — recréer le conteneur de Cindy sur l'image à jour

L'étape pivot. Recrée `wally-cindy` sur l'image `wally-ai-wally` courante. L'identité (Task 2) et le front (Task 3) prennent effet ici. L'init de schéma DB au boot crée les tables mémoire V2 manquantes.

**Files:**
- Modify (runtime): conteneur `wally-cindy` (recréé)
- Read: logs de boot du conteneur

**Interfaces:**
- Consumes: `config.yaml` (Task 2), `public-ui/` (Task 3), backup `data.bak/` (Task 1, pour rollback).
- Produces: un conteneur `wally-cindy` tournant l'image courante, boot propre, schéma DB à jour.

- [ ] **Step 1 : Confirmer l'image actuellement utilisée (pour le rollback)**

```bash
docker inspect --format '{{.Image}}' wally-cindy
```
Expected : commence par `sha256:efa76f665a6c…` — c'est l'image de rollback. **La noter** si elle diffère de la constante du plan.

- [ ] **Step 2 : Recréer le conteneur sur l'image à jour**

```bash
cd /opt/stacks/wally-instances/cindy
docker compose up -d --force-recreate cindy
```
Expected : `wally-cindy` recréé et démarré.

- [ ] **Step 3 : Vérifier l'image et le boot**

```bash
docker inspect --format '{{.Image}}' wally-cindy   # doit être 0eb49483b730… (image courante)
docker logs --tail=120 wally-cindy 2>&1 | grep -iE "ready|started|error|traceback|schema|sqlite" | tail -40
```
Expected : l'image est la courante ; les logs montrent un démarrage « ready/started » **sans** `Traceback`, **sans** erreur de schéma SQLite. **Si erreur de schéma DB ou crash au boot → STOP et exécuter le ROLLBACK (section finale).**

- [ ] **Step 4 : Confirmer la création des tables mémoire V2 sans perte**

```bash
cd /opt/stacks/wally-instances/cindy
for db in data/*.db data/*.sqlite data/*.sqlite3; do
  [ -f "$db" ] && echo "=== $db ===" && \
  docker exec wally-cindy python -c "import sqlite3; c=sqlite3.connect('/app/data/$(basename $db)'); print(sorted(r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")))"
done
```
Expected : les tables mémoire V2 (`atomic_facts`, `thoughts`, etc.) sont désormais présentes ; les tables/données préexistantes (comparées à Task 1 Step 4) sont toujours là. Si des données ont disparu → ROLLBACK.

**Gate de revue :** Cindy tourne l'image courante, boot propre, schéma DB enrichi sans perte. Sinon → rollback.

---

### Task 5: Smoke tests post-migration (identité, self-modif off, site)

Valide que la migration produit le comportement attendu côté utilisateur.

**Files:**
- Read: logs/DB/site de Cindy (vérifications uniquement)

**Interfaces:**
- Consumes: conteneur basculé (Task 4).
- Produces: une checklist de validation passée (ou un défaut identifié → décision rollback).

- [ ] **Step 1 : Identité runtime — un message Discord → réponse étiquetée Cindy**

Envoyer (ou faire envoyer) un message à Cindy sur Discord, puis vérifier l'étiquette d'auteur de SES réponses en mémoire :

```bash
cd /opt/stacks/wally-instances/cindy
docker exec wally-cindy python -c "import sqlite3,glob; \
[print(db, sorted({r[0] for r in sqlite3.connect(db).execute('select distinct author from messages limit 50')})) for db in glob.glob('/app/data/*.db')]" 2>/dev/null || echo "adapter le nom de table/colonne au schéma réel"
```
Expected : les nouveaux messages du bot sont étiquetés **Cindy** (pas Wally). (Adapter table/colonne au schéma réel si besoin — l'objectif est : author du bot == « Cindy ».)

- [ ] **Step 2 : `/mood` et journal portent « Cindy »**

Déclencher `/mood` sur Discord → l'embed doit titrer « Humeur de **Cindy** ». Vérifier le prochain titre de journal :

```bash
docker exec wally-cindy sh -c "grep -rh 'Journal de' /app/data 2>/dev/null | tail -3" || echo "journal pas encore généré (21:00) — vérifier le titre au prochain run"
```
Expected : « Humeur de Cindy » dans l'embed ; titre de journal « Journal de Cindy » (ou à confirmer au prochain run 21:00).

- [ ] **Step 3 : Self-modif OFF — outil `code_fix` absent, garde non câblée**

```bash
docker logs wally-cindy 2>&1 | grep -iE "self.?fix|self.?upgrade|code_fix|bridge" | tail -20
```
Expected : **aucune** trace de câblage de `SelfFix`/`SelfUpgrade`/bridge (la garde `self_modify_enabled=false` court-circuite). Confirmer côté comportement : l'outil `code_fix` n'est pas proposé au LLM.

- [ ] **Step 4 : Site de Cindy — bouton ADMIN pour mrmakkx + SSE vivant**

```bash
curl -s http://localhost:8081/api/public/status | python -c "import sys,json; d=json.load(sys.stdin); print('owner_discord_id=', d.get('owner_discord_id'))"
curl -s -N --max-time 5 http://localhost:8081/api/public/sse/cognitive | head -3
```
Expected : `owner_discord_id= 521849789797761035` (→ bouton ADMIN s'affichera pour mrmakkx) ; le flux SSE renvoie des lignes `event:`/`data:` (cognition vivante). Vérification navigateur facultative : ouvrir le site de Cindy, confirmer le bouton ADMIN visible une fois connecté en tant que mrmakkx.

- [ ] **Step 5 : Geler le résultat de migration**

Consigner dans `MIGRATION_NOTES.md` : image avant/après, boot OK, tables créées, identité Cindy confirmée, self-modif off, owner endpoint OK. Marquer la migration comme réussie. Nettoyer les backups après une période d'observation (garder `data.bak/` au moins 48 h).

**Gate de revue :** tous les smoke tests passent → SP2 livré. Un échec d'identité ou un crash → rollback.

---

## ROLLBACK (si un gate échoue après la bascule)

Réversibilité complète vers l'état pré-migration :

```bash
cd /opt/stacks/wally-instances/cindy
# 1. Restaurer les données pré-migration
rm -rf data/ && cp -a data.bak/ data/
# 2. Restaurer le front si modifié
rm -rf public-ui/ && cp -a public-ui.bak/ public-ui/
# 3. Restaurer le config si l'identité est en cause
cp -a config.yaml.bak config.yaml
# 4. Recréer le conteneur sur l'ANCIENNE image (épingler l'ID exact)
docker run -d --name wally-cindy_rollback --env-file .env \
  -p 8081:8080 -v "$PWD/data:/app/data" -v "$PWD/config.yaml:/app/config.yaml" \
  efa76f665a6c
# (ou : retagger efa76f665a6c et relancer `docker compose up -d`)
```
Note : comme le tag `wally-ai-wally` pointe désormais sur l'image courante, le rollback compose nécessite de cibler l'image par son **ID** `efa76f665a6c` (la commande `docker run` ci-dessus, à aligner sur les volumes du compose) ou de retagger temporairement. Vérifier ensuite `docker logs wally-cindy*` = boot propre sur l'ancienne image.

---

## Self-Review (vérifié contre le spec)

- **Couverture spec :** identité config (Task 2 ✓), migration image + vérifs config/DB/env (Tasks 1, 4 ✓), front à niveau API (Task 3 ✓), caveat mémoire « Wally » (documenté, pas de migration — cohérent Task 5 Step 1 vérifie les NOUVEAUX messages), procédure bascule + rollback (Task 4 + section ROLLBACK ✓), self-modif off (Task 5 Step 3 ✓), site/owner (Task 5 Step 4 ✓). Hors-périmètre (clone git, daemon, design custom, tokens persona) : non inclus, conforme au spec.
- **Placeholders :** aucun TBD/TODO ; chaque step a une commande exacte + sortie attendue. Les seuls « à adapter » concernent le nom réel de table/colonne mémoire (Task 5 Step 1) — assumé car le schéma exact dépend de la base, l'objectif est explicite.
- **Cohérence :** image rollback `efa76f665a6c` et image cible `0eb49483b730`/`wally-ai-wally` utilisées de façon cohérente partout ; chemins de déploiement constants ; owner `521849789797761035` identique config/site.
