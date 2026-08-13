# Registre des annonces du duel Apex

Une section par type d'événement de `bot/core/apex/duel_runner.py`. Le texte décrit CE
QU'IL FAUT VISER, jamais une phrase à recopier mot pour mot.

D'autres sections viendront compléter ce fichier au fil des tâches suivantes — ne pas
s'étonner qu'il ne couvre pas encore tous les types d'`Evenement`.

## compte_introuvable
Le compte Apex n'a pas été retrouvé. Explique les étapes qu'on te donne — elles sont
exactes, ne les improvise pas — et donne le lien tel quel. Reste léger : ce n'est pas
la faute du viewer, la recherche par pseudo de l'API rate des comptes réels.

## duel_ouvert
Annonce le duel et rappelle deux choses, sans en faire une notice : le viewer doit
être invité dans le squad d'Azraël, et **la Mixtape ne compte aucun kill** — le duel
doit se jouer en Battle Royale ou en Joker.

## manche_debut
Une ligne, l'ambiance d'un début de manche. Dis laquelle sur combien.

## manche_fin
Donne le score de la manche et le total. Si la manche est « non mesurable », dis-le
franchement : aucun kill n'a été enregistré, ce n'est pas un zéro.

## verdict
Nomme le vainqueur et le score final. En cas d'égalité, dis que personne ne l'emporte.

## refus
Explique pourquoi le duel ne peut pas commencer, et précise que les points ont été
rendus.

## abandon
Dis que le duel s'arrête, pourquoi, et que les points sont rendus. S'ils ne l'ont
PAS été (au moins une manche a été jouée et mesurée, le verdict tranche sur elles),
ne le prétends pas.

## recommence
Les compteurs repartent de zéro, le duelliste garde sa place.
