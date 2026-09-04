# TCG du Purgatoire — le catalogue fermé des Réflexes

**Date** : 2026-09-04 · **Statut** : proposition, à calibrer en parties de test
**Spec mère** : `docs/superpowers/specs/2026-08-29-tcg-purgatoire-design.md` (§2.4, §3)

Wally **choisit** un Réflexe dans ce catalogue et rédige la phrase qui l'habille. Il n'invente
jamais une mécanique, ne fixe jamais un prix. Le code exécute l'entrée, pas la phrase.

> ⚠️ C'est le **seul endroit du jeu où un humain conçoit vraiment**, donc le seul endroit où
> l'équilibre peut casser. Les ~315 cartes-personnes sortent d'une formule et ne sont pas un
> risque. Ces 53 entrées le sont. D'où le plafond, le barème de prix ci-dessous, et l'interdiction
> d'ajouter une entrée sans lui appliquer le barème.

---

## 0. Ce que trois arbitrages du 2026-09-04 changent

| Arbitrage | Conséquence sur ce catalogue |
|---|---|
| **Les cartes objets/moments entrent dans le deck de 12** | Le catalogue sert deux fois : il habille une carte-personne, ou il **est** une carte-objet à lui seul. D'où la colonne *Portée*. |
| **Le hasard est tiré et AFFICHÉ avant la pose** | Un seul aléa par tour, partagé : le **Tirage du tour** (§2). Aucune entrée ne lance de dé pour elle-même. |
| **On ne joue jamais sur le stream** | Aucun Réflexe ne lit l'état du live, ne s'adresse aux viewers, ni ne déclenche quoi que ce soit sur l'overlay. Le Réveil (famille H) lit l'activité des **personnes**, pas la surface de jeu. |

---

## 1. Le barème — d'où sort un prix

Le prix est payé sur le budget de stats de la carte :
`budget = budget_base(coût) + bonus_rareté − prix_du_Réflexe` (spec §2.2).

Un prix n'est donc pas une opinion, c'est une conversion. **1 point de budget = 1 point de Voix**,
par définition. Tout le reste s'y ramène :

| Ce que fait l'effet | Conversion |
|---|---|
| Voix, inconditionnel et permanent | prix = gain |
| Conditionnel **subi** (la condition tombe ou non, ~1 fois sur 2) | gain × 0,5, arrondi au supérieur |
| Conditionnel **choisi** (le joueur décide quand le déclencher) | gain × 0,8 — voir l'avertissement du §2 |
| Usage unique dans la partie | × 0,5 |
| Qui touche l'adversaire (retirer, priver, bloquer) | × 1,25 — le tempo vaut plus que la masse |
| 1 énergie | ≈ 3 points (une carte moyenne coûte 3) |
| 1 carte piochée | ≈ 2 points (on en pioche déjà une par tour) |
| Qui neutralise une mécanique signature (Chute, Anonyme, Renoncement) | **plancher 5**, quelle que soit la fréquence |

Le dernier plancher n'est pas négociable : la Chute est l'auto-équilibrage de tout le jeu
(spec §3.6). La rendre évitable à bas prix rouvre exactement la porte qu'elle ferme.

⚠️ **Aucun effet multiplicatif n'est jamais laissé sans plafond.** Un prix est fixe, un
multiplicateur est proportionnel : « sa Voix est doublée » à prix 3 vaut +2 sur une petite carte
et +9 sur une grosse. C'est cassé par construction. Tout doublement de ce catalogue est borné en
valeur absolue (I01, B02).

### Qui peut porter quoi

