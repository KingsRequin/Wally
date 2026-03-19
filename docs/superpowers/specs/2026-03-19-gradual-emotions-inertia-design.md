# Seuils d'émotion graduels + Inertie émotionnelle

**Date :** 2026-03-19
**Scope :** `bot/core/emotion.py`, `bot/core/prompts.py`, `bot/core/persona.py`, `bot/persona/EMOTIONS.md`, `bot/config.py`, `config.yaml`

---

## Problème

Le système émotionnel actuel a deux limitations :

1. **Seuil binaire** — Les directives comportementales s'activent à 0.4 ou pas du tout. Wally passe de "neutre" à "en colère" sans transition. Pas de "légèrement agacé".

2. **Pas d'inertie** — Un delta émotionnel est appliqué tel quel, peu importe l'état actuel. Si Wally est très joyeux (joy=0.7), un message triste a le même impact que s'il était neutre. Un humain résisterait davantage.

---

## Feature 1 : Seuils graduels (3 paliers)

### Principe

Chaque émotion a 3 niveaux de directive au lieu d'un :

| Palier | Range | Clé dans EMOTIONS.md |
|--------|-------|----------------------|
| low    | 0.2 – 0.4 | `## {emotion}_low` |
| mid    | 0.4 – 0.7 | `## {emotion}_mid` |
| high   | ≥ 0.7     | `## {emotion}_high` |

En dessous de 0.2, aucune directive n'est injectée (émotion négligeable).

### Changements

#### `bot/persona/EMOTIONS.md`

Remplacer les 5 sections `## emotion` par 15 sections `## emotion_level`. Chaque palier a une directive distincte en intensité et ton :

- `anger_low` : sec, expéditif, peu patient
- `anger_mid` : irrité, agressif, sarcasme mordant (≈ directive actuelle)
- `anger_high` : furax, cinglant, insultes possibles

Pattern identique pour joy, sadness, curiosity, boredom.

Le préambule du fichier est mis à jour pour refléter le nouveau système à 3 paliers.

#### `bot/core/persona.py` — `_parse_emotions()`

Aucun changement de code nécessaire. La méthode parse déjà les sections `## {key}` et retourne `{key: directive}`. Avec les nouvelles clés `anger_low`, `anger_mid`, etc., le dict retourné contiendra naturellement les 15 entrées. Le code existant est déjà compatible.

#### `bot/core/prompts.py` — `build_system_prompt()`

Remplacer la logique actuelle :

```python
# AVANT (seuil binaire)
dominant = sorted(
    [(e, v) for e, v in emotion_state.items() if v >= EMOTION_THRESHOLD],
    key=lambda x: x[1], reverse=True,
)[:2]
for emotion, _ in dominant:
    if emotion in directives:
        parts.append(directives[emotion])
```

Par une logique à paliers :

```python
# APRÈS (3 paliers)
EMOTION_THRESHOLDS = {"low": 0.2, "mid": 0.4, "high": 0.7}

def _get_tier(value: float) -> str | None:
    if value >= 0.7:
        return "high"
    if value >= 0.4:
        return "mid"
    if value >= 0.2:
        return "low"
    return None

dominant = sorted(
    [(e, v) for e, v in emotion_state.items() if v >= 0.2],
    key=lambda x: x[1], reverse=True,
)[:2]
for emotion, value in dominant:
    tier = _get_tier(value)
    key = f"{emotion}_{tier}"
    if key in directives:
        parts.append(directives[key])
```

Supprimer la constante `EMOTION_THRESHOLD = 0.4`.

#### `bot/core/emotion.py` — `build_emotion_tag()`

Mettre à jour la fonction libre `build_emotion_tag` pour utiliser le seuil 0.2 au lieu de 0.4 :

```python
def build_emotion_tag(emotion_state: dict[str, float]) -> str:
    dominant = [e for e, v in emotion_state.items() if v >= 0.2]
    if not dominant:
        return ""
    return "Wally: " + ", ".join(dominant)
```

#### `bot/core/emotion.py` — `get_dominant()`

Mettre à jour le seuil par défaut de `get_dominant()` de 0.4 à 0.2 :

```python
def get_dominant(self, threshold: float = 0.2) -> list[str]:
```

---

## Feature 2 : Inertie émotionnelle

### Principe

