# Spec — Cohérence émotionnelle de Wally

**Date :** 2026-03-16
**Statut :** validé

---

## Problème

Les 5 émotions de Wally (`anger`, `joy`, `sadness`, `curiosity`, `boredom`) s'accumulent de façon
totalement indépendante. Un message joyeux peut faire monter `joy` pendant qu'`anger` reste élevée
d'un échange précédent, ce qui produit un état interne incohérent (Wally simultanément heureux et
en colère) et des directives comportementales contradictoires dans le prompt.

---

## Objectif

Introduire une suppression partielle et automatique des émotions incompatibles au niveau de l'état
interne, sans modifier l'API publique ni la logique d'accumulation des autres émotions.

---

## Décisions de design

### 1. Où agir : état interne (pas seulement le rendu)

La correction s'applique dans `apply_delta()` ET dans `set_emotion()`, via un helper privé
`_apply_suppression(emotion, delta)`. Cela garantit la cohérence quel que soit le chemin d'appel
(NRCLex, LLM, événements Twitch, commande `/wally mood`).

**`set_emotion` calcule le delta effectif** avant d'appliquer la suppression :
```
delta_effectif = new_value - self._state[emotion]
```
Si `delta_effectif <= 0`, aucune suppression n'est déclenchée.

### 2. Paires incompatibles

| Paire | Justification |
|---|---|
| `joy` ↔ `anger` | Incohérence psychologique forte |
| `joy` ↔ `sadness` | Incohérence psychologique forte |

`anger` et `sadness` peuvent coexister.
`curiosity` et `boredom` sont libres (aucune incompatibilité retenue).

### 3. Intensité : partielle (coefficient 0.5), symétrique dans les deux sens

Le coefficient 0.5 s'applique **dans les deux directions** de chaque paire :
- `joy` +d → `anger` −d×0.5 et `sadness` −d×0.5
- `anger` +d → `joy` −d×0.5
- `sadness` +d → `joy` −d×0.5

La suppression ne s'applique qu'aux deltas positifs. Un delta négatif (émotion qui baisse) ne
"recharge" pas son opposée.

### 4. Pas de cascade

La boucle de suppression dans `_apply_suppression` modifie `_state` directement sans rappeler
`apply_delta`. Les suppressions ne se propagent donc pas en cascade. Si des règles futures créaient
des chaînes (A→B→C), il faudrait réexaminer ce choix.

### 5. Comportement lors d'appels multi-émotions (path LLM)

Quand `process_message()` applique les deltas LLM, il itère sur `EMOTIONS` dans l'ordre déclaré :
`["anger", "joy", "sadness", "curiosity", "boredom"]`. Si le LLM retourne anger+0.1 et joy+0.2
simultanément :

1. `apply_delta("anger", 0.1)` → `joy` −0.05
2. `apply_delta("joy", 0.2)` → `anger` −0.1, `sadness` −0.1

Il y a une double suppression croisée sur le même message. Ce comportement est **intentionnel et
souhaitable** : deux émotions contradictoires se combattent, le résultat dépend de leurs deltas
respectifs. L'ordre fixe (`EMOTIONS`) garantit la déterminisme.

---

## Implémentation

### Fichier : `bot/core/emotion.py`

**Nouvelle constante (après `MAX_DELTA_PER_MESSAGE`) :**

```python
# Paires d'émotions incompatibles : (source, cible, coefficient de suppression)
# Bidirectionnel et symétrique : même coefficient dans les deux sens.
SUPPRESSION_RULES: list[tuple[str, str, float]] = [
    ("joy", "anger",   0.5),
    ("joy", "sadness", 0.5),
]
```

**Nouveau helper privé :**

```python
def _apply_suppression(self, emotion: str, delta: float) -> None:
    """Supprime partiellement les émotions incompatibles si delta > 0."""
    if delta <= 0:
        return
    for src, tgt, coeff in SUPPRESSION_RULES:
        if emotion == src:
            self._state[tgt] = max(0.0, self._state[tgt] - delta * coeff)
        elif emotion == tgt:
            self._state[src] = max(0.0, self._state[src] - delta * coeff)
```

**`apply_delta` modifié :**

```python
def apply_delta(self, emotion: str, delta: float) -> None:
    if emotion not in self._state:
        return
    self._state[emotion] = max(0.0, min(1.0, self._state[emotion] + delta))
    self._apply_suppression(emotion, delta)
    self._dirty = True
    self._schedule_save()
```

**`set_emotion` modifié :**

```python
def set_emotion(self, emotion: str, value: float) -> None:
    if emotion in self._state:
        effective_delta = value - self._state[emotion]
        self._state[emotion] = max(0.0, min(1.0, value))
        self._apply_suppression(emotion, effective_delta)
        self._dirty = True
        self._schedule_save()
```

---

## Tests

| Cas | Entrée | Résultat attendu |
|---|---|---|
| `joy` supprime `anger` | `anger=0.8`, `apply_delta("joy", 0.2)` | `anger=0.70`, `joy=0.20` |
| `joy` supprime `sadness` | `sadness=0.6`, `apply_delta("joy", 0.4)` | `sadness=0.40`, `joy=0.40` |
| `anger` supprime `joy` | `joy=0.8`, `apply_delta("anger", 0.3)` | `joy=0.65`, `anger=0.30` |
| `sadness` supprime `joy` | `joy=0.8`, `apply_delta("sadness", 0.3)` | `joy=0.65`, `sadness=0.30` |
| `anger` ne touche pas `sadness` | `sadness=0.5`, `apply_delta("anger", 0.3)` | `sadness=0.50` (inchangé) |
| `curiosity` ne touche rien | `joy=0.8`, `apply_delta("curiosity", 0.3)` | `joy=0.80` (inchangé) |
| delta négatif → pas de suppression | `anger=0.5`, `apply_delta("joy", -0.1)` | `anger=0.50` (inchangé) |
| delta zéro → pas de suppression | `anger=0.5`, `apply_delta("joy", 0.0)` | `anger=0.50` (inchangé) |
| suppression floored à 0 | `anger=0.05`, `apply_delta("joy", 0.8)` | `anger=0.0` (floor, pas négatif) |
| `set_emotion` supprime | `anger=0.8`, `set_emotion("joy", 0.9)` | `anger=0.35` (0.8 − 0.9×0.5) |
| `set_emotion` delta négatif → pas de suppression | `anger=0.8`, `set_emotion("joy", 0.1)` (joy était 0.5) | `anger=0.80` (inchangé) |
| double suppression LLM | `apply_delta("anger", 0.1)` puis `apply_delta("joy", 0.2)` | `anger` baisse des deux appels, `joy` baisse du premier |

---

## Périmètre

- **Touché :** `bot/core/emotion.py` (constante + `_apply_suppression` + `apply_delta` + `set_emotion`)
- **Non touché :** `prompts.py`, `config.yaml`, `database.py`, handlers Discord/Twitch
- **Aucune migration de données** — les états persistés existants restent valides

---

## Ce qui n'est PAS dans ce spec

- Coefficients configurables via `config.yaml` (YAGNI)
- Visualisation des suppressions dans les logs (les logs existants suffisent)
- Modification du rendu prompt (la cohérence de l'état interne suffit)
