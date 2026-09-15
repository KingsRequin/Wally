# Fusion de `wally-discord` dans Wally — design

Date : 2026-09-15 · Statut : proposé

## 0. Pourquoi

`/opt/stacks/wally-discord` (Node, discord.js) et Wally (Python, discord.py) sont **le même
bot** : les deux `.env` portent le token de l'application `1114896051321708544`. Deux sessions
gateway pour une identité, deux codes, deux configurations.

Constaté le 2026-09-15 :

- Le Node plantait en boucle (38 redémarrages) sur des `503` de la gateway Discord : une erreur
  émise sans écouteur dans `@discordjs/ws` tue le process (discord.js #10389, #9103). Wally, sur
  la même gateway au même moment, n'a rien perdu.
- À chaque démarrage, `ready.js` faisait `client.application.commands.set([])` : il **effaçait
  les slash commands globales de Wally**. Retiré le jour même (patch transitoire, avec la montée
  en discord.js 14.27), le Node restant en service jusqu'à la fin de la fusion.

## 1. Périmètre

Porté (les quatre fonctions réellement vivantes) :

| # | Fonction | Source Node |
|---|---|---|
| 1 | Salons vocaux temporaires | `events/voiceStateUpdate.js`, `ready.js` (ménage), `utils/database.js` |
| 2 | Journal de modération (supprimé / modifié / vocal créé-supprimé) | `events/messageDelete.js`, `messageUpdate.js`, `utils/discordLogger.js` |
| 3 | Salon de statut du stream renommé | `ready.js` (`checkStreamStatus`) |
| 4 | Embed de bienvenue (message + GIF + fact traduite) | `events/guildMemberAdd.js` |

Non porté, parce que mort ou nuisible — vérifié dans le code, pas supposé :

- Votes 🔥 (`vote.js`) : la génération d'images qu'ils comptaient n'existe plus côté Node.
- Épinglage hebdomadaire du clip (`twitchClips.js`) : `setInterval` de 7 jours sur un process
  qui redémarre — n'a jamais pu tirer. Wally republie déjà les clips (`clips_channel_id`).
- Reset quotidien du salon `1267122210166935563` (`specialChannelManager.js`) :
  `updateActivity()` n'est appelé nulle part, la purge ne se déclenche jamais. ⚠️ Ce salon est
  le `journal_channel_id` de Wally : ne surtout pas le porter.
- `!memoire`, `!channels`, `!twitch` : mémoire JSON parallèle ; Wally a la sienne.
- Rapport de démarrage, révocation des slash commands.

## 2. Architecture

Quatre modules dans `bot/discord/`, un par fonction. Chacun est un ensemble de fonctions
`async` prenant `bot` en premier argument — la forme de `edits.py` et `members.py` — testables
sans gateway.

### 2.1 `bot/discord/salons_temporaires.py`

- `async def sur_changement_vocal(bot, member, before, after)` :
  - `after.channel.id == salon_createur_id` et `before.channel` différent → crée un salon vocal
    dans la **catégorie du salon créateur**, nom tiré de `noms`, overwrite `manage_channels` +
    `manage_roles` pour le membre, l'enregistre en base, déplace le membre.
  - `before.channel` quitté, non créateur, désormais vide, **et présent en base** → supprime le
    salon et la ligne.
- `async def menage_au_boot(bot)` : pour chaque ligne en base, salon introuvable ou vide →
  suppression (salon + ligne). Appelé une fois après `on_ready`.
- Branchement : **en tête** de `WallyDiscord.on_voice_state_update` (`bot/discord/bot.py`),
  AVANT le `return` « voice_service non connecté ». ⚠️ Un `@bot.event on_voice_state_update`
  dans `events/` REMPLACERAIT la méthode de classe et casserait l'accueil vocal : on appelle,
  on n'enregistre pas.
- Ignorer les bots ; un échec ne remonte jamais (log `{e!r}`, on continue).
- `10003 Unknown Channel` à la suppression = déjà supprimé : on retire la ligne, log INFO.

**Stockage** : table `salons_vocaux_temporaires (channel_id TEXT PRIMARY KEY, guild_id TEXT NOT
NULL, created_at REAL NOT NULL)` dans `bot/db/database.py`, trois helpers dans un mixin
`bot/db/mixins/salons.py` (ajouter, retirer, lister). Pas de `est_gere()` séparé : la lecture de
la ligne sert de test. Reprise : le `voice_channels.json` du Node (1 salon au 2026-09-15) est
importé une fois par le ménage de coupure (§4), pas par un script permanent.

### 2.2 `bot/discord/journal_moderation.py`

- `async def publier(bot, *, titre, couleur, champs, pied=None)` : embed dans
  `journal_moderation.salon_id`. Mentions désactivées (`AllowedMentions.none()`), champs tronqués
  à 1024, `@` échappés. Salon introuvable → WARNING à chaque tentative (c'est une panne de config, elle doit se voir ;
  le volume est celui des suppressions, faible).
- Suppression : nouvel écouteur `on_raw_message_delete` dans `bot/discord/events/moderation.py`
  (message en cache → auteur, contenu, pièces jointes ; sinon « contenu non disponible » comme
  le Node). Les messages de bots sont journalisés aussi, comme dans le Node : une suppression
  de message de bot est justement un geste de modération.
- Modification : appel depuis `on_message_edit` de `events/edits.py`, **placé avant** le filtre
  `ignored_guilds` (le journal de modération couvre la communauté même là où Wally ne perçoit
  pas) et après le filtre « contenu inchangé » (les embeds de lien).
- Vocal créé / supprimé : appelé par `salons_temporaires`.
- Portée : uniquement les serveurs listés dans `journal_moderation.guild_ids` (le Node limitait
  aux guilds `features.*`) — sinon Wally journaliserait les suppressions de serveurs tiers.

### 2.3 `bot/discord/statut_stream.py`

- `def sur_releve(bot, statut: dict)` : synchrone, planifie `_renommer(bot, live)` si le nom
  courant diffère du nom voulu. Aucun appel réseau quand le nom est déjà bon.
- Branché sur `on_poll` du `StreamWatcher` (`bot/main.py`), à côté de l'écriture de
  `_stream_info`. **Pas `on_transition`** : le premier relevé y est volontairement muet, et le
  salon doit être juste dès le boot. Pas de second polling Twitch.
- `statut.get("unknown")` n'arrive jamais ici (filtré par le watcher) : rien à gérer.
- Rate limit Discord (2 renommages / 10 min par salon) : ne compte qu'aux bascules réelles ;
  un 429 est logué, le relevé suivant (60 s) retente.

### 2.4 `bot/discord/bienvenue.py`

- `async def accueillir(bot, member)` : embed « BIENVENUE A {username} », titre tiré de
  `messages`, GIF tiré de `gifs`, fact `uselessfacts.jsph.pl` + traduction `mymemory`
  (`httpx`, timeout 5 s chacun, repli « Impossible de récupérer une fact. » /
  « Traduction indisponible. »). Couleur `#1ad5b6`, pied « Le Purgatoire ».
- Salon : `bienvenue.salon_id`, sinon `guild.system_channel`. Uniquement les `guild_ids` listés.
- Branché dans `on_member_join` (`events/members.py`), à côté de `_member_join_context`.
- `note_act("a posté l'embed de bienvenue de {pseudo} dans #{salon}")` (`self_trace`) : sans
  quoi la cognition, qui perçoit l'arrivée, accueillerait une seconde fois en croyant être la
  première.
- La fact est du contenu externe, mais elle part dans un embed, pas dans un prompt :
  pas de `wrap_untrusted`. Si un jour elle entre dans un prompt, elle y passe.

## 3. Configuration

Sous `discord:` dans `config.yaml`, trois dataclasses imbriquées dans `DiscordConfig`,
construites par `Config.load()` comme `spam_detection`. Chaque champ a son lecteur ci-dessus.
**Pas d'écran dashboard** (non demandé ; règle « du consommateur vers l'UI »).

