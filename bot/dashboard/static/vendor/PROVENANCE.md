# bot/dashboard/static/vendor/ — les polices

Dépendances tierces servies telles quelles. **Ne rien éditer ici** : à la
prochaine mise à jour, toute modification locale disparaît sans laisser de
trace. Les bibliothèques JS du même dossier (`canvas-confetti`, `spin-wheel`)
sont documentées à côté, dans `README.md`.

---

## Inter

| Fichier | Version | Licence | Source |
|---|---|---|---|
| `inter-400.woff2` | v20 (police 4.001) | SIL Open Font License 1.1 (Rasmus Andersson) | `https://fonts.gstatic.com/s/inter/v20/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuLyfAZFhiA.woff2` |
| `inter-500.woff2` | v20 (police 4.001) | idem | `…/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuI6fAZFhiA.woff2` |
| `inter-600.woff2` | v20 (police 4.001) | idem | `…/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuGKYAZFhiA.woff2` |
| `inter-700.woff2` | v20 (police 4.001) | idem | `…/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuFuYAZFhiA.woff2` |
| `inter-800.woff2` | v20 (police 4.001) | idem | `…/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuDyYAZFhiA.woff2` |

Récupérées le **2026-09-07**. Style normal, sous-ensembles **latin + latin-ext**
réunis dans UN seul fichier par poids : 1 192 glyphes, 950 points de code,
~51 ko chacun.

```
sha256:c5ef976fc27b16b9145b977611f41ca32b4838596c35f92615e46521140ccb11  inter-400.woff2
sha256:7a2a4832506447653f01c6b5421babc0540dac1c35857a121bfa1336cedd6264  inter-500.woff2
sha256:5bd868c2ed6a9c2bb0e5df95273ab08a37c6cb1fae261bf835cf92ebf81efcfb  inter-600.woff2
sha256:995e0bd2f370dd31b874878f0664ae3bbdc4fea947ea6dc80fd988e171a18b12  inter-700.woff2
sha256:a8f15d3213a80013fdadfd5020f90ba15d55073b9558fbe89d7f775dbcbaec7b  inter-800.woff2
```

C'est la police du dashboard admin — `--font` dans `style.css`, et les cinq
poids sont réellement utilisés par ses règles. Elle arrivait de
`fonts.googleapis.com` par un `<link>` dans `index.html` ; ce lien est retiré,
les `@font-face` sont désormais en tête de `bot/dashboard/static/style.css`.
Vendorée pour la même raison que les polices du site public
(`public-ui/vendor/PROVENANCE.md`) : un tiers de moins sur le chemin critique,
et un premier affichage qui ne dépend plus du réseau de Google. Le dossier est
séparé de celui du site public **exprès** — `public-ui/` est une autre surface,
bind-montée, que l'owner peut remplacer sans que le panneau d'admin perde sa
typo.

**Licence** : SIL Open Font License, Version 1.1. Copyright 2020 The Inter
Project Authors (`https://github.com/rsms/inter`). Attestée par
`https://github.com/google/fonts/blob/main/ofl/inter/OFL.txt`
(`license: "OFL"` dans le `METADATA.pb` du même dossier) et par la police
elle-même, dont le champ `name` n° 14 porte `https://openfontlicense.org`. Le
`METADATA.pb` date le copyright de 2016, l'`OFL.txt` de 2020 : c'est ce dernier
qui est copié ici, donc c'est sa ligne qui fait foi.

Le texte complet est à côté, dans `OFL-inter.txt`, copié tel quel depuis
`google/fonts` : la clause 2 de l'OFL exige qu'il accompagne toute
redistribution, et **ce dépôt est public**. Le lien seul ne suffit pas. Un
fichier par police et pas un `OFL.txt` générique — la première ligne de chaque
OFL est le copyright de SON auteur.

### Comment les récupérer à nouveau

⚠️ **L'`User-Agent` décide de ce que Google renvoie** : un UA moderne
(Chrome 120) rend le woff2 **découpé par `unicode-range`**, un fichier par
sous-ensemble ; un UA trop vieux (Chrome 36) fait tomber la réponse en **woff**
legacy. Le fichier unique s'obtient avec un UA qui lit le woff2 mais ignore
`unicode-range` — Firefox 40 — ce qui force Google à réunir les sous-ensembles.

⚠️ **Et ici, l'API v1 (`/css`) et pas `css2`.** Inter couvre le cyrillique, le
grec et le vietnamien ; `css2` ignore le paramètre `subset` et sert la police
ENTIÈRE — 109 ko par poids, 543 ko en tout pour des alphabets que le panneau
n'affiche jamais. L'API v1 honore `subset`, et rend 51 ko par poids.

```bash
# 1. La feuille CSS : cinq règles @font-face, une URL chacune
curl -s -H "User-Agent: Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.0" \
  "https://fonts.googleapis.com/css?family=Inter:400,500,600,700,800&subset=latin,latin-ext"

# 2. Chaque woff2 pointé par ces règles, un par poids
curl -sS -o bot/dashboard/static/vendor/inter-400.woff2 "https://fonts.gstatic.com/s/inter/v20/…"
# … idem pour 500, 600, 700, 800

# 3. Vérifier — « Web Open Font Format (Version 2) », une cinquantaine de ko
file bot/dashboard/static/vendor/inter-*.woff2
```

Le `v20` de l'URL est un numéro de révision de Google : il bougera. Relire la
feuille CSS plutôt que recopier les URL ci-dessus. Les fichiers sont servis tels
quels, aucune modification locale. Après mise à jour, relancer
`python3 scripts/smoke_front.py --admin`.