- **Carte-personne** : `prix ≤ budget − 1` (il faut garder `Voix ≥ 1`).
- **Carte-objet ou moment** : pas de stats, donc **elle paie son effet en ÉNERGIE, pas en
  budget** → `coût = ⌈prix / 3⌉`, borné à 1-5. Le taux est celui du barème ci-dessus
  (1 énergie ≈ 3 points), il n'y en a pas deux.

  ⚠️ La règle précédente — `prix ≤ 4 + 3 × coût`, « elle convertit tout son budget en effet » —
  **était fausse et je l'ai corrigée en construisant le contrôle de saisie**. Aucun prix du
  catalogue ne dépasse 6, le budget minimum est 7 : *aucune* carte-objet n'aurait jamais pu
  dépenser son budget, et toutes seraient nées sous-payées. Une règle qui ne peut être satisfaite
  par aucun cas réel n'est pas une contrainte, c'est un angle mort.

### Objet ou moment — ce qui décide, c'est le moment de l'effet

| | Reste sur la table ? | Occupe une place ? | Déclencheurs concernés |
|---|---|---|---|
| **Objet** | oui, jusqu'à la fin | oui, une des 4 | `permanent`, `au décompte`, `fin de tour` |
| **Moment** | non, il part aussitôt son effet produit | **non** | `à la pose`, `à la révélation` |

C'est la seule compensation qu'un moment reçoit pour ne poser aucune Voix : il ne prend la place
de personne. Un **objet**, lui, occupe une place à 0 Voix — c'est le point le plus fragile de tout
le barème, et **le premier à calibrer en parties de test** (§5).
- **Exception, famille F** : une carte-objet ou moment portant une entrée de la famille F a un
  **coût minimum de 3**, quel que soit ce que donne `⌈prix / 3⌉`. Sans cette ligne, F06 (prix 6)
  tomberait à 2 d'énergie et annulerait une Chute pour presque rien — le plancher de *prix* serait
  respecté, et celui d'**énergie** contourné.

Conséquence utile côté cartes-personnes : les entrées à prix 5+ sont de fait réservées aux cartes
chères ou rares. Aucune règle de plus à écrire — l'inégalité `prix ≤ budget − 1` s'en charge.

---

## 2. Le Tirage du tour — le seul hasard du jeu

Au début de chaque tour, **avant la pose**, un dé 1-6 est lancé et **affiché aux deux joueurs**.
Toutes les entrées de la famille I lisent ce même dé.

C'est ce qui rend le hasard jouable au lieu d'être subi : quand tu poses ta manette, tu **sais
déjà** ce que le tirage vaut. Une carte à hasard n'est pas un pari, c'est une carte qui est bonne
certains tours et mauvaise d'autres — et Wally peut la commenter avant, pas seulement après.

> 🚨 **Le piège de ce design, et c'est le vrai.** Un hasard affiché avant la pose **n'est plus une
> espérance, c'est une option** : le joueur ne la joue que sur le bon tirage. Un effet « +6 une
> fois sur trois » ne vaut pas +2 en moyenne, il vaut **+6**, parce que sur cinq tours le bon
> tirage sort presque toujours au moins une fois (≈ 87 % pour un seuil de 4).
>
> **Les prix de la famille I se calculent donc sur le MEILLEUR cas, jamais sur la moyenne.** Un
> catalogue qui les tarife à l'espérance rend mécaniquement les cartes à hasard les meilleures du
> jeu — c'est la faute classique, et elle est invisible tant qu'on n'a pas joué vingt parties.

Corollaire : aucun effet ne relance, ne modifie ni ne cache le Tirage. Une seule source d'aléa,
publique, par tour.

---

## 3. Les familles

Portée : **👤** habille une carte-personne · **🎴** peut être une carte-objet autonome ·
**👤🎴** les deux.

### A — Voix conditionnelle (le socle)

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| A01 | Tenue de table | 2 | permanent | +3 Voix tant qu'elle est ta seule carte sur cette table | 👤 |
| A02 | Renfort | 3 | à l'arrivée d'une alliée | +1 Voix par autre carte alliée de sa table (max +3) | 👤 |
| A03 | Dernier mot | 3 | à la pose | +4 Voix si posée au tour 5 | 👤 |
| A04 | Contre-pied | 2 | à la révélation | +3 Voix si l'adversaire mène cette table | 👤 |
| A05 | Poids mort | 4 | permanent | +5 Voix, et −2 Voix à la carte alliée adjacente | 👤 |
| A06 | Montée en régime | 4 | fin de tour | +1 Voix cumulatif à chaque fin de tour où elle est en jeu (max +4) | 👤 |

