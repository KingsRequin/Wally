# Wally compagnon de stream — Document de conception

**Date :** 2026-08-06
**Statut :** En attente (accord d'Azraël requis pour le volet vocal)
**Salon vocal cible :** `1267757914953875487`

---

## Objectif

Wally accompagne le live d'Azraël : il perçoit ce qui se passe (conversations du vocal Discord,
chat Twitch, événements de la chaîne) et réagit par une **courte bulle de texte** sur un overlay
OBS, à côté d'un avatar animé.

Il ne parle pas à l'oral et n'écrit pas dans le chat Twitch. Sa seule sortie est visuelle.

**Contrainte cardinale :** l'overlay est petit et ne se scrolle pas. Quelques mots, rarement.
Un compagnon bavard est pire que pas de compagnon.

---

## Ce qui existe déjà

Le socle est en place ; l'essentiel du travail est d'assembler, pas de construire.

| Brique | Rôle | Emplacement |
|---|---|---|
| `StreamFeed` | jeu, titre, audience, raids/subs/bits, lignes de chat | `bot/core/stream_feed.py` |
| `StreamWatcher` | bascule live ↔ offline (`on_transition`) | `bot/core/stream_watcher.py` |
| `WallyAudioSink` | capture vocale **par personne** + VAD → PCM 16 kHz | `bot/discord/voice/sink.py` |
| STT | `faster-whisper` local, RTF mesuré **0,05** | `bot/discord/voice/providers.py` |
| `/overlay` | page OBS, fond transparent, **SSE**, avatars émotionnels | `bot/dashboard/static/overlay.html` |
| `SpeakGuard` | filtre adversarial avant tout message spontané | `bot/intelligence/speak_guard.py` |
| `account_linker` | correspondance compte Twitch ↔ membre Discord | `bot/core/account_linker.py` |
| Toggle overlay | masquage en direct depuis l'admin | `/api/public/sse/overlay` |

---

## Déroulé visé

```
Azraël passe en live   → Wally rejoint 1267757914953875487, sans saluer
                       → perçoit : conversations vocales, chat Twitch, événements
                       → bulle courte quand un moment le justifie
Fin du stream          → il quitte
```

---

## Décisions de conception

### 1. Le vocal Discord, pas la capture Twitch

Testé le 2026-08-06 sur une VOD réelle (extrait de 3 min) : le mix jeu + voix compressée donne
une transcription inexploitable (« L'orthographe d'un pannefet », « la chumée couille », « Nasrel »
pour Azraël). Amorcer Whisper avec les pseudos corrige les noms propres, pas le fond.

Le vocal Discord fournit le **micro direct, séparé par personne**, sans son de jeu — et supprime
au passage streamlink, le décodage HLS et la bande passante.

### 2. Le rythme de parole est un mécanisme, pas une consigne

Le risque principal du projet est produit, pas technique. Un prompt qui dit « sois discret » ne
suffira pas : il faut un **budget** qui refuse.

- **Plafond dur** : une bulle toutes les 2 minutes maximum.
- **Jamais deux fois de suite** sans avoir été sollicité entre-temps.
- **Trois niveaux de déclenchement** :

| Niveau | Situations | Comportement |
|---|---|---|
| Franc | on le nomme dans le vocal ; raid, sub, gros cheer | réagit presque toujours |
| Opportuniste | vague de chat, changement de jeu ou de titre, question lancée au vide, long silence rompu | réagit parfois |
| Jamais | rien de neuf, ou il vient déjà de parler | se tait |

### 3. Le chat Twitch : contexte **et** déclencheur

Le chat est le signal le plus fiable de tous — il ne dépend ni de la transcription, ni du son du
jeu. Quand dix personnes tapent « gg » en trois secondes, il s'est passé quelque chose de fort, et
Wally n'a pas besoin de savoir quoi pour réagir juste.

