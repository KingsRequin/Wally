# Duel Apex par points de chaîne — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un viewer achète une récompense de points de chaîne, rejoint le squad d'Azraël, et Wally arbitre trois parties au nombre de kills.

**Architecture:** Une machine à états pure et sans réseau (`bot/core/apex/duel.py`) qui reçoit des relevés et rend des décisions, entourée d'un runner qui porte la sonde à 2 s. L'état vit dans une clé JSON de `bot_state` pour survivre aux rebuilds. La perception passe par EventSub, l'affichage réutilise le widget `versus` existant, les annonces passent par la persona.

**Tech Stack:** Python 3.11 asyncio, httpx, twitchio v2, aiosqlite, loguru, pytest/pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-08-13-apex-duel-points-chaine-design.md`

**Référence API:** `docs/api-apex-legends-status.md`

## Global Constraints

- **Fichiers GELÉS — ne pas modifier** : `bot/core/apex/service.py`, `bot/core/apex/tool.py`, `bot/db/database.py`, `bot/db/mixins/apex.py`, `bot/dashboard/routes/apex_accounts.py`, `bot/dashboard/static/app.js`, `bot/dashboard/static/style.css` (session Claude Code concurrente). Si un lot en a besoin, il attend.
- **Aucune nouvelle table** : l'état du duel vit dans `bot_state`, via `db.get_state(clé)` / `db.set_state(clé, valeur)`.
- **Logging** : `from loguru import logger` exclusivement. Jamais `print()` ni `import logging`.
- **Débit API Apex** : 5 req/s maximum. La sonde du duel consomme 1 req/s (2 comptes / 2 s).
- **Un delta de kills se prend au MAXIMUM des trackers, jamais à leur somme.** 4 kills → +4 sur les quatre trackers simultanément ; les additionner donnerait 16.
- **Ne jamais annoncer « 0 kill » par défaut.** Une absence de donnée est une absence, pas un zéro.
- **Tests** : aucun test n'assertera une ligne d'implémentation (ça verrouille le bug — arrivé 5 fois sur ce projet). Chaque test doit d'abord échouer contre le code d'avant.
- **Toute entrée viewer** passe par `wrap_untrusted` avant d'atteindre un prompt.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `bot/core/apex/reader.py` (modif) | + `read_kill_trackers(payload)` : les trackers de kills **bruts**, non normalisés |
| `bot/core/apex/duel.py` (neuf) | Machine à états pure, sans réseau ni I/O. Le cœur testable. |
| `bot/core/apex/duel_runner.py` (neuf) | Sonde 2 s, persistance `bot_state`, effets (chat, widget) |
| `bot/core/apex/client.py` (modif) | Débit réel 5 req/s + chemin sans cache |
| `bot/twitch/events/redemptions.py` (neuf) | Handler EventSub des redemptions |
| `bot/twitch/events/__init__.py` (modif) | Souscription `channel_points_redeemed` |
| `bot/twitch/api.py` (modif) | `refund_redemption()` |
| `bot/dashboard/routes/twitch_auth.py` (modif) | Scopes + correctif du slash |
| `bot/dashboard/routes/setup.py` (modif) | Mêmes scopes, même correctif |
| `bot/intelligence/prompts.py` (modif) | Bloc « Duel Apex en cours » |
| `bot/persona/prompts/apex_duel.md` (neuf) | Registre d'annonces, éditable sans rebuild |
| `config.yaml` (modif) | `apex.duel.*` |

---

## Task 1 : Débrider le client Apex et lui donner un chemin sans cache

**Files:**
- Modify: `bot/core/apex/client.py:36-37` (`_MIN_INTERVAL`), `:59-82` (`get`)
- Test: `tests/test_apex_client_debit.py` (créer)

**Interfaces:**
- Produces: `ApexClient.get(endpoint, params=None, *, sans_cache: bool = False)` — quand `sans_cache=True`, ni lecture ni écriture du cache.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_apex_client_debit.py
"""Le client doit exploiter le débit réellement autorisé, et savoir l'ignorer.

Mesuré le 2026-08-13 : l'API accepte 5 req/s (la limite n'est écrite que dans le
corps du 429). Le client en annonçait 2 et bridait d'autant — 60 % du débit payé
inutilisé, pour tout le projet.
"""
import pytest

from bot.core.apex.client import ApexClient, _MIN_INTERVAL


def test_intervalle_minimal_respecte_les_5_req_par_seconde():
    # 5 req/s => au plus 0,2 s entre deux requêtes.
    assert _MIN_INTERVAL <= 0.2


@pytest.mark.asyncio
async def test_sans_cache_refait_l_appel_reseau():
    """Le TTL de `bridge` est de 15 s : une sonde à 2 s verrait 7 relevés sur 8
    depuis le cache, et raterait tout mouvement de compteur."""
    client = ApexClient(api_key="k")
    appels = []

    async def faux_fetch(endpoint, params):
        appels.append(endpoint)
        return {"n": len(appels)}

    client._fetch = faux_fetch

    premier = await client.get("bridge", {"uid": "1"})
    second = await client.get("bridge", {"uid": "1"}, sans_cache=True)

    assert premier == {"n": 1}
    assert second == {"n": 2}, "sans_cache doit refaire l'appel"
    assert len(appels) == 2


@pytest.mark.asyncio
async def test_sans_cache_n_empoisonne_pas_le_cache_des_autres():
    """Un relevé de duel ne doit pas devenir la réponse servie au reste du bot."""
    client = ApexClient(api_key="k")
    valeurs = iter([{"v": "frais"}, {"v": "duel"}])

    async def faux_fetch(endpoint, params):
        return next(valeurs)

    client._fetch = faux_fetch

    await client.get("bridge", {"uid": "1"})                    # met "frais" en cache
    await client.get("bridge", {"uid": "1"}, sans_cache=True)   # ne doit RIEN écrire
    assert await client.get("bridge", {"uid": "1"}) == {"v": "frais"}
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_apex_client_debit.py -v`
Expected: FAIL — `_MIN_INTERVAL` vaut 0.5, et `get()` n'accepte pas `sans_cache`.

- [ ] **Step 3 : Corriger `_MIN_INTERVAL` et son commentaire**

Remplacer `bot/core/apex/client.py:36-37` :

```python
# L'API tolère 5 requêtes/seconde. Mesuré à la clé le 2026-08-13 par montée
# progressive : 3 et 5 req/s passent intégralement, à 8 req/s la 6e requête de
# la seconde prend un 429 dont le CORPS donne la limite en toutes lettres
# (« You have 5 req/s allowed »). Aucun en-tête ne l'annonce — seul
# `x-current-rate` est renvoyé, et il ne dit que le compteur courant.
#
# Ce commentaire annonçait « 2 requêtes/seconde » et bridait le client à 0,5 s :
# 60 % du débit disponible inutilisé, pour tout le projet. Il contredisait
# `watcher.py`, qui disait juste.
_MIN_INTERVAL = 0.2
```

- [ ] **Step 4 : Ajouter le chemin sans cache**

Dans `bot/core/apex/client.py`, remplacer la signature et les deux points de cache de `get()` :

```python
    async def get(self, endpoint: str, params: dict | None = None,
                  *, sans_cache: bool = False) -> Any:
        """La réponse de l'endpoint, depuis le cache si elle y est encore fraîche.

        Une erreur est retournée sous forme de chaîne et n'entre jamais dans le
        cache : une panne d'une seconde condamnerait l'endpoint tout son TTL.

        `sans_cache` court-circuite le cache dans les DEUX sens — ni lu, ni
        écrit. Le duel sonde à 2 s alors que le TTL de `bridge` est de 15 s :
        sans ce chemin, il verrait sept relevés sur huit depuis la mémoire et
        raterait les mouvements de compteurs. Et ne pas écrire non plus évite
        qu'un relevé de duel devienne la réponse servie au reste du bot.
        """
        key = (endpoint, tuple(sorted((params or {}).items())))
        if not sans_cache:
            cached = self._cache.get(key)
            if cached and cached[0] > self._now():
                return cached[1]

        try:
            value = await self._fetch(endpoint, params or {})
        except httpx.HTTPStatusError as exc:
            logger.error("Apex {ep} HTTP {code}", ep=endpoint, code=exc.response.status_code)
            return f"Apex API error (HTTP {exc.response.status_code})"
        except Exception as exc:
            logger.error("Apex {ep} error: {e}", ep=endpoint, e=exc)
            return f"Apex API error: {exc}"

        if not sans_cache:
            ttl = self._ttl.get(endpoint, _FALLBACK_TTL)
            self._cache[key] = (self._now() + ttl, value)
            self._purger()
        return value
```

- [ ] **Step 5 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_apex_client_debit.py -v`
Expected: 3 passed

- [ ] **Step 6 : Vérifier la non-régression du client**

Run: `python3 -m pytest tests/ -k "apex" -q`
Expected: aucun échec nouveau.

- [ ] **Step 7 : Commit**

```bash
git add bot/core/apex/client.py tests/test_apex_client_debit.py
git commit -m "fix(apex): le client était bridé à 2 req/s alors que l'API en autorise 5

Mesuré à la clé : 3 et 5 req/s passent, à 8 req/s la 6e requête de la seconde
prend un 429 dont le corps dit « You have 5 req/s allowed ». Le commentaire de
client.py annonçait 2 et en tirait _MIN_INTERVAL = 0.5 — 60 % du débit payé
inutilisé, pour tout le projet, et en contradiction avec watcher.py.

Ajoute aussi un chemin sans_cache dans les deux sens : le duel sonde à 2 s
alors que le TTL de bridge est de 15 s, il ne verrait qu'un relevé sur huit."
```

---

## Task 2 : Lire les trackers de kills bruts

**Files:**
- Modify: `bot/core/apex/reader.py` (ajout d'une fonction publique, aucune signature existante touchée)
- Test: `tests/test_apex_kill_trackers.py` (créer)

**Interfaces:**
- Produces: `read_kill_trackers(payload: dict) -> dict[str, int]` — clé de tracker → valeur, pour tous les trackers de kills de `total` **et** de la légende sélectionnée. Les clés de légende sont préfixées `legend:`.

**Pourquoi cette fonction existe :** `_read_stats()` normalise par notion et prend le **premier** alias trouvé (`Career Kills` avant `BR Kills`, avec un `break`). Si un joueur a `Career Kills` gelé et `BR Kills` vivant, `stats["kills"]` ne bougerait **jamais** — le duel annoncerait 0 à quelqu'un qui a joué. Le duel a besoin des compteurs bruts pour prendre le maximum de leurs deltas.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_apex_kill_trackers.py
"""Les trackers de kills BRUTS, pour un delta de partie.

`_read_stats` ne convient pas : il prend le PREMIER alias connu et jette les
autres. Un joueur dont « Career Kills » est gelé (tracker retiré de sa bannière,
valeur figée au jour du retrait) et dont « BR Kills » est vivant verrait son
score bloqué à zéro.
"""
from bot.core.apex.reader import read_kill_trackers


def test_prend_tous_les_trackers_de_kills_de_total():
    payload = {
        "total": {
            "career_kills": {"name": "Career Kills", "value": 18788},
            "specialEvent_kills": {"name": "BR Kills", "value": 8528},
            "specialEvent_damage": {"name": "BR Damage", "value": 27324446},
        }
    }
    assert read_kill_trackers(payload) == {
        "career_kills": 18788,
        "specialEvent_kills": 8528,
    }


def test_inclut_les_trackers_de_la_legende_selectionnee_prefixes():
    """`legends.selected.data` est une LISTE, là où `total` est un dict.
    Ne traiter que la seconde forme rend les stats de légende vides EN SILENCE."""
    payload = {
        "total": {"career_kills": {"name": "Career Kills", "value": 100}},
        "legends": {"selected": {"LegendName": "Mirage", "data": [
            {"name": "BR Kills", "value": 5973, "key": "specialEvent_kills"},
            {"name": "Bamboozles", "value": 4210, "key": "bamboozles"},
        ]}},
    }
    assert read_kill_trackers(payload) == {
        "career_kills": 100,
        "legend:specialEvent_kills": 5973,
    }


def test_ignore_les_valeurs_non_numeriques():
    payload = {"total": {"k": {"name": "BR Kills", "value": "No game this split"}}}
    assert read_kill_trackers(payload) == {}


def test_paye_le_payload_casse_sans_lever():
    for casse in ({}, {"total": None}, {"total": []}, {"legends": {"selected": {"data": {}}}}):
        assert read_kill_trackers(casse) == {}


def test_une_liste_ne_traverse_pas_le_or():
    """`or {}` ne protège pas d'un type inattendu : une LISTE est vraie."""
    assert read_kill_trackers({"total": [1, 2, 3]}) == {}
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_apex_kill_trackers.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_kill_trackers'`

