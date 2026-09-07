# public-ui/vendor/

Dépendances tierces servies telles quelles. **Ne rien éditer ici** : à la
prochaine mise à jour, tout modification locale disparaît sans laisser de trace.

| Fichier | Version | Licence | Source |
|---|---|---|---|
| `lenis.min.js` | 1.1.18 | MIT (Darkroom Engineering) | `https://unpkg.com/lenis@1.1.18/dist/lenis.min.js` |

Vendoré plutôt que chargé depuis unpkg : un CDN tiers sur le chemin critique du
site public, c'est une dépendance réseau de plus ET une surface d'exécution
qu'on ne contrôle pas. La seule modification apportée au fichier est le retrait
du commentaire `sourceMappingURL`, qui pointait vers un fichier absent et
provoquait un 404 à chaque chargement.

Mise à jour : retélécharger, retirer la ligne `sourceMappingURL`, relancer
`python3 scripts/smoke_front.py --public`.

---

## Archivo Black

| Fichier | Version | Licence | Source |
|---|---|---|---|
| `archivo-black-400.woff2` | v23 (police 1.006) | SIL Open Font License 1.1 (Omnibus-Type) | `https://fonts.gstatic.com/s/archivoblack/v23/HTxqL289NzCGg4MzN6KJ7eW6CYKF_g.woff2` |

Récupérée le **2026-09-07**. Poids 400, style normal, sous-ensembles **latin +
latin-ext** réunis dans UN seul fichier : 372 glyphes, 27 492 octets,
`sha256:c1e3f0089fedacfc6f3ee9e1d5900794b18d421abc0986b6d9504cafdbe70f21`.

Vendorée pour la même raison que Lenis, en plus net : c'est la police du TITRE
des cartes du TCG, et l'overlay OBS l'affiche EN DIRECT. Une requête vers
`fonts.googleapis.com` au démarrage, c'est un premier titre rendu dans la police
de repli si le réseau traîne — sur un stream, ça ne se rattrape pas.

**Licence** : SIL Open Font License, Version 1.1. Copyright 2017 The Archivo
Black Project Authors (`https://github.com/Omnibus-Type/ArchivoBlack`). Attestée
par `https://github.com/google/fonts/blob/main/ofl/archivoblack/OFL.txt`
(`license: "OFL"` dans le `METADATA.pb` du même dossier) et par la police
elle-même, dont le champ `name` n° 14 porte `http://scripts.sil.org/OFL`.

Le texte complet de la licence est à côté, dans `OFL-archivo-black.txt` : la
clause 2 de l'OFL exige qu'il accompagne toute redistribution, et **ce dépôt
est public**. Le lien seul ne suffit pas. Le fichier s'appelait `OFL.txt` tant
qu'il n'y avait qu'une police OFL ici ; il porte le nom de la sienne depuis
qu'elles sont trois, parce que la première ligne de chaque OFL est un
copyright DIFFÉRENT — un `OFL.txt` unique ne couvrirait qu'un seul auteur.

### Comment la récupérer à nouveau

⚠️ **L'`User-Agent` décide de ce que Google renvoie**, et il décide de DEUX
choses à la fois :

- un UA trop vieux (Chrome 36) fait tomber la réponse en **woff** legacy ;
- un UA moderne (Chrome 120) rend bien du woff2, mais **découpé en deux
  fichiers** par `unicode-range` — un pour `latin`, un pour `latin-ext`.

Le fichier unique s'obtient avec un UA qui sait lire le woff2 mais ignore
`unicode-range` — Firefox 40 — ce qui force Google à réunir les sous-ensembles :

```bash
# 1. La feuille CSS : une seule règle @font-face, une seule URL
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.0" \
  "https://fonts.googleapis.com/css?family=Archivo+Black&subset=latin,latin-ext"

# 2. Le woff2 pointé par cette règle
curl -sS -o public-ui/vendor/archivo-black-400.woff2 \
  "https://fonts.gstatic.com/s/archivoblack/v23/HTxqL289NzCGg4MzN6KJ7eW6CYKF_g.woff2"

# 3. Vérifier — « Web Open Font Format (Version 2) », quelques dizaines de ko
file public-ui/vendor/archivo-black-400.woff2
```

Le `v23` de l'URL est un numéro de révision de Google : il bougera. Relire la
feuille CSS plutôt que recopier l'URL ci-dessus. Le fichier est servi tel quel,
aucune modification locale.

---

## Space Grotesk et JetBrains Mono

