# TCG du Purgatoire — conception des règles

**Date** : 2026-08-29
**Statut** : conception validée section par section avec l'owner. Aucune ligne de code écrite.
**Portée** : les RÈGLES et l'économie. Le rendu visuel des cartes fait l'objet d'un chantier
distinct (fiche Notion « Les images fabriquées par Wally se dessinent en HTML/CSS »).

Fiches Notion sources : « TCG de la commu — Wally dessine une carte par personne » (statut
`à faire`, sévérité haute) et « Discord Activity, comme table de jeu du TCG ».

---

## 0. Ce qui est arbitré

| Question | Décision |
|---|---|
| Qui joue | **Viewer contre viewer**, Wally arbitre et commente |
| Ce qu'on amène | **Son héros** (sa propre carte) + un deck de **11 cartes** — membres, objets ou moments de la commu |
| Durée | **~5 min**, 5 manches |
| Où | **Une app web unique**, servie en Activity Discord et sur la page `/tcg` du site |
| Le stream | N'est **pas** une surface de jeu, **à aucun moment** : boutique (lootbox), vitrine (animations, annonce des duels). Une partie ne s'y joue pas, ne s'y regarde pas, et rien de la partie n'y est décidé — arbitré le 2026-09-04 |
| Qui commente | Wally, **en vocal dans l'Activity Discord** (il y est déjà, avec son TTS) et en texte sur le site |
| Les chiffres | **Calculés**, jamais écrits par le LLM. Budget constant par palier |
| La rareté | **Six paliers adossés aux grades** Discord/Twitch |
| La variabilité | Une **roulette** au lancement — pas l'humeur de Wally |
| Le hasard en jeu | **Tiré et AFFICHÉ avant la pose**, jamais résolu en secret (2026-09-04) |

**Le principe qui tient tout** : la mémoire de Wally décide de la **répartition**, jamais du
**total**. Wally écrit le nom, l'illustration et le texte d'ambiance. Il ne touche pas un chiffre.

---

## 1. Le lore existe déjà — ne rien inventer

Relevé sur les 287 membres du serveur « Le Purgatoire » le 2026-08-29 :

```
Archange  1 (Azraël)   Anges 7 (dont rhaezzia)   Prophète 1   Chérubin 2   Hérétique 1
Âmes                        276  ← rôle de base
Ames Lumineuses  117  |  Ames Sombres  85
Twitch Subscriber T1 16 · T2 0 · T3 1 (Azraël)
```

Deux conséquences :

**La hiérarchie est trop plate pour servir seule de rareté** — 276 Âmes contre 7 Anges. Les
paliers intermédiaires viennent donc des grades Twitch et d'une sélection manuelle (§5).

**Les factions sont natives.** `Ames Lumineuses` (117) contre `Ames Sombres` (85), presque
équilibrées, **choisies par les gens eux-mêmes**. Ce n'est pas une hiérarchie : c'est la couleur
du jeu. Un membre sans aucun des deux rôles est **Neutre**.

---

## 2. Anatomie d'une carte

| Champ | Origine | Écrit par |
|---|---|---|
| Nom | libre | **Wally** |
| Illustration | libre | modèle d'image |
| Texte d'ambiance | libre | **Wally** |
| Coût (1-5) | longueur de message médiane, en percentile de la commu | calcul |
| Voix / Aura / Piquant | répartition d'un budget fixe | calcul |
| Faction | rôle `Ames Lumineuses` / `Ames Sombres` / aucun | calcul |
| Affinité (1-2 sujets) | `topics` | calcul |
| Réflexe | **choisi dans un catalogue fermé** | Wally choisit, le code exécute |
| Rareté | grade Discord/Twitch (§5) | calcul |

### 2.1 Le coût sort d'un trait de style, pas de mérite

`coût = percentile(longueur médiane des messages) → 1..5`

Tu écris des pavés : carte chère et lourde, injouable avant le tour 4. Tu balances des punchlines
de six mots : carte à 1, posable dès le premier tour. **C'est vrai, c'est drôle, et personne ne
peut le lire comme une note.** Un critère de mérite (ancienneté, volume, confiance) transformerait
la carte en classement social public — c'est le piège nommé dans la fiche Notion.

### 2.2 Le budget

```
budget_base(coût)  = 4 + 3 × coût          →  C1=7  C2=10  C3=13  C4=16  C5=19
bonus_rareté       = Âme 0 · Fidèle +1 · Âme Promise +2 · Élu +3 · Ange +5 · Archange +8
budget             = budget_base + bonus_rareté − prix_du_Réflexe
```