- [ ] **Step 3 : Implémenter**

Ajouter à la fin de `bot/core/apex/reader.py` :

```python
def read_kill_trackers(payload: Any) -> dict[str, int]:
    """Tous les compteurs de kills BRUTS : clé de tracker → valeur.

    `_read_stats()` ne convient pas pour mesurer une partie. Il normalise par
    notion et retient le PREMIER alias connu (« Career Kills » avant « BR
    Kills »), donc un joueur dont ce premier tracker est GELÉ — retiré de sa
    bannière, valeur figée au jour du retrait — verrait son compteur immobile
    quoi qu'il fasse en jeu. Mesuré le 2026-08-13 : `career_kills` affichait
    10 989 pour un joueur qui en avait 18 782, et n'a bougé qu'au ré-épinglage.

    On rend donc TOUS les trackers, sans en préférer aucun. L'appelant prendra
    le MAXIMUM de leurs deltas — jamais la somme : les quatre bougent du même
    montant à chaque kill, les additionner quadruplerait le score.

    Les trackers de la légende sélectionnée sont préfixés `legend:` : ils
    portent parfois la même clé que ceux de `total` sans compter la même chose.
    """
    trackers: dict[str, int] = {}

    total = payload.get("total") if isinstance(payload, dict) else None
    if isinstance(total, dict):
        for cle, entree in total.items():
            if not isinstance(entree, dict):
                continue
            if "kill" not in str(entree.get("name", "")).lower() and "kill" not in str(cle).lower():
                continue
            valeur = _num(entree.get("value"))
            if valeur is not None:
                trackers[str(cle)] = int(valeur)

    legendes = payload.get("legends") if isinstance(payload, dict) else None
    selected = (legendes or {}).get("selected") if isinstance(legendes, dict) else None
    data = (selected or {}).get("data") if isinstance(selected, dict) else None
    # `data` est une LISTE ici, un DICT dans `total` — les deux formes coexistent
    # dans le même payload.
    if isinstance(data, list):
        for entree in data:
            if not isinstance(entree, dict):
                continue
            cle = str(entree.get("key", ""))
            if "kill" not in str(entree.get("name", "")).lower() and "kill" not in cle.lower():
                continue
            valeur = _num(entree.get("value"))
            if valeur is not None and cle:
                trackers[f"legend:{cle}"] = int(valeur)

    return trackers
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_apex_kill_trackers.py -v`
Expected: 5 passed

- [ ] **Step 5 : Vérifier contre un payload réel**

Run:
```bash
python3 -c "
import json, asyncio, httpx
from pathlib import Path
from bot.core.apex.reader import read_kill_trackers
key = next(l.split('=',1)[1].strip() for l in Path('.env').read_text().splitlines() if l.startswith('APEX_API_KEY='))
async def m():
    async with httpx.AsyncClient(base_url='https://api.mozambiquehe.re') as c:
        r = await c.get('/bridge', headers={'Authorization': key}, params={'uid':'1012242925358','platform':'PC'})
        print(read_kill_trackers(r.json()))
asyncio.run(m())"
```
Expected: un dict contenant au moins `career_kills`, `specialEvent_kills` et une clé `legend:…`.

- [ ] **Step 6 : Commit**

```bash
git add bot/core/apex/reader.py tests/test_apex_kill_trackers.py
git commit -m "feat(apex): lire les trackers de kills bruts, pour mesurer une partie

_read_stats normalise par notion et retient le PREMIER alias (Career Kills
avant BR Kills, avec un break). Un joueur dont ce tracker est gelé — retiré de
sa bannière, valeur figée au retrait — aurait un compteur immobile quoi qu'il
fasse : le duel lui annoncerait 0 kill après trois parties.

read_kill_trackers rend tous les compteurs sans en préférer aucun, en gérant
les deux formes du payload (total = dict, legends.selected.data = liste)."
```

---

## Task 3 : Le score d'une manche

**Files:**
- Create: `bot/core/apex/duel.py`
- Test: `tests/test_apex_duel_score.py`

**Interfaces:**
- Consumes: `read_kill_trackers()` (Task 2)
- Produces:
  - `PLAFOND_KILLS_MANCHE: int = 30`
  - `score_manche(avant: dict[str, int], apres: dict[str, int], *, plafond: int = PLAFOND_KILLS_MANCHE) -> int | None` — le score, ou `None` si non mesurable.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_apex_duel_score.py
"""Le score d'une manche, mesuré sur des deltas de compteurs.

Trois faits établis le 2026-08-13 sur des parties réelles :
  - les quatre trackers bougent du MÊME montant (4 kills → +4 partout) ;
  - un tracker ré-épinglé saute de milliers d'un coup (+7793 sans un kill) ;
  - la Mixtape n'incrémente rien du tout (10 kills → 0).
"""
from bot.core.apex.duel import PLAFOND_KILLS_MANCHE, score_manche


def test_quatre_kills_donnent_quatre_pas_seize():
    """Tous les trackers bougent ensemble : les sommer quadruplerait le score."""
    avant = {"career_kills": 18782, "specialEvent_kills": 8522,
             "legend:career_kills": 18782, "legend:specialEvent_kills": 5967}
    apres = {"career_kills": 18786, "specialEvent_kills": 8526,
             "legend:career_kills": 18786, "legend:specialEvent_kills": 5971}
    assert score_manche(avant, apres) == 4


def test_un_seul_tracker_vivant_suffit():
    """Career Kills gelé, BR Kills vivant : le score est celui qui bouge."""
    avant = {"career_kills": 10989, "specialEvent_kills": 8522}
    apres = {"career_kills": 10989, "specialEvent_kills": 8524}
    assert score_manche(avant, apres) == 2


def test_un_tracker_epingle_en_cours_de_manche_est_ecarte():
    """+7793 mesuré au ré-épinglage, sans un kill joué. Sans ce filtre, il
    emporterait le duel."""
    avant = {"career_kills": 10989, "specialEvent_kills": 8522}
    apres = {"career_kills": 18782, "specialEvent_kills": 8524}
    assert score_manche(avant, apres) == 2


def test_cle_absente_du_releve_initial_ignoree():
    avant = {"career_kills": 100}
    apres = {"career_kills": 103, "nouveau_kills": 99999}
    assert score_manche(avant, apres) == 3


def test_delta_negatif_ignore():
    avant = {"a_kills": 100, "b_kills": 50}
    apres = {"a_kills": 90, "b_kills": 52}
    assert score_manche(avant, apres) == 2


def test_zero_kill_reel_vaut_zero_pas_none():
    """Une manche sans kill est un résultat, pas une absence de mesure."""
    avant = {"career_kills": 100, "specialEvent_kills": 50}
    apres = {"career_kills": 100, "specialEvent_kills": 50}
    assert score_manche(avant, apres) == 0


def test_aucun_tracker_commun_donne_none():
    """Non mesurable — jamais zéro. Un zéro inventé est un mensonge."""
    assert score_manche({}, {"career_kills": 100}) is None
    assert score_manche({"career_kills": 100}, {}) is None


def test_tous_les_deltas_ecartes_donne_none():
    avant = {"a_kills": 10}
    apres = {"a_kills": 10_000}
    assert score_manche(avant, apres) is None


def test_le_plafond_est_haut_pour_ne_jamais_mordre_sur_un_vrai_score():
    """Les records connus tournent autour de 25-30 kills."""
    assert PLAFOND_KILLS_MANCHE >= 25
    avant, apres = {"k_kills": 0}, {"k_kills": 25}
    assert score_manche(avant, apres) == 25
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_apex_duel_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.core.apex.duel'`

- [ ] **Step 3 : Implémenter**

Créer `bot/core/apex/duel.py` :

```python
# bot/core/apex/duel.py
"""Le duel Apex : machine à états PURE, sans réseau ni I/O.

Elle reçoit des relevés et rend des décisions ; tout se teste en rejouant une
séquence, sans toucher l'API. Le réseau, la persistance et les effets vivent
dans `duel_runner.py`.

Spec : docs/superpowers/specs/2026-08-13-apex-duel-points-chaine-design.md
"""
from __future__ import annotations

# Au-delà de ce delta sur une seule manche, ce n'est pas un score : c'est un
# tracker qu'on vient d'épingler. Mesuré le 2026-08-13 : +7793 d'un coup, sans
# un kill joué. Le plafond est volontairement haut — les records connus en Apex
# tournent autour de 25-30 kills — pour ne jamais mordre sur un vrai résultat.
PLAFOND_KILLS_MANCHE = 30


def score_manche(avant: dict[str, int], apres: dict[str, int],
                 *, plafond: int = PLAFOND_KILLS_MANCHE) -> int | None:
    """Les kills faits entre deux relevés, ou None si la manche n'est pas mesurable.

    Le MAXIMUM des deltas, jamais leur somme : les quatre trackers bougent du
    même montant à chaque kill (4 kills → +4 partout), donc les additionner
    donnerait 16. C'est le piège exactement symétrique de la règle d'addition
    qui vaut, elle, pour un total carrière.

    Seules les clés présentes dans les DEUX relevés comptent : un tracker apparu
    en cours de manche n'a pas de point de départ.

    `None` et non `0` quand rien n'est mesurable : un zéro inventé est un
    mensonge, pas une valeur par défaut. La Mixtape, qui n'incrémente aucun
    compteur (10 kills → 0, mesuré), tombe dans ce cas.
    """
    deltas = []
    for cle, depart in avant.items():
        arrivee = apres.get(cle)
        if arrivee is None:
            continue
        delta = arrivee - depart
        if delta < 0 or delta > plafond:
            continue
        deltas.append(delta)
    if not deltas:
        return None
    return max(deltas)
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_apex_duel_score.py -v`
Expected: 9 passed

- [ ] **Step 5 : Commit**

```bash
git add bot/core/apex/duel.py tests/test_apex_duel_score.py
git commit -m "feat(apex): score d'une manche de duel, au max des deltas

Les quatre trackers de kills bougent du même montant à chaque kill (4 kills →
+4 partout, mesuré) : les sommer donnerait 16. On prend donc le maximum.

Trois filtres adossés à des mesures : clé absente au départ (tracker apparu en
route), delta négatif, et delta au-delà de 30 (signature d'un épinglage, +7793
observé sans un kill joué). Si tout est écarté, la manche est non mesurable —
None et jamais 0, un zéro inventé étant un mensonge."
```

