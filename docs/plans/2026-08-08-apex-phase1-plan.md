# Apex phase 1 — plan d'implémentation

**But :** remplacer `bot/core/apex_api.py` par le paquet `bot/core/apex/`, qui lit
l'API sans jamais supposer la forme de ses données, met en cache ce qui ne bouge
pas, et dit clairement ce qu'il ne sait pas faire.

**Architecture :** trois unités à responsabilité unique — `client` (réseau, débit,
cache), `reader` (interprétation d'une réponse `/bridge`, sans réseau), `service`
(les actions offertes au LLM, en texte). `reader` isolé du réseau est ce qui rend
testable la variation de forme entre joueurs.

**Pile :** Python 3.11, httpx, pytest / pytest-asyncio, loguru.

**Spec :** `docs/plans/2026-08-08-apex-legends-integration-complete.md`

## Contraintes globales

- Journalisation via `loguru` uniquement — jamais `print()` ni `import logging`.
- Tout le réseau est `async`. Débit maximal : **2 requêtes/seconde** (0,5 s entre
  deux appels), partagé par tout le paquet.
- Une erreur réseau **retourne une chaîne** (convention actuelle, dont dépendent
  les appelants) et **n'est jamais mise en cache**.
- Une statistique absente est rendue absente — **jamais `0`**.
- Fixtures réelles dans `tests/fixtures/apex/` : ne pas les réécrire à la main.
- Après chaque tâche : `python3 -m pytest -q` en entier doit rester vert.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `bot/core/apex/__init__.py` | Façade : `ApexLegendsService`, `APEX_LEGENDS_TOOL` |
| `bot/core/apex/client.py` | HTTP, limite de débit, cache TTL par endpoint |
| `bot/core/apex/reader.py` | Interprète `/bridge` → objets nommés. Aucun réseau. |
| `bot/core/apex/service.py` | Les actions du LLM + leur rendu texte |
| `bot/core/apex_api.py` | **Supprimé** (tâche 6) |
| `bot/bootstrap.py:25,90` | Imports à rediriger |
| `tests/fixtures/apex/*.json` | Six réponses réelles, déjà capturées |

---

### Tâche 1 : le client (réseau, débit, cache)

**Fichiers :**
- Créer : `bot/core/apex/__init__.py`, `bot/core/apex/client.py`
- Test : `tests/test_apex_client.py`

**Interfaces produites :**
- `ApexClient(api_key: str = "", *, ttl: dict[str, float] | None = None)`
- `ApexClient.available -> bool`
- `await ApexClient.get(endpoint: str, params: dict | None = None) -> dict | list | str`
- `DEFAULT_TTL: dict[str, float]`

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# tests/test_apex_client.py
"""Le client Apex : cache par endpoint, débit borné, erreurs non mémorisées."""
import pytest

from bot.core.apex.client import ApexClient, DEFAULT_TTL


def _client(responses, clock):
    """Un client dont le réseau est doublé et l'horloge injectée."""
    calls = []
    client = ApexClient(api_key="k", now=clock)

    async def _fetch(endpoint, params):
        calls.append((endpoint, params))
        return responses.pop(0) if len(responses) > 1 else responses[0]

    client._fetch = _fetch          # seul point réseau
    return client, calls


@pytest.mark.asyncio
async def test_deux_demandes_rapprochees_ne_font_qu_un_appel():
    t = [1000.0]
    client, calls = _client([{"map": "Olympus"}], lambda: t[0])
    a = await client.get("maprotation", {"version": "2"})
    t[0] += 10
    b = await client.get("maprotation", {"version": "2"})
    assert a == b == {"map": "Olympus"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_le_cache_expire_selon_l_endpoint():
    t = [1000.0]
    client, calls = _client([{"n": 1}, {"n": 2}], lambda: t[0])
    await client.get("maprotation")
    t[0] += DEFAULT_TTL["maprotation"] + 1
    assert await client.get("maprotation") == {"n": 2}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_des_parametres_differents_sont_des_entrees_distinctes():
    t = [1000.0]
    client, calls = _client([{"p": "a"}, {"p": "b"}], lambda: t[0])
    await client.get("bridge", {"player": "A"})
    await client.get("bridge", {"player": "B"})
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_une_erreur_n_est_jamais_mise_en_cache():
    """Sinon une panne d'une seconde condamne l'endpoint pour tout son TTL."""
    t = [1000.0]
    client = ApexClient(api_key="k", now=lambda: t[0])
    appels = []

    async def _fetch(endpoint, params):
        appels.append(endpoint)
        if len(appels) == 1:
            raise RuntimeError("réseau coupé")
        return {"ok": True}

    client._fetch = _fetch
    premier = await client.get("servers")
    assert isinstance(premier, str) and "error" in premier.lower()
    assert await client.get("servers") == {"ok": True}
    assert len(appels) == 2


def test_indisponible_sans_cle():
    assert ApexClient(api_key="").available is False
    assert ApexClient(api_key="k").available is True
```

- [ ] **Étape 2 : vérifier que ça échoue**

Lancer : `python3 -m pytest tests/test_apex_client.py -q`
Attendu : `ModuleNotFoundError: No module named 'bot.core.apex'`

- [ ] **Étape 3 : écrire le client**

```python
# bot/core/apex/client.py
"""Accès réseau à l'API Apex Legends Status : débit borné, réponses en cache.

Un seul objet parle au réseau dans tout le paquet. Le cache évite qu'une même
question posée deux fois en dix secondes coûte deux appels — la rotation des
cartes ne change pas plus vite que la minute.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
from loguru import logger

_BASE_URL = "https://api.mozambiquehe.re"

# Durée de validité par endpoint, en secondes. Choisies sur ce que la donnée
# représente : les lots du replicator tiennent la journée, l'état d'un joueur
# non.
DEFAULT_TTL: dict[str, float] = {
    "maprotation": 60.0,
    "crafting": 3600.0,
    "predator": 300.0,
    "servers": 300.0,
    "bridge": 60.0,
}
_FALLBACK_TTL = 60.0

# L'API tolère 2 requêtes/seconde.
_MIN_INTERVAL = 0.5


class ApexClient:
    def __init__(
        self,
        api_key: str = "",
        *,
        ttl: dict[str, float] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._ttl = {**DEFAULT_TTL, **(ttl or {})}
        self._now = now
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache: dict[tuple, tuple[float, Any]] = {}

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def get(self, endpoint: str, params: dict | None = None) -> Any:
        """La réponse de l'endpoint, depuis le cache si elle y est encore fraîche.

        Une erreur est retournée sous forme de chaîne et n'entre jamais dans le
        cache : une panne d'une seconde condamnerait l'endpoint tout son TTL.
        """
        key = (endpoint, tuple(sorted((params or {}).items())))
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

        ttl = self._ttl.get(endpoint, _FALLBACK_TTL)
        self._cache[key] = (self._now() + ttl, value)
        return value

    async def _fetch(self, endpoint: str, params: dict) -> Any:
        """Le seul point qui touche le réseau — doublé dans les tests."""
        await self._rate_limit()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_BASE_URL}/{endpoint}",
                headers={"Authorization": self._api_key},
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def _rate_limit(self) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_request = time.monotonic()
```

```python
# bot/core/apex/__init__.py
"""Accès à l'API Apex Legends Status.

`client` parle au réseau, `reader` interprète, `service` rend en texte.
"""
from bot.core.apex.client import ApexClient

__all__ = ["ApexClient"]
```

- [ ] **Étape 4 : vérifier que ça passe**

Lancer : `python3 -m pytest tests/test_apex_client.py -q` → 5 passed

- [ ] **Étape 5 : commiter**

```bash
git add bot/core/apex/ tests/test_apex_client.py
git commit -m "feat(apex): un seul point qui parle au réseau, et qui se souvient"
```

---

### Tâche 2 : le lecteur (la forme varie, les notions non)

**Fichiers :**
- Créer : `bot/core/apex/reader.py`
- Test : `tests/test_apex_reader.py`

**Interfaces produites :**
- `read_profile(payload: dict) -> PlayerProfile | None`
- `PlayerProfile` : `name, uid, platform, level, level_percent, avatar, banned,
  ban_reason, rank: RankInfo | None, state: str, in_game: bool, legend: str | None,
  stats: dict[str, StatValue]`
- `RankInfo` : `name, div, score, img, top_percent: float | None, ladder_pos: int | None`
- `StatValue` : `label: str, value: int, world_pos: int | None, top_percent: float | None`
- `STAT_ALIASES: dict[str, tuple[str, ...]]`

**Ce que les fixtures imposent** — deux joueurs, deux formes :

| | `bridge_kingsrequin.json` | `bridge_azrael.json` |
|---|---|---|
| Kills | `total.career_kills` / « Career Kills » | `total.specialEvent_kills` / « **BR Kills** » |
| `ALStopPercent` | `"No game this split"` (chaîne) | `49.45` (nombre) |
| `ladderPosPlatform` | `-1` | `-1` (⇒ absent, jamais affiché) |
| Rang mondial kills | `Global` → top 21,41 % | `Revenant` → top **2,73 %** |

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# tests/test_apex_reader.py
"""Lecture d'une réponse /bridge — la forme change d'un joueur à l'autre.

Les deux fixtures sont des réponses RÉELLES capturées le 2026-08-08. Elles ne
diffèrent pas par hasard : les trackers dépendent de ce que le joueur a épinglé
en jeu, et changent au fil des saisons. Un code qui lit `career_kills` en dur
marche pour l'un et casse pour l'autre.
"""
import json
import pathlib

import pytest

from bot.core.apex.reader import read_profile

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex"


def _payload(name):
    return json.loads((FIXTURES / f"bridge_{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("who", ["kingsrequin", "azrael"])
def test_les_kills_sortent_des_deux_formes(who):
    profil = read_profile(_payload(who))
    assert profil.stats["kills"].value > 0


def test_le_libelle_reel_est_conserve():
    """« BR Kills » et « Career Kills » ne se traduisent pas l'un en l'autre."""
    assert read_profile(_payload("azrael")).stats["kills"].label == "BR Kills"
    assert read_profile(_payload("kingsrequin")).stats["kills"].label == "Career Kills"


def test_une_notion_absente_est_absente_pas_zero():
    """« Azraël : 0 réanimation » serait un mensonge, pas une valeur par défaut.

    Le cas est réel : KingsRequin publie « Career Revives », Azraël ne publie
    aucun tracker de réanimation."""
    assert "revives" not in read_profile(_payload("azrael")).stats
    assert read_profile(_payload("kingsrequin")).stats["revives"].value > 0


def test_le_top_pourcent_du_ladder_quand_c_est_un_nombre():
    assert read_profile(_payload("azrael")).rank.top_percent == pytest.approx(49.45)


def test_no_game_this_split_ne_devient_pas_un_nombre():
    assert read_profile(_payload("kingsrequin")).rank.top_percent is None


def test_une_position_de_ladder_a_moins_un_est_absente():
    for who in ("kingsrequin", "azrael"):
        assert read_profile(_payload(who)).rank.ladder_pos is None


def test_le_rang_mondial_par_statistique():
    kills = read_profile(_payload("azrael")).stats["kills"]
    assert kills.world_pos == 37089
    assert kills.top_percent == pytest.approx(2.73)


def test_identite_et_etat_en_jeu():
    profil = read_profile(_payload("azrael"))
    assert profil.name == "Azrael_ttv"
    assert profil.uid == "2274044345"
    assert profil.level == 1354
    assert profil.rank.name == "Gold"
    assert profil.rank.div == 3
    assert profil.legend == "Fuse"
    assert profil.state


def test_une_reponse_d_erreur_ne_donne_pas_de_profil():
    assert read_profile({"Error": "Player not found"}) is None
    assert read_profile({}) is None
```

- [ ] **Étape 2 : vérifier que ça échoue**

Lancer : `python3 -m pytest tests/test_apex_reader.py -q`
Attendu : `ModuleNotFoundError: No module named 'bot.core.apex.reader'`

- [ ] **Étape 3 : écrire le lecteur**

```python
# bot/core/apex/reader.py
"""Interprète une réponse `/bridge` sans supposer sa forme.

Le piège, vérifié sur deux comptes réels le 2026-08-08 : les statistiques ne
portent pas les mêmes clés d'un joueur à l'autre. Les kills de KingsRequin sont
dans `career_kills` (« Career Kills »), ceux d'Azraël dans `specialEvent_kills`
(« BR Kills »). Les trackers dépendent de ce que chacun a épinglé en jeu.

D'où la règle : on cherche une NOTION par ses libellés connus, jamais par une
clé supposée, et ce qu'on ne trouve pas reste introuvé — jamais 0.

Aucun accès réseau ici : c'est ce qui rend le piège testable sur fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Une notion → les libellés sous lesquels l'API la publie, du plus précis au
# plus générique. La casse est ignorée à la comparaison.
STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "kills": ("Career Kills", "BR Kills", "Kills"),
    "wins": ("Career Wins", "BR Wins", "Wins"),
    "damage": ("Career Damage", "BR Damage", "Damage"),
    "revives": ("Career Revives", "BR Revives", "Revives"),
    "headshots": ("Career Headshots", "BR Headshots", "Headshots"),
    "matches": ("Games Played", "BR Games Played", "Matches Played"),
}


@dataclass(frozen=True)
class StatValue:
    label: str
    value: int
    world_pos: int | None = None
    top_percent: float | None = None


@dataclass(frozen=True)
class RankInfo:
    name: str
    div: int
    score: int
    img: str = ""
    top_percent: float | None = None
    ladder_pos: int | None = None


@dataclass(frozen=True)
class PlayerProfile:
    name: str
    uid: str
    platform: str
    level: int
    level_percent: int
    avatar: str
    banned: bool
    ban_reason: str
    rank: RankInfo | None
    state: str
    in_game: bool
    legend: str | None
    stats: dict[str, StatValue] = field(default_factory=dict)


def _num(value: Any) -> float | None:
    """Le nombre, ou None. L'API glisse des phrases là où on attend un chiffre :
    `ALStopPercent` vaut « No game this split » pour qui n'a pas joué du split."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int | None:
    """Une position de classement. `-1` signifie « non classé » : c'est une
    absence, pas un rang."""
    number = _num(value)
    if number is None or number < 0:
        return None
    return int(number)


def _world_ranks(payload: dict) -> dict[str, tuple[int | None, float | None]]:
    """Position mondiale par libellé de tracker, glanée sur toutes les légendes.

    Le même tracker apparaît sous plusieurs légendes ; on garde la meilleure
    position trouvée, qui est celle du compte.
    """
    found: dict[str, tuple[int | None, float | None]] = {}
    legends = payload.get("legends", {}).get("all", {})
    if not isinstance(legends, dict):
        return found
    for body in legends.values():
        for item in (body or {}).get("data") or []:
            label = str(item.get("name", "")).lower()
            rank = item.get("rank") or {}
            pos = _positive_int(rank.get("rankPos"))
            pct = _num(rank.get("topPercent"))
            if not label or (pos is None and pct is None):
                continue
            previous = found.get(label)
            if previous is None or (pos is not None and (previous[0] is None or pos < previous[0])):
                found[label] = (pos, pct)
    return found


def _read_stats(payload: dict) -> dict[str, StatValue]:
    """Les notions connues, telles que ce joueur les publie."""
    total = payload.get("total") or {}
    if not isinstance(total, dict):
        return {}
    # index libellé → (libellé d'origine, valeur)
    by_label: dict[str, tuple[str, int]] = {}
    for entry in total.values():
        if not isinstance(entry, dict):
            continue
        label = entry.get("name")
        value = _num(entry.get("value"))
        if not label or value is None:
            continue
        by_label.setdefault(str(label).lower(), (str(label), int(value)))

    ranks = _world_ranks(payload)
    stats: dict[str, StatValue] = {}
    for notion, aliases in STAT_ALIASES.items():
        for alias in aliases:
            hit = by_label.get(alias.lower())
            if hit is None:
                continue
            pos, pct = ranks.get(alias.lower(), (None, None))
            stats[notion] = StatValue(label=hit[0], value=hit[1], world_pos=pos, top_percent=pct)
            break
    return stats


def _read_rank(payload: dict) -> RankInfo | None:
    rank = (payload.get("global") or {}).get("rank") or {}
    if not rank.get("rankName"):
        return None
    return RankInfo(
        name=str(rank.get("rankName")),
        div=int(_num(rank.get("rankDiv")) or 0),
        score=int(_num(rank.get("rankScore")) or 0),
        img=str(rank.get("rankImg") or ""),
        top_percent=_num(rank.get("ALStopPercent")),
        ladder_pos=_positive_int(rank.get("ladderPosPlatform")),
    )


def read_profile(payload: Any) -> PlayerProfile | None:
    """Le profil, ou None si la réponse n'en contient pas."""
    if not isinstance(payload, dict) or "Error" in payload:
        return None
    glob = payload.get("global")
    if not isinstance(glob, dict) or not glob.get("name"):
        return None

    bans = glob.get("bans") or {}
    realtime = payload.get("realtime") or {}
    return PlayerProfile(
        name=str(glob.get("name")),
        uid=str(glob.get("uid") or ""),
        platform=str(glob.get("platform") or ""),
        level=int(_num(glob.get("level")) or 0),
        level_percent=int(_num(glob.get("toNextLevelPercent")) or 0),
        avatar=str(glob.get("avatar") or ""),
        banned=bool(bans.get("isActive")),
        ban_reason=str(bans.get("last_banReason") or ""),
        rank=_read_rank(payload),
        state=str(realtime.get("currentStateAsText") or ""),
        in_game=bool(_num(realtime.get("isInGame"))),
        legend=str(realtime.get("selectedLegend")) if realtime.get("selectedLegend") else None,
        stats=_read_stats(payload),
    )
```

- [ ] **Étape 4 : vérifier que ça passe**

Lancer : `python3 -m pytest tests/test_apex_reader.py -q` → 10 passed

- [ ] **Étape 5 : commiter**

```bash
git add bot/core/apex/reader.py tests/test_apex_reader.py tests/fixtures/apex/
git commit -m "feat(apex): lire une notion, pas une clé — la forme change selon le joueur"
```

---

### Tâche 3 : le service — le profil d'un joueur

**Fichiers :**
- Créer : `bot/core/apex/service.py`
- Test : `tests/test_apex_service.py`

**Interfaces consommées :** `ApexClient.get`, `read_profile`
**Interfaces produites :**
- `ApexLegendsService(client: ApexClient | None = None)`
- `.available -> bool` · `.get_tool_definition() -> dict`
- `await .execute(action: str, player_name: str = "", platform: str = "PC") -> str`

Ce que `player_stats` doit rendre, et que l'ancienne version taisait : l'état en
jeu, le niveau, le top % du ladder, et le rang mondial par statistique.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# tests/test_apex_service.py
"""Les actions offertes au LLM, et leur rendu."""
import json
import pathlib

import pytest

from bot.core.apex.service import ApexLegendsService

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex"


class _FakeClient:
    """Rend la fixture correspondant à l'endpoint demandé."""

    available = True

    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = []

    async def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        value = self._mapping[endpoint]
        return value(params) if callable(value) else value


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _service(mapping):
    return ApexLegendsService(client=_FakeClient(mapping))


@pytest.mark.asyncio
async def test_le_profil_annonce_l_etat_en_jeu_et_la_legende():
    svc = _service({"bridge": _fixture("bridge_azrael")})
    texte = await svc.execute("player_stats", "Azrael_ttv")
    assert "Azrael_ttv" in texte
    assert "Fuse" in texte
    assert "Gold" in texte


@pytest.mark.asyncio
async def test_le_profil_donne_les_kills_et_le_rang_mondial():
    svc = _service({"bridge": _fixture("bridge_azrael")})
    texte = await svc.execute("player_stats", "Azrael_ttv")
    assert "92" in texte              # 92 182 kills, quel que soit le séparateur
    assert "2.73" in texte or "2,73" in texte


@pytest.mark.asyncio
async def test_un_joueur_introuvable_le_dit_sans_inventer():
    svc = _service({"bridge": {"Error": "Player not found"}})
    texte = await svc.execute("player_stats", "PersonneIci")
    assert "PersonneIci" in texte
    assert "trouv" in texte.lower()


@pytest.mark.asyncio
async def test_sans_pseudo_on_ne_part_pas_en_reseau():
    client = _FakeClient({"bridge": {}})
    texte = await ApexLegendsService(client=client).execute("player_stats", "")
    assert client.calls == []
    assert "pseudo" in texte.lower()


@pytest.mark.asyncio
async def test_une_erreur_reseau_remonte_telle_quelle():
    svc = _service({"bridge": "Apex API error (HTTP 500)"})
    assert "500" in await svc.execute("player_stats", "X")


@pytest.mark.asyncio
async def test_une_action_inconnue_ne_plante_pas():
    assert "inconnue" in (await _service({}).execute("danse")).lower()
```

- [ ] **Étape 2 : vérifier que ça échoue**

Lancer : `python3 -m pytest tests/test_apex_service.py -q`
Attendu : `ModuleNotFoundError: No module named 'bot.core.apex.service'`

- [ ] **Étape 3 : écrire le service (profil seulement, le reste en tâche 4)**

```python
# bot/core/apex/service.py
"""Les actions Apex offertes au LLM, rendues en texte lisible.

Le service ne décide de rien : il va chercher, met en forme, et dit clairement
quand il n'a pas. Ce qu'il ne sait pas faire est annoncé dans la description de
l'outil, pour que le modèle n'aille pas le chercher ailleurs.
"""
from __future__ import annotations

import os

from bot.core.apex.client import ApexClient
from bot.core.apex.reader import PlayerProfile, read_profile


def _fr(n: int) -> str:
    """12345 → « 12 345 » (espace insécable fine, lisible dans un chat)."""
    return f"{n:,}".replace(",", " ")


class ApexLegendsService:
    def __init__(self, client: ApexClient | None = None) -> None:
        self._client = client or ApexClient(os.environ.get("APEX_API_KEY", ""))

    @property
    def available(self) -> bool:
        return bool(self._client.available)

    def get_tool_definition(self) -> dict:
        from bot.core.apex.tool import APEX_LEGENDS_TOOL   # tâche 5
        return APEX_LEGENDS_TOOL

    async def execute(self, action: str, player_name: str = "", platform: str = "PC") -> str:
        if action == "player_stats":
            return await self._player_stats(player_name, platform)
        return f"Action inconnue : {action}"

    async def _player_stats(self, player_name: str, platform: str) -> str:
        if not player_name:
            return "Il me faut un pseudo Apex pour chercher."
        data = await self._client.get("bridge", {"player": player_name, "platform": platform or "PC"})
        if isinstance(data, str):
            return data
        profil = read_profile(data)
        if profil is None:
            erreur = data.get("Error") if isinstance(data, dict) else ""
            return f"{player_name} : pas trouvé sur l'API Apex ({erreur or 'compte inconnu'})."
        return self._render_profile(profil)

    def _render_profile(self, p: PlayerProfile) -> str:
        lignes = [f"{p.name} — niveau {_fr(p.level)} ({p.platform})"]
        if p.rank:
            rang = f"Rang BR : {p.rank.name}"
            if p.rank.div:
                rang += f" {p.rank.div}"
            rang += f" ({_fr(p.rank.score)} RP)"
            if p.rank.top_percent is not None:
                rang += f" — top {p.rank.top_percent} % du ladder"
            lignes.append(rang)
        etat = p.state or "état inconnu"
        if p.legend:
            etat += f", sur {p.legend}"
        lignes.append(f"État : {etat}")
        if p.banned:
            lignes.append(f"⚠️ Banni ({p.ban_reason or 'raison inconnue'})")
        for stat in p.stats.values():
            ligne = f"{stat.label} : {_fr(stat.value)}"
            if stat.top_percent is not None:
                ligne += f" (top {stat.top_percent} % mondial"
                if stat.world_pos is not None:
                    ligne += f", {_fr(stat.world_pos)}ᵉ"
                ligne += ")"
            lignes.append(ligne)
        return "\n".join(lignes)
```

- [ ] **Étape 4 : vérifier que ça passe**

Lancer : `python3 -m pytest tests/test_apex_service.py -q` → 6 passed
(La tâche 5 crée `tool.py` ; `get_tool_definition` n'est pas encore appelé ici.)

- [ ] **Étape 5 : commiter**

```bash
git add bot/core/apex/service.py tests/test_apex_service.py
git commit -m "feat(apex): un profil qui dit l'état en jeu et le rang mondial"
```

---

### Tâche 4 : les quatre autres actions, et le code mort

**Fichiers :**
- Modifier : `bot/core/apex/service.py`
- Test : `tests/test_apex_service.py` (ajouts)

Trois corrections portées par cette tâche, constatées sur les fixtures :
`wildcard` est un mode qui tourne et que l'ancien formateur ignorait ;
`predator` ne publie plus de clé `AP` (arènes) — la moitié du formateur lisait
du vide ; `news` répond `[]` et disparaît.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# à ajouter dans tests/test_apex_service.py

@pytest.mark.asyncio
async def test_la_rotation_montre_les_quatre_modes_dont_wildcard():
    svc = _service({"maprotation": _fixture("maprotation")})
    texte = await svc.execute("map_rotation")
    for mode in ("battle_royale", "ranked", "ltm", "wildcard"):
        assert mode in texte.lower() or mode.replace("_", " ") in texte.lower()


@pytest.mark.asyncio
async def test_la_rotation_donne_le_temps_restant():
    texte = await _service({"maprotation": _fixture("maprotation")}).execute("map_rotation")
    assert ":" in texte


@pytest.mark.asyncio
async def test_le_predator_ne_cherche_plus_les_arenes():
    """La clé `AP` a disparu de l'API : la moitié de l'ancien rendu était morte."""
    texte = await _service({"predator": _fixture("predator")}).execute("predator")
    assert "PC" in texte
    assert "arena" not in texte.lower()


@pytest.mark.asyncio
async def test_le_craft_liste_les_lots():
    texte = await _service({"crafting": _fixture("crafting")}).execute("crafting")
    assert len(texte.splitlines()) >= 2


@pytest.mark.asyncio
async def test_les_serveurs_rendent_un_etat():
    texte = await _service({"servers": _fixture("servers")}).execute("server_status")
    assert texte.strip()


@pytest.mark.asyncio
async def test_l_action_news_n_existe_plus():
    """L'endpoint répond [] : mieux vaut pas d'action qu'une action muette."""
    assert "inconnue" in (await _service({}).execute("news")).lower()
```

- [ ] **Étape 2 : vérifier que ça échoue**

Lancer : `python3 -m pytest tests/test_apex_service.py -q`
Attendu : les six nouveaux tests échouent (`Action inconnue : map_rotation`)

- [ ] **Étape 3 : compléter le service**

Dans `execute`, remplacer le corps par le routage complet :

```python
    async def execute(self, action: str, player_name: str = "", platform: str = "PC") -> str:
        if action == "player_stats":
            return await self._player_stats(player_name, platform)
        if action == "map_rotation":
            return await self._map_rotation()
        if action == "crafting":
            return await self._crafting()
        if action == "predator":
            return await self._predator()
        if action == "server_status":
            return await self._server_status()
        return f"Action inconnue : {action}"
```

Puis ajouter les quatre méthodes :

```python
    # Les libellés des modes, dans l'ordre d'intérêt. `wildcard` manquait :
    # c'est un mode qui tourne, et son absence donnait une rotation incomplète.
    _MODES = (
        ("battle_royale", "Battle Royale"),
        ("ranked", "Ranked"),
        ("ltm", "Mode temporaire"),
        ("wildcard", "Wildcard"),
    )

    async def _map_rotation(self) -> str:
        data = await self._client.get("maprotation", {"version": "2"})
        if isinstance(data, str):
            return data
        lignes = []
        for cle, nom in self._MODES:
            mode = data.get(cle)
            if not isinstance(mode, dict):
                continue
            courant = mode.get("current") or {}
            suivant = mode.get("next") or {}
            ligne = f"{nom} : {courant.get('map', '?')}"
            if courant.get("remainingTimer"):
                ligne += f" (encore {courant['remainingTimer']})"
            if suivant.get("map"):
                ligne += f" → puis {suivant['map']}"
            lignes.append(ligne)
        return "\n".join(lignes) or "Pas de rotation disponible."

    async def _crafting(self) -> str:
        data = await self._client.get("crafting")
        if isinstance(data, str):
            return data
        if not isinstance(data, list):
            return "Pas de données de craft."
        lignes = []
        for lot in data:
            if not isinstance(lot, dict):
                continue
            objets = [
                (o.get("itemType") or {}).get("name", "?")
                for o in lot.get("bundleContent") or []
            ]
            if objets:
                lignes.append(f"{lot.get('bundleType', '?')} : {', '.join(objets)}")
        return "\n".join(lignes) or "Pas de données de craft."

    async def _predator(self) -> str:
        """Seuil Predator. L'API ne publie plus que `RP` : les arènes ont disparu."""
        data = await self._client.get("predator")
        if isinstance(data, str):
            return data
        rp = (data or {}).get("RP") or {}
        lignes = []
        for cle, nom in (("PC", "PC"), ("PS4", "PS4"), ("X1", "Xbox")):
            info = rp.get(cle)
            if not isinstance(info, dict):
                continue
            ligne = f"{nom} : {info.get('val', '?')} RP pour être Predator"
            if info.get("totalMastersAndPreds") is not None:
                ligne += f" ({info['totalMastersAndPreds']} Masters+Preds)"
            lignes.append(ligne)
        return "\n".join(lignes) or "Pas de données Predator."

    async def _server_status(self) -> str:
        data = await self._client.get("servers")
        if isinstance(data, str):
            return data
        lignes = []
        for groupe in (data or {}).values():
            if not isinstance(groupe, dict):
                continue
            for nom, info in groupe.items():
                if isinstance(info, dict) and info.get("Status"):
                    marque = "✅" if info["Status"] == "UP" else "❌"
                    lignes.append(f"{marque} {nom} : {info['Status']}")
        return "\n".join(lignes[:10]) or "Pas de données serveurs."
```

- [ ] **Étape 4 : vérifier que ça passe**

Lancer : `python3 -m pytest tests/test_apex_service.py -q` → 12 passed

- [ ] **Étape 5 : commiter**

```bash
git add bot/core/apex/service.py tests/test_apex_service.py
git commit -m "feat(apex): la rotation complète, et deux formateurs qui lisaient du vide"
```

---

### Tâche 5 : l'outil, et le garde anti-cascade

**Fichiers :**
- Créer : `bot/core/apex/tool.py`
- Modifier : `bot/core/apex/__init__.py`
- Test : `tests/test_apex_tool.py`

C'est la leçon du 2026-08-07 : privé de réponse, le modèle a enchaîné six outils.
La description doit donc **nommer ce que l'API ne donne pas**, et la porte de
sortie utile.

- [ ] **Étape 1 : écrire les tests qui échouent**

```python
# tests/test_apex_tool.py
"""Le schéma de l'outil Apex, et ce qu'il empêche."""
from bot.core.apex.tool import APEX_LEGENDS_TOOL


def test_les_actions_offertes():
    enum = APEX_LEGENDS_TOOL["function"]["parameters"]["properties"]["action"]["enum"]
    assert enum == ["player_stats", "map_rotation", "crafting", "predator", "server_status"]
    assert "news" not in enum


def test_la_description_nomme_ce_qui_est_hors_de_portee():
    """Sans ça, le modèle part chercher ailleurs et sature la boucle d'outils."""
    desc = APEX_LEGENDS_TOOL["function"]["description"].lower()
    assert "classement" in desc
    assert "historique" in desc
    assert "ne cherche pas ailleurs" in desc


def test_les_plateformes_acceptees():
    props = APEX_LEGENDS_TOOL["function"]["parameters"]["properties"]
    assert props["platform"]["enum"] == ["PC", "PS4", "X1"]
```

- [ ] **Étape 2 : vérifier que ça échoue**

Lancer : `python3 -m pytest tests/test_apex_tool.py -q`
Attendu : `ModuleNotFoundError: No module named 'bot.core.apex.tool'`

- [ ] **Étape 3 : écrire l'outil**

```python
# bot/core/apex/tool.py
"""Le schéma de l'outil Apex présenté au LLM.

La description dit aussi ce que l'API NE donne PAS. Le 2026-08-07, faute de
cette phrase, une question sur le top 3 mondial a envoyé le modèle sur trois
`web_search` et un `scrape_url` avant de saturer la boucle d'outils.
"""

APEX_LEGENDS_TOOL = {
    "type": "function",
    "function": {
        "name": "apex_legends",
        "description": (
            "Données Apex Legends. À n'utiliser que pour une question précise sur "
            "le jeu ou sur un joueur.\n"
            "ACTIONS : player_stats → profil d'un joueur (rang, niveau, état en "
            "jeu, kills et rang mondial). Demande 'player_name' et 'platform' "
            "(PC par défaut). · map_rotation → cartes en cours et suivantes. · "
            "crafting → lots du replicator. · predator → seuil pour Predator. · "
            "server_status → état des serveurs.\n"
            "CE QUE CETTE API NE DONNE PAS : le classement mondial (top 500, "
            "classement par légende ou par pays), l'historique des matchs, la "
            "boutique, les nouveautés du jeu. Si on te le demande, dis-le "
            "simplement et propose à la place la position et le top % du joueur "
            "via player_stats — ne cherche pas ailleurs, aucun site ne te le "
            "donnera dans un format exploitable.\n"
            "UTILISE : « c'est quoi le rank de Daltoosh ? » → player_stats · "
            "« quelle map en ce moment ? » → map_rotation\n"
            "N'UTILISE PAS : « Apex c'est nul » → une opinion, pas une demande de "
            "données."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "player_stats",
                        "map_rotation",
                        "crafting",
                        "predator",
                        "server_status",
                    ],
                    "description": "La donnée voulue",
                },
                "player_name": {
                    "type": "string",
                    "description": "Le pseudo Apex, requis pour player_stats",
                },
                "platform": {
                    "type": "string",
                    "enum": ["PC", "PS4", "X1"],
                    "description": "La plateforme, PC par défaut",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}
```

Puis dans `bot/core/apex/__init__.py` :

```python
from bot.core.apex.client import ApexClient
from bot.core.apex.service import ApexLegendsService
from bot.core.apex.tool import APEX_LEGENDS_TOOL

__all__ = ["ApexClient", "ApexLegendsService", "APEX_LEGENDS_TOOL"]
```

- [ ] **Étape 4 : vérifier que ça passe**

Lancer : `python3 -m pytest tests/test_apex_tool.py tests/test_apex_service.py -q` → 15 passed

- [ ] **Étape 5 : commiter**

```bash
git add bot/core/apex/tool.py bot/core/apex/__init__.py tests/test_apex_tool.py
git commit -m "feat(apex): dire au modèle ce que l'API ne sait pas faire"
```

---

### Tâche 6 : la bascule

**Fichiers :**
- Supprimer : `bot/core/apex_api.py`
- Modifier : `bot/bootstrap.py` (lignes 25 et 90)
- Remplacer : `tests/test_apex_api.py` → couvert par les trois nouveaux fichiers

Aucun autre appelant : `discord/handlers.py` et `twitch/handlers.py` passent par
`bot.apex_api`, un attribut posé dans `main.py` — l'interface publique
(`available`, `get_tool_definition`, `execute`) ne change pas.

- [ ] **Étape 1 : vérifier qu'aucun appelant n'a été oublié**

```bash
grep -rn "apex_api\|ApexLegendsService\|APEX_LEGENDS_TOOL" --include=*.py . | grep -v __pycache__
```

Attendu : seulement `bot/bootstrap.py`, les tests, et les attributs `bot.apex_api`.

- [ ] **Étape 2 : rediriger les imports**

Dans `bot/bootstrap.py`, aux deux endroits :

```python
    from bot.core.apex import ApexLegendsService
```

- [ ] **Étape 3 : supprimer l'ancien module et son test**

```bash
git rm bot/core/apex_api.py tests/test_apex_api.py
```

- [ ] **Étape 4 : vérifier l'ensemble**

```bash
python3 -m pytest -q
python3 -c "import bot.bootstrap"
ruff check --output-format=concise bot/core/apex/ tests/test_apex_*.py
```

Attendu : suite entière verte, import sans erreur, ruff sans avertissement neuf.

- [ ] **Étape 5 : commiter**

```bash
git add -A
git commit -m "refactor(apex): un paquet à la place d'un fichier fourre-tout"
```

---

## Vérification de fin de phase

- [ ] `python3 -m pytest -q` — suite entière verte
- [ ] `grep -rn "career_kills" bot/` ne renvoie **rien** (aucune clé en dur)
- [ ] `grep -rn "\"news\"" bot/core/apex/` ne renvoie rien
- [ ] Appel réel de bout en bout, hors test :

```bash
python3 -c "
import asyncio, os
os.environ.setdefault('APEX_API_KEY', open('.env').read().split('APEX_API_KEY=')[1].split(chr(10))[0].strip())
from bot.core.apex import ApexLegendsService
svc = ApexLegendsService()
print(asyncio.run(svc.execute('player_stats', 'Azrael_ttv')))
print(asyncio.run(svc.execute('map_rotation')))
"
```

Attendu : le profil d'Azraël avec son état en jeu et son top % mondial, puis les
quatre modes de rotation.
