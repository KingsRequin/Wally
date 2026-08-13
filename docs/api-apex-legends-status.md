# API Apex Legends Status — ce qu'elle donne, ce qu'elle ment, ce qu'elle refuse

Référence de `api.mozambiquehe.re`, la source de toutes les données Apex de Wally.

Tout ce qui suit a été **mesuré à notre clé**, pas lu dans une doc : le 2026-08-08 pour
la forme des données, le 2026-08-13 pour le débit et le comportement en partie réelle
(trois parties observées à 2 s, journal `/tmp/duel_probe_2026-08-13.jsonl`, sonde
`scripts/probe_duel.py`).

Le client du projet est `bot/core/apex/client.py` (un seul objet parle au réseau), le
lecteur sans réseau est `bot/core/apex/reader.py`.

---

## 1. Accès

| | |
|---|---|
| Base | `https://api.mozambiquehe.re` |
| Auth | en-tête `Authorization: <clé>` — **pas** `Bearer` |
| Clé | `APEX_API_KEY` dans `.env` |
| Débit | **5 requêtes/seconde** |
| Latence | **~1,0 s par requête**, stable |
| Quota mensuel | aucun constaté |
| Cache CDN | aucun — `cf-cache-status: DYNAMIC`, chaque appel touche l'origine |

**Le plafond de débit n'est annoncé nulle part** : aucun en-tête `x-max-rate` n'existe,
seul `x-current-rate` est renvoyé (compteur de la seconde en cours, remis à zéro chaque
seconde). La limite ne se lit que dans le **corps** du 429 :

```
{"Error":"Slow down ! You're being throttled. You have 5 req/s allowed, but you're current…"}
```

Mesuré par montée progressive : 3 et 5 req/s passent intégralement, à 8 req/s la 6ᵉ
requête de la seconde est refusée.

> ⚠️ `client.py:36` affirme « L'API tolère 2 requêtes/seconde » et en tire
> `_MIN_INTERVAL = 0.5`. **C'est faux** : 60 % du débit disponible est inutilisé, pour
> tout le projet. `watcher.py:34` disait juste. Correctif prévu au lot 0 de la spec du
> duel.

**Les requêtes en `urllib` sont bloquées par Cloudflare (erreur 1010)** là où `httpx`
passe.

---

## 2. Endpoints

### `/bridge` — le profil d'un joueur

Le seul endpoint qui compte vraiment. Deux façons d'identifier un joueur, **`platform`
étant obligatoire dans les deux cas** :

```
/bridge?player=<pseudo>&platform=PC
/bridge?uid=<uid>&platform=PC
```

Sans `platform`, même avec un `uid` valide : `Bad Request. Missing at least one of the
following parameters: player or uid, platform, auth`.

Plateformes : `PC`, `PS4`, `X1`, `SWITCH`.

**La recherche par pseudo rate des comptes bien réels** — voir §4.

Structure de la réponse :

```
global      → name, tag, uid, avatar, platform, level, toNextLevelPercent,
              internalUpdateCount, bans{isActive, remainingSeconds, last_banReason},
              rank{…}, arena{…}, battlepass{level, history}
realtime    → lobbyState, isOnline, isInGame, canJoin, partyFull,
              selectedLegend, currentState, currentStateSinceTimestamp,
              currentStateAsText
legends
  .selected → LegendName, data[], gameInfo{skin, frame, pose, intro, badges[]},
              ImgAssets{icon, banner}
  .all      → { "<Légende>": {data[], gameInfo, ImgAssets}, …, "Global": {…} }
total       → { "<clé_tracker>": {name, value}, … }
```

Deux formes distinctes, et c'est une source d'erreur constante :

```python
total["specialEvent_kills"]  = {"name": "BR Kills", "value": 93129}          # DICT, 2 champs

legends.all.Fuse.data        = [                                            # LISTE
  {"name": "BR Kills", "value": 83761, "key": "specialEvent_kills",
   "rank":                 {"rankPos": 3, "topPercent": 0.01},
   "rankPlatformSpecific": {"rankPos": 2, "topPercent": 0.01}},
  …
]
```

