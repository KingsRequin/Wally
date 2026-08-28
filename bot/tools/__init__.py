"""Les outils que Wally peut appeler — un module par outil, et rien d'autre.

## Pourquoi ce dossier existe

Les outils étaient dispersés sur 15 fichiers et 4 dossiers, sans règle. Trois
symptômes mesurés le 2026-08-28 :

  · `bot/discord/handlers.py` (3 760 lignes, le plus gros fichier du projet)
    portait ONZE outils, que `twitch/handlers.py` importait en bloc — vingt
    symboles d'un coup. Un adapter de plateforme était devenu la bibliothèque
    commune de l'autre.
  · `bot/core/` contredisait sa propre définition. Le CLAUDE.md le décrit comme
    « primitives SANS LLM » ; il contenait `follow_tool`, `music_tool`,
    `shoutout_tool`.
  · Et surtout : ces trois-là n'y étaient pas par choix. Chacun porte en en-tête
    le même aveu — rangé là pour ne pas faire de cycle avec `discord/handlers`.
    Trois fois le même contournement, c'est une structure qui pousse au mauvais
    placement.

## Ce qui vit ici, et ce qui n'y vit pas

**Ici** : un module qui n'est QUE l'outil — sa définition (le dict au format
OpenAI Chat Completions) et son exécutant. `follow_tool`, `music_tool`,
`shoutout_tool`.

**Pas ici** : un SERVICE qui expose son propre outil. `web_search`, `scrape`,
`history_search`, `prediction_kills`, `apex/tool` gardent leur outil collé à la
logique qu'il appelle — les séparer éloignerait la définition de ce qu'elle
décrit, sans rien régler.

La ligne de partage est donc : *est-ce que ce fichier existerait encore si on
retirait l'outil ?* Si oui, c'est un service, il reste chez lui.

## La règle pour la suite

Un nouvel outil se pose ICI, jamais dans un adapter. C'est ce qui empêche
`discord/handlers.py` de regagner ce qu'il vient de perdre, et ce qui évite au
prochain contributeur de refaire le contournement par `core/`.
`tests/test_tools_rangement.py` le vérifie.
"""