---

## Task 4 : La machine à états du duel

**Files:**
- Modify: `bot/core/apex/duel.py`
- Test: `tests/test_apex_duel_machine.py`

**Interfaces:**
- Consumes: `score_manche()` (Task 3)
- Produces:
  - `Etat` (str enum) : `RESOLUTION`, `ATTENTE_SQUAD`, `MANCHE`, `ENTRE_MANCHES`, `VERDICT`, `ABANDON`
  - `Releve` dataclass : `t: float`, `azrael_in_game: bool`, `viewer_in_game: bool`, `kills_azrael: dict[str,int]`, `kills_viewer: dict[str,int]`
  - `Duel` dataclass avec `avancer(releve) -> list[Evenement]`, `to_dict()`, `from_dict()`
  - `Evenement` : `(type, données)` — types `manche_debut`, `manche_fin`, `verdict`, `abandon`

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_apex_duel_machine.py
"""La machine à états, rejouée sur des séquences de relevés.

Les durées imitent les mesures réelles du 2026-08-13 : partie de ~8 min,
39 s seulement entre un retour au lobby et le lancement suivant.
"""
import pytest

from bot.core.apex.duel import Duel, Etat, Releve

K0 = {"career_kills": 1000, "specialEvent_kills": 500}


def kills(n):
    return {"career_kills": 1000 + n, "specialEvent_kills": 500 + n}


def duel_pret():
    d = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7", manches=3)
    d.etat = Etat.ATTENTE_SQUAD
    return d


def test_la_manche_demarre_quand_LES_DEUX_sont_en_partie():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=False,
                     kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.ATTENTE_SQUAD, "Azraël seul ne lance pas le duel"

    evts = d.avancer(Releve(t=2, azrael_in_game=True, viewer_in_game=True,
                            kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.MANCHE
    assert [e.type for e in evts] == ["manche_debut"]


def test_la_manche_se_clot_quand_azrael_revient_au_lobby():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    evts = d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=kills(4), kills_viewer=kills(2)))
    assert d.etat is Etat.ENTRE_MANCHES
    assert [e.type for e in evts] == ["manche_fin"]
    assert evts[0].donnees["azrael"] == 4
    assert evts[0].donnees["viewer"] == 2


def test_trois_manches_puis_verdict_sur_la_SOMME():
    d = duel_pret()
    a = v = 0
    for i, (ka, kv) in enumerate([(4, 2), (0, 5), (3, 1)]):
        a, v = a + ka, v + kv
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=kills(a - ka), kills_viewer=kills(v - kv)))
        evts = d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False, viewer_in_game=False,
                                kills_azrael=kills(a), kills_viewer=kills(v)))
    assert d.etat is Etat.VERDICT
    verdict = [e for e in evts if e.type == "verdict"][0]
    assert verdict.donnees["azrael"] == 7
    assert verdict.donnees["viewer"] == 8
    assert verdict.donnees["gagnant"] == "viewer"


def test_la_baseline_est_reprise_a_CHAQUE_manche():
    """Un tracker épinglé entre deux manches saute de milliers. La nouvelle
    baseline doit l'absorber au lieu de le compter."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(3), kills_viewer=kills(1)))
    # Entre les manches, le viewer épingle un tracker : +7793 d'un coup.
    saute = {"career_kills": 1000 + 1 + 7793, "specialEvent_kills": 500 + 1}
    d.avancer(Releve(t=519, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=kills(3), kills_viewer=saute))
    apres = {"career_kills": saute["career_kills"], "specialEvent_kills": 500 + 3}
    evts = d.avancer(Releve(t=1000, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=kills(5), kills_viewer=apres))
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["viewer"] == 2, "le saut d'épinglage doit être absorbé"


def test_manche_non_mesurable_annoncee_et_non_comptee():
    """Mixtape : aucun compteur ne bouge alors que la partie a bien eu lieu."""
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael={}, kills_viewer={}))
    evts = d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael={}, kills_viewer={}))
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["azrael"] is None
    assert fin.donnees["viewer"] is None
    assert fin.donnees["mesurable"] is False


def test_duel_entierement_non_mesurable_est_un_abandon_pas_un_nul():
    """0-0 sans qu'aucun compteur n'ait bougé = Mixtape ou API muette. Le duel
    n'est pas arbitrable : remboursement, jamais un faux match nul annoncé."""
    d = duel_pret()
    for i in range(3):
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael={}, kills_viewer={}))
        evts = d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False,
                                viewer_in_game=False, kills_azrael={}, kills_viewer={}))
    assert d.etat is Etat.ABANDON
    abandon = [e for e in evts if e.type == "abandon"][0]
    assert abandon.donnees["rembourser"] is True
    assert "mixtape" in abandon.donnees["motif"].lower()


def test_egalite_vraie_est_un_match_nul_sans_remboursement():
    d = duel_pret()
    for i in range(3):
        d.avancer(Releve(t=i * 600, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=kills(i * 2), kills_viewer=kills(i * 2)))
        evts = d.avancer(Releve(t=i * 600 + 480, azrael_in_game=False, viewer_in_game=False,
                                kills_azrael=kills(i * 2 + 2), kills_viewer=kills(i * 2 + 2)))
    verdict = [e for e in evts if e.type == "verdict"][0]
    assert verdict.donnees["gagnant"] is None
    assert verdict.donnees["azrael"] == verdict.donnees["viewer"] == 6


