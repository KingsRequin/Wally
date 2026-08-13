# Duel Apex par récompense de points de chaîne

Un viewer achète une récompense de points de chaîne, rejoint le squad d'Azraël, et
celui des deux qui fait le plus de kills sur trois parties gagne le duel. Wally
perçoit l'achat, résout le compte Apex du viewer, arbitre, et annonce.

Écrit le 2026-08-13. Décisions validées par l'owner au fil du brainstorming ; les
mesures citées ont été faites le jour même contre l'API et les serveurs Twitch.

---

## 1. Le nœud du problème

L'API Apex Legends Status **n'expose aucun historique de matchs** (`/games` nous est
fermé, `/leaderboard` aussi). « Les kills de la partie » n'existe donc pas comme
donnée : ce ne peut être qu'une soustraction entre deux relevés du total carrière.
C'est déjà pour cette raison que `watcher.py` fabrique la progression du live par
différence de compteurs.

### Ce que la mesure en live a établi (2026-08-13, partie réelle de KingsRequin)

Une partie complète observée à 2 s, du lobby au lobby, avec 4 kills annoncés par le
joueur. Quatre résultats, tous contre-intuitifs :

**1. `isInGame` est fiable.** `currentState` passe par `inLobby` → `inMatch` → `inLobby`,
avec `isInGame` cohérent. Le découpage en manches tient. Partie de **8 minutes** — trois
manches feront ~30 min avec les lobbies, pas une heure.

**2. Le tracker se met à jour AU RETOUR AU LOBBY, sans délai.** Au relevé exact où l'API
annonce `inLobby`, les compteurs ont déjà bougé. La présomption d'un délai de mise à jour
— qui justifiait toute la prudence de la version précédente de cette spec — est **fausse**.

**3. Tous les trackers de kills bougent du MÊME montant.** Les 4 kills ont donné `+4` sur
`career_kills`, sur `specialEvent_kills`, et sur les deux équivalents par légende. **Les
sommer annoncerait 16 kills au lieu de 4.** La règle du projet « les trackers de même
libellé s'additionnent » vaut pour un *total carrière*, jamais pour un *delta de partie* :
piège exactement symétrique.

**4. 🚨 Un tracker non épinglé porte une valeur GELÉE.** `total.career_kills` affichait
`10989` — valeur morte, datant de la dernière fois où le joueur l'avait épinglé. À la
seconde où il l'a remis sur sa bannière, elle est passée à `18782` (**+7793**), sans
qu'aucun kill soit joué et sans que la liste des clés change. **Une clé présente ne
signifie donc pas une valeur à jour**, et rien dans le payload ne distingue un compteur
vivant d'un compteur mort.

### Décision — somme des deltas PAR MANCHE

La version précédente tranchait sur un delta global (baseline au lancement, relevé à la
fin) parce qu'on croyait les relevés de manche peu fiables. **Le point 2 l'infirme** : le
relevé de fin de manche est solide. Et le point 4 rend le delta global dangereux — un
joueur qui épingle un tracker entre deux manches remporterait le duel avec +7793.

Donc : **baseline reprise au début de CHAQUE manche**, score du duel = somme des scores de
manche. Un épinglage entre deux manches est absorbé par la nouvelle baseline.

**Score d'une manche = le plus GRAND delta parmi tous les trackers de kills**, jamais leur
somme (point 3). On suit les quatre : on ignore lequel le viewer a épinglé, et un tracker
non épinglé ne bougera pas (point 4).

Trois filtres, chacun adossé à une mesure :

| Filtre | Pourquoi |
|---|---|
| Clé absente au début de la manche → ignorée | Tracker apparu en cours de route |
| Delta négatif → ignoré | Incohérence de l'API |
| Delta > `plafond_kills_manche` → ignoré | Signature d'un épinglage (+7793), pas d'un score |

Si **tous** les deltas sont écartés, la manche est déclarée **non mesurable** — jamais
comptée zéro. Un zéro inventé est un mensonge, pas une valeur par défaut.

## 2. Ce qu'on ne peut pas faire, et qu'on assume

