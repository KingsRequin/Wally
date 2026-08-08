# Apex Legends : intégration complète — conception

**Date** : 2026-08-08 · **Statut** : validé, pas encore implémenté
**Origine** : le 2026-08-07, sur le chat d'Azraël, « le top 3 avec Ash en BR kills
France PC » n'a trouvé aucune réponse dans nos outils. Wally a enchaîné six appels
(`apex_legends`, trois `web_search`, un `scrape_url`, un `web_search`), saturé la
boucle d'outils, et recraché du markup DSML à l'écran. Le bug d'affichage est
corrigé (`2be2c64`) ; ce document traite la cause en amont : **nous n'exploitons
qu'une fraction de l'API, et rien ne dit à Wally où sont ses limites.**

---

## 0. Deux règles héritées de l'overlay

Elles priment sur tout le reste de ce document (`docs/overlay.md`) :

1. **L'overlay s'adresse aux SPECTATEURS.** Le streamer ne voit pas son overlay
   pendant qu'il joue. Un widget qui lui dirait « regarde ton rang » n'a pas de sens.
2. **Rien hors live.** Aucun widget, aucun sondage de l'API en tâche de fond.

Corollaire trop souvent oublié : un widget se rationne sur `_may_react`, une bulle
sur `_may_speak`. Tester le mauvais des deux fait taire la fonctionnalité en silence.

---

## 1. Ce que l'API donne — inventaire vérifié le 2026-08-08

Sondé avec notre clé réelle, pas d'après la documentation.

| Endpoint | État | Contenu |
|---|---|---|
| `/bridge` | ✅ | Tout le profil joueur — détaillé au §2 |
| `/maprotation?version=2` | ✅ | 4 modes : `battle_royale`, `ranked`, `ltm`, **`wildcard`** |
| `/crafting` | ✅ | 7 lots du replicator, avec rareté |
| `/predator` | ✅ | Seuil pred — **clé `RP` uniquement** |
| `/servers` | ✅ | État par région |
| `/leaderboard` | ❌ | `Unauthorized. You must be whitelisted to use this API.` |
| `/games` | ❌ | `404 — This API key doesn't exist or you are not allowed to access this data.` |
| `/store` | ❌ | `This endpoint is no longer available at this time.` |
| `/news` | ⚠️ | Répond `[]`, avec ou sans `lang` |
| `/nametouid` | ⚠️ | `err origin lookup` là où `/bridge` trouve le même joueur |

Débit : 2 req/s (en-tête `x-current-rate`), aucun quota journalier annoncé.

### Dette constatée dans le code actuel

- `_format_maps` ignore **`wildcard`**, un mode qui tourne aujourd'hui.
- `_format_predator` lit `data["AP"]` (arènes) : **la clé n'existe plus**. La moitié
  du formateur est morte.
- L'action `news` ne peut plus rien renvoyer — elle occupe une place dans
  l'énumération de l'outil et coûte un aller-retour pour rien.
- `_player_stats` n'expose que trois trackers de la légende sélectionnée. Il ignore
  `realtime`, `total`, le niveau, le top %, l'avatar et l'image du rang.

---

## 2. `/bridge`, et le piège qu'il contient

Un seul appel rend : `global` (nom, uid, avatar, plateforme, niveau +
`toNextLevelPercent`, `bans`, `rank`, `arena`), `realtime`, `legends`
(`selected` avec `gameInfo`, `all` pour 29 légendes), `total`.

**Le piège : la forme de `total` dépend du joueur.**

| | KingsRequin | Azrael_ttv |
|---|---|---|
| Kills | `career_kills` | **absent** — `specialEvent_kills`, libellé « BR Kills » |
| Rang mondial par stat | `rank.rankPos` + `topPercent` | absent |
| Top % du ladder | `No game this split` | `ALStopPercent` = 49.46 |

Les trackers dépendent de ce que le joueur a épinglé en jeu, et changent au fil
des saisons.

> **Règle de conception :** ne jamais lire une statistique par une clé supposée.
> On cherche par libellé (`name`), avec une liste de synonymes par notion
> (kills : `Career Kills`, `BR Kills`, `Kills`…), et on rend **ce qu'on a trouvé**.
> Une notion absente est annoncée absente ; elle n'est jamais remplacée par 0 —
> « Azraël : 0 kill » serait un mensonge, pas une valeur par défaut.

Idem pour le classement : `ALStopPercent` et `rank.rankPos` valent parfois une
chaîne (`"No game this split"`) là où on attend un nombre.

---

