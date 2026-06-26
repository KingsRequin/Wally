# Cohérence cognitive des canaux — Design

**Date :** 2026-06-26
**Branche :** `feat/site-redesign-arcade`
**Statut :** spec validée, en attente de plan d'implémentation

## Problème

Wally « confond » les canaux et perd le fil. Symptômes rapportés par le créateur,
confirmés dans les logs (`logs/conversations/`) et le code :

1. Il pose en salon public une question sur un sujet abordé en **DM privé**.
2. Il parle dans `#chambre-de-wally` d'un sujet passé dans `#général`.
3. En **DM**, le créateur pose une question et Wally **ne répond pas**.
4. Quand Wally envoie une demande de **self-fix** en DM, il n'en a aucune trace
   ensuite : le créateur veut en reparler, Wally « ne sait pas de quoi il parle ».

## Diagnostic (cause racine)

Tous les symptômes proviennent du **chemin cognitif proactif** (messages
`kind: cognitive` dans les logs) et du **ResponseGate**, pas du chemin réactif
direct (qui, lui, a déjà le bon contexte par canal).

| # | Cause racine | Preuve |
|---|---|---|
| A | La boucle cognitive maintient **un flux de conscience global** : `_recent_interactions` mélange les 20 derniers messages **tous canaux confondus**. Le `reasoning_agent` raisonne sur les **5 derniers messages mélangés**, choisit un canal cible, mais peut ressortir un sujet venu d'un **autre** canal. | `cognitive_loop.py:68,93,171` · `reasoning_agent.py:199` |
| B | Les **DM** alimentent ce flux global (`channel_allowed = True` pour les DM → `notify_activity` appelé). Un sujet de DM peut donc ressortir en public. | `handlers.py:805-807,864-871` |
| C | Le prompt cognitif affiche les **IDs numériques** de canaux (`[123456789]`), pas les noms. Le LLM ne distingue pas vraiment les espaces. | `reasoning_agent.py:203` |
| D | `ResponseGate.decide()` **ignore la notion DM vs salon** : aucun paramètre `is_dm`. En DM 1:1 il juge comme un salon public et peut décider `IGNORE`. | `gate.py:70-83` · logs DM 2026-06-26 (`ignore` sur « ca [+ image] ») |
| E | Le gate juge **quasi phrase-par-phrase** : il ne reçoit que le message courant + le dernier message de Wally, **pas le fil**. D'où des `IGNORE` du type « micro-remarque qui n'ajoute rien ». | `gate.py:72,80,97-103` |
| F | Le flux self-fix envoie ses DM via `dm.send()` direct, ce qui **contourne le pipeline d'historique** (`on_message`). Seul un résumé est stocké sous `wally:self`, pas dans le fil de conversation avec le créateur. | `self_fix.py:90-96,192-217` |

## Décisions de design (validées avec le créateur)

- **DM = option B (contextuel, pas confidentiel)** : les DM restent dans la
  cognition mais marqués `privé` ; consigne stricte de ne jamais croiser
  DM ↔ salon public. Rien de réellement secret en DM, mais aucune fuite croisée.
- **Gate en DM = ne jamais ignorer** : en conversation privée 1:1, Wally répond
  toujours. Seule exception : utilisateur explicitement banni (`is_ignored`).

## Solution — 6 corrections

### 1. Cloisonnement du contexte cognitif par canal
Au moment de raisonner pour parler, le cerveau ne doit considérer qu'**un canal
à la fois**. `build_context` groupe `_recent_interactions` par canal ; le
`reasoning_agent` présente les messages **séparés par salon**, et le prompt
système porte la consigne explicite : *« Ne ressors jamais dans un salon un
sujet entendu dans un autre. Chaque salon est une conversation distincte. »*

### 2. Noms de salons au lieu d'IDs
Le prompt cognitif affiche `#chambre-de-wally` au lieu de `[123456789]`, via le
mapping `id → name` du `ChannelDirectory` existant. Le `cognitive_loop` reçoit
ce mapping (aujourd'hui il ne reçoit que le `set` d'IDs `speakable_channels`).
Pour un DM (absent du directory), afficher `[DM privé avec <auteur>]`.

