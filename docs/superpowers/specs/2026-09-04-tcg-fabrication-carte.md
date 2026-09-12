# TCG du Purgatoire — fabriquer une carte-personne

**Date** : 2026-09-04 · **Statut** : procédure arrêtée, valeurs à recalibrer par saison
**Spec mère** : `2026-08-29-tcg-purgatoire-design.md` · **Catalogue** : `2026-09-04-tcg-catalogue-reflexes.md`

La spec mère dit *que* les chiffres sont calculés. Ce document dit **comment**, assez
précisément pour être codé, et pour que deux passes sur la même personne rendent la même carte.

> 🚨 **Pourquoi ce document existe.** La première carte (ClakerNoJutsu) a été fabriquée « à la
> main » le 2026-09-04 : `Voix 5 / Aura 3 / Piquant 1`, à l'intuition. C'est exactement ce que la
> spec mère interdit — un total juste ne suffit pas si la répartition est une opinion. Personne
> n'aurait pu reproduire ces trois nombres. Écrire la procédure a ensuite montré que l'intuition
> était bonne (§7) — mais on ne le savait pas avant de l'écrire, et c'est tout le sujet.

---

## 1. Ce qui ne se calcule pas : l'owner le pose

Arbitré le 2026-09-04. Un champ sort du calcul et est **saisi à la main**, carte par
carte, dans la base Notion « 🃏 Cartes du Purgatoire » :

| Champ | Pourquoi à la main |
|---|---|
| **Rareté** | Les grades Twitch (sub, VIP, modo) ne sont pas lisibles : `_STREAMER_SCOPES` ne porte ni `channel:read:vips` ni `moderation:read`, et les ajouter n'agit pas sur un token déjà émis. L'owner connaît sa commu mieux que ces scopes. |

Conséquence assumée : la rareté devient un **choix éditorial** de l'owner et non une lecture
mécanique d'un grade. La spec mère l'avait nommé comme un risque (« la rareté est un jugement
public sur ta place dans la commu ») ; le risque est le même, la décision est simplement prise
par un humain qui connaît les gens.

⚠️ La **rareté modifie le budget** (`+0 / +1 / +2 / +3 / +5 / +8`). La changer après coup
**refait toutes les stats de la carte**. À poser avant de figer, pas après.

### La rareté se VOIT : le reflet holographique

Arbitrage de l'owner, 2026-09-08. Le reflet irisé qui court sur la carte quand
elle se penche n'est pas un ornement : c'est le marqueur visible de la rareté,
en trois paliers.

| Palier | Ce que la carte porte | État |
|---|---|---|
| Les deux plus hautes | le reflet sur **toute la surface** | ✅ livré — Azraël, rhae___ |
| Le suivant | le reflet **sur les bords seulement** | ❌ pas écrit — cf. ci-dessous |
| Les autres | rien | ✅ par défaut |

Le palier « bords seulement » revient à **KingsRequin, Malef et Lilio**. Ces
trois cartes **n'existent pas encore**, et la variante n'est donc **pas
implémentée** : `holographique` est un booléen, pas un niveau.

🚨 C'est délibéré. Un réglage s'écrit du CONSOMMATEUR vers l'UI : écrire
aujourd'hui un troisième palier que personne ne porte donnerait un bouton
branché sur rien, invérifiable, et qui aurait dérivé le jour où la première de
ces cartes arriverait. Le projet a payé ça huit fois (cf. `CLAUDE.md`, §0bis).

Quand la première des trois sera dessinée, `holographique: bool` devient un
niveau (`aucun` / `bords` / `plein`) **et** la variante CSS s'écrit dans le
même geste. La couche existe déjà (`.chero-holo` dans
`public-ui/partage/tcg-carte.css`) ; il s'agira de la masquer au liseré plutôt
que de la laisser courir sur toute la carte.

---

## 2. Les stats — écrites à la MAIN, sur un budget borné

> ⚖️ **Arbitrage de l'owner, 2026-09-10.** *« On va retirer les faits sur les gens, on ne les
> utilisera pas pour les héros. »* La mémoire de Wally ne fabrique plus les cartes.

