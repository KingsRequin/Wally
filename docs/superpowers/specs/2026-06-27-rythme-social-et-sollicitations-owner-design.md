# Rythme social appris + discipline des sollicitations vers l'owner

**Date :** 2026-06-27
**Branche :** `feat/site-redesign-arcade`
**Statut :** design validé, en attente de relecture avant plan d'implémentation

## Problème

Wally poste sans aucune conscience de l'heure :

1. **Messages spontanés nocturnes.** La boucle cognitive idle (`cognitive_loop._tick`)
   déclenche des SPEAK toutes les 5 min – 1 h, nuit comme jour. Aucune des conditions
   de suppression du SPEAK ne regarde l'heure ni la réceptivité de l'audience.
2. **Self-fix nocturne qui « se refuse tout seul ».** Quand Wally décide `[ACT code_fix]`,
   `self_fix.py` DM l'owner et attend une réaction ✅/❌ avec un **timeout d'1 h**. Sur
   non-réponse, il envoie « j'abandonne » **et blackliste le goal** (`_declined.add(norm)`)
   → jamais reproposé. L'owner dormait → la demande s'est auto-annulée.
3. **Empilement de sollicitations.** La même nuit : 1 demande de self-fix, puis une
   question en DM (« quels animes tu regardes »), puis la même question en public sur
   le serveur — alors que rien n'avait reçu de réponse. Wally insiste comme s'il
   harcelait.

## Principe directeur (non négociable)

**Coder le mécanisme d'apprentissage, jamais les valeurs en dur.** Pas de créneau
« nuit = 0h–6h » figé. Wally *découvre* ses rythmes par observation statistique et les
fait évoluer dans le temps. La « nuit » émerge comme un creux de réceptivité, elle n'est
jamais déclarée. North Star : libre, humain, apprend au fil du temps, décide librement.
Voir mémoire `feedback_emergent_over_hardcode`.

---

## Vue d'ensemble

Deux chantiers indépendants, reliés au même symptôme :

- **Partie A — Rythme social appris** : un modèle de « réceptivité de l'audience
  maintenant » (0→1), appris par EMA, qui module la **parole publique spontanée** (cadence,
  conscience injectée, amortisseur probabiliste). Couvre le symptôme #1 et la question
  publique de #3.
- **Partie B — Discipline des sollicitations vers l'owner** : retirer l'auto-refus du
  self-fix + un portail de backpressure « un seul fil de sollicitation vers l'owner à la
  fois ». Couvre #2 et la partie DM de #3.

Le chemin **réactif** (on parle à Wally / on le DM) n'est JAMAIS touché : il répond
toujours, nuit comprise. Seules les initiatives spontanées sont régulées.

---

## Partie A — Rythme social appris

### A1. Service `SocialRhythm` (nouveau : `bot/intelligence/social_rhythm.py`)

Rôle unique : apprendre et restituer une **réceptivité ∈ [0,1]** pour l'instant présent.