Le reste se répartit sur les trois stats, chacune bornée à `[0, 9]`, `Voix ≥ 1`.

**Carte étalon** (celle à laquelle tout se compare, conformément à la pratique des designers
indé) : coût 3, rareté Âme, Réflexe à 3 → 10 points → typiquement **Voix 5 / Aura 3 / Piquant 2**.

Deux cartes fabriquées à trois mois d'écart tombent sur la même échelle. Aucune inflation
possible : le total est une fonction, pas une opinion.

### 2.3 La répartition, elle, vient de la mémoire

| Stat | Ce qu'elle fait en jeu | Source |
|---|---|---|
| **Voix** | force brute posée sur la table | volume et régularité de parole (`chat_messages`) |
| **Aura** | s'ajoute à la Voix des cartes **alliées adjacentes** sur la même table | densité de liens réels (`fact_relations`, mentions de tiers, co-présence vocale) |
| **Piquant** | retire autant de Voix à **une** carte adverse de la même table, au décompte final : celle de plus haute Voix, à égalité la plus chère, puis le plus petit identifiant. Plancher 0, jamais de report sur une autre carte | charge émotionnelle des échanges (`emotional_memory`, réactions déclenchées) |

Les trois mesures sont normalisées en percentile **intra-commu**, converties en poids qui somment
à 1, puis appliquées au budget (arrondi, puis correction du reste sur la stat la plus forte).

Un bavard aura beaucoup de Voix et peu du reste. Un liant aura de l'Aura. Un provocateur du
Piquant. **Personne n'a « plus » que les autres — chacun a une forme.**

### 2.4 Le Réflexe vient d'un catalogue fermé

Exactement la logique du vocabulaire fermé de prédicats de `bot/intelligence/memory/vocab.py`.
Wally **choisit** l'effet qui colle à la personne et rédige la phrase qui l'habille ; il n'invente
jamais une mécanique. Chaque entrée du catalogue porte un prix payé sur le budget.

⚠️ **Le catalogue reste plafonné à 40-60 entrées.** C'est le seul endroit du jeu où un humain
conçoit vraiment, donc le seul endroit où l'équilibre peut casser. Les ~315 cartes ne sont pas un
risque : elles sortent d'une formule. Les Réflexes, si.

---

## 3. Le déroulé d'une partie

### 3.1 Mise en place

- **Deck de 12** : le héros (sa propre carte, obligatoire) + 11 cartes collectées.
- Le **héros ne se pose pas** : il se tient au bord du plateau, présent toute la partie, et donne
  une capacité passive. Ta carte, c'est toi — tu ne te joues pas, tu assistes. Ça règle au passage
  le « je joue Azraël contre Azraël ».
- Main de départ **3 cartes**, +1 par tour.
- **La roulette** est lancée (§3.5), visible des deux.
- **3 tables**, révélées une par tour sur les trois premiers tours. Avant sa révélation, le sujet
  d'une table est caché — on peut y poser à l'aveugle, et c'est là qu'est la vraie décision.

### 3.2 Un tour (≈ 35 s)

1. Révélation de la table du tour (tours 1 à 3).
2. **Énergie = le numéro du tour** (T1 = 1 … T5 = 5). Non cumulable d'un tour à l'autre.
3. Les deux joueurs posent **en simultané et à l'aveugle**. Personne n'attend l'autre : c'est ce
   qui tient le format en cinq minutes.
4. **Révélation croisée**, et Wally commente — **à voix haute dans le vocal Discord** quand la
   partie se joue en Activity, en texte sur le site. C'est le moment de spectacle, et il a lieu
   pour les deux joueurs, pas pour un stream.
5. Fenêtre de **Chute** (§3.6), puis résolution des Réflexes.

Total d'énergie sur la partie : 15. Coût moyen 3 → environ **5 cartes posées** sur les 7 vues.

**Ordre de résolution des Réflexes — déterministe** : coût croissant, puis Voix décroissante,
puis identifiant de carte. Jamais d'arbitrage au jugé sur un ordre de résolution : c'est par là
que les jeux commentés en direct se font contester.

### 3.3 Score et victoire

```
score(table) = Σ Voix des cartes alliées
             + 2 par carte dont une affinité correspond au sujet de la table
             + Aura reçue des alliées adjacentes (Duo : ×2 entre les deux, cf. §3.4)
             − Piquant adverse appliqué
             ± effets
```