```
Attaque + PV + Aura = 12 + bonus de rareté
```

L'owner écrit les trois nombres. La **seule** contrainte est que leur somme tienne le budget —
et elle n'est pas négociable : c'est tout ce qui reste pour que deux cartes faites à trois mois
d'écart puissent s'affronter sans que l'une écrase l'autre par accident (décision fondatrice du
2026-08-27, toujours en vigueur).

Bonus de rareté : `Âme +0` · `Fidèle +1` · `Âme Promise +2` · `Élu +3` · `Ange +5` · `Archange +8`.

⚠️ **Pas de plafond par stat.** Retiré par l'owner le 2026-09-07 : c'était un reste de l'époque
où le budget valait 9. Une carte peut donc être `0 / 20 / 0`.

### 🚨 Ce que cet arbitrage déplace, et qu'il faut regarder en face

La spec mère du 2026-08-27 nommait le risque à l'envers : *« le seul endroit du jeu où un humain
conçoit vraiment est le seul endroit où l'équilibre peut casser »*. Cet endroit est désormais
**toutes les cartes**, pas seulement les objets. Deux conséquences :

1. **La calibration devient obligatoire, elle n'est plus un confort.** Une formule se relit ; une
   opinion, non. Le moteur d'auto-jeu et son journal d'événements sont ce qui remplace la
   reproductibilité perdue — c'est là que se verra une carte trop forte.
2. **La répartition n'est plus justifiable.** Avant, on pouvait dire *« ta carte est comme ça
   parce que tu parles beaucoup »*. Maintenant, c'est un choix de l'owner. Ça retire au passage
   le risque nommé en tête de spec mère — la carte n'est plus un jugement mesuré sur ta place
   dans la commu — mais ça met chaque chiffre sur le dos d'une personne.

### ⚰️ Ce qui a été abandonné, pour ne pas le reproposer dans six mois

Les §2 à §4 de ce document décrivaient une formule : trois mesures (messages par jour actif,
part de faits relationnels, `emotional_memory.anger`), normalisées en **racine carrée** de leur
z-score, réparties sur le budget ; plus un **coût** tiré du quintile de la longueur médiane des
messages. Elle a été vérifiée sur huit personnes réelles et rendait six profils distincts.

Elle n'est pas abandonnée parce qu'elle était fausse — mais parce que l'owner ne veut pas que la
mémoire décide des cartes. **Les pièges qu'elle a payés restent vrais** et valent pour toute
mesure future sur cette base :

- 🚨 **Grouper par `author_id`, jamais par `author`** : le libellé change avec le pseudo. Jubeii
  comptait **0 message au lieu de 473**.
- 🚨 **`category='EMOTION'` ne mesurait rien** : médiane 0, max 4 sur toute la commu. *Une mesure
  trop rare ne mesure pas peu, elle mesure faux.*
- 🚨 **Le percentile mesure le rang, pas la forme** : quelqu'un de fort partout ressortait `3/3/3`,
  sans forme — l'inverse du but. Le log aplatissait tout le monde ; la racine carrée gardait les
  écarts.

---

## 5. Les cas limites — tranchés, pas laissés au moteur

| Cas | Décision |
|---|---|
| Aucun message au journal | `Voix` prend le plancher 1, le reste se répartit sur Aura et Piquant |
| Aucun signal du tout (les trois à 0) | tout le budget en `Voix`. Une carte muette n'existe pas |
| Moins de 5 faits actifs | **pas de carte.** Wally n'en sait pas assez ; il inventerait |
| Deux comptes liés | une seule carte, mesures sommées après résolution d'alias |
| Personne qui refuse sa carte | retrait total de la circulation, y compris des collections déjà distribuées (spec mère §8) |
| Personne décédée | statut `hommage — hors jeu` : la carte existe, elle n'entre ni en lootbox, ni en tirage, ni en deck |

---

## 6. La capacité passive du héros