**Découpage temporel — « créneaux ».**
`heure (0–23) × type-de-jour {semaine, weekend}` = **48 créneaux**. Capture la distinction
weekend (demandée par l'owner) tout en convergeant ~3,5× plus vite que 24×7 = 168 créneaux.
Fuseau : réutilise `config.emotions.circadian.timezone` (`Europe/Paris`) — aucun nouveau
réglage en dur.

**Deux signaux appris par créneau, en moyenne mobile exponentielle (EMA) :**
- `ambient` : volume de messages reçus dans les canaux → vivacité de l'audience à cette
  heure. Incrémenté à chaque message entrant.
- `engagement` : quand Wally parle spontanément, est-il **répondu** (récompense +1) ou
  **ignoré** (signal 0 ) ? Vrai signal d'apprentissage social.

L'EMA (facteur α configurable, défaut p.ex. 0.1) garantit l'évolution dans le temps : le
comportement récent pèse plus, donc le modèle suit la dérive des habitudes sans reset.

**Calcul de la réceptivité courante :**
```
ambient_norm = normalisation de ambient[bin] vs le max appris sur tous les bins
engagement_rate = engagement[bin]                      # déjà ∈ [0,1]
observed = w_a * ambient_norm + w_e * engagement_rate  # w_a + w_e = 1, p.ex. 0.5/0.5
conf = min(1, n_obs[bin] / N_CONF)                     # confiance ~ nb d'observations
receptivity = 0.5 * (1 - conf) + observed * conf       # prior doux 0.5 écrasé par les données
```
Lissage : `observed` mélangé avec les créneaux d'heures voisines (noyau simple) pour
combler la sparsité d'un petit serveur.

**Démarrage à froid (compromis assumé).** Tant que `conf` est bas, `receptivity ≈ 0.5`
(comportement modéré, ni muet ni bavard). Les tout premiers jours, un message nocturne
reste possible ; les creux se creusent en quelques jours. **Backfill optionnel au boot :**
rejouer une fois l'historique de `logs/conversations/` (déjà horodaté) pour pré-chauffer
les `ambient[bin]` — Wally « sait » dès le départ quand le serveur vit, sans rien coder en
dur.

**Persistance.** Table `social_rhythm_bins` ajoutée à `bot/db/schema_v2.py` (pattern
idempotent existant). Une ligne par créneau : `bin_key, ambient, engagement, n_obs,
updated_at`. Chargée au boot, écrite sur mise à jour (best-effort, ne casse jamais le tick).

**Interface publique (esquisse) :**
```python
class SocialRhythm:
    def record_incoming(self, when: datetime) -> None        # signal ambient
    def record_spontaneous_outcome(self, answered: bool, when: datetime) -> None  # engagement
    def receptivity(self, when: datetime | None = None) -> float   # 0→1 pour le bin courant
    def describe(self, when=None) -> str  # phrase FR pour la conscience injectée
    async def load(self, db) -> None
    async def persist(self, db) -> None   # ou flush périodique
```

### A2. Consommateurs (dans `cognitive_loop.py` + `attention_agent.py`)

1. **Cadence (somnolence)** — `cognitive_loop._tick_interval()` : basse réceptivité allonge
   le plafond du vagabondage idle (multiplie le `hi` actuel). Calme/nuit → Wally somnole,
   pense plus lentement. *Accepté que la cognition privée ralentisse aussi, pas seulement
   l'expression.*

2. **Conscience injectée** — nouveau champ `AttentionContext.social_receptivity` (str ou
   petit objet) → une phrase en clair dans le contexte cognitif via `SocialRhythm.describe()`,
   p.ex. : *« Il est tard, un samedi : historiquement le serveur est très calme à cette
   heure et tes derniers messages nocturnes sont restés sans réponse. »* Wally lit et décide
   librement. **Fix au passage :** `attention_agent.build_context` calcule `time_of_day` en
   **UTC** (bug) → le passer en `Europe/Paris`.

3. **Amortisseur probabiliste du SPEAK** — `cognitive_loop._tick()`, avant d'émettre un SPEAK
   spontané : tirage `random() < p(receptivity)`. Basse réceptivité → `p` bas → message
   **rare mais pas impossible**. Aucun seuil « nuit » codé : `p` sort des stats apprises.
   Chaque suppression journalisée via `_log_cog("speak_suppressed", reason="réceptivité
   apprise 0.08", …)` pour audit. S'ajoute aux suppressions existantes (canal silencieux,
   cooldowns, anti-récap), ne les remplace pas.

4. **Alimentation des signaux** :
   - `record_incoming` appelé depuis `notify_activity` (chaque message perçu).
   - `record_spontaneous_outcome` : la boucle suit déjà `_spontaneous[ch]["unanswered"]`.
     Quand `unanswered` repasse à 0 (quelqu'un a répondu) → `answered=True` ; quand un
     message spontané vieillit sans réponse (compteur atteint le plafond / fenêtre écoulée)
     → `answered=False`.

### A3. Câblage DI

`SocialRhythm` construit dans `bot/bootstrap.py`, chargé depuis la DB au boot, injecté dans
`CognitiveLoop` et `AttentionAgent`. Optionnel `feed`/`conv_log` pour l'audit.

---

## Partie B — Discipline des sollicitations vers l'owner

### B1. Retirer l'auto-refus du self-fix (`self_fix.py`)

- Supprimer le **timeout d'1 h** de `_await_reaction` : la demande reste ouverte jusqu'à une
  vraie réaction ✅/❌. Implémentation : attente longue (p.ex. 72 h) **ou** persistance de la
  demande + écoute de réaction, plutôt qu'une coroutine parkée indéfiniment. À trancher au
  plan ; préférence pour persister via `pending_upgrades` (table existante) et ne pas tenir
  une coroutine vivante éternellement.
- Sur non-réponse : **ne plus blacklister** (`_declined.add(norm)` retiré de la branche
  timeout) et ne plus envoyer « j'abandonne ». Statut `deferred`/en attente, pas `declined`.
- Le message de self-fix EST une sollicitation owner → il alimente le portail B2.

### B2. Portail de backpressure owner (nouveau : `OwnerOutreachGate`)

Règle : **au plus une sollicitation vers l'owner sans réponse à la fois, tout type confondu**
(self-fix, questions DM). Tant qu'une est en suspens, les nouvelles sollicitations ne sont
**pas envoyées** (« en attente » = simple retenue). Quand l'owner répond, le portail se
libère et la **cognition re-soulève d'elle-même** ce qui compte encore (option (ii) validée —
PAS de file qui rejoue).

**Interface :**
```python
class OwnerOutreachGate:
    def is_blocked(self) -> bool          # une sollicitation owner est en suspens ?
    def mark_sent(self) -> None           # Wally vient d'envoyer un DM/self-fix à l'owner
    def clear(self) -> None               # l'owner a répondu en DM
```
État minimal en mémoire (un booléen + timestamp). Pas de persistance nécessaire : au
redémarrage, repartir « non bloqué » est sûr (au pire un message de plus, jamais un
empilement).

