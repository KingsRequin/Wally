# La courbe Apex : périodes libres, trous compressés, parties classées

**Date** : 2026-08-12 · **État** : validé, à construire en trois lots

## Le problème

Trois défauts constatés sur la même image, demandée en live le 2026-08-12 :

1. **« La courbe de ce stream » rend 15 heures.** `live` vaut douze heures glissantes,
   arbitraires. Aucun moyen de demander autre chose que `live`/`jour`/`semaine`/`mois` : une
   courbe des cinq dernières minutes est impossible à formuler.
2. **La courbe est coupée en deux.** Neuf heures sans un seul relevé au milieu, parce que
   personne ne jouait. Le trait interrompu est juste — relier les deux blocs inventerait une
   progression nocturne — mais l'image consacre les trois quarts de sa largeur à du vide.
3. **Toutes les parties se ressemblent.** Rien ne distingue une session classée d'une session
   non classée.

## Ce que l'API donne, et ce qu'elle ne donne pas

Vérifié le 2026-08-12 sur le compte d'Azraël, pas déduit du code :

- **Le mode d'une partie n'existe nulle part.** Les trackers du joueur sont libellés « BR Kills »,
  « BR Wins », « BR Damage » — et les compteurs BR incluent le classé. `realtime` ne porte que
  `lobbyState`, `isInGame`, `selectedLegend`, `currentState` : jamais la file de jeu. Aucun
  « joker », « mixtape » ou « ranked » identifiable.
- **Le RP, lui, est là** : `global.rank.rankScore` (7787, Gold 1), lu à chaque sonde. Une partie
  qui fait bouger le RP est une partie classée. C'est le seul signal de mode exploitable.
- **Le début du live est connu** : `started_at` de `_stream_info`, déjà consommé par
  `ApexWatcher` pour identifier le live courant.

## Lot 1 — les périodes

### Un seul parseur, trois consommateurs

Nouveau module `bot/core/apex/periode.py`. L'action `progression`, le panneau d'overlay et la
route image passent tous par lui : trois calculs de fenêtre séparés, c'est trois occasions qu'une
carte passe la garde et que l'image refuse ensuite de la tracer (défaut déjà corrigé une fois le
2026-08-12, `18526e0`).

```
Fenetre(depuis: float, cle: str, libelle: str)
parse_periode(texte, *, maintenant=None, debut_stream=None) -> Fenetre   # ValueError si illisible
libelle_de(cle, depuis, *, maintenant=None) -> str
```

Formes acceptées : `stream` / `live` / `session` · `jour` / `aujourd'hui` · `semaine` · `mois` ·
toute durée (`5m`, `30min`, `45 minutes`, `2h`, `1h30`, `3j`). Casse et accents ignorés.

