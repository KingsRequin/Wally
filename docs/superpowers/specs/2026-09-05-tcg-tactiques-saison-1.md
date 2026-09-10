# TCG du Purgatoire — les tactiques de la saison 1

**Date** : 2026-09-04 · **Statut** : proposition, coûts à calibrer en parties de test
**Règles** : `2026-09-05-tcg-regles-heros-tactiques.md` · **Barème** : `2026-09-04-tcg-catalogue-reflexes.md` §1

Les héros sont figés à vie. **Tout le contenu neuf passe par ici** — et il change chaque saison.
C'est donc le seul endroit où la commu s'écrit vraiment.

> Chaque carte de cette liste vient d'un **fait réel** de la mémoire de Wally ou d'un topic de la
> commu, pas d'une idée de jeu générique. La colonne *Origine* le dit. Une tactique qui ne
> renvoie à rien de vécu n'a rien à faire dans une saison.

---

## 1. Deux sous-types

| | **Passif** | **Tactique** |
|---|---|---|
| Quand | posé, reste en jeu | joué, effet immédiat, part |
| Emplacements | **2 par joueur** | aucun |
| Coût | payé une fois à la pose | payé au moment de jouer |

Un passif occupe une place limitée : c'est ce qui l'empêche d'être toujours meilleur qu'une
tactique. Deux passifs maximum, on choisit.

## 2. ⚰️ Le Tirage du tour — SUPPRIMÉ le 2026-09-10

> ⚖️ L'owner : *« Il y aurait du hasard en stats — esquive, boost d'attaque, chance de heal, etc.
> Pas de dé. »*

Il y avait un dé 1-6 lancé et **affiché aux deux joueurs** au début de chaque tour. Il n'existe
plus : le hasard est désormais un **pourcentage porté par la carte**, résolu au moment de l'effet
(cf. `2026-09-05-tcg-regles-heros-tactiques.md` §2bis).

🚨 **Six cartes de cette liste lisent encore « si le Tirage ≥ N » et sont donc À REFAIRE** :
*La manette* · *Le clavier-souris* · *Codage à la Requin* · *Michel-Velux* (dont le contre entier
reposait sur le Tirage) · *Azraël met ta perk !* (état Oublie) · et l'état **Oublie** lui-même.
Elles sont laissées telles quelles à dessein : l'owner refait les cartes, cette liste sert à
garder les **refs**. Les remplacer à moitié maintenant ferait deux vocabulaires en circulation —
le défaut retiré le 2026-09-09.

🎁 **La tarification se simplifie, et à la baisse.** Ces effets se tarifaient **au meilleur cas**,
parce qu'un hasard affiché avant la pose n'est pas une espérance mais une **option** — on
n'engageait que sur le bon tirage. Un hasard **caché** ne se choisit pas : « +6 une fois sur
trois » revaut **+2**.

## 3. Le prix

`coût en énergie = ⌈ valeur de l'effet en points / 3 ⌉`, borné 1-5 — le taux du barème
(1 énergie ≈ 3 points de budget). Un effet qui frappe l'adversaire vaut ×1,25 : le tempo coûte
plus cher que la masse.

---

## 4. Les 29 cartes

> Compté en comptant les lignes du tableau, pas en relisant ce titre — l'écart d'une carte du
> 2026-09-04 (« 24 » annoncé pour 25 écrites) venait de là.

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
| **Oublie** | 2 tours | le héros **n'attaque pas si le Tirage du tour est ≤ 3** |
| **Stun** | le tour où il est posé | le héros **n'attaque pas**, sans condition |
| **Régénération** | tant que le passif est en jeu | **+2 PV** au début de chacun de tes tours |

🚨 **`Oublie` lit le Tirage, et ce n'est pas un détail d'équilibrage.** L'owner l'avait demandé
comme *« un pourcentage de chance d'oublier d'attaquer »* — c'est-à-dire un **jet caché**, résolu
au moment de l'attaque. L'arbitrage du 2026-09-04 l'interdit : le hasard est *tiré et affiché
avant la pose*. Un pourcentage caché est incommentable en direct (Wally ne peut plus raconter
pourquoi une table bascule) et **indiscernable d'un bug de calcul de dégâts**. Accroché au
Tirage, l'effet est le même — une fois sur deux — mais les deux joueurs le voient venir.

