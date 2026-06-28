# Self-model dérivé — anti-fossilisation des capacités

**Date :** 2026-06-28
**Branche :** `feat/site-redesign-arcade`
**Statut :** Design validé, en attente de relecture

---

## Problème

Pendant sa boucle cognitive idle, Wally a produit cette pensée **fausse** :

> « Le vocal est dans mon code mais désactivé — KingsRequin le sait déjà, je l'ai déjà
> demandé, il m'a dit que c'était construit mais pas branché. Inutile de redemander. »

Or le vocal **fonctionne** (`config.voice.enabled: true`, Azure TTS + STT GPU branchés
et déployés le 27/06).

### Cause racine

`bot/persona/CAPABILITIES.md` est le **self-model** de Wally : un fichier Markdown statique,
lu **une seule fois au boot** et injecté **littéralement** dans le contexte cognitif.

- Lecture cognition : `bot/discord/bot.py:217` → passé à `ReasoningAgent(capabilities_text=…)`,
  ré-injecté à chaque tick dans `bot/intelligence/reasoning_agent.py:163-166`.
- Lecture réactive : `CAPABILITIES.md` est dans `PersonaService._FILES`
  (`bot/intelligence/persona.py:12`), concaténé dans `build_prompt_block()`.

La **ligne 22** affirme en dur que le vocal est « désactivé (pas branché) ». Le 22/06 ce texte
a été écrit ; le 27/06 le vocal a été réellement activé ; **le `.md` n'a jamais été mis à jour**.
Il n'existe **aucun mécanisme de péremption / correction** pour ce fichier : il se *fossilise*.

Le contenu de `CAPABILITIES.md` mélange **deux natures** :

1. **Vérités de personnage stables** — « je n'ai pas de corps », « je n'étais pas là aux streams
   passés », garde anti-hallucination, mémoire, émotions, vie intérieure, journal. Ne dépendent
   d'aucun toggle.
