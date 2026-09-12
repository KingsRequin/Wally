# TCG du Purgatoire — les tactiques de la saison 1

> ⚖️ **2026-09-12 — ce fichier ne fait PAS foi.** L'owner : *« arrête de te fier aux règles, elles
> changeront une fois toutes les cartes terminées. Pour le moment, seules les cartes comptent, pas
> de règles. »* La source des cartes est la base Notion **🃏 Cartes du Purgatoire**.
> Le **Tirage du tour** (dé 1-6 partagé) est supprimé : le hasard du jeu est un **pourcentage pur**,
> résolu au moment de l'effet.

**Date** : 2026-09-04 · **Statut** : proposition, coûts à calibrer en parties de test
**Règles** : `2026-09-05-tcg-regles-heros-tactiques.md` · **Barème** : `2026-09-04-tcg-catalogue-reflexes.md` §1

Les héros sont figés à vie. **Tout le contenu neuf passe par ici** — et il change chaque saison.
C'est donc le seul endroit où la commu s'écrit vraiment.

> Chaque carte de cette liste vient d'un **fait réel** de la mémoire de Wally ou d'un topic de la
> commu, pas d'une idée de jeu générique. La colonne *Origine* le dit. Une tactique qui ne
> renvoie à rien de vécu n'a rien à faire dans une saison.

---

## 1. Deux sous-types

| | **Passif** | **Action** |
|---|---|---|
| Quand | posé, reste en jeu | joué, effet immédiat, part |
| Emplacements | **2 par joueur** | aucun |
| Coût | payé une fois à la pose | payé au moment de jouer |

⚠️ **Le sous-type se dit ACTION, plus « tactique » — 2026-09-12.** C'est le mot de l'owner, et
c'est celui que le recto affiche : le bandeau du bas d'une carte porte `ACTION` ou `PASSIF`. Le
reste de ce fichier et `2026-09-05-tcg-regles-heros-tactiques.md` disent encore « tactique » par
endroits — le renommage complet reste à faire, il touche deux specs et le nom d'un fichier.

Un passif occupe une place limitée : c'est ce qui l'empêche d'être toujours meilleur qu'une
tactique. Deux passifs maximum, on choisit.

## 3. Le prix

`coût en énergie = ⌈ valeur de l'effet en points / 3 ⌉`, borné 1-5 — le taux du barème
(1 énergie ≈ 3 points de budget). Un effet qui frappe l'adversaire vaut ×1,25 : le tempo coûte
plus cher que la masse.

---

## 3bis. ⚖️ Ce que le DESIGN a figé — relevé le 2026-09-12

Le recto et le dos des cartes action/passif ont été dessinés dans le projet Claude Design
« Conception plateau TCG Wally ». Trois fichiers font foi, et ils priment sur ce document pour
tout ce qui touche au type, à la catégorie et au coût :

| Fichier du projet | Ce qu'il porte |
|---|---|
| `Cartes Tactique.dc.html` | La planche — **46 entrées de catalogue, 52 cartes affichées** |
| `Carte Tactique.dc.html` | UNE carte, recto figé, réutilisable par le plateau |
| `Dos Carte.dc.html` | Le dos — 5 variantes, **`purgatoire` est celle retenue dans l'éditeur** |

Relevé figé sur disque : `/opt/design-tcg/import-2026-09-12/catalogue-cartes-action-passif.tsv`.
🚨 Les valeurs qui comptent dans un `.dc.html` sont les `default` des `data-props`, **jamais** les
replis `?? '…'` du `renderVals()`.

### 🚨 Tous les coûts sont remis à ZÉRO, et un 0 ne veut pas dire gratuit

> ⚖️ L'owner, 2026-09-12 : *« on ne peut pas mettre de coût alors que les cartes ne sont pas
> terminées, le coût est en rapport avec la puissance de la carte, donc faut attendre que tout
> soit fini. »*

Les colonnes `Coût` des tableaux du §4 portaient les valeurs calibrées des 2026-09-04/10. Elles
**ne sont plus la vérité** : la planche met 0 partout, et **28 des 46 règles y sont encore
« Règle pas encore écrite »**. La colonne est donc passée à `—`. Le raisonnement de prix qui avait
produit les anciens chiffres n'est pas perdu — il vit dans la propriété `Notes` de chaque fiche
de la base Notion « 🃏 Cartes du Purgatoire », carte par carte, avec sa chaîne de calcul.

⚠️ Le barème du §3 reste la règle de tarification. Ce qui change, c'est **quand** on l'applique :
à la fin, une fois l'effet arrêté, et pas pendant qu'on l'écrit.

### 🆕 Deux dimensions au lieu d'une : le TYPE et la CATÉGORIE

Le recto ne les mélange jamais. **Le cadre dit le type, le bandeau dit la catégorie.**

| Dimension | Valeurs | Où ça se voit |
|---|---|---|
| **Type** | `ACTION` `#2f5f94` · `PASSIF` `#f7ecd9` | Le cadre de la carte, et le bandeau du bas |
| **Catégorie** | attaque `#b23b2e` · soin `#3d6e46` · contrôle `#7a5296` · aura `#ad3f63` · ressource `#35707d` | La barrette du haut, avec son icône |

🚨 **L'or `#e1a947` est RÉSERVÉ à la pastille de coût.** L'Aura était or, elle est passée en baie
pour ça : deux choses différentes de la même couleur au même endroit se lisent comme la même
chose. Aucune catégorie ne portera d'or.

⚠️ **Ces cinq catégories ne sont PAS les cinq familles du §5** (Soin et protection · Attaque et
dégâts · Énergie et tempo · Aura et coopération · Rares). Les familles servaient à mesurer la
couverture du paquet ; les catégories sont ce qu'un joueur LIT sur la carte. Les comptes du §5
n'en dérivent pas et ne doivent pas être recalculés dessus.

Le passage aux catégories a **reclassé** quatre cartes par rapport aux familles : *Le
clavier-souris* et *Push par 3 teams* sont en **soin**, *Le care package* en **ressource**, *Un
montage de Malef* en **contrôle**.

### 🆕 Six cartes de plus, une renommée, cinq sans visuel

- **Renommée** : *Le scan de Crypto* → **`Le scan de Seer`**.
- **Au design mais pas dans ce fichier** (6) : *L'anti-cheat* · *Pika* · *Spiro* · *Lili* ·
  *Pika, Spiro et Lili* · *« C'est mon kill » / « NOTRE kill »*. Les quatre cartes de chats sont
  en `PASSIF / aura`, les deux autres en `ACTION`.
- **Ici mais pas encore dessinées** (5, arbitrage owner du 2026-09-12 — elles RESTENT au
  catalogue) : *Le mode diva* · *Michel-Velux* · *Sur le chemin* · *La Chute* · *Le pendu*. Elles
  portent `*(sans visuel)*` dans la colonne Type, et pas un type inventé : écrire `ACTION` pour
  une carte que la planche ignore ferait croire que le design l'a tranché.

### Les mécaniques d'illustration du recto

