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
- **Aura** : donne des **chances de critique** (§2bis). Elle ne s'ajoute PAS à l'Attaque.

> ⚖️ **Arbitrage du 2026-09-09.** L'Aura ajoutait l'Attaque des alliés en ligne. L'owner l'a
> retiré : *« augmenter l'attaque je trouve ça trop cheaté, du coup on ne jouerait que les cartes
> avec le plus gros aura et c'est tout. Une chance de critique peut être contrable. »* Un bonus
> déterministe et cumulatif rend la stat qui le porte strictement supérieure aux autres.

**Répartition : écrite à la MAIN par l'owner.** Seule contrainte, la somme tient le budget.
Planchers Attaque ≥ 1 et PV ≥ 1. **Rareté et faction sont posées par l'owner**, carte par carte —
et la rareté AVANT les stats, puisqu'elle fixe le budget.

> ⚖️ **Arbitrage du 2026-09-10.** La répartition sortait d'une formule tirée de la mémoire de
> Wally. *« On va retirer les faits sur les gens, on ne les utilisera pas pour les héros. »*
> Le budget est désormais la seule règle d'équilibre vérifiable, et il l'est au chargement du
> fichier (`bot/core/tcg_cartes.py`).

### Le coût de l'Ultime sort du style, pas du mérite

```
coût de l'Ultime : 6 à 10, posé par l'owner
puissance de l'effet = prix du catalogue, aligné sur ce coût  →  2 à 6
```

⚠️ Le coût sortait du **quintile de la longueur médiane des messages** — tu écris des pavés, ton
Ultime est cher et lent. C'était juste, drôle et illisible comme une note. **Il tombe avec la
formule le 2026-09-10** : il se pose à la main, dans la même plage.

Ce qui SURVIT de ce principe, et qui compte : le coût d'un Ultime dit un **style**, jamais un
mérite. Un Ultime cher n'est pas la récompense de quelqu'un d'important.

---

## 2bis. Le hasard vit dans les STATS — il n'y a pas de dé

> ⚖️ **Arbitrage de l'owner, 2026-09-10.** *« Il y aurait du hasard en stats — esquive, boost
> d'attaque, chance de heal, etc. Pas de dé. »*

Chaque carte peut porter des **pourcentages qui lui sont propres**, résolus au moment de l'effet :
esquive, critique, soin, boost. Il n'y a **aucun tirage partagé**, aucun dé, aucune valeur
annoncée en début de tour.

L'**Aura** est la première de ces chances : elle donne le **taux de critique** du héros.

### 🚨 Ce que ça remplace, et ce qu'il faut refaire

Ceci **annule l'arbitrage du 2026-09-04** (« le hasard est tiré et AFFICHÉ avant la pose, un dé
1-6 partagé par tour »). Le **Tirage du tour n'existe plus**. Conséquences, à traiter avant toute
calibration :

| Ce qui en dépendait | État |
|---|---|
| **15 cartes** lisant « si le Tirage ≥ N » (6 tactiques, 9 entrées du catalogue) | à refaire |
| `I01 Critique` et `I02 Esquive` du catalogue | deviennent des **stats**, plus des Réflexes |
| **Michel-Velux** (« l'adversaire choisit ton Tirage ») | son contre disparaît — carte à repenser |
| L'état **Oublie** (Tirage ≤ 3) | devient un pourcentage porté par l'état |
| L'Aura qui **abaisse un seuil de Tirage** | devient directement un **taux** |
| La zone `TIRAGE` de la maquette du plateau | sans objet |

🎁 **Et ça SIMPLIFIE la tarification, ce qui n'est pas évident.** Le catalogue tarifait les effets
à hasard **au meilleur cas** — parce qu'un hasard affiché avant la pose n'est pas une espérance,
c'est une **option** : le joueur n'engageait que sur le bon tirage. Un hasard **caché** ne se
choisit pas. Ces effets se retarifent donc à leur **espérance** : « +6 une fois sur trois » vaut
de nouveau **+2**, et non +6. Tout le §2 du catalogue est à réécrire dans ce sens — à la baisse.

### ⚠️ Ce qu'on perd, et qu'il faut assumer

- **Wally ne peut plus commenter avant le coup.** *« Avec ce tirage, à ta place j'aurais pas
  engagé »* n'a plus de sens si personne ne connaît le tirage. Ses commentaires se replient sur
  l'**après** (une gaffe se lit dans la chute d'évaluation du moteur, ce qui marche toujours).
- **Un résultat improbable devient indiscernable d'un bug.** C'était l'argument central du
  2026-09-04. Le contre-poison est le **journal d'événements** : chaque jet doit y être écrit
  avec son taux et son résultat, sinon aucune contestation ne pourra jamais être tranchée.
  Ce n'est plus une commodité de calibration, c'est ce qui rend le jeu défendable.
- **La triche annoncée de Wally** (`TRICHE` : ses PV ne suivent aucune règle) reposait sur le
  contraste avec un hasard visible. Elle reste jouable, mais il faut qu'elle soit **écrite sur sa
  carte** — c'est déjà le cas — sinon elle se confond avec les jets cachés.

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

⚠️ Une entrée de la famille F peut aussi porter un **Ultime** quand elle est marquée
*👤 Ultime* dans le catalogue : c'est le cas de **F07 Rework** (l'Ultime d'Azraël), qui neutralise
durablement l'Ultime d'un adversaire. La famille F reste le seul endroit où une entrée touche à
une mécanique signature, qu'elle serve de tactique ou d'Ultime.

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
