# Auto-modification autonome de Wally via Claude Code

**Date :** 2026-06-24
**Branche :** `feat/site-redesign-arcade`
**Statut :** design validé, prêt pour plan d'implémentation

---

## 1. Contexte & intention

Wally possède déjà une boucle cognitive autonome (`cognitive_loop.py`) qui, à chaque tick,
assemble un contexte (émotions, goals, pensées, relations…), raisonne via un LLM unique
(`reasoning_agent.py`), et émet des décisions `[THINK|SPEAK|ACT|EVOLVE|SLEEP]` dispatchées par
`action_dispatcher.py`.

Wally tient aussi des **goals** numérotés (faits `category=GOAL`) qui représentent ses
préoccupations et ses **faiblesses perçues** — par ex. le goal réel `#1109 : « est-ce que je
vois les réactions emoji ou seulement le texte ? »`.

**But de ce chantier :** permettre à Wally de **décider lui-même** de corriger une de ses
faiblesses de code, **après autorisation explicite du créateur**, en déléguant l'implémentation
à **Claude Code** (et non plus à DeepSeek générant un diff).

### Ce qui existe déjà
- L'action `code_fix` est câblée dans `action_dispatcher.py:361-381` et testée, mais
  **non documentée dans le prompt** `reasoning_system.md` → Wally ignore qu'elle existe.
- `self_fix.py` génère aujourd'hui un diff via `llm_secondary` (DeepSeek), l'envoie en DM pour
  approbation ✅/❌, puis `git apply` + `docker rebuild` via le **host bridge**.
- Le **host bridge** : daemon root sur l'hôte (`scripts/host_bridge_daemon.py`,
  `/opt/stacks/wally-ai`) écoutant un socket Unix, exposant `/git-apply`, `/docker-rebuild`,
  `/docker-restart`. Client côté conteneur : `bot/intelligence/host_bridge.py`.
- `claude` CLI v2.1.187 est présent sur l'hôte (`/root/.local/bin/claude`), le daemon tourne en
  root, et `IS_SANDBOX=1` est dans l'environnement de l'hôte.

### Ce qui change
- La génération de diff par DeepSeek est **abandonnée**. Claude Code fait le vrai travail.
- Le déclencheur n'est plus un outil conversationnel réservé au créateur, mais une **action
  cognitive** que Wally choisit lui-même.
- L'approbation humaine passe au niveau de **l'intention** (« as-tu le droit de te modifier pour
  ça ? »), pas du diff final.

---

## 2. Modèle d'autorité (cœur de la conception)

| Acteur | Pouvoir |
|--------|---------|
| **Wally** | décide *quoi* corriger — autonomie d'initiative (boucle cognitive) |
| **Créateur** | autorise *si* ça se fait — contrôle d'exécution (✅/❌ en DM) |
| **Claude Code** | décide *comment* — autonome après le ✅ (`--dangerously-skip-permissions`) |

**Garde-fou central :** le DM d'autorisation affiche **le texte exact du `goal`** qui sera passé
à Claude Code. Le créateur lit l'intention avant d'approuver. Wally peut *vouloir* n'importe
quoi, il ne peut *rien exécuter* sans le ✅. C'est la barrière contre toute dérive
(« demain il décide de hacker un site pour son bon fonctionnement »).

`--dangerously-skip-permissions` signifie : une fois l'intention approuvée, le créateur ne valide
**pas** chaque modification de fichier. Il a validé le but, pas les étapes.

---

## 3. Flux complet