def test_personne_ne_rejoint_dans_le_delai_abandon_et_remboursement():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=K0, kills_viewer=K0))
    evts = d.avancer(Releve(t=16 * 60, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.ABANDON
    assert [e for e in evts if e.type == "abandon"][0].donnees["rembourser"] is True


def test_le_duel_survit_a_un_rebuild():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    repris = Duel.from_dict(d.to_dict())
    assert repris.etat is d.etat
    assert repris.scores == d.scores
    assert repris.viewer_nom == "Bob"


def test_recommencer_remet_les_compteurs_a_zero():
    d = duel_pret()
    d.avancer(Releve(t=0, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=K0, kills_viewer=K0))
    d.avancer(Releve(t=480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(4), kills_viewer=kills(2)))
    d.recommencer()
    assert d.scores == []
    assert d.etat is Etat.ATTENTE_SQUAD
    assert d.viewer_nom == "Bob", "le duelliste garde sa place"
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_apex_duel_machine.py -v`
Expected: FAIL — `ImportError: cannot import name 'Duel'`

- [ ] **Step 3 : Implémenter**

Ajouter à `bot/core/apex/duel.py` (au-dessus de `score_manche`, après les imports) :

```python
from dataclasses import dataclass, field
from enum import Enum

# Le viewer a ce délai pour rejoindre le squad. Au-delà, remboursement : un
# viewer qui a payé et ne voit rien est le pire résultat possible.
ATTENTE_SQUAD_S = 15 * 60


class Etat(str, Enum):
    RESOLUTION = "resolution"
    ATTENTE_SQUAD = "attente_squad"
    MANCHE = "manche"
    ENTRE_MANCHES = "entre_manches"
    VERDICT = "verdict"
    ABANDON = "abandon"


@dataclass(frozen=True)
class Releve:
    t: float
    azrael_in_game: bool
    viewer_in_game: bool
    kills_azrael: dict[str, int]
    kills_viewer: dict[str, int]


@dataclass(frozen=True)
class Evenement:
    type: str
    donnees: dict


@dataclass
class Duel:
    viewer_nom: str
    viewer_uid: str
    azrael_uid: str
    manches: int = 3
    redemption_id: str = ""
    etat: Etat = Etat.RESOLUTION
    # Un score par manche jouée : {"azrael": int|None, "viewer": int|None}
    scores: list[dict] = field(default_factory=list)
    _base_azrael: dict = field(default_factory=dict)
    _base_viewer: dict = field(default_factory=dict)
    _t_attente: float | None = None

    # -- Totaux -------------------------------------------------------------
    @property
    def total_azrael(self) -> int:
        return sum(s["azrael"] or 0 for s in self.scores)

    @property
    def total_viewer(self) -> int:
        return sum(s["viewer"] or 0 for s in self.scores)

    @property
    def manche_courante(self) -> int:
        """1-indexée, pour l'affichage."""
        return min(len(self.scores) + 1, self.manches)

    def recommencer(self) -> None:
        """Remet les compteurs à zéro, même duelliste (§7 de la spec)."""
        self.scores = []
        self._base_azrael = {}
        self._base_viewer = {}
        self._t_attente = None
        self.etat = Etat.ATTENTE_SQUAD

    # -- Persistance --------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "viewer_nom": self.viewer_nom, "viewer_uid": self.viewer_uid,
            "azrael_uid": self.azrael_uid, "manches": self.manches,
            "redemption_id": self.redemption_id, "etat": self.etat.value,
            "scores": self.scores, "base_azrael": self._base_azrael,
            "base_viewer": self._base_viewer, "t_attente": self._t_attente,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Duel":
        duel = cls(
            viewer_nom=d.get("viewer_nom", ""), viewer_uid=d.get("viewer_uid", ""),
            azrael_uid=d.get("azrael_uid", ""), manches=int(d.get("manches", 3)),
            redemption_id=d.get("redemption_id", ""),
            etat=Etat(d.get("etat", Etat.RESOLUTION.value)),
            scores=list(d.get("scores") or []),
        )
        duel._base_azrael = dict(d.get("base_azrael") or {})
        duel._base_viewer = dict(d.get("base_viewer") or {})
        duel._t_attente = d.get("t_attente")
        return duel

    # -- Le cœur ------------------------------------------------------------
    def avancer(self, r: Releve) -> list[Evenement]:
        """Fait avancer le duel d'un relevé, et rend ce qu'il faut annoncer."""
        if self.etat in (Etat.VERDICT, Etat.ABANDON, Etat.RESOLUTION):
            return []

        if self.etat in (Etat.ATTENTE_SQUAD, Etat.ENTRE_MANCHES):
            if self._t_attente is None:
                self._t_attente = r.t
            # Les DEUX en partie : la manche commence. On ne peut pas vérifier
            # qu'ils sont dans le même squad — l'API ne donne pas la composition
            # d'une équipe (§2 de la spec).
            if r.azrael_in_game and r.viewer_in_game:
                self._base_azrael = dict(r.kills_azrael)
                self._base_viewer = dict(r.kills_viewer)
                self._t_attente = None
                self.etat = Etat.MANCHE
                return [Evenement("manche_debut", {"manche": self.manche_courante,
                                                   "sur": self.manches})]
            if r.t - self._t_attente >= ATTENTE_SQUAD_S:
                self.etat = Etat.ABANDON
                return [Evenement("abandon", {
                    "rembourser": True,
                    "motif": "personne n'a rejoint le squad dans le délai",
                })]
            return []

        if self.etat is Etat.MANCHE:
            # C'est le retour au lobby d'Azraël qui clôt la manche : les
            # compteurs y sont déjà à jour, mesuré deux fois sur deux.
            if r.azrael_in_game:
                return []
            sa = score_manche(self._base_azrael, r.kills_azrael)
            sv = score_manche(self._base_viewer, r.kills_viewer)
            self.scores.append({"azrael": sa, "viewer": sv})
            evts = [Evenement("manche_fin", {
                "manche": len(self.scores), "sur": self.manches,
                "azrael": sa, "viewer": sv,
                "mesurable": sa is not None or sv is not None,
                "total_azrael": self.total_azrael, "total_viewer": self.total_viewer,
            })]
            if len(self.scores) >= self.manches:
                evts.extend(self._clore())
            else:
                self.etat = Etat.ENTRE_MANCHES
                self._t_attente = None
            return evts

        return []

    def _clore(self) -> list[Evenement]:
        """Verdict, ou abandon si rien n'a jamais été mesurable."""
        # Aucune manche mesurable : Mixtape (10 kills → 0 compteur, mesuré) ou
        # API muette. Dans les deux cas le duel n'est pas arbitrable. Annoncer
        # un match nul serait mentir avec aplomb.
        if all(s["azrael"] is None and s["viewer"] is None for s in self.scores):
            self.etat = Etat.ABANDON
            return [Evenement("abandon", {
                "rembourser": True,
                "motif": ("aucun kill n'a été enregistré de tout le duel — "
                          "la Mixtape ne compte pas les kills, ou l'API n'a rien vu"),
            })]
        self.etat = Etat.VERDICT
        a, v = self.total_azrael, self.total_viewer
        return [Evenement("verdict", {
            "azrael": a, "viewer": v,
            "gagnant": None if a == v else ("azrael" if a > v else "viewer"),
            "scores": list(self.scores),
        })]
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_apex_duel_machine.py -v`
Expected: 10 passed

- [ ] **Step 5 : Lancer toute la suite du duel**

Run: `python3 -m pytest tests/test_apex_duel_score.py tests/test_apex_duel_machine.py tests/test_apex_kill_trackers.py -q`
Expected: 24 passed

- [ ] **Step 6 : Commit**

```bash
git add bot/core/apex/duel.py tests/test_apex_duel_machine.py
git commit -m "feat(apex): machine à états du duel, pure et rejouable

Une baseline par MANCHE et non pour tout le duel : un tracker épinglé entre
deux parties saute de milliers (+7793 mesuré), et un delta global l'aurait
compté comme un score. La nouvelle baseline l'absorbe.

Un 0-0 dont aucun compteur n'a jamais bougé n'est pas un match nul mais une
Mixtape ou une API muette — donc un abandon remboursé, pas un verdict."
```

---

## Task 5 : Rembourser une redemption

**Files:**
- Modify: `bot/twitch/api.py`
- Test: `tests/test_twitch_refund.py`

**Interfaces:**
- Produces: `TwitchAPI.refund_redemption(reward_id: str, redemption_id: str) -> bool`

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_twitch_refund.py
"""Annuler une redemption REND les points au viewer (statut CANCELED).

Chaque refus du duel doit rembourser : un viewer qui a payé et ne voit rien
est le pire résultat possible.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _api(reponse):
    from bot.twitch.api import TwitchAPI
    tm = MagicMock()
    tm.streamer_token = "tok"
    tm.refresh = AsyncMock(return_value=True)
    api = TwitchAPI(tm, client_id="cid", broadcaster_id="123")
    client = MagicMock()
    client.patch = AsyncMock(return_value=reponse)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return api, client


def _resp(status, payload):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = str(payload)
    return r


@pytest.mark.asyncio
async def test_remboursement_reussi(monkeypatch):
    api, client = _api(_resp(200, {"data": [{"status": "CANCELED"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is True
    _, kwargs = client.patch.call_args
    assert kwargs["json"] == {"status": "CANCELED"}
    assert kwargs["params"]["reward_id"] == "rw"
    assert kwargs["params"]["id"] == "rd"


@pytest.mark.asyncio
async def test_un_200_qui_ne_dit_pas_CANCELED_est_un_echec(monkeypatch):
    """Sur Helix, un 200 ne prouve pas que l'ordre est passé — ce projet l'a
    déjà payé avec is_sent. On lit le CORPS."""
    api, client = _api(_resp(200, {"data": [{"status": "UNFULFILLED"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False


@pytest.mark.asyncio
async def test_corps_vide_est_un_echec(monkeypatch):
    api, client = _api(_resp(200, {"data": []}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False


@pytest.mark.asyncio
async def test_erreur_http_ne_leve_pas(monkeypatch):
    api, client = _api(_resp(403, {"error": "Forbidden"}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_twitch_refund.py -v`
Expected: FAIL — `AttributeError: 'TwitchAPI' object has no attribute 'refund_redemption'`

- [ ] **Step 3 : Implémenter**

Ajouter à `bot/twitch/api.py`, dans la classe, à côté de `get_stream` :

```python
    REDEMPTIONS_URL = "https://api.twitch.tv/helix/channel_points/custom_rewards/redemptions"

    async def refund_redemption(self, reward_id: str, redemption_id: str) -> bool:
        """Annule une redemption — les points sont RENDUS au viewer.

        Utilise le token STREAMER : `channel:manage:redemptions` est un scope de
        la chaîne, le token du bot ne l'a pas.

        Comme partout sur Helix, un 200 ne prouve pas que l'ordre est passé : on
        vérifie que le corps renvoie bien `status: CANCELED`. Ce projet a déjà
        payé la leçon avec `is_sent` sur l'envoi de messages.
        """
        if not (reward_id and redemption_id):
            logger.warning("Remboursement impossible : reward_id ou redemption_id vide")
            return False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.patch(
                    self.REDEMPTIONS_URL,
                    params={"broadcaster_id": self._broadcaster_id,
                            "reward_id": reward_id, "id": redemption_id},
                    json={"status": "CANCELED"},
                    headers={"Authorization": f"Bearer {self._tm.streamer_token}",
                             "Client-Id": self._client_id},
                    timeout=10,
                )
            if resp.status_code != 200:
                logger.error("Remboursement refusé HTTP {c} : {t}",
                             c=resp.status_code, t=resp.text[:200])
                return False
            data = (resp.json() or {}).get("data") or []
            statut = (data[0] or {}).get("status") if data else None
            if statut != "CANCELED":
                logger.error("Remboursement non appliqué — statut rendu : {s}", s=statut)
                return False
            logger.info("Points rendus au viewer (redemption {r})", r=redemption_id)
            return True
        except Exception as exc:  # noqa: BLE001 — un remboursement raté ne tue pas le duel
            logger.error("Remboursement en erreur : {e}", e=exc)
            return False
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_twitch_refund.py -v`
Expected: 4 passed

- [ ] **Step 5 : Commit**

```bash
git add bot/twitch/api.py tests/test_twitch_refund.py
git commit -m "feat(twitch): rembourser une redemption de points de chaîne

PATCH .../redemptions avec status=CANCELED rend les points au viewer. Utilise
le token streamer — channel:manage:redemptions est un scope de la chaîne.

Le corps est vérifié, pas seulement le statut : sur Helix un 200 ne prouve pas
que l'ordre est passé, leçon déjà payée avec is_sent."
```

---

## Task 6 : Scopes OAuth et correctif du redirect_uri

**Files:**
- Modify: `bot/dashboard/routes/twitch_auth.py:16` et `:111`, `:150`
- Modify: `bot/dashboard/routes/setup.py:72`, `:140`, `:148`
- Test: `tests/dashboard/test_twitch_auth_scopes.py`

⚠️ **`bot/dashboard/static/app.js:3652` porte le libellé des scopes mais est GELÉ.** Si la session concurrente est terminée au moment d'exécuter cette tâche, mettre à jour `STREAMER_SCOPES` ; sinon, laisser et ouvrir une note — le libellé est cosmétique, il n'empêche pas l'autorisation.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/dashboard/test_twitch_auth_scopes.py
"""Les scopes demandés et l'URI de redirection produite.

Un nouveau token REMPLACE l'ancien avec exactement les scopes demandés :
n'en demander que deux ferait perdre abonnés et bits en silence.
"""
import urllib.parse

from bot.dashboard.routes.twitch_auth import _STREAMER_SCOPES, _base_url_propre


def test_les_quatre_scopes_streamer_sont_demandes():
    scopes = set(_STREAMER_SCOPES.split())
    assert scopes == {
        "channel:read:subscriptions", "bits:read",
        "channel:read:redemptions", "channel:manage:redemptions",
    }


def test_le_slash_final_de_WEB_BASE_URL_est_retire(monkeypatch):
    """Twitch exige une correspondance EXACTE de l'URI enregistrée. Un
    WEB_BASE_URL finissant par « / » produisait un double slash."""
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    assert _base_url_propre("http://fallback") == "https://heywally.fr"


def test_le_fallback_est_nettoye_aussi(monkeypatch):
    monkeypatch.delenv("WEB_BASE_URL", raising=False)
    assert _base_url_propre("http://localhost:8080/") == "http://localhost:8080"


def test_l_uri_de_redirection_n_a_pas_de_double_slash(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://heywally.fr/")
    uri = f"{_base_url_propre('x')}/api/admin/twitch/auth/callback"
    assert "//api" not in uri
    assert uri == "https://heywally.fr/api/admin/twitch/auth/callback"
    # et il survit à l'encodage utilisé dans l'URL d'autorisation
    assert "%2F%2Fapi" not in urllib.parse.quote(uri, safe="")
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/dashboard/test_twitch_auth_scopes.py -v`
Expected: FAIL — `ImportError: cannot import name '_base_url_propre'`, et les scopes ne sont que deux.

- [ ] **Step 3 : Implémenter dans `twitch_auth.py`**

Remplacer la ligne 16 :

```python
# Les QUATRE scopes, pas seulement les nouveaux : un token fraîchement émis
# remplace l'ancien avec exactement ce qu'on lui demande. N'en demander que deux
# ferait perdre les abonnés et les bits sans un mot dans les logs.
# Vérifié le 2026-08-13 via /oauth2/validate : le token en service ne porte rien
# d'autre que ce que ce code demande — contrôle à refaire avant toute évolution.
_STREAMER_SCOPES   = ("channel:read:subscriptions bits:read "
                      "channel:read:redemptions channel:manage:redemptions")
```

Ajouter après les constantes :

```python
def _base_url_propre(defaut: str) -> str:
    """L'URL publique, sans slash final.

    `.rstrip("/")` n'était appliqué qu'à la valeur PAR DÉFAUT, jamais à
    `WEB_BASE_URL` — qui vaut `https://heywally.fr/`. Le `redirect_uri` généré
    portait donc un double slash, et Twitch exige une correspondance exacte avec
    l'URI enregistrée dans l'application.
    """
    return (os.getenv("WEB_BASE_URL", "") or defaut).rstrip("/")
```

Remplacer aux lignes 111 et 150 :

```python
    base_url     = _base_url_propre(str(request.base_url))
```

- [ ] **Step 4 : Répercuter dans `setup.py`**

Aux lignes 72 et 140, remplacer `base_url = os.getenv("WEB_BASE_URL", "")` par :

```python
    from bot.dashboard.routes.twitch_auth import _base_url_propre
    base_url = _base_url_propre("")
```

Et à la ligne 148, aligner les scopes streamer sur `_STREAMER_SCOPES` :

```python
        from bot.dashboard.routes.twitch_auth import _STREAMER_SCOPES
        scope = _STREAMER_SCOPES
```

- [ ] **Step 5 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/dashboard/test_twitch_auth_scopes.py tests/dashboard/test_twitch_auth.py -v`
Expected: tout passe, y compris les tests existants.

- [ ] **Step 6 : Commit**

```bash
git add bot/dashboard/routes/twitch_auth.py bot/dashboard/routes/setup.py tests/dashboard/test_twitch_auth_scopes.py
git commit -m "fix(twitch): scopes points de chaîne, et redirect_uri à double slash

Ajoute channel:read:redemptions et channel:manage:redemptions, en gardant les
deux existants : un nouveau token remplace l'ancien avec exactement les scopes
demandés, et n'en demander que deux perdrait abonnés et bits en silence.

Corrige aussi un défaut dormant : .rstrip('/') n'était appliqué qu'à la valeur
par défaut, jamais à WEB_BASE_URL — qui finit par un slash. L'URI produite
portait un double slash, là où Twitch exige une correspondance exacte."
```

- [ ] **Step 7 : ⚠️ Action manuelle de l'owner, hors code**

Après le rebuild, autoriser depuis **le bouton du dashboard** (lui seul génère un `state` valide ; une URL fabriquée à la main échoue au callback sans rien écrire). Vérifier ensuite :

```bash
curl -s -H "Authorization: OAuth $(grep '^STREAMER_ACCESS_TOKEN=' .env | cut -d= -f2)" \
  https://id.twitch.tv/oauth2/validate | python3 -m json.tool
```
Expected: les quatre scopes présents.

---

## Task 7 : Percevoir l'achat de la récompense

**Files:**
- Create: `bot/twitch/events/redemptions.py`
- Modify: `bot/twitch/events/__init__.py` (bloc des souscriptions streamer, ~ligne 114-126)
- Modify: `config.yaml`
- Test: `tests/test_twitch_redemptions.py`

**Interfaces:**
- Consumes: `TwitchAPI.refund_redemption()` (Task 5)
- Produces: `handle_redemption(bot, event) -> None`, `_est_notre_recompense(bot, reward_id) -> bool`

- [ ] **Step 1 : Ajouter la configuration**

Dans `config.yaml`, sous la section `apex` existante :

```yaml
apex:
  streamer_account: Azrael_ttv
  streamer_platform: PC
  duel:
    # ID de la récompense de points de chaîne, lu dans la console Twitch.
    # Vide = duel désactivé. Filtrage par ID et JAMAIS par titre : un titre se
    # renomme d'un clic et casserait tout en silence.
    reward_id: ""
    manches: 3
    cadence_s: 2
    attente_squad_min: 15
    plafond_kills_manche: 30
```

- [ ] **Step 2 : Écrire les tests qui échouent**

```python
# tests/test_twitch_redemptions.py
"""L'achat de la récompense ouvre un duel — ou rembourse, mais ne se tait jamais."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.events.redemptions import _est_notre_recompense, handle_redemption


def _bot(reward_id="RW", duel_en_cours=None):
    bot = MagicMock()
    bot.config.apex.duel.reward_id = reward_id
    bot.api.refund_redemption = AsyncMock(return_value=True)
    bot.duel_runner = MagicMock()
    bot.duel_runner.duel_en_cours = duel_en_cours
    bot.duel_runner.ouvrir = AsyncMock()
    return bot


def _event(reward_id="RW", user="bob", texte="1012242925358"):
    e = MagicMock()
    e.reward.id = reward_id
    e.id = "RD1"
    e.user.name = user
    e.input = texte
    return e


def test_une_autre_recompense_est_ignoree():
    assert _est_notre_recompense(_bot("RW"), "AUTRE") is False
    assert _est_notre_recompense(_bot("RW"), "RW") is True


def test_reward_id_non_configure_n_attrape_rien():
    """Vide = duel désactivé. Sans ce garde, toute récompense de la chaîne
    lancerait un duel."""
    assert _est_notre_recompense(_bot(""), "") is False
    assert _est_notre_recompense(_bot(""), "RW") is False


@pytest.mark.asyncio
async def test_duel_deja_en_cours_rembourse():
    bot = _bot(duel_en_cours=object())
    await handle_redemption(bot, _event())
    bot.api.refund_redemption.assert_awaited_once()
    bot.duel_runner.ouvrir.assert_not_awaited()


@pytest.mark.asyncio
async def test_achat_valide_ouvre_le_duel():
    bot = _bot()
    await handle_redemption(bot, _event(texte="1012242925358"))
    bot.duel_runner.ouvrir.assert_awaited_once()
    args = bot.duel_runner.ouvrir.await_args.kwargs
    assert args["saisie"] == "1012242925358"
    assert args["redemption_id"] == "RD1"
    bot.api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_exception_ne_remonte_jamais():
    """Un handler d'événement ne crashe pas le bot."""
    bot = _bot()
    bot.duel_runner.ouvrir = AsyncMock(side_effect=RuntimeError("boum"))
    await handle_redemption(bot, _event())  # ne doit pas lever
```

- [ ] **Step 3 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_twitch_redemptions.py -v`
Expected: FAIL — module absent.

- [ ] **Step 4 : Implémenter le handler**

Créer `bot/twitch/events/redemptions.py` :

```python
# bot/twitch/events/redemptions.py
"""Achat d'une récompense de points de chaîne → ouverture d'un duel Apex.

Perception passive comme tout événement de stream ici : on alimente le flux,
on ne réveille aucune cadence de parole (`notify_*` absent volontairement).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


def _est_notre_recompense(bot, reward_id: str) -> bool:
    """La récompense configurée, identifiée par son ID.

    Jamais par son titre : un titre se renomme d'un clic dans la console Twitch
    et le duel cesserait de répondre sans un mot dans les logs.

    Un `reward_id` vide DÉSACTIVE le duel — sans ce garde, la moindre
    récompense de la chaîne en lancerait un.
    """
    attendu = str(getattr(bot.config.apex.duel, "reward_id", "") or "")
    return bool(attendu) and str(reward_id) == attendu


async def handle_redemption(bot: "WallyTwitch", event) -> None:
    """Point d'entrée EventSub. N'échoue jamais vers l'appelant."""
    try:
        reward_id = str(getattr(getattr(event, "reward", None), "id", ""))
        if not _est_notre_recompense(bot, reward_id):
            return

        redemption_id = str(getattr(event, "id", ""))
        acheteur = str(getattr(getattr(event, "user", None), "name", "") or "?")
        saisie = str(getattr(event, "input", "") or "")

        logger.info("Duel Apex demandé par {u} (saisie : {s!r})", u=acheteur, s=saisie[:60])

        runner = getattr(bot, "duel_runner", None)
        if runner is None:
            logger.error("Duel demandé mais aucun runner câblé — remboursement")
            await bot.api.refund_redemption(reward_id, redemption_id)
            return

        if runner.duel_en_cours is not None:
            logger.info("Duel déjà en cours — remboursement de {u}", u=acheteur)
            await bot.api.refund_redemption(reward_id, redemption_id)
            return

        await runner.ouvrir(
            acheteur=acheteur, saisie=saisie,
            reward_id=reward_id, redemption_id=redemption_id,
        )
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("Redemption en erreur : {e}", e=exc)
```

- [ ] **Step 5 : Souscrire à l'événement**

Dans `bot/twitch/events/__init__.py`, ajouter à la liste des souscriptions **streamer** (celle qui contient `sub`, `resub`, `cheer`) :

```python
                ("duel_redemption", lambda: client.subscribe_channel_points_redeemed(
                    broadcaster=broadcaster_id, token=streamer_token)),
```

Et dans le docstring d'en-tête, sous « Streamer token » :

```
        channel.channel_points_custom_reward_redemption.add — channel:read:redemptions
```

- [ ] **Step 6 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_twitch_redemptions.py -v`
Expected: 5 passed

- [ ] **Step 7 : Vérifier que le boot ne casse pas**

Run: `python3 -m pytest tests/ -k "canari or boot" -q && python3 -c "import bot.twitch.events.redemptions"`
Expected: aucun échec.

- [ ] **Step 8 : Commit**

```bash
git add bot/twitch/events/redemptions.py bot/twitch/events/__init__.py config.yaml tests/test_twitch_redemptions.py
git commit -m "feat(twitch): percevoir l'achat de la récompense de duel

subscribe_channel_points_redeemed existe nativement dans twitchio v2 — pas de
patch runtime comme pour channel.chat.message.

Filtrage par ID de récompense et jamais par titre, un titre se renommant d'un
clic. Un reward_id vide désactive le duel plutôt que d'attraper toutes les
récompenses de la chaîne."
```

---

## Task 8 : Le runner — sonde, persistance, effets

**Files:**
- Create: `bot/core/apex/duel_runner.py`
- Test: `tests/test_apex_duel_runner.py`

**Interfaces:**
- Consumes: `Duel`, `Releve`, `Etat` (Task 4), `read_kill_trackers` (Task 2), `ApexClient.get(..., sans_cache=True)` (Task 1), `refund_redemption` (Task 5)
- Produces: `DuelRunner(client, db, api, feed, annoncer)` avec `.duel_en_cours`, `.ouvrir(...)`, `.tick()`, `.charger()`, `.annuler(motif)`, `.recommencer()`

**Clé de persistance :** `apex:duel` dans `bot_state`, comme `apex:live_baseline` de `watcher.py`.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_apex_duel_runner.py
"""Le runner : sonde, persistance, remboursements.

La machine à états est testée ailleurs — ici on vérifie le câblage.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat
from bot.core.apex.duel_runner import CLE_ETAT, DuelRunner


def _runner(profil_viewer=None):
    client = MagicMock()
    client.get = AsyncMock(return_value=profil_viewer or {})
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    return DuelRunner(client=client, db=db, api=api, feed=MagicMock(),
                      annoncer=AsyncMock(), azrael_uid="7", plateforme="PC"), client, db, api


@pytest.mark.asyncio
async def test_uid_non_numerique_refuse_avant_tout_appel_reseau():
    """Un UID est purement numérique. Le valider AVANT le réseau évite
    d'envoyer n'importe quelle saisie de viewer à l'API."""
    runner, client, _, api = _runner()
    await runner.ouvrir(acheteur="bob", saisie="'; DROP TABLE--",
                        reward_id="rw", redemption_id="rd")
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_compte_d_azrael_est_refuse_et_rembourse():
    runner, _, _, api = _runner()
    await runner.ouvrir(acheteur="bob", saisie="7", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_compte_sans_tracker_de_kills_refuse_et_rembourse():
    """Une clé présente ne prouve pas une valeur vivante, mais une absence
    totale de tracker est éliminatoire d'emblée."""
    runner, _, _, api = _runner(profil_viewer={"total": {"d": {"name": "BR Damage", "value": 5}}})
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_ouverture_reussie_persiste_l_etat():
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, db, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    db.set_state.assert_awaited()
    cle, valeur = db.set_state.await_args.args[:2]
    assert cle == CLE_ETAT
    assert json.loads(valeur)["viewer_uid"] == "42"
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_reprise_apres_rebuild():
    runner, _, db, _ = _runner()
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7")
    duel.etat = Etat.ENTRE_MANCHES
    duel.scores = [{"azrael": 3, "viewer": 1}]
    db.get_state = AsyncMock(return_value=json.dumps(duel.to_dict()))
    await runner.charger()
    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.scores == [{"azrael": 3, "viewer": 1}]


@pytest.mark.asyncio
async def test_etat_corrompu_en_base_ne_casse_pas_le_boot():
    runner, _, db, _ = _runner()
    db.get_state = AsyncMock(return_value="{ pas du json")
    await runner.charger()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_annuler_rembourse_et_efface():
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, db, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    api.refund_redemption.reset_mock()
    await runner.annuler("le streamer a annulé")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_recommencer_ne_rembourse_PAS():
    """Le viewer garde sa place — les points restent dépensés."""
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, _, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    runner.duel_en_cours.scores = [{"azrael": 2, "viewer": 1}]
    api.refund_redemption.reset_mock()
    await runner.recommencer()
    api.refund_redemption.assert_not_awaited()
    assert runner.duel_en_cours.scores == []
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_apex_duel_runner.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3 : Implémenter**

Créer `bot/core/apex/duel_runner.py` :

```python
# bot/core/apex/duel_runner.py
"""Ce qui entoure la machine à états : réseau, persistance, effets.

La logique du duel est dans `duel.py`, pure et testable sans rien brancher.
Ici on sonde, on range l'état, et on déclenche les annonces.
"""
from __future__ import annotations

import json

from loguru import logger

from bot.core.apex.duel import Duel, Etat, Evenement, Releve
from bot.core.apex.reader import read_kill_trackers

# Une clé de `bot_state`, comme `apex:live_baseline` — un seul duel à la fois,
# donc pas de table. L'état survit ainsi aux rebuilds, qui sont fréquents ici.
CLE_ETAT = "apex:duel"


def _uid_valide(saisie: str) -> str | None:
    """Un uid Apex est purement numérique. Validé AVANT tout appel réseau :
    la saisie vient d'un viewer, c'est de l'entrée non fiable."""
    nettoye = (saisie or "").strip()
    return nettoye if nettoye.isdigit() else None


class DuelRunner:
    def __init__(self, client, db, api, feed, annoncer, *,
                 azrael_uid: str, plateforme: str = "PC", cadence_s: float = 2.0):
        self._client = client
        self._db = db
        self._api = api
        self._feed = feed
        self._annoncer = annoncer          # coroutine(evenement) -> None
        self._azrael_uid = azrael_uid
        self._plateforme = plateforme
        self._cadence_s = cadence_s
        self.duel_en_cours: Duel | None = None
        self._reward_id = ""

    # -- Persistance --------------------------------------------------------
    async def _ranger(self) -> None:
        if self.duel_en_cours is None:
            await self._db.set_state(CLE_ETAT, "")
            return
        await self._db.set_state(CLE_ETAT, json.dumps(self.duel_en_cours.to_dict()))

    async def charger(self) -> None:
        """Reprend un duel interrompu par un rebuild."""
        try:
            brut = await self._db.get_state(CLE_ETAT)
            if not brut:
                return
            self.duel_en_cours = Duel.from_dict(json.loads(brut))
            logger.info("Duel Apex repris après redémarrage : {v} en état {e}",
                        v=self.duel_en_cours.viewer_nom, e=self.duel_en_cours.etat.value)
        except Exception as exc:  # noqa: BLE001 — un état illisible ne bloque pas le boot
            logger.warning("État de duel illisible, ignoré : {e}", e=exc)
            self.duel_en_cours = None

    # -- Ouverture ----------------------------------------------------------
    async def _refuser(self, reward_id: str, redemption_id: str, motif: str) -> None:
        """Un refus s'annonce ET se rembourse. Jamais un silence."""
        logger.info("Duel refusé : {m}", m=motif)
        await self._annoncer(Evenement("refus", {"motif": motif}))
        await self._api.refund_redemption(reward_id, redemption_id)

    async def ouvrir(self, *, acheteur: str, saisie: str,
                     reward_id: str, redemption_id: str) -> None:
        uid = _uid_valide(saisie)
        if uid is None:
            await self._refuser(reward_id, redemption_id,
                                "l'identifiant fourni n'est pas un uid Apex")
            return
        if uid == self._azrael_uid:
            await self._refuser(reward_id, redemption_id,
                                "un duel contre soi-même n'a pas de vainqueur")
            return

        profil = await self._client.get(
            "bridge", {"uid": uid, "platform": self._plateforme}, sans_cache=True)
        if not isinstance(profil, dict) or not read_kill_trackers(profil):
            await self._refuser(
                reward_id, redemption_id,
                "aucun tracker de kills n'est épinglé sur ce compte")
            return

        self._reward_id = reward_id
        self.duel_en_cours = Duel(
            viewer_nom=acheteur, viewer_uid=uid, azrael_uid=self._azrael_uid,
            redemption_id=redemption_id, etat=Etat.ATTENTE_SQUAD)
        await self._ranger()
        await self._annoncer(Evenement("duel_ouvert", {"viewer": acheteur}))

    # -- Sonde --------------------------------------------------------------
    async def _profil(self, uid: str) -> dict | None:
        p = await self._client.get(
            "bridge", {"uid": uid, "platform": self._plateforme}, sans_cache=True)
        return p if isinstance(p, dict) else None

    async def tick(self, maintenant: float) -> None:
        """Un tour de sonde. Appelé toutes les `cadence_s` pendant un duel."""
        duel = self.duel_en_cours
        if duel is None or duel.etat in (Etat.RESOLUTION, Etat.VERDICT, Etat.ABANDON):
            return
        azrael = await self._profil(duel.azrael_uid)
        viewer = await self._profil(duel.viewer_uid)
        if azrael is None or viewer is None:
            # L'API muette quelques relevés est tolérée : la machine à états ne
            # voit simplement rien passer.
            logger.debug("Duel : relevé incomplet, tour sauté")
            return

        releve = Releve(
            t=maintenant,
            azrael_in_game=bool((azrael.get("realtime") or {}).get("isInGame")),
            viewer_in_game=bool((viewer.get("realtime") or {}).get("isInGame")),
            kills_azrael=read_kill_trackers(azrael),
            kills_viewer=read_kill_trackers(viewer),
        )
        for evt in duel.avancer(releve):
            await self._annoncer(evt)
            if evt.type == "abandon" and evt.donnees.get("rembourser"):
                await self._api.refund_redemption(self._reward_id, duel.redemption_id)
        if duel.etat in (Etat.VERDICT, Etat.ABANDON):
            self.duel_en_cours = None
        await self._ranger()

    # -- Contrôle (streamer et modérateurs) ---------------------------------
    async def annuler(self, motif: str) -> None:
        duel = self.duel_en_cours
        if duel is None:
            return
        await self._api.refund_redemption(self._reward_id, duel.redemption_id)
        await self._annoncer(Evenement("abandon", {"motif": motif, "rembourser": True}))
        self.duel_en_cours = None
        await self._ranger()

    async def recommencer(self) -> None:
        """Compteurs à zéro, même duelliste — pas de remboursement, il garde sa place."""
        if self.duel_en_cours is None:
            return
        self.duel_en_cours.recommencer()
        await self._annoncer(Evenement("recommence", {
            "viewer": self.duel_en_cours.viewer_nom}))
        await self._ranger()
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_apex_duel_runner.py -v`
Expected: 8 passed

- [ ] **Step 5 : Commit**

```bash
git add bot/core/apex/duel_runner.py tests/test_apex_duel_runner.py
git commit -m "feat(apex): runner du duel — sonde, persistance, remboursements

L'état vit dans une clé bot_state, comme apex:live_baseline : un seul duel à la
fois, donc pas de table, et il survit aux rebuilds.

Tout refus rembourse et s'annonce — jamais un silence. L'uid est validé
purement numérique AVANT le réseau, la saisie venant d'un viewer."
```

---

## Task 8 bis : Le repli en chat quand le compte est introuvable

**Files:**
- Modify: `bot/core/apex/duel_runner.py`
- Test: `tests/test_apex_duel_resolution.py`

**Interfaces:**
- Consumes: `DuelRunner.ouvrir()` (Task 8)
- Produces: `DuelRunner.repondre_resolution(auteur: str, texte: str) -> bool` — `True` si la réponse a été consommée par le duel.
- Produces: `URL_APEX_STATUS: str`, `TENTATIVES_RESOLUTION: int = 3`

**Pourquoi :** la spec (§9) veut que Wally **explique et attende** plutôt que de rembourser au premier essai raté. La recherche par pseudo de l'API rate des comptes bien réels — refuser d'emblée punirait le viewer pour un défaut de l'API.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_apex_duel_resolution.py
"""Un compte introuvable s'explique, il ne se rembourse pas d'emblée.

La recherche par pseudo de l'API rate des comptes parfaitement réels : refuser
au premier essai punirait le viewer pour un défaut qui n'est pas le sien.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Etat
from bot.core.apex.duel_runner import (TENTATIVES_RESOLUTION, URL_APEX_STATUS,
                                       DuelRunner)

PROFIL_OK = {"total": {"k": {"name": "BR Kills", "value": 10}}}


def _runner(profils):
    client = MagicMock()
    client.get = AsyncMock(side_effect=list(profils))
    db = MagicMock(); db.get_state = AsyncMock(return_value=None); db.set_state = AsyncMock()
    api = MagicMock(); api.refund_redemption = AsyncMock(return_value=True)
    annoncer = AsyncMock()
    r = DuelRunner(client=client, db=db, api=api, feed=MagicMock(),
                   annoncer=annoncer, azrael_uid="7", plateforme="PC")
    return r, api, annoncer


@pytest.mark.asyncio
async def test_saisie_illisible_demande_l_uid_sans_rembourser():
    runner, api, annoncer = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="mon pseudo", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_not_awaited()
    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.etat is Etat.RESOLUTION
    evt = annoncer.await_args.args[0]
    assert evt.type == "compte_introuvable"


@pytest.mark.asyncio
async def test_le_message_porte_l_url_ET_l_astuce_deep_search():
    """L'URL est collée en dur, jamais laissée au LLM : un modèle qui
    reformule une adresse la casse, et un lien mort bloque tout duel."""
    runner, _, annoncer = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="x", reward_id="rw", redemption_id="rd")
    evt = annoncer.await_args.args[0]
    assert URL_APEX_STATUS in evt.donnees["url"]
    assert "deep search" in evt.donnees["etapes"].lower()


@pytest.mark.asyncio
async def test_une_reponse_correcte_lance_le_duel():
    runner, api, _ = _runner([PROFIL_OK])
    await runner.ouvrir(acheteur="bob", saisie="x", reward_id="rw", redemption_id="rd")
    consomme = await runner.repondre_resolution("bob", "1012242925358")
    assert consomme is True
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    assert runner.duel_en_cours.viewer_uid == "1012242925358"
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_la_reponse_d_un_AUTRE_viewer_est_ignoree():
    runner, _, _ = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="x", reward_id="rw", redemption_id="rd")
    assert await runner.repondre_resolution("carol", "1012242925358") is False
    assert runner.duel_en_cours.etat is Etat.RESOLUTION


@pytest.mark.asyncio
async def test_apres_N_tentatives_on_rembourse():
    runner, api, _ = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="x", reward_id="rw", redemption_id="rd")
    for _ in range(TENTATIVES_RESOLUTION):
        await runner.repondre_resolution("bob", "toujours pas un uid")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_hors_resolution_le_chat_n_est_pas_consomme():
    """Pendant une manche, un message du duelliste reste un message normal."""
    runner, _, _ = _runner([PROFIL_OK])
    await runner.ouvrir(acheteur="bob", saisie="1012242925358",
                        reward_id="rw", redemption_id="rd")
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    assert await runner.repondre_resolution("bob", "gg") is False
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_apex_duel_resolution.py -v`
Expected: FAIL — `ImportError: cannot import name 'URL_APEX_STATUS'`

- [ ] **Step 3 : Implémenter**

Dans `bot/core/apex/duel_runner.py`, ajouter aux constantes :

```python
# Collée en dur dans le message, jamais laissée au LLM : un modèle qui
# reformule une adresse finit par la casser, et un lien mort rend le duel
# impossible à démarrer. Le ton est libre, l'adresse ne l'est pas.
URL_APEX_STATUS = "https://apexlegendsstatus.com"

# Étapes exactes et non devinables — fournies au prompt comme des FAITS.
ETAPES_UID = (
    "cherche ton pseudo sur le site, ouvre ton profil, et regarde l'URL : si "
    "elle ne contient pas de numéro, clique sur « Not the profile you are "
    "looking for? Try deep search », puis reclique sur ton compte — l'URL "
    "devient une adresse en profile/uid/… C'est ce numéro qu'il me faut."
)

# Au-delà, on rend les points : mieux vaut un remboursement qu'un viewer qui
# attend indéfiniment.
TENTATIVES_RESOLUTION = 3
```

Remplacer le début d'`ouvrir()` (le cas `uid is None`) et ajouter la méthode :

```python
    async def _demander_uid(self, acheteur: str, reward_id: str,
                            redemption_id: str) -> None:
        """Explique comment trouver son uid, et garde le duel en attente."""
        self._reward_id = reward_id
        self._tentatives = 0
        self.duel_en_cours = Duel(
            viewer_nom=acheteur, viewer_uid="", azrael_uid=self._azrael_uid,
            redemption_id=redemption_id, etat=Etat.RESOLUTION)
        await self._ranger()
        await self._annoncer(Evenement("compte_introuvable", {
            "viewer": acheteur, "url": URL_APEX_STATUS, "etapes": ETAPES_UID,
        }))

    async def repondre_resolution(self, auteur: str, texte: str) -> bool:
        """Une réponse du duelliste pendant la phase de résolution.

        Rend True si le message a été consommé par le duel — l'appelant sait
        alors qu'il n'a pas à le traiter comme un message ordinaire.
        """
        duel = self.duel_en_cours
        if duel is None or duel.etat is not Etat.RESOLUTION:
            return False
        if auteur.lower() != duel.viewer_nom.lower():
            return False

        uid = _uid_valide(texte)
        if uid is not None and uid != self._azrael_uid:
            profil = await self._client.get(
                "bridge", {"uid": uid, "platform": self._plateforme}, sans_cache=True)
            if isinstance(profil, dict) and read_kill_trackers(profil):
                duel.viewer_uid = uid
                duel.etat = Etat.ATTENTE_SQUAD
                await self._ranger()
                await self._annoncer(Evenement("duel_ouvert", {"viewer": duel.viewer_nom}))
                return True

        self._tentatives += 1
        if self._tentatives >= TENTATIVES_RESOLUTION:
            await self._api.refund_redemption(self._reward_id, duel.redemption_id)
            await self._annoncer(Evenement("abandon", {
                "rembourser": True,
                "motif": "impossible de retrouver ce compte Apex"}))
            self.duel_en_cours = None
            await self._ranger()
            return True
        await self._annoncer(Evenement("compte_introuvable", {
            "viewer": duel.viewer_nom, "url": URL_APEX_STATUS, "etapes": ETAPES_UID}))
        return True
```

Dans `__init__`, ajouter `self._tentatives = 0`.

Dans `ouvrir()`, remplacer le bloc `if uid is None:` par :

```python
        uid = _uid_valide(saisie)
        if uid is None:
            # Pas de remboursement au premier essai : la recherche par pseudo de
            # l'API rate des comptes bien réels, ce serait punir le viewer pour
            # un défaut qui n'est pas le sien.
            await self._demander_uid(acheteur, reward_id, redemption_id)
            return
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_apex_duel_resolution.py -v`
Expected: 6 passed

- [ ] **Step 5 : Brancher sur le chat Twitch**

Dans `bot/twitch/handlers.py`, au tout début du traitement d'un message (avant le cooldown et l'appel LLM) :

```python
    runner = getattr(bot, "duel_runner", None)
    if runner is not None and await runner.repondre_resolution(auteur, contenu):
        return
```

- [ ] **Step 6 : Ajouter la section au registre d'annonces**

Ajouter à `bot/persona/prompts/apex_duel.md` :

```markdown
## compte_introuvable
Le compte Apex n'a pas été retrouvé. Explique les étapes qu'on te donne — elles sont
exactes, ne les improvise pas — et donne le lien tel quel. Reste léger : ce n'est pas
la faute du viewer, la recherche par pseudo de l'API rate des comptes réels.
```

- [ ] **Step 7 : Commit**

```bash
git add bot/core/apex/duel_runner.py bot/twitch/handlers.py \
        bot/persona/prompts/apex_duel.md tests/test_apex_duel_resolution.py
git commit -m "feat(apex): expliquer comment trouver son uid au lieu de rembourser

La recherche par pseudo de l'API rate des comptes parfaitement réels : refuser
au premier essai punirait le viewer pour un défaut qui n'est pas le sien.

Wally explique les étapes — y compris le « Try deep search », non devinable —
et attend, trois tentatives durant. L'URL est collée en dur : un modèle qui
reformule une adresse finit par la casser, et un lien mort bloque tout duel."
```

---

## Task 9 : Widget, annonces et perception

**Files:**
- Create: `bot/persona/prompts/apex_duel.md`
- Modify: `bot/intelligence/prompts.py`
- Modify: `bot/dashboard/static/overlay.js` (widget `versus` : sous-titres optionnels)
- Modify: `bot/dashboard/static/overlay.html` (CSS `.vs-sub`)
- Test: `tests/test_apex_duel_perception.py`

**Interfaces:**
- Consumes: `DuelRunner.duel_en_cours` (Task 8)
- Produces: `bloc_duel_en_cours(duel) -> str` dans `prompts.py`

**Décision par rapport à la spec :** la spec prévoyait une classe `.duel` neuve. Le widget **`versus` existant fait déjà le travail** (deux noms, deux valeurs, barres relatives au meilleur des deux, celui qui mène en `--win`, égalité gérée). On l'étend de deux champs optionnels au lieu de dupliquer.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/test_apex_duel_perception.py
"""Wally doit pouvoir PARLER du duel, pas seulement l'afficher.

Le piège déjà payé : l'état de l'overlay n'allait qu'au prompt des
conversations, la cognition restait aveugle à ses propres effets et Wally
relançait un bingo déjà en cours.
"""
from bot.core.apex.duel import Duel, Etat
from bot.intelligence.prompts import bloc_duel_en_cours


def _duel():
    d = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7")
    d.etat = Etat.ENTRE_MANCHES
    d.scores = [{"azrael": 4, "viewer": 2}, {"azrael": 0, "viewer": 5}]
    return d


def test_le_bloc_nomme_le_demandeur():
    assert "Bob" in bloc_duel_en_cours(_duel())


def test_le_bloc_donne_le_score_de_CHAQUE_manche():
    bloc = bloc_duel_en_cours(_duel())
    assert "4" in bloc and "2" in bloc and "5" in bloc


def test_le_bloc_donne_le_total():
    bloc = bloc_duel_en_cours(_duel())
    assert "4" in bloc and "7" in bloc  # 4+0 contre 2+5


def test_une_manche_non_mesurable_est_dite_comme_telle():
    d = _duel()
    d.scores = [{"azrael": None, "viewer": None}]
    bloc = bloc_duel_en_cours(d)
    assert "0" not in bloc.split("Manche")[1][:40], "ne jamais afficher 0 pour une absence"


def test_pas_de_duel_pas_de_bloc():
    assert bloc_duel_en_cours(None) == ""
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `python3 -m pytest tests/test_apex_duel_perception.py -v`
Expected: FAIL — `ImportError: cannot import name 'bloc_duel_en_cours'`

- [ ] **Step 3 : Implémenter le bloc de perception**

Ajouter à `bot/intelligence/prompts.py` :

```python
def bloc_duel_en_cours(duel) -> str:
    """Le duel Apex courant, pour que Wally puisse en PARLER.

    Injecté à la fois dans `build_system_prompt` et dans le contexte cognitif :
    n'alimenter que le premier laissait la cognition aveugle à ses propres
    effets — c'est ainsi qu'un bingo se relançait en boucle.

    Une manche non mesurable est dite telle quelle. Afficher « 0 » pour une
    absence de mesure serait un mensonge.
    """
    if duel is None:
        return ""
    lignes = [
        "--- Duel Apex en cours ---",
        f"Lancé par {duel.viewer_nom} (récompense de points de chaîne).",
        f"Manche {duel.manche_courante} sur {duel.manches}.",
    ]
    for i, s in enumerate(duel.scores, start=1):
        if s["azrael"] is None and s["viewer"] is None:
            lignes.append(f"Manche {i} : non mesurable (aucun kill enregistré).")
        else:
            lignes.append(
                f"Manche {i} : Azraël {s['azrael'] if s['azrael'] is not None else '?'}"
                f" — {duel.viewer_nom} {s['viewer'] if s['viewer'] is not None else '?'}")
    lignes.append(f"Total : Azraël {duel.total_azrael} — {duel.viewer_nom} {duel.total_viewer}.")
    return "\n".join(lignes)
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest tests/test_apex_duel_perception.py -v`
Expected: 5 passed

- [ ] **Step 5 : Brancher le bloc aux DEUX endroits**

Dans `bot/intelligence/prompts.py`, à l'endroit où `current_apex_block()` est déjà injecté dans `build_system_prompt`, ajouter le duel juste après. Puis, dans `bot/intelligence/cognitive_loop.py`, là où `AttentionContext` est construit avec `stream_feed`, ajouter le même bloc.

Run pour repérer les deux points exacts :
```bash
grep -n "current_apex_block\|current_stream_feed_block" bot/intelligence/prompts.py bot/intelligence/cognitive_loop.py
```

- [ ] **Step 6 : Étendre le widget `versus` de sous-titres**

Dans `bot/dashboard/static/overlay.js`, fonction `versus(p)`, après `head.append(n, v);` :

```javascript
        // Sous-titre optionnel (légende jouée, niveau du compte) — le duel s'en
        // sert, les appels génériques ne le passent pas et n'affichent rien.
        const subs = [p.left_sub, p.right_sub];
        if (subs[i]) {
          const sub = el("div", "vs-sub");
          sub.textContent = String(subs[i]);
          row.appendChild(sub);
        }
```

Et dans `bot/dashboard/static/overlay.html`, à côté des règles `.versus` :

```css
    /* Sous-titre d'un camp : légende jouée et niveau. Discret — c'est le score
       qui se lit, pas le détail. */
    .versus .vs-sub {
      font-size: 11px;
      opacity: .6;
      margin-top: 1px;
    }
```

- [ ] **Step 7 : Écrire le registre d'annonces**

Créer `bot/persona/prompts/apex_duel.md` :

```markdown
# Duel Apex — comment tu l'annonces

Tu arbitres un duel entre Azraël et un viewer qui a dépensé ses points de chaîne.
Les chiffres te sont donnés : tu les habilles, tu ne les inventes pas et tu ne les
recalcules pas.

Tu parles aux SPECTATEURS du live, pas au streamer.

## duel_ouvert
Annonce le duel et rappelle deux choses, sans en faire une notice : le viewer doit
être invité dans le squad d'Azraël, et **la Mixtape ne compte aucun kill** — le duel
doit se jouer en Battle Royale ou en Joker.

## manche_debut
Une ligne, l'ambiance d'un début de manche. Dis laquelle sur combien.

## manche_fin
Donne le score de la manche et le total. Si la manche est « non mesurable », dis-le
franchement : aucun kill n'a été enregistré, ce n'est pas un zéro.

## verdict
Nomme le vainqueur et le score final. En cas d'égalité, dis que personne ne l'emporte.

## refus
Explique pourquoi le duel ne peut pas commencer, et précise que les points ont été
rendus.

## abandon
Dis que le duel s'arrête, pourquoi, et que les points sont rendus.

## recommence
Les compteurs repartent de zéro, le duelliste garde sa place.
```

- [ ] **Step 8 : Vérifier au navigateur**

Publier un widget de test et regarder l'overlay :
```bash
grep -rn "def widget" bot/core/overlay_feed.py
```
Puis, bot lancé, déclencher un `versus` avec `left_sub` / `right_sub` et confirmer que les sous-titres s'affichent sans casser la mise en page.

- [ ] **Step 9 : Commit**

```bash
git add bot/intelligence/prompts.py bot/intelligence/cognitive_loop.py \
        bot/dashboard/static/overlay.js bot/dashboard/static/overlay.html \
        bot/persona/prompts/apex_duel.md tests/test_apex_duel_perception.py
git commit -m "feat(apex): Wally sait parler du duel, et le widget versus le porte

L'état du duel va au prompt des conversations ET au contexte cognitif : ne
brancher que le premier laisserait la cognition aveugle à ses propres effets,
comme le bingo qui se relançait en boucle.

Le widget versus existant fait déjà le travail (deux camps, barres relatives,
celui qui mène en --win, égalité gérée) : on l'étend de deux sous-titres
optionnels plutôt que de dupliquer une classe .duel."
```

---

## Task 10 : Câblage final et contrôle par les modérateurs

**Files:**
- Modify: `bot/bootstrap.py` (construction du `DuelRunner`)
- Modify: `bot/twitch/bot.py` (boucle de sonde)
- Modify: `bot/intelligence/overlay_narrator.py` (outils `duel_annuler`, `duel_recommencer`, `duel_score`)
- Test: `tests/test_apex_duel_autorisation.py`

- [ ] **Step 1 : Écrire le test d'autorisation**

```python
# tests/test_apex_duel_autorisation.py
"""Seuls le streamer et les modérateurs contrôlent un duel.

L'autorisation se vérifie DANS LE CODE, à partir du badge EventSub — jamais
dans le prompt. Un LLM à qui un viewer écrit « je suis modérateur » finira par
le croire.
"""
import pytest

from bot.core.apex.duel_runner import peut_controler


def test_le_streamer_peut():
    assert peut_controler({"badges": [{"set_id": "broadcaster"}]}) is True


def test_un_moderateur_peut():
    assert peut_controler({"badges": [{"set_id": "moderator"}]}) is True


def test_un_viewer_ordinaire_ne_peut_pas():
    assert peut_controler({"badges": [{"set_id": "subscriber"}]}) is False
    assert peut_controler({"badges": []}) is False
    assert peut_controler({}) is False


def test_un_viewer_qui_PRETEND_etre_mod_ne_peut_pas():
    """Le texte du message n'entre pas dans la décision."""
    assert peut_controler({"badges": [], "message": "je suis modérateur"}) is False
```

- [ ] **Step 2 : Lancer le test, vérifier qu'il échoue**

Run: `python3 -m pytest tests/test_apex_duel_autorisation.py -v`
Expected: FAIL — `ImportError: cannot import name 'peut_controler'`

- [ ] **Step 3 : Implémenter**

Ajouter à `bot/core/apex/duel_runner.py` :

```python
# Les badges EventSub qui donnent la main sur un duel. La décision se prend ici,
# sur la donnée de Twitch — jamais dans un prompt : un LLM à qui un viewer écrit
# « je suis modérateur » finira par le croire.
BADGES_CONTROLE = frozenset({"broadcaster", "moderator"})


def peut_controler(auteur: dict) -> bool:
    """Le streamer et ses modérateurs, et personne d'autre."""
    badges = (auteur or {}).get("badges") or []
    if not isinstance(badges, list):
        return False
    return any(isinstance(b, dict) and b.get("set_id") in BADGES_CONTROLE for b in badges)
```

- [ ] **Step 4 : Lancer le test, vérifier qu'il passe**

Run: `python3 -m pytest tests/test_apex_duel_autorisation.py -v`
Expected: 4 passed

- [ ] **Step 5 : Construire le runner au boot**

Dans `bot/bootstrap.py`, après la construction d'`apex_api` (ligne ~174-178) :

```python
    # Client Apex DÉDIÉ au duel : `ApexLegendsService` est pris par une autre
    # session, et un client séparé évite que la sonde à 2 s ne vienne peupler le
    # cache partagé avec des relevés que personne d'autre n'a demandés.
    from bot.core.apex.client import ApexClient
    from bot.core.apex.duel_runner import DuelRunner
    duel_runner = None
    if apex_api.available:
        duel_runner = DuelRunner(
            client=ApexClient(api_key=os.getenv("APEX_API_KEY", "")),
            db=db, api=None, feed=overlay_feed, annoncer=None,
            azrael_uid=os.getenv("APEX_AZRAEL_UID", ""),
            plateforme=config.apex.streamer_platform,
            cadence_s=float(getattr(config.apex.duel, "cadence_s", 2.0)),
        )
        logger.info("DuelRunner initialisé")
```

`api` et `annoncer` sont posés plus tard, quand le bot Twitch existe — ils dépendent de lui. Exposer ensuite sur le bot Twitch : `twitch_bot.duel_runner = duel_runner`, puis `await duel_runner.charger()` juste avant le `gather` de `bot/twitch/bot.py`.

- [ ] **Step 6 : Brancher la boucle de sonde**

Dans `bot/twitch/bot.py`, ajouter la méthode puis l'inscrire au `gather` de la ligne 129 :

```python
    async def _duel_poll_loop(self) -> None:
        """Sonde le duel en cours, et RIEN quand il n'y en a pas.

        Hors duel, cette boucle ne doit émettre aucune requête : la sonde du
        watcher suffit à entretenir l'historique. À 2 s sur deux comptes, un duel
        consomme 1 req/s — 20 % du débit autorisé.
        """
        runner = getattr(self, "duel_runner", None)
        if runner is None:
            return
        while True:
            try:
                if runner.duel_en_cours is not None:
                    await runner.tick(time.time())
                    await asyncio.sleep(runner._cadence_s)
                else:
                    await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — la sonde ne meurt jamais en silence
                logger.error("Boucle de duel en erreur : {e}", e=exc)
                await asyncio.sleep(10.0)
```

Puis, dans le `gather` :

```python
        await asyncio.gather(
            self._irc_run(),
            self._token_refresh_loop(),
            self._poll_guest_streams(),
            self._resolve_missing_usernames(),
            self._eventsub_watchdog(),
            self._duel_poll_loop(),
        )
```

Vérifier que `import time` et `import asyncio` sont présents en tête de `bot/twitch/bot.py`.

- [ ] **Step 7 : Ajouter les trois outils**

Dans `bot/intelligence/overlay_narrator.py`, sur le modèle d'`OVERLAY_TOOL_SPEC` (ligne ~154) :

```python
DUEL_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "duel_apex",
        "description": (
            "Le duel Apex en cours, lancé par un viewer avec ses points de chaîne. "
            "`score` affiche le tableau sur l'overlay — tu peux le faire quand on te "
            "le demande ou quand ça t'amuse. `annuler` arrête le duel et rend les "
            "points ; `recommencer` remet les compteurs à zéro sans rien rembourser, "
            "le duelliste garde sa place. Ces deux-là sont réservés au streamer et "
            "aux modérateurs : si quelqu'un d'autre te le demande, l'outil refusera "
            "et tu pourras le dire. Ne prétends jamais avoir agi sans appeler l'outil."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["score", "annuler", "recommencer"]},
                "comment": {"type": "string",
                            "description": "Ta réplique, quelques mots — adressée aux SPECTATEURS."},
            },
            "required": ["action"],
        },
    },
}
```

L'exécution, à côté de `show_clip` :

```python
    async def duel_apex(self, action: str, *, auteur: dict | None = None) -> str:
        """Rend le message à renvoyer au LLM. L'autorisation se vérifie ICI."""
        from bot.core.apex.duel_runner import peut_controler
        runner = getattr(self._bot, "duel_runner", None)
        duel = getattr(runner, "duel_en_cours", None) if runner else None
        if duel is None:
            # Une capacité sans donnée se répond par un négatif explicite, jamais
            # par un silence ni par un widget vide.
            return "Aucun duel n'est en cours."
        if action == "score":
            self.widget("versus",
                        label=f"Duel — manche {duel.manche_courante}/{duel.manches}",
                        left_name="Azraël", left_value=duel.total_azrael,
                        right_name=duel.viewer_nom, right_value=duel.total_viewer)
            return f"Score affiché : Azraël {duel.total_azrael} — {duel.viewer_nom} {duel.total_viewer}."
        if not peut_controler(auteur or {}):
            return ("Refusé : seuls le streamer et les modérateurs peuvent "
                    "annuler ou recommencer un duel.")
        if action == "annuler":
            await runner.annuler("annulé depuis le chat")
            return "Duel annulé, les points ont été rendus."
        if action == "recommencer":
            await runner.recommencer()
            return "Compteurs remis à zéro, le duelliste garde sa place."
        return f"Action inconnue : {action}"