Bornes : **une minute** au minimum, **400 jours** au maximum (la rétention de l'historique).
Hors bornes ou illisible : refus qui liste les formes valides — un silence enverrait Wally
inventer un chiffre.

L'enum `period` disparaît des deux schémas d'outil, remplacé par un champ libre décrit par
l'exemple.

### « Ce stream », et le dernier à défaut

`parse_periode` reçoit `debut_stream`, que le service résout dans cet ordre :

1. **live en cours** → `started_at` Twitch, injecté dans le service par `main.py` ;
2. **sinon** → `ApexHistory.debut_derniere_session(uid)` : le dernier bloc de relevés, un trou de
   plus de trente minutes marquant la fin d'une session. Couvre « il n'y a plus de stream, prends
   le dernier » **et** le cas où le bot a redémarré en plein live ;
3. **rien en base** → refus explicite.

Le niveau 2 commence à la première partie plutôt qu'à l'ouverture du stream. C'est voulu :
quelques minutes de plat en moins.

### L'URL de l'image porte un instant, plus un mot

`/api/public/apex/progression.png?uid=…&notion=kills&depuis=<epoch>&libelle=<clé>` au lieu de
`period=live`. Deux raisons : le dashboard ne sait pas quand le live a commencé — lui passer
`stream` le ferait diverger de la carte affichée ; et `libelle` est une **clé d'une liste
blanche**, jamais du texte libre, parce que cette route est publique et que son titre finit
dessiné dans l'image.

## Lot 2 — les trous compressés  ✅ construit le 2026-08-12

Sur la cumulative uniquement (l'histogramme par jour ne souffre pas du problème) : tout
intervalle sans relevé de plus de **vingt minutes** est réduit à une bande étroite, marquée d'un
pointillé vertical et annotée de sa durée réelle (« ⋯ 9 h »). Les heures restent lisibles de part
et d'autre. Le trait reste interrompu : on compresse le vide, on ne le comble pas.

La construction des séries (marches, trous, couleurs) sort dans `bot/core/apex/serie.py`,
testable sans matplotlib. `chart.py` ne garde que le dessin — il porterait sinon la compression
et la coloration en plus du reste, et deviendrait le genre de bloc qu'on ne relit plus.

### Trois règles que la donnée réelle a imposées

La première image tracée sur les relevés d'Azraël a montré ce que la spec n'avait pas prévu : un
compte n'est sondé qu'en live ou à la consultation, si bien qu'une journée compte **3,7 h de
relevés pour 13,5 h de vide** et **onze trous** de plus de vingt minutes. Comprimer restait juste,
mais tout le reste s'écroulait.

- **Nommer ≠ comprimer.** Onze bandes annotées empilaient onze durées en bouillie sur le haut de
  l'image. Le pointillé marque désormais TOUS les vides — c'est lui qui dit « on n'a pas
  regardé » — mais le libellé ne va qu'aux vides pesant au moins un dixième de la période
  couverte. Savoir qu'une pause a duré vingt minutes ne change pas la lecture de la courbe ;
  savoir qu'une nuit de neuf heures est passée, si.
- **Les bandes ont un budget commun.** À 4 % de la largeur chacune, onze bandes reprenaient 26 %
  de l'image — un quart de la place rendu au vide qu'on venait d'en chasser. Au-delà de deux ou
  trois trous, chacune rétrécit pour que l'ensemble tienne dans 15 %.
- **Les heures s'écartent.** Chaque bloc gradue sur sa propre grille d'heures rondes : rien
  n'empêchait la dernière d'un bloc de tomber juste avant la première du suivant. « 21h30 » et
  « 22h00 » se sont retrouvés collés de part et d'autre d'une bande étroite. Deux heures affichées
  gardent maintenant 7 % de la largeur entre elles — un libellé en occupe 4,3 % — et quand deux se
  disputent la place, c'est celle qui OUVRE un bloc qui reste, faute de quoi un bloc entier ne
  serait plus daté du tout.

Les tests rejouent les **intervalles exactement relevés en base**, pas une approximation
régulière : ni les libellés empilés ni les heures qui se recouvrent ne se reproduisent sur une
cadence lisse, et l'instant de départ compte autant que les écarts puisque la grille se cale sur
des heures rondes — un `T0` à 20h00 pile évitait le défaut par chance.

## Lot 3 — classé vs non classé

`ApexWatcher` range `rank_score` avec les autres compteurs (écriture au changement seulement).
Au tracé, une marche dont l'intervalle contient un changement de RP est colorée « classé », les
autres « non classé », avec une légende.

Deux limites assumées, à dire plutôt qu'à masquer :

- **aucune rétroactivité** : sans point de RP sur la fenêtre, la courbe reste monochrome et sans
  légende — pas de mention trompeuse sur l'historique d'avant ce déploiement ;
- `rank_score` reste une notion **interne**, absente des compteurs proposés au modèle : le calcul
  de gain somme les écarts positifs, et un RP qui descend n'est pas une régression à masquer.

## Vérification

Chaque lot : tests d'abord (chacun rejoué sur l'ancien code pour prouver qu'il échouait),
`pytest` complet, cliquets silences et types, rebuild, vérification sur le bot en marche, commit
et push. Les images sont **ouvertes et regardées** — la courbe en diagonale du 2026-08-11 était
invisible aux tests et sautait aux yeux sur le PNG.