⚠️ **`Stun` est déterministe et n'a donc pas besoin du Tirage.** Ne pas lui en ajouter un « pour
faire pareil » : un effet certain qui coûte son prix est plus simple à calibrer qu'un effet
conditionnel, et le jeu en a besoin d'au moins un.

### 🚨 Le Tirage n'est défini dans AUCUNE règle

`2026-09-05-tcg-regles-heros-tactiques.md` ne contient **pas une seule fois** le mot « Tirage ».
Il n'existe que dans ce document (§2) et dans le catalogue des Réflexes — alors que **15 cartes
en dépendent** et que l'arbitrage du 2026-09-09 fait dériver **tout le critique de l'Aura** de
son seuil.

Pire : le §7 des règles retire la roulette de début de partie en écrivant *« la tension vient
maintenant de l'énergie, pas d'un tirage »*. La roulette et le Tirage du tour sont deux choses
distinctes, mais cette phrase se lit comme si le dé était mort lui aussi.

→ **À remonter dans les règles**, avec les états ci-dessus. Une mécanique centrale définie
uniquement dans un catalogue de cartes est une mécanique qu'on retirera par erreur.

### Soin et protection

| Carte | Type | Coût | Effet | Origine |
|---|---|---|---|---|
| **Tenma à 10 HP** | passif | 2 | le premier de tes héros qui tomberait à **0 PV survit à 1 PV** et gagne **+5 d'Attaque** ce tour | 2 memes — *« TENMA A 10HP : moi qui pensais pouvoir gagner mon 1v1 »* · 17 pers. |
| **Push par 3 teams** | tactique | 1 | **tu choisis** lequel de tes héros encaisse **toutes** les attaques adverses ce tour ; les autres ne subissent rien | le meme de la vache hébétée |
| **Le mode diva** | tactique | 3 | un héros allié devient la seule cible possible ce tour, et gagne +3 PV | l'entrée royale de Kassandre, statue de Lifeline comprise |
| **Lifeline** | passif | 3 | **Régénération** : +2 PV à un héros allié au début de chacun de tes tours | la médic d'Apex — la statue que Kassandre exige, et le perso que Raiky refuse de lâcher |
| **Mets-le dans du riz** | tactique | 2 | rend **6 PV** à un héros allié — mais **au début de ton prochain tour**, pas maintenant | *« mets ton casque dans du riz »* · *« t'as essayé de mettre ton arc star dans du riz avant de la jeter ? »* |