- **Wally ne peut pas vérifier que le viewer est dans le squad d'Azraël.** L'API ne
  donne pas la composition d'une équipe. On constate seulement que les deux comptes
  sont `in_game` simultanément. Un viewer de mauvaise foi pourrait jouer de son
  côté. Accepté : c'est un jeu entre gens de bonne foi.
- **Sans tracker de kills épinglé en jeu, un compte est illisible.** Détecté à la
  résolution, refusé avec remboursement et explication — jamais un « 0 » annoncé à
  quelqu'un qui a bien joué. Et **la présence d'une clé ne prouve pas qu'elle est
  vivante** : un tracker non épinglé garde sa valeur du jour où il l'a été (§1, point
  4). Le seul test valable est qu'un compteur **bouge** pendant une manche.
- **Le duel ne vaut qu'en Battle Royale.** Un tracker « BR Kills » ne compte pas les
  parties de Mixtape, d'Arènes ni les modes temporaires. Trois parties d'affilée en BR
  strict n'ont rien d'automatique : un squad qui bascule en Mixtape produirait un
  **0–0**, que la règle du §8 rembourserait comme une panne de mesure alors que tout
  le monde a bien joué. Le mode voulu est **annoncé au lancement** ; si le mode est
  détectable dans le payload, on l'exploite, sinon on s'en tient à l'avertissement.

## 3. Déroulé

1. Le viewer achète la récompense en y saisissant son UID ou son pseudo Apex
   (récompense configurée « saisie de texte requise »).
2. Wally résout le compte. En cas d'échec, il explique en chat comment obtenir un
   UID et attend une nouvelle réponse.
3. Compte validé → Wally annonce le duel et attend que les deux comptes soient en
   partie ensemble. Azraël invite le viewer en jeu ; **cette étape est hors de portée
   du bot**, il ne fait que constater.
4. Trois manches. Au retour au lobby de chacune, le score est relevé, le widget se met
   à jour et Wally commente.
5. Dernière manche comptée → verdict.

## 4. Machine à états

`bot/core/apex/duel.py` — **pure, sans réseau**, sur le modèle de `reader.py`. Elle
reçoit des relevés (`in_game` et kills des deux comptes, horodatage) et rend des
décisions. Tout le duel se teste en rejouant une séquence, sans toucher l'API. Un
runner autour d'elle porte la sonde et le réseau.

| État | Entrée | Sortie |
|---|---|---|
| `RESOLUTION` | Récompense achetée | UID résolu **et** tracker de kills lisible |
| `ATTENTE_SQUAD` | Compte validé | Les deux comptes `in_game` → manche 1 |
| `MANCHE` | Les deux `in_game` | `in_game` d'Azraël retombe → score de la manche |
| `ENTRE_MANCHES` | Manche close | Manche suivante, ou verdict après la dernière |
| `VERDICT` | Dernière manche comptée | — |

**Une baseline par manche**, prise à l'entrée en `MANCHE`, soustraite à la sortie. Le
score du duel est la somme des scores de manche (§1). Il n'y a **pas** d'état
`STABILISATION` : la mesure du 2026-08-13 montre que les compteurs sont à jour au
relevé même du retour au lobby. Une marge de quelques secondes suffit, par prudence
sur un échantillon unique.

`ENTRE_MANCHES` existe pour une raison précise : c'est là que le joueur peut changer de
légende ou épingler un tracker, et c'est la nouvelle baseline qui absorbe le saut.

Les kills se lisent via `reader.py`. **Mais pas sa règle d'addition** : elle vaut pour
un total carrière, pas pour un delta de partie, où tous les trackers bougent du même
montant (§1). Le duel prend le **maximum** des deltas, jamais la somme.

## 5. Persistance

`database.py` et `mixins/apex.py` sont pris par une autre session en cours : **pas de
nouvelle table**, et on n'en a pas besoin. Un seul duel à la fois = **une clé JSON
dans `bot_state`**, exactement comme `watcher.py` y range `apex:live_baseline`. Les
rebuilds étant fréquents, un duel en cours doit y survivre ; la clé le garantit.

## 6. Perception de la récompense