- **En contexte** : de quoi parlent les viewers.
- **En déclencheur** : un pic d'activité soudain = un moment.

`StreamFeed.record_chat()` capte déjà ces lignes ; elles sont simplement retirées du bloc sur le
chemin Twitch home. Il faudra les exposer ici.

### 4. Le format

- **3 à 8 mots.** Une seule idée. Pas de ponctuation lourde, pas d'emoji systématique.
- Chemin de génération **dédié** : les prompts actuels produisent des paragraphes. Ce n'est pas un
  raccourcissement, c'est un autre prompt.
- Affichage proportionnel à la longueur : ~2,5 s pour cinq mots, jamais moins de 2 s.
- Fond semi-opaque et contour : doit rester lisible sur n'importe quel gameplay.

### 5. Deux bulles : il parle, ou il pense

L'overlay a **deux états d'expression**, visuellement distincts :

| | Bulle de **dialogue** | Bulle de **pensée** |
|---|---|---|
| Forme | bulle classique, pointe vers l'avatar | nuage, petits ronds (convention BD) |
| Quand | il y a du monde en vocal, ou un moment le justifie | personne en vocal, ou rien à commenter |
| Contenu | réaction à ce qui se passe | pensées libres |
| Rythme | rare, sur déclencheur | régulier, il occupe l'écran |

**La bulle de pensée résout le cas « live sans vocal »** : plutôt que de rester muet, Wally
vit à l'écran. Il pense aux gens présents dans le chat, à ce qu'il voit passer, ou à des
choses sans rapport.

**Source : la boucle cognitive existante.** Wally produit déjà des `THINK` en continu, et
`CognitiveFeed` les diffuse **déjà en SSE** (`/api/public/sse/cognitive`, utilisé par le site
public). Rien à inventer : il faut un rendu court de ces pensées, pas un nouveau mécanisme.
⚠️ Les pensées internes sont longues et introspectives — il faudra une version condensée
(quelques mots), pas l'extrait brut.

### 6. L'attente est affichée

Trois petits points animés dans la bulle **pendant la génération**.

La génération mesurée tourne autour de **1,3 s** (cf. point dur n°3), donc l'attente est courte.
L'animation reste utile : elle occupe l'intervalle, signale que quelque chose arrive, et couvre
les cas où le contexte gonfle ou l'API rame. Prévoir malgré tout un abandon au-delà de quelques
secondes — mieux vaut se taire que commenter le passé.

### 7. L'avatar (Rive.app)

Meilleur que les GIF actuels : transitions fluides, plus léger, machine à états pilotable.
Entrées à exposer :

| Entrée | Type | Source |
|---|---|---|
| `emotion` | énum (5 émotions) | état émotionnel réel de Wally |
| `intensity` | 0 → 1 | paliers existants (idle / low / mid / high) |
| `speaking` | déclencheur | au moment où la bulle de dialogue apparaît |
| `thinking` | booléen | pendant la génération, et sur bulle de pensée |

Effet secondaire intéressant : l'avatar rend **visible l'humeur réelle** de Wally aux viewers.
Il vit en continu, même sans parler.

---

## Pièges identifiés dans le code existant

À traiter **avant** toute mise en service, sous peine de casser le concept :

1. **`join()` déclenche `_greet()` → `speak()`** : Wally saluerait tout le monde **à l'oral** en
   arrivant, en plein stream. Le mode écoute doit court-circuiter tout le TTS.
2. **`_auto_leave_watch()` quitte après 2 min sans parole** (`auto_leave_minutes: 2`). Pendant une
   partie concentrée, les silences de 2 min sont constants : Wally ferait des allers-retours toute
   la soirée. En mode stream, la sortie doit être liée à la **fin du live**, pas au silence.
