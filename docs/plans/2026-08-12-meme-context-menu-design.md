# Ranger un meme depuis Discord — design

Date : 2026-08-12
État : validé, prêt pour le plan d'implémentation

## Le besoin

Verser une image vue dans un salon Discord directement dans `data/memes/`, sans passer par
un accès fichier : clic droit sur le message → *Applications* → « Ranger ce meme ». Le fichier
rejoint la banque que l'overlay tire au sort, converti en WebP si l'échange est avantageux, avec
un `.txt` de description écrit par Wally.

## Ce qui existe déjà et qu'on réutilise

| Brique | Où | Rôle ici |
|---|---|---|
| `MemeLibrary` | `bot/core/memes.py` | Conventions du dossier : extensions admises, sidecar `.txt`, plafond de 8 Mo |
| Conversion WebP | `scripts/convertir_memes_webp.py` | `_convertir` / `_verifier` — la garde qui a rattrapé 8 GIF aplatis en silence par Pillow |
| `VisionService` | `bot/core/vision.py` | `analyze(image_urls, caption)` — décrit une image via le client OpenAI multimodal |
| Garde SSRF | `bot/core/scrape.py` | `ScrapeService._adresses_publiques(host)` — refuse les cibles internes |
| Dossier bind-monté | `docker-compose.yml` | `./data:/app/data` — un fichier écrit est servi aussitôt, ni rebuild ni redémarrage |

Rien de tout cela n'est réécrit. Le seul remaniement d'existant est l'extraction de la conversion
(voir « Découpage »).

## La commande

Une `app_commands.ContextMenu` de type message, nommée « Ranger ce meme », enregistrée sur l'arbre
de commandes depuis un cog, comme les autres commandes de `bot/discord/commands/`.

Réservée à « Gérer le serveur » (`default_permissions(manage_guild=True)`) : le dossier alimente un
overlay diffusé en direct, un dépôt malvenu sortirait à l'antenne.

## Le flux

Discord impose qu'un formulaire (`send_modal`) soit la **première** réponse à l'interaction, sous
trois secondes, et interdit de faire patienter avant. L'analyse d'une image prend cinq à dix
secondes : un formulaire pré-rempli par l'analyse est donc impossible. D'où le passage par des
boutons.

1. Clic droit → `defer(ephemeral=True)` (la fenêtre passe de 3 s à 15 min)
2. Extraction de l'image (pièce jointe, sinon embed), téléchargement, contrôles
3. Analyse par `VisionService` avec un prompt dédié (voir plus bas)
4. Message éphémère : nom de fichier retenu, description proposée, gain de la conversion s'il y en
   a une — et trois boutons **Ranger** · **Corriger** · **Annuler**
5. « Corriger » ouvre un formulaire pré-rempli de la description ; le nom n'y est pas, il est
   automatique
6. À la validation : écriture de l'image et du `.txt`, puis message **public** dans le salon

Les boutons expirent au bout de 120 s et n'obéissent qu'à celui qui a lancé la commande.

## Nommage

Suite de la numérotation existante : le plus grand `N` trouvé parmi les fichiers `memeN.*` du
dossier, plus un — `meme38` aujourd'hui. Le maximum, pas le premier trou : réutiliser le numéro
d'un meme supprimé le confondrait avec son `.txt` s'il en reste un. Les sidecars comptent dans le
balayage pour cette raison même — `meme12.webp.txt` orphelin réserve le numéro 12.

L'extension est celle retenue après conversion : `meme38.webp`, ou `meme38.jpg` si le WebP
n'apporte rien. Le sidecar prend la forme `meme38.webp.txt` — celle que `_describe` cherche en
premier.

## Conversion WebP

Reprise telle quelle de la logique du script : on tente la conversion, on vérifie le résultat, on
ne garde le WebP que s'il est **plus petit** et que la vérification passe. Un GIF animé dont
l'animation n'a pas survécu est rejeté, l'original est conservé.

Les JPEG ne sont pas convertis : le projet a tranché que l'échange n'en vaut pas la peine, et
`LISEZ-MOI.md` le documente.

## Doublons

Empreinte SHA-256, sans index à maintenir. À l'import on calcule l'empreinte des octets
téléchargés et, si conversion il y a, celle du fichier converti ; on les confronte aux empreintes
des fichiers déjà présents, calculées à la volée (37 fichiers, 28 Mo — instantané).

Ce que ça attrape : le repost exact, le double-clic sur le même message, un meme déjà rangé — les
37 existants compris, sans migration. Ce que ça ne voit pas : le même meme ré-encodé ailleurs, en
autre résolution ou recompressé. Une détection perceptuelle le verrait, au prix d'une dépendance
et de faux positifs entre deux memes du même modèle ; écarté volontairement.

En cas de doublon, rien n'est écrit et un message éphémère nomme le fichier déjà en place.

## Description automatique

