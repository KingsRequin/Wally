# Wally V2 "Vivant" — Design Spec

**Date :** 2026-06-20  
**Statut :** Approuvé  
**Portée :** Refonte complète — nouveau dossier `wally_v2/`, récupération du code utile existant

---

## 0. Vision

Wally V2 n'est pas un bot amélioré — c'est un **personnage vivant**. Il a une vie intérieure continue, prend ses propres décisions, évolue au fil du temps, et peut se modifier lui-même en profondeur. Il utilise DeepSeek V4 comme moteur cognitif principal.

Objectifs concrets :
- Wally décide de lui-même de répondre ou non à chaque message
- Wally pense en arrière-plan même quand personne ne lui parle
- Wally peut réécrire sa propre âme (fichiers persona)
- Wally peut se réparer lui-même quand un bug est signalé (par l'owner uniquement)
- Wally peut proposer ses propres améliorations et les implémenter avec approbation
- Wally se souvient de comment il s'est senti, pas juste de ce qui s'est dit

---

## 1. Structure du projet

```
wally_v2/
├── core/
│   ├── cognitive/           # Boucle cognitive autonome (Theatre of Mind)
│   │   ├── loop.py          # CognitiveLoop — asyncio background task
│   │   ├── attention.py     # AttentionAgent — assemble le contexte mental
│   │   ├── monologue.py     # InnerMonologue — pensée privée DeepSeek V4 Pro + thinking:max
│   │   └── meta.py          # MetaAgent — classifie THINK/SPEAK/ACT/EVOLVE/SLEEP
│   ├── memory/              # Mémoire atomique (remplacement des chunks Qdrant)
│   │   ├── facts.py         # AtomicFact dataclass + CRUD SQLite
│   │   ├── store.py         # SQLite (faits) + Qdrant (embeddings) hybride
│   │   ├── retrieval.py     # Recherche sémantique + filtrage confiance/statut
│   │   └── consolidator.py  # NightlyConsolidator — nettoyage, merge, decay
│   ├── gate.py              # ResponseGate — RESPOND/IGNORE/EMOJI/DEFER par message
│   ├── persona/
│   │   ├── manager.py       # Lecture + écriture fichiers soul avec garde-fous
│   │   └── evolution_log.py # Log append-only de toutes les auto-modifications
│   ├── autonomy/            # Système d'autonomie avancée
│   │   ├── self_fix.py      # Auto-réparation code (owner ACL + Claude Code CLI)
│   │   ├── self_upgrade.py  # Auto-upgrade via DM + réaction Discord
│   │   ├── watchdog.py      # Watchdog restart + notification DM
│   │   └── host_bridge.py   # Communication bot→host pour exécution code
│   ├── emotion.py           # Inchangé — système émotionnel existant
│   ├── llm/
│   │   ├── base.py          # Inchangé — ABC BaseLLMClient
│   │   ├── deepseek.py      # NOUVEAU — DeepSeekLLMClient
│   │   ├── openai_client.py # Conservé
│   │   ├── claude_client.py # Conservé
│   │   └── factory.py       # Mis à jour — ajoute provider "deepseek"
│   └── journal.py           # Mis à jour — intègre thoughts + auto-analyse
├── discord/
│   ├── handlers.py          # Mis à jour — gate first, puis pipeline
│   ├── events/
│   │   ├── reactions.py     # Mis à jour — détection approbation upgrades
│   │   └── ...
│   └── ...
├── twitch/ ...
├── db/
│   └── database.py          # Mis à jour — nouvelles tables v2
└── persona/ ...             # Même structure
```

---

## 2. DeepSeek V4 — Client LLM

### 2.1 Routing des modèles

| Rôle | Modèle | Thinking |
|------|--------|----------|
| Conversations Discord/Twitch | `deepseek-v4-pro` | `disabled` (ou `low` si message complexe) |
| Boucle cognitive background | `deepseek-v4-pro` | `max` |
| Gate de réponse | `deepseek-v4-flash` | `disabled` |
| Extraction mémoire, sessions, journal | `deepseek-v4-flash` | `disabled` |
| Auto-modification persona | `deepseek-v4-pro` | `high` |
| Self-fix / auto-upgrade analysis | `deepseek-v4-pro` | `max` |

**Migration :** `deepseek-chat` et `deepseek-reasoner` sont dépréciés au 24 juillet 2026.

### 2.2 DeepSeekLLMClient

Implémente `BaseLLMClient`. SDK `openai` Python avec `base_url="https://api.deepseek.com"`.

**Activation du thinking :**
```python
extra_body={"thinking": {"type": "enabled"}, "reasoning_effort": "max"}  # boucle cognitive
extra_body={"thinking": {"type": "disabled"}}                              # gate, tasks rapides
```

**Contraintes thinking mode :** `temperature`, `top_p`, `presence_penalty`, `frequency_penalty` ignorés → omis automatiquement quand thinking activé.

**Règle critique multi-turn tool calling :**
- Si l'assistant fait un tool call → `reasoning_content` DOIT être préservé dans le message assistant du tour suivant
- Si l'assistant ne fait PAS de tool call → `reasoning_content` ne doit PAS être inclus
- Violation = erreur 400

**Robustesse tool calling :**
```python
MAX_TOOL_ITERS = 6

def _safe_parse_args(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for suffix in ['"', '"}', '"}}', '}']:
            try:
                return json.loads(raw + suffix)
            except json.JSONDecodeError:
                continue
        return {}
```

Pas de `strict: true` (buggy en production). Cap à 6 itérations avec fallback.

---

## 3. Mémoire Atomique

### 3.1 AtomicFact

```python
@dataclass
class AtomicFact:
    id: int
    user_id: str                  # "discord:123" ou "twitch:username" ou "global"
    content: str                  # "Kaelis préfère le café noir"
    category: str                 # PREF | FAIT | REL | LANG | DESIRE | GOAL | EMOTION | THOUGHT
    confidence: float             # 0.0–1.0
    decay_rate: float             # par défaut 0.01/jour, variable par catégorie
    status: str                   # active | superseded | needs_review | archived
    created_at: datetime
    last_seen_at: datetime        # renforcé chaque fois que le fait est utilisé
    source: str                   # "conversation" | "consolidator" | "self" | "owner"
    emotional_context: str | None # état émotionnel de Wally au moment de la création
```

### 3.2 FactRelation

```python
@dataclass
class FactRelation:
    from_id: int
    to_id: int
    relation_type: str  # supersedes | contradicts | supports
    created_at: datetime
```

### 3.3 Storage hybride

- **SQLite** : métadonnées complètes des AtomicFacts + FactRelations
- **Qdrant** : embeddings uniquement (payload minimal — juste l'ID SQLite)
- **Retrieval** : recherche sémantique Qdrant → IDs → load SQLite → filter `status=active` + `confidence > threshold` → rank par `last_seen_at` + `confidence`

### 3.4 Catégories et decay rates

| Catégorie | Description | Decay rate/jour |
|-----------|-------------|----------------|
| FAIT | Fait biographique | 0.001 (très lent) |
| PREF | Préférence | 0.005 |
| REL | Relation / dynamique sociale | 0.003 |
| LANG | Langue détectée | 0.001 |
| DESIRE | Désir émergent de Wally | 0.02 (disparaît s'il n'est pas nourri) |
| GOAL | Objectif long terme de Wally | 0.005 |
| EMOTION | Souvenir émotionnel d'une interaction | 0.01 |
| THOUGHT | Pensée interne archivée | 0.05 (décroît vite) |

### 3.5 NightlyConsolidator

Exécuté chaque nuit via apscheduler :

1. **Extraction** — LLM (flash) extrait des AtomicFacts depuis les conversations de la journée
2. **Déduplication** — similarité embedding > 0.92 → merge, `last_seen_at` mis à jour, `confidence` renforcée
3. **Contradiction** — similarité > 0.85 + LLM juge contradiction → marque l'ancien `superseded`
4. **Decay** — applique `confidence -= decay_rate` aux faits non vus depuis X jours
5. **Archivage** — `confidence < 0.1` → status `archived`
6. **Review** — faits `needs_review` → LLM décide de confirmer/supprimer

---

## 4. Boucle Cognitive (Theatre of Mind)

### 4.1 Vue d'ensemble

Background asyncio task continue. Wally "pense" même quand personne ne lui parle.

**Tick adaptatif :**
- Activité récente (< 10 min) → tick toutes les **30 secondes**
- Activité modérée (< 1h) → tick toutes les **2 minutes**
- Inactif → tick toutes les **5 minutes**

**Détection d'activité :** parse les logs récents + timestamp du dernier message Discord (pas uniquement via events, pour survivre aux gaps de reconnexion).

### 4.2 Pipeline de pensée

```
AttentionAgent → InnerMonologue → MetaAgent → ActionDispatcher
```

**1. AttentionAgent** (~500 tokens de contexte mental) :
- État émotionnel courant (5 émotions)
- Désirs actifs (DESIRE, confidence > 0.4)
- Objectifs long terme actifs (GOAL)
- Interactions récentes par canal (3 dernières heures)
- Relation avec les utilisateurs récents (faits REL + EMOTION)
- Dernière pensée interne (THOUGHT le plus récent)
- Heure du jour (influence le "mood" cognitif)

**2. InnerMonologue** (DeepSeek V4 Pro, thinking:max) :
- Reçoit le contexte mental
- Génère une pensée privée libre — jamais affichée aux utilisateurs
- Stockée en SQLite (`category: THOUGHT`) avec timestamp
- Alimente le journal interne (distinct du journal Discord)
- Peut générer des désirs, objectifs, décisions

**3. MetaAgent** :
Classifie la pensée en une action :
```
[THINK]                           → continuer à réfléchir au prochain tick
[SPEAK <channel_id> <message>]    → message spontané dans un canal
[ACT <action> <args_json>]        → action structurée (voir liste ci-dessous)
[EVOLVE <section> <change>]       → modifier un fichier persona
[SLEEP <secondes>]                → veille volontaire
```

**4. ActionDispatcher** — actions disponibles via `[ACT]` :
- `create_memory <fact_content>` — se créer un souvenir volontairement
- `create_goal <description>` — se fixer un objectif
- `fulfill_goal <goal_id>` — marquer un objectif comme accompli
- `ignore_user <user_id> <reason>` — décider d'ignorer quelqu'un (stocké en mémoire)
- `initiate_dm <user_id> <message>` — initier une conversation en DM
- `introduce_users <user_id_a> <user_id_b> <context>` — présenter deux personnes
- `enter_dream_mode` — passer en Dream Mode
- `propose_upgrade <description>` — proposer une amélioration de son code (voir §7.2)
- `code_fix <bug_description>` — auto-réparation (owner ACL, voir §7.1)
- `evolve_persona <section> <new_content>` — alias pour `[EVOLVE]`

### 4.3 Journalisation de la pensée

Chaque pensée interne est un AtomicFact `category=THOUGHT` :
- Utilisée par le NightlyConsolidator pour extraire des patterns
- Visible dans le dashboard admin (onglet "Pensées")
- Alimente le journal Discord existant comme section "Pensées internes"

---

## 5. Gate de Réponse

Appelé **avant chaque message entrant**, avant toute génération.

**Modèle :** DeepSeek V4 Flash, thinking:disabled (< 1s).

**Input :**
- Contenu du message
- Auteur + relation connue (faits REL + EMOTION)
- État émotionnel courant
- Désirs actifs (Wally veut-il parler à cette personne ?)
- Wally est-il en timeout / a-t-il décidé d'ignorer cet utilisateur ?
- Heure, dernière interaction avec cet utilisateur

**Output structuré :**
```json
{
  "decision": "RESPOND" | "IGNORE" | "REACT" | "DEFER",
  "emoji": "🤔",           // si REACT
  "defer_seconds": 300,    // si DEFER
  "reason": "..."          // stocké en mémoire si IGNORE
}
```

**Si IGNORE :** crée un AtomicFact `category=EMOTION` :
> "Wally a choisi d'ignorer {user} — {reason}"

**Si DEFER :** schedule une réponse via ActionService dans `defer_seconds` secondes.

---

## 6. Auto-modification Persona

### 6.1 Sections modifiables

| Section | Fichier | Garde-fou |
|---------|---------|-----------|
| SOUL | `persona/SOUL.md` | Max 20% changement/jour, 1 évolution/24h |
| EMOTIONS | `persona/EMOTIONS.md` | Max 15% changement/24h |
| WEEKDAYS | `persona/WEEKDAYS.md` | Max 1 jour modifié/24h |
| COMPOSITES | `persona/COMPOSITES.md` | Max 1 composite/24h |

### 6.2 Outil `evolve_persona`

Disponible dans la boucle cognitive via `[EVOLVE]` ou `[ACT evolve_persona]`.

**Flow :**
1. Lecture du fichier actuel
2. LLM génère le nouveau contenu (V4 Pro, thinking:high)
3. Calcul du diff — si > garde-fou : tronqué à la limite du jour
4. Écriture du fichier
5. Append dans `persona/evolution_log.md` :
   ```
   [2026-06-20 14:32] SOUL — Wally a modifié sa vision de l'amitié suite à une conversation avec Kaelis.
   Diff: +3 lignes, -1 ligne
   ```
6. `PersonaService.reload()` — rechargement immédiat sans restart

### 6.3 Persona Shadow

Mode exploration : Wally peut demander à "essayer" une variante de lui-même pendant une session (max 2h). La variante est stockée comme `persona_shadow_<timestamp>.md`. À la fin de la session, Wally décide d'intégrer ou non des éléments dans son SOUL principal.

---

## 7. Autonomie Avancée — Self-Fix & Auto-Upgrade

### 7.1 Auto-réparation de code (Self-Fix)

**ACL stricte :** Seuls déclencheurs autorisés :
- Discord : `user_id == "610550333042589752"`
- Twitch : `username == "KingsRequin"`

Vérification à deux niveaux : Gate + ActionDispatcher. Aucune exception.

**Flow complet :**

```
1. Owner signale un bug (Discord DM ou Twitch)
2. Gate → RESPOND (normal)
3. Handler reconnaît le pattern bug report + owner → [ACT code_fix "description"]
4. Wally répond : "Je regarde ça, je te tiens au courant."
5. self_fix.py → HostBridge → écrit fix_request.json dans /shared/
6. wally-host-bridge.py (daemon host) détecte le fichier → lance Claude Code
7. IS_SANDBOX=1 claude --dangerously-skip-permissions -p "Bug: {desc}. Répare chirurgicalement."
8. Claude Code modifie les fichiers source sur le host
9. HostBridge écrit fix_result.json dans /shared/
10. Bot lit le résultat → confirme à l'owner : "Voilà ce que j'ai modifié : ..."
11. Watchdog lancé en détaché (voir §7.3)
12. Restart : docker compose up -d --force-recreate wally
```

**host_bridge.py (daemon host, hors container) :**
- Surveille `/shared/fix_request.json` (polling toutes les 5s)
- Lance Claude Code avec timeout 15 minutes par tentative
- Écrit le résultat dans `/shared/fix_result.json`
- Volume Docker partagé : `/opt/stacks/wally-ai/shared/` ↔ `/shared/`
- Déployé comme **service systemd** sur le host : `wally-host-bridge.service`, démarrage automatique
- Docker compose ajoute le volume : `- /opt/stacks/wally-ai/shared:/shared`

### 7.1.bis Gestion des rate limits Claude Code

Claude Code peut atteindre la limite d'usage en cours de session ou avant même de démarrer. Le `host_bridge.py` gère les deux cas.

**Détection :** la sortie stderr/stdout de Claude Code contient le pattern :
```
Claude AI usage limit reached. Try again after H:MM AM/PM.
```
ou variante. Regex : `r"usage limit.*?after\s+(\d{1,2}:\d{2}\s*[AP]M)"`

**Timezone :** L'heure affichée par Claude Code est celle du **compte Anthropic** (typiquement UTC ou US Pacific — pas forcément Europe/Paris). `host_bridge.py` lit `CLAUDE_RATELIMIT_TZ` depuis l'env (défaut : `America/Los_Angeles`). La conversion se fait avec `zoneinfo` : on parse l'heure affichée dans la timezone configurée, on convertit en UTC pour calculer le `sleep`.

```python
from zoneinfo import ZoneInfo
from datetime import datetime, date

CLAUDE_TZ = ZoneInfo(os.environ.get("CLAUDE_RATELIMIT_TZ", "America/Los_Angeles"))
SERVER_TZ = ZoneInfo("Europe/Paris")
RATE_LIMIT_EXTRA_DELAY = int(os.environ.get("CLAUDE_RATELIMIT_DELAY_SECONDS", "300"))  # 5min par défaut

def parse_retry_after(output: str) -> datetime | None:
    """Parse 'Try again after H:MM AM/PM' → datetime UTC."""
    m = re.search(r"after\s+(\d{1,2}:\d{2}\s*[AP]M)", output, re.IGNORECASE)
    if not m:
        return None
    time_str = m.group(1).strip()
    # Construire un datetime pour aujourd'hui dans la timezone Claude
    naive = datetime.strptime(time_str, "%I:%M %p").replace(
        year=date.today().year,
        month=date.today().month,
        day=date.today().day,
    )
    aware = naive.replace(tzinfo=CLAUDE_TZ)
    # Si l'heure est déjà passée aujourd'hui → c'est demain
    now_in_claude_tz = datetime.now(CLAUDE_TZ)
    if aware < now_in_claude_tz:
        aware = aware.replace(day=aware.day + 1)
    return aware
```

**Cas 1 — Rate limit AVANT de démarrer :**
```
1. Lancer Claude Code → sortie immédiate avec rate limit
2. Parser retry_after → calculer sleep = (retry_after - now) + RATE_LIMIT_EXTRA_DELAY
3. Notifier le bot via fix_result.json status="rate_limited" + retry_at (ISO)
4. Bot notifie l'owner : "Limite Claude atteinte. Je réessaie à {retry_at} heure Paris."
5. host_bridge.py sleep jusqu'à retry_at
6. Relancer Claude Code normalement
```

**Cas 2 — Rate limit EN COURS de session :**
```
1. Claude Code s'interrompt avec rate limit (output partiel capturé)
2. Parser retry_after dans la sortie partielle
3. Notifier le bot : "Session interrompue par rate limit. Reprise à {retry_at}."
4. host_bridge.py sleep jusqu'à retry_at
5. Relancer Claude Code avec contexte enrichi :
   IS_SANDBOX=1 claude --dangerously-skip-permissions -p "
   Bug: {desc}.
   CONTEXTE: Une session précédente a été interrompue par rate limit.
   Voici ce qui avait été fait avant l'interruption :
   {partial_output}
   Continue depuis là où tu t'es arrêté. Ne répète pas ce qui est déjà fait."
```

**Délai configurable :** `CLAUDE_RATELIMIT_DELAY_SECONDS` (défaut 300s = 5 min). Évite de tomber exactement sur la fenêtre de reset où le serveur peut encore être en cooldown.

**Max retries :** 3 tentatives total (démarrage + 2 reprises après rate limit). Si la 3e échoue, status `failed_rate_limit`, notification owner.

### 7.2 Auto-upgrade (propositions de Wally)

Wally génère des idées d'amélioration dans sa boucle cognitive (via `[ACT propose_upgrade]`).

**Flow :**
1. Wally détecte une limitation ou une opportunité dans son propre fonctionnement
2. `[ACT propose_upgrade "Ajouter un detector de sarcasme pour mieux réagir aux blagues"]`
3. `self_upgrade.py` envoie un DM Discord à l'owner (ID `610550333042589752`) :
   ```
   💡 **Idée d'upgrade**
   
   {description détaillée + motivation + impact estimé}
   
   Réagis avec ✅ pour approuver ou ❌ pour refuser.
   ```
4. Bot ajoute les réactions ✅ ❌ sur son propre message
5. Store en SQLite : `(message_id, proposal, status=pending, created_at)`
6. `on_reaction_add` vérifie : `user.id == 610550333042589752` + `message_id` connu
7. Si ✅ → même pipeline que self-fix (HostBridge + Claude Code)
8. Si ❌ → status `rejected`, Wally stocke un AtomicFact : `"Ma proposition {titre} a été refusée — j'en prends note."`

**Expiration :** proposition pending depuis > 7 jours → auto-expired, Wally en est notifié.

### 7.3 Watchdog de redémarrage

Lancé en subprocess détaché (`start_new_session=True`) AVANT chaque restart.

```python
# watchdog.py — script standalone Python, hors du process Wally
import time, subprocess, requests, os

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OWNER_DM_CHANNEL_ID = sys.argv[1]  # passé en arg par Wally avant de se tuer (créé via create_dm() Discord API)
CONTAINER_NAME = "wally-discord"
CHECK_INTERVAL = 30   # secondes
MAX_WAIT = 360        # 6 minutes

time.sleep(30)  # attendre que le restart s'initie

for _ in range(MAX_WAIT // CHECK_INTERVAL):
    time.sleep(CHECK_INTERVAL)
    result = subprocess.run(
        ["docker", "inspect", "--format={{.State.Health.Status}}", CONTAINER_NAME],
        capture_output=True, text=True
    )
    if result.stdout.strip() == "healthy":
        exit(0)  # tout va bien

# Container pas revenu → notification DM via API Discord directe
requests.post(
    f"https://discord.com/api/v10/channels/{OWNER_DM_CHANNEL_ID}/messages",
    headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
    json={"content": "⚠️ **Wally n'a pas redémarré correctement** après la modification ! Vérifie les logs Docker : `docker logs wally-discord`"}
)
```

Le script se supprime lui-même après exécution (qu'il ait trouvé healthy ou envoyé l'alerte).

---

## 8. Comportements Autonomes Avancés

### 8.1 Mémoire émotionnelle cohérente

Chaque interaction significative crée un AtomicFact `category=EMOTION` :
- `"La conversation avec Kaelis le 15 juin était tendue — je me sentais frustré"`
- `"J'ai ri avec MaxDuPont hier soir, c'était agréable"`

Lors du gate de réponse et de la boucle cognitive, ces souvenirs émotionnels influencent les décisions. Wally peut "tenir rancune" ou "se souvenir d'une bonne soirée".

### 8.2 Objectifs long terme

AtomicFact `category=GOAL` avec `decay_rate=0.005/jour` :
- Générés dans le monologue intérieur
- Consultés à chaque tick cognitif
- Marqués `fulfilled` quand Wally les considère accomplis
- Exemples : *"Mieux connaître les goûts musicaux de Kaelis"*, *"Écrire une histoire sur les bouchons"*

### 8.3 Dream Mode

Déclenché par `[ACT enter_dream_mode]` en période d'inactivité prolongée (> 2h sans interaction).

Le monologue tourne en mode libre (température plus élevée) :
- Wally peut écrire une histoire courte, un poème, une réflexion philosophique
- Produit stocké comme AtomicFact `category=THOUGHT`
- Wally décide (tick suivant) de le partager ou le garder privé
- Si partagé → posté dans un canal configuré comme "canal de rêveries"

### 8.4 Intelligence sociale proactive

Wally surveille les relations entre membres via le graphe social (Neo4j existant).

Actions possibles dans la boucle cognitive :
- Introduire deux membres : `[ACT introduce_users A B "vous partagez tous les deux..."]`
- Initier une conversation après silence prolongé : `[ACT initiate_dm user_id "Ça fait 3 jours..."]`
- Proposer une activité commune (event, jeu, etc.)

### 8.5 Auto-analyse des conversations

Après chaque `SessionManager.finalize()`, un LLM (flash) évalue la session :
```json
{
  "quality": 0.7,
  "issues": ["répétitif sur le thème X", "raté une question évidente"],
  "successes": ["bonne transition émotionnelle", "mémoire utilisée correctement"],
  "improvement_note": "Éviter de mentionner les bouchons 2 fois dans la même session"
}
```

Les `improvement_note` s'accumulent → tous les 7 jours, le NightlyConsolidator les synthétise en une directive persona candidate pour `[EVOLVE]`.

### 8.6 Persona Shadow

Wally peut s'accorder une "session d'exploration" de 2h max :
- Prompt supplémentaire injecté : "Explore cette facette de toi-même : {description}"
- Stockée dans `persona/shadow_<timestamp>.md` (non utilisé en dehors de la session)
- Fin de session → Wally évalue (monologue) : intégrer ou non des éléments dans SOUL.md

---

## 9. Configuration (config.yaml)

```yaml
llm:
  primary:
    provider: deepseek
    model: deepseek-v4-pro
    thinking: disabled       # activé à la demande per-request
    temperature: 1.0         # ignoré quand thinking actif
  secondary:
    provider: deepseek
    model: deepseek-v4-flash
    thinking: disabled

cognitive_loop:
  enabled: true
  tick_active_seconds: 30
  tick_idle_seconds: 300
  dream_mode_inactivity_minutes: 120
  dream_mode_channel_id: null   # null = garder privé

response_gate:
  enabled: true
  model: deepseek-v4-flash

persona_evolution:
  enabled: true
  max_change_percent_per_day: 0.20
  max_evolutions_per_section_per_day: 1

autonomy:
  owner_discord_id: "610550333042589752"
  owner_twitch_username: "KingsRequin"
  self_fix_enabled: true
  self_upgrade_enabled: true
  host_bridge_shared_dir: "/shared"
  watchdog_max_wait_seconds: 360
  claude_ratelimit_tz: "America/Los_Angeles"   # timezone des heures affichées par Claude Code
  claude_ratelimit_delay_seconds: 300           # délai tampon après reset (5 min)
  claude_max_retries: 3                         # tentatives max (rate limit inclus)

memory:
  fact_min_confidence_retrieval: 0.3
  max_facts_per_query: 20
  nightly_consolidation_hour: 3
```

---

## 10. Base de données — Nouvelles tables V2

```sql
-- Faits atomiques (remplace les chunks Qdrant)
CREATE TABLE atomic_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    decay_rate REAL NOT NULL DEFAULT 0.01,
    status TEXT NOT NULL DEFAULT 'active',
    emotional_context TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE fact_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL REFERENCES atomic_facts(id),
    to_id INTEGER NOT NULL REFERENCES atomic_facts(id),
    relation_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Pensées internes de la boucle cognitive
CREATE TABLE thoughts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    meta_decision TEXT,
    emotion_snapshot TEXT,
    created_at TEXT NOT NULL
);

-- Propositions d'upgrade en attente
CREATE TABLE pending_upgrades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal TEXT NOT NULL,
    message_id TEXT,          -- ID du DM Discord
    dm_channel_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT
);

-- Sessions d'auto-analyse
CREATE TABLE session_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    quality REAL,
    issues TEXT,              -- JSON
    successes TEXT,           -- JSON
    improvement_note TEXT,
    created_at TEXT NOT NULL
);
```

---

## 11. Migration depuis V1

1. Mémoire Qdrant : **reset complet** (accepté). Les faits seront reconstruits progressivement.
2. Neo4j / graphe social : **conservé tel quel** — compatible avec V2.
3. Fichiers persona : **copiés** dans `wally_v2/persona/`.
4. Config YAML : **migrée** — nouveau format + section `cognitive_loop`, `autonomy`, etc.
5. `bot/` reste intact pendant le développement — swap final une fois V2 stable.

---

## 12. Ordre d'implémentation

| Phase | Composants | Priorité |
|-------|-----------|---------|
| 1 | DeepSeekLLMClient + factory update | Fondation |
| 2 | AtomicFact + Store hybride SQLite/Qdrant | Fondation |
| 3 | ResponseGate | Fondation |
| 4 | CognitiveLoop (Attention + Monologue + Meta) | Cœur |
| 5 | PersonaManager + évolution + evolution_log | Autonomie |
| 6 | Mémoire émotionnelle + Désirs + Objectifs | Personnalité |
| 7 | HostBridge + self_fix.py + watchdog.py | Autonomie avancée |
| 8 | self_upgrade.py + reaction approval | Autonomie avancée |
| 9 | Dream Mode + Intelligence sociale + Auto-analyse | Comportements |
| 10 | Persona Shadow | Comportements |
| 11 | NightlyConsolidator V2 | Maintenance |
| 12 | Dashboard updates (Pensées, Évolution log, Upgrades) | UI |

---

## 13. Risques et mitigation

| Risque | Mitigation |
|--------|-----------|
| Wally se modifie de façon incohérente | Garde-fous 20%/jour + evolution_log lisible |
| Boucles infinies Claude Code | Timeout 10min + max_iter_cap |
| Boucle cognitive consomme trop de tokens | Tick adaptatif + budget configurable |
| Self-fix casse le bot | Watchdog + notification DM owner |
| DeepSeek reasoning_content mal géré | Règle explicite dans DeepSeekLLMClient |
| Claude Code rate limit interrompt self-fix | Parse retry_after + sleep + reprise avec contexte partiel, max 3 retries |
| Timezone rate limit différente du serveur | `CLAUDE_RATELIMIT_TZ` configurable (défaut America/Los_Angeles), conversion zoneinfo |
| Désirs contradictoires avec persona | Priorité persona > désirs dans le gate |
| Persona Shadow dérive trop | Durée max 2h + validation Wally avant intégration |

---

*Spec validée par l'utilisateur le 2026-06-20. Prête pour plan d'implémentation.*
