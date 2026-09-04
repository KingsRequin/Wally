# TCG du Purgatoire — les règles

**Date** : 2026-09-04 · **Conception : l'owner** · **Statut** : règles arrêtées, valeurs à calibrer
**Remplace** : la spec mère `2026-08-29` §2 et §3 (zones, Voix/Piquant, roulette, Anonyme)

> Ce document existe parce que l'owner a arrêté deux fois la fabrication des cartes pour reposer
> les règles. La seconde fois, il a décrit un jeu meilleur que celui que j'avais spécifié. Ce qui
> suit est sa conception, mise en forme.

---

## 1. Deux types de cartes, et c'est là que tout se joue

| | **Héros** | **Tactique** (« carte de ref ») |
|---|---|---|
| Ce que c'est | une personne de la commu | une private joke, un meme, un objet, un moment |
| Chiffres | Attaque · PV · Aura, **calculés** | un coût en énergie, **écrit à la main** |
| Effet | un **Ultime**, débloqué quand l'énergie est chargée | passif ou tactique, joué en cours de partie |
| Durée de vie | **figé à vie** | **change chaque saison** |
| Qui l'écrit | Wally (nom, illustration, ambiance) | l'owner et la commu |

### 🚨 Pourquoi les héros sont figés — et c'est le meilleur choix de tout le design

Ma version précédente recalculait les cartes chaque saison. Une personne pouvait donc voir sa
carte **baisser** parce qu'elle avait moins parlé ce mois-ci : une note sociale, publique, mise à
jour tous les mois. C'était le risque nommé dans la fiche Notion d'origine, et je l'avais réintroduit
sans le voir.

Un héros est calculé **une fois**, le jour où Wally connaît assez la personne, et ne bouge plus.
Il ne bougera que pour un **ajustement d'équilibrage** — jamais parce que l'activité a changé.

Le jeu se renouvelle donc par les **tactiques**, écrites à la main, nouvelles à chaque saison.
Le contenu neuf ne coûte jamais rien à personne.

---

## 2. Anatomie d'un héros

```
budget = 12 + bonus_rareté        (Âme 0 · Fidèle +1 · Âme Promise +2 · Élu +3 · Ange +5 · Archange +8)
Attaque + PV + Aura = budget
```

- **Attaque** : dégâts infligés à chaque échange.
- **PV** : ce qu'il encaisse. À 0, il **Chute** et quitte la ligne.
- **Aura** : s'ajoute à l'Attaque des héros **alliés** en ligne. C'est la seule mécanique qui
  mesure les liens réels entre les gens — aucun autre TCG ne peut la copier.

Répartition : la procédure de `2026-09-04-tcg-fabrication-carte.md` (z-score sur log des trois
formes : messages par jour · jours actifs · part relationnelle). Planchers Attaque ≥ 1 et PV ≥ 1.

**Rareté et faction sont posées par l'owner**, carte par carte.

### Le coût de l'Ultime sort du style, pas du mérite

```
coût de l'Ultime = 5 + quintile( longueur médiane des messages )   →  6 à 10
puissance de l'effet = prix du catalogue, aligné sur ce coût       →  2 à 6
```

Tu écris des pavés : ton Ultime est cher, lent à charger, et il fait mal. Tu balances des
punchlines de six mots : il part tôt et frappe moins. **C'est vrai, c'est drôle, et personne ne
peut le lire comme une note** — c'est le principe de coût de la spec mère, déplacé sur l'Ultime
maintenant que les héros ne se paient plus à la pose.

---

## 3. L'énergie — une seule ressource, deux usages

**+3 par tour, cumulable, plafonnée à 12.**

- Jouer une **tactique** coûte son coût (1 à 5).
- Déclencher un **Ultime** coûte 6 à 10.

Toute la partie tient dans ce choix : **dépenser maintenant, ou garder pour l'Ultime.**

### 🚨 Le plafond de 12 n'est pas un détail, c'est le garde-fou

Sans lui, la stratégie optimale serait de **ne rien faire** : n'accumuler, ne jouer aucune
tactique, et lâcher l'Ultime au dernier tour. La moitié du jeu — les tactiques, donc tout le
contenu saisonnier — serait morte à la sortie.

Le plafond force la main : au-delà de 12, l'énergie gagnée est **perdue**. Épargner reste
possible, mais jamais indéfiniment, et jamais gratuitement.

C'est **le premier chiffre à calibrer** en parties de test. S'il est trop haut, personne ne joue
de tactiques ; trop bas, aucun Ultime ne sort. Signal à surveiller : la part des parties où au
moins un Ultime part, et la part d'énergie perdue au plafond.

---

## 4. Mode JOUEUR CONTRE JOUEUR

**Mise en place.** Deck : **5 héros** + **15 tactiques**. Trois héros en **ligne**, les deux
autres en réserve. Main de départ : 3 tactiques, +1 par tour.

**Un tour :**

