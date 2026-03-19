# Trust score nuancé + Love par utilisateur

**Date :** 2026-03-19
**Scope :** `bot/core/emotion.py`, `bot/db/database.py`, `bot/discord/handlers.py`, `bot/twitch/handlers.py`, `bot/discord/commands/memory_cmd.py`, `bot/persona/SOUL.md`, `bot/config.py`

---

## Problème

1. Le trust score est binaire : insulte → -0.05, sinon → +0.01. Pas de nuance entre inside joke, question sincère, provocation déguisée.
2. Wally n'a pas d'affinité par utilisateur. Il est également aigri avec tout le monde, qu'il connaisse la personne depuis 6 mois ou 5 minutes.
3. `/wally memory` n'affiche pas le niveau de confiance/affection.

---

## Solution : 3 composantes

### 1. Trust delta via LLM

Remplacer le système binaire dans `_post_process` par un `trust_delta` retourné par le LLM d'analyse émotionnelle.

**`bot/core/emotion.py` — `_analyze_llm`**

Ajouter au prompt d'analyse émotionnelle :

```
## Trust delta
Retourne aussi "trust_delta" : un float dans [-0.10, +0.10].
- Interaction constructive, amicale, drôle, engageante → positif (+0.01 à +0.05)
- Interaction hostile, insulte, provocation, toxique → négatif (-0.03 à -0.10)
- Interaction neutre, factuelle, sans charge émotionnelle → 0.0
- Inside joke, complicité, défendre Wally → bonus (+0.05 à +0.10)
```

Ajouter au format JSON de sortie : `"trust_delta": 0.0`

La méthode `_analyze_llm` retourne maintenant un tuple `(deltas, new_words, trust_delta, love_delta)`.

**`bot/discord/handlers.py` et `bot/twitch/handlers.py` — `_post_process`**

Remplacer :
```python
insult_words = ["idiot", "stupide", ...]
if any(w in text.lower() for w in insult_words):
    await bot.db.update_trust_score(platform, user_id, -0.05)
else:
    await bot.db.update_trust_score(platform, user_id, 0.01)
```

Par l'utilisation du `trust_delta` retourné par `process_message`. La méthode `process_message` doit retourner les deltas LLM (trust_delta, love_delta) pour que `_post_process` puisse les utiliser.

### 2. Love par utilisateur

**Stockage** — nouvelle colonne dans `trust_scores` :

```sql
ALTER TABLE trust_scores ADD COLUMN love REAL DEFAULT 0.0;
ALTER TABLE trust_scores ADD COLUMN love_updated_at REAL DEFAULT 0;
```

Range 0.0–1.0. Ne va jamais en négatif.

**Love delta via LLM** — même appel que trust_delta :

```
## Love delta
Retourne aussi "love_delta" : un float dans [0.0, 0.10].
- Interaction chaleureuse, drôle partagée, intérêt pour Wally → positif (+0.02 à +0.08)
- Le love_delta n'est jamais négatif — l'affection ne baisse que par le decay temporel.
- Interaction neutre ou hostile → 0.0
```

**Lazy decay** — appliqué au moment de la lecture (`get_love_score`) :

```python
async def get_love_score(self, platform: str, user_id: str) -> float:
    # Lire love + love_updated_at
    # Calculer elapsed = now - love_updated_at
    # decayed = love * exp(-lambda * elapsed_days)
    # Sauvegarder si changement significatif
    return decayed
```

Lambda configurable : `love_decay_lambda: 0.1` → perte ~50% en 7 jours d'absence.

**Update** :

```python
async def update_love_score(self, platform: str, user_id: str, delta: float):
    # Appliquer le decay d'abord, puis ajouter le delta
    # Clamp [0.0, 1.0]
```

### 3. Injection dans le prompt + directives

**Injection** — dans `_respond()` (Discord et Twitch), après avoir récupéré trust et mem_context, récupérer aussi love :

```python
love = await bot.db.get_love_score(platform, user_id)
```

Ajouter au mem_context :
```
Niveau de confiance : 0.82/1.0
Niveau d'affection : 0.65/1.0
```

**Directives SOUL.md** :

```
Tu connais ton niveau d'affection pour chaque personne (indiqué
dans "Ce que tu sais de cet utilisateur"). Adapte ton comportement :
- Affection élevée (≥ 0.6) : tu es moins aigri, tu fais des vrais
  compliments (que tu sabotes parfois par réflexe), tu t'inquiètes
  sincèrement, tu es protecteur. C'est un pote.
- Affection moyenne (0.3–0.6) : tu es familier, tu taquines avec
  affection, tu te permets plus de vannes personnelles.
- Affection basse (< 0.3) : mode par défaut — aigri, distant,
  sarcastique. Tu ne les connais pas assez pour t'investir.
L'affection se mérite et s'estompe naturellement si la personne
disparaît. Ne mentionne jamais les chiffres directement.
```

### `/wally memory` — afficher trust + love

Dans l'embed, avant le texte des souvenirs, ajouter une ligne :
```
🛡️ Confiance : 0.82  ❤️ Affection : 0.65
```

### `process_message` — retour enrichi

`EmotionEngine.process_message` doit retourner les trust/love deltas pour que `_post_process` puisse les utiliser. Changer le return type :

```python
async def process_message(...) -> dict | None:
    # Retourne {"trust_delta": float, "love_delta": float} ou None (fallback)
```

Les callers existants qui n'utilisent pas le retour ne sont pas affectés (retour ignoré).

### Config

```yaml
bot:
  love_decay_lambda: 0.1
```

Nouveau champ `BotConfig` : `love_decay_lambda: float = 0.1`

---

## Tests

- `test_analyze_llm_returns_trust_and_love_delta` — mock LLM retourne trust_delta et love_delta, vérifie le parsing
- `test_analyze_llm_clamps_trust_delta` — trust_delta hors range → clampé [-0.1, 0.1]
- `test_analyze_llm_clamps_love_delta` — love_delta hors range → clampé [0.0, 0.1]
- `test_get_love_score_with_decay` — love=0.8, 7 jours passés → ~0.4
- `test_get_love_score_no_decay_recent` — love=0.8, 1 heure passée → ~0.8
- `test_update_love_score_clamps` — love=0.95 + delta 0.1 → 1.0
- `test_love_column_migration` — la colonne love existe après migration
- `test_process_message_returns_deltas` — process_message retourne les deltas LLM

---

## Fichiers

| Fichier | Changement |
|---------|-----------|
| `bot/core/emotion.py` | `_analyze_llm` retourne trust_delta + love_delta, `process_message` retourne les deltas |
| `bot/db/database.py` | Migration colonne love, `get_love_score()` avec lazy decay, `update_love_score()` |
| `bot/config.py` + `config.yaml` | `love_decay_lambda: 0.1` |
| `bot/discord/handlers.py` | `_post_process` utilise trust/love deltas, injection trust+love dans prompt |
| `bot/twitch/handlers.py` | Idem |
| `bot/discord/commands/memory_cmd.py` | Afficher trust + love dans l'embed |
| `bot/persona/SOUL.md` | Directives love-based |
| `bot/dashboard/routes/admin.py` | Support `love_decay_lambda` |
| Tests | Parsing, DB, decay, injection |
