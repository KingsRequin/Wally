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
dossier, plus un — `meme81` aujourd'hui, la série comptant neuf trous (9, 26, 27, 37, 39, 41, 42,
43, 69). Le maximum, pas le premier trou : réutiliser le numéro
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
des fichiers déjà présents, calculées à la volée (81 fichiers, 32 Mo — instantané).

Ce que ça attrape : le repost exact, le double-clic sur le même message, un meme déjà rangé — les
81 existants compris, sans migration. Ce que ça ne voit pas : le même meme ré-encodé ailleurs, en
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

**Elle ne s'affiche jamais.** La description est un contexte interne, écrit pour que Wally commente
juste une image qu'il ne voit pas. L'overlay l'affichait en légende sous le meme : elle doublait à
l'écran ce qu'il allait dire, et exposait aux spectateurs une note qui lui était destinée. Retiré
du narrateur, du rendu et de la feuille de style — le widget ne reçoit plus que `src`.

`VisionService.analyze()` charge aujourd'hui son prompt en dur ; il reçoit un paramètre
`prompt_name` optionnel, sans changement pour les appelants actuels.

**Une seule fois, à l'import.** Le `.txt` n'est pas un cache qu'on pourrait rafraîchir : c'est la
vision du meme, figée au moment où il entre dans la banque. Rien ne rappelle le modèle quand
l'image s'affiche — l'overlay tire, `MemeLibrary` lit le sidecar, et c'est tout. Décrire les 81
memes existants coûterait quatre centimes, une fois ; ensuite le fichier répond gratuitement.

Les fichiers déjà rangés n'étant pas exposés publiquement, le rattrapage les envoie en `data:`
base64 — vérifié sur `meme77.png` : le client l'accepte et rend une description exploitable pour
0,000473 $.

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

## Rattrapage de l'existant

Les mêmes briques, passées en revue sur le dossier : `scripts/rattraper_memes.py`, calqué sur
`convertir_memes_webp.py` — simulation par défaut, `--apply` pour écrire.

Il fait deux choses, et rien d'autre :

1. **Décrire les memes muets.** Cinq n'ont pas de sidecar — `meme77.png`, `meme78.png`,
   `meme79.png`, `meme80.gif`, `meme35.mp4`. Leur description est donc leur nom de fichier :
   « meme80 ». `pick(hint)` cherchant dans les descriptions, ils sont **introuvables** par
   mot-clé ; et quand l'un sort, Wally le commente à l'aveugle. Le `.mp4` reste à l'écart, faute
   d'analyse possible.
2. **Convertir ce qui y gagne.** Quatre fichiers déposés après la conversion du 11 août :

   | fichier | actuel | WebP | |
   |---|---|---|---|
   | meme77.png | 197 Ko | 21 Ko | −89 % |
   | meme78.png | 171 Ko | 19 Ko | −89 % |
   | meme79.png | 343 Ko | 38 Ko | −89 % |
   | meme80.gif | 3 375 Ko | 834 Ko | −75 %, 64 images |

   4,1 Mo → 0,9 Mo. Le GIF est le cas que `LISEZ-MOI.md` décrit — « plusieurs secondes à traverser
   le tunnel, le widget passe avant d'être visible » — et celui où Pillow peut aplatir l'animation
   en silence : la garde doit confirmer les 64 images.

Renommer un fichier casserait le lien avec son sidecar : la conversion réécrit les deux, comme le
fait déjà le script existant.

## État de la banque au démarrage

Aujourd'hui, un meme trop lourd est écarté par `MemeLibrary.list()` avec un log en DEBUG —
invisible en production, où les sinks sont à INFO. Un `.mp4` ne s'affichera jamais sans que rien ne
le dise. Ce sont des silences, exactement ce que le canari de démarrage existe pour rompre.

Une fonction `_verifier_memes()` rejoint `bot/core/canari.py`, au même format que ses voisines :
elle renvoie la liste des anomalies — memes sans description, fichiers au-delà de 8 Mo donc jamais
tirés, vidéos que l'affichage ignore — et le canari les loge. Aucun changement de comportement, un
constat qui cesse d'être muet.

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

**`scripts/rattraper_memes.py`** — nouveau : le passage en revue du dossier, sans logique propre,
il enchaîne les fonctions de `meme_import`.

**`bot/core/canari.py`** — une fonction `_verifier_memes()` de plus, au format des autres.

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

Sur le rattrapage et le canari :
- la simulation n'écrit rien, `--apply` écrit
- un meme déjà décrit n'est pas redécrit — on ne repasse pas la facture ni sur une main humaine
- la conversion réécrit l'image ET son sidecar, jamais l'une sans l'autre
- `_verifier_memes` signale un meme sans description, un fichier au-delà de 8 Mo, une vidéo ; et
  ne dit rien d'un dossier sain

## Hors périmètre

- Retirer ou renommer un meme depuis Discord — le dashboard et le système de fichiers s'en chargent
- Détection perceptuelle de doublons
- Afficher le meme sur l'overlay dans la foulée (tranché : non)
- Toute reprise du rotateur de memes ou de la route publique qui sert les fichiers
