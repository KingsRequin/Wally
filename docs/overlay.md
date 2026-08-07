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
  titre. L'avatar s'emballe une seconde sur les gros moments.
- **Il dit bonjour** aux inconnus et à ceux qui reviennent après ≥ 7 jours, à
  leur première prise de parole dans le chat. Une fois par personne et par live.
- **Il écoute le vocal** : présent dans le salon d'Azraël, il entend sans jamais
  parler à l'oral — il couvrirait le streamer et serait réinjecté dans son micro.

Le compteur de spectateurs, lui, est perçu mais ne déclenche rien : il fluctue
tout seul et ne dit rien de neuf au public.

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

> « wally affiche mes stats Apex »
> « wally compare mes kills avec ceux de KingsRequin »

Les chiffres viennent de l'API : Wally les lit puis les recopie. Il n'invente
pas une statistique.

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

> « wally lance un pendu »

Wally choisit un mot (3 à 16 lettres), de préférence tiré de l'univers de la
chaîne. Le chat propose des lettres — **une lettre seule par message**, sinon
chaque phrase du chat en proposerait. Les accents sont ignorés : « fusée » se
devine avec un `e`.

Six fautes et c'est perdu : le pendu se dessine trait par trait, chaque membre
se traçant à l'apparition. Le mot n'est révélé qu'à la fin, gagné ou perdu — il
ne transite jamais vers l'overlay avant, sinon les viewers le liraient à
l'écran.

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
  120 max) : oublié actif, il ferait parler Wally dans le vide.
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
« azrael blame le ping »), ou d'un fichier `.txt` du même nom si le nom ne suffit
pas. Elle sert à deux choses : Wally ne voit pas les images, donc c'est sa seule
prise pour commenter juste — et pour choisir un meme **à propos** plutôt qu'au
hasard.

Le même meme n'est jamais tiré deux fois de suite. Les fichiers de plus de 8 Mo
sont ignorés (trop lents à afficher). Voir `data/memes/LISEZ-MOI.md`.

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
