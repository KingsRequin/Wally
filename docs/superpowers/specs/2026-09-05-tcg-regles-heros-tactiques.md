# TCG du Purgatoire — les règles

> ⚖️ **2026-09-12 — ce fichier ne fait PAS foi.** L'owner : *« arrête de te fier aux règles, elles
> changeront une fois toutes les cartes terminées. Pour le moment, seules les cartes comptent, pas
> de règles. »* La source des cartes est la base Notion **🃏 Cartes du Purgatoire**.
> Le **Tirage du tour** (dé 1-6 partagé) est supprimé : le hasard du jeu est un **pourcentage pur**,
> résolu au moment de l'effet.

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
Planchers Attaque ≥ 1 et PV ≥ 1. **La rareté est posée par l'owner**, carte par carte — et AVANT
les stats, puisqu'elle fixe le budget.

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

### ⚠️ Ce qu'on perd, et qu'il faut assumer

- **Un résultat improbable devient indiscernable d'un bug.** C'était l'argument central du
  2026-09-04. Le contre-poison est le **journal d'événements** : chaque jet doit y être écrit
  avec son taux et son résultat, sinon aucune contestation ne pourra jamais être tranchée.
  Ce n'est plus une commodité de calibration, c'est ce qui rend le jeu défendable.
- **La triche annoncée de Wally** (`TRICHE` : ses PV ne suivent aucune règle) reste jouable,
  mais il faut qu'elle soit **écrite sur sa carte** — c'est déjà le cas — sinon elle se confond
  avec les jets cachés.

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

### 🆕 Payer en AURA — la seconde monnaie, 2026-09-10

> ⚖️ L'owner : *« Pour les cartes spéciales, on peut prendre de l'Aura plutôt que de l'énergie. »*

Une carte **spéciale** — celles des paquets rares, et le deck de Wally — peut annoncer son coût
en **Aura** au lieu d'énergie. On paie alors en retirant ce montant à l'Aura d'un de ses héros,
pour le reste de la partie.

🎁 **Ça règle un défaut que le §3 portait depuis le début.** L'énergie est la SEULE ressource, donc
tous les choix passent par le même goulot : garder pour l'Ultime, ou dépenser. Une carte chère est
mécaniquement une carte qu'on ne joue pas le tour d'un Ultime. Payer en Aura ouvre une seconde
voie — jouer gros sans repousser son Ultime — au prix d'un héros durablement moins critique
(l'Aura est le taux de critique, §2bis).

🚨 **Le taux de conversion est le point dur, et il n'est pas posé.** Le barème du catalogue donne
`1 énergie ≈ 3 points` et `1 point d'Aura = 1 point de budget` : à la lettre, **1 énergie = 3
d'Aura**. Mais l'énergie revient à +3 par tour et l'Aura, elle, ne repousse pas. Payer en Aura est
donc un coût PERMANENT là où l'énergie est un coût de trésorerie — le même chiffre n'achète pas la
même chose.
→ **À calibrer avant d'écrire la moindre carte qui s'en sert** : si le taux est trop doux, plus
personne ne paie en énergie et le §3 s'effondre. Piste à mesurer : **1 énergie = 1 d'Aura**, qui
paraît cher au premier regard et ne l'est probablement pas.

⚠️ Une carte ne propose ce paiement que si elle l'écrit. Ce n'est pas un choix global offert sur
toutes les cartes : ce serait exactement le multiplicateur sans plafond que le barème interdit.

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

Le catalogue des 49 Réflexes (`2026-09-04-tcg-catalogue-reflexes.md`) se scinde en deux sans rien
perdre :

| Famille du catalogue | Devient |
|---|---|
| A (Attaque conditionnelle) · C (dégâts) | **Ultimes** de héros |
| B (Aura) · D (placement) · E (énergie) · G (affinités) · H (réveil) · J (soin, bouclier) | **Tactiques** jouables |
| F (Chute, Anonyme, Renoncement) | **Tactiques rares** — la Chute devient une carte, plus une règle générale |

⚠️ Une entrée de la famille F peut aussi porter un **Ultime** quand elle est marquée
*👤 Ultime* dans le catalogue : c'est le cas de **F07 Rework** (l'Ultime d'Azraël), qui emprunte
l'Ultime d'un héros du plateau — réécrit le 2026-09-10, il ne neutralise plus rien. La famille F
reste le seul endroit où une entrée touche à une mécanique signature, qu'elle serve de tactique
ou d'Ultime.

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
| ~~L'**Anonyme**~~ | ⚰️ **RÉCUPÉRÉ le 2026-09-10** — le besoin est revenu, cf. ci-dessous |
| Le **Renoncement** | lié aux zones ; récupérable en tactique si le besoin revient |
| Le **recalcul saisonnier** des héros | figés à vie (§1) |

### 🆕 L'Anonyme revient, et il est ATTAQUABLE — 2026-09-10

> ⚖️ L'owner : *« Les cartes face cachée pourront être attaquées pour être détruites. »*

Ce tableau annonçait l'Anonyme « récupérable si le besoin revient ». Il est revenu le jour même :
**trois cartes du 2026-09-10** se posent face cachée (*baril de Caustique*, *Typical Octane*, et
le *leurre* qui en est une variante). La mécanique n'est donc plus optionnelle.

Elle revient **modifiée**, et c'est l'apport de l'owner : une carte face cachée **occupe la table
et peut être attaquée**. La détruire coûte une attaque, sans savoir ce qu'on détruit.

| | Version d'origine (spec mère §3.7) | Version 2026-09-11 |
|---|---|---|
| Pose | 1 d'énergie fixe, n'importe quelle carte | **le coût de la carte**, seulement celles qui l'écrivent |
| Ce qu'elle vaut | 2 de Voix (4 avec `F03 Masque`) | **rien** tant qu'elle est cachée : elle attend son déclencheur |
| Révélation | à la fin de la manche | **à son déclencheur**, ou quand elle est détruite |
| Attaquable | non — les zones la protégeaient | **oui**, c'est la nouveauté |
| PV | sans objet | **= son coût en énergie**, et ils ne sont **pas affichés** |
| Détruite | sans objet | **révélée puis défaussée, son effet ne part pas** |

🚨 **C'est ce qui rend le bluff jouable au lieu d'être gratuit.** Dans la version d'origine, poser
face caché ne coûtait presque rien et ne risquait rien : la stratégie dominante était d'en poser
autant que possible. Rendre la carte attaquable met un prix sur le bluff — l'adversaire peut
dépenser une attaque pour lever le doute, et se tromper.

### ✅ Ses PV et sa mort, tranchés le 2026-09-11

> ⚖️ L'owner : *« Donner à la carte face cachée le même nombre de PV que l'énergie qu'elle
> coûte. »*

**PV = coût en énergie.** 🎁 C'est une valeur **dérivée**, pas posée : rien à calibrer, et toute
carte face cachée écrite plus tard en hérite sans qu'on y pense. C'est la règle de la maison
appliquée au bon endroit.

🚨 **Mais les PV ne sont PAS AFFICHÉS, et cette moitié n'est pas négociable.** Telle quelle, la
formule trahit la carte : les PV *disent* le coût, et le coût est le plus gros indice sur ce qu'une
carte cachée contient. Voir « 5 PV » revient à lire la moitié du dos. Cachés, la formule devient
meilleure qu'un nombre fixe connu — on frappe **sans savoir si le coup suffit**, et on apprend le
coût seulement quand la carte meurt. L'attaque devient un engagement au lieu d'un calcul.

🎁 **Et l'échelle tombe juste sans retouche.** Les attaques du paquet sont à **3-5** (un héros
commun frappe à ~4, `Le camion de Raiky` fait 4) :

