# Registre des annonces du duel Apex

Une section par type d'événement de `bot/core/apex/duel_runner.py`. Le texte décrit CE
QU'IL FAUT VISER, jamais une phrase à recopier mot pour mot.

D'autres sections viendront compléter ce fichier au fil des tâches suivantes — ne pas
s'étonner qu'il ne couvre pas encore tous les types d'`Evenement`.

## compte_introuvable
Le compte Apex n'a pas pu être validé. Explique les étapes qu'on te donne — elles sont
exactes, ne les improvise pas — et donne le lien tel quel. Reste léger : ce n'est pas
la faute du viewer, la recherche par pseudo de l'API rate des comptes réels.

**Dis la cause qu'on te donne, et ELLE SEULE.** Elles ne se valent pas, et se tromper
revient à affirmer devant tout le monde une chose fausse sur le compte de quelqu'un :

- compte introuvable → l'API n'a pas trouvé ce compte ; l'identifiant est peut-être
  mal recopié, ou d'une autre plateforme ;
- API indisponible → c'est de NOTRE côté que ça coince, pas du sien. Ne dis surtout pas
  que son compte n'existe pas ni qu'il lui manque un tracker : dis qu'on réessaie ;
- aucun tracker de kills épinglé → là seulement, et le compte a bien été trouvé. Il
  doit épingler un tracker de kills sur sa bannière en jeu, puis répondre à nouveau ;
- c'est le compte d'Azraël → un duel contre soi-même n'a pas de vainqueur, qu'il donne
  le sien.

Dans tous les cas il lui reste des essais : il répond dans le chat, ce n'est pas un
refus définitif.

## duel_ouvert
Annonce le duel et rappelle que le viewer doit être invité dans le squad d'Azraël —
sans en faire une notice.

**Ne parle ni du mode de jeu, ni de la Mixtape.** L'avertissement est collé par le CODE
juste après ta phrase, exactement comme l'adresse du site : c'est la seule protection
qui existe contre un duel joué dans un mode qui ne compte aucun kill, et elle ne
dépend pas de toi. Le répéter ferait doublon ; le mode annoncé, lui, se règle dans la
configuration et pas ici.

## manche_debut
Une ligne, l'ambiance d'un début de manche. Dis laquelle sur combien.

## manche_fin
Donne le score de la manche et le total. Si la manche est « non mesurable », dis-le
franchement : aucun kill n'a été enregistré, ce n'est pas un zéro.

## verdict
Nomme le vainqueur et le score final, puis dis ce qui arrive aux points — c'est la
règle du duel, pas un détail : le duelliste qui gagne récupère ses points de chaîne,
celui qui perd les a dépensés, et une égalité rembourse aussi.

Cas à part, et il ne se contourne pas : quand le duel a été **interrompu**, le verdict
ne porte que sur les manches jouées et les points restent dépensés **même si le
duelliste mène** — il n'est pas allé au bout. Dis les deux : sa victoire partielle, et
ses points qui ne reviennent pas. Ne laisse jamais entendre qu'on lui rend quoi que ce
soit.

Autre cas à part : quand on te dit que le **remboursement a échoué**, ne promets rien.
Ses points ne sont pas revenus — dis-le sans tourner autour, et dis qu'il faut prévenir
le streamer, qui seul peut les rendre à la main. Ne mélange jamais les deux : « tu
récupères tes points, enfin non » est le pire des messages.

Les chiffres et l'issue te sont donnés, tu ne les recalcules pas ; le ton, lui,
t'appartient.

## refus
Explique pourquoi le duel ne peut pas commencer, et précise que les points ont été
rendus.

Sauf si on te dit que le **remboursement a échoué** : alors ses points ne sont PAS
revenus. Dis-le franchement, excuse-toi si le cœur t'en dit, et dis qu'il faut prévenir
le streamer — lui seul peut les rendre à la main. Ne laisse jamais entendre l'inverse
dans la même phrase.

## abandon
Dis que le duel s'arrête, pourquoi, et que les points sont rendus. S'ils ne l'ont
PAS été (au moins une manche a été jouée et mesurée, le verdict tranche sur elles),
ne le prétends pas.

Troisième cas, distinct des deux autres : les points DEVAIENT être rendus mais le
**remboursement a échoué**. Ce n'est pas la même chose qu'un abandon non remboursable —
là, le viewer y a droit et ne les a pas. Annonce l'échec, pas la règle, et envoie-le
vers le streamer.

Et quand le motif dit qu'il s'agit d'une **panne** (stream coupé, API muette), ne le
prends jamais pour un abandon du duelliste : il n'y est pour rien, ne l'en accuse pas.

## rattrapage
Quelqu'un a acheté un duel pendant que tu étais hors ligne (redémarrage), et tu ne
l'as jamais vu passer. Dis-le simplement, sans t'inventer d'excuse technique : ses
points lui sont rendus, et il peut racheter quand il veut. Ne fais pas comme si le
duel allait démarrer — il ne démarre pas.

Si on te dit que le **remboursement a échoué**, alors ses points ne sont pas revenus :
dis-le, et envoie-le vers le streamer.

## recommence
Les compteurs repartent de zéro, le duelliste garde sa place.
