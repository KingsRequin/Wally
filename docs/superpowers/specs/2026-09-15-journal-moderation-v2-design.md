# Journal de modération, deuxième passe — design

Date : 2026-09-15 · Statut : validé par l'owner (« fait tout »)

Suite de `2026-09-15-fusion-wally-discord-design.md`. Le journal publie déjà (Components V2,
salons `salon_ids`, serveurs `guild_ids`) : message supprimé / modifié / suppression en masse,
salon vocal temporaire créé / supprimé. Relu sur les vraies cartes de `#logs` le 2026-09-15.

## 1. Les dix améliorations retenues

| # | Amélioration | Tâche |
|---|---|---|
| 5 | Horodatage Discord natif `<t:unix:f>` + relatif `<t:unix:R>` (fuseau du lecteur) | T1 |
| 7 | Id de l'utilisateur en pied, copiable | T1 |
| 6 | Édition : seuls les passages changés mis en évidence | T1 |
| 4 | Messages de bots exclus par défaut (`inclure_bots: false`) | T1 |
| 1 | Qui a supprimé (journal d'audit, par recoupement) | T2 |
| 2 | Ghost ping 👻 + âge du message supprimé | T2 |
| 3 | Salon temporaire : UNE carte, créée puis mise à jour (durée, participants) | T3 |
| 10 | Vocal : entrées, sorties, changements de salon | T3 |
| 8 | Membres : arrivée (âge du compte), départ, ban, déban, expulsion, exclusion temporaire | T4 |
| 9 | Surnoms, rôles ajoutés / retirés | T4 |

## 2. Architecture

- `bot/discord/journal_moderation.py` garde les MESSAGES et devient le tronc commun du journal :
  les deux briques partagées passent publiques (`salons_cibles`, `publier_partout`) plus une
  fabrique d'horodatage `horodatage(dt) -> str` et de pied `pied_utilisateur(user) -> str`.
- `bot/discord/journal_vocal.py` (nouveau) : carte unique des salons temporaires + mouvements vocaux.
- `bot/discord/journal_membres.py` (nouveau) : arrivées, départs, sanctions, surnoms, rôles.
- Événements : `bot/discord/events/moderation.py` reçoit les nouveaux écouteurs. ⚠️ Un seul
  `@bot.event` par nom dans tout `bot/` (vérifier par grep avant d'en poser un) ;
  `on_voice_state_update` reste une MÉTHODE de `WallyDiscord`, on y appelle, on n'enregistre pas.
- Tout ce qui publie : jamais de levée, `{e!r}`, garde-fous existants (`salon_ids` vide → rien,
  guild hors `guild_ids` → rien, salons de logs et leurs fils exclus comme source).

## 3. Détails qui décident

**#1 Qui a supprimé.** Discord ne relie pas une entrée d'audit au message, et ne journalise
JAMAIS la suppression par l'auteur ni par un bot (discord-api-docs #656, #1611). Les entrées
`message_delete` se REGROUPENT : une suppression de plus par le même modo sur le même auteur
dans le même salon incrémente `extra.count` sans nouvel événement. Méthode : à la suppression
d'un message en cache, attendre ~2 s, lire les 10 dernières entrées `message_delete`, retenir
celle dont `target.id == auteur` ET `extra.channel.id == salon` ET (créée il y a < 10 s OU
`extra.count` supérieur au compteur mémorisé pour cette entrée). Compteurs mémorisés en RAM
(perte au reboot = une fausse négative au pire). Trouvé → « **Supprimé par** <@modo> » ; sinon
« **Supprimé par** l'auteur ou un bot (Discord ne le trace pas) ». Hors cache → rien à recouper.
Permission manquante → WARNING une fois par serveur, et la carte part sans la ligne. Le délai ne
retarde que CETTE carte (tâche de fond), jamais les autres événements.

**#2 Ghost ping.** Message supprimé moins de 5 minutes après publication ET qui mentionnait un
utilisateur, un rôle ou @everyone/@here (`raw_mentions`, `raw_role_mentions`, `mention_everyone`)
→ titre `👻 Ghost ping supprimé`, bloc « **Mentionnait** » (mentions rendues, sans ping grâce à
`AllowedMentions.none()`). Âge affiché sur toute suppression en cache : « posté <t:…:R> ».

**#3 Carte vocale unique.** À la création : carte publiée dans chaque salon de logs, et les
couples (salon temporaire, salon de logs, message) rangés en base — nouvelle table
`journal_cartes_vocales` (ids TEXT, clé primaire (salon_temp_id, log_salon_id), `participants`
TEXT JSON, `cree_a` REAL, `createur_id` TEXT). Chaque entrée d'un membre dans le salon temporaire
ajoute son id aux participants (en base : un reboot ne perd rien). À la suppression : chaque carte
est ÉDITÉE (`edit(view=...)`, message déjà V2) → « 🔊 {nom} — créé <t> par <@x>, supprimé <t>,
a vécu {durée}, participants : … ». Message de carte introuvable → nouvelle carte. Lignes
retirées après. Remplace `vocal_cree` / `vocal_supprime`.

**#10 Mouvements vocaux.** Depuis `WallyDiscord.on_voice_state_update` : entrée, sortie,
déplacement (avant → après). Ignorés : changements de mute/sourdine/stream/caméra (même salon),
les bots, le salon créateur (l'aller-retour vers le salon perso serait du bruit : la carte
vocale le couvre). Une fiche courte par mouvement.

**#8 Membres.** Arrivée : âge du compte (`created_at`), badge ⚠️ si compte < 7 jours. Départ :
distinguer expulsion (entrée d'audit `kick` sur ce membre < 10 s) d'un départ volontaire ; durée
de présence (`joined_at`) si connue. Ban / déban : `on_member_ban` / `on_member_unban` + auteur
et raison depuis l'audit (même recoupement court). Exclusion temporaire : `on_member_update`,
`timed_out_until` qui passe de None à une date (ou l'inverse) + auteur/raison via audit
`member_update`.

**#9 Surnoms et rôles.** `on_member_update` : `nick` changé (avant → après) ; rôles ajoutés /
retirés (diff d'ensembles, noms). Auteur via audit si trouvé. ⚠️ Un seul `on_member_update` dans
`bot/` : il porte #8 (exclusion) et #9 ensemble. `on_user_update` (members.py, pseudo de compte)
n'est pas touché.

**#4 Bots.** `JournalModerationConfig.inclure_bots: bool = False`. Vaut pour suppressions,
éditions, suppressions en masse (lignes de bots retirées du compte « auteur : extrait » mais
comptées dans le total), membres bots (arrivée/départ). Wally lui-même compte comme un bot.

**#6 Diff d'édition.** `difflib.SequenceMatcher` sur les MOTS : les passages supprimés en
`~~barré~~`, les ajoutés en `**gras**`, le reste tel quel ; blocs Avant/Après conservés quand
l'édition réécrit plus de la moitié du texte (le diff serait illisible). Markdown du contenu
échappé AVANT de poser les marqueurs. Budget 4000 tenu (tests de pire cas).

## 4. Tests et vérification

Chaque tâche : TDD, tests de comportement sur la vue envoyée (`walk_children()`), pire cas du
budget V2, garde-fous (désactivé, guild hors liste, source = salon de logs, bot exclu), aucune
levée. Recoupement d'audit testé avec une horloge et des entrées factices (nouvelle entrée,
compteur incrémenté, rien trouvé, permission refusée). Prod : cartes relues dans `#logs` après
rebuild (suppression par soi, par un modo si possible, déplacement vocal, salon temporaire).