### B — Aura, adjacence, propagation

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| B01 | Rassemblement — *« apéro chez Zeddo »* | 3 | permanent | +1 Aura à toutes tes cartes de cette table | 👤🎴 |
| B02 | Épaule | 3 | à la pose | +3 à l'Aura qu'elle donne à une carte alliée adjacente désignée | 👤 |
| B03 | Liant | 4 | permanent | son Aura touche toutes tes cartes de la table, pas seulement les adjacentes | 👤 |
| B04 | Duo forcé | 4 | à la pose | forme un Duo avec une carte alliée adjacente même sans lien réel | 👤🎴 |
| B05 | Écho | 2 | à l'arrivée d'une alliée | +1 Voix à chaque carte alliée qui arrive sur sa table après elle | 👤🎴 |
| B06 | Propagation — *« le meme de la commu »* | 2 | à la pose | +1 Voix à toutes tes cartes en jeu partageant une affinité avec elle | 🎴 |

### C — Piquant et attaque

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| C01 | Pointe | 3 | permanent | +2 Piquant | 👤 |
| C02 | Double tranchant | 4 | au décompte | son Piquant frappe deux cartes adverses au lieu d'une | 👤 |
| C03 | Marquage | 2 | à la pose | désigne une carte adverse : tout ton Piquant de cette table la vise en priorité | 👤🎴 |
| C04 | Séance de révision — *« avec Meliodas »* | 2 | à la révélation | −2 Voix à une carte adverse de sa table, **et −1 à ta carte adjacente** | 🎴 |
| C05 | Contre-attaque | 2 | quand elle subit du Piquant | en renvoie la moitié (arrondi inférieur) à la source | 👤 |
| C06 | Silence | 4 | à la pose | la carte adverse la plus chère de sa table perd son Réflexe | 👤 |
| C07 | Ponction | 4 | au décompte | −1 Voix à toutes les cartes adverses de sa table | 👤🎴 |

### D — Tables et placement

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| D01 | Remontage — *« un montage de Malef »* | 5 | une fois, à la révélation | reprends une de tes cartes posées et repose-la sur une autre table, sans payer son coût | 🎴 |
| D02 | Verrou | 5 | à la pose, **tours 1 à 4 seulement** | l'adversaire ne peut plus rien poser sur cette table ce tour-ci | 👤🎴 |
| D03 | Place réservée | 2 | permanent | sa table accepte 5 cartes alliées au lieu de 4 | 👤🎴 |
| D04 | Squat | 3 | à la pose | +4 Voix, mais elle occupe deux places de la table | 👤 |
| D05 | Coup d'œil | 2 | à la pose | révèle le sujet d'une table non encore révélée | 👤🎴 |

### E — Énergie et main

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| E01 | Diète — *« tu manges quoi à midi ? — De l'air »* | 4 | à la révélation | l'adversaire a 1 énergie de moins au tour suivant | 🎴 |
| E02 | Second souffle | 3 | à la pose | +1 énergie immédiatement, ce tour-ci | 👤🎴 |
| E03 | Rab | 2 | à la pose | pioche une carte | 👤🎴 |
| E04 | Tri | 3 | à la pose | défausse une carte, pioches-en deux | 👤🎴 |
| E05 | Radin | 2 | fin de tour | +3 Voix si tu n'as pas dépensé toute ton énergie ce tour | 👤 |

