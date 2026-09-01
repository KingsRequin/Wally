# Sondage Discord — design (2026-09-01)

Wally sait ouvrir un sondage sur l'overlay du live depuis le 2026-08. Ce
document décrit son jumeau **Discord** : un embed portant une IMAGE du sondage
dessinée à la manière de l'overlay, des réactions `1️⃣ 2️⃣ …` pour voter, et une
image redessinée à chaque vote.

Demande de l'owner, mot pour mot : « si je lui demande de faire un sondage il
mettra un embed avec en images le sondage · il aura une réaction à cet embed
avec 1️⃣, 2️⃣, etc. suivant le nombre de réponses · il se mettra à jour à chaque
vote · dans le cas d'une personne qui vote deux fois, son premier sera annulé
pour mettre le deuxième uniquement · si je lui demande il devrait aussi pouvoir
ping everyone ou poster le sondage dans un autre channel ».

## Arbitrages rendus

| Question | Réponse |
|---|---|
| Lien avec le sondage overlay | **Séparé.** `overlay_narrator._poll` n'est jamais touché : un sondage Discord ne peut pas écraser celui du live. Seul le RENDU est repris. |
| Durée de vie | **Durée si demandée, sinon ouvert.** Avec durée : clôture automatique, image figée avec le gagnant, réactions retirées. Sans : ouvert jusqu'à `action: fermer`. |
| Droits `@everyone` / autre salon | **Ceux qui les ont déjà.** Wally ne ping que si le DEMANDEUR a `mention_everyone` dans le salon visé, et ne poste ailleurs que s'il peut y écrire. Aucune escalade de privilège par procuration. |
| Rendu de l'image | **Pillow, redessiné à chaque vote** (~30 ms), édition groupée à 1,5 s. |

**Écarté : les sondages natifs (`discord.Poll`).** Ils gèrent le vote unique
tout seuls et sont meilleurs sur mobile, mais n'acceptent ni image ni la
présentation de l'overlay — qui est exactement la demande.

## Découpage

### `bot/core/sondage.py` — le moteur, sans Discord

`Sondage` : question, options, `votes: {user_id: index}`, `ends_at` **en temps
mural**, ids du salon et du message. `voter()` remplace le vote précédent et
rend « est-ce que l'état a bougé » — c'est ce booléen qui décide d'un redessin.
`Sondages` indexe par `message_id` et par salon.

⚠️ `ends_at` se range en `time.time()`, jamais en `time.monotonic()` : un
sondage de dix minutes traverse volontiers un rebuild, et un monotonic relu
après redémarrage donne une échéance absurde (piège déjà payé sur l'uptime).

**La source de vérité à la reprise, ce sont les RÉACTIONS**, pas les votes
rangés en base : au boot on relit le message et on recompte à partir de ce que
Discord affiche. Ça répare du même geste les votes tombés pendant la coupure —
un `on_raw_reaction_add` manqué ne laisse aucune autre trace.

### `bot/core/sondage_image.py` — la carte PNG

Reprend `.poll` de l'overlay : carte sombre, question en Fredoka SemiBold,
sablier, options `1. label` (pas d'emoji DANS l'image — l'overlay non plus),
barres arrondies en dégradé `--info → --who-deep`, compte et pourcentage, et à
la clôture le gagnant en `--win` avec les perdants estompés.

⚠️ **Fredoka n'existait qu'en `.woff2`, que Pillow ne sait pas lire.** La police
variable `fredoka.ttf` (OFL, dépôt `google/fonts`) est committée à côté ; repli
DejaVu si elle manque, pour que l'image sorte quand même.

Le dessin part en `asyncio.to_thread` : Pillow est CPU-bound, et la boucle porte
le vocal.

### `bot/tools/sondage_tool.py` — l'outil

`sondage_discord(action: creer|fermer, question, options[], duree_minutes?,
salon?, ping_everyone?)`. Offert sur Discord seulement — le chat du live a déjà
le sondage de l'overlay — donc inscrit dans `_TWITCH_SEULEMENT` avec sa raison.

### `bot/discord/events/reactions.py` — le vote

Wally pose `1️⃣…9️⃣` après l'envoi. À chaque réaction sur un sondage ouvert : si
la personne avait déjà voté ailleurs, **son ancienne réaction est retirée**
(`remove_reaction`, qui exige `Gérer les messages` — le bot l'a sur les trois
serveurs), la nouvelle est comptée, l'image redessinée.

⚠️ Sans cette permission, retirer la réaction d'autrui est IMPOSSIBLE. Repli :
le premier vote fait foi, et le pied de l'embed le dit.

### Cadence

Une édition au plus toutes les 1,5 s par sondage ; les votes arrivés entre-temps
sont fondus dans le prochain redessin. Discord limite les éditions, et une
rafale de votes mettrait sinon le message en file d'attente — l'affichage
retarderait de plusieurs secondes sur le vote.

## Vérification

pytest + les six cliquets. Aucun JS touché : pas de `smoke_front`. Puis un vrai
sondage sur « Les Tests », vote et changement d'avis compris.
