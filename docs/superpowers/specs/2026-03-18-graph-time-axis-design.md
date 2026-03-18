# Dashboard — Graduations temporelles sur le graphique d'émotions

**Date :** 2026-03-18
**Statut :** Approuvé

---

## Contexte

Le graphique d'émotions du dashboard affiche actuellement uniquement les labels de début et de fin sur l'axe X. Les périodes 7J et 30J n'ont aucun repère intermédiaire, rendant la lecture temporelle difficile.

---

## Comportement attendu

| Période | Intervalle des ticks | Format du label |
|---|---|---|
| 24H (`tRange ≤ 97 200 s = 27h`) | Toutes les 2 heures | `"14h"` |
| 7J (`tRange ≤ 691 200 s = 8j`) | Tous les jours | `"16/3"` |
| 30J (sinon) | Tous les 2 jours | `"16/3"` |

---

## Design

### Calcul des ticks

Auto-détection depuis `rawRange = tMax - tMin` dans `drawEmotionGraph`. Utiliser la valeur brute avant le `|| 1` appliqué sur `tRange` (qui ne vaut `1` que si tous les snapshots ont exactement le même timestamp — cas impossible avec un historique de ≥ 2 points distincts, mais prévoir quand même).

```
rawRange = tMax - tMin   // pas le tRange forcé à 1
if rawRange <= 27 * 3600   → step = 7 200 s   (toutes les 2h)
if rawRange <= 8 * 86 400  → step = 86 400 s  (tous les jours)
else                       → step = 172 800 s (tous les 2 jours)
```

**Alignement du premier tick :**

Mode heure :
```javascript
const firstTick = Math.ceil(tMin / 3600) * 3600;
```

Mode jour :
```javascript
const d = new Date(tMin * 1000);
d.setHours(0, 0, 0, 0);                        // tronquer au minuit du jour courant
if (d.getTime() / 1000 < tMin) d.setDate(d.getDate() + 1);  // avancer si strictement avant tMin
const firstTick = d.getTime() / 1000;
```
Ainsi, si `tMin` est exactement minuit, le premier tick est `tMin` lui-même ; sinon c'est le prochain minuit.

**Itération :** de `firstTick` jusqu'à `tMax` par pas de `step`.

### Format des labels

- Mode heure : `new Date(t * 1000).toLocaleTimeString('fr', { hour: '2-digit' })` → `"14h"`
- Mode jour : `new Date(t * 1000).toLocaleDateString('fr', { day: 'numeric', month: 'numeric' })` → `"16/3"`

### Rendu par tick

Avant la boucle ticks, forcer `ctx.globalAlpha = 1` (la boucle des lignes d'émotion précédente peut laisser `globalAlpha` à `0.85`).

Pour chaque tick à timestamp `t` :

1. **Position X** : `x = PAD.left + ((t - tMin) / tRange) * gW`
2. **Anti-collision bords** : ignorer si `x < PAD.left + 40` ou `x > W - PAD.right - 40` (marge de 40 px pour ne pas chevaucher les labels de début/fin, quelle que soit leur longueur)
3. **Ligne verticale** : `rgba(255,255,255,0.12)`, `lineWidth = 1`, de `y = PAD.top` à `y = PAD.top + gH` (cohérent avec la zone graphique, ne pas dépasser dans la zone des labels)
4. **Label** : centré sur `x`, à `y = H - 26`, `font = '10px monospace'`, `fillStyle = 'rgba(255,255,255,0.35)'`, `textAlign = 'center'`

### Intégration dans `drawEmotionGraph`

La section ticks s'insère **après les gridlines horizontales et avant le tracé des lignes d'émotions**, afin que les lignes d'émotion passent par-dessus les ticks visuellement.

### Hors scope explicite

Les labels de début et de fin (`label0` / `labelN`) conservent leur format `toLocaleTimeString` actuel quelle que soit la période. L'incohérence visuelle (heures en bords, dates au centre en mode 7J/30J) est acceptée pour l'instant.

---

## Fichier modifié

| Fichier | Changement |
|---|---|
| `bot/dashboard/static/app.js` | Ajout de la section ticks dans `drawEmotionGraph` |

Aucun autre fichier. Aucun nouveau paramètre de fonction. Aucune nouvelle fonction publique.

---

## Hors scope

- Labels sur l'axe Y (valeurs 0–1)
- Ticks adaptatifs selon la largeur du canvas (la logique 2h/1j/2j est fixe)
- Localisation du format de date (toujours `'fr'`)
