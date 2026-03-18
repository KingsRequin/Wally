# Graph Time Axis — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter des graduations temporelles (ticks + labels) sur l'axe X du graphique d'émotions, adaptées à la période sélectionnée (2h / 1j / 2j).

**Architecture:** Un seul bloc de code inséré dans `drawEmotionGraph` après les gridlines horizontales. Calcul auto-détecté depuis `rawRange = tMax - tMin`. Aucun nouveau paramètre, aucune nouvelle fonction publique.

**Tech Stack:** Vanilla JS, HTML Canvas 2D

---

## Fichiers touchés

| Fichier | Changement |
|---|---|
| `bot/dashboard/static/app.js` | Ajout du bloc ticks dans `drawEmotionGraph` (~ligne 329) |

---

## Task 1 : Ajouter les graduations temporelles dans `drawEmotionGraph`

**Fichiers :**
- Modify: `bot/dashboard/static/app.js` (fonction `drawEmotionGraph`, après la boucle des gridlines horizontales ~ligne 328)

Pas de tests automatisés possibles pour le rendu canvas — la vérification est visuelle.

- [ ] **Étape 1 : Localiser le point d'insertion exact**

Ouvrir `bot/dashboard/static/app.js` et repérer la fin de la boucle des gridlines horizontales :

```javascript
  // Grille — 4 lignes horizontales à 25/50/75/100%
  ctx.lineWidth = 1;
  for (let pct = 0.25; pct <= 1.0; pct += 0.25) {
    ...
    ctx.stroke();
  }

  // Tracé ligne + area fill par émotion   ← insérer AVANT cette ligne
```

Le bloc ticks va entre la fin de la boucle gridlines et le commentaire `// Tracé ligne + area fill par émotion`.

- [ ] **Étape 2 : Insérer le bloc ticks**

Insérer le code suivant à l'emplacement identifié :

```javascript
  // ── Ticks temporels ──────────────────────────────────────────────────────
  {
    const rawRange = tMax - tMin;
    let tickStep, tickMode;
    if (rawRange <= 27 * 3600) {
      tickStep = 7200;   // toutes les 2h
      tickMode = 'hour';
    } else if (rawRange <= 8 * 86400) {
      tickStep = 86400;  // tous les jours
      tickMode = 'day';
    } else {
      tickStep = 172800; // tous les 2 jours
      tickMode = 'day';
    }

    let firstTick;
    if (tickMode === 'hour') {
      firstTick = Math.ceil(tMin / 3600) * 3600;
    } else {
      const d = new Date(tMin * 1000);
      d.setHours(0, 0, 0, 0);
      if (d.getTime() / 1000 < tMin) d.setDate(d.getDate() + 1);
      firstTick = d.getTime() / 1000;
    }

    ctx.globalAlpha = 1;
    for (let t = firstTick; t <= tMax; t += tickStep) {
      const x = PAD.left + ((t - tMin) / tRange) * gW;
      if (x < PAD.left + 40 || x > W - PAD.right - 40) continue;

      // Ligne verticale (même hauteur que la zone graphique)
      ctx.strokeStyle = 'rgba(255,255,255,0.12)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, PAD.top);
      ctx.lineTo(x, PAD.top + gH);
      ctx.stroke();

      // Label centré
      const label = tickMode === 'hour'
        ? new Date(t * 1000).toLocaleTimeString('fr', { hour: '2-digit' })
        : new Date(t * 1000).toLocaleDateString('fr', { day: 'numeric', month: 'numeric' });
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.font = '10px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(label, x, H - 26);
    }
  }
```

- [ ] **Étape 3 : Vérifier visuellement en mode 24H**

Ouvrir le dashboard dans un navigateur. Sélectionner 24H. Vérifier :
- Des labels `"14h"`, `"16h"`, `"18h"`... apparaissent sous le graphe à intervalles réguliers de 2h
- Les lignes verticales fines traversent la zone du graphe
- Aucun label ne chevauche les labels de bord (début / fin)
- Les lignes d'émotions passent par-dessus les ticks (non masquées)

- [ ] **Étape 4 : Vérifier visuellement en mode 7J**

Cliquer le bouton 7J. Vérifier :
- Des labels `"16/3"`, `"17/3"`... apparaissent, un par jour
- L'intervalle est journalier, aligné sur minuit

- [ ] **Étape 5 : Vérifier visuellement en mode 30J**

Cliquer le bouton 30J. Vérifier :
- Des labels tous les 2 jours : `"1/3"`, `"3/3"`, `"5/3"`...
- Pas de chevauchement visible

- [ ] **Étape 6 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): graduations temporelles sur l'axe X du graphique (2h/1j/2j)"
```