Maximum **4 cartes par table**. Une carte posée reste (sauf Renoncement, §3.7).

Fin du tour 5 : tu remportes une table si ton score y est **strictement supérieur**.
**Deux tables sur trois = victoire.** Égalité 1-1-1 → total des Voix ; encore égal → **Wally
tranche**, et là seulement c'est légitime.

### 3.4 Les trois greffes issues de la commu

Ce sont elles qui rendent le jeu incopiable : aucun autre TCG n'a de cartes qui sont des gens
vivants, présents, dont le moteur connaît les liens réels.

| Greffe | Règle | Garde-fou |
|---|---|---|
| **Réveil** | Une carte posée dont la personne a parlé (Twitch ou Discord) dans les **10 dernières minutes** est *Réveillée* : **+2 Voix** pour la partie. Wally l'annonce à voix haute. | **3 réveils maximum par joueur et par partie**, sinon la partie devient un appel à venir spammer. Évalué **au moment de la pose**, jamais rétroactivement. La fenêtre suit l'activité de la COMMU, jamais la surface de jeu : **10 min** quand un stream tourne ou qu'un salon est animé, **24 h** sinon, pour que la mécanique ne meure pas la nuit. |
| **Duo** | Deux cartes **adjacentes sur la même table** dont les personnes ont un lien réel mesuré : l'Aura que chacune donne à l'autre est **doublée**. Aucun autre cumul — un Duo ne se propage pas à une troisième carte. Wally **raconte** le lien. | Table de liens **pré-calculée par saison**. Aucune requête en pleine partie. |
| **Faction** | Deck mono-faction (héros exclu du calcul) : **+1 énergie au tour 1**. | Volontairement faible : la faction est un parfum, pas un mur. |

### 3.5 La roulette

Lancée au début, **même effet pour les deux joueurs**, figée pour la partie. Elle remplace l'idée
initiale d'une règle tirée de l'humeur de Wally : celui-ci est très rarement triste ou en colère,
la mécanique aurait été morte 90 % du temps.

Faces de départ (à calibrer) : *Sur-régime* (+1 énergie par tour) · *Chacun pour soi* (les Duos ne
fonctionnent pas) · *Heure de pointe* (le Réveil donne +4) · *Anonymat* (les cartes posées face cachée valent 4 de Voix au lieu
de 2) · *Court* (4 tours) · *Prolongations* (6 tours) · *Mains pleines* (5 cartes au
départ) · *Rappel* (au tour 3, chacun reprend une carte posée) · *Terrain neutre* (les affinités
ne rapportent rien) · *Grand oral* (les affinités rapportent +4).

La roulette est lancée **dans l'app**, sous les yeux des deux joueurs. Elle ne passe pas par
l'overlay : le stream ne touche la partie à aucun moment (§0).

### 3.6 La Chute — emprunté au Mindbug

Chaque joueur dispose de **2 Chutes par partie**. Après la révélation croisée et **avant**
résolution, tu peux prendre la carte que l'adversaire vient de poser : elle passe dans ton camp,
**sur la même table**, et compte pour toi jusqu'à la fin.

C'est le mécanisme d'auto-équilibrage de Richard Garfield : *« même une carte "je gagne" ne
ruinerait pas le jeu — si tu la joues, l'adversaire te la prend et gagne à ta place. »* Il rend
les légendaires désirables **sans qu'elles cassent le jeu** : plus une carte est forte, plus la
poser est risqué.

Thématiquement, il tombe juste : dans une commu, tu ne possèdes pas les gens. Au Purgatoire, une
âme qui change de camp, c'est une **Chute**.

- Une carte ne peut pas être Chutée deux fois.
- Une carte **Anonyme** (§3.7) ne peut pas être Chutée : on ne fait pas chuter une âme qu'on n'a
  pas reconnue. Ça ferme aussi l'abus consistant à faire tomber une Chute sur une carte à 2 Voix.
- Si les deux joueurs veulent Chuter le même tour, **celui qui mène le moins de tables décide en
  premier** ; à égalité (tour 1 notamment), celui à qui il reste le plus de Chutes ; puis l'ordre
  de priorité tiré au lancement de la partie et affiché dès le départ. Jamais d'indécision.

### 3.7 L'Anonyme et le Renoncement — empruntés à *Air, Land & Sea*

