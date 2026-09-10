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

## 2. Le Tirage du tour — le hasard, et il reste visible

Au début de chaque tour, un dé 1-6 est **lancé et affiché aux deux joueurs, avant qu'ils jouent**.
Toutes les cartes à critique le lisent.

🚨 Rappel de l'arbitrage du 2026-09-04 : un hasard affiché avant l'action **n'est pas une
espérance, c'est une option** — on ne joue la carte que sur le bon tirage. Ces cartes se
tarifent donc **au meilleur cas**, jamais à la moyenne, sinon elles deviennent mécaniquement les
meilleures du jeu.

## 3. Le prix

`coût en énergie = ⌈ valeur de l'effet en points / 3 ⌉`, borné 1-5 — le taux du barème
(1 énergie ≈ 3 points de budget). Un effet qui frappe l'adversaire vaut ×1,25 : le tempo coûte
plus cher que la masse.

---

## 4. Les 17 cartes

> Compté en comptant les lignes du tableau, pas en relisant ce titre — l'écart d'une carte du
> 2026-09-04 (« 24 » annoncé pour 25 écrites) venait de là.

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

### Soin et protection

| Carte | Type | Coût | Effet | Origine |
|---|---|---|---|---|
| **Le mode diva** | tactique | 3 | un héros allié devient la seule cible possible ce tour, et gagne +3 PV | l'entrée royale de Kassandre, statue de Lifeline comprise |
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
| **Le pendu** | tactique | 3 | nomme une carte ; si l'adversaire l'a en main, il la défausse. Sinon tu prends 2 dégâts | le jeu du pendu sur l'overlay |

---

## 5. 🚨 Ce que le tri a cassé — une des deux voies de victoire a disparu

L'owner avait posé une tension : **épargner pour l'Ultime**, ou **tout miser sur les tactiques**.
La seconde voie tenait sur quatre cartes qui accélèrent le rythme et remplissent la main —
*Michel-Velux*, *Souvent en retard*, *4 h du matin*, *Le PC au micro-ondes*. **Trois sur quatre
sont sorties au tri.** Il ne reste que Michel-Velux.

Côté tenir, même effet en plus doux : *chatdodo* et *Temcox le petit cœur* sont sorties, il reste
*Le mode diva* et la nouvelle *Mets-le dans du riz*.

Ce n'est **pas** un reproche au tri : ces cartes ne renvoyaient à rien que la commu reconnaisse,
et une saison n'est pas là pour héberger des refs mortes. Mais le trou est réel et il faut le
combler avec des refs QUI EN SONT — sinon la seule stratégie viable est d'épargner, et toutes les
parties se ressemblent.

**À écrire, par famille et par ordre de manque :**

| Famille | Cartes restantes | Manque |
|---|---|---|
| Énergie et tempo | **2** | 3 à 4 — c'est le trou le plus grave |
| Soin et protection | **2** | 2 à 3 |
| Aura et coopération | 4 | ça tient |
| Attaque et dégâts | 6 | ça tient |
| Rares | 3 | ça tient |

🎁 **Le gisement à ouvrir en premier : les emotes de la chaîne.** Mesurées dans les logs —
`kassandreyunikon` 693 · `azrael74hype` 287 · `dance` 268 · `love` 148 · `queen` 105 · `fuze` 72 ·
`goodboi` 67 · `chadfuse` 67 · `koko` 61 · `cringe` 28 · `spongefuse` 27 · `gngngn` 20 ·
`triggered` 19 · `pewpew` 18 · `pepsi` 15 · `potatoaim` 12. C'est la ref la **plus** partagée de
la commu — tout le monde la lit sans explication — et **aucune** des 17 cartes ne s'en sert.
Elles échappent aussi au point dur du consentement (§6) : une emote n'est pas une personne.

⚠️ Et si les parties de test montrent que tout le monde choisit la même voie, ce sont ces deux
paquets qu'il faut rééquilibrer, **pas le plafond d'énergie** — lui ne se touche qu'en dernier,
il change tout le jeu d'un coup.

### Trois cartes à surveiller en priorité

- **La Chute** (5) — la plus chère du jeu et elle doit le rester. Elle est ce qui autorise des
  héros vraiment forts sans casser le jeu : plus un héros est fort, plus le poser devient risqué.
- **Michel-Velux** — donner 4 d'énergie pour 1 est énorme ; le contre (l'adversaire choisit ton
  Tirage) n'a de valeur que si les cartes à Tirage sont jouées. Il en reste **trois** (*manette*,
  *clavier-souris*, *Codage à la Requin*) : le contre tient encore, de justesse.
- **Sur le chemin** — n'existe qu'en coop, où elle peut porter toute une équipe. À tester à 6
  joueurs avant de la sortir.

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
