# L'overlay de stream de Wally

Document vivant : à mettre à jour **en même temps** que le code, sinon il se
transforme en promesse invérifiable. La source de vérité reste
`OverlayNarrator._WIDGETS` — ce fichier l'explique, il ne la remplace pas.

---

## Installation dans OBS

| Réglage | Valeur |
|---|---|
| Source | Navigateur (`Browser Source`) |
| URL | `https://heywally.fr/overlay` |
| Largeur × hauteur | **560 × 460** |
| Fond | transparent |

Wally se place en **bas à droite** ; ses bulles s'ouvrent vers la gauche.
`?side=left` inverse l'ancrage si la source est posée à gauche de l'écran.

La taille n'est pas arbitraire : 534 px sont nécessaires pour une bulle au
maximum de sa longueur, et 432 px pour un sondage à quatre options. Plus petit,
le contenu est rogné ; plus grand, ce sont des pixels transparents en trop.

**Pas besoin de rafraîchir la source** : l'overlay compare une empreinte du
contenu servi toutes les 30 s et se recharge de lui-même quand elle change.

---

## Le principe

Wally **décide** d'afficher, il n'exécute pas une commande. C'est ce qui lui
permet de refuser quand on lui en demande trop, de commenter ce qu'il montre,
de tricher sur un tirage — ou de proposer quelque chose de lui-même.

Deux règles structurent tout le reste :

1. **L'overlay s'adresse aux SPECTATEURS.** Le streamer ne voit pas son propre
   overlay pendant qu'il joue ; y écrire « regarde ça » n'aurait aucun sens.
2. **Rien hors live.** Personne ne regarde, et chaque bulle coûte un appel LLM.
   Sollicité hors stream, Wally le dit plutôt que de faire semblant.

Un **budget de parole** limite la fréquence : c'est un mécanisme qui refuse, pas
une consigne dans un prompt. Un compagnon qui commente sans arrêt devient
insupportable, et un overlay ne se scrolle pas.

Il y en a **deux, distincts** : celui des *bulles* (`_may_speak`) et celui des
*widgets et événements* (`_may_react`). Un raid ne doit pas être avalé parce
qu'une pensée vient de passer. Corollaire à retenir avant d'ajouter un
producteur : une bulle se rationne sur le premier, un affichage sur le second —
tester le mauvais des deux fait taire la fonctionnalité en silence. Le
commentaire de palier d'un compteur en est l'exemple : il suit son propre
widget, qui vient de consommer le budget des événements, et ne passait donc
jamais.

---

## Ce qu'il fait sans qu'on demande

- **Il pense à voix haute** — nuage de BD, quand il ne se passe rien.
- **Il réagit aux événements du live** : raid, sub, changement de jeu ou de
  titre. L'avatar s'emballe une seconde sur les gros moments. Ces réactions ne
  dépendent PAS de `twitch_events.*.active` : ce réglage ne gouverne que les
  messages de remerciement automatiques dans le chat. Les avoir liés rendait
  Wally aveugle aux raids tant que ces messages étaient coupés (2026-08-07).
- **Il dit bonjour** aux inconnus et à ceux qui reviennent après ≥ 7 jours, à
  leur première prise de parole dans le chat. Une fois par personne et par live.
- **Il écoute le vocal** : présent dans le salon d'Azraël, il entend sans jamais
  parler à l'oral — il couvrirait le streamer et serait réinjecté dans son micro.

Le compteur de spectateurs, lui, est perçu mais ne déclenche rien : il fluctue
tout seul et ne dit rien de neuf au public.

- **Il suit la partie d'Azraël** — pendant le live, son compte Apex est consulté
  toutes les 90 s : Wally sait qu'il est en partie, sur quelle légende, à quel
  rang, et ce qu'il a gagné depuis le début du stream. Perception **passive**,
  comme le flux du stream : elle ne le fait jamais parler de lui-même.

---

## Ce qu'on peut lui demander

Dans le chat Twitch, sur Discord, ou **à voix haute en vocal** — en le nommant.

### Le hasard, commenté