Quand une émotion opposée est dominante, les deltas entrants sont atténués proportionnellement. L'atténuation ne s'applique qu'aux paires d'opposition (pas à l'émotion elle-même).

Formule : `effective_delta = delta × (1 - opposite_value × inertia_factor)`

### Paires d'opposition

Réutilise `SUPPRESSION_RULES` déjà défini dans `emotion.py` :
- joy ↔ anger
- joy ↔ sadness

Ces paires sont bidirectionnelles : si joy est haute, anger et sadness sont atténués, et inversement.

### Changements

#### `bot/config.py` — `BotConfig`

Ajouter le champ :

```python
emotion_inertia_factor: float = 0.5
```

#### `config.yaml`

Ajouter sous `bot:` :

```yaml
emotion_inertia_factor: 0.5
```

#### `bot/core/emotion.py` — `apply_delta()`

Ajouter l'atténuation par inertie avant d'appliquer le delta :

```python
def apply_delta(self, emotion: str, delta: float) -> None:
    if emotion not in self._state:
        return
    # Inertie : atténuer si une émotion opposée est dominante
    inertia = getattr(self._config.bot, "emotion_inertia_factor", 0.5)
    if inertia > 0 and delta > 0:
        max_opposite = 0.0
        for src, tgt, _ in SUPPRESSION_RULES:
            if emotion == src:
                max_opposite = max(max_opposite, self._state.get(tgt, 0.0))
            elif emotion == tgt:
                max_opposite = max(max_opposite, self._state.get(src, 0.0))
        if max_opposite > 0:
            delta = delta * (1 - max_opposite * inertia)
    old = self._state[emotion]
    self._state[emotion] = max(0.0, min(1.0, old + delta))
    effective_delta = self._state[emotion] - old
    self._apply_suppression(emotion, effective_delta)
    self._dirty = True
    self._schedule_save()
```

Note : l'inertie s'applique uniquement aux deltas positifs. Les deltas négatifs (decay, suppression) ne sont pas affectés.

Note : les émotions sans paire d'opposition (curiosity, boredom) ne sont jamais atténuées par l'inertie. C'est voulu — la curiosité et l'ennui ne s'opposent pas directement aux autres émotions.

---

## Tests

### Tests seuils graduels

- `test_get_tier_returns_correct_level` — vérifie low/mid/high/None pour différentes valeurs
- `test_build_system_prompt_injects_tiered_directive` — vérifie qu'anger=0.3 injecte `anger_low`, anger=0.5 injecte `anger_mid`, anger=0.8 injecte `anger_high`
- `test_build_system_prompt_no_directive_below_threshold` — vérifie qu'anger=0.1 n'injecte rien
- `test_build_system_prompt_top2_with_tiers` — vérifie que seules les 2 émotions les plus fortes sont injectées, chacune avec le bon palier
- `test_build_emotion_tag_threshold_02` — vérifie que le tag utilise le seuil 0.2
- `test_get_dominant_default_threshold` — vérifie le nouveau seuil par défaut 0.2

### Tests inertie

- `test_inertia_attenuates_opposite_emotion` — joy=0.7, delta sadness=0.2 → effective ≈ 0.13
- `test_inertia_no_effect_same_emotion` — joy=0.7, delta joy=0.2 → pas d'atténuation
- `test_inertia_no_effect_unrelated_emotion` — joy=0.7, delta curiosity=0.2 → pas d'atténuation
- `test_inertia_zero_when_opposite_zero` — anger=0.0, delta joy=0.2 → pas d'atténuation
- `test_inertia_configurable` — vérifie que changer `emotion_inertia_factor` modifie le résultat
- `test_inertia_bidirectional` — anger=0.6, delta joy atténué ET joy=0.6, delta anger atténué

### Tests existants à adapter

- Tous les tests qui référencent `emotion_directives` avec des clés simples (`"anger"`, `"joy"`) doivent utiliser les nouvelles clés (`"anger_low"`, `"anger_mid"`, `"anger_high"`)
- Le seuil `EMOTION_THRESHOLD` importé dans certains tests doit être remplacé

---

## Résumé des fichiers modifiés

| Fichier | Nature du changement |
|---------|---------------------|
| `bot/persona/EMOTIONS.md` | 5 → 15 sections (3 paliers × 5 émotions) |
| `bot/core/prompts.py` | Logique de sélection par palier, suppr. `EMOTION_THRESHOLD` |
| `bot/core/emotion.py` | Inertie dans `apply_delta()`, seuil `build_emotion_tag()` 0.2, `get_dominant()` défaut 0.2 |
| `bot/config.py` | Ajout `emotion_inertia_factor: float = 0.5` dans `BotConfig` |
| `config.yaml` | Ajout `emotion_inertia_factor: 0.5` |
| Tests | Adaptation clés directives + nouveaux tests inertie/paliers |