## 3. Architecture

`bot/core/apex_api.py` (275 l.) devient `bot/core/apex/`. Motif : chaque unité doit
tenir dans une tête, et **on n'ajoute pas huit branches Apex au `show_widget` de
`overlay_narrator.py`**, déjà à 1840 lignes.

| Unité | Responsabilité | Dépend de |
|---|---|---|
| `apex/client.py` | HTTP, limite de débit, cache par endpoint. Seul point qui parle au réseau. | httpx |
| `apex/reader.py` | Lit une réponse `/bridge` et en extrait des notions nommées, malgré les variations du §2. | rien |
| `apex/service.py` | Les actions offertes au LLM, rendues en texte. | client, reader |
| `apex/widgets.py` | Construit la charge utile des widgets depuis la donnée brute. | client, reader |
| `apex/watcher.py` | Sondage passif pendant le live + instantanés de progression. | client, reader |
| `static/overlay_apex.js` | Les rendus, enregistrés dans la table `BUILDERS`. | — |

**Durées de cache** (le même chiffre demandé deux fois en dix secondes ne vaut pas
deux appels) : rotation 60 s, replicator 1 h, predator 5 min, serveurs 5 min,
joueur 60 s.

`reader.py` isolé du réseau est ce qui rend le §2 testable : on lui donne les deux
réponses réelles capturées et on vérifie qu'il rend les mêmes notions pour deux
joueurs de forme différente.

---

## 4. Les capacités