### F — Chute, Anonyme, Renoncement (mécaniques signature — plancher 5, objets à coût ≥ 3)

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| F01 | Insaisissable | 5 | permanent | ne peut pas être Chutée | 👤 |
| F02 | Retour de flamme | 5 | si elle est Chutée | l'adversaire perd 2 énergie au tour suivant | 👤 |
| F03 | Masque | 4 | à la pose | posable face cachée pour 0 énergie, et vaut 4 de Voix en Anonyme au lieu de 2. **Seule exception à « l'Anonyme n'a pas de Réflexe »** (spec §3.7) : celui-ci s'applique, et lui seul | 👤 |
| F04 | Démasquage | 3 | à la pose | révèle immédiatement une carte Anonyme adverse de sa table | 👤🎴 |
| F05 | Retenue | 3 | si tu Renonces à sa table | elle revient en main **et** tu récupères son coût en énergie | 👤 |
| F06 | Rachat | 6 | une fois | récupère une de tes cartes Chutée par l'adversaire ; elle revient en main | 🎴 |

### G — Affinités et factions

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| G01 | Touche-à-tout | 2 | permanent | compte comme portant l'affinité de la table où elle est posée | 👤 |
| G02 | Spécialiste | 2 | au décompte | +4 Voix si une de ses affinités correspond au sujet de la table | 👤 |
| G03 | Bannière | 2 | permanent | +1 Voix à tes cartes de même faction sur cette table | 👤🎴 |
| G04 | Sujet imposé | 5 | à la pose sur une table non révélée | tu choisis son sujet parmi deux tirés | 🎴 |

### H — Réveil et Duo (les greffes commu)

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| H01 | Réveil forcé — *« le jingle de Lilio »* | 2 | à la pose | une de tes cartes de cette table devient Réveillée sans condition. **Compte dans le plafond de 3 réveils** | 🎴 |
| H02 | Insomniaque | 2 | permanent | sa fenêtre de Réveil est toujours de 24 h, quelle que soit celle en cours | 👤 |
| H03 | Meneur | 3 | au décompte | si elle est Réveillée, +2 Voix à toutes tes cartes de sa table | 👤 |
| H04 | Vieux pote | 4 | à la pose | son Aura s'applique **aussi** à une carte alliée désignée d'une autre table, et un Duo la double si le lien réel existe | 👤 |

### I — Le Tirage du tour (hasard visible — prix au MEILLEUR cas, cf. §2)

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| I01 | Critique — *« la manette »* | 4 | au décompte | si le Tirage du tour où elle a été posée ≥ 4, sa Voix est doublée, **dans la limite de +5**. En objet : celle d'une alliée désignée (§4.6) | 👤🎴 |
| I02 | Esquive — *« clavier-souris »* | 3 | au décompte | si le Tirage ≥ 3, elle ignore tout le Piquant qui la vise. En objet : protège une alliée désignée (§4.6) | 👤🎴 |
| I03 | Ça compile ou ça casse — *« codage à la Requin »* | 4 | au décompte | Tirage ≥ 5 : +6 Voix · Tirage ≤ 2 : −3 Voix · sinon rien | 🎴 |
| I04 | À la valeur | 5 | à la pose | gagne autant de Voix que le Tirage du tour (+1 à +6) | 👤 |
| I05 | Superstition | 3 | au décompte | +3 Voix si le Tirage du tour est pair | 👤 |

### J — Soin et protection

| ID | Nom mécanique | Prix | Déclencheur | Effet | Portée |
|---|---|---|---|---|---|
| J01 | Soin | 2 | à la pose | rend 3 Voix perdues à une de tes cartes de cette table, jamais au-dessus de sa valeur d'origine | 🎴 |
| J02 | Garde | 2 | permanent | le Piquant adverse de cette table la vise en premier | 👤 |
| J03 | Bouclier | 3 | permanent | une carte alliée adjacente désignée ignore le Piquant | 👤 |
| J04 | Rémission | 3 | au décompte | si le Piquant subi la réduit à 0, elle compte pour 3 | 👤 |
| J05 | Trousse | 3 | fin de tour | +1 Voix à ta carte de plus basse Voix sur cette table | 👤🎴 |