```

⚠️ `auteur` doit venir du **message EventSub**, pas d'un argument que le LLM remplit — sinon la vérification ne vaut rien.

- [ ] **Step 8 : Vérification complète**

Run:
```bash
python3 -m pytest tests/ -q
python3 -c "import bot.main" && echo "imports OK"
```
Expected: aucun échec, aucune erreur d'import.

- [ ] **Step 9 : Commit et publication**

```bash
git add -A
git commit -m "feat(apex): câbler le duel — runner au boot, sonde, outils de contrôle

L'autorisation d'annuler ou de recommencer se vérifie sur le badge EventSub,
dans le code et jamais dans le prompt."
docker compose build --build-arg GIT_HASH=$(git rev-parse --short HEAD) \
                     --build-arg BUILD_DATE=$(date -Iseconds) wally
docker compose up -d wally
git push public feat/site-redesign-arcade:main
```

⚠️ **Sans `--build-arg GIT_HASH`, `BOT_GIT_HASH` vaut `unknown`** et la version affichée par le dashboard devient fausse.

---

## Vérification en production

Après déploiement, dans l'ordre :

1. **Scopes** — `curl -H "Authorization: OAuth $TOKEN" https://id.twitch.tv/oauth2/validate` doit lister les quatre.
2. **Souscription EventSub** — les logs de boot doivent montrer `duel_redemption` souscrit sans erreur.
3. **`reward_id`** — le renseigner dans `config.yaml` depuis la console Twitch, puis `config.save()` ou redémarrage.
4. **Un duel réel** — acheter la récompense soi-même, vérifier : annonce, widget, score par manche, verdict, et surtout **que les points sont rendus** sur un refus.
5. **Mesurer `marge_lobby_s`** avec `scripts/probe_duel.py` sur le duel réel, et ajuster si les compteurs se révélaient plus lents qu'observé.

---

## Ce que ce plan ne fait pas

- **La détection du mode de jeu** — impossible, `realtime` ne le porte pas. Seul l'avertissement au lancement protège du cas Mixtape.
- **La vérification que le viewer est dans le squad d'Azraël** — l'API ne donne pas la composition d'une équipe.
- **La mémoire des duels passés** (§11 ter de la spec) — un `memory.add()` en fin de duel, à ajouter quand le reste tourne. Volontairement hors du premier jet pour ne pas mêler deux sujets.
- **Le libellé des scopes dans `app.js`** — fichier gelé par une session concurrente. Cosmétique, n'empêche pas l'autorisation.
