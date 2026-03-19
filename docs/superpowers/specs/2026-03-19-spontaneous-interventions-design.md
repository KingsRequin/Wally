# Interventions spontanées

**Date :** 2026-03-19
**Scope :** `bot/config.py`, `config.yaml`, `bot/discord/handlers.py`, `bot/twitch/handlers.py`, `bot/dashboard/routes/admin.py`

---

## Problème

Wally ne parle que quand on le mentionne. Un humain dans un chat intervient parfois spontanément — quand un sujet l'intéresse, quand quelqu'un dit une connerie, quand il s'ennuie. L'absence d'interventions spontanées rend Wally passif et prévisible.

---

## Solution : Interventions spontanées avec probabilité émotionnelle

### Principe

Quand Wally n'est pas mentionné (path non-trigger dans `handle_message`), il peut décider d'intervenir spontanément selon la probabilité la plus haute qui matche :

| Déclencheur | Probabilité | Condition |
|------------|-------------|-----------|
| **Passion/aversion** | 15% (`spontaneous_passion_probability`) | Le message mentionne un sujet de IDENTITY.md |
| **Émotion forte** | 5% (`spontaneous_probability`) | curiosity ≥ 0.6, boredom ≥ 0.7, ou anger ≥ 0.7 |
| **Base** | 0% | Sinon rien |

La passion/aversion est prioritaire (probabilité plus haute). Si le message matche un mot-clé passion ET une émotion forte, on utilise la probabilité passion (15%).

### Mots-clés passions/aversions

Extraits de IDENTITY.md, détection case-insensitive par substring :

**Passions :** `bouchon`, `silice`, `chariot`, `néon`, `ticket de caisse`, `notice pliée`, `feuille morte`

**Aversions :** `ananas`, `pizza ananas`, `ketchup`, `croque-monsieur`, `c'est juste un jeu`, `on part sur`, `eau tiède`, `clavier mécanique`, `applaudir`

### Cooldown

Maximum une intervention spontanée toutes les 5 minutes (`spontaneous_cooldown_seconds`) par canal. Dict `{channel_id: last_spontaneous_timestamp}` en mémoire dans le handler.

### Quand Wally intervient

1. Le message n'est PAS un trigger (Wally n'est pas mentionné)
2. Le canal est autorisé
3. La feature est enabled (`spontaneous_discord_enabled` ou `spontaneous_twitch_enabled`)
4. Le cooldown est passé (> 300s depuis la dernière intervention dans ce canal)
5. Random check passe (passion prob ou emotion prob)
6. Wally génère une réponse LLM basée sur le prelude + le message déclencheur
7. Le message est envoyé dans le canal (pas un reply, juste un message)

### Réponse LLM pour les interventions

On réutilise le pipeline existant (`bot.openai.complete`) avec un system prompt construit comme une réponse normale, mais le user message est préfixé d'une instruction :

```
[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément parce que le sujet t'intéresse ou te fait réagir. Réponds en une phrase courte et percutante, comme un commentaire lâché en passant.]
```

Pas de memory search ni de trust score pour les interventions spontanées — c'est un commentaire en passant, pas une interaction complète.

### Config

```yaml
bot:
  spontaneous_discord_enabled: true
  spontaneous_twitch_enabled: true
  spontaneous_probability: 0.05
  spontaneous_passion_probability: 0.15
  spontaneous_cooldown_seconds: 300
```

Tous dans `BotConfig` avec valeurs par défaut. Hot-reload via `config.save()` depuis le dashboard.

### Dashboard

`bot/dashboard/routes/admin.py` — ajouter le support des 5 nouveaux champs dans `update_config` sous `"bot"`.

---

## Fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/config.py` | 5 nouveaux champs BotConfig |
| `config.yaml` | Valeurs par défaut |
| `bot/discord/handlers.py` | Logique intervention dans path non-trigger, cooldown, keyword matching |
| `bot/twitch/handlers.py` | Même logique pour Twitch |
| `bot/dashboard/routes/admin.py` | Support des 5 nouveaux champs |
| Tests | Keywords, cooldown, probabilité, enabled/disabled |

---

## Tests

- `test_passion_keywords_detected` — message avec "bouchon" → matche
- `test_aversion_keywords_detected` — message avec "pizza ananas" → matche
- `test_no_keyword_no_passion_match` — message neutre → pas de match
- `test_emotion_gate_curiosity` — curiosity=0.6 → gate passe
- `test_emotion_gate_below_threshold` — curiosity=0.3 → gate bloquée
- `test_cooldown_prevents_double_intervention` — 2e intervention < 300s → bloquée
- `test_disabled_prevents_intervention` — `spontaneous_discord_enabled=False` → rien