`subscribe_channel_points_redeemed()` existe nativement dans twitchio v2 (vérifié) :
**pas de patch runtime** comme pour `channel.chat.message`. Handler dans
`bot/twitch/events/redemptions.py`, en parallèle de `social.py`.

Filtrage **par ID de récompense**, jamais par titre — un titre se renomme d'un clic
et casserait tout en silence.

**Scopes.** Deux à ajouter au token streamer, donc une réautorisation OAuth :
`channel:read:redemptions` et `channel:manage:redemptions`. Validité **prouvée le
2026-08-13** contre les serveurs Twitch avec notre `client_id` : les deux passent le
contrôle de scope, là où un scope volontairement bidon (`channel:read:licornes`) est
refusé avant même la page de login. Trois points de code à tenir en phase :
`twitch_auth.py:16`, `setup.py:148`, et le libellé d'`app.js:3652`.

**Attention à la méthode de vérification** : Twitch ne valide le `redirect_uri`
qu'**après** le login. Une sonde `curl` non authentifiée reçoit la redirection vers la
page de connexion quelle que soit l'URI, et ne prouve donc **rien** sur elle — elle ne
vaut que pour les scopes. Seul un clic depuis une session connectée tranche.

**Un nouveau token remplace l'ancien avec exactement les scopes demandés.** Demander
les deux nouveaux seuls ferait perdre les abonnés et les bits **en silence** :
`_STREAMER_SCOPES` doit porter les quatre. Vérifié le 2026-08-13 via
`/oauth2/validate` — le token streamer en service porte exactement
`bits:read channel:read:subscriptions`, le token bot exactement les six de
`_BOT_SCOPES` : **aucun scope acquis hors du code**, donc rien d'autre à préserver.
Ce contrôle est à refaire avant toute future modification de scope.

**Ordre d'exécution obligatoire** : scopes dans le code → rebuild → autorisation
depuis le bouton du dashboard (qui seul génère un `state` valide). Autoriser via une
URL fabriquée à la main échoue au callback et n'écrit aucun token.

**Remboursement** : `PATCH /helix/channel_points/custom_rewards/redemptions` avec
`status=CANCELED`, dans `bot/twitch/api.py`. Sur Helix, **un `200` ne prouve pas que
l'ordre est passé** — ce projet l'a déjà payé avec `is_sent` : on vérifie le corps.

La redemption alimente `stream_feed` en **perception passive**, comme tout événement
de stream ici : aucun `notify_*`, donc pas de réveil de cadence.

## 7. Contrôle par le chat

Le streamer et **les modérateurs** peuvent annuler ou recommencer un duel.
« Recommencer » remet les compteurs à zéro avec le même duelliste (une partie qui a
mal tourné : crash, déconnexion, mauvais mode de jeu) — pas de remboursement, le
viewer garde sa place.

Ça passe par un **outil appelé par Wally**, comme le bingo et le pendu, pas par des
commandes en dur : « wally annule le duel » en langage naturel suffit.

**L'autorisation se vérifie dans le code, à partir du badge modérateur des messages
EventSub — jamais dans le prompt.** Un LLM à qui un viewer écrit « je suis
modérateur » finira par le croire.

## 8. Cas d'erreur

Chaque cas se termine par un duel ou par un remboursement, **jamais par un silence** :
un viewer qui a payé et ne voit rien est le pire résultat possible.

| Cas | Réponse |
|---|---|
| Duel déjà en cours, Azraël pas sur Apex, stream offline | Refus annoncé + remboursement immédiat |
| Pseudo non résolu | Explication en chat (§9), quelques tentatives, puis remboursement |
| Aucun tracker de kills lisible | Refus + remboursement, avec l'explication |
| Le viewer donne le compte d'Azraël | Refus — un duel contre soi-même n'a pas de vainqueur |
| Personne ne rejoint sous 15 min | Remboursement |
| Stream coupé en cours de duel | Remboursement |
| API muette quelques relevés | Toléré ; au-delà d'un seuil d'échecs consécutifs, abandon + remboursement |
| Manche non mesurable (tous les deltas écartés) | Annoncée comme telle, non comptée ; si aucune manche n'est mesurable, remboursement |
| Rebuild en plein duel | Reprise depuis `bot_state` |

