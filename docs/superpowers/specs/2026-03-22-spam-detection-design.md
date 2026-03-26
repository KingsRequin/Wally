# Spam Detection — Design Spec

**Date:** 2026-03-22
**Scope:** Discord uniquement

---

## Objectif

Détecter quand un utilisateur envoie trop de messages en peu de temps et déclencher une réponse
"calme-toi" générée par le LLM, suivie d'un mute temporaire. Pendant le mute, les messages
continuent de faire monter la colère de Wally. Wally est conscient qu'il a coupé quelqu'un —
cet événement est mémorisé et peut influencer le journal quotidien et les prochaines interactions.

---

## Comportement

### Détection
- Tracker en mémoire : `dict[(user_id, channel_id), deque[float]]` — timestamps des messages
- Le tracker enregistre **tous** les messages dans les channels autorisés, pas seulement ceux
  qui mentionnent Wally. La détection se fait tôt dans le flow, avant le check `triggered`.
- À chaque message :
  1. Enregistrer `time.time()` dans le deque
  2. Purger les timestamps plus vieux que `window_seconds`
  3. Si `len(deque) >= max_messages` → déclencher le spam flow
- Nettoyage : supprimer la clé du dict quand le deque est vide après purge (évite la croissance mémoire)

### Déclenchement
Quand le seuil est atteint :
1. Générer un message LLM via `bot.openai.complete_secondary()` avec le prompt template
   `bot/persona/prompts/spam_warning_system.md`
   - Le contexte (pseudo, nombre de messages, fenêtre) est injecté dans le message user,
     pas via `.format()` sur le system prompt (cohérent avec le pattern existant)
   - Wally formule le message dans sa personnalité et humeur actuelle
2. Envoyer le message dans le channel
3. Activer le mute via `bot.db.add_timeout(user_id, guild_id, mute_minutes, anger_level)`
   - `anger_level` = valeur actuelle de `bot.emotion.get_state()["anger"]`
4. Vider le deque de l'utilisateur pour ce channel (reset du compteur)
5. Ajouter un fait en mémoire via `bot.memory.add()` :
   "Wally a coupé {username} pour spam — trop de messages en peu de temps"
   → permet au journal et aux futures réponses d'en être conscients

### Conscience de l'événement
- Le fait est stocké dans la mémoire long-terme (mem0) sous le namespace de l'utilisateur
- Le journal quotidien (`DailyJournal`) verra ce fait via le contexte mémoire habituel
- Lors de la prochaine interaction avec cet utilisateur, le `memory.search()` remontera
  l'événement, permettant à Wally de le mentionner naturellement ("la dernière fois tu
  m'as spammé...")

### Pendant le mute
- Comportement existant : réactions emoji uniquement (💩 ⛔ 😤), pas de réponse texte
- **Nouveau** : chaque message d'un utilisateur muté applique un delta de colère :
  `emotion.apply_delta("anger", +spam_anger_delta)` (défaut : +0.05 par message)
- Cela influence le ton de Wally quand le mute expire et que l'utilisateur reparle

### Exclusions
- Channels listés dans `spam_detection.exempt_channels` sont ignorés
- Défaut : `[1485380606224502844]` (channel de conversation libre)
- DMs ignorés (`guild_id == "dm"`) — pas de contexte guild pour le mute

---

## Configuration

### config.yaml
```yaml
discord:
  spam_detection:
    enabled: true
    max_messages: 10
    window_seconds: 120
    mute_minutes: 5
    spam_anger_delta: 0.05
    exempt_channels:
      - 1485380606224502844
```

### Config dataclass
Nouvelle dataclass `SpamDetectionConfig` dans `bot/config.py` :
```python
@dataclass
class SpamDetectionConfig:
    enabled: bool = True
    max_messages: int = 10
    window_seconds: int = 120
    mute_minutes: int = 5
    spam_anger_delta: float = 0.05
    exempt_channels: list[int] = field(default_factory=list)
```

Ajoutée comme attribut de `DiscordConfig` :
```python
spam_detection: SpamDetectionConfig = field(default_factory=SpamDetectionConfig)
```

