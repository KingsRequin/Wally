# TCG du Purgatoire — fabriquer une carte-personne

**Date** : 2026-09-04 · **Statut** : procédure arrêtée, valeurs à recalibrer par saison
**Spec mère** : `2026-08-29-tcg-purgatoire-design.md` · **Catalogue** : `2026-09-04-tcg-catalogue-reflexes.md`

La spec mère dit *que* les chiffres sont calculés. Ce document dit **comment**, assez
précisément pour être codé, et pour que deux passes sur la même personne rendent la même carte.

> 🚨 **Pourquoi ce document existe.** La première carte (ClakerNoJutsu) a été fabriquée « à la
> main » le 2026-09-04 : `Voix 5 / Aura 3 / Piquant 1`, à l'intuition. C'est exactement ce que la
> spec mère interdit — un total juste ne suffit pas si la répartition est une opinion. Personne
> n'aurait pu reproduire ces trois nombres. Écrire la procédure a ensuite montré que l'intuition
> était bonne (§7) — mais on ne le savait pas avant de l'écrire, et c'est tout le sujet.

---

## 1. Ce qui ne se calcule pas : l'owner le pose

Arbitré le 2026-09-04. Deux champs sortent du calcul et sont **saisis à la main**, carte par
carte, dans la base Notion « 🃏 Cartes du Purgatoire » :

| Champ | Pourquoi à la main |
|---|---|
| **Rareté** | Les grades Twitch (sub, VIP, modo) ne sont pas lisibles : `_STREAMER_SCOPES` ne porte ni `channel:read:vips` ni `moderation:read`, et les ajouter n'agit pas sur un token déjà émis. L'owner connaît sa commu mieux que ces scopes. |
| **Faction** | Elle venait du rôle Discord `Ames Lumineuses` / `Ames Sombres` — or **les deux tiers des cartes sont des comptes Twitch**, qui n'ont aucun rôle. La mécanique du deck mono-faction serait morte pour la majorité. |

Conséquence assumée : la rareté devient un **choix éditorial** de l'owner et non une lecture
mécanique d'un grade. La spec mère l'avait nommé comme un risque (« la rareté est un jugement
public sur ta place dans la commu ») ; le risque est le même, la décision est simplement prise
par un humain qui connaît les gens.

⚠️ La **rareté modifie le budget** (`+0 / +1 / +2 / +3 / +5 / +8`). La changer après coup
**refait toutes les stats de la carte**. À poser avant de figer, pas après.

---

## 2. Les trois mesures — source exacte

Fenêtre : **toute l'histoire connue**. Pas de fenêtre glissante — les cartes se recalculent par
saison (spec mère §4), c'est déjà la respiration du système.

| Stat | Mesure brute | Source exacte |
|---|---|---|
| **Voix** | nombre de messages | `logs/conversations/{discord,twitch,voice}/**/*.jsonl`, lignes `type == "message_in"`, groupées par **`author_id`** |
| **Aura** | nombre de faits de relation | `atomic_facts` où `status='active'` et `category='REL'` |
| **Piquant** | charge de colère déclenchée | `emotional_memory` où `emotion='anger'` → somme des `affinity` |

### 🚨 Grouper par `author_id`, JAMAIS par `author`

Le journal porte les deux. `author` est le libellé d'affichage (`display_name (@username)`) et il
**change quand la personne change de pseudo** : KingsRequin y apparaissait sous trois libellés
(3025 + 781 + 11), zeddo sous trois aussi. Grouper par libellé donnait **473 messages à Jubeii au
lieu de 0** — soit une Voix fausse pour tous ceux qui ont changé de nom, c'est-à-dire les plus
anciens, c'est-à-dire ceux dont la carte compte le plus.

`author_id` est présent sur **100 %** des `message_in` (0 manquant sur 104 072 lignes vérifiées).
La plateforme se lit dans le chemin, et **`voice/` compte comme `discord`**.

Les identifiants passent ensuite par la **résolution d'alias** (`user_links` acceptées) : une
personne à deux comptes est une seule carte, avec la somme de ses mesures.

### Pourquoi pas `category='EMOTION'` pour le Piquant

C'était la source évidente, et elle ne discrimine rien : **médiane 0, maximum 4** sur toute la
commu. ClakerNoJutsu avec ses 3 faits `EMOTION` tombait au **percentile 98** — un artefact pur,
qui lui donnait un Piquant élevé sans qu'aucune mesure ne le soutienne. `emotional_memory.anger`
couvre 40 personnes avec une médiane de 0,049 et un maximum de 0,749 : elle sépare vraiment.

**Une mesure trop rare ne mesure pas peu, elle mesure faux.** Vérifier la distribution d'un signal
avant de l'adosser à une stat, pas après.

---

## 3. La répartition — la formule

```
pool          = personnes ayant ≥ 5 faits actifs           (123 au 2026-09-04)
médiane_i     = médiane de la mesure i sur le pool          (messages 31 · REL 2 · anger 0,050)
rapport_i     = mesure_i / médiane_i                        sans dimension
score_i       = rapport_i ** 0.5                            racine carrée
poids_i       = score_i / Σ score
stat_i        = budget × poids_i                            réparti au PLUS GRAND RESTE
```

Puis, dans cet ordre : **plancher `Voix ≥ 1`** (on retire 1 à la plus haute des deux autres),
puis **plafond 9** par stat (le surplus va à la plus basse). `Aura` et `Piquant` peuvent valoir 0
— c'est une forme, pas un défaut.

