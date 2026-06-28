# Outils cognitifs en vocal + santé des canaux configurés

**Date :** 2026-06-28
**Branche :** `feat/site-redesign-arcade`
**Statut :** Design validé, en attente de relecture

---

## Problème

Le contexte vocal de Wally n'expose que deux outils (`join_voice` / `leave_voice`),
alors que le contexte texte dispose de bien plus : recherche web, notes persistantes,
rappels/actions planifiées. Le pipeline vocal passe pourtant déjà par
`complete_with_tools(...)` — il suffit d'y brancher les mêmes outils.

En parallèle, on a découvert que `notification_channel_id` (config) pointe vers un canal
supprimé (« Unknown Channel ») sans qu'aucune alerte n'ait jamais été émise : les
notifications système ne partent nulle part depuis un moment, en silence.

## Objectifs

1. Brancher en vocal trois outils cognitifs : **recherche web**, **notes persistantes**,
   **rappels**.
2. Pour la recherche web : un comportement « cherche à voix haute » qui masque la latence
   (amorce parlée + petits bruits de réflexion), **dans le style/l'humeur de Wally**.
3. Au démarrage du bot : **valider chaque channel id configuré** et prévenir si l'un est mort.

## Hors périmètre

- Délivrance vocale des rappels (« il le dit à l'oral si encore connecté ») — évolution future.
- `scrape_url` en vocal (pas de liens collés à l'oral).
- Correction du `notification_channel_id` mort (l'utilisateur le mettra à jour ; le health-check
  ne fait que prévenir, il ne réécrit pas la config).

---

## Composant 1 — Recherche web vocale « à voix haute »

### Flux

```
Wally décide de chercher  →  tool_executor("web_search", {query})
        │
        ├─[parallèle]─ generate_search_filler(bot, query) → { amorce, bruits[] }  (1 appel LLM court)
        └─[parallèle]─ bot.web_search.search(query)
        │
   amorce prête → service.speak(amorce)              ex: « attends, je regarde ça… »
   tant que la recherche tourne → service.speak(bruit)  ex: « mh… », « ok je vois… »
   recherche finie → résultat brut renvoyé au LLM principal
        │
   réponse finale formulée par le LLM → parlée normalement
```

### `generate_search_filler(bot, query) -> dict`  (`bot/discord/voice/brain.py`)

- **Un seul** appel LLM court (modèle secondaire, `max_tokens` réduit), sortie structurée :
  `{ "amorce": str, "bruits": [str, ...] }` (2–3 bruits).
- Construit avec la persona + l'émotion courante (réutilise `_voice_system` /
  `build_voice_system`) pour rester dans la voix de Wally.
- **Filet déterministe** : si l'appel échoue ou renvoie du vide, on retombe sur une mini-banque
  d'amorces neutres codées en dur (ex. « attends, je regarde ça »). La recherche n'est **jamais**
  bloquée par l'amorce.

### `_search_aloud(bot, service, query) -> str`  (`bot/discord/voice/tools.py`)

- Lance `generate_search_filler` et `bot.web_search.search` **en parallèle** (`asyncio`).
- Parle l'amorce dès qu'elle est prête, puis débite les bruits un par un **tant que** la
  recherche n'est pas terminée. `service.speak()` étant séquentiel (il attend la fin de chaque
  TTS), si la recherche se termine pendant un bruit, on s'arrête naturellement ; si elle est plus
  rapide que l'amorce, les bruits sont sautés.
- Retourne le résultat brut de la recherche (string) — c'est ce que reçoit le LLM principal,
  exactement comme côté texte.

### Disponibilité

- L'outil `web_search` n'est ajouté à la liste vocale **que si** `bot.web_search.available` et
  quota non dépassé (`await is_quota_exceeded()`), comme dans `handlers.py`. Sinon Wally répond
  de mémoire (comportement actuel inchangé).

---

## Composant 2 — Notes persistantes en vocal

- Réutilise `_NOTE_TOOLS` (`save_persistent_note` / `delete_persistent_note`), déjà défini dans
  `discord/handlers.py` et importé par Twitch — on l'importe aussi dans le vocal.
- Exécution = pur appel DB (`bot.db.upsert_persistent_note` / `delete_persistent_note`), **aucune
  dépendance** au contexte Discord (pas de message/channel/author requis).
- Pas de « voix haute » : l'opération est instantanée, la confirmation (« c'est noté ») sort
  naturellement dans la réponse finale du LLM.

---

## Composant 3 — Rappels en vocal