**L'Anonyme.** N'importe quelle carte peut être posée **face cachée**, pour **1 d'énergie fixe**,
**sur n'importe quelle table** : elle vaut **2 de Voix**, sans Réflexe, sans affinité, sans Aura
ni Piquant, et se révèle à la fin de la partie.

Trois problèmes réglés d'un coup : la main qui ne colle jamais aux sujets tirés, l'absence de
bluff dans un jeu à révélation simultanée, et une manche entière où Wally peut spéculer à voix
haute sur l'identité de la carte cachée — **dans le vocal Discord**, aux deux joueurs.

**Le Renoncement.** Une fois par partie, tu déclares une table perdue : tu **reprends en main**
toutes tes cartes posées dessus (l'énergie n'est pas remboursée), tu ne peux plus rien y poser, et
la table est acquise à l'adversaire. Repli tactique : une défaite locale redevient une ressource.

---

## 4. Les cartes vivent

Les personnes continuent d'exister, donc leurs cartes se recalculent — **à cadence mensuelle, par
saison, jamais en continu**. Ton deck ne bouge pas sous tes pieds en pleine partie, et la sortie
d'une saison devient un rendez-vous que Wally annonce lui-même.

⚠️ Cette cadence **ne s'adosse à rien d'autre**. Le « Wally Wrapped » mensuel, auquel j'avais
pensé l'accrocher, est en statut **`refusé`** dans Notion (vérifié le 2026-08-29).

---

## 5. Rareté et budget de prestige

| # | Palier | Source | Pool observé | Prestige |
|---|---|---|---|---|
| 1 | **Archange** | Azraël, rhaezzia | 2 | 12 |
| 2 | **Ange** | rôle `Anges` ∪ modérateurs Twitch | ~8 | 7 |
| 3 | **Élu** | VIP Twitch | à mesurer | 5 |
| 4 | **Âme Promise** | subs Twitch T1/T2/T3 | ~17 | 3 |
| 5 | **Fidèle** | sélection manuelle (fidèles, amis) | libre | 2 |
| 6 | **Âme** | tout le reste, Discord et Twitch | ~270 | 0 |

- **Cumul** : on garde toujours le palier le plus haut.
- **Budget de prestige d'un deck : 20.** Un Archange (12) plus un Ange (7) ne laisse que 1 — donc
  plus rien d'autre de rare. C'est ce qui empêche l'empilement tout en gardant les légendaires
  réellement désirables. Combiné à la Chute, une légendaire posée est un pari, pas une victoire.
- **Le héros est gratuit en prestige.** Sans ça, Azraël ne pourrait pas jouer son propre deck.
- Les noms suivent le lore du Purgatoire mais **évitent** `Prophète`, `Chérubin` et `Hérétique`,
  déjà pris par des rôles existants à 1-2 porteurs.
- Le palier **Fidèle se marque depuis le dashboard**, pas par un rôle Discord : un fidèle peut
  très bien être Twitch-only et n'avoir jamais mis les pieds sur le serveur.

⚠️ **Ni les VIP ni les modérateurs Twitch ne sont lisibles aujourd'hui.** `_STREAMER_SCOPES`
(`bot/dashboard/routes/twitch_auth.py:32`) ne porte ni `channel:read:vips` ni `moderation:read`.
Les ajouter au code **ne suffit pas** : il faut refaire l'autorisation du compte streamer depuis
le dashboard. Le fichier documente déjà trois fois ce piège — un token en service ne gagne jamais
un scope rétroactivement, et l'appel rend 401 sans un mot dans les logs.

---

## 6. Économie

**Où** : la boutique est sur le **stream**. Lootbox achetables en points de chaîne ; **5 offertes
par sub**, stockées et réclamables à tout moment. Animation d'ouverture sur l'overlay pendant le
live, dans l'app le reste du temps.

**Contenu** : 3 cartes par boîte. Taux de départ, à calibrer :

| Palier | Taux |
|---|---|
| Âme | 70 % |
| Fidèle | 15 % |
| Âme Promise | 9 % |
| Élu | 4 % |
| Ange | 1,8 % |
| Archange | 0,2 % |

**Deux pièges propres à un pool minuscule** (2 légendaires, ~315 cartes, là où un vrai TCG en a
des milliers) :

- **Garantie (pity)** : un Ange ou mieux tous les 30 paquets ; un Archange garanti au 150ᵉ paquet
  sans Archange. Sans ça, la légendaire est un mirage et l'économie se vide de son sens.
