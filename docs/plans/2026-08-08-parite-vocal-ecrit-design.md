# Parité vocal / écrit — conception

**Date** : 2026-08-08 · **Statut** : validé, à implémenter
**Demande** : tout ce qu'on peut demander à Wally par écrit doit pouvoir lui être
demandé à voix haute, et il répond **dans le chat Twitch**, en mentionnant la
personne — exactement comme s'il avait été mentionné dans le chat.

---

## 1. Ce qui existe

Une phrase vocale qui contient son nom part vers `OverlayNarrator.on_voice_request`
(`bot/discord/voice/service.py:625`). Ce chemin :

- n'offre que **4 outils** : `show_overlay`, `cancel_overlay`, `show_last_clip`,
  `show_apex` ;
- ne répond que par une **bulle d'overlay** de 3 à 8 mots ;
- n'écrit **jamais** dans le chat.

Le chemin écrit (`bot/twitch/handlers.py`), lui, offre une vingtaine d'outils
(Apex, recherche web, scraping, memes, clips, citations, paris, compteurs, notes,
mémoire, rappels, overlay), avec la persona, la mémoire et le contexte du canal.

L'écart n'est donc pas un réglage : c'est un chemin pauvre à côté d'un chemin riche.

---

## 2. Le piège à éviter

Élargir `on_voice_request` en y recopiant les vingt outils créerait **une seconde
liste et un second exécuteur** à côté de ceux du chat. Deux vérités qui
divergeraient au premier ajout.

Le projet a déjà payé cette erreur : l'énumération des coups du chifoumi existait
en anglais dans le schéma d'outil et en français dans le comparateur — la triche
retombait silencieusement sur un tirage au hasard.

> **Décision :** une seule liste d'outils et un seul exécuteur, partagés par les
> deux bouches.

On écarte aussi la solution inverse — rejouer la phrase vocale comme un faux
message de chat. Elle serait comptée dans les visites, injectée dans le flux du
stream comme une ligne de chat, passée au détecteur de spam et au `fact_extractor`.
Ce n'est pas du chat ; le faire croire salirait quatre mécanismes pour économiser
une extraction.

---

## 3. Architecture

Deux briques sortent de `bot/twitch/handlers.py`, sans changer leur comportement :

| Brique | Rôle |
|---|---|
| `build_chat_tools(bot, *, allow_self_modify)` | La liste d'outils offerte au LLM |
| `make_tool_executor(bot, *, requester, requester_name, channel)` | L'exécution d'un appel d'outil |

`handle_message` les appelle (comportement inchangé, garanti par les tests
existants). Le nouveau chemin vocal les appelle aussi.

**`bot/discord/voice/request.py`** (nouveau) porte le chemin vocal : filtre du
demandeur, appel LLM outillé, envoi de la réponse. Un fichier à part parce que
`voice/service.py` fait déjà de l'audio, du STT et de la présence — la logique de
demande n'y a pas sa place.

---

## 4. Qui peut demander

Seuls **Azraël** et **KingsRequin**. Le filtre remplace tout rationnement : deux
personnes ne saturent pas un chat. Les autres restent perçus comme aujourd'hui —
Wally les entend, il ne leur obéit pas.

```yaml
voice:
  requesters:
    - discord_id: '610550333042589752'   # KingsRequin
      twitch_login: kingsrequin
    - discord_id: '419172225451556874'   # Azraël
      twitch_login: azrael_ttv
```

Les deux identités sont portées ensemble parce qu'elles servent à deux choses :
le `discord_id` **identifie** celui qui parle (c'est un salon vocal Discord), le
`twitch_login` sert à le **mentionner** dans la réponse.

**Compte Apex :** le demandeur est passé aux outils sous son identité Discord
(`discord:419…`). Quelqu'un qui a déclaré son compte Apex sur Twitch devra donc le
redéclarer une fois à l'oral — `remember` fonctionne par ce chemin aussi. Lier les
deux identités automatiquement supposerait une correspondance qui n'existe pas en
base pour tout le monde ; on préfère un redéclaratif d'une phrase à une
correspondance devinée.

---

## 5. Ce qui sort, et où

- **Le chat Twitch de la chaîne**, préfixé de la mention : `@azrael_ttv …`. Une à
  deux phrases, comme une réponse à une mention écrite.
- **La bulle d'overlay** reste, courte, pour les viewers qui ne lisent pas le chat.
- **Le widget** s'affiche comme aujourd'hui quand un outil d'overlay est appelé.

**Rien hors live.** Sans live, personne ne lit le chat : la réponse ne part pas et
Wally le dit à l'oral — même règle que l'overlay.

---

## 6. La marge d'erreur du STT

La transcription se trompe : « il y a des jambons » pour « il y a des gens bons ».
Deux dispositions, pas une.

**Interpréter au son.** Consigne dans le prompt vocal : *ce que tu lis sort d'une
transcription automatique. Si une phrase n'a pas de sens, suppose une erreur et
cherche ce qui lui ressemble phonétiquement. Ne relève pas l'absurdité, ne réponds
pas à côté.*

**Ne pas agir dans le doute.** Si la demande est douteuse **et** qu'elle laisserait
une trace durable — note, rappel, souvenir mémorisé — Wally demande confirmation
au lieu d'exécuter. Se tromper sur un pile ou face ne coûte rien ; un rappel
programmé de travers reste. C'est le pendant vocal d'une règle déjà en place :
*capacité sans donnée = négatif explicite, jamais de silence.*

**Tolérance sur le nom seulement.** « wally » s'entend « wallis », « ouali »,
« oualy ». Le déclencheur accepte ces variantes (distance de Levenshtein ≤ 2 sur un
mot du message). La tolérance porte sur le **nom**, jamais sur la commande : on ne
devine pas « pile ou face » à partir d'un mot approchant.

---

## 7. Hors périmètre

- **`code_fix`** — l'auto-modification reste hors du vocal. Une phrase mal
  transcrite ne doit pas pouvoir toucher au code du bot. Elle garde son chemin :
  demande écrite, autorisation en DM.
- **Répondre à voix haute** — Wally reste muet en live : il couvrirait le streamer
  et serait réinjecté dans son micro. Il écoute et il écrit.
- **Les autres personnes en vocal** — perçues, jamais obéies. À rouvrir si le
  besoin se présente.

---

## 8. Tests

- Une demande d'Azraël en vocal part dans le chat Twitch, préfixée de `@azrael_ttv`.
- Une demande d'un tiers en vocal ne déclenche **aucun** outil et n'écrit rien.
- Hors live, rien ne part sur Twitch.
- Le chemin vocal reçoit **exactement** la même liste d'outils que le chat, moins
  `code_fix` — un test d'appariement qui échoue si l'une des deux listes bouge.
- `handle_message` se comporte comme avant l'extraction (tests existants).
- Le déclencheur accepte « wallis », « ouali » ; il refuse un mot sans rapport.
- Un appel d'outil passé par le vocal reçoit l'identité du demandeur.

---

## 9. Étapes

| # | Contenu | Fichiers |
|---|---|---|
| 1 | Extraire `build_chat_tools` et `make_tool_executor` | `twitch/handlers.py` + tests |
| 2 | Config `voice.requesters` | `config.py`, `config.yaml` |
| 3 | `voice/request.py` : filtre, appel outillé, sortie chat + bulle | nouveau + `voice/service.py` |
| 4 | Prompt vocal : marge d'erreur STT, tolérance du nom | `persona/prompts/overlay_voice.md` |