**`total` ne porte AUCUN rang** — juste `name` et `value`. Les classements n'existent
que dans les blocs par légende, où chaque tracker porte son `rank` (mondial) et son
`rankPlatformSpecific` (restreint à la plateforme).

Ne traiter que la forme dict rend les stats par légende vides **en silence**.

### `/maprotation?version=2` — cartes et modes en cours

Trois blocs, chacun avec `current` et `next` :

| Bloc | Contenu |
|---|---|
| `battle_royale` | carte publique, rotation de 90 min |
| `ranked` | carte classée, rotation de 270 min |
| `ltm` | mode temporaire — porte en plus **`eventName`** (« Control », « Gun Game »…) et `isActive` |

Champs utiles : `map`, `code`, `start` / `end` (epoch), `readableDate_start` / `_end`,
`DurationInSecs` / `InMinutes`, `remainingSecs` / `remainingMins` / `remainingTimer`
(`"01:05:55"`), `asset` (image).

`remainingTimer` est déjà formaté — inutile de le recalculer.

### `/crafting` — lots du replicator

Une **LISTE** de lots : `bundle`, `bundleType` (`weekly`, `daily`…), `start` / `end`,
`startDate` / `endDate`, `bundleContent[]` de `{item, cost, itemType}`.

### `/servers` — état des services

Dict à deux niveaux : `<service>.<région>.{Status, HTTPCode, ResponseTime,
QueryTimestamp}`. Services observés : `Origin_login`, `EA_novafusion`, `EA_accounts`,
etc. Régions : `EU-West`, `EU-East`, `US-West`, `US-Central`, `US-East`,
`SouthAmerica`, `Asia`. `Status` vaut `UP` ou non.

### `/predator` — seuil du rang Prédateur

`RP.<plateforme>.{foundRank, val, uid, updateTimestamp, totalMastersAndPreds}`.
`val` est le RP nécessaire pour entrer dans le top 750. `foundRank: -1` et `uid: "-1"`
signalent une plateforme sans données (X1, SWITCH au moment de la mesure).

### `/nametouid` — inutilisable

Répond systématiquement *« Your request has been declined because of server load issue,
Origin refusing the connection or a wrong username »*, y compris sur des comptes
parfaitement lisibles par `/bridge`. Il tape dans le même index cassé que la recherche
par pseudo. **Ne pas s'en servir.**

### Endpoints fermés à notre clé

Revérifiés le 2026-08-13, réponses exactes :

| Endpoint | Réponse |
|---|---|
| `/leaderboard` | `Unauthorized. You must be whitelisted to use this API.` |
| `/games` | `This API key doesn't exist or you are not allowed to access this data.` — **il n'existe donc aucun historique de matchs** |

Le message de `/games` parle d'une clé inexistante alors que la même clé sert `/bridge`
sans problème : c'est un refus de droits déguisé en erreur d'authentification. Ne pas
partir en chasse d'un problème de clé.

L'absence de `/games` est structurante : toute notion de « ce qui s'est passé dans une
partie » ne peut être qu'une **différence entre deux relevés** de compteurs cumulés.
C'est ce que fait `watcher.py` pour la progression du live, et la spec du duel.

---

## 3. Les trackers — la partie piégeuse

Un « tracker » est un compteur que le joueur **épingle sur sa bannière en jeu**. Tout ce
que l'API sait de ses statistiques en découle, et c'est la source de la quasi-totalité
des erreurs possibles.

### 3.1 Les clés ne sont pas les mêmes d'un joueur à l'autre

Les kills de KingsRequin sont dans `career_kills` (« Career Kills »), ceux d'Azraël dans
`specialEvent_kills` (« BR Kills »). Ça change aussi au fil des saisons.

→ **Chercher une NOTION par ses libellés connus, jamais par une clé supposée.** Ce qu'on
ne trouve pas reste introuvé : « 0 kill » serait un mensonge, pas une valeur par défaut.

### 3.2 Plusieurs trackers portent le même libellé et s'ADDITIONNENT

