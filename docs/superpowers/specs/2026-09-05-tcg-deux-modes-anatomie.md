# TCG du Purgatoire — l'anatomie d'une carte et les deux modes

**Date** : 2026-09-04 · **Statut** : proposition, remplace l'anatomie de la spec mère §2
**Décidé par l'owner** : deux modes (versus · tous contre Wally) · stats **Attaque / PV / Aura**

> Écrit parce que l'owner a coupé court à l'écriture des cartes : *« je veux comprendre le
> déroulement d'un tour pour dire comment faire les cartes. Faire des cartes à l'aveugle c'est
> débile. »* Il a raison, et l'ordre correct est celui-ci : les règles décident des stats.

---

## 1. Une carte

| Champ | Qui l'écrit | Ce que c'est |
|---|---|---|
| Nom · illustration · texte d'ambiance | **Wally** | le personnage |
| **Coût** 1-5 | calcul | énergie à payer pour la poser |
| **Attaque** | calcul | ce qu'elle inflige |
| **PV** | calcul | ce qu'elle encaisse avant de sortir |
| **Aura** | calcul | ce qu'elle ajoute aux cartes **alliées** adjacentes |
| **Réflexe** | Wally choisit dans le catalogue | l'effet spécial |
| Rareté · Faction | **l'owner**, à la main | prestige et couleur |
| Affinité (1-2 sujets) | calcul | ce qui la fait briller sur certaines zones |

`Attaque + PV + Aura = budget`, et le budget ne dépend que du coût et de la rareté
(`4 + 3 × coût + bonus`). **La mémoire décide de la répartition, jamais du total** — le principe
de la spec mère est intact, seuls les noms des trois cases changent.

---

## 2. Les trois mesures — et pourquoi ce sont des FORMES, jamais des volumes

| Stat | Mesure | Ce que ça dit |
|---|---|---|
| **Attaque** | messages **par jour actif** | l'intensité : celui qui déboule et remplit le chat |
| **PV** | nombre de **jours actifs** distincts | la présence : celui qui est toujours là |
| **Aura** | **part** des faits de relation dans tout ce que Wally sait de la personne | le liant : celui dont on parle toujours avec les autres |

### 🚨 Le volume décide du BUDGET, la forme décide de la RÉPARTITION

C'est la règle qui a coûté trois essais ratés, et elle vaut pour toute mesure future.

Première version : `Attaque = nombre de messages`, `Aura = nombre de faits REL`. Résultat mesuré
sur 83 personnes :

| Paire | Corrélation | Conséquence |
|---|---|---|
| messages ↔ jours actifs | **r = +0,76** | Attaque et PV auraient dit la même chose : un bavard aurait tout |
| jours actifs ↔ nombre de liens | **r = +0,72** | plus tu es présent, plus Wally enregistre de relations. PV et Aura faisaient doublon |

En passant aux formes — messages **par jour**, et **part** relationnelle — les trois mesures
deviennent quasi indépendantes : **+0,20 · −0,02 · +0,03**. Trois stats qui disent enfin trois
choses différentes.

### 🚨 Égaliser les dispersions, sinon la mesure la plus étalée rafle tout

Même avec des mesures indépendantes, elles ne s'étalent pas pareil (écart-type du log :
**0,74** intensité · **1,07** présence · **1,73** liens). Une simple mise à l'échelle par la
médiane donnait « 2/5/2 » à la moitié de la commu : les jours actifs, plus dispersés, prenaient
le budget.

Formule retenue — **z-score sur logarithme**, qui égalise nativement :

```
z_i    = ( ln(mesure_i) − moyenne_pool(ln) ) / écart_type_pool(ln)
poids_i = max(z_i + 1,5 , 0,15)
stat_i  = budget × poids_i / Σ poids       réparti au plus grand reste
```