`image_analyze_system`, le prompt de vision existant, ne convient pas : il vise le commentaire
factuel d'une image de chat et consacre un bloc entier à l'extraction de statistiques de jeu.

Un prompt dédié, `bot/persona/prompts/meme_describe_system.md`, reprend le registre des sidecars
déjà écrits — format ou modèle du meme, ce qu'on voit, le texte visible entre guillemets, un ou
deux mots de contexte, le tout en une à deux phrases :

> `BD 4 cases : EA offre un tour de montgolfière gratuit, le ballon s'envole, pancarte l'atterrissage est 19.99$. Microtransactions, arnaque, payant.`

Ces descriptions ne servent pas qu'au tirage : elles nourrissent ce que Wally raconte en montrant
le meme. Le dossier `bot/persona/prompts/` est bind-monté, le registre s'édite sans rebuild.

`VisionService.analyze()` charge aujourd'hui son prompt en dur ; il reçoit un paramètre
`prompt_name` optionnel, sans changement pour les appelants actuels.

## Message public

Posté dans le salon du clic droit une fois le fichier écrit : qui a rangé quoi, sous quel nom, la
description retenue, et l'image en aperçu. Un message de service, sobre — pas une prise de parole
de Wally, donc pas d'appel au LLM de conversation.

Il ne remplace pas le message éphémère de l'étape 4, qui est un aperçu avant validation : l'un sert
à décider, l'autre à annoncer. Un import annulé ne laisse donc aucune trace publique.

## Cas limites

| Situation | Réponse |
|---|---|
| Aucune image dans le message | Refus éphémère explicite |
| Plusieurs images | La première ; le message public dit combien ont été laissées |
| Lien Tenor/Klipy sans pièce jointe | On prend l'image de l'embed |
| `.mp4` / `.webm` | Acceptés — le rotateur les joue — mais pas d'analyse visuelle. L'aperçu s'ouvre avec une description vide et invite à la corriger ; « Ranger » reste possible, le nom du fichier servant alors de description comme pour tout dépôt manuel |
| Plus de 8 Mo après conversion | **Refus.** Rangé, le fichier serait ignoré par `MemeLibrary.list()`, dont le rejet est logué en DEBUG donc invisible en production : un meme qui dort sans que rien ne le signale |
| Fichier distant de plus de 16 Mo | Téléchargement interrompu et refus, avant toute tentative de conversion |
| Extension inconnue | Refus, avec la liste des formats admis |
| URL d'embed non publique | Refus via la garde SSRF |
| Écriture impossible (droits, disque) | Refus éphémère avec la cause ; rien de partiel ne subsiste |

## Découpage

**`bot/core/meme_import.py`** — nouveau, sans dépendance à Discord, donc testable seul :
- `prochain_numero(dossier) -> int` — la suite de la numérotation
- `empreintes(dossier) -> dict[str, str]` — SHA-256 des fichiers présents
- `convertir_si_avantageux(octets, suffixe) -> tuple[bytes, str]` — la logique du script, déplacée
- `importer(octets, suffixe, description, dossier) -> ResultatImport` — orchestration, écriture
  de l'image et du sidecar, refus motivés (doublon, trop lourd, format)

**`scripts/convertir_memes_webp.py`** — importe désormais la conversion depuis ce module au lieu
de la porter. Une seule garde anti-perte d'animation, pas deux qui divergeraient.

**`bot/discord/commands/meme_cmd.py`** — nouveau : la commande contextuelle, la vue à boutons, le
formulaire. Enregistré dans `bot/discord/bot.py` avec les autres cogs.

**`bot/core/vision.py`** — un paramètre `prompt_name` sur `analyze()`.

**`bot/persona/prompts/meme_describe_system.md`** — nouveau registre.

**`data/memes/LISEZ-MOI.md`** — une section sur la nouvelle voie d'entrée.

## Tests

Sur `meme_import`, sans réseau ni Discord :
- conversion retenue quand elle fait gagner, écartée sinon
- GIF animé dont l'animation survit, GIF dont elle ne survit pas → original conservé
- sidecar écrit sous `memeN.ext.txt`, contenu exact
- numérotation : suite du maximum, y compris avec un trou dans la série
- doublon détecté avant écriture, sur l'original comme sur le converti ; rien n'est écrit
- refus au-delà de 8 Mo, refus d'une extension inconnue

Sur la commande, Discord simulé :
- un membre sans « Gérer le serveur » ne peut pas l'exécuter
- message sans image → refus, aucun fichier créé
- plusieurs images → la première rangée, le compte des autres annoncé
- la description corrigée au formulaire est bien celle qui finit dans le `.txt`
- « Annuler » n'écrit rien
- le message public part dans le salon d'origine

## Hors périmètre

- Retirer ou renommer un meme depuis Discord — le dashboard et le système de fichiers s'en chargent
- Détection perceptuelle de doublons
- Afficher le meme sur l'overlay dans la foulée (tranché : non)
- Toute reprise du rotateur de memes ou de la route publique qui sert les fichiers