3. **Latence — le modèle n'est pas le levier, le contexte l'est.**
   Mesuré le 2026-08-06 sur des répliques courtes, prompt compact :

   | modèle | médiane | plage |
   |---|---|---|
   | `deepseek-v4-flash` | **1,25 s** | 1,06 – 1,37 s |
   | `deepseek-v4-pro` | 1,33 s | 1,30 – 1,44 s |

   Les deux sont équivalents. Les 9,2 s de p90 relevées ailleurs viennent du `reasoning`, qui
   envoie **10 128 tokens de contexte** : c'est le traitement du prompt qui coûte, pas la
   génération de cinq mots. **Garder le contexte de l'overlay compact** est donc la vraie
   contrainte — pas le choix du modèle.

   **`deepseek-v4-flash` retenu** : qualité suffisante à ce format, ~10× moins cher. `pro` est
   légèrement plus caractérisé (« La lose légendaire d'Azraël » contre « Oh non Azraël pas ça »),
   sans justifier l'écart de prix pour des bulles de quelques mots.
4. **`whisper_cpu_threads: 0`** = tous les cœurs. À borner (CT100 est déjà à ~65 % de charge).

---

## Rendu : où ça tourne, et ce que ça coûte

⚠️ **Tout le rendu se fait sur la machine d'Azraël**, pas sur le serveur. L'overlay est une page
chargée par OBS ; CT100 n'envoie que du HTML, du JS et le flux SSE. Le coût se paie donc là où
tournent déjà Apex et l'encodage — c'est le pire endroit où être gourmand.

### Rive ou CSS ?

| Élément | Techno | Pourquoi |
|---|---|---|
| Avatar | **Rive** | machine à états, transitions d'émotions, `speaking`/`thinking` pilotés en direct |
| Pièce, dé, roue | **CSS 3D** ou Rive | cas d'école bien documenté, GPU, très léger |
| Jauges, compteurs | CSS | trivial |

Rive rend **sur le GPU via WebGL**, avec un runtime WASM qui contourne le moteur de rendu du
navigateur. Son gros atout : **une machine à états au repos coûte ~0% CPU** — elle ne travaille
que sur transition.

⚠️ **Mais Wally est une flamme : sa boucle d'animation tourne en continu**, donc l'avantage « ~0%
au repos » ne s'applique PAS à l'avatar. C'est le seul élément permanent de l'overlay, et donc le
seul où l'optimisation compte vraiment. Par ordre de coût décroissant :

1. **Le flou** — piège n°1 pour du feu, très cher en GPU. Préférer des dégradés statiques
   superposés à un vrai blur calculé.
2. **La superposition de transparences** — chaque couche redessine la même zone. Deux ou trois
   suffisent.
3. **Le nombre de chemins vectoriels** — une flamme stylisée en 5-8 formes suffit ; à 200 px, le
   détail d'une flamme réaliste ne se voit pas.
4. **Les particules** (étincelles) — chacune est un objet animé.

Deux leviers gratuits : **baisser la boucle à 24-30 fps** (indiscernable sur du feu) et **garder
la boucle courte** (1-2 s qui rebouclent proprement).

L'échelle joue en notre faveur : l'avatar fait ~200×200 px, soit ~2% de la surface d'un 1080p.

**Un seul fichier Rive** pour l'avatar et les widgets qui en relèvent : le runtime est partagé et
son surcoût reste plat, alors que multiplier les runtimes coûte.

### Mesurer le coût réel

Il est **impossible de lire l'usage GPU depuis une page web** : la
[Compute Pressure API](https://developer.chrome.com/docs/web-platform/compute-pressure) existe mais
ne couvre que le **CPU**, et n'est disponible qu'en Canary derrière un flag — inutilisable dans le
CEF d'OBS.

Ce qu'on peut instrumenter dans l'overlay, **dès la phase 1** :

- son propre **framerate** (`requestAnimationFrame`) et son **temps par image** (3 ms confortable,
  12 ms préoccupant) ;
- le **modèle de GPU** via `WEBGL_debug_renderer_info` ;
- remontée de ces mesures au serveur → visibles depuis le dashboard, **sans rien demander à
  Azraël pendant qu'il stream**.

Mais la mesure qui tranche est ailleurs : **les statistiques d'OBS** (images perdues, temps de
rendu moyen) et un **test A/B** — relever les FPS en jeu avec la source overlay activée puis
désactivée. Un overlay peut afficher 60 fps parfaits tout en volant 10% du GPU au jeu.

👉 Instrumenter **avant** d'ajouter la flamme, pour disposer d'une base de comparaison.

### Ressource retenue

[3D Coin Flipper with Sound](https://rive.app/marketplace/27493-52114-3d-coin-flipper-with-sound/)
par Victor_K — gratuit, remixable, à personnaliser aux couleurs de Wally.
⚠️ Licence **CC BY** : attribution obligatoire (à placer dans les crédits du site, pas à l'écran).
⚠️ **Couper le son** (l'overlay ne doit rien émettre dans le mix).
⚠️ L'asset tire au sort tout seul : il faut une **entrée pour forcer la face**, afin que ce soit
Wally qui décide — et donc qu'il puisse commenter, voire tricher.

## Widgets candidats

Aucun n'est décidé ; liste à arbitrer. Le mécanisme d'affichage **existe déjà** :
`overlay_image` (commande `!image`) affiche une image temporaire animée sur l'overlay
(`bounceInLeft`, 5 s). Il suffirait d'ajouter des types de widgets au même endroit.

**Le hasard, commenté**
1. **Pile ou face** — la pièce tourne, Wally commente le résultat.
2. **Dé** (D6 / D20).
3. **Roue / roulette** — trancher entre plusieurs options.

**Wally tranche**
4. **Note d'une partie sur 10.**
5. **Classement** — « qui a le plus tryhard ce soir ? ». Il l'a déjà fait spontanément dans un
   journal, et il a la mémoire pour justifier.

**Participation des viewers**
6. **Sondage express** — « tapez 1 ou 2 », deux barres qui montent en direct.
7. **Tirage au sort** parmi les viewers actifs du chat.
8. **Hype-meter** — jauge qui monte quand le chat s'emballe (réutilise la détection de vague).
9. **Shoutout d'habitué** — un viewer connu arrive, son nom s'affiche (mémoire + `account_linker`).

**Données réelles** (`apex_api` disponible)
10. **Stats du joueur** — rang, kills.
11. **Comparaison** entre deux membres du squad.

**Utilitaires**
12. **Message libre** — « affiche BRB 5 min ».
13. **Compte à rebours.**
14. **Jauge d'objectif** subs / follows.

**Gags récurrents**
15. **Compteur de morts** d'Azraël, avec commentaire qui s'aigrit.
16. **Prédiction** — il parie sur l'issue avant le drop, on voit après s'il avait raison.
17. **Jauge d'humeur** de Wally, affichée en permanence.

### Le principe qui rend tout ça vivant

Passer par le **tool calling**, comme `ActionService` le fait déjà : Wally **décide** d'afficher,
il n'exécute pas une commande. C'est ce qui permet qu'il **refuse**, qu'il **commente**, qu'il
**triche**, ou qu'il **le propose de lui-même** — lancer le compteur de morts après la cinquième
défaite, sans qu'on demande rien. Un widget télécommandé est un gadget ; un widget qu'il choisit
d'afficher fait partie du personnage.

## Pistes d'amélioration

Classées par rapport valeur / effort. Aucune n'est nécessaire à une v1.

### Fortes

**Les viewers interpellent Wally dans le chat Twitch.** Le bot lit déjà ce chat. Un viewer écrit
« wally t'en penses quoi ? » → réponse dans la bulle. Ça transforme un gadget passif en
interaction, et c'est la seule fonctionnalité qui donne une raison aux viewers de le regarder.

**Reconnaître les gens.** `account_linker` relie déjà comptes Twitch et membres Discord, et Wally
a une mémoire par personne. Un habitué qui arrive dans le chat peut être salué comme tel — c'est
ce qui sépare un bot d'un compagnon.

**Nourrir le journal du soir.** Le stream deviendrait une matière de plus pour le journal
quotidien, au même titre que les visites Twitch déjà enregistrées.

### Moyennes

**Anti-répétition à l'échelle du live.** Ne pas resservir la même réaction deux fois dans une
soirée. La garde anti-redite existe, elle est à étendre à la durée du stream.

**Journal des bulles côté admin.** Relire après coup ce qu'il a dit et quand, pour régler le
rythme sur du réel plutôt qu'au jugé.

**Détecter les phases de concentration.** Chat calme + personne ne parle = moment tendu : se taire.
Inférable sans le son du jeu.

### À étudier

**Mode « sans vocal ».** Azraël streamera parfois sans être en vocal. Wally devrait alors
fonctionner avec le chat et les événements seuls — c'est aussi **la version testable sans son
accord**, et donc un bon point de départ.

**Réactions aux followers et subs.** Déjà captés par EventSub (8/8 souscriptions actives depuis
le correctif du 2026-08-05). Ce sont des moments où une réaction est attendue.

---

## Risques

| Risque | Parade |
|---|---|
| Wally dit une bêtise en direct devant l'audience | `SpeakGuard` en filtre obligatoire sur ce chemin |
| Il devient répétitif ou envahissant | budget de parole strict + anti-redite |
| Réaction hors sujet à cause de la latence | abandon au-delà de ~3 s |
| Commentaire vexant sur une défaite | cadrage du prompt : jamais de jugement sur la performance |
| Transcription fausse → réaction absurde | seuil de confiance ; dans le doute, se taire |

**Consentement** : le vocal est privé. Azraël doit accepter, et les personnes présentes doivent
savoir que Wally transcrit.

---

## Mise en œuvre suggérée

Par phases, chacune utilisable seule.

**Phase 1 — sans vocal, testable immédiatement.**
Les deux bulles sur l'overlay (dialogue + pensée), réactions aux événements de stream et aux vagues
de chat, pensées branchées sur `CognitiveFeed`. Ne dépend d'aucun accord. C'est la phase qui permet
de régler le rythme, le format et la fréquence des pensées en conditions réelles — et de savoir si
le concept tient **avant** d'investir dans le vocal et dans Rive.

**Phase 2 — l'écoute.**
Auto-join du salon `1267757914953875487` sur passage en live, mode écoute (sans TTS, sans départ
automatique), transcription branchée sur `StreamFeed`, et prise en compte d'un déplacement manuel
depuis Discord.

**Phase 3 — l'avatar Rive.**
Remplacement des GIF, machine à états, `speaking` synchronisé avec la bulle.

**Phase 4 — les enrichissements.**
Interpellation par les viewers, reconnaissance des habitués, alimentation du journal.

---

## Points tranchés (2026-08-06)

- **Salon fixe.** Azraël ne change pas de salon en cours de live. Si ça arrive, on **déplace Wally
  manuellement depuis Discord** — le bot doit donc accepter d'être déplacé et continuer d'écouter
  dans le nouveau salon, plutôt que de revenir de force sur `1267757914953875487`.
  (`on_voice_state_update` signale déjà le déplacement du bot lui-même.)
- **Live sans vocal** → bulle de pensée, alimentée par la boucle cognitive.
- **Génération** → trois points animés, l'attente est visible.

## Questions encore ouvertes

- À quelle fréquence les bulles de pensée ? Assez pour que l'overlay vive, assez peu pour ne pas
  lasser. À régler en conditions réelles — c'est exactement ce que la phase 1 permet de tester.
- Faut-il tarir les pensées quand une conversation est en cours (pour ne pas mélanger les deux
  registres), ou les laisser coexister ?