> `Mets-le dans du riz` : 6 PV valent 6 points, **× 0,8** parce que le soin est différé d'un tour
> (l'adversaire a un tour pour achever la cible) → 5 → `⌈5/3⌉ = 2` d'énergie. Le délai n'est pas
> un équilibrage, c'est le gag : le riz met la nuit à faire effet.

### Attaque et dégâts

| Carte | Type | Coût | Effet | Origine |
|---|---|---|---|---|
| **La manette** | passif | 2 | si le Tirage du tour ≥ 4, tes héros frappent **deux fois** ce tour | l'objet, plus personne derrière |
| **Le clavier-souris** | passif | 2 | si le Tirage ≥ 3, tes héros ignorent les dégâts de zone | l'objet, plus personne derrière |
| **La Flatline d'Azraël** | passif | 2 | **+4 d'Attaque** à un héros allié, pour toute la partie | *« c'est LE flatline »* · *« tu croises plus de hemlock que de flatline, ce jeu est si cruel »* |
| **Le tunnel de Rina** | tactique | 2 | **−2 d'Attaque à toutes les AUTRES cartes de sa table**, alliées comprises | *« tout ça pour esquiver son tunel »* · *« tunel numero 2......... »* · le GIF Tenor dédié |
| **Codage à la Requin** | tactique | 2 | Tirage ≥ 5 : 8 dégâts à un héros adverse · Tirage ≤ 2 : 3 dégâts à un des tiens · sinon 4 | ça compile ou ça casse |
| **Séance de révision avec Meliodas** | tactique | 1 | −3 d'Attaque à un héros adverse **et −1 au tien le plus fort** ce tour | on s'endort à deux |
| **Aim assist = aimbot** | tactique | 2 | copie l'Attaque de ton héros le plus fort sur un autre des tiens ce tour, **dans la limite de +5** | le meme *The Office* « they're the same picture », signé Taki — 7 pers. |
| **Azraël met ta perk !** | tactique | 2 | pose l'état **Oublie** sur un héros adverse | le meme de la mouette qui inspire et hurle *« azrael met ta perk !!!! »* |
| **POV le chevreuil** | tactique | 2 | pose **Stun** sur un héros adverse — figé dans les phares | le meme du chevreuil *« quand il a vu la voiture »* |
| **Mozambique here!** | tactique | 2 | un héros allié n'inflige plus que **1 dégât** ce tour, mais il frappe **TOUS** les héros adverses | le meme *« redis-le encore une fois »* — la pire arme d'Apex, devenue culte |
| **Raciste** | tactique | 2 | **−3 d'Attaque à tous les héros adverses qui partagent la même faction**, ce tour | le mot ne veut PAS dire ça ici : dans la commu, être raciste c'est jouer toujours les mêmes persos ou la même arme — ~10 pers. |

> 🚨 **`Le tunnel de Rina` est la carte « Blabla Rina »**, proposée le 2026-09-05 dans la fiche
> Notion et jamais écrite ici. Même gag, même effet, même prix : **une seule carte**, sous le nom
> que l'owner lui a donné le 2026-09-10. Deux entrées auraient fait deux cartes du même gag —
> exactement le doublon que le tri venait de retirer côté personnes.
> Prix 5 au barème (C07 *Ponction* vaut 4 pour −1 à la table adverse ; doubler le malus vaut plus,
> mais il est **subi aussi par son camp**, × 0,5 sur cette moitié) → `⌈5/3⌉ = 2` d'énergie.
> 🎁 Le son existe déjà : `data/sons/commande/rina.mp3`, migré de PhantomBot.
> ⚠️ À vérifier en calibration : sur une table où elle est seule alliée, l'effet est purement
> offensif et vaut plus que 5. La borne serait d'exiger au moins une alliée sur sa table.

> `La Flatline d'Azraël` : +4 d'Attaque permanent = 4 points → `⌈4/3⌉ = 2` d'énergie. C'est une
> arme, elle se garde — d'où le passif plutôt que la tactique.

### Énergie et tempo

| Carte | Type | Coût | Effet | Origine |
|---|---|---|---|---|
| **Les PP du samedi** | tactique | 2 | **+4 d'énergie**, mais l'adversaire en gagne **2** | le rituel du samedi — **42 pers.**, 149 occ. |
| **Requin qui tente d'expliquer** | tactique | 2 | les tactiques de l'adversaire coûtent **+1 d'énergie** ce tour | le meme des formules confuses — 17 pers. |
| **Raiky dans l'anneau** | tactique | 2 | un héros de ta **réserve** entre en ligne immédiatement, mais perd **2 PV** | le meme *Let me in* — hors zone, il veut rentrer |
| **De l'air** | tactique | 2 | l'adversaire gagne 2 d'énergie de moins au tour suivant | *« tu manges quoi à midi ? — de l'air 😅 »* |
| **Michel-Velux** | tactique | 1 | +4 d'énergie immédiatement, mais l'adversaire choisit ton Tirage au prochain tour | le running gag du TTS |

### Aura et coopération

| Carte | Type | Coût | Effet | Origine |
|---|---|---|---|---|
| **Apéro chez Zeddo** | passif | 2 | +2 d'Aura à tous tes héros en ligne | l'apéro |
| **10 pizzas géantes** | tactique | 3 | rend 4 PV à **tous** tes héros. En coop, à ceux de tous les joueurs | la commande à 240 € |
| **Sur le chemin** | passif | 3 | l'Aura de tes héros s'applique aussi aux héros des **autres joueurs** | le rituel de chanson du salon |
| **Un piercing de petitpoissonnn** | tactique | 1 | +3 d'Aura à un héros allié pour la partie, **et il perd 1 PV** | *« j'ai craqué j'ai un nouveau piercing azra »* · *« comme ça j'ai un nombre pair de piercing »* |

> `Un piercing` : +3 d'Aura permanent = 3 points, moins un malus subi de 1 PV (× 0,5 → −0,5) →
> 3 arrondi → `⌈3/3⌉ = 1` d'énergie. On souffre un peu pour être beau : c'est le gag, et c'est
> aussi la seule carte d'Aura qui se paie en PV plutôt qu'en énergie.

### Les rares — elles touchent aux mécaniques signature

| Carte | Type | Coût | Effet | Origine |
|---|---|---|---|---|
| **La Chute** | tactique | 5 | prends le contrôle d'un héros adverse jusqu'à la fin du tour suivant | l'auto-équilibrage emprunté au Mindbug, devenu une carte |
| **Un montage de Malef** | tactique | 4 | échange un héros de ta ligne avec un de ta réserve, en gardant ses PV actuels | le montage |
| **Le pendu** | tactique | 3 | nomme une carte ; si l'adversaire l'a en main, il la défausse. Sinon tu prends 2 dégâts | le jeu du pendu |
| **Quoi → FEUR** | tactique | 2 | **annule la prochaine tactique jouée par l'adversaire** ce tour | le meme du bouton rouge : *« quand quelqu'un dit quoi et qu'il y a Requin »* |

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

| Famille | Après le tri | Aujourd'hui |
|---|---|---|
| Soin et protection | 2 | **5** |
| Attaque et dégâts | 6 | **11** |
| Énergie et tempo | **2** | **5** |
| Aura et coopération | 4 | 4 |
| Rares | 3 | **4** |

🚨 **Le déséquilibre s'est inversé, et c'est maintenant Attaque qui déborde** : 11 cartes sur 29,
soit 38 % du paquet. Les deux passes du 2026-09-10 y ont versé 5 cartes de plus, parce que les
memes de la commu parlent surtout d'Apex et qu'un meme d'Apex se traduit presque toujours en
dégâts. C'est un biais de la SOURCE, pas un choix : à corriger en cherchant les prochaines refs
ailleurs que dans les memes de jeu — Aura et coopération n'a rien reçu depuis le début.

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
en prime au point dur du consentement (§6) : une emote n'est pas une personne.

### 🚨 « Raciste » — le mot ne veut pas dire ça ici

Dans cette commu, **être raciste, c'est jouer toujours les mêmes personnages ou la même arme**.
*« Je me disais bien que tu jouais des perso raciste »* · *« en ranked je joue Spitfire/Prowler,
j'suis un bon raciste aussi »* · *« une raciste dans son gameplay »* · *« Compétitive vs casual
racisme »*. Une dizaine de personnes distinctes l'emploient dans ce sens, et jamais dans l'autre.

La ref se traduit toute seule : **tu rejoues la même chose, tu le paies** — d'où le malus qui
frappe les héros adverses d'une même faction. Nom arrêté par l'owner le 2026-09-10.

### Trois cartes à surveiller en priorité

- **La Chute** (5) — la plus chère du jeu et elle doit le rester. Elle est ce qui autorise des
  héros vraiment forts sans casser le jeu : plus un héros est fort, plus le poser devient risqué.
- **Michel-Velux** — donner 4 d'énergie pour 1 est énorme ; le contre (l'adversaire choisit ton
  Tirage) n'a de valeur que si les cartes à Tirage sont jouées. Il en reste trois.