### Config.load() — gestion du nested dataclass
`DiscordConfig(**raw["discord"])` ne gère pas les nested dataclasses automatiquement.
Il faut extraire et construire manuellement :
```python
discord_raw = dict(raw.get("discord", {}))
spam_raw = discord_raw.pop("spam_detection", {})
discord_cfg = DiscordConfig(**discord_raw, spam_detection=SpamDetectionConfig(**spam_raw))
```

`Config.save()` fonctionne déjà car `dataclasses.asdict()` est récursif.

---

## Dashboard Web Admin

Section "Anti-spam" dans la page admin settings existante.

### UI
- **Toggle** enabled/disabled
- **Input** max_messages (nombre entier, min 3, max 50)
- **Input** window_seconds (entier, min 30, max 600)
- **Input** mute_minutes (entier, min 1, max 60)
- **Input** spam_anger_delta (float, min 0.01, max 0.2)
- **Liste** exempt_channels avec ajout/suppression

### API — extension des endpoints existants
Pas de nouveaux endpoints dédiés. On étend le pattern existant :
- `GET /api/admin/config` retourne déjà `asdict(cfg.discord)` — inclura automatiquement `spam_detection`
- `POST /api/admin/config` — ajouter un handler pour la section `spam_detection` sous `discord`,
  avec merge field-by-field comme les autres sections

---

## Prompt Template

Fichier `bot/persona/prompts/spam_warning_system.md` :

```
Tu as détecté qu'un utilisateur envoie beaucoup trop de messages dans un court laps de temps.
Tu en as marre. Tu dois lui dire de se calmer et de ralentir.
Formule ta réponse en une ou deux phrases maximum. Sois direct et agacé.
Ne mentionne pas de chiffres exacts.
```

Le contexte spécifique (pseudo, stats) est passé dans le message user :
```
L'utilisateur {username} a envoyé {message_count} messages en {window_seconds} secondes.
```

---

## Intégration dans handlers.py

### Position dans le flow
```
message reçu (tout message, pas seulement triggered)
  ↓
skip si bot, si DM, si exempt_channel
  ↓
enregistrer timestamp dans _spam_tracker
  ↓
check seuil → si dépassé : LLM message + memory.add() + mute + return
  ↓
(flow existant continue)
check is_muted() → si oui : emoji + apply anger delta + return
  ↓
check triggered → si non : return
  ↓
traitement normal (émotion, LLM, réponse)
```

### Modification du check is_muted existant
Le block `is_muted` actuel fait juste une réaction emoji et return.
Ajouter : `bot.emotion.apply_delta("anger", config.spam_detection.spam_anger_delta)`

### Nouveau code spam detection
Nouvelle fonction `_check_spam()` dans handlers.py :
- Prend `bot`, `message` en paramètres
- Retourne `True` si spam détecté et traité, `False` sinon
- Gère le tracking, la détection, la génération LLM, le memory.add() et le mute
- Le tracking (enregistrement timestamp) se fait même si le seuil n'est pas atteint

### State
Dict module-level dans handlers.py :
```python
_spam_tracker: dict[tuple[str, str], deque] = {}
```

---

## Fichiers impactés

| Fichier | Modification |
|---|---|
| `bot/config.py` | Ajouter `SpamDetectionConfig` + mise à jour `Config.load()` |
| `config.yaml` | Ajouter section `spam_detection` sous `discord` |
| `bot/discord/handlers.py` | Tracker + `_check_spam()` + anger delta sur mute |
| `bot/persona/prompts/spam_warning_system.md` | Nouveau fichier — prompt template |
| `bot/dashboard/routes/admin.py` | Étendre POST config pour spam_detection |
| Dashboard JS (admin page) | Section anti-spam dans les settings |
| Tests | Tests unitaires pour le tracker et la détection |

---

## Ce qui ne change PAS

- Le système de mute existant (anger-triggered) reste inchangé
- Le système de cooldown Twitch reste inchangé
- Pas de persistance DB pour le spam tracker (in-memory seulement)
- Pas d'impact sur le web chat ou Twitch