```yaml
discord:
  salons_temporaires:
    salon_createur_id: 1105088949887696988   # None → désactivé
    noms: [...]                               # 199 noms repris du Node
  journal_moderation:
    salon_id: 1416714887849185340             # None → désactivé
    guild_ids: [875421531415666698]
  statut_stream:
    salon_id: 875443145813417984              # None → désactivé
    nom_live: "🟢𝗲𝗻-𝘀𝘁𝗿𝗲𝗮𝗺"
    nom_hors_live: "🔴𝗵𝗼𝗿𝘀-𝘀𝘁𝗿𝗲𝗮𝗺"
  bienvenue:
    salon_id: 875421532351000627              # None → system_channel
    guild_ids: [875421531415666698]
    messages: [...]                           # repris du Node
    gifs: [...]                               # repris du Node
```

⚠️ `clé: null` en YAML : tester `is None`, pas `.get(clé, défaut)`.

## 4. Coupure de `wally-discord`

Phase finale, uniquement quand les quatre fonctions sont **vues en prod** (§6) :

1. `docker compose stop` du Node **avant** le rebuild de Wally qui active les salons temporaires
   — sinon deux bots créent chacun un salon pour la même entrée.
2. Importer les lignes de `data/voice_channels.json` dans la table (commande ponctuelle
   documentée dans le commit, pas de script gardé).