- **Quoi → FEUR** — annuler une tactique pour 2 d'énergie est la meilleure affaire de la liste
  quand l'adversaire joue cher, et une carte morte quand il ne joue rien. C'est la première à
  faire tourner en calibration : une annulation bon marché aplatit tout un paquet d'un coup.

## 6. Ce qui manque encore

- **Les tactiques de Wally** : en coop, il a son propre paquet (§5 des règles). Elles ne sont pas
  écrites — et elles doivent être conçues **contre** un groupe, pas contre un joueur.
- **Combler les deux familles vidées** par le tri (cf. §5), sur des refs vérifiées.
- **Les illustrations** : 17 cartes à générer. Coût à chiffrer avant d'ouvrir le robinet.
- **Le consentement** : huit cartes nomment encore des personnes réelles — **Kassandre**
  (mode diva), **Azraël** (Flatline), **Rina** (tunnel), **Meliodas** (révision), **Zeddo**
  (apéro), **Malef** (montage), **petitpoissonnn** (piercing), **KingsRequin** (codage). Chacune
  doit pouvoir être retirée à la demande de la personne — point dur nommé depuis le premier jour,
  toujours pas résolu.
  🎁 Le tri l'a allégé au passage : *MrMakkx*, *Temcox*, *oyoloyoo* et *Taki* ne sont plus nommés.