- **Le doublon** : une carte déjà possédée se convertit en **Cendres**, qui permettent de
  **fabriquer une carte précise**. C'est ce qui rend « je veux la carte de mon pote » possible
  sans dépendre du hasard. Prix indicatifs : Âme 40 · Fidèle 80 · Âme Promise 200 · Élu 400 ·
  Ange 1 200 · Archange 4 000. Un doublon rend 10 % du prix de sa carte.

---

## 7. Architecture

**Une seule app web**, servie deux fois :

| Surface | Identité | Note |
|---|---|---|
| **Activity Discord** | fournie nativement par l'iframe | Embedded App SDK, global depuis 2024, ouvert à tous |
| **Page `/tcg` du site** | OAuth Discord déjà en place (`bot/dashboard/routes/chat_auth.py`) | même bundle, même moteur |
| **Overlay** | — | boutique, animations d'ouverture, annonce des duels. **Jamais la partie
elle-même** : ni roulette, ni pose, ni score |

⚠️ **Le moteur de règles vit côté serveur, en Python.** L'app web n'est qu'un client : elle
affiche et transmet des intentions. Toute règle dupliquée en JavaScript est une porte de triche
ouverte — et un deuxième jeu à maintenir.

---

## 8. Points durs

**Le consentement.** Les cartes sont des personnes réelles. Il faut un **retrait possible** :
quelqu'un qui ne veut pas être une carte doit pouvoir le dire, et sa carte disparaît de la
circulation (y compris des collections existantes). À concevoir avant la première génération, pas
après.

**Le cloisonnement de ce que Wally invente.** Le nom et le texte d'ambiance d'une carte sortent du
même LLM que le reste. S'ils repassent par `fact_extractor` ou la consolidation nocturne, ils
deviennent des faits vrais pour toujours, et c'est invisible pendant des semaines. Même risque
exact que les rêves, le mensonge de « deux vérités » et les charges du procès — et **même
traitement : cloisonnement à l'ÉCRITURE**, comme `voice_transcript`.

**Le coût par carte.** Chaque illustration est un appel facturé. ~315 cartes générées une fois est
négligeable ; un recalcul complet chaque saison ne l'est pas. À décider : la saison recalcule les
**chiffres** (gratuit) mais **conserve l'illustration**, qui n'est régénérée que sur changement de
palier de rareté.

**La ressemblance.** Wally ne sait pas à quoi ressemblent les gens, et c'est tant mieux. La carte
représente **ce qu'il sait d'eux**, jamais leur visage.

---

## 9. Points ouverts

| Sujet | À trancher par |
|---|---|
| Prix d'une lootbox en points de chaîne | l'owner (dépend de son économie de points) |
| Le catalogue des 40-60 Réflexes | à écrire, avec leurs prix |
| Calibration des formules et des taux | mesure sur données réelles, puis parties de test |
| Capacité passive des héros | à concevoir (par palier ? par faction ?) |
| Ajout des scopes Twitch + réautorisation | l'owner, depuis le dashboard |
| Liste initiale des « Fidèles » | l'owner |

---

## 10. Sources

Jeux étudiés pour cette conception :

- [Mindbug](https://shop.nerdlab-games.com/blogs/articles/dreaming-of-simpler-times-why-magic-players-will-love-mindbug) — Richard Garfield, 2021. Le vol de créature comme auto-équilibrage.
- [Air, Land & Sea](https://ultraboardgames.com/air-land-and-sea/game-rules.php) — 18 cartes, trois théâtres, pose face cachée et retrait.
- [Marvel Snap](https://www.marvel.com/articles/games/a-starter-guide-on-how-to-play-marvel-snap) — six tours, lieux révélés progressivement, révélation simultanée.
- [KeyForge](https://nerdlab-games.com/keyforge-a-game-design-review-of-the-unique-deck-idea/) — génération procédurale et decks uniques non construits.
- [Altered](https://gamersguildaz.com/blogs/news/a-beginners-guide-to-altered-tcg) — n'importe quelle carte comme ressource.
- [Faraway](https://mr-boardgames.com/en/reviews/faraway-plan-forward-score-backwards/) — scoring inversé. **Écarté** : illisible pour un spectateur.
- [Discord Embedded App SDK](https://docs.discord.com/developers/developer-tools/embedded-app-sdk) — les Activities sont des apps web en iframe.
- [Leçons de designers indé](https://pixarts.store/blog/how-to-create-a-card-game) — démarrer à 40-60 cartes, une carte étalon, 15 parties minimum avant de figer.