| Fichier | Version | Licence | Source |
|---|---|---|---|
| `space-grotesk-400.woff2` | v22 (police 2.000) | SIL Open Font License 1.1 (Florian Karsten) | `https://fonts.gstatic.com/s/spacegrotesk/v22/V8mQoQDjQSkFtoMM3T6r8E7mF71Q-gOoraIAEj7oUUsm.woff2` |
| `space-grotesk-500.woff2` | v22 (police 2.000) | idem | `…/V8mQoQDjQSkFtoMM3T6r8E7mF71Q-gOoraIAEj7aUUsm.woff2` |
| `space-grotesk-600.woff2` | v22 (police 2.000) | idem | `…/V8mQoQDjQSkFtoMM3T6r8E7mF71Q-gOoraIAEj42Vksm.woff2` |
| `space-grotesk-700.woff2` | v22 (police 2.000) | idem | `…/V8mQoQDjQSkFtoMM3T6r8E7mF71Q-gOoraIAEj4PVksm.woff2` |
| `jetbrains-mono-400.woff2` | v24 (police 2.211) | SIL Open Font License 1.1 (JetBrains) | `https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKxjOA.woff2` |
| `jetbrains-mono-500.woff2` | v24 (police 2.211) | idem | `…/tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8-qxjOA.woff2` |
| `jetbrains-mono-700.woff2` | v24 (police 2.211) | idem | `…/tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8L6tjOA.woff2` |

Récupérées le **2026-09-07**. Style normal, sous-ensembles **latin + latin-ext**
réunis dans UN seul fichier par poids (Space Grotesk : 818 glyphes, 735 points
de code ; JetBrains Mono : 1 167 glyphes, 976 points de code).

```
sha256:3520459c3898403dd3011c661a200305e5165e935413fd35df1b19c35da9365f  space-grotesk-400.woff2
sha256:7c1d5ed34611c3068cd0b4fe8493e2f51dc022309afc2b800e402fa582ba2356  space-grotesk-500.woff2
sha256:e1d073e69b4b662ef5ddbbcb18f0e68549b7f14e3ebaf1aabb5e00eb5363886a  space-grotesk-600.woff2
sha256:cff763a4cf84bb5f120b5f7938c79012da850ead25e86dbb6e2ca90b722e0110  space-grotesk-700.woff2
sha256:fb7f08e7a457c94c70a28ca549dd1bee7c3261756c6886934098cb978e22de6c  jetbrains-mono-400.woff2
sha256:1ff3bfa1f1d787f00f987e5296f8484e1cbfcb6d7f96ab4b9245c74dba0a4aa0  jetbrains-mono-500.woff2
sha256:295b2e472b2b1b6dfd83563802a06998cd645e661dca45353d0fd6e8573d219e  jetbrains-mono-700.woff2
```

Ce sont les deux polices du thème « braise » : Space Grotesk pour le texte,
JetBrains Mono pour les chiffres et le monospace. Elles arrivaient de
`fonts.googleapis.com` par un `<link>` dans `index.html` ; ce lien est retiré,
les `@font-face` sont désormais en tête de `public-ui/style.css`. Vendorées
pour la même raison que Lenis et Archivo Black : un tiers de moins sur le
chemin critique, et un premier affichage qui ne dépend plus du réseau de
Google.

**Licence** : SIL Open Font License, Version 1.1 pour les deux.

- Space Grotesk — Copyright 2020 The Space Grotesk Project Authors
  (`https://github.com/floriankarsten/space-grotesk`). Attestée par
  `https://github.com/google/fonts/blob/main/ofl/spacegrotesk/OFL.txt`
  (`license: "OFL"` dans le `METADATA.pb` du même dossier) et par la police
  elle-même, dont le champ `name` n° 14 porte `https://scripts.sil.org/OFL`.
- JetBrains Mono — Copyright 2020 The JetBrains Mono Project Authors
  (`https://github.com/JetBrains/JetBrainsMono`). Attestée par
  `https://github.com/google/fonts/blob/main/ofl/jetbrainsmono/OFL.txt`,
  le `METADATA.pb` du même dossier, et le même champ `name` n° 14.

Les textes complets sont à côté, dans `OFL-space-grotesk.txt` et
`OFL-jetbrains-mono.txt`, copiés tels quels depuis `google/fonts`. **Un fichier
par police, et pas un seul pour trois** : le corps de l'OFL est le même, mais sa
PREMIÈRE ligne est le copyright de l'auteur, et les trois auteurs sont
différents (Omnibus-Type, Florian Karsten, JetBrains). Un `OFL.txt` unique
n'attesterait la licence que d'une police sur trois.

### Comment les récupérer à nouveau

Même piège d'`User-Agent` que pour Archivo Black — un UA moderne rend un fichier
PAR `unicode-range`, il faut Firefox 40 pour obtenir un fichier unique couvrant
latin + latin-ext :

```bash
# 1. La feuille CSS : sept règles @font-face, une URL chacune
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.0" \
  "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&subset=latin,latin-ext"

# 2. Chaque woff2 pointé par ces règles, un par poids
curl -sS -o public-ui/vendor/space-grotesk-400.woff2 "https://fonts.gstatic.com/s/spacegrotesk/v22/…"
# … idem pour 500, 600, 700 et les trois JetBrains Mono

# 3. Vérifier — « Web Open Font Format (Version 2) », quelques dizaines de ko
file public-ui/vendor/*.woff2
```

Les `v22` / `v24` sont des numéros de révision de Google : ils bougeront. Relire
la feuille CSS plutôt que recopier les URL ci-dessus. Les fichiers sont servis
tels quels, aucune modification locale.