**Total : 53 entrées** (A 6 · B 6 · C 7 · D 5 · E 5 · F 6 · G 4 · H 4 · I 5 · J 5) — la marge
jusqu'au plafond de 60 est volontaire.

---

## 4. Règles d'exécution — ce que le moteur doit trancher sans jugement

Le §3.2 de la spec mère fixe déjà l'ordre : **coût croissant, puis Voix décroissante, puis
identifiant de carte.** Ce catalogue ajoute cinq points qui, non écrits, deviendraient des
contestations en pleine partie :

1. **Une carte ne porte qu'un seul Réflexe.** Un objet **est** son Réflexe.
2. **Un effet permanent ne se recalcule qu'aux moments définis** (pose, arrivée d'une alliée, fin
   de tour, décompte). Jamais en continu — sinon A02 et B05 se déclenchent en boucle.
3. **Les modificateurs de Voix se cumulent additivement ; le doublement (I01) s'applique en
   DERNIER**, après tous les `+` et `−`. Sans cet ordre fixé, la même main donne deux scores
   différents selon l'ordre de lecture.
4. **Un effet qui désigne une cible absente ne se déclenche pas** — il ne se reporte jamais sur
   une autre. Même règle que le Piquant (spec §2.3).
5. **Une carte-objet ne donne ni Voix, ni Aura, ni Piquant, et n'a pas d'affinité** — sauf si son
   entrée le dit explicitement. Elle occupe une place de table et rien d'autre. Un **moment**
   n'occupe même pas de place : il part une fois son effet produit.
6. **Un objet ne peut pas être la cible de son propre effet.** Toute entrée dont l'effet porte sur
   « elle-même » désigne, quand elle est jouée comme objet, **une carte alliée de sa table**, à la
   pose ; c'est elle qui reçoit l'effet.

   > 🚨 Trouvé en remplissant les fiches des dix cartes de l'owner, pas en écrivant le catalogue.
   > Un objet pose 0 Voix : **la manette doublait 0**, et le clavier-souris esquivait un Piquant
   > qui ne l'avait jamais visée. Deux cartes qui ne faisaient littéralement rien, avec un prix,
   > un coût et une illustration. Une règle générale plutôt qu'une exception par entrée : la
   > prochaine entrée 👤🎴 écrite dans six mois est couverte sans que personne y repense.
7. **Le Piquant ne vise jamais un objet** — il n'a pas de Voix à lui retirer. Sinon un objet à
   0 Voix devient un absorbeur de Piquant gratuit : c'est pour ça que J02 (Garde) est réservée aux
   cartes-personnes, et que C03 (Marquage) ne peut pas désigner un objet adverse.

---

## 5. Ce qui reste à calibrer, et par quoi

Aucun de ces 53 prix ne survivra intact à quinze parties, et c'est prévu — les designers
indé le disent tous. Ce qui compte, c'est **par quoi** on les corrige :

| À mesurer | Signal qui dit « ce prix est faux » |
|---|---|
| Taux de présence en deck, par entrée | jamais choisie = trop chère ; dans 80 % des decks = trop peu chère |
| Taux de victoire des parties où l'entrée a été jouée | l'écart à 50 % est le vrai prix |
| Par famille | une famille entière sur- ou sous-représentée = c'est le **barème** (§1) qui est faux, pas l'entrée |
| Famille I | si elle domine les decks, c'est que le §2 a été oublié et que les prix sont retombés à l'espérance |
| Le plancher signature (F) | si les Chutes tombent sous ~1,2 par partie, F01/F06 sont trop accessibles |
| **Les objets** (ceux qui restent) | **le premier point à mesurer.** Un objet occupe une place à 0 Voix ; s'ils sont absents des decks, c'est que la place vaut plus cher que l'effet, et `coût = ⌈prix/3⌉` doit descendre à `⌈prix/4⌉` pour eux seuls |

Tout cela **sort du journal d'événements** (télémétrie demandée par l'owner le 2026-09-04) — et
n'existe que si ce journal est posé **avec** la première partie, jamais après.