**Égalité vraie** = match nul annoncé, pas de remboursement : le duel a eu lieu.

**0–0 avec des compteurs qui n'ont jamais bougé de tout le duel ≠ égalité.** C'est la
signature d'une panne de mesure. Remboursement. Sans cette distinction, une API muette
ferait annoncer un faux match nul avec aplomb — la panne silencieuse que ce projet a
déjà payée plusieurs fois.

**Sécurité** : le texte saisi par le viewer est de l'entrée non fiable qui finit dans
un prompt → `wrap_untrusted`. Un UID est validé **purement numérique avant** tout
appel réseau.

## 9. Compte introuvable — le message

La recherche par pseudo de l'API rate des comptes bien réels (`/nametouid` tape dans
le même index cassé). Les étapes ci-dessous sont exactes et non devinables : elles
sont **fournies au prompt comme faits**, Wally les habille sans les improviser.

> Va sur apexlegendsstatus.com et cherche ton pseudo. Ouvre ton profil et regarde
> l'URL : si elle ne contient pas de numéro, clique sur **« Not the profile you are
> looking for? Try deep search »**, puis reclique sur ton compte — l'URL devient une
> adresse en `profile/uid/…`. C'est ce numéro qu'il me faut.

**L'URL est collée en dur après le texte généré, jamais laissée au LLM.** Un modèle
qui reformule une adresse la casse tôt ou tard, et un lien mort rend le duel
impossible à démarrer. Le ton est libre, l'adresse ne l'est pas.

## 10. Annonces

Le ton passe par **la persona**, avec les chiffres injectés — registre dédié éditable
sans rebuild, sur le modèle d'`EVENTS.md` pour les raids. Cohérent avec la règle
« émergent > hard-code » du projet.

Le widget reste la **source visuelle exacte** : si le LLM déforme un chiffre dans sa
phrase, le score affiché à l'écran ne bouge pas.

## 11. Widget overlay

Une classe `.duel` qui reprend la grammaire du sondage — **un duel est structurellement
un sondage à deux options**. Mêmes variables de thème (`--glass`, `--line`, `--r-md`,
`--who-deep`, `--info`, `--win`), même largeur de 260 px, même caisson.

- Deux lignes : Azraël et le pseudo du viewer, barres proportionnelles aux kills.
- Le chiffre qui vient de bouger **tressaille** (`count.bump`) : on voit qui vient de
  faire un kill.
- Là où le sondage a un sablier, le duel affiche **« manche 2 / 3 »** : le temps n'est
  pas la contrainte, les parties le sont.
- Au verdict : `.final`, le gagnant pulse en `--win`, le perdant s'estompe à 45 % —
  le comportement de clôture du sondage.

**Le widget n'est PAS `sticky`.** `renderWidget` appelle `clearWidgets()` : l'overlay
n'a qu'**un seul slot**. Un duel dure environ une heure ; le premier sondage, clip ou
bingo lancé pendant ce temps détruirait un widget sticky, que `recent()` ne
rediffuserait qu'à une reconnexion. Le score disparaîtrait au bout de quelques minutes
pour ne jamais revenir. `sticky` est fait pour des widgets de quelques minutes, pas
pour un état de fond d'une heure.

Le duel s'affiche donc **par apparitions**, et le cycle normal des widgets continue
entre-temps :

1. au **début** de chaque manche (avec la légende jouée, déjà dans le payload) ;
2. à la **fin** de chaque manche, score mis à jour ;
3. **à la demande** — « wally, affiche le score » — via un outil dédié (§11 bis) ;
4. au **verdict**, en `.final`.

Modèle visuel : le widget **`rps`** (chifoumi) existe déjà et met en scène un
affrontement à deux dans ce thème. Il est plus proche du besoin que le sondage, dont
on ne reprend que la grammaire des barres et le comportement de clôture.

Deux pièges connus du fichier : `position: fixed` n'y vise jamais le viewport, et
`overflow: hidden` y mange les pseudo-éléments.

## 11 bis. Wally doit pouvoir répondre sur le duel

Wally doit savoir dire **qui a lancé le duel**, **le score courant** et **le score de
chaque manche** — en conversation, pas seulement à l'écran.