```
┌─ COGNITIVE LOOP (autonome) ──────────────────────────────────────────┐
│ Wally raisonne sur ses goals/faiblesses (ex. #1109 réactions emoji)  │
│ → émet  [ACT self_upgrade {"goal": "voir les réactions emoji ..."}]  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ parse_decisions → MetaDecision
                                ▼
┌─ ActionDispatcher._act("self_upgrade") ──────────────────────────────┐
│ récupère bot.self_fix ; fire async  self_fix.request_upgrade(goal)   │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌─ SelfFix.request_upgrade(goal) ──────────────────────────────────────┐
│ 1. anti-emballement : refuse si un upgrade est déjà en attente,      │
│    ou si ce goal a déjà été refusé récemment (fait mémoire).         │
│ 2. DM créateur :                                                     │
│    "🧠 Faiblesse repérée : «<goal>». Je veux me modifier pour la     │
│     corriger (Claude Code). Tu autorises ? ✅ / ❌"                    │
│ 3. await réaction (timeout configurable, défaut 1h)                  │
│    ├─ ❌ / timeout → DM "ok, j'abandonne" + mémorise le refus → STOP  │
│    └─ ✅ → continue                                                   │
│ 4. DM "👍 Je m'y mets, Claude Code travaille…"                        │
│ 5. job_id = bridge.claude_run(goal)                                  │
│ 6. poll bridge.claude_status(job_id) toutes ~10s jusqu'à terminal    │
│ 7. terminal :                                                        │
│    ├─ succès + (working tree sale OU Claude a déjà committé) →        │
│    │   bridge commit (no-op si déjà committé) + docker_rebuild       │
│    │   → DM "✅ Fait : <résumé Claude> · <N fichiers> · je redémarre" │
│    ├─ succès sans aucun changement → DM "Rien à changer finalement"  │
│    └─ échec → DM "❌ <erreur>"                                         │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Composants & interfaces

### 4.1 `scripts/host_bridge_daemon.py` (HÔTE, root — restart daemon requis)

Ajoute deux endpoints POST (toujours derrière `X-Bridge-Secret`) + gestion de job.

- **`POST /claude-run`** — body `{"goal": "<texte>"}`
  - Refuse si un job est déjà en cours (verrou simple : un seul job global) → `409`.
  - Valide que `goal` est non vide.
  - Capture `git rev-parse HEAD` (avant) pour détecter un commit ultérieur de Claude.
  - Spawn en arrière-plan (`subprocess.Popen`, `start_new_session=True`) :
    ```
    IS_SANDBOX=1 claude --dangerously-skip-permissions -p "<goal>" \
        --output-format json
    ```
    `cwd=REPO_ROOT`, `env` incluant `IS_SANDBOX=1` et le PATH de root (claude résolu).
    stdout+stderr redirigés vers un fichier de job (`<jobs_dir>/<job_id>.out`).
  - Génère un `job_id` (uuid4), persiste l'état en mémoire process : `{state: "running",
    pid, head_before, started_at}`.
  - Retourne `200 {"job_id": "..."}`.

- **`POST /claude-status`** — body `{"job_id": "..."}`
  - Si inconnu → `404`.
  - Si process encore vivant → `{"state": "running"}`.
  - Si terminé → lit le code retour + la sortie ; renvoie
    `{"state": "done"|"failed", "exit_code": N, "result": "<dernier message/summary>",
      "changed": bool, "head_changed": bool, "output_tail": "<derniers ~2000 char>"}`.
    - `result` : extrait du JSON `--output-format json` de claude (champ `result`/dernier
      message assistant) ; fallback = tail de la sortie brute.
    - `changed` : `git status --porcelain` non vide.
    - `head_changed` : `git rev-parse HEAD` != `head_before`.

- **`POST /claude-commit`** — body `{"goal": "..."}`
  - `git add -A && git commit -m "self-upgrade: <goal>"` si working tree sale.
  - No-op si rien à committer. Retourne le hash du commit (ou `head_changed` si Claude a déjà
    committé).

> **Note concurrence** : le daemon est un `socketserver.UnixStreamServer` mono-thread. Le modèle
> spawn-and-poll évite de bloquer le daemon pendant les minutes de run Claude (au lieu d'un
> endpoint synchrone qui tiendrait la socket ouverte). Le verrou « 1 job » empêche deux runs
> concurrents.

Constantes : `JOBS_DIR` (ex. `REPO_ROOT/data/claude_jobs/`), `CLAUDE_BIN` (résolu/configurable),
`CLAUDE_TIMEOUT` (ex. 1800s, le daemon marque `failed` si dépassé).

### 4.2 `bot/intelligence/host_bridge.py` (client conteneur)

Ajoute :
- `async claude_run(goal: str) -> str` → POST `/claude-run`, retourne `job_id`. Lève
  `HostBridgeError` sur 409 (job déjà en cours) ou autre.
- `async claude_status(job_id: str) -> dict` → POST `/claude-status`, retourne le dict d'état.
- `async claude_commit(goal: str) -> dict` → POST `/claude-commit`.

Timeouts httpx courts (ces appels sont rapides ; le run lui-même est asynchrone côté daemon).

### 4.3 `bot/intelligence/self_fix.py` (réécriture)

Remplace `FixRequest`/`fix()`/`resolve()`/diff par :

```python
@dataclass
class UpgradeRequest:
    goal: str