### 3. DM marqués « privé » dans la cognition
`notify_activity` reçoit un flag `is_dm` (ou un `channel_kind`). Les interactions
DM sont étiquetées `privé` dans le prompt. Consigne associée : un propos de DM
ne doit jamais apparaître dans un salon public, et inversement.

### 4. Gate : toujours répondre en DM
`ResponseGate.decide()` reçoit `is_dm: bool`. Si `is_dm and not is_ignored`, la
décision est **forcée à RESPOND sans appel LLM** (court-circuit, économie de
tokens). Le `handlers.py` passe `is_dm = message.guild is None`.

### 5. Gate : juger sur le fil, pas phrase-par-phrase
`decide()` reçoit les **~4 derniers messages du canal** (auteur + contenu), en
plus du message courant. Le prompt du gate présente ce court historique pour que
la décision de pertinence tienne compte du fil réel. (Sans objet pour le cas DM,
court-circuité au point 4 — mais utile pour tous les salons publics.)

### 6. Self-fix visible dans l'historique conversationnel
Quand Wally envoie une demande de self-fix, le **texte de la demande** et son
**issue** (accepté / refusé / déployé / échoué) sont injectés dans l'historique
conversationnel du **DM créateur** (le même canal de mémoire que celui lu au
moment de répondre), en plus du fait `wally:self` déjà enregistré. Wally peut
ainsi en reparler naturellement.

## Périmètre & fichiers touchés

| Fichier | Correction(s) |
|---|---|
| `bot/intelligence/cognitive_loop.py` | 1, 2, 3 (mapping noms, groupement, flag DM) |
| `bot/intelligence/attention_agent.py` | 1 (contexte groupé par canal) |
| `bot/intelligence/reasoning_agent.py` | 1, 2, 3 (rendu par canal, noms, DM privé) |
| `bot/intelligence/persona/prompts/reasoning_system.md` | 1, 3 (consignes anti-fuite) |
| `bot/intelligence/gate.py` | 4, 5 (`is_dm`, historique récent) |
| `bot/intelligence/persona/prompts/` (prompt gate) | 5 (rendu du fil) |
| `bot/discord/handlers.py` | 3, 4, 5 (flag DM dans `notify_activity`, `is_dm` + historique au gate) |
| `bot/intelligence/self_fix.py` | 6 (injection historique DM) |
| `bot/bootstrap.py` | 2 (wiring du mapping canaux vers `cognitive_loop`) |

> 9 fichiers → **exécution par phases** (max 5 fichiers/phase, cf. directives
> projet). Le plan d'implémentation découpera. Découpage pressenti :
> **Phase 1** — Gate (4, 5) : impact immédiat sur « il répond pas en DM », isolé.
> **Phase 2** — Cloisonnement cognitif (1, 2, 3) : cœur de la fuite inter-canaux.
> **Phase 3** — Self-fix historique (6) : indépendant.

## Critères de succès (vérifiables)

- **Gate DM** : un message en DM d'un utilisateur non-banni → décision RESPOND
  systématique, **sans appel LLM** au gate. Test unitaire sur `decide(is_dm=True)`.
- **Gate fil** : `decide()` reçoit et présente l'historique récent ; test vérifiant
  que le prompt contient les N derniers messages.
- **Cloisonnement** : test sur le rendu du `reasoning_agent` → les interactions
  sont groupées par canal et un canal ne contient que ses propres messages ;
  les DM apparaissent en bloc `privé` distinct.
- **Noms de canaux** : le prompt affiche le nom (`#chambre-de-wally`) quand il est
  connu, l'ID en repli sinon.
- **Self-fix** : après une demande, l'historique conversationnel du DM créateur
  contient la demande et son issue (test sur `_record_outcome` / injection).
- **Non-régression** : suite de tests existante verte (baseline connue :
  ~1010 verts, échecs préexistants spam + cost non liés).

## Hors périmètre

- Refonte de l'architecture de perception (full-channel perception conservée).
- Qdrant / mémoire sémantique (inchangés).
- Chemin réactif direct (déjà correct, non touché).