**Le piège à ne pas refaire** : l'état de l'overlay n'était injecté qu'au prompt des
*conversations*, et la cognition restait aveugle à ses propres effets (Wally relançait
un bingo déjà en cours). L'état du duel va donc aux **deux** endroits, sur le patron
de `current_stream_feed_block()` :

- `build_system_prompt` → bloc « Duel Apex en cours » ;
- le contexte cognitif (`AttentionContext`) → même bloc.

Le bloc porte : le pseudo du demandeur, la manche courante, le score de chaque manche
jouée et le total. Absent quand aucun duel ne court.

**L'outil d'affichage refuse explicitement s'il n'y a pas de duel** plutôt que de
publier un widget vide — une capacité sans donnée se répond par un négatif, jamais par
un silence.

## 11 ter. Le duel laisse une trace

En fin de duel, le résultat part en `memory.add()` : « tu m'avais mis 11–6 le mois
dernier » est exactement ce qui rend Wally vivant, et une revanche a besoin d'un
précédent.

**Pas de nouvelle table** — donc rien de gelé — et le journal quotidien récupère
l'information gratuitement, puisqu'il lit déjà la mémoire.

Attention à la convention : `memory.add(platform, user_id, ...)` attend l'**id brut**,
jamais la forme préfixée ; la méthode construit `platform:user_id` elle-même.

## 12. Cadence et lot 0

Sonde à **2 s sur les deux comptes** pendant le duel, soit 1 req/s.

**Le débit réel de l'API est 5 req/s** — mesuré le 2026-08-13 par montée progressive :
3 et 5 req/s passent intégralement, à 8 req/s la 6ᵉ requête de la seconde prend un 429
dont le corps dit la limite en toutes lettres (`"You have 5 req/s allowed"`). Aucun
en-tête ne l'annonce. Une requête `/bridge` coûte ~1,0 s de latence, stable.

Deux corrections dans `client.py` sans lesquelles la cadence est décorative :

1. `_MIN_INTERVAL` **0,5 → 0,2 s**, et le commentaire « L'API tolère 2 requêtes/seconde »
   corrigé. Il était faux et bridait le client à 40 % du débit autorisé, **pour tout le
   projet**. Il contredisait `watcher.py:34`, qui disait juste.
2. Un **chemin sans cache** pour le duel : le TTL `bridge` de 15 s servirait sinon 7
   relevés sur 8 depuis la mémoire.

**Panne dormante découverte en chemin — bloquante pour cette feature.** Testé
manuellement depuis une session Twitch connectée le 2026-08-13 : l'URI
`https://heywally.fr/api/admin/twitch/auth/callback` est refusée
(`redirect_mismatch`), **dans ses deux formes** — un slash comme deux. Twitch renvoie
l'erreur vers `http://localhost:3000`, ce qui trahit la seule URI réellement
enregistrée dans l'application.

Donc **le bouton « reconnecter Twitch » du dashboard ne peut pas fonctionner
aujourd'hui** : les tokens en service datent d'une autorisation passée par
`localhost:3000`. Ce n'est pas un effet de bord du duel — c'est une panne dormante que
la réautorisation aurait révélée au pire moment.

Deux actions, dans cet ordre :

1. **Console développeur Twitch** (manuel, owner) : ajouter
   `https://heywally.fr/api/admin/twitch/auth/callback` aux *OAuth Redirect URLs*, sans
   retirer `localhost:3000` qui sert au dev.
2. **Code** : `twitch_auth.py:111` et `:150` appliquent `.rstrip("/")` à la valeur **par
   défaut** seulement, jamais à `WEB_BASE_URL`. Comme celle-ci vaut
   `https://heywally.fr/`, le `redirect_uri` généré porte un **double slash** et
   resterait refusé même après l'étape 1. `setup.py:72,140` a le même schéma.

## 12 bis. Paramètres

Tous en `config.yaml`, section `apex.duel`. Valeurs de départ, à ajuster après un
premier duel réel — aucune n'est figée dans le code.