class SelfFix:
    def __init__(self, bridge, bot, *, poll_interval=10, approval_timeout=3600): ...

    async def request_upgrade(self, req: UpgradeRequest) -> None:
        # 1. anti-emballement (pending unique + refus mémorisés)
        # 2. DM autorisation (montre le goal exact) + réactions ✅/❌
        # 3. await réaction (timeout) — réutilise _await_reaction
        # 4. ❌/timeout → DM + _record_decline(goal) → return
        # 5. ✅ → DM "je m'y mets"
        # 6. job_id = bridge.claude_run(goal)
        # 7. poll claude_status jusqu'à terminal (avec garde temps max)
        # 8. commit + rebuild + DM compte-rendu (ou DM no-change / erreur)
```

- `llm_secondary` n'est plus injecté (plus de génération de diff).
- Réutilise la robustesse acquise : tout chemin d'échec envoie un DM (`_notify`), jamais de
  `return` silencieux ; wrap global try/except.
- L'anti-emballement s'appuie sur le fact store (un fait `self:upgrade_declined` ou un statut)
  et un flag d'instance `_pending` pour le « un seul à la fois ».

### 4.4 `bot/intelligence/action_dispatcher.py`

- Renomme/reshape la branche `code_fix` → **`self_upgrade`** prenant `{"goal": "..."}`.
- Supprime le check `requester_discord_id == OWNER` (la porte est désormais le DM d'autorisation ;
  Wally est toujours l'initiateur).
- `asyncio.create_task(self_fix.request_upgrade(UpgradeRequest(goal=args.get("goal", ""))))`,
  après garde `goal` non vide + `self_fix` disponible.

### 4.5 `bot/intelligence/persona/prompts/reasoning_system.md`

Documente l'action dans la section DÉCIDE, avec garde-fous explicites :

```markdown
- `[ACT self_upgrade {"goal": "<description claire de la capacité à ajouter/corriger>"}]`
  — quand tu identifies une **vraie limite technique de ton code** que seul un changement de
  code peut résoudre (ex. « je ne perçois pas les réactions emoji »). Décris le BUT, pas le
  comment — Claude Code s'en charge. Ton créateur doit **autoriser** chaque self-upgrade en DM ;
  s'il refuse, n'insiste pas et ne le reproposes pas. N'utilise PAS ceci pour ce qui relève de
  ta personnalité ou de ton ton (→ `[EVOLVE]`), ni pour des envies vagues.