Azraël a « BR Kills » deux fois dans `total` : `specialEvent_kills` = 92 182 et
`kills` = 10 142. Leur somme vaut exactement la somme de ses « BR Kills » par légende.
Garder le premier (un `setdefault`) amputait le total de 10 %.

**Vaut pour un TOTAL CARRIÈRE uniquement** — voir 3.4 pour l'inverse.

### 3.3 🚨 Un tracker non épinglé porte une valeur GELÉE

Mesuré le 2026-08-13. `total.career_kills` affichait `10989` pour KingsRequin. À la
seconde où il a remis ce tracker sur sa bannière, la valeur est passée à **`18782`**
(+7793) — sans qu'un seul kill soit joué, et **sans que la liste des clés change**.

**Une clé présente ne prouve donc pas une valeur à jour.** Un tracker retiré garde la
valeur qu'il avait au moment du retrait, et rien dans le payload ne distingue un
compteur vivant d'un compteur mort.

Conséquence directe : Wally peut annoncer aujourd'hui, avec aplomb, les statistiques
périmées de n'importe quel joueur ayant changé de bannière. Le seul test valable est
qu'un compteur **bouge**.

### 3.4 🚨 Pour un DELTA, tous les trackers bougent du même montant

Mesuré sur deux parties réelles : 4 kills → `+4` sur `career_kills`, sur
`specialEvent_kills`, **et** sur leurs équivalents par légende. Idem avec 2 kills → `+4`
partout devient `+2` partout.

**Les sommer donnerait 16 kills au lieu de 4.** C'est le piège exactement symétrique de
3.2 : la règle d'addition vaut pour un total carrière, **jamais** pour une différence
entre deux relevés.

→ Pour un delta : prendre le **maximum**, jamais la somme. Et suivre **tous** les
trackers, puisqu'on ignore lequel le joueur a épinglé (3.3).

### 3.5 Les stats par légende existent, le classement non

`legends.all.<Légende>.data` donne les chiffres d'un joueur avec une légende, rang
mondial compris (Azraël : 83 115 kills et 3ᵉ mondial avec Fuse). Ce que l'API refuse,
c'est le **tableau** de classement (`/leaderboard`), pas les chiffres d'un joueur.

Une légende non épinglée est **absente** du bloc — « 0 kill avec Fuse » serait un
mensonge.

### 3.6 Un rang est TOUJOURS relatif à sa légende

Les mêmes libellés existent sous chaque légende mais n'y comptent pas la même chose :
« BR Kills » sous Fuse classe les kills faits *avec Fuse* (Azraël : 83 761 kills, **3ᵉ
mondial**, 2ᵉ sur PC). Confondre ce rang avec le total carrière annonçait « Azraël,
92 182 kills, 3ᵉ mondial » au lieu de « pas de rang » — faux d'un facteur mille.

Le rang carrière, lui, se lirait dans `legends.all.Global`. **Mais ce bloc peut être
vide** : le 2026-08-13, `Global` d'Azraël ne contient qu'`ImgAssets`, avec `data: null`.
Il n'a donc **aucun rang mondial carrière** exploitable ce jour-là, alors que ses rangs
par légende sont bien là. Un `Global` présent ne garantit pas un `data` — vérifier les
deux.

Chaque tracker porte deux classements : `rank` (mondial) et `rankPlatformSpecific`
(restreint à la plateforme), tous deux en `{rankPos, topPercent}`. Le second est le plus
fin disponible.

**Aucun rang par PAYS n'existe** — vérifié par balayage complet du payload le
2026-08-10, pas d'après la doc.

---

## 4. La recherche par pseudo rate des comptes réels

`/bridge?player=…` délègue à un « low priority search service » qui n'indexe pas tout.
`IBrainroTI67` et `LicorneKssandre` sont introuvables par nom sur les trois plateformes
— y compris depuis le site officiel, et quelle que soit la casse — mais parfaitement
lisibles par `uid`.

**Un « Player not found » ne veut donc PAS dire que le compte n'existe pas.**