| Coût de la carte cachée | Ce qu'il faut pour la tuer |
|---|---|
| 1 à 3 | n'importe quelle attaque, un seul coup |
| 4 à 5 | deux coups, ou un gros |

Une carte chère est donc réellement plus dure à déloger, une carte à 1 est du bluff jetable. Si la
calibration montre que tout meurt en un coup malgré tout, le levier est un **multiplicateur** sur
la formule (× 2), jamais une valeur écrite à la main.

**Détruite, elle est révélée puis défaussée — son effet NE PART PAS.**

C'est dur pour le défenseur, et c'est payé : l'attaquant a frappé du carton au lieu d'un héros. Il
a dépensé un tour de dégâts pour nier une carte qu'il ne connaissait pas. Les deux camps perdent
quelque chose, personne n'est gratuit.

🚨 **L'autre option se referme sur elle-même.** Si l'effet partait en mourant, attaquer une carte
cachée serait toujours un mauvais coup ; donc plus personne ne le ferait ; donc le face caché
redeviendrait gratuit — et on perdrait exactement ce que l'attaquabilité vient d'installer.

🎁 **Le gag du baril de Caustique survit quand même, sans exception à écrire.** Son effet démarre au
début du tour suivant : elle est donc cachée pendant **exactement un** tour adverse. C'est la
fenêtre pour la désamorcer ; ratée, elle se révèle en explosant toute seule. Le baril finit
toujours par partir, on a juste eu une chance de couper le fil.

⚠️ `F03 Masque` du catalogue décrit encore l'ancienne version (« posable face cachée pour 0
énergie, vaut 4 de Voix en Anonyme »). Il est à réécrire avec le reste des entrées reprises à
zéro — l'owner s'en charge, la ligne garde la ref en attendant.

---

La mesure du Piquant (`emotional_memory.anger`) n'est pas perdue : elle **oriente le choix de
l'Ultime**. Quelqu'un dont les échanges sont chargés reçoit un effet agressif du catalogue plutôt
qu'un effet de soutien. L'information décide d'un caractère au lieu d'être un score affiché.

---

## 8. À calibrer, dans cet ordre

1. **Le plafond d'énergie (12)** — le chiffre dont dépend l'existence même du choix (§3).
2. **Le coût des Ultimes (6-10)** — s'ils partent tous au même tour, l'échelle de style ne sert à rien.
3. **Les 40 PV par joueur en coop** — mesurer la durée d'un raid à 2, 4 et 6 joueurs.
4. **Le budget de base (12)** — décide de la durée d'un JcJ.
5. 🆕 **Le taux Aura ↔ énergie** (§3) — sans lui, aucune carte spéciale ne peut être écrite.
6. 🆕 **Le multiplicateur des PV d'une carte face cachée** (§7) — la formule est posée (PV = coût) ;
   il ne reste qu'à vérifier que l'échelle 1-5 contre des attaques de 3-5 laisse survivre les
   cartes chères. Si non, × 2 sur la formule, jamais une valeur à la main.

Rien ne se fige avant **quinze parties**, conformément à ce que font les designers indé.