```

### 4.6 `bot/discord/handlers.py`

- **Supprime** la définition d'outil `request_self_modification` (lignes ~85-115) et son
  handler (~1004-1024) — modèle obsolète (un seul chemin : Wally décide → créateur autorise).
- **Conserve** l'amélioration de `_fire()` (log des exceptions de tâches de fond) — utile
  généralement.
- Retire l'import devenu inutile si `OWNER_DISCORD_ID`/`FixRequest` n'y servent plus.

### 4.7 `bot/discord/bot.py`

- Construction `SelfFix(bridge, self, ...)` sans `llm_secondary`.
- Le reste du câblage (bridge socket/secret, accès via `bot.self_fix`) inchangé.

---

## 5. Sécurité & garde-fous

1. **Autorisation d'intention** : aucun run Claude sans ✅ du créateur ; le DM affiche le `goal`
   verbatim. Surface de revue = ce texte.
2. **Anti-emballement** : un seul upgrade en attente ; refus mémorisés pour ne pas reproposer le
   même but ; l'anti-harcèlement DM existant s'applique.
3. **Verrou daemon** : un seul job Claude à la fois.
4. **Bridge secret** : endpoints `/claude-*` derrière `X-Bridge-Secret` comme le reste.
5. **Rollback** : commit avant rebuild → retour arrière manuel possible (`git revert`).
6. **Risque résiduel accepté** (choix explicite du créateur) : Claude tourne en
   `--dangerously-skip-permissions` en root, scope = le `goal` approuvé. Une interprétation large
   du goal par Claude reste possible ; mitigée par la revue d'intention + le fait que le créateur
   formule/voit le but. Pas de garde-fou réseau supplémentaire dans cette itération.
7. **Pas de validation finale du diff** (choix « autonome après ✅ ») : mitigation = consigne dans
   le `goal`/prompt de lancer `pytest` et de ne pas casser le build ; le commit permet le rollback.

---

## 6. Gestion d'erreurs

Tous les chemins d'échec → **DM au créateur**, jamais de silence :
- bridge indisponible / 409 job en cours / claude introuvable,
- run Claude échoué (exit ≠ 0) → DM avec le tail de sortie,
- aucun changement produit → DM informatif (pas de rebuild),
- échec commit/rebuild → DM erreur (l'état reste committé localement).
Wrap global try/except dans `request_upgrade`, `_fire` loggue les exceptions de tâche.

---

## 7. Tests

- `tests/intelligence/core/test_self_fix.py` réécrit pour le nouveau flux :
  - autorisation ✅ → `claude_run` appelé, puis `docker_rebuild` après job `done`+`changed`.
  - autorisation ❌ → `claude_run` **non** appelé + refus mémorisé.
  - timeout → pas de run + DM d'annulation.
  - job `failed` → DM erreur, pas de rebuild.
  - job `done` sans changement → DM no-change, pas de rebuild.
  - anti-emballement : 2e `request_upgrade` pendant un pending → ignorée.
- `test_action_dispatcher_*` : `self_upgrade {"goal"}` → `self_fix.request_upgrade` appelé ;
  garde `goal` vide / self_fix absent.
- Daemon : test léger du parsing d'état (changed/head_changed) si faisable hors hôte, sinon
  vérification manuelle documentée.

---

## 8. Implémentation phasée (≤5 fichiers/phase)

- **Phase 1 — Bridge (transport)** : `host_bridge_daemon.py` (+`/claude-run` `/claude-status`
  `/claude-commit`, jobs, verrou) + `host_bridge.py` (client). Vérif : daemon redémarré, run
  Claude manuel via curl sur le socket OK. *(2 fichiers)*
- **Phase 2 — SelfFix + dispatch** : `self_fix.py` réécrit, `action_dispatcher.py` reshape,
  `bot.py` câblage. Vérif : `pytest test_self_fix.py` vert. *(3 fichiers)*
- **Phase 3 — Prompt + nettoyage handlers** : `reasoning_system.md` (doc action),
  `handlers.py` (suppression outil, garde `_fire`). Vérif : suite de tests complète + Wally
  émet `self_upgrade` en conditions réelles. *(2 fichiers)*

Chaque phase : vérification + approbation avant la suivante. Déploiement backend = rebuild image
(le daemon hôte se restart séparément).

---

## 9. Points hors scope (YAGNI)

- Échange interactif temps réel Claude ↔ Wally ↔ créateur (« one-shot simple » retenu).
- Stage LLM dédié « analyse de faiblesse » : superflu, Wally raisonne déjà sur ses goals et peut
  émettre l'action directement.
- Validation du diff final / branches jetables : « autonome après ✅ » retenu, working tree live.
- Garde-fou réseau autour de Claude : accepté comme risque résiduel.