Chaque donnée est accessible **par l'outil** (Wally la dit, sur Discord comme sur
Twitch) et **par un widget** (Wally l'affiche, pendant le live uniquement).

| Notion | Ce que Wally peut dire | Widget |
|---|---|---|
| Rang | division, RP, top % du ladder, position | `apex_rank` — avec l'image officielle du rang |
| Temps réel | « il est en partie, sur Fuse » | `apex_status` |
| Statistiques | kills / victoires / réanimations, et le rang mondial quand il existe | `apex_stats` |
| Comparaison | deux joueurs sur une notion | `versus` existant, **alimenté par le serveur** |
| Profil | niveau, progression, avatar, ban éventuel | `apex_profile` |
| Légende jouée | skin et sa rareté, pose, badges | `apex_legend` |
| Progression du live | « +14 kills, +2 victoires ce soir » | `apex_session` |
| Rotation | carte actuelle et suivante, minuteur qui décompte, 4 modes | `apex_map` |
| Replicator | lots du jour + rareté | `apex_craft` |
| Predator | seuil par plateforme | `apex_predator` |
| Serveurs | état par région | `apex_servers` |

**Le serveur rend la donnée, Wally ne la recopie pas.** C'est le changement de
fond : aujourd'hui `stats` reçoit des lignes déjà rédigées par le modèle, qui peut
donc se tromper en recopiant. Désormais il choisit *quoi* montrer et *quoi en
dire* ; les chiffres ne transitent plus par lui.

Contrainte de rendu : **560 × 460 px**. Chaque widget doit tenir dedans sans
rogner — un tableau de 29 légendes n'y entre pas, et n'a rien à y faire.

---

## 5. Les comptes Apex

Aucun fait en base ne relie qui que ce soit à un compte Apex. Ce qui marche
aujourd'hui pour « les kills d'azra » est une **devinette** : le modèle essaie le
pseudo Twitch, qui se trouve être le bon. Pour `xeforce_`, dont le pseudo Apex
diffère, la même devinette a produit trois échecs de suite le 2026-08-07.

**Table `apex_accounts`** : `platform` + `platform_user_id` → `apex_name`,
`apex_platform` (`PC` / `PS4` / `X1`), `uid`, `linked_at`.

- Le compte du streamer est déclaré en config (`apex.streamer_account`) : la
  perception passive doit fonctionner dès le démarrage, sans attendre que
  quelqu'un en parle. Valeur : `Azrael_ttv` / `PC` (uid `2274044345`, vérifié).
- Pour tout le monde : l'outil `apex_legends` gagne un paramètre `remember_for`,
  que le modèle remplit avec l'identité de la personne **quand elle déclare son
  propre compte** (« mon pseudo Apex c'est X »). L'association n'est écrite que si
  la recherche aboutit — on n'enregistre pas un pseudo introuvable. Nul ne peut
  ainsi déclarer le compte d'un autre. La fois suivante, « wally mes stats » suffit.
- La casse est ignorée (`Azrael_ttv` = `Azrael_TTV`).
- On enregistre l'`uid` en même temps que le pseudo : un joueur peut changer de
  pseudo, l'uid non.

---

## 6. Perception passive pendant le live

Patron `stream_feed` : **voie sans retour vers l'action**. Le watcher sonde le
compte du streamer toutes les 90 s pendant le live, et alimente un bloc de prompt
(« Azraël est en partie, sur Fuse — Or 3, 6422 RP »). Il n'appelle jamais
`notify_activity` / `notify_event` : il ne réveille aucune cadence et ne déclenche
aucune prise de parole. Wally *sait* ; il n'en parle que si on l'y amène.

Hors live : aucun sondage. Le watcher démarre sur le passage à `stream_live` et
s'arrête à la fin.

**Instantanés de progression.** Au premier sondage du live, on enregistre les
compteurs. Chaque sondage suivant en donne la différence : c'est notre réponse à
`/games`, qui nous est fermé. Table `apex_snapshots` (`taken_at`, `uid`,
`stats_json`), purgée au-delà de 30 jours. La progression se lit **sur le live en
cours** ; on ne construit pas d'historique long terme (arbitré : usage à prouver).

---

## 7. Le garde anti-cascade

C'est la leçon du 2026-08-07 : privé de réponse, le modèle a cherché ailleurs
jusqu'à saturer la boucle d'outils.

Toute demande hors du périmètre de l'API (top 500 mondial, classement par légende
et par pays, historique de matchs, boutique) reçoit une réponse **explicite et
terminale** :

> « Le classement mondial n'est pas accessible via l'API (accès non autorisé). Ce
> que je peux donner : la position et le top % de ce joueur. Ne cherche pas
> ailleurs. »

Deux effets : Wally répond au lieu de bricoler, et il ne part pas en cascade de
`web_search` / `scrape_url`. Ce que l'on peut offrir à la place — la position
personnelle du joueur (`rank.rankPos`, `ALStopPercent`) — est nommé dans la même
phrase, pour que le modèle ait une porte de sortie utile.

---

## 8. Hors périmètre

- **Le top 500 mondial** — `/leaderboard` demande une whitelist. Redemandable
  auprès de l'éditeur, hors de ce chantier.
- **L'historique des matchs** — `/games` interdit à notre clé. Compensé par le §6.
- **La boutique** — endpoint supprimé chez l'éditeur.
- **Les nouvelles Apex** — l'action `news` est retirée : elle ne renvoie plus rien.
  Le flux RSS Dexerto Apex, déjà en place, couvre le besoin.
- **Affichage automatique** — Wally n'affiche jamais un widget Apex de lui-même
  (arbitré). Il perçoit, il attend qu'on demande.
- **Le classement écarté le 2026-08-06** visait un classement de *viewers*. Le rang
  Apex d'un joueur n'entre pas en conflit (confirmé par l'owner le 2026-08-08).

---

## 9. Tests

- `reader.py` sur les **deux réponses réelles capturées** (KingsRequin et
  Azrael_ttv, formes différentes) : les mêmes notions doivent sortir des deux.
- Une notion absente est rendue absente, jamais `0`.
- `ALStopPercent` en chaîne (`"No game this split"`) ne fait pas planter le rendu.
- `wildcard` apparaît dans la rotation ; `predator` ne cherche plus les arènes.
- Le cache : deux demandes rapprochées = un seul appel réseau.
- Le garde anti-cascade : une demande de classement mondial rend le refus explicite
  et n'ouvre aucun autre outil.
- Le watcher ne sonde pas hors live, et n'appelle jamais `notify_*`.
- Les widgets passent par `_may_react`, jamais `_may_speak`.
- Chaque widget se construit sans que le modèle ait fourni le moindre chiffre.

---

## 10. Découpage

Cinq fichiers au plus par phase, vérification à chaque fin de phase.

| Phase | Contenu | Livre |
|---|---|---|
| **1** | Paquet `apex/` : client + cache, `reader`, service enrichi, corrections `wildcard` / `predator` / retrait `news`, fixtures réelles | Wally répond juste et complet, sur les deux plateformes |
| **2** | Table `apex_accounts`, mémorisation des comptes, garde anti-cascade | Plus de « t'es sur PC ou console ? » à répétition |
| **3** | `apex/widgets.py` + `overlay_apex.js` + branchement dans l'outil overlay | Les dix nouveaux widgets à l'écran, plus `versus` réalimenté par le serveur |
| **4** | `apex/watcher.py`, instantanés, bloc de prompt passif | Wally sait ce qui se passe en jeu, et la progression du live |