- L'outil vient de `action_service.get_tool_definitions()` ; l'exécution passe par
  `action_service.execute_tool(name, args, ...)`.
- Paramètres fournis depuis le contexte vocal :
  - `user_id` = `speaker_user_id` (raw snowflake du locuteur courant) ;
  - `user_roles` = `_resolve_discord_roles(member)`, le membre étant résolu depuis le salon vocal ;
  - `platform` = `"discord"` ;
  - `guild_id` = guild du salon vocal ;
  - **`channel_id` = la chambre de Wally** (voir nouveau champ config ci-dessous) — c'est là que
    le rappel sera posté au déclenchement.
- Délivrance = mécanisme texte standard d'`ActionService` (inchangé). Le rappel survit au départ
  du vocal (l'ActionService persiste et reprogramme au boot).

### Nouveau champ config : `bedroom_channel_id`

- Ajouté dans la config Discord (même endroit que `notification_channel_id`),
  type `int | None = None`.
- Valeur cible connue : `1485380606224502844` (`#chambre-de-wally`, serveur « Le Purgatoire »).
- Hot-reloadable ; éditable via `/wally setup` ; toute mutation appelle `config.save()`.
- Si non configuré (`None`), les rappels créés en vocal sont refusés proprement avec un message
  parlé (« je ne sais pas encore où poster tes rappels »), plutôt que de planter.

---

## Composant 4 — Santé des canaux au démarrage

- Au boot (après `on_ready`, quand le cache des guildes est prêt), un validateur résout chaque
  channel id **configuré** :
  - `notification_channel_id`, `bedroom_channel_id`, `journal_channel_id` (config) ;
  - tous les ids de `CHANNELS.md` (via `ChannelDirectory`).
- Résolution : `bot.get_channel(id)` puis, si absent du cache, `await bot.fetch_channel(id)`.
  Un id introuvable (`NotFound` / `None`) est considéré **mort**.
- **Prévenir** (défaut, à confirmer en relecture) :
  - `logger.warning(...)` listant chaque id mort avec sa provenance (clé config ou ligne CHANNELS) ;
  - **DM au créateur** (`owner_discord_id`) avec la liste, **uniquement** s'il y a au moins un mort.
- Lecture seule : le validateur ne réécrit jamais la config. Il signale, l'humain corrige.

---

## Fichiers touchés

| Fichier | Changement |
|---|---|
| `bot/discord/voice/tools.py` | +`web_search` / `_NOTE_TOOLS` / rappels aux outils vocaux ; routage exécution ; `_search_aloud` |
| `bot/discord/voice/brain.py` | `generate_search_filler` (+ mini-banque de repli) |
| `bot/discord/voice/service.py` | câblage exécuteur (accès `bot.web_search`, `action_service`, chambre) ; liste d'outils dynamique (check quota async) |
| `bot/config.py` | champ `bedroom_channel_id` (+ pris en compte par `config.save()`) |
| `bot/discord/bot.py` (ou `handlers`/boot) | validateur de santé des canaux au démarrage |
| `bot/discord/commands/setup*.py` | (optionnel) édition de `bedroom_channel_id` via `/wally setup` |
| `tests/discord/voice/` + `tests/` | tests des 4 composants |

## Gestion d'erreurs

- Outil indisponible (quota/clé absente) → non proposé ; comportement de repli inchangé.
- Recherche qui échoue → message d'erreur renvoyé au LLM (pattern existant) ; Wally dit qu'il n'a
  pas trouvé.
- Amorce LLM qui échoue → mini-banque déterministe.
- `bedroom_channel_id` non configuré → rappel vocal refusé proprement (message parlé).
- Health-check : toute exception de résolution d'un id isolé est attrapée et traitée comme « mort »
  (jamais de crash au boot).

## Tests

1. `generate_search_filler` renvoie `{amorce, bruits}` (LLM mocké) ; repli mini-banque si échec/vide.
2. `web_search` proposé en vocal **seulement** si dispo + quota OK.
3. `_search_aloud` : amorce parlée puis bruits débités puis résultat renvoyé ; recherche rapide →
   bruits sautés ; recherche en échec → message d'erreur propagé.
4. Notes : `save_persistent_note` / `delete_persistent_note` exécutés en vocal (DB mockée).
5. Rappels : `execute_tool` appelé avec `channel_id == bedroom_channel_id`, `user_id` du locuteur,
   rôles résolus ; refus propre si `bedroom_channel_id is None`.
6. Health-check : un id mort → WARNING + DM créateur ; tous vivants → aucun DM ; exception isolée
   n'interrompt pas le scan.
