# Brief — maquette jouable du TCG (session parallèle)

**Date** : 2026-09-04 · **Pour** : une seconde session Claude Code, en parallèle de la conception
**Lire d'abord** : `docs/superpowers/specs/2026-09-05-tcg-regles-heros-tactiques.md`

---

## Ce qu'on veut voir

Un **plateau et des cartes à l'écran**, pour juger le design autrement que sur du texte. Rien
d'autre. La conception des règles continue en parallèle et les valeurs bougeront encore.

## 🚨 La ligne à ne pas franchir : aucune règle en JavaScript

**Le moteur de règles vit côté serveur, en Python.** Toute règle dupliquée en JS est une porte de
triche ouverte, et un deuxième jeu à maintenir (spec mère §7).

Concrètement, pour cette maquette :

- ✅ **Afficher** une carte, une ligne de héros, une main, une jauge d'énergie, des dégâts.
- ✅ **Animer** un coup, une Chute, un Ultime qui part.
- ✅ Travailler sur des **données figées en dur** dans un fichier de démo.
- ❌ **Calculer** qui gagne, appliquer des dégâts, décider si un Ultime est jouable, faire tourner
  un tour. Rien de tout ça n'est du JS — même « juste pour la démo ».

La maquette montre des **états**, elle ne les produit pas. Un état = un objet JSON figé. Pour voir
la suite d'un tour, on passe d'un état figé au suivant, à la main.

Pourquoi cette rigueur sur une simple maquette : la maquette devient toujours le squelette de la
vraie page. Un calcul de dégâts écrit « pour voir » finit en production six semaines plus tard,
et on ne saura plus qu'il est là.

## Ce qui est STABLE et sur quoi on peut construire

L'anatomie d'une carte et la structure du plateau sont arrêtées :

**Un héros** — nom · illustration · Attaque · PV · Aura · un Ultime (nom + coût 6-10 + texte) ·
rareté (6 paliers) · faction (Lumineuse / Sombre / aucune) · 1-2 affinités.

**Une tactique** — nom · illustration · coût (1-5) · texte d'effet · type (passif ou tactique).

**Le plateau** — 3 héros en ligne face à 3 héros · une réserve de 2 · une main de tactiques ·
une jauge d'énergie (0-12) par joueur.

**Ce qui n'est PAS stable** : toutes les valeurs numériques (plafond d'énergie, PV de Wally,
coûts). Ne jamais les écrire en dur ailleurs que dans le fichier de démo.

## Données de démo — de vraies cartes, déjà calculées

Budget 12, rareté Âme, calculées le 2026-09-04 par la procédure de
`2026-09-04-tcg-fabrication-carte.md` :

| Héros | ATK | PV | Aura | Ce que la forme dit |
|---|---|---|---|---|
| OriganireTV | 6 | 3 | 3 | l'éclair : il déboule fort et ne reste pas |
| KassandreYunikon | 5 | 4 | 3 | la frappeuse |
| ClakerNoJutsu | 5 | 4 | 3 | |
| KingsRequin | 4 | 5 | 3 | l'équilibré |
| Azraël | 3 | 6 | 3 | le mur : toujours là |
| rhae___ | 2 | 5 | 5 | parle peu, relie tout le monde |

⚠️ Ces valeurs sont un **exemple de rendu**, pas la vérité du jeu : elles seront recalculées.
Les mettre dans un seul fichier `demo.js`, jamais éparpillées dans les composants.

## Direction visuelle

Le site public a son thème **« braise »** (sombre, Space Grotesk + JetBrains Mono, une seule
couleur saturée, tokens dans `:root` de `style.css`). La carte doit s'y intégrer — **ne pas
redéfinir de couleur en dur dans un module JS**, prendre les tokens existants.

Trois surfaces distinctes coexistent déjà dans ce dépôt et ne se mélangent pas : le glassmorphism
du dashboard, l'encre/papier de l'overlay OBS, la braise du site public. Le TCG est sur la
**braise**.

## Périmètre de fichiers — à respecter strictement

| Autorisé | Interdit |
|---|---|
| `public-ui/pages/tcg.js` (la page existante, 116 l., purement vitrine) | `bot/**` — aucun fichier Python |
| de nouveaux fichiers `public-ui/pages/tcg-*.js` | `docs/superpowers/specs/**` — la conception continue en parallèle |
| `public-ui/style.css` (ajouts en fin de fichier) | tout ce qui touche la mémoire, les liaisons, l'overlay |

⚠️ **`style.css` : la position d'une règle décide.** Deux pièges déjà payés dans ce fichier — une
media query battue par une règle déclarée 200 lignes plus bas à spécificité égale, et un
`grid-template-columns` en style en ligne qui battait la media query. Ajouter en fin de fichier,
et vérifier en 390 px de large.

## 🚨 Règle de commit — un incident déjà survenu aujourd'hui

Deux sessions travaillent sur le **même dépôt et le même working tree**. Le 2026-09-04, une
session a lancé un `commit` global et a embarqué la modification d'une autre dans son commit, sous
un message qui ne la décrivait pas. Rien n'a été perdu, mais c'était déjà poussé.

- **Toujours `git add <chemins explicites>`**, jamais `git add -A`, jamais `git commit -a`.
- **Vérifier `git status` avant de commiter** et ne rien ajouter qu'on n'a pas écrit soi-même.
- En cas de doute sur un fichier modifié qu'on ne reconnaît pas : **le laisser**, et le signaler.

## Vérifications dues avant de dire que c'est fait

```bash
python3 scripts/lint_js.py       # porte dure + cliquet sur le front
python3 scripts/smoke_front.py --public   # le SEUL test qui exécute ce JavaScript
```

`smoke_front.py` charge les pages, échoue sur une erreur JS, un panneau vide **ou un débordement
horizontal en 390 px**. Il ne demande aucun rebuild (tout est bind-monté) et vise `127.0.0.1:8080`.

⚠️ Un test vert ne prouve pas qu'un panneau MONTE : un `throw` dans un `mount()` casse tous les
montages suivants, et `node --check` ne voit pas les TDZ. Vérifier dans un navigateur.