Le recours est l'uid, visible à la fin de l'URL du profil sur apexlegendsstatus.com. Si
l'URL n'en contient pas, il faut cliquer sur *« Not the profile you are looking for? Try
deep search »* puis recliquer sur le compte : l'URL devient une adresse `profile/uid/…`.

Un uid est **purement numérique** — le valider avant tout appel réseau. Le projet
mémorise les uid croisés dans `apex_accounts` et dans le registre des profils.

---

## 5. États temps réel

`realtime.currentState` vaut `offline`, `inLobby` ou `inMatch`, avec `isInGame`
cohérent (`0` / `1`). **Fiable** pour détecter le début et la fin d'une partie.

Mesures du 2026-08-13 :

- Une partie BR dure **7 à 8 minutes**.
- L'intervalle entre un retour au lobby et le lancement suivant peut descendre à
  **39 secondes**. Toute logique qui attend après une fin de partie doit rester bien en
  dessous, sous peine de mordre sur la partie suivante.
- **Les compteurs de kills sont à jour au relevé même du retour au lobby**, sans délai —
  vérifié deux fois sur deux. Il n'y a pas de temps de stabilisation à prévoir.
- `currentStateSinceTimestamp` **change en permanence** pendant un même état (toutes les
  ~4 s) : ce n'est pas la date d'entrée dans l'état, et s'en servir comme telle est une
  erreur. Vaut `-1` hors ligne.

### 🚨 Le mode de jeu n'est pas lisible, et tous ne comptent pas

`realtime` ne contient **que** les neuf champs listés au §2. Aucun champ de mode.

Or **la Mixtape n'incrémente aucun tracker de kills** : une partie avec 10 kills
annoncés n'a bougé aucun des neuf compteurs, alors que le **niveau** du compte
progressait (285 → 286). L'API voit la partie ; elle ignore les kills.

Le **Joker** — mode dérivé du BR, et mode de référence de la chaîne, le BR classique
n'étant plus guère joué — compte **normalement**.

Donc : impossible de distinguer une partie de Mixtape d'une partie normale, et le niveau
ne tranche rien (un vrai 0 kill en BR le fait progresser pareil). Toute feature qui
compte des kills doit **avertir en amont**, pas espérer détecter.

`/maprotation` donne bien le LTM en cours via `ltm.eventName`, mais c'est ce qui tourne
**sur le serveur**, pas ce que joue un joueur donné.

---

## 6. Valeurs qui ne sont pas des nombres

L'API glisse des phrases là où on attend des chiffres :

| Champ | Surprise |
|---|---|
| `ALStopPercent`, `ALStopInt`, `…Global` | la chaîne `"No game this split"` |
| `ladderPosPlatform` | `-1` = « non classé » (une absence, pas un rang) |
| `foundRank`, `uid` de `/predator` | `-1` et `"-1"` = plateforme sans données |
| `battlepass.level` | `null` |
| `rank.rankScore` à 0 + `rankName: "Unranked"` | non classé cette saison |

`or {}` ne suffit pas à se protéger d'un type inattendu : **une LISTE est vraie**, elle
traverse le `or` et fait lever le `.get()` suivant. Vérifier `isinstance`.

---

## 7. Où c'est utilisé dans le projet

| Fichier | Rôle |
|---|---|
| `bot/core/apex/client.py` | seul point réseau — débit, cache par endpoint |
| `bot/core/apex/reader.py` | lecture du payload, **sans réseau**, testable sur fixtures |
| `bot/core/apex/watcher.py` | sonde du compte streamer (30 s en live, 60 s sinon) |
| `bot/core/apex/history.py`, `serie.py`, `periode.py`, `chart.py` | progression et courbes |
| `bot/core/apex/service.py`, `tool.py` | service et outil exposé au LLM |
| `bot/core/apex/widgets.py` | rendu overlay |
| `scripts/probe_duel.py` | sonde de mesure jetable (états, trackers, deltas) |

Fixtures de test : `tests/fixtures/apex/`.

TTL de cache par endpoint dans `client.py` : `bridge` 15 s, `maprotation` 60 s,
`predator` et `servers` 300 s, `crafting` 3600 s, défaut 60 s.