2. **Capacités techniques à bascule** — typiquement le vocal (état réel : `config.voice.enabled`).
   C'est cette catégorie qui diverge de l'état réel quand on active/désactive quelque chose.
   (La recherche web appartient aussi à cette catégorie mais sa source de vérité est différente —
   voir « Pourquoi le web n'est PAS dans le registre initial ».)

Aligné avec la North Star du projet (« coder le mécanisme, jamais la valeur en dur ») : la partie
à bascule doit être **dérivée de l'état réel**, pas écrite à la main.

---

## Objectif

Que le self-model de Wally ne puisse plus affirmer une capacité technique contraire à l'état réel
de sa configuration — **sans réécrire** la partie narrative, et en rendant l'ajout d'une capacité
future trivial (une ligne de registre).

### Hors scope

- Le hot-reload du self-model dérivé dans la cognition (changement de toggle à chaud → reflété
  sans restart). Voir « Limite assumée ».
- La recherche web pendant la pensée idle (« chantier B », traité séparément).
- Toute refonte plus large du self-model (option « entièrement dérivé » écartée au cadrage).

---

## Conception

Approche retenue au cadrage : **hybride dérivé**. Le `.md` garde le narratif stable ; les
capacités à bascule sont générées au runtime depuis la config.

### 1. Nouveau module pur — `bot/intelligence/self_model.py`

Fonction pure, sans I/O ni dépendance aux objets services (donc insensible à l'ordre de montage) :

```
build_self_model(static_text: str, config) -> str
```

- Prend le markdown **statique** (le `.md` nettoyé).
- Évalue un **registre déclaratif** de capacités à bascule contre la `config`.
- Appende une section générée `## Mes capacités techniques actuelles` listant les phrases
  correspondant à l'état réel.
- Retourne le texte assemblé.

**Registre déclaratif** — une entrée par capacité à bascule :

```
(condition: config -> bool,  phrase_si_actif: str,  phrase_si_inactif: str)
```

Capacité couverte au départ (YAGNI : la seule qui a réellement fossilisé, avec une source de
vérité nette) :

| Capacité | Source de vérité       | Phrase si actif                                                | Phrase si inactif                                                      |
|----------|------------------------|-----------------------------------------------------------------|-----------------------------------------------------------------------|
| Vocal    | `config.voice.enabled` | « Je peux entendre et parler en vocal dans les salons audio. » | « Le vocal existe dans mon code mais n'est pas activé pour l'instant. » |

Ajouter une capacité future = **une ligne** dans le registre.

#### Pourquoi le web n'est PAS dans le registre initial

La « recherche web » ne se dérive **pas** d'un simple toggle config, contrairement au vocal :

- La recherche (`web_search`) repose sur **Tavily**, dont la disponibilité dépend de
  `TAVILY_API_KEY` (variable d'**env**, lue dans `bot/core/web_search.py:83`), pas d'une clé config.
- `config.firecrawl.enabled` concerne le **scraping** (`scrape_url`), pas la recherche — les deux
  services sont distincts et complémentaires (Tavily = chercher sans URL ; Firecrawl = lire une URL).

L'inclure ici mélangerait env + config et deux services. Surtout, tant que le chantier B (recherche
web pendant la pensée idle) n'est pas fait, Wally a le web en **réactif** mais pas en **cognition** —
affirmer « je peux chercher sur le web » dans le contexte cognitif serait une nouvelle incohérence.

La capacité « recherche web » sera ajoutée au registre **dans le chantier B**, au moment où l'on
tranche aussi sa source de vérité (Tavily via env vs `/search` de Firecrawl self-host, à benchmarker)
et son accès en idle. Le mécanisme du registre est conçu pour l'accueillir sans refonte.

### 2. Nettoyage de `CAPABILITIES.md`

Retirer la seule ligne « à bascule » qui a fossilisé :

- **Ligne 22 (vocal)** : supprimée (désormais dérivée du registre).

La **ligne 21 (web)** est **conservée telle quelle** : « je ne navigue pas sur le web librement,
seulement via un outil précis » est une affirmation **correcte et stable** (elle n'a pas fossilisé).
Elle sera revue dans le chantier B si l'accès web évolue.

Tout le reste (narratif stable + garde anti-hallucination) est **conservé tel quel**.

### 3. Branchement des deux consommateurs

Les deux chemins lisent déjà `CAPABILITIES.md` indépendamment ; chacun applique la même
fonction pure.

**a. Cognition idle** — `bot/discord/bot.py:217`
```
_caps_text = build_self_model(_caps_static_text, self.config)
```
Le reste (construction de `ReasoningAgent`) est inchangé.

**b. Réactif** — `bot/intelligence/persona.py`
- `PersonaService.__init__` reçoit `config` (optionnel, défaut `None` pour rétrocompat tests).
- `CAPABILITIES.md` sort de `_FILES` ; il est chargé à part comme `caps_static`.
- `build_prompt_block()` appende `build_self_model(caps_static, config)` à la fin du bloc
  (préserve l'ordre canonique SOUL→IDENTITY→VOICE→EXEMPLES→[self-model]).
- Si `config is None` (tests / appel legacy), fallback au texte statique brut.
- Bénéfice : `/reload-persona` (qui appelle `reload()`) re-dérive automatiquement.

> `PersonaService` est construit dans le wiring DI — lui passer `config` y est ajouté.

### Pourquoi dériver de `config` et non des objets services

`ReasoningAgent` est construit à `bot.py:222`, mais `voice_service` n'est câblé qu'à `bot.py:294`
(**après**). Dériver des objets montés serait une course à l'ordre d'init. La `config` est
entièrement disponible dès le début de `setup_hook`, déterministe, et c'est la source de vérité
déclarative du toggle.

---

## Tests

La fonction pure rend les tests directs (pas d'async, pas de mocks lourds) :

- `build_self_model` avec `voice.enabled: true` → la sortie **contient** « parler en vocal »,
  **ne contient pas** « désactivé » / « pas branché ».
- `voice.enabled: false` → contient la phrase inactive.
- Le narratif stable (« pas de corps », garde anti-hallucination) est toujours présent en sortie.
- `PersonaService.build_prompt_block()` avec une config injectée reflète l'état des toggles ;
  avec `config=None` retombe sur le texte statique sans crash.

---

## Limite assumée

La dérivation se fait **au boot**. Changer un toggle (ex. `voice.enabled` via le dashboard) ne se
reflète dans la **cognition** qu'au prochain restart. C'est déjà très supérieur à l'état actuel
(édition manuelle du `.md` + rebuild image). Le côté **réactif** se rafraîchit, lui, via
`/reload-persona`. Le hot-reload complet du self-model cognitif est une amélioration distincte,
hors scope.

---

## Surface de changement

- **Nouveau** : `bot/intelligence/self_model.py` (fonction pure + registre).
- **Nouveau** : tests unitaires associés.
- **Modifié** : `bot/persona/CAPABILITIES.md` (retrait de la ligne 22, vocal).
- **Modifié** : `bot/discord/bot.py` (1 ligne au point d'injection).
- **Modifié** : `bot/intelligence/persona.py` (`config` injecté, `CAPABILITIES.md` hors `_FILES`,
  `build_prompt_block` appende le self-model dérivé).
- **Modifié** : wiring DI de `PersonaService` (passage de `config`).
