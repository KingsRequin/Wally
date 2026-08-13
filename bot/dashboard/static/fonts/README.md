# Polices de l'overlay

Auto-hébergées : OBS ne doit pas dépendre d'un appel réseau pour afficher du
texte pendant un live, et un CDN qui répond en 2 s laisserait la bulle vide.

| Fichier | Famille | Poids | Usage |
|---|---|---|---|
| `fredoka.woff2` | [Fredoka](https://fonts.google.com/specimen/Fredoka) | variable 300–700 | tout le texte : bulles, widgets |
| `bangers.woff2` | [Bangers](https://fonts.google.com/specimen/Bangers) | 400 | titres de widget et gros moments, en capitales |

Les deux sont sous **SIL Open Font License 1.1**, qui autorise l'usage,
l'intégration et la redistribution.

Sous-ensemble `latin` (U+0000–00FF) : il couvre les accents français. Récupérés
via l'API `fonts.googleapis.com/css2`, qui renvoie **plusieurs** `@font-face`,
un par plage Unicode — prendre le premier bloc donne `latin-ext`, qui ne
contient qu'une poignée de glyphes accentués et fait replier tout le reste sur
une serif système.