### Pourquoi la racine carrée, et pas le percentile ni le log

Trois normalisations essayées sur les mêmes gens :

| Méthode | Résultat pour ClakerNoJutsu | Défaut |
|---|---|---|
| **Percentile** intra-commu | `3 / 3 / 3` | Il est dans le haut du panier sur les trois mesures, donc ses trois percentiles valent ~0,99, donc les poids sont égaux. **Le percentile mesure le rang, pas la forme** — et quelqu'un de fort partout se retrouve sans forme du tout. |
| **Logarithme** du rapport | `4 / 4 / 1` | Compresse trop : 91× la médiane et 40× la médiane deviennent 4,5 et 3,7. Tout le monde finit en Voix 4-5. |
| **Racine carrée** ✅ | `5 / 3 / 1` | Garde l'écart entre les ordres de grandeur sans laisser le plus gros signal tout rafler. |

La racine carrée n'est pas un réglage esthétique : c'est le seul des trois qui produise des
**profils distincts** sur des personnes réellement différentes (§7).

---

## 4. Le coût

```
coût = quintile( percentile(longueur médiane des messages de la personne) ) → 1..5
```

Longueur médiane en caractères, sur les mêmes lignes `message_in`, groupées par `author_id`.
Pool de référence : les personnes ayant **≥ 20 messages** (98 au 2026-09-04 ; médianes observées
de 14 à 100 caractères).

Quintiles : `p < 20 % → 1` · `< 40 % → 2` · `< 60 % → 3` · `< 80 % → 4` · sinon `5`.

Rappel de la spec mère : c'est un trait de **style**, jamais de mérite. Tu écris des pavés, ta
carte est chère et lourde ; tu balances des punchlines, elle se pose au premier tour.

---

## 5. Les cas limites — tranchés, pas laissés au moteur

| Cas | Décision |
|---|---|
| Aucun message au journal | `Voix` prend le plancher 1, le reste se répartit sur Aura et Piquant |
| Aucun signal du tout (les trois à 0) | tout le budget en `Voix`. Une carte muette n'existe pas |
| Moins de 5 faits actifs | **pas de carte.** Wally n'en sait pas assez ; il inventerait |
| Deux comptes liés | une seule carte, mesures sommées après résolution d'alias |
| Personne qui refuse sa carte | retrait total de la circulation, y compris des collections déjà distribuées (spec mère §8) |
| Personne décédée | statut `hommage — hors jeu` : la carte existe, elle n'entre ni en lootbox, ni en tirage, ni en deck |

---

## 6. La capacité passive du héros

Le héros ne se pose pas : il reste au bord du plateau et donne une passive (spec mère §3.1), qui
était en « à concevoir ». Elle **dérive de la stat dominante** de sa propre carte — donc de la
personne, pas de son grade :

| Dominante | Passive | Effet |
|---|---|---|
| **Voix** | *Porte-voix* | +1 Voix à la première carte que tu poses chaque tour |
| **Aura** | *Hôte* | +1 Aura à tes cartes de la table où tu en as le plus |
| **Piquant** | *Aiguillon* | +1 Piquant à ta carte la plus chère en jeu |

Égalité départagée dans l'ordre **Voix > Aura > Piquant**, comme partout ailleurs. Aucune passive
n'est plus forte qu'une autre : c'est la même valeur, appliquée à trois endroits différents.

Dériver de la dominante plutôt que du palier de rareté évite qu'un Archange ait *en plus* une
meilleure passive : son prestige coûte déjà 12 sur les 20 du deck.

---

## 7. Vérification sur huit personnes réelles

Calculé le 2026-09-04, budget 9 (coût 3, rareté Âme) pour tout le monde afin que seules les
formes se comparent :

| Personne | messages | REL | anger | Voix | Aura | Piquant | Ce que la forme dit |
|---|---|---|---|---|---|---|---|
| Kassandre | 3832 | 35 | 0,13 | **6** | 2 | 1 | la voix de la commu |
| Azraël | 1158 | 8 | 0,09 | **6** | 2 | 1 | il parle, il ne réseaute pas |
| KingsRequin | 3914 | 76 | 0,75 | **5** | 2 | **2** | le seul vrai Piquant — c'est lui qui taquine Wally |
| ClakerNoJutsu | 2382 | 81 | 0,09 | **5** | 3 | 1 | bavard ET liant |
| Taki_Gano | 941 | 27 | 0,06 | **5** | 3 | 1 | |
| Jubeii | 473 | 22 | 0,01 | **5** | 4 | 0 | aucune pique, jamais |
| zeddo | 876 | 50 | 0,09 | 4 | **4** | 1 | l'équilibré |
| rhae___ | 50 | 6 | 0,00 | 4 | **5** | 0 | parle peu, relie tout le monde |

Huit personnes, six profils distincts. C'est le test qui compte : une formule qui rendrait le même
5/3/1 à tout le monde ne mesurerait rien.

---

## 8. Ce qui reste à calibrer

- **Les médianes du pool bougent** à chaque saison. Elles se recalculent, elles ne se figent pas.
- **Le Piquant ne couvre que 40 personnes** sur 123 : les deux tiers des cartes auront `Piquant 0`
  ou 1. À surveiller — si la stat est morte pour la majorité, il faudra une seconde source
  (réactions déclenchées, interruptions) plutôt que de forcer le curseur.
- **L'exposant 0,5** est un choix mesuré sur huit personnes, pas une loi. À revoir sur les 45.