Une seule s'applique par carte, dans cet ordre : **rang** (carte à regrouper : icône entière
barrée en diagonale, frappée de « n SUR 3 ») · **semis** (l'icône répétée, position tirée d'une
graine FIXE dérivée du nom — deux captures de la même carte sont identiques) · **arc** (la même
figure, mais rangée en courbe : le semis dit « en vrac », l'arc dit « ensemble ») · **image**
(un visuel fourni, posé en **pochoir** et teinté de la couleur de catégorie, jamais en image
brute) · **texte** (le mot posé en Archivo Black à la taille d'une icône — *Quoi → FEUR* n'a pas
d'objet à dessiner, il a une réplique) · **icône de catégorie** en dernier recours.

⚠️ Chaque carte porte **deux** icônes, et c'est le but : celle du bandeau est celle de la
CATÉGORIE — identique sur toutes les cartes de la famille, c'est ce qui la rend lisible d'un coup
d'œil — et la grande est celle de la CARTE. Donner son icône au camion de Raiky n'efface pas
l'épée du bandeau.

⚠️ Le bandeau **FACE CACHÉE** n'est aujourd'hui posé que sur deux cartes (*Le baril de Caustique*,
*Typical Octane*). L'owner a généralisé la pose face cachée à **toute** carte action le
2026-09-12 — le recto ne le reflète pas encore, et il ne le doit peut-être pas : un bandeau porté
par 46 cartes sur 46 ne dit plus rien.

---

## 4. Les 45 cartes

> Compté en comptant les lignes du tableau, pas en relisant ce titre — l'écart d'une carte du
> 2026-09-04 (« 24 » annoncé pour 25 écrites) venait de là.

> **2026-09-10, pack de l'owner** : **16 cartes** de plus, écrites depuis sa liste, plus les deux
> nouveaux états et le retour de l'Anonyme. Quinze viennent de l'univers d'Apex ; la seizième — le
> steak haché — est la seule à sortir du chat. Chaque prix est refait au barème du §3, et chaque
> origine est vérifiée dans les logs avant écriture : ce qui n'a pas de trace le dit.
>
> **2026-09-10, seconde passe** : 8 cartes ajoutées après extraction des refs dans la mémoire de
> Wally, les memes rangés et les logs. Elles visent les **deux familles que le tri avait vidées**
> (§5) — Énergie passe de 2 à 5, Soin de 2 à 4. Chacune porte son indice de partage : nombre de
> personnes distinctes mesuré dans les logs, et/ou l'existence d'un **meme rangé**, qui est une
> preuve d'un autre ordre — quelqu'un l'a fabriqué et gardé.

### 🚨 Le tri de l'owner du 2026-09-10 — 11 cartes retirées sur 24

Ces cartes venaient de la **mémoire de Wally**. L'owner, en les relisant :

> *« Beaucoup de ces refs n'en sont pas. C'est pas parce que Wally le retient que tout le monde
> aussi — genre le café de MrMakkx, je sais même pas d'où ça vient et tout le monde s'en fout. »*

Il a raison, et c'est le même piège que celui payé sur les héros la veille : **Wally s'en souvient
≠ la commu la reconnaît.** Sa mémoire retient ce qu'une personne a dit une fois, avec la même
force qu'un running gag de six mois. Le critère d'une saison n'est pas la trace en base, c'est
le nombre de gens qui **riraient sans qu'on explique**.

Retirées : *Le café de MrMakkx* · *Grass shower* · *chatdodo* · *Temcox le petit cœur* ·
*Le test des 86 926 kills* · *Le cerveau de Rina a bug* · *Souvent en retard* · *4 h du matin* ·
*Le PC au micro-ondes* · *Le jingle de Lilio* · *Le dictateur requin*.

⚠️ **Et une mesure ne tranche pas à sa place.** J'ai compté les personnes distinctes employant
chaque ref dans les logs : elle confond « on parle de X » et « la ref est reconnue ». *La manette*
sortait à 44 personnes parce que le mot est générique ; 15 des « Rina » étaient en fait
`Origanire`, capté en sous-chaîne. Le chiffre est un indice, l'owner décide.

### ⚖️ On ne mesure plus les refs de l'owner — arbitrage du 2026-09-11

> ⚖️ L'owner : *« Tout ce que je mets c'est pertinent, ne vérifie pas les occurrences. »*

**Une ref proposée par l'owner est retenue, point.** Plus de comptage de personnes distinctes, plus
de « 2 occurrences contre 42 », plus de recale au nom du partage. Les chiffres déjà relevés dans la
colonne *Origine* restent — ils documentent ce qui a été mesuré — mais **ils ne sont plus un
critère**, et les cartes suivantes n'en porteront pas.

🎁 **Ce n'est pas un renoncement à la rigueur, c'est la conclusion de ce paragraphe-ci.** La mesure
avait déjà été prise trois fois en défaut le 2026-09-10 : *La manette* à 44 personnes pour un mot
générique, 15 « Rina » qui étaient `Origanire`, et *Raiky dans l'anneau* / *Push par 3 teams* à
zéro trace au chat alors que ce sont de vraies refs. Un indice faux la moitié du temps n'est pas un
indice. **Celui qui vit la commu sait ce qui fait rire ; le grep ne le sait pas.**

⚠️ Ce qui RESTE à vérifier, et qui n'a rien à voir : qu'une ref ne fasse pas **doublon** avec une
carte déjà écrite (c'est comme ça que *Blabla Rina* et *Le tunnel de Rina* ont été fusionnées), et
que son effet tienne le **barème**. Le tri éditorial est à l'owner, la cohérence mécanique est à
moi.

### 🚨 Deux cartes dépersonnalisées

*La manette* et *Le clavier-souris* étaient accrochées à quelqu'un (« Claker joue à la manette »,
« oyoloyoo n'a jamais joué à la manette »). Décision de l'owner : **ce sont des objets, pas des
refs à une personne.** Elles rejoignent la forme que sa liste du 2026-09-04 leur donnait déjà.
Bénéfice de bord : deux cartes de moins à faire valider par une personne réelle (§6).

### 🆕 Les états — posés ici parce que trois cartes en ont besoin

Le jeu n'avait aucun **état persistant** : chaque effet durait un tour et partait. Trois cartes
du 2026-09-10 en demandent un. Ils sont définis **une fois, ici**, et pas dans chaque carte —
sinon la quatrième carte réinventera son propre « il n'attaque pas », avec ses propres bornes.

| État | Durée | Effet |
|---|---|---|
| **Stun** | le tour où il est posé | le héros **n'attaque pas**, sans condition |
| **Régénération** | tant que le passif est en jeu | **+2 PV** au début de chacun de tes tours |
| 🆕 **Tunnel** | 2 tours | le héros **ne peut attaquer QUE** celui qui lui a posé l'état |
| 🆕 **Scroll** | le tour où il est posé | le héros **passe son tour** : ni attaque, ni Ultime |

> ⚖️ **Tunnel et Scroll, posés par l'owner le 2026-09-10.** *« Tunnel : force le héros à attaquer
> la personne qui inflige l'état. Scroll : fait passer un tour à l'adversaire. »*

🎁 **Tunnel comble le trou nommé au §5** : c'est le premier effet du jeu qui **redirige** au lieu
d'empêcher. Les trois états d'avant étaient tous des interdictions ; celui-ci force une cible, ce
qui est jouable des deux côtés — l'attaquant décide où le coup part, le défenseur peut s'en servir
pour protéger un héros faible. C'est un effet de *provocation*, la forme qui manquait à *Aura et
coopération*.

🚨 **Scroll est strictement plus fort que Stun, et c'est à surveiller.** Stun retire l'attaque ;
Scroll retire l'attaque **et** l'Ultime. Sur un héros qui allait déclencher un Ultime à 10, Scroll
vaut le double d'un Stun ; sur un héros ordinaire, exactement pareil. C'est donc un effet dont la
valeur dépend de la cible — la même forme que « copier l'Attaque », bornée sur *Aim assist* pour
cette raison. Ici la borne est structurelle : un Ultime ne se paie qu'une fois par partie ou deux,
Scroll ne peut donc pas répéter son meilleur cas. À vérifier en calibration quand même.

✅ **L'homonymie `Tunnel` est TRANCHÉE — 2026-09-11.** La carte *Le tunnel de Rina* et l'état
portaient le même nom pour deux effets différents.

> ⚖️ L'owner : *« Oui, c'est ça que je voulais. Les états ne sont pas des cartes. »*

Donc **la carte POSE l'état**, et il n'y a plus qu'un seul objet nommé *Tunnel* dans le jeu. Son
ancien effet (−2 d'Attaque à toute la table) est remplacé, cf. *Attaque et dégâts*.

🎁 **Et le gag y gagne.** −2 d'Attaque était une traduction tiède ; l'état dit exactement ce que
fait une anecdote de Rina — **tu ne peux plus parler à personne d'autre**. La règle générale se
lisait mal à l'envers : un état n'est pas une carte, c'est ce qu'une carte inflige. Aucun autre
état n'a de carte homonyme, celui-ci était le seul.

### 🆕 Le REGROUPEMENT — posé ici parce que deux cartes en ont besoin

> ⚖️ **Arbitrage de l'owner, 2026-09-11.** *« Une seule carte est comptée dans le deck, mais ça en
> ajoute deux autres en plus au moment de jouer. Quand récupérées, elles prennent chacune un
> emplacement dans les passifs ; elles se regroupent en une seule carte une fois les trois
> récupérées. »*

Deux cartes du pack fonctionnent par collection — *Le Rhum* et *La statue de Mirage*. Le
Regroupement est défini **une fois, ici**, et pas dans chacune : sinon la troisième réinventera sa
propre façon de compter.

| Étape | Ce qui se passe |
|---|---|
| Dans le deck | elle compte pour **UNE** carte sur les 12 |
| Jouée | elle verse ses **deux sœurs** dans ta pioche — elles ne coûtent rien à poser |
| Chaque sœur récupérée | occupe **un emplacement de passif** |
| À la troisième | les trois **se regroupent en une seule carte**, qui porte l'effet complet |

🎁 **Ça règle d'un coup les deux défauts que j'avais nommés, et c'est mieux que ce que je
proposais.** Je voyais deux problèmes séparés : *La statue de Mirage* gonflait le deck de 12 à 15,
et le « si 3 réunis » du *Rhum* demandait 3 emplacements de passif quand il n'y en a que 2. La même
règle les ferme tous les deux : **le deck reste à 12** (une seule carte comptée), et le
regroupement libère les emplacements au lieu d'en réclamer un troisième.

🎁 **Et les 2 emplacements tombent juste, ce n'est pas une coïncidence qu'il faut casser.** Première
sœur → emplacement 1. Deuxième → emplacement 2. La troisième arrive : le regroupement se fait
**à son arrivée**, les trois fondent en une carte, et il reste un emplacement libre. Le jeu n'a
jamais besoin de 3 emplacements, donc **la règle des 2 passifs n'est pas à toucher**.
⚠️ Corollaire à ne pas perdre : le regroupement est **immédiat**. S'il était différé d'un tour, il
faudrait bien tenir 3 passifs à la fois, et la mécanique redeviendrait injouable.

⚠️ **Tant que les trois ne sont pas réunies, le porteur n'a QUE le malus.** C'est voulu sur le
Rhum — on boit avant d'en tirer quoi que ce soit — mais ça veut dire qu'une carte à regrouper est
un **pari sur la durée de la partie**. Si les parties de test sont courtes, aucune des deux ne se
complète jamais et les deux sont mortes. C'est leur premier point de calibration, avant leur prix.

### Soin et protection

| Carte | Type | Catégorie | Coût | Effet | Origine |
|---|---|---|---|---|---|
| **Tenma** | PASSIF | attaque | — | le premier de tes héros qui tomberait à **0 PV survit à 1 PV** et gagne **+5 d'Attaque** ce tour | 2 memes — *« TENMA A 10HP : moi qui pensais pouvoir gagner mon 1v1 »* · 17 pers. |
| **Push par 3 teams** | ACTION | soin | — | **tu choisis** lequel de tes héros encaisse **toutes** les attaques adverses ce tour ; les autres ne subissent rien | le meme de la vache hébétée |
| **Le mode diva** | *(sans visuel)* | — | — | un héros allié devient la seule cible possible ce tour, et gagne +3 PV | l'entrée royale de Kassandre, statue de Lifeline comprise |
| **Lifeline** | PASSIF | soin | — | **Régénération** : +2 PV à un héros allié au début de chacun de tes tours | la médic d'Apex — la statue que Kassandre exige, et le perso que Raiky refuse de lâcher |
| **Mets-le dans du riz** | ACTION | soin | — | rend **6 PV** à un héros allié — mais **au début de ton prochain tour**, pas maintenant | *« mets ton casque dans du riz »* · *« t'as essayé de mettre ton arc star dans du riz avant de la jeter ? »* |
| 🆕 **Le totem** | PASSIF | soin | — | **une fois** : un de tes héros morts revient en ligne avec **la moitié de ses PV**, arrondie au supérieur | le totem de Revenant — 3 pers. au chat, mais la ref Apex se passe d'explication |
| 🆕 **La statue de Mirage** | PASSIF, **à regrouper** | soin | — | une fois les **trois** réunies et regroupées, **tes cartes de soin ne coûtent plus rien** | la statue — celle que Kassandre exige déjà pour son entrée royale |
| 🆕 **Le leurre** | ACTION | contrôle | — | double un de tes héros en jeu ; **une seule des deux copies est vraie**. Attaquer la fausse la détruit et **coûte le tour** de l'attaquant | Mirage — 5 pers. |
| 🆕 **Le Rhum** | PASSIF, **à regrouper** | soin | — | chaque Rhum en jeu fait perdre **1 PV tous les 5 tours** à son porteur. Les **trois** regroupées donnent **50 % d'esquive** | *« le rhum là »* · *« ya du rhum ? »* |
| 🆕 **Le baril de soins** | PASSIF | soin | — | tant qu'il est en jeu, **tout baril posé soigne au lieu de blesser** — y compris ceux de l'adversaire | le baril d'Apex, l'autre usage |

> `Le totem` **introduit la RÉANIMATION**, et c'est la première fois qu'un héros mort revient. Ce
> n'est pas un effet de plus : ça change la condition de victoire, qui repose sur les héros qui
> tombent. Prix 9 (un héros à mi-PV vaut plus qu'un gros soin), usage unique déjà compris dans le
> chiffre → `⌈9/3⌉ = 3` d'énergie, **et** un des deux emplacements de passif. Les deux ensemble
> sont ce qui l'empêche d'être automatique.
> 🚨 **À calibrer en premier du lot** : si réanimer est rentable, plus personne ne joue autre chose
> en passif.

> `La statue de Mirage` : ✅ **à REGROUPER** (§ ci-dessus) — le défaut « elle gonfle le deck de 12
> à 15 » est fermé par la règle générale, une seule carte est comptée.
> Prix : le soin **gratuit pour le reste de la partie** (et non une seule fois — l'arbitrage du
> 2026-09-11 porte sur la carte regroupée, qui est un passif permanent) ≈ 9 points, **× 0,5** pour
> une condition très longue → 4,5 → `⌈4,5/3⌉ = 2`… **ramené à 1** parce que deux des trois
> emplacements de passif sont immobilisés pendant toute la collecte. C'est le seul endroit du
> barème où un coût d'OCCUPATION entre dans le prix, et c'est justifié : le Regroupement est la
> seule mécanique qui fait payer en emplacements plutôt qu'en énergie.

> `Le leurre` : annule une attaque (≈ 4 points) **× 1,25** parce qu'il fait perdre son tour à
> l'adversaire → 5 → `⌈5/3⌉ = 2` d'énergie.
> ⚠️ Il repose sur de l'**information cachée en jeu**, la même famille que les cartes face cachée
> (§7 des règles) : le moteur doit pouvoir dire lequel est vrai sans jamais le montrer, et
> l'écrire au journal d'événements. Sinon un leurre deviné devient indiscernable d'un bug.
> ⚠️ **Mais ce n'est PAS une carte face cachée, et il ne suit donc pas sa règle de PV.** Une carte
> cachée a autant de PV que son coût ; le leurre, lui, est une copie de héros et porte les PV du
> héros copié — sinon on le reconnaîtrait au nombre de coups qu'il encaisse, ce qui tue le bluff.
> Et il garde sa pénalité propre : frapper la fausse **coûte le tour**, là où détruire une carte
> cachée ne coûte que l'attaque. C'est la seule exception du jeu, et elle est le prix de son coût 2.

> `Le Rhum` : ✅ **à REGROUPER** (§ ci-dessus) — le « si 3 réunis » que j'avais déclaré injouable
> est exactement ce que la règle générale rend jouable. Je l'avais écrit sans lui ; il est rétabli.
> Prix : +50 % d'esquive ≈ diviser par deux les dégâts reçus, tarifé à l'**espérance** → 5 points,
> **× 0,5** parce qu'il n'arrive qu'au regroupement, moins le malus subi de −1 PV/5 tours sur
> chaque porteur → 2 → `⌈2/3⌉ = 1` d'énergie. **Il passe de 2 à
> 1** : le payoff est le même, mais il se mérite.
> 🎁 **C'est la carte la plus fidèle du paquet, et c'est la mécanique qui l'a rendue telle.** Un
> seul Rhum ne fait que du mal à son porteur ; il en faut trois pour que ça serve à quelque chose,
> et ce qui sert c'est d'être difficile à toucher. On ne pouvait pas écrire ça avec un passif
> ordinaire.

> `Le baril de soins` est la **première carte du jeu qui modifie une autre carte** plutôt que des
> héros, et c'est un vrai apport : elle ouvre une couche de contre-jeu que le paquet n'avait pas.
> Prix : inverse un effet adverse, 4 **× 1,25** → 5 → `⌈5/3⌉ = 2` d'énergie.
> ⚠️ **Elle est morte si personne ne joue de baril.** Même défaut que *Michel-Velux* et
> *Quoi → FEUR* — une carte dont la valeur dépend entièrement du deck d'en face. À ce jour un seul
> baril existe (*Caustique*), donc une chance sur deux qu'elle ne serve jamais.

> `Mets-le dans du riz` : 6 PV valent 6 points, **× 0,8** parce que le soin est différé d'un tour
> (l'adversaire a un tour pour achever la cible) → 5 → `⌈5/3⌉ = 2` d'énergie. Le délai n'est pas
> un équilibrage, c'est le gag : le riz met la nuit à faire effet.

### Attaque et dégâts

| Carte | Type | Catégorie | Coût | Effet | Origine |
|---|---|---|---|---|---|
| **La manette** | PASSIF | attaque | — | à écrire (hasard pur) | l'objet, plus personne derrière |
| **Le clavier-souris** | PASSIF | soin | — | à écrire (hasard pur) | l'objet, plus personne derrière |
| **La Flatline d'Azraël** | PASSIF | attaque | — | **+4 d'Attaque** à un héros allié, pour toute la partie | *« c'est LE flatline »* · *« tu croises plus de hemlock que de flatline, ce jeu est si cruel »* |
| **Le tunnel de Rina** | ACTION | contrôle | — | pose l'état **Tunnel** sur un héros adverse — il ne peut plus attaquer que le tien, 2 tours | *« tout ça pour esquiver son tunel »* · *« tunel numero 2......... »* · le GIF Tenor dédié |
| **Codage à la Requin** | ACTION | attaque | — | à écrire (hasard pur) | ça compile ou ça casse |
| **Séance de révision avec Meliodas** | ACTION | contrôle | — | −3 d'Attaque à un héros adverse **et −1 au tien le plus fort** ce tour | on s'endort à deux |
| **Aim assist = aimbot** | ACTION | attaque | — | copie l'Attaque de ton héros le plus fort sur un autre des tiens ce tour, **dans la limite de +5** | le meme *The Office* « they're the same picture », signé Taki — 7 pers. |
| **Azraël met ta perk !** | ACTION | contrôle | — | à écrire (hasard pur) | le meme de la mouette qui inspire et hurle *« azrael met ta perk !!!! »* |
| **POV le chevreuil** | ACTION | contrôle | — | pose **Stun** sur un héros adverse — figé dans les phares | le meme du chevreuil *« quand il a vu la voiture »* |
| **Mozambique here!** | ACTION | attaque | — | un héros allié n'inflige plus que **1 dégât** ce tour, mais il frappe **TOUS** les héros adverses | le meme *« redis-le encore une fois »* — la pire arme d'Apex, devenue culte |
| **Raciste** | ACTION | contrôle | — | **−3 d'Attaque à tous les héros adverses qui partagent la même faction**, ce tour | le mot ne veut PAS dire ça ici : dans la commu, être raciste c'est jouer toujours les mêmes persos ou la même arme — ~10 pers. |
| 🆕 **Le camion de Raiky** | ACTION | attaque | — | **4 dégâts** à un héros adverse | son pseudo entier : *Raiky le fusible de camion* — 6 pers., 26 occ. |
| 🆕 **Le stim d'Octane** | ACTION | attaque | — | un héros allié perd **2 PV** et gagne **+4 d'Attaque** ce tour | Octane — 18 pers., 36 occ. |
| 🆕 **Le cluster** | ACTION | attaque | — | **4 dégâts répartis au hasard** entre les héros adverses, jamais plus de 2 sur le même | la grenade à fragmentation — 6 pers. |
| 🆕 **Le baril de Caustique** | ACTION, **face cachée** | attaque | — | **1 dégât à TOUS les héros** — les tiens compris — au début de chacun des 3 prochains tours | Caustique — 14 pers., 22 occ. |

> 🚨 **`Le tunnel de Rina` est la carte « Blabla Rina »**, proposée le 2026-09-05 dans la fiche
> Notion et jamais écrite ici. Même gag, même effet, même prix : **une seule carte**, sous le nom
> que l'owner lui a donné le 2026-09-10. Deux entrées auraient fait deux cartes du même gag —
> exactement le doublon que le tri venait de retirer côté personnes.
>
> ✅ **Son effet est RÉÉCRIT le 2026-09-11** : elle pose l'état **Tunnel** au lieu d'infliger −2
> d'Attaque à toute la table. C'est l'arbitrage d'homonymie du §4 — *« les états ne sont pas des
> cartes »* — et le gag y gagne : on ne baisse pas l'attaque des gens, on les empêche de parler à
> quelqu'un d'autre.
> Prix : une **redirection forcée** sur 2 tours ≈ 4 points **× 1,25** (elle frappe l'adversaire) →
> 5 → `⌈5/3⌉ = 2` d'énergie. **Même prix qu'avant**, par un autre chemin — l'ancien passait par
> C07 *Ponction*, qui ne s'applique plus.
> 🎁 **Et la réécriture ferme le défaut que l'ancienne version portait** : je l'avais laissée avec
> un « à vérifier en calibration — sur une table où elle est seule alliée, l'effet est purement
> offensif et vaut plus que 5 ». L'état n'a pas cette asymétrie : il ne touche qu'une cible, et ne
> dépend ni de la table ni des alliés.
> 🎁 Le son existe déjà : `data/sons/commande/rina.mp3`, migré de PhantomBot.
> ⚠️ Reste à surveiller, et c'est propre à l'état : **Tunnel peut PROTÉGER**. Poser Tunnel sur le
> plus gros héros adverse avec un héros-mur à toi le détourne de tes cartes fragiles pendant deux
> tours. C'est un usage défensif que le gag ne laissait pas prévoir, et il est peut-être meilleur
> que l'offensif.

> `La Flatline d'Azraël` : +4 d'Attaque permanent = 4 points → `⌈4/3⌉ = 2` d'énergie. C'est une
> arme, elle se garde — d'où le passif plutôt que la tactique.

> `Le camion de Raiky` est la seule carte du paquet à ne faire **que** des dégâts, sans clause, et
> c'est utile : un paquet sans carte simple n'a pas d'étalon. 4 dégâts **× 1,25** → 5 →
> `⌈5/3⌉ = 2` d'énergie. C'est le prix de référence auquel comparer tout le reste.
> Elle nomme Raiky, qui a déjà *Raiky dans l'anneau* et une carte-héros : trois entrées pour une
> personne, et ce n'est plus une dette depuis l'arbitrage du 2026-09-11 (§7) — une carte est une
> ref, pas un portrait.

> `Le stim d'Octane` : +4 d'Attaque le tour (4 points) moins un malus **subi** de 2 PV (× 0,5 →
> −1) → 3 → `⌈3/3⌉ = 1` d'énergie. Même forme que *Un piercing* : on se fait mal pour aller plus
> vite, et c'est exactement ce que fait le personnage.

> `Le cluster` : 4 dégâts répartis **× 1,25** → 5 → `⌈5/3⌉ = 2`.
> 🚨 **Le « jamais plus de 2 sur le même » n'est pas décoratif.** Sans borne, la répartition
> aléatoire peut mettre les 4 sur une seule cible et la carte devient parfois deux fois meilleure
> qu'un *camion de Raiky* pour le même prix. C'est le piège « aucun multiplicateur sans plafond »,
> payé sur B02 et *Aim assist*.

> `Le baril de Caustique` : ~3 dégâts par camp sur 3 tours, mais **symétriques** — pas de × 1,25,
> il frappe aussi les siens → 4 → `⌈4/3⌉ = 2` d'énergie.
> 🆕 **C'est l'une des trois cartes qui font revenir l'Anonyme** (§7 des règles), et elle a servi à
> trancher ses deux questions ouvertes le 2026-09-11 : une carte cachée a **autant de PV que son
> coût** (donc 2 ici, non affichés), et la détruire la **défausse sans déclencher son effet**.
> 🎁 **Son gag survit quand même, sans exception à écrire.** Son effet démarre au début du tour
> suivant : elle est cachée pendant **exactement un** tour adverse. C'est la fenêtre pour la
> désamorcer ; ratée, elle se révèle en explosant toute seule. Le baril finit toujours par partir,
> on a juste eu une chance de couper le fil.

### Énergie et tempo

| Carte | Type | Catégorie | Coût | Effet | Origine |
|---|---|---|---|---|---|
| **Les PP du samedi** | ACTION | ressource | — | **+4 d'énergie**, mais l'adversaire en gagne **2** | le rituel du samedi — **42 pers.**, 149 occ. |
| **Requin qui tente d'expliquer** | ACTION | contrôle | — | les tactiques de l'adversaire coûtent **+1 d'énergie** ce tour | le meme des formules confuses — 17 pers. |
| **Raiky dans l'anneau** | ACTION | contrôle | — | un héros de ta **réserve** entre en ligne immédiatement, mais perd **2 PV** | le meme *Let me in* — hors zone, il veut rentrer |
| **De l'air** | ACTION | ressource | — | l'adversaire gagne 2 d'énergie de moins au tour suivant | *« tu manges quoi à midi ? — de l'air 😅 »* |
| **Michel-Velux** | *(sans visuel)* | — | — | à écrire (hasard pur) | le running gag du TTS |
| 🆕 **Rendez-vous au véto** | ACTION | contrôle | — | pose **Scroll** sur un héros adverse — il passe son tour — **et −2 d'Aura** | les vrais rendez-vous chez le véto d'Azraël pour l'œil de Spiro, qui annulent des streams — 4 pers. |
| 🆕 **Le drone de Crypto** | ACTION | ressource | — | **regarde la main de l'adversaire** jusqu'à la fin du tour | Crypto — **25 pers., 121 occ.**, la ref la mieux partagée du lot |
| 🆕 **Le care package** | ACTION | ressource | — | pioche **3 cartes**, garde-en **1**, remets les autres au-dessus de ta pioche | le ravitaillement d'Apex |
| 🆕 **Le shop de Loba** | ACTION | ressource | — | prends **une carte au hasard** dans la main de l'adversaire | Loba — 19 pers., 40 occ. |
| 🆕 **Typical Octane** | ACTION, **face cachée** | ressource | — | la prochaine fois que l'adversaire pioche, **c'est toi qui prends la carte** | le meme *typical octane* — le mec qui part avec ce qui n'est pas à lui |
| 🆕 **Le scan de Seer** | ACTION | contrôle | — | **désactive tous les passifs adverses** pendant 2 tours | le drone qui scanne — 14 pers. sur *scan* |

> `Rendez-vous au véto` : Scroll sur un héros adverse vaut plus qu'un Stun (il retire aussi
> l'Ultime, cf. les états ci-dessus) — 4 points **× 1,25** = 5, plus 2 d'Aura retirée × 1,25 = 2,5
> → 7,5 → `⌈7,5/3⌉ = 3` d'énergie. **La plus chère du paquet Énergie**, et c'est voulu : priver
> quelqu'un d'un tour entier est le geste le plus brutal du jeu.
> 🎁 **Elle relie deux cartes de l'owner sans qu'on l'ait cherché** : les rendez-vous en question
> sont ceux de **Spiro**, qui a sa propre carte au pack 3. La ref est vérifiée et datée dans les
> logs — *« rendez vous veto en urgence demain matin »*, *« gros ulcère de la cornée »*,
> *« rendez vous veto pour un contrôle pour l'œil de Spiro à 10h, si c'est rapide je lance vers
> 10h30, sinon pas de matinale »*. Le stream saute : voilà pourquoi la carte fait passer un tour.
> 🚨 **L'owner a écrit « passe un tour adverse », ce qui peut se lire « TOUT le tour de
> l'adversaire ».** Écrit ici comme **un seul héros**, parce que sauter le tour entier d'un joueur
> pour 3 d'énergie est la carte la plus forte du jeu de très loin, et rend *La Chute* (5, la rare
> la plus chère) ridicule. Si l'owner voulait bien le tour complet, le prix n'est pas 3 : c'est
> une rare à 5 minimum, et elle demande sa propre calibration.

> `Le drone de Crypto` : de l'information pure, elle ne retire rien — 4 points, pas de × 1,25 →
> `⌈4/3⌉ = 2` d'énergie.
> 🚨 **En coop, cette carte vise Wally — et c'est le §9.3 en face.** Wally connaît sa main ; s'il
> doit la montrer, c'est le moteur qui la rend, pas lui. Le jour où le drone est joué contre lui,
> l'état public envoyé au juge et la main révélée aux joueurs sont **deux choses distinctes**, et
> les confondre se lit comme de la triche dans un sens ou dans l'autre.

> `Le care package` : +1 carte nette (2 points) plus la sélection sur trois (≈ 2 points de
> qualité) → 4 → `⌈4/3⌉ = 2` d'énergie. Remettre les deux autres **au-dessus** de la pioche et non
> dessous est ce qui la garde honnête : on sait ce qui arrive, l'adversaire aussi.

> `Le shop de Loba` : +1 carte pour toi (2) et −1 pour lui (2) **× 1,25** → 5 → `⌈5/3⌉ = 2`.
> ⚠️ **Au hasard, pas au choix.** L'owner a précisé *« main adverse face cachée »* et il a raison :
> choisir dans une main révélée vaudrait le double, et enchaîné après un *drone de Crypto* ça
> devient un combo à deux cartes qui prend la meilleure carte d'en face pour 4 d'énergie. À
> surveiller en calibration — c'est le seul combo à deux cartes du paquet.

> `Typical Octane` : +1 carte (2) et −1 pour l'adversaire (2) **× 1,25** → 5 → `⌈5/3⌉ = 2`. Même
> prix que le shop de Loba pour un effet voisin, et c'est cohérent : l'un prend dans la main,
> l'autre dans la pioche.
> 🆕 Troisième carte qui fait revenir l'**Anonyme** (§7 des règles) : 2 PV cachés (= son coût), et
> détruite elle part sans déclencher. Contrairement au baril, elle n'a **aucune fenêtre garantie** —
> elle attend que l'adversaire pioche, ce qui peut ne jamais venir avant qu'on la descende. C'est la
> plus fragile des trois, et c'est cohérent : elle vole, elle se cache vraiment.

> `Le scan de Crypto` : neutraliser jusqu'à 2 passifs pendant 2 tours ≈ 6 points **× 1,25** → 7,5
> → `⌈7,5/3⌉ = 3` d'énergie.
> ⚠️ **C'est un contre direct aux 12 passifs du paquet, dont 5 arrivés aujourd'hui.** Une carte
> anti-passif dans un paquet qui vient de doubler ses passifs se calibre en même temps qu'eux,
> jamais après : si elle est trop bonne, elle tue *Le totem*, *Lifeline*, *Le Rhum* et
> *La Flatline* d'un seul coup.

### Aura et coopération

| Carte | Type | Catégorie | Coût | Effet | Origine |
|---|---|---|---|---|---|
| **Apéro chez Zeddo** | ACTION | aura | — | +2 d'Aura à tous tes héros en ligne | l'apéro |
| **10 pizzas géantes** | ACTION | soin | — | rend 4 PV à **tous** tes héros. En coop, à ceux de tous les joueurs | la commande à 240 € |
| **Sur le chemin** | *(sans visuel)* | — | — | l'Aura de tes héros s'applique aussi aux héros des **autres joueurs** | le rituel de chanson du salon |
| **Un piercing de petitpoissonnn** | ACTION | aura | — | +3 d'Aura à un héros allié pour la partie, **et il perd 1 PV** | *« j'ai craqué j'ai un nouveau piercing azra »* · *« comme ça j'ai un nombre pair de piercing »* |
| 🆕 **Le steak haché de Meliodas** | ACTION | contrôle | — | désigne un héros adverse : ce tour, il **ne reçoit ni Aura ni soin allié**. Il est seul dans son assiette | *« mon steak haché ressemblait un peu à un pissenlit à être seul dans mon assiette »* — 5 pers. sur une semaine |

> `Le steak haché de Meliodas` : couper un héros de l'Aura et des soins de son camp ≈ 4 points
> **× 1,25** → 5 → `⌈5/3⌉ = 2` d'énergie.
> ✅ **La ref s'entretient toute seule, et c'est le meilleur signe qu'elle est solide** : la
> victime elle-même la relance. *« eh oh je suis pas sourd hein, laissez-moi tranquille avec ce
> foutu steak haché »* (meliodas987_, 01/09) · *« le plus rien dire en question: talk about
> melio's steak haché for the past week »* (02/09) · *« le steack haché avait faim »* (Malef__) ·
> *« c'est pour avoir un menu à base de steak haché »* (kassandreyunikon). **5 personnes, du 28/08
> au 02/09.** Une ref qu'on continue de servir à quelqu'un qui demande qu'on arrête est
> exactement le critère du §4 : tout le monde rit sans qu'on explique.
> 🎁 **C'est la SEULE des 16 cartes du jour à tomber dans *Aura et coopération*** — la famille qui
> n'avait rien reçu depuis le début (§5, §7). Elle y tombe naturellement parce que le gag EST un
> gag d'isolement : le seul du lot qui ne parle pas d'Apex.
> Elle nomme Meliodas, qui a déjà *Séance de révision* et une carte-héros — trois entrées, sans
> dette depuis l'arbitrage du 2026-09-11 (§7).
> ⚠️ Écrite « steak haché », pas « streak hacher » : la ligne Notion portait l'orthographe de la
> saisie. Le nom d'une carte est ce que les joueurs liront.

> `Un piercing` : +3 d'Aura permanent = 3 points, moins un malus subi de 1 PV (× 0,5 → −0,5) →
> 3 arrondi → `⌈3/3⌉ = 1` d'énergie. On souffre un peu pour être beau : c'est le gag, et c'est
> aussi la seule carte d'Aura qui se paie en PV plutôt qu'en énergie.

### Les rares — elles touchent aux mécaniques signature

| Carte | Type | Catégorie | Coût | Effet | Origine |
|---|---|---|---|---|---|
| **La Chute** | *(sans visuel)* | — | — | prends le contrôle d'un héros adverse jusqu'à la fin du tour suivant | l'auto-équilibrage emprunté au Mindbug, devenu une carte |
| **Un montage de Malef** | ACTION | contrôle | — | échange un héros de ta ligne avec un de ta réserve, en gardant ses PV actuels | le montage |
| **Le pendu** | *(sans visuel)* | — | — | nomme une carte ; si l'adversaire l'a en main, il la défausse. Sinon tu prends 2 dégâts | le jeu du pendu |
| **Quoi → FEUR** | ACTION | contrôle | — | **annule la prochaine tactique jouée par l'adversaire** ce tour | le meme du bouton rouge : *« quand quelqu'un dit quoi et qu'il y a Requin »* |

---

## 5. Le tri avait cassé une voie de victoire — comblé le jour même

L'owner avait posé une tension : **épargner pour l'Ultime**, ou **tout miser sur les tactiques**.
La seconde tenait sur quatre cartes ; le tri du 2026-09-10 en a sorti **trois** (*Souvent en
retard*, *4 h du matin*, *Le PC au micro-ondes*), ne laissant que Michel-Velux. Côté tenir,
*chatdodo* et *Temcox le petit cœur* étaient sorties aussi.

⚠️ **La leçon vaut au-delà de ce cas** : un tri éditorial peut casser un équilibre sans que
personne le voie. La liste reste cohérente **carte par carte** — c'est la **distribution par
famille** qui s'effondre. À recompter par famille après chaque tri, jamais seulement le total.

Comblé dans la foulée par la seconde passe :

| Famille | Après le tri | Après les passes du matin | 🆕 Après le pack de l'owner |
|---|---|---|---|
| Soin et protection | 2 | 5 | **10** |
| Attaque et dégâts | 6 | 11 | **15** |
| Énergie et tempo | **2** | 5 | **11** |
| Aura et coopération | 4 | 4 | **5** |
| Rares | 3 | **4** | 4 |

🎁 **Le pack de l'owner du 2026-09-10 (16 cartes) a corrigé le déséquilibre sans le viser.**
Attaque passe de **38 % à 33 %** du paquet non pas parce qu'on lui a retiré des cartes, mais parce
que les autres familles ont grossi plus vite. *Énergie et tempo* double, *Soin et protection*
double.

🚨 **Aura et coopération reste le trou, et il est maintenant le SEUL** : 5 cartes sur 45 (11 %).
Une seule des 16 cartes du pack y tombe — *Le steak haché de Meliodas*, et précisément parce que
c'est la seule ref du lot qui ne parle **pas** d'Apex. La cause est nommée depuis le début et elle
se confirme à chaque passe : **la source impose sa forme au résultat**. Quinze refs Apex donnent
quinze cartes de dégâts, d'énergie et de soin, parce que c'est ce qu'un jeu de tir sait produire.
→ La piste reste la même, et elle n'a toujours pas été exploitée : les **emotes de la chaîne**
(§ ci-dessous), qui ne parlent d'aucun jeu.

⚠️ Si les parties de test montrent que tout le monde choisit la même voie, ce sont ces deux
paquets qu'il faut rééquilibrer, **pas le plafond d'énergie** — lui ne se touche qu'en dernier,
il change tout le jeu d'un coup.

### D'où viennent les refs de la seconde passe

Extraites de la mémoire de Wally, des **memes rangés** et des logs, puis **mesurées avant
écriture**. Deux indices distincts, et ils ne disent pas la même chose :

- **le partage au chat** — combien de personnes distinctes emploient la ref ;
- **l'existence d'un meme rangé** — preuve d'un autre ordre : quelqu'un l'a fabriqué et gardé.
  *Raiky dans l'anneau* et *Push par 3 teams* n'ont aucune trace au chat et sont pourtant des
  refs solides, parce que le meme existe.

🎁 **Le gisement le plus riche n'était ni les faits ni les topics, mais les 358 memes décrits.**
Les faits rendent des THÈMES (Apex, ranked, wildcard, heirloom, manette) et non des gags ; les
14 topics parlent surtout du TCG lui-même. Le meme, lui, est déjà un gag que quelqu'un a jugé
digne d'être gardé — c'est un tri humain déjà fait.

🎁 **Et le gisement encore ouvert : les emotes de la chaîne.** `kassandreyunikon` **693** ·
`azrael74hype` 287 · `dance` 268 · `love` 148 · `queen` 105 · `fuze` 72 · `goodboi` 67 ·
`chadfuse` 67 · `koko` 61 · `cringe` 28 · `spongefuse` 27 · `gngngn` 20 · `triggered` 19 ·
`pewpew` 18 · `pepsi` 15 · `potatoaim` 12. Aucune des 25 cartes ne s'en sert. Elles échappent
aussi au reproche d'être des portraits (§7) : une emote n'est pas une personne.

### 🚨 « Raciste » — le mot ne veut pas dire ça ici

Dans cette commu, **être raciste, c'est jouer toujours les mêmes personnages ou la même arme**.
*« Je me disais bien que tu jouais des perso raciste »* · *« en ranked je joue Spitfire/Prowler,
j'suis un bon raciste aussi »* · *« une raciste dans son gameplay »* · *« Compétitive vs casual
racisme »*. Une dizaine de personnes distinctes l'emploient dans ce sens, et jamais dans l'autre.

La ref se traduit toute seule : **tu rejoues la même chose, tu le paies** — d'où le malus qui
frappe les héros adverses d'une même faction. Nom arrêté par l'owner le 2026-09-10.

### Deux cartes à surveiller en priorité

- **La Chute** (5) — la plus chère du jeu et elle doit le rester. Elle est ce qui autorise des
  héros vraiment forts sans casser le jeu : plus un héros est fort, plus le poser devient risqué.
- **Quoi → FEUR** — annuler une tactique pour 2 d'énergie est la meilleure affaire de la liste
  quand l'adversaire joue cher, et une carte morte quand il ne joue rien. C'est la première à
  faire tourner en calibration : une annulation bon marché aplatit tout un paquet d'un coup.

## 6. 🆕 Le deck de Wally — sa première carte est écrite

Le §5 des règles lui donne son propre paquet en coop ; il n'existait pas. L'owner en a posé la
première carte le 2026-09-10 :

> **« Viens en vocal »** — *« une carte spéciale, une carte du deck de Wally. Une fois jouée, ça
> lance une boîte de dialogue : un des joueurs doit parler avec Wally et le convaincre d'un truc.
> À voir encore quoi. »*

C'est la **première carte du jeu qui appelle le LLM en pleine partie**. Elle est encore une
intention, pas une règle — mais cinq points durs sont déjà identifiables, et **deux décident si
elle est faisable du tout** :

🚨 **1. Elle casse la reproductibilité, qui est la condition de toute la calibration.**
L'arbitrage du 2026-09-09 a choisi un moteur **heuristique à graine** contre un LLM précisément
parce qu'*« on ne peut pas équilibrer un jeu contre un adversaire non déterministe »* — 10 000
parties en une nuit, rejouables à l'identique. Une conversation ne se rejoue pas.
→ **Issue** : en calibration, la conversation est remplacée par un **verdict tiré à taux fixe**.
Sans ça, cette seule carte rend le paquet entier incalibrable.

🚨 **2. « Convaincre un LLM » est un vecteur d'attaque, pas une mécanique.** Le gagnant sera celui
qui sait manipuler un modèle, pas celui qui joue bien — et le jeu devient un concours d'injection.
🎁 La brique existe déjà dans le dépôt : `wrap_untrusted()` (`bot/core/untrusted.py`) borne le
texte externe et rappelle au modèle que c'est de la **donnée**, jamais une instruction. Le message
du joueur doit y passer, sans exception.

3. **Le temps.** Une conversation bloque toute la table : borner en nombre de messages ou en
   chrono, décidé avant d'écrire la règle.
4. **Vue censurée.** En coop, Wally est l'adversaire et connaît sa main. Le juge reçoit l'**état
   public**, jamais l'état complet — sinon il vend sa main ou commente ce que le joueur ne voit
   pas, ce qui se lit comme de la triche (§9.3 de la fiche).
5. **Cloisonnement.** Rien de cet échange ne repasse par `fact_extractor` ni par la consolidation
   nocturne. Une vanne de partie ne doit pas devenir un fait mémorisé sur quelqu'un.

⏸️ **Reste à définir par l'owner** : de quoi le joueur doit convaincre Wally, et ce qu'il gagne
ou perd. C'est la question qui décide de tout le reste — un enjeu faible rend la carte anecdotique
malgré son coût de développement, un enjeu fort la rend décisive et donc contestable.

### 🆕 La direction de son deck — « Wally doit être un vicieux », 2026-09-10

> ⚖️ L'owner : *« Wally doit être un vicieux. Il peut avoir des perks qui prennent une carte à un
> joueur et la lui font jouer au hasard, etc. »*

C'est la première **ligne éditoriale** donnée à son paquet, et elle vaut plus qu'une carte de plus :
elle dit de quelle FORME sont ses effets. Le §7 réclamait des cartes conçues *« contre un groupe,
pas contre un joueur »* sans dire lesquelles. Voilà la réponse : Wally ne frappe pas plus fort, il
**détourne** — il prend ce qui est à toi et s'en sert.

🎁 **La forme est déjà écrite ailleurs dans le jeu, et c'est ce qui la rend crédible.** *La Chute*
prend le contrôle d'un héros adverse, *Le shop de Loba* prend une carte en main, `F07 Rework`
emprunte un Ultime. Le deck de Wally est la version systématique de ce que le paquet fait déjà par
exception — pas une mécanique neuve à équilibrer de zéro.

🚨 **« La lui fait jouer au hasard » est la partie à écrire avec précaution.** Une carte volée puis
jouée au hasard est un effet dont la valeur ne dépend ni de Wally ni du joueur, mais du tirage :
c'est incalibrable et illisible en partie. Deux issues, et la seconde est meilleure :
- au hasard **parmi les cibles légales** seulement, jamais parmi les cartes ;
- ou **Wally choisit**, et c'est ce qui le rend vicieux plutôt que chanceux. Un adversaire qui
  retourne ta meilleure carte contre toi est une histoire ; un adversaire qui tire au sort est un
  dé.

⚠️ **Et ça heurte de front la vue censurée (§4 ci-dessus, §9.3 de la fiche).** Pour choisir *quelle*
carte prendre dans ta main, Wally doit la voir. En coop il est l'adversaire : soit c'est le
**moteur** qui applique l'effet sans que le modèle voie la main, soit c'est Wally qui commente ce
qu'il vient de faire **après coup** — jamais le modèle qui décide en regardant. La seconde est la
seule qui reste défendable si un joueur conteste.

---

## 7. Ce qui manque encore

- **Le reste du deck de Wally** : « Viens en vocal » est sa première carte (§6). Les autres
  doivent être conçues **contre un groupe**, pas contre un joueur.
- **Refaire les 5 cartes dont l'effet est marqué « à écrire (hasard pur) »**, une fois les
  pourcentages en stats posés. L'owner s'en charge ; les listes gardent les refs en attendant.
- **Rééquilibrer *Aura et coopération*.** Elle pèse **5 cartes sur 45** (11 %) et reste le seul
  trou après le pack du 2026-09-10 (§5). **La source impose sa forme au résultat** ; chercher
  toutes les refs dans les memes d'Apex déséquilibre le paquet sans qu'aucune décision ne l'ait
  voulu.
  🎁 Les refs retenues au pack 3 visent précisément ce trou : les trois chats, la carte des trois
  réunis, « c'est mon kill / NOTRE kill ». Et le gisement des **emotes** n'est toujours pas ouvert.
- 🆕 **La portée de *Rendez-vous au véto*** : un seul héros qui passe son tour, ou le tour entier de
  l'adversaire ? Écrite comme un héros à 3 d'énergie ; le tour complet en ferait une **rare à 5**,
  parce qu'elle dépasserait *La Chute*. ⏸️ **Seul point du pack encore ouvert.**
- ✅ **Soldés le 2026-09-11** : les **PV d'une carte face cachée** (= son coût, non affichés) et sa
  mort (révélée, défaussée, effet nié) — §7 des règles · la taille du deck face à *La statue de
  Mirage* et le « si 3 réunis » du *Rhum*, tous deux par le **Regroupement** (§4) · le doublon de
  nom `Tunnel`, la carte pose désormais l'état · le **consentement**, ci-dessous.
- **Les illustrations** : **45** cartes à générer, plus les héros. Coût à chiffrer avant d'ouvrir
  le robinet — il a grossi de 55 % en une journée.
- ✅ **Le consentement — TRANCHÉ le 2026-09-11, ce n'est plus un point dur.**

  > ⚖️ L'owner : *« On s'en fout de la personne que ça couvre, c'est des refs qui font des cartes
  > c'est tout. »*

  Treize cartes nomment des personnes réelles — **Kassandre** (mode diva), **Azraël** (Flatline,
  « notre kill »), **Rina** (tunnel), **Meliodas** (révision, steak haché), **Zeddo** (apéro),
  **Malef** (montage), **petitpoissonnn** (piercing), **KingsRequin** (codage), **Raiky** (anneau,
  camion), **Tenma**, **Spiro** (véto). Ce n'est plus une dette : **une carte est une ref, pas un
  portrait.** Plus de décompte par personne, plus de « Meliodas passe à trois entrées », plus de
  question sur qui peut consentir pour un chat.

  ⚠️ **Ce que ça ne couvre PAS, et qui reste vrai.** Deux garde-fous sont ailleurs et tiennent
  toujours : les cartes de **personnes** tirent leurs chiffres d'une formule sur la mémoire — ce
  sont elles qui risquaient de devenir un classement social public, pas les cartes-refs — et la
  règle du 2026-09-04 *« on ne joue jamais sur le stream »* (le public d'une carte, ce sont les
  joueurs). L'arbitrage porte sur le **nommage dans une ref**, rien d'autre.
