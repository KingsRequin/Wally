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

Le texte complet de la licence est à côté, dans `OFL.txt` : la clause 2 de
l'OFL exige qu'il accompagne toute redistribution, et **ce dépôt est public**.
Le lien seul ne suffit pas.

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