**Points de branchement :**
- `action_dispatcher._dm()` : si `gate.is_blocked()` → ne pas envoyer, journaliser
  `DM_SUPPRESSED reason="sollicitation owner déjà en attente de réponse"` ; sinon envoyer
  puis `gate.mark_sent()`.
- `self_fix.request_upgrade()` : si `gate.is_blocked()` → différer (statut `deferred`, ne
  pas DM) ; sinon, sur envoi du DM → `gate.mark_sent()`.
- `discord/handlers.py` `on_message` : message reçu **en DM** de la part de l'owner
  (`message.guild is None and author.id == owner_discord_id`, détection déjà présente
  l.1399/1476) → `gate.clear()`.

**Rapport au cooldown existant.** `action_dispatcher` a déjà un `DM_CREATOR_COOLDOWN` (2 h,
temporel) + `_last_dm_ts`. Le portail (basé sur la *réponse*, pas le temps) est la nouvelle
règle principale anti-empilement. Décision : conserver le cooldown temporel comme plancher
secondaire **ou** le retirer au profit du portail. Préférence : garder un plancher court,
laisser le portail porter la sémantique « n'insiste pas tant que je n'ai pas répondu ».

### B3. Câblage DI

`OwnerOutreachGate` construit dans `bootstrap.py`, **partagé** entre `ActionDispatcher`,
`SelfFix` et le handler `on_message` (via un attribut sur `bot`, p.ex. `bot.owner_gate`).

---

## Tests (TDD)

**Partie A — `SocialRhythm` (déterministe) :**
- Apprend un creux synthétique : beaucoup de messages le jour / zéro la nuit + parole
  nocturne toujours ignorée → `receptivity` nocturne s'effondre, diurne reste haute.
- Prior à froid : 0 observation → `receptivity ≈ 0.5`.
- EMA : un changement durable de comportement déplace la réceptivité d'un créneau dans le
  temps (concept drift).
- Amortisseur : réceptivité basse → quasi toujours supprimé ; haute → quasi toujours passé
  (test statistique sur N tirages, graine fixe).
- Lissage/voisinage : un créneau sans données hérite partiellement de ses voisins.

**Partie B :**
- Self-fix : non-réponse → statut `deferred`, **pas** dans `_declined`, reproposable plus
  tard ; pas de message « j'abandonne ».
- Gate : `mark_sent` → `is_blocked()` True → second DM supprimé ; `clear()` → débloqué.
- Intégration : owner répond en DM → `on_message` appelle `clear()`.

**Baseline existante à préserver** : 2 échecs préexistants connus (`test_web_search`,
`test_dashboard_costs`) — ne pas les compter comme régressions.

---

## Fichiers touchés (~8 prod + 3 nouveaux + tests) → exécution en phases (≤5 fichiers/phase)

**Phase 1 — le modèle (isolé, testable seul)**
1. `bot/intelligence/social_rhythm.py` *(nouveau)*
2. `bot/db/schema_v2.py` (table `social_rhythm_bins`)
3. tests `tests/test_social_rhythm.py` *(nouveau)*

**Phase 2 — branchement cognitif (parole publique)**
4. `bot/intelligence/cognitive_loop.py` (cadence + amortisseur + signaux)
5. `bot/intelligence/attention_agent.py` (`social_receptivity` + fix UTC→Paris)
6. `bot/bootstrap.py` (DI `SocialRhythm`)
7. phrase de conscience dans `bot/persona/prompts/…` (reasoning context)
+ tests d'intégration cognitive.

**Phase 3 — sollicitations owner**
8. `bot/intelligence/self_fix.py` (retrait auto-refus/blacklist)
9. `bot/intelligence/action_dispatcher.py` (gate sur `_dm`)
10. `bot/intelligence/owner_outreach.py` *(nouveau : `OwnerOutreachGate`)*
11. `bot/discord/handlers.py` (`clear()` sur DM owner)
12. `bot/bootstrap.py` (DI gate)
+ tests gate/self-fix.

Validation explicite entre chaque phase. Vérification forcée par phase : `python3 -m pytest -q`.

## Déploiement

Backend non bind-mount → **rebuild image** requis pour activer (cf. mémoire projet).
Aucun nouveau secret, aucune nouvelle dépendance externe.

## Hors périmètre (YAGNI)

- Modèle de rythme *personnel à l'owner* / dépendance à la présence Discord : **abandonné**
  (owner souvent en invisible ; un MP n'exige pas de réponse immédiate).
- File de sollicitations qui rejoue les messages en attente : **abandonné** (option (ii)).
- Auto-réflexion LLM où Wally verbalise ses propres règles de rythme (approche B du
  brainstorming) : éventuelle itération future, hors de ce spec.
- Dédup sémantique question-DM ↔ question-publique : non couvert (les deux mécanismes
  traitent déjà chaque canal).