Le héros ne se pose pas : il reste au bord du plateau et donne une passive (spec mère §3.1), qui
était en « à concevoir ». Elle **dérive de la stat dominante** de sa propre carte — donc de la
personne, pas de son grade :

| Dominante | Passive | Effet |
|---|---|---|
| **Voix** | *Porte-voix* | +1 Voix à la première carte que tu poses chaque tour |
| **Aura** | *Hôte* | +1 Aura à tes cartes de la table où tu en as le plus |
| **Piquant** | *Aiguillon* | +1 Piquant à ta carte la plus chère en jeu |

Égalité départagée dans l'ordre **Voix > Aura > Piquant**, comme partout ailleurs. Aucune passive
n'est plus forte qu'une autre : c'est la même valeur, appliquée à trois endroits différents.

Dériver de la dominante plutôt que du palier de rareté évite qu'un Archange ait *en plus* une
meilleure passive : son prestige coûte déjà 12 sur les 20 du deck.

---

## 7. L'état RÉEL des sept cartes — mesuré le 2026-09-10

Relevé dans `tcg/cartes.yaml`, pas dans la maquette :

| Carte | Rareté | atk/pv/aura | Somme | Budget | |
|---|---|---|---|---|---|
| AZRAËL | archange | `5/10/5` | 20 | 20 | ✅ |
| CLAKER | ame | `0/0/0` | 0 | 12 | ⬜ à écrire |
| RHAE | ange | `0/0/0` | 0 | 17 | ⬜ à écrire |
| LILITH | indefinie | `0/0/0` | 0 | — | ⬜ rareté d'abord |
| KINGSREQUIN | indefinie | `0/0/0` | 0 | — | ⬜ rareté d'abord |
| WALLY | indefinie | `0/0/0` | 0 | — | ⬜ boss, budget à part |
| MÉLIODAS | indefinie | `0/0/0` | 0 | — | ⬜ rareté d'abord |

**Une seule carte porte des chiffres**, et elle tient son budget. Les six autres sont à zéro :
il n'y a donc rien à « recalculer », tout est à écrire. L'arbitrage du 2026-09-10 arrive au bon
moment — aucun travail de formule n'est perdu.

⚠️ **La rareté avant les stats.** Quatre cartes sur sept ont `rarete: indefinie`, et la rareté
fixe le budget. Les poser dans l'autre ordre oblige à tout refaire (déjà noté au §1).

### 🚨 La maquette porte des chiffres que le YAML n'a plus

La fiche Notion affirme que les chiffres de la maquette (`claker 8 · 5/4/3`, `rhae 6 · 8/5/4`,
`lilith 7 · 6/6/5`) sont **identiques** à `tcg/cartes.yaml`. Ils ne le sont plus : le YAML a été
vidé le 2026-09-07 quand on a constaté qu'ils dataient du modèle Voix/Aura/Piquant.

C'est **exactement la signature du défaut retiré le 2026-09-09** (`92f6132a`, les deux catalogues
de héros) : une seconde définition qui survit ailleurs et que personne ne relit. `lilith 6/6/5`
fait d'ailleurs 17, pour un budget de 12 — la maquette montre une carte hors budget.

→ **Les chiffres de la maquette sont des placeholders**, au même titre que ses tactiques. À dire
dans le brief de la maquette, sinon ils seront recopiés de bonne foi.

---

## 8. Ce qui reste à calibrer

- **Le budget est désormais la SEULE vérification automatique possible.** Un test qui relit
  `tcg/cartes.yaml` et refuse `atk + pv + aura ≠ 12 + rareté` est ce qui remplace la formule.
  À écrire avec la prochaine carte, pas après.
- **Le moteur d'auto-jeu et son journal d'événements** deviennent le seul juge de l'équilibre :
  15 parties minimum avant de figer un prix, 10 000 en une nuit avec un moteur à graine.
- **La passive du héros (§6) dépend encore de la stat dominante** — donc d'un choix de l'owner et
  non plus d'une mesure. Elle reste valable telle quelle : les trois passives valent la même
  chose, appliquée à trois endroits.