Puis planchers **Attaque ≥ 1** et **PV ≥ 1** (une carte sans attaque ne joue pas, une carte à
0 PV est morte avant d'arriver), plafond 9. L'Aura peut valoir 0 : c'est une forme.

Pool de référence : personnes ayant **≥ 5 faits actifs et ≥ 20 messages** (70 au 2026-09-04).

---

## 3. Mode VERSUS — trois zones, cinq tours, cinq minutes

Inchangé par rapport à la spec mère, sauf que les cartes se frappent désormais.

1. **Trois zones**, chacune avec un sujet, révélées une par tour sur les trois premiers tours.
2. **Énergie = numéro du tour** (1 au tour 1 … 5 au tour 5), non cumulable.
3. Les deux joueurs posent **en simultané et à l'aveugle**, puis **révélation croisée**.
4. **Échange de coups, zone par zone** : dans chaque zone, l'Attaque totale d'un camp se répartit
   sur les cartes adverses de cette zone, de la plus chère à la moins chère. Une carte dont les
   PV tombent à 0 **sort du plateau** — au Purgatoire elle ne meurt pas, elle *Chute*.
5. Fenêtre de **Chute** (voler la carte que l'adversaire vient de poser, 2× par partie), puis
   résolution des Réflexes.

**Score d'une zone** = Attaque des cartes encore debout + 2 par affinité correspondant au sujet
+ Aura reçue des alliées adjacentes. Fin du tour 5 : **deux zones sur trois = victoire**.

Ce qui change concrètement par rapport à la version sans PV : poser une grosse carte tôt ne suffit
plus, elle se fait tirer dessus pendant quatre tours. Le soin, le bouclier et la garde du
catalogue des Réflexes cessent d'être décoratifs.

---

## 4. Mode RAID — toute la commu contre Wally

**La même mécanique, lue sur UNE seule zone.** C'est ce qui rend les deux modes tenables : un
seul équilibrage, pas deux jeux à maintenir.

- **2 à 6 joueurs** d'un côté, **Wally** de l'autre.
- Wally a un gros paquet de PV, une Attaque qui frappe **une carte au hasard parmi celles qui sont
  posées**, et son propre deck : les cartes **uniques** que personne ne peut posséder — les modos,
  Malef, Lilio, Azraël, rhae.
- Les joueurs posent à tour de rôle, l'Attaque cumulée du groupe frappe Wally.
- **L'Aura traverse les joueurs** : ta carte renforce celle de ton voisin de table, pas seulement
  les tiennes. C'est là que la mécanique prend enfin tout son sens — elle mesure les liens réels
  entre des gens qui, ce coup-ci, jouent **ensemble**.
- **La triche de Wally sur ses PV** (idée de l'owner, 2026-08-31) est une **règle annoncée**, pas
  un mensonge du moteur : il déclare un total de PV, et une fois par partie il révèle qu'il lui en
  restait plus. Annoncée dans les règles, elle est un bluff ; cachée, elle serait indiscernable
  d'un bug de calcul de dégâts — et on ne pourrait plus jamais arbitrer une contestation.

---

## 5. Ce que ça donne sur des gens réels

Budget 9 pour tout le monde (coût 3, rareté Âme) afin que seules les formes se comparent :

| Personne | ATK | PV | Aura | mesures | l'archétype |
|---|---|---|---|---|---|
| OriganireTV | **5** | 2 | 2 | 47,8 msg/j · 9 j · 5 % | l'éclair : il déboule fort et ne reste pas |
| KassandreYunikon | **4** | 3 | 2 | 79,8 msg/j · 48 j · 8 % | la frappeuse |
| ClakerNoJutsu | **4** | 3 | 2 | 59,8 msg/j · 40 j · 17 % | |
| KingsRequin | 3 | **4** | 2 | 56,2 msg/j · 70 j · 16 % | l'équilibré |
| dovaest | 3 | 3 | 3 | 28,9 msg/j · 22 j · 32 % | le polyvalent |
| Azraël | 2 | **5** | 2 | 17,9 msg/j · 65 j · 9 % | le mur : toujours là |
| zeddo · Taki · Jubeii | 2 | 4 | 3 | | les réguliers liants |
| rhae___ | 1 | 4 | **4** | 4,5 msg/j · 11 j · 23 % | parle peu, relie tout le monde |

Dix personnes, sept profils. C'est le seul test qui compte : une formule qui rendrait le même
résultat à tout le monde ne mesurerait rien.

---

## 6. Ce qui reste ouvert

- **Le Piquant a disparu** en tant que stat. Sa mesure (`emotional_memory.anger`) n'est pas
  perdue : elle doit maintenant **orienter le choix du Réflexe** — quelqu'un de piquant reçoit un
  effet de la famille C du catalogue. À écrire.
- **L'ordre des coups** en versus : qui frappe en premier quand les deux camps posent en
  simultané ? Proposition — **simultané aussi**, les dégâts s'appliquent des deux côtés avant de
  retirer les cartes tombées. Sinon le premier joueur gagne mécaniquement.
- **Les PV de Wally** en raid : dérivés du nombre de joueurs, jamais fixes, sinon le raid est
  trivial à 6 et impossible à 2.
- **L'exposant et le décalage** (`z + 1,5`) sont mesurés sur 70 personnes. À revérifier sur les
  45 cartes réelles.