3. Rebuild + push Wally, vérification §6.
4. `docker compose down` du Node ; le dossier est archivé (`/opt/stacks/_archives/`), pas
   supprimé. `CLAUDE.md` de CT100 et la mémoire mis à jour (16 → 15 containers).

## 5. Erreurs

Tout handler : `try/except Exception` + `logger.warning("… {e!r}")`, jamais de crash, jamais
d'`except` muet. Un `discord.Forbidden` (permission manquante) est logué en WARNING avec le salon
et la permission visée : c'est la panne la plus probable après la coupure du Node, le rôle du
bot étant le même, mais à vérifier.

## 6. Tests et vérification

Tests (`tests/discord/`), bots et salons factices, sans gateway :

- salons temporaires : création dans la bonne catégorie + enregistrement + déplacement ;
  suppression seulement si vide ET en base ; salon non géré vide jamais supprimé ; `10003` retire
  la ligne ; ménage au boot ; **l'accueil vocal de `on_voice_state_update` est toujours appelé**
  (enchaînement réel, pas le module isolé).
- journal : troncature 1024, `@` échappés, mentions coupées, guild hors liste ignorée, édition
  d'un embed de lien ignorée, édition journalisée même dans une guild `ignored_guilds`.
- statut : aucun appel si le nom est déjà bon ; renommage à la bascule.
- bienvenue : replis fact/traduction sur timeout ; `note_act` appelé ; guild hors liste ignorée.
- config : `tests/test_config_sans_bouton_mort.py` passe (chaque champ a un lecteur).

Vérification en prod avant de déclarer fini : entrer dans le salon créateur, en sortir ;
supprimer et modifier un message test ; lire le nom du salon statut ; logs d'une vraie arrivée
de membre (ou d'un test `on_member_join` simulé si aucune arrivée).

## 7. Phases

| Phase | Contenu | Fichiers |
|---|---|---|
| 1 | Salons temporaires : config + table/mixin + module + branchement | 8 (dont 3 de colle) |
| 2 | Journal de modération + `events/moderation.py` + appels dans `edits.py` et `salons_temporaires.py` | 7 |
| 3 | Statut du stream + `main.py` | 5 |
| 4 | Bienvenue + `members.py` | 5 |
| 5 | Coupure §4 + doc | config + docs |

Un champ de config ne peut pas précéder son lecteur (`tests/test_config_sans_bouton_mort.py`) :
la config de chaque fonction arrive donc avec elle, pas dans une phase à part. Le plafond de
5 fichiers est dépassé en phases 1 et 2 par les fichiers de colle (`config.yaml`,
`config.example.yaml`, `__init__.py`). Les tests ne comptent pas.

La phase 1 n'est **pas activée en prod** avant la coupure : `salon_createur_id` reste `null`
dans `config.yaml` tant que le Node tourne (double création), et prend sa valeur au moment du §4.
Les phases 2 et 3 non plus, pour la même raison (doubles embeds) : chaque bloc est livré
désactivé, testé, puis les quatre sont allumés ensemble à la coupure.