> « wally fais un pile ou face »
> « wally lance un dé » · « wally lance deux dés » *(jusqu'à 4)*
> « wally fais tourner la roue entre pizza, burger et tacos » *(2 à 8 options)*

Le tirage est décidé côté serveur, jamais par le navigateur : c'est ce qui
permet à Wally d'annoncer le résultat — et de le forcer s'il veut tricher.

### Participation du chat

> « wally fais un sondage de 30 secondes pour savoir si les gens aiment le chocolat »

Le chat vote en tapant le numéro. Le dépouillement monte en direct, le gagnant
s'affiche à la fin. 10 s par défaut, 120 s au plus, 2 à 4 options. Un vote par
personne, changement d'avis permis ; « j'ai 2 chats » ne compte pas.

> « wally épingle le message de Kassandre »

### L'objectif du live

> « wally lance un objectif de 10 subs »

La jauge se remplit **toute seule** au fil des vrais follows, abonnements ou
bits reçus — rien à mettre à jour. Elle se ferme quand l'objectif est atteint.
À ne pas confondre avec `gauge`, qui attend un pourcentage donné à la main.

### Les plus bavards

> « wally qui parle le plus ? »

Le top 3 du chat depuis le début du live. Purement mécanique — rien n'est
interprété, donc rien ne peut être inventé. Sur demande seulement : un
classement permanent inciterait au spam.

### Utilitaires

> « wally affiche depuis combien de temps je stream »
> « wally lance un compte à rebours de 60 secondes »
> « wally affiche BRB 5 min »
> « wally affiche une jauge à 70 % pour l'objectif subs »

### Données réelles (Apex)

> « wally affiche mon rang » · « wally montre la rotation des cartes »
> « wally affiche les stats d'Azra » · « wally le craft du jour »

Sept panneaux : **rang** (avec l'écusson officiel), **état en jeu** (en partie ou
non, légende et skin), **stats** de carrière, **rotation** des cartes avec un
décompte qui tourne vraiment, **replicator**, **seuil Predator**, **serveurs**.

Wally **ne recopie plus aucun chiffre** : il nomme un panneau, le serveur va
chercher la donnée et la rend. C'est la différence avec `stats` et `versus`, où
il transcrivait à la main des valeurs qu'il venait de lire — et pouvait se
tromper.

Il retient aussi le **compte Apex** de ceux qui le déclarent (« mon pseudo Apex
c'est X ») : il va chercher l'**uid** au passage, et ensuite « wally j'ai combien
de kills ? » suffit. L'uid est ce qui est interrogé ensuite — un pseudo se
change, un uid non. Personne ne peut déclarer le
compte d'un autre — l'identité vient du chat, pas du modèle.

⚠️ Le **classement mondial** (top 500, par légende, par pays) et l'**historique
des matchs** ne nous sont pas accessibles : l'API les réserve à des clés
autorisées. Wally a pour consigne de le dire au lieu d'aller scraper un site.

### Le bingo du stream

> « wally lance le bingo du stream »

Il compose une grille de pronostics (jusqu'à 9) à partir de ce qu'il sait
vraiment d'Azraël et des habitués, puis **coche les cases quand il les
constate** — en vocal ou dans le chat. Il ne coche que ce qu'il a vu ou entendu.

> « wally coche la case du ping »
> « wally remontre le bingo »

Une case se coche par quelques mots de son intitulé : le modèle ne voit pas la
grille, lui demander un numéro de mémoire garantissait la mauvaise case. La
grille ne reste pas à l'écran — on peut la redemander à tout moment.

### Le pendu

**C'est Wally qui choisit le mot**, seul, dans le même appel — il ne demande
jamais qu'on lui en propose un, ce serait l'inverse du jeu. **L'indice reste
caché** jusqu'à ce qu'il ne reste que 2 essais : c'est un secours, pas une
ouverture. Le mot fait 3 à 16 lettres et n'apparaît jamais avant la fin.


> « wally lance un pendu »

Wally choisit un mot (3 à 16 lettres), de préférence tiré de l'univers de la
chaîne. Le chat propose des lettres — **une lettre seule par message**, sinon
chaque phrase du chat en proposerait. Les accents sont ignorés : « fusée » se
devine avec un `e`.

**On peut l'interpeller** : « @Wally d » propose la lettre `d` aussi bien que
« d » tout seul. L'interpellation est retirée avant lecture — sans quoi le
compteur voyait quinze caractères là où il attend une lettre, et deux parties
entières n'ont enregistré aucune proposition (2026-08-07). Même chose pour les
votes de sondage et les coups du chifoumi.

Six fautes et c'est perdu : le pendu se dessine trait par trait, chaque membre
se traçant à l'apparition. Le mot n'est révélé qu'à la fin, gagné ou perdu — il
ne transite jamais vers l'overlay avant, sinon les viewers le liraient à
l'écran.

**La grille reste à l'écran tant qu'on joue** — dix secondes, c'est la durée
d'un résultat qu'on lit, pas d'une partie. Elle survit aussi à une reconnexion
d'OBS. Gagné ou perdu, elle redevient un résultat et s'efface.

> « wally remontre le pendu »

Redemander la grille la **remontre**, sans jamais relancer de partie : le faire
effaçait les lettres déjà trouvées. Un mot fourni, en revanche, ouvre bien une
nouvelle partie. Pour arrêter : « wally annule le pendu ».

### Le chifoumi

> « wally lance un chifoumi »

Le chat vote en tapant `1`, `2` ou `3` pendant 15 s ; Wally joue contre le coup
majoritaire. Les deux mains secouent trois fois avant de se figer — sans ce
battement, le résultat tombe sans suspense. Il peut forcer son coup s'il veut
tricher.

---

## Les citations du live

> « wally retiens ça »
> « wally ressors une citation »

Wally retient une réplique entendue **en vocal** et l'affiche ; plus tard — même
un autre jour — il peut la ressortir. C'est le décalage qui fait rire : une
phrase reprise dix minutes après fait sourire, la même trois jours plus tard
fait rire.

Les citations sont en base, avec la date. Celles qu'on vient de montrer sont
écartées du tirage suivant, mais tout redevient candidat au fil du temps. La
citation est plafonnée à 160 caractères : au-delà, ce n'est plus une punchline.

⚠️ Il ne peut citer que ce qu'il a **entendu** — la qualité dépend donc de la
transcription vocale.

---

## Les compteurs — d'un stream à l'autre

> « wally compte combien de fois je dis que j'ai pas rechargé »
> « wally compte mes morts »
> « wally tu comptes quoi ? » → la liste avec les totaux
> « wally arrête de compter les morts »

Wally traduit la demande en formulations réellement prononcées, puis repère les
occurrences **tout seul**, dans le vocal comme dans le chat. Le comptage est
mécanique : c'est ce qui permet de passer sur chaque phrase sans coût.

Les totaux sont en base : ils survivent aux redémarrages et courent d'un live à
l'autre. **Relancer un compteur reprend son total**, il ne repart pas de zéro —
un gag peut durer des semaines.

L'affichage à l'écran est rationné par le budget ; le comptage, lui, ne rate
rien.

---

## Les paris

> « wally, tu paries quoi sur cette partie ? »

Il annonce un pronostic, puis le **tranche lui-même** quand il connaît l'issue —
aucune source ne la lui donne, il la constate en écoutant. Son score cumulé
s'affiche : « 2 / 4 » se défend d'un live à l'autre, et il assume ses ratés
(pronostic barré, bordure rouge).

Trois gardes contre le point facile : on ne tranche pas sans avoir parié, ouvrir
un pari abandonne le précédent, et un pari oublié depuis plus d'une heure expire
au lieu d'être tranché au hasard.

---

## Réglages (panneau admin → Système → Overlay)

- **Afficher / masquer** l'overlay.
- **Mode test (hors live)** — fait croire à Wally qu'un live tourne, pour régler
  l'affichage sans attendre un stream. Borné dans le temps (30 min par défaut,
  120 max) : oublié actif, il ferait parler Wally dans le vide. Il **survit à un
  redémarrage** depuis le 2026-08-08 : il vivait sur une horloge qui repart de
  zéro à chaque process, et disparaissait donc à chaque déploiement — au moment
  précis où l'on s'en sert, puisqu'on règle l'overlay entre deux builds.
- **Ancré à droite / à gauche** — met à jour l'URL à recopier dans OBS.

---

## File d'attente

Deux demandes rapprochées ne s'écrasent plus : la seconde attend que la première
ait fini. Cinq en attente au plus, et une demande de plus d'une minute est
abandonnée — un dé lancé il y a une minute n'intéresse plus personne.

Les **mises à jour** ne passent pas par la file : un vote de sondage, une case
de bingo ou le verdict d'un pari s'appliquent tout de suite sur le widget
affiché. Les empiler les ferait arriver après coup, sur un widget disparu.

---

## Alerte clip

Quand un viewer crée un clip, Wally l'affiche avec **son auteur** — c'est celui
qui clippe qu'on récompense. Twitch n'émettant aucun événement à la création
d'un clip, l'API est interrogée toutes les deux minutes pendant le live : un
clip signalé deux minutes après reste un moment frais.

---

## Voter à la voix

Pendant un sondage, ceux qui sont **en vocal** peuvent répondre à haute voix
plutôt que d'aller taper dans le chat : « deux », « oui », ou le nom de l'option.
Plus permissif que le chat, car une phrase parlée n'est jamais réduite à un
chiffre — mais limité aux phrases courtes, sinon « deux » parlerait d'autre
chose.

---

## Garde anti-répétition

Plusieurs sources produisent des réactions voisines — un salut, une vague de
follows, une arrivée dans le chat se ressemblent toutes. Sans garde, Wally
répétait « du monde arrive, faut bien se tenir » toute la soirée.

Une réplique qui partage l'essentiel de ses mots porteurs avec l'une des huit
dernières est écartée, quelle qu'en soit la tournure. La mémoire se vide à
chaque nouveau live.

Toutes les bulles sont tracées en INFO (`Overlay [speech] : …`) : sans ça, ce
que l'overlay a dit pendant un live était introuvable après coup.

---

## Limites connues

- **Le bingo et les compteurs** dépendent de la qualité de la transcription
  vocale. Tant que le serveur STT GPU (`192.168.1.49`) est hors ligne, le repli
  CPU transcrit avec ~2 s de latence et des approximations.
- **Un widget occupe tout l'espace** : l'avatar et la bulle s'effacent pendant
  son affichage, et il n'ouvre donc pas de bulle de commentaire.
- **Les bulles durent 10 s** et font au plus 90 caractères ; au-delà, la
  condensation est refusée plutôt que tronquée.

---

## Les memes de la communauté

> « wally affiche un meme »
> « wally sors le meme du ping »

Les images vivent dans **`data/memes/`** — dépose-les, aucun redémarrage n'est
nécessaire, le dossier est relu à chaque tirage. Formats : png, jpg, gif, webp.

**La description** vient du nom du fichier (`azrael-blame-le-ping.jpg` →
« azrael blame le ping »), ou d'un fichier texte voisin si le nom ne suffit pas.
Elle sert à deux choses : Wally ne voit pas les images, donc c'est sa seule prise
pour commenter juste — et pour choisir un meme **à propos** plutôt qu'au hasard.

Le fichier texte se nomme **`azrael-blame-le-ping.jpg.txt`** — extension de
l'image comprise. `azrael-blame-le-ping.txt` marche toujours, mais ne distingue
pas `truc.gif` de `truc.jpg`, qui se partageaient alors la même description.
Une description est **tronquée à 160 caractères** : viser une phrase dense.

Le choix « à propos » retient les memes dont la description contient le **plus**
de mots du sujet demandé. Un seul mot en commun ne suffit pas : « qui », « pas »
et « une » figurent dans presque toutes les descriptions, et suffisaient
autrefois à faire retomber la sélection sur un tirage au hasard.

Le même meme n'est jamais tiré deux fois de suite. Les fichiers de plus de 8 Mo
sont ignorés (trop lents à afficher). Voir `data/memes/LISEZ-MOI.md`.

---

## Les clips

> « wally mets le dernier clip » · « wally mets le dernier clip d'azra »
> « wally mets le clip le plus vu » · « wally mets le clip du 1v3 »
> « wally montre le top 5 des clips »

Quatre façons de choisir : le **dernier**, le **plus vu** du mois, celui dont le
**titre** correspond à ce qu'on décrit, ou le **podium** des cinq plus vus. Le
podium n'affiche aucune vidéo — c'est un tableau qu'on lit, et enchaîner cinq
clips monopoliserait l'écran plusieurs minutes.

La recherche par titre se fait chez nous : Helix ne sait filtrer ni sur le titre
ni sur le clippeur. À pertinence égale, le plus vu gagne — c'est celui que les
gens ont en tête. Rien de convaincant : Wally le dit plutôt que de montrer un
clip au hasard.

Le clip est **rejoué sur l'overlay**, en **muet**, et reste affiché le temps de
la vidéo. Il part aussi tout seul dès qu'un viewer crée un clip pendant le live
(veille toutes les 2 min).

En nommant quelqu'un, on obtient **son** dernier clip. Un surnom suffit
(« azra » → « Azrael ») : la reconnaissance passe par `matches_name()`, la même
mécanique que l'appariement de comptes. Helix ne sait pas filtrer sur le
clippeur, le tri se fait chez nous — dans la fenêtre des **24 dernières heures**,
comme pour le dernier clip tout court. ⚠️ La fenêtre reste **cette chaîne** : « le
dernier clip d'Azra » veut dire ce qu'Azra a clippé ici, pas ce qui a été clippé
sur sa chaîne à lui. Sans clip de cette personne, Wally le dit en la nommant —
il ne rabat pas sur le clip d'un autre.

Trois niveaux, du meilleur au moins bon :

| Mode | Ce qui se passe |
|---|---|
| **Fichier vidéo** | `<video muted autoplay>` — démarre tout seul. Le mode normal. |
| **Player Twitch** | S'affiche mais **attend un clic**. Filet de secours. |
| **Carte texte** | « ✂ nouveau clip » + titre + auteur, quand rien d'autre n'est possible. |

⚠️ Le player officiel en iframe **refuse de démarrer seul** dans un overlay :
« Autoplay disabled … style visibility ». C'est un faux positif de Twitch, connu
et non corrigé ([twitchdev/issues#1127](https://github.com/twitchdev/issues/issues/1127)).
D'où l'URL du fichier vidéo, obtenue via l'API **GraphQL non officielle** de
Twitch — celle qu'emploient yt-dlp et streamlink. Twitch peut la changer sans
préavis : c'est exactement ce que les deux replis couvrent.

Wally ne VOIT pas le clip. Il n'a que son titre et son auteur, et a pour
consigne de ne pas raconter ce qu'il contient.

---

## Annuler ce qui est à l'écran

> « wally annule le bingo » · « wally enlève le meme » · « wally vire tout ça »

Wally appelle `cancel_overlay`. Cibles :

| Cible | Effet |
|---|---|
| `ecran` | Retire ce qui est affiché à l'instant — meme, message épinglé, compteur, bulle. Les parties en cours continuent. |
| `bingo` `pendu` `sondage` `chifoumi` `objectif` | La partie est **abandonnée**, et l'écran nettoyé. |
| `tout` | L'écran et toutes les parties. |

Un abandon **ne dépouille pas** : un sondage annulé n'a pas de gagnant, un
chifoumi annulé pas de verdict. Wally a pour consigne de ne pas en annoncer.

Quand il n'y avait rien à annuler, l'outil le dit et Wally le répète au lieu de
prétendre avoir retiré quelque chose — même exigence d'honnêteté que
`show_overlay`. Et il garde le droit de refuser.

Marche partout où Wally répond : chat Twitch, Discord, et **vocal**.

**Ce qui tourne lui est visible.** Pendant un live, un bloc « Sur ton overlay »
lui indique le bingo en cours, l'objectif, le pendu. Il peut donc annuler
nommément, et voir qu'une partie traîne. C'est une perception **passive** : elle
ne le fait jamais parler de lui-même. Hors live, ou sans rien en cours, le bloc
est absent.

**Le mode test s'y annonce aussi.** C'est le seul cas où le reste du prompt
l'induit en erreur : `stream_live` dit « pas de live », ce qui est vrai, et Wally
en concluait que ses outils d'overlay ne marchaient pas — le 2026-08-08 il a
refusé d'afficher un clip **sans appeler l'outil**, mode test pourtant actif. Le
bloc précise donc que l'overlay répond alors qu'aucun stream ne tourne, et que
seul son créateur le voit. Les descriptions d'outils, elles, ne préjugent plus du
live : c'est l'outil qui rend le verdict, pas le modèle.

---

## Réactions automatiques

- **Vagues d'emotes** — quand quatre personnes différentes spamment le même
  emote en douze secondes, il le relève à l'écran. Le signal est le nombre de
  PERSONNES, pas de messages : dix « KEKW » d'un seul viewer, c'est un habitué
  qui s'amuse. Signalé une fois, puis silence 90 s sur cet emote.
- **Paliers de compteur** — aux 10ᵉ, 25ᵉ, 50ᵉ, 100ᵉ (puis tous les 100), Wally
  commente au lieu d'afficher un chiffre muet.
- **Rappel du bingo** — la grille repasse toutes les dix minutes tant qu'une
  partie court : sinon les viewers arrivés entre deux cases l'ignorent.

---

## Validé, pas encore fait

*(rien pour l'instant — tout ce qui a été validé est livré)*

---

## Écarté volontairement

- **Note d'une partie sur 10**, **classement**, **tirage au sort parmi les
  viewers**, **hype-meter** — arbitrage owner du 2026-08-06.
- **« Il y a un mois, tu disais que… »** — s'adressait au streamer, ce que la
  règle n°1 interdit. Refusé une seconde fois le 2026-08-07 sous sa forme
  « rappel de promesse adressé au chat » : pas de promesses, point.
- **Jauge d'humeur** — l'avatar la porte déjà.
- **Résumé de fin de live** (2026-08-07).
- Refusés le 2026-08-07 (ne pas reproposer) : quiz de la communauté, compteur
  inversé (« ça fait X min que… »), mot interdit, panneau de raid, le juste
  prix, « le premier qui tape 🔥 », trombinoscope des habitués, bandeau
  défilant, météo du stream, classement du bingo, sous-titres du vocal.
- **Aperçu de l'overlay dans le panneau admin** (2026-08-07) — ouvrir l'URL de
  l'overlay suffit.