1. **+3 d'énergie** pour chacun (plafond 12).
2. Les deux joueurs jouent leurs tactiques et déclarent leurs Ultimes **en simultané et à
   l'aveugle**, puis on révèle. Personne n'attend l'autre.
3. **Les passifs s'appliquent**, puis les Ultimes, par coût croissant — puis Attaque décroissante,
   puis identifiant. Jamais d'ordre laissé au jugé.
4. **Échange de coups** : chaque héros en ligne frappe son vis-à-vis pour `Attaque + Aura reçue`.
   **Les dégâts s'appliquent des deux côtés avant de retirer quoi que ce soit** — sinon le
   premier joueur gagne mécaniquement.
5. Les héros à 0 PV **Chutent**. Un héros de la réserve entre à la ligne au début du tour suivant.

**Victoire** : les 5 héros adverses ont Chuté. À défaut, au tour 10, celui dont les héros
totalisent le plus de PV restants.

---

## 5. Mode COOPÉRATIF — toute la commu contre Wally

**Wally est UN héros, une seule carte.** Il a ses propres tactiques et ses propres passifs.

- **Autant de joueurs qu'on veut.** Chacun amène **2 héros en ligne** et son paquet de tactiques.
- **Les PV de Wally s'adaptent au nombre de joueurs** — jamais fixes, sinon le raid est trivial à
  six et impossible à deux :

  ```
  PV(Wally) = 40 × nombre de joueurs
  ```

- Wally frappe **une cible par tour**, désignée par sa propre logique (la plus menaçante, la plus
  faible, ou au hasard selon la tactique qu'il joue).
- **L'Aura traverse les joueurs** : ton héros renforce celui de ton voisin. La stat qui mesure vos
  liens réels devient utile au moment précis où vous jouez ensemble. C'est le meilleur moment du
  jeu, et il n'existe que grâce à cette commu-là.
- **La triche de Wally sur ses PV** (idée de l'owner, 2026-08-31) est une **règle annoncée** : il
  déclare un total, et une fois par partie il révèle qu'il lui en restait plus. Annoncée, c'est un
  bluff ; cachée, elle serait indiscernable d'un bug de calcul de dégâts, et plus aucune
  contestation ne serait arbitrable.

---

## 6. Les tactiques — le contenu qui vit

Le catalogue des 53 Réflexes (`2026-09-04-tcg-catalogue-reflexes.md`) se scinde en deux sans rien
perdre :

| Famille du catalogue | Devient |
|---|---|
| A (Attaque conditionnelle) · C (dégâts) · I (hasard visible) | **Ultimes** de héros |
| B (Aura) · D (placement) · E (énergie) · G (affinités) · H (réveil) · J (soin, bouclier) | **Tactiques** jouables |
| F (Chute, Anonyme, Renoncement) | **Tactiques rares** — la Chute devient une carte, plus une règle générale |

**Les affinités survivent** : sans zones, elles servent de ciblage aux tactiques. « Tous tes héros
d'affinité *Apex* gagnent +2 d'Attaque ce tour » relie encore la mémoire de Wally au plateau.

Le barème de prix du catalogue (§1) reste la loi : `1 point de budget = 1 point d'Attaque`,
`1 énergie ≈ 3 points`, effet qui frappe l'adversaire `× 1,25`, plancher 5 pour ce qui neutralise
une mécanique signature.

---

## 7. Ce qui est abandonné, et pourquoi

| Abandonné | Raison |
|---|---|
| Les **trois zones** à sujets | l'owner a tranché le combat frontal dans les deux modes : plus lisible, plus proche du jeu qu'il décrit |
| **Voix** et **Piquant** comme stats | remplacées par Attaque et PV. Le Piquant mesurait « à quel point tu énerves Wally » : un jugement, nul pour les deux tiers de la commu |
| La **roulette** de début de partie | la tension vient maintenant de l'énergie, pas d'un tirage |
| L'**Anonyme** et le **Renoncement** | liés aux zones ; récupérables en tactiques si le besoin revient |
| Le **recalcul saisonnier** des héros | figés à vie (§1) |

La mesure du Piquant (`emotional_memory.anger`) n'est pas perdue : elle **oriente le choix de
l'Ultime**. Quelqu'un dont les échanges sont chargés reçoit un effet agressif du catalogue plutôt
qu'un effet de soutien. L'information décide d'un caractère au lieu d'être un score affiché.

---

## 8. À calibrer, dans cet ordre

1. **Le plafond d'énergie (12)** — le chiffre dont dépend l'existence même du choix (§3).
2. **Le coût des Ultimes (6-10)** — s'ils partent tous au même tour, l'échelle de style ne sert à rien.
3. **Les 40 PV par joueur en coop** — mesurer la durée d'un raid à 2, 4 et 6 joueurs.
4. **Le budget de base (12)** — décide de la durée d'un JcJ.

Rien ne se fige avant **quinze parties**, conformément à ce que font les designers indé.