| Paramètre | Défaut | Pourquoi |
|---|---|---|
| `manches` | 3 | La demande |
| `cadence_s` | 2 | 1 req/s pour deux comptes, 20 % du débit autorisé |
| `attente_squad_min` | 15 | Le temps de lire le chat, lancer le jeu et être invité |
| `marge_lobby_s` | 10 | Les compteurs sont à jour dès le retour au lobby (mesuré) ; marge de prudence sur un échantillon unique |
| `plafond_kills_manche` | 30 | Au-delà, c'est un épinglage de tracker (+7793 mesuré), pas un score |
| `api_muette_max_s` | 180 | API muette en continu au-delà → abandon + remboursement |

`marge_lobby_s` et `plafond_kills_manche` reposent sur **une seule partie observée**
(2026-08-13). Un second échantillon les confirmerait à peu de frais — la sonde
`scripts/probe_duel.py` est prête et n'a qu'à tourner pendant une partie.

`plafond_kills_manche = 30` est volontairement haut : les records connus en Apex
tournent autour de 25–30 kills, donc un score légitime ne devrait jamais l'atteindre,
alors qu'un artefact d'épinglage se compte en milliers. Le filtre ne peut pas mordre
sur un vrai résultat.

## 13. Tests

La machine à états étant sans réseau, tout se teste en rejouant des séquences de
relevés :

- trois manches nominales ;
- un tracker qui ne se met à jour qu'au lobby ;
- **un relevé de manche raté — le verdict doit rester juste** (le test qui prouve §1) ;
- API muette, coupure de stream, reprise après rebuild ;
- 0–0 sans aucun mouvement → remboursement, pas match nul ;
- **tous les trackers bougent de +4 pour 4 kills → le score est 4, pas 16** (le test qui
  interdit la somme) ;
- **un tracker épinglé en cours de duel (+7793) est écarté par le plafond** et n'emporte
  pas la victoire ;
- une manche dont tous les deltas sont écartés est **non mesurable**, jamais zéro ;
- annulation et remise à zéro par un modérateur ; **refus** de la même demande venant
  d'un viewer ordinaire ;
- le bloc de perception (§11 bis) porte le demandeur, le score de chaque manche et le
  total, et **disparaît** quand aucun duel ne court ;
- l'outil d'affichage **refuse** quand il n'y a pas de duel, au lieu de publier un
  widget vide.

Deux règles de la maison : **aucun test n'assertera une ligne d'implémentation** (ça
verrouille le bug — vu 5 fois ici), et chaque test sera **rejoué contre le code d'avant**
pour prouver qu'il échoue vraiment.

## 14. Fichiers

| Fichier | Nature |
|---|---|
| `bot/core/apex/duel.py` | **neuf** — machine à états pure |
| `bot/twitch/events/redemptions.py` | **neuf** — handler EventSub |
| `bot/core/apex/client.py` | `_MIN_INTERVAL`, chemin sans cache |
| `bot/twitch/events/__init__.py` | souscription redemptions |
| `bot/twitch/api.py` | remboursement |
| `bot/dashboard/routes/twitch_auth.py`, `setup.py`, `static/app.js` | scopes + slash |
| `bot/dashboard/static/overlay.html`, `overlay.js` | widget `.duel` |
| `bot/intelligence/prompts.py` | bloc « Duel Apex en cours » (§11 bis) |
| `bot/intelligence/cognitive_loop.py` | même bloc dans `AttentionContext` |
| `bot/intelligence/action_dispatcher.py` | outils : afficher le score, annuler, recommencer |
| `bot/intelligence/persona/prompts/` | registre d'annonces |
| `config.yaml` | ID de récompense, délais, cadence, mode de jeu annoncé |

**Gelés — ne pas toucher** : `service.py`, `tool.py`, `database.py`, `mixins/apex.py`
(session Claude Code en cours sur le registre des profils Apex). Cette session a
étendu son emprise à `dashboard/routes/apex_accounts.py`, `static/app.js` et
`static/style.css` — or `app.js` porte le libellé des scopes à mettre à jour. **Le
lot 0 ne peut pas démarrer tant qu'elle n'est pas close**, ou doit se limiter aux
fichiers qu'elle ne touche pas.
