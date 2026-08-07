# Annuler sur l'overlay · décrire les memes

**2026-08-07** — deux chantiers indépendants, demandés ensemble.

---

## 1. Annuler ce qui est à l'écran

### Le problème

Rien n'était annulable. Seul le chifoumi avait une sortie (`close`). Le bingo,
l'objectif, le pendu et le sondage n'avaient **aucune** façon de se terminer
avant la fin du live : une fois ouverts, ils vivaient jusqu'à `reset_live()`. Et
un meme affiché restait à l'écran jusqu'à l'expiration de son minuteur.

Wally ne savait pas non plus ce qu'il avait à l'écran : aucun état overlay
n'était injecté dans son prompt, il ne l'apprenait qu'au retour de son propre
appel d'outil.

### Ce qui a été fait

**Un outil `cancel_overlay`**, à côté de `show_overlay`, avec `target` requis :

| Cible | Effet |
|---|---|
| `ecran` | Retire ce qui est affiché à l'instant. Ne touche à aucun état. |
| `bingo` `pendu` `sondage` `chifoumi` `objectif` | La partie est abandonnée ; l'écran est nettoyé dans la foulée. |
| `tout` | Les deux. |

`target` est **requis, sans défaut** : « annule » tout court est ambigu, et un
défaut destructeur tuerait un bingo qu'on voulait seulement sortir de l'écran.

**Un abandon n'est pas une clôture.** `cancel()` ne passe pas par `close_poll()`
ni `close_rps()` : ceux-ci dépouillent et annoncent un gagnant, ce qui n'a aucun
sens pour une manche qu'on vient d'interrompre. Les clôtures planifiées
(`_poll_task`, `_rps_task`) sont annulées, sinon leur `sleep` rouvrait le
dépouillement d'un sondage déjà abandonné.

**Insensible au live** — c'est justement quand le stream vient de se couper avec
un bingo resté ouvert qu'il faut pouvoir nettoyer.

**Compte rendu honnête.** `cancel()` retourne la liste de ce qui a réellement
été annulé ; la liste vide est la réponse utile. `run_overlay_cancel_tool` la
traduit en `status: nothing` + « ne prétends pas l'avoir retiré », sur le modèle
de `run_overlay_tool`.

### Deux pièges rencontrés

**Le tampon du feed.** `OverlayFeed.recent()` rejoue les événements encore
vivants à tout client qui se connecte. Nettoyer l'écran sans vider `_buffer`
laissait la reconnexion SSE automatique d'OBS ramener le widget qu'on venait
d'annuler. `clear()` vide donc les deux.

**La file d'attente du navigateur.** `pending` garde les demandes qui n'ont pas
encore eu leur tour. Sans la vider, la suivante surgissait 300 ms après
l'annulation : on annulait un meme, le dé qui patientait prenait sa place.

### Le bloc d'état

`current_state_block()` injecte, pendant un live et seulement s'il y a quelque
chose :

```
--- Sur ton overlay ---
Bingo : 3/9 cases cochées.
Objectif « 50 follows » : 12/50.
```

**Perception passive**, comme `StreamFeed` : aucun `notify_*` derrière, donc ce
bloc ne réveille ni la cadence vive ni une prise de parole. Un bingo ouvert
ferait sinon parler Wally en boucle pendant tout le live.

Le narrateur s'enregistre via `activate()` (même patron que `stream_feed`) —
l'injection de dépendance s'arrête au bot Discord et ne descend pas jusqu'à
`prompts.py`. L'import y est **paresseux** : `overlay_narrator` importe
`load_prompt` de `prompts`, un import en tête de module se mordait la queue.

### Chemins câblés

Discord, Twitch, et **vocal** (`on_voice_request`) — ce dernier étant le plus
utilisé pour « Wally, annule le bingo ». `overlay_voice.md` porte la consigne.

---

## 2. Les descriptions de memes

### Le problème

64 images dans `data/memes/`, aucune description. Wally ne les voit pas : sans
description, il n'avait que le nom du fichier (`meme31.gif` → « meme31 »), donc
aucune prise pour commenter juste ni pour choisir à propos.

### Deux défauts levés au passage

**Collision de sidecar.** `_describe()` cherchait `path.with_suffix(".txt")` :
`meme31.gif` et `meme31.jpg` — deux images différentes — se seraient partagé
`meme31.txt`. Dix paires du dossier étaient dans ce cas. `_describe()` cherche
maintenant `meme31.gif.txt` d'abord, et retombe sur `meme31.txt` : l'ancienne
forme reste valide.

**Sélection « à propos » cassée.** `pick(hint)` retenait tout meme partageant
**au moins un** mot de plus de 2 lettres avec le sujet. Or « qui », « pas »,
« une » passent ce filtre et figurent dans presque toutes les descriptions :
« chat qui hurle » retenait quasi tout le dossier et retombait sur un tirage au
hasard. Le défaut était invisible tant que les descriptions n'étaient que des
noms de fichiers — et il aurait annulé le bénéfice de tout ce chantier. On garde
désormais les memes ayant le **plus** de mots en commun, ce qui règle les mots
vides sans avoir à en maintenir la liste.

### Méthode

Pas de ffmpeg sur CT100, mais PIL. Un script jetable a produit une vignette par
image dans `/tmp` : redimensionnement pour les images fixes, planche verticale
de 3 frames pour les GIF animés — ce qui donne le déroulé de la blague et fait
passer sous la limite de 5 Mo de l'API les 5 GIF qui la dépassaient.

Huit sous-agents en parallèle, 8 memes chacun, ont lu les vignettes et écrit
`data/memes/<nom>.<ext>.txt` : une ligne, ≤ 155 caractères (le code tronque à
160), dense en mots-clés puisque la sélection se fait par sous-chaîne.

64/64 écrits, aucune tronquée, moyenne 149 caractères.

**Limite assumée** : les descriptions rapportent le visible et le texte lu sur
l'image, jamais le contexte communautaire (qui est visé, quel running gag) —
impossible à deviner depuis une image. C'est une base à corriger à la main, ce
que `LISEZ-MOI.md` indique désormais.

`meme35.mp4` est ignoré : l'extension n'est pas gérée par `MemeLibrary`.

---

## Dette signalée, non traitée

`on_voice_request` déclare `shown: list[dict]` (`overlay_narrator.py`), la
peuple, et ne la relit jamais. Code mort préexistant, laissé en place.
