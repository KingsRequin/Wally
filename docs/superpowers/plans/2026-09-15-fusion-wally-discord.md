# Fusion de wally-discord dans Wally — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Porter dans Wally les quatre fonctions vivantes du bot Node `wally-discord` (salons vocaux temporaires, journal de modération, salon de statut du stream, embed de bienvenue), puis éteindre le Node.

**Architecture:** Quatre modules `bot/discord/*.py` de fonctions `async (bot, …)`, testables sans gateway. Chacun lit sa propre sous-section de `discord:` dans la config, livrée DÉSACTIVÉE (`null` / liste vide) tant que le Node tourne. La coupure (Task 5) allume les quatre en même temps qu'elle arrête le Node.

**Tech Stack:** Python 3 asyncio, discord.py, aiosqlite, httpx, loguru, pytest (`asyncio_mode = auto`).

**Spec:** `docs/superpowers/specs/2026-09-15-fusion-wally-discord-design.md`

## Global Constraints

- `loguru` uniquement ; toute exception journalisée avec `{e!r}` (jamais `{e}`) — `scripts/lint_logs.py`.
- Aucun `except` muet : log, ou commentaire qui dit POURQUOI le silence — `scripts/lint_silences.py`.
- Chaque champ de config ajouté doit être LU dans `bot/` dans la MÊME tâche — `tests/test_config_sans_bouton_mort.py`. D'où : pas de tâche « config seule ».
- Chaque fonction ajoutée a un appelant dans la même tâche — `scripts/lint_mort.py`.
- `clé: null` en YAML : `discord_raw.pop("x", None) or {}`, jamais `pop("x", {})`.
- Aucun handler ne lève : `try/except Exception` + `logger.warning("… {e!r}")`.
- Un `@bot.event on_voice_state_update` est INTERDIT : il remplacerait `WallyDiscord.on_voice_state_update` (accueil vocal). On appelle depuis la méthode.
- Ne PAS porter la purge du salon `1267122210166935563` (c'est `journal_channel_id` de Wally).
- Rien n'est allumé en prod avant la Task 5 (double création de salons, doubles embeds).
- CLAUDE.md du dépôt : attendre l'accord de l'owner entre phases. **Une tâche = une phase.** Le plafond de 5 fichiers est dépassé par les fichiers de colle (`config.yaml`, `config.example.yaml`, `mixins/__init__.py`, `events/__init__.py`) que le cliquet `test_config_sans_bouton_mort.py` oblige à livrer avec leur consommateur ; dépassement accepté par l'owner à la validation du plan.
- Vérifications avant chaque commit de fin de phase :
  ```bash
  python3 -m pytest tests/ -q
  python3 scripts/lint_types.py && python3 scripts/lint_silences.py && python3 scripts/lint_ruff.py
  python3 scripts/lint_logs.py && python3 scripts/lint_mort.py
  ```
- Publication : `git push public feat/site-redesign-arcade:main` + rebuild
  `GIT_HASH=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) docker compose up -d --build wally`.

## File Structure

| Fichier | Rôle | Task |
|---|---|---|
| `bot/config.py` | 4 dataclasses + construction dans `Config.load()` | 1–4 |
| `config.yaml`, `config.example.yaml` | sous-sections `discord.*` (désactivées) | 1–4 |
| `bot/db/database.py` | table `salons_vocaux_temporaires` + mixin dans `Database` | 1 |
| `bot/db/mixins/salons.py` (+ `__init__.py`) | 3 helpers de la table | 1 |
| `bot/discord/salons_temporaires.py` | création / suppression / ménage | 1, 2 |
| `bot/discord/bot.py` | appel en tête de `on_voice_state_update`, ménage dans `on_ready` | 1 |
| `bot/discord/journal_moderation.py` | embeds dans le salon de logs | 2 |
| `bot/discord/events/moderation.py` (+ `events/__init__.py`) | `on_raw_message_delete` | 2 |
| `bot/discord/events/edits.py` | appel du journal en tête de `on_message_edit` | 2 |
| `bot/discord/statut_stream.py` | renommage du salon statut | 3 |
| `bot/main.py` | `on_poll` du `StreamWatcher` → statut | 3 |
| `bot/discord/bienvenue.py` | embed de bienvenue | 4 |
| `bot/discord/events/members.py` | appel dans `on_member_join` | 4 |

---

### Task 1: Salons vocaux temporaires (livrés désactivés)

**Files:**
- Modify: `bot/config.py` (après `SpamDetectionConfig` ~l.139 ; champ dans `DiscordConfig` ~l.213 ; `Config.load` ~l.771 et ~l.790)
- Modify: `config.yaml`, `config.example.yaml` (section `discord:`)
- Modify: `bot/db/database.py` (import mixins l.10-23, `SCHEMA`, bases de `Database` l.517-530)
- Create: `bot/db/mixins/salons.py` ; Modify: `bot/db/mixins/__init__.py`
- Create: `bot/discord/salons_temporaires.py`
- Modify: `bot/discord/bot.py` (`on_ready` l.665, `on_voice_state_update` l.714)
- Test: `tests/discord/test_salons_temporaires.py`, `tests/test_db_salons_temporaires.py`

**Interfaces:**
- Produces: `SalonsTemporairesConfig(salon_createur_id: int | None, noms: list[str])` à `config.discord.salons_temporaires`
- Produces: `Database.salon_temporaire_ajouter(channel_id: int, guild_id: int) -> None`, `Database.salon_temporaire_retirer(channel_id: int) -> None`, `Database.salons_temporaires() -> set[int]`
- Produces: `async sur_changement_vocal(bot, member, before, after) -> None`, `async menage_au_boot(bot) -> None` — ne lèvent jamais

- [ ] **Step 1: Test du mixin (échoue)**

`tests/test_db_salons_temporaires.py` :
```python
from bot.db.database import Database


async def test_registre_des_salons_temporaires(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        assert await db.salons_temporaires() == set()
        await db.salon_temporaire_ajouter(111, 9)
        await db.salon_temporaire_ajouter(111, 9)   # idempotent
        await db.salon_temporaire_ajouter(222, 9)
        assert await db.salons_temporaires() == {111, 222}
        await db.salon_temporaire_retirer(111)
        await db.salon_temporaire_retirer(333)      # absent : sans erreur
        assert await db.salons_temporaires() == {222}
    finally:
        await db.close()
```

- [ ] **Step 2: Lancer — attendu FAIL (`AttributeError: 'Database' object has no attribute 'salons_temporaires'`)**

Run: `python3 -m pytest tests/test_db_salons_temporaires.py -q -n 0`

- [ ] **Step 3: Table + mixin**

`bot/db/mixins/salons.py` :
```python
"""Le registre des salons vocaux temporaires (`bot/discord/salons_temporaires.py`).

Il remplace le `data/voice_channels.json` du bot Node `wally-discord`. Le
registre est ce qui distingue un salon créé par Wally — qu'il peut supprimer
quand il se vide — d'un salon vocal ordinaire, qu'il ne doit jamais toucher.
"""
from __future__ import annotations

import time

import aiosqlite


class SalonsMixin:
    _conn: aiosqlite.Connection

    # Déclarés pour le type-check (implémentés dans Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def execute(self, query: str, params=()): ...

    async def salon_temporaire_ajouter(self, channel_id: int, guild_id: int) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO salons_vocaux_temporaires "
            "(channel_id, guild_id, created_at) VALUES (?, ?, ?)",
            (str(channel_id), str(guild_id), time.time()),
        )

    async def salon_temporaire_retirer(self, channel_id: int) -> None:
        await self.execute(
            "DELETE FROM salons_vocaux_temporaires WHERE channel_id = ?",
            (str(channel_id),),
        )

    async def salons_temporaires(self) -> set[int]:
        rows = await self.fetch_all("SELECT channel_id FROM salons_vocaux_temporaires")
        return {int(r["channel_id"]) for r in rows}
```

`bot/db/mixins/__init__.py` : ajouter `from bot.db.mixins.salons import SalonsMixin` et `"SalonsMixin"` dans `__all__`.

`bot/db/database.py` : ajouter `SalonsMixin,` dans l'import `from bot.db.mixins import (...)` et dans les bases de `class Database(...)` (après `TcgMixin,`). Dans `SCHEMA`, ajouter :
```sql
-- Salons vocaux créés par Wally (salon « créateur »), supprimés quand ils se
-- vident. Ids en TEXT : un snowflake ne survit pas à un REAL.
CREATE TABLE IF NOT EXISTS salons_vocaux_temporaires (
    channel_id TEXT PRIMARY KEY,
    guild_id TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

- [ ] **Step 4: Lancer — attendu PASS**

Run: `python3 -m pytest tests/test_db_salons_temporaires.py -q -n 0`

- [ ] **Step 5: Tests du module (échouent)**

`tests/discord/test_salons_temporaires.py` :
```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.discord import salons_temporaires as st

CREATEUR = 500


class FauxDb:
    def __init__(self, ids=()):
        self.ids = set(ids)

    async def salon_temporaire_ajouter(self, channel_id, guild_id):
        self.ids.add(channel_id)

    async def salon_temporaire_retirer(self, channel_id):
        self.ids.discard(channel_id)

    async def salons_temporaires(self):
        return set(self.ids)


def _bot(db, createur=CREATEUR, noms=("Arène des Apex",)):
    cfg = SimpleNamespace(salon_createur_id=createur, noms=list(noms))
    bot = SimpleNamespace(
        db=db,
        config=SimpleNamespace(discord=SimpleNamespace(salons_temporaires=cfg)),
        salons={},
    )
    bot.get_channel = lambda cid: bot.salons.get(cid)
    return bot


def _salon(cid, membres=(), guild=SimpleNamespace(id=9), category="cat"):
    s = SimpleNamespace(id=cid, name=f"s{cid}", members=list(membres),
                        guild=guild, category=category)
    s.delete = AsyncMock()
    return s


def _etat(salon):
    return SimpleNamespace(channel=salon)


async def test_entrer_dans_le_createur_cree_enregistre_et_deplace():
    nouveau = _salon(777, guild=SimpleNamespace(id=9))
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock(return_value=nouveau))
    createur = _salon(CREATEUR, guild=guild)
    membre = SimpleNamespace(id=1, bot=False, move_to=AsyncMock(), display_name="A")
    db = FauxDb()

    await st.sur_changement_vocal(_bot(db), membre, _etat(None), _etat(createur))

    kwargs = guild.create_voice_channel.await_args.kwargs
    assert guild.create_voice_channel.await_args.args[0] == "Arène des Apex"
    assert kwargs["category"] == "cat"
    assert kwargs["overwrites"][membre].manage_channels is True
    assert db.ids == {777}
    membre.move_to.assert_awaited_once_with(nouveau)


async def test_un_bot_qui_entre_dans_le_createur_ne_cree_rien():
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock())
    membre = SimpleNamespace(id=1, bot=True, move_to=AsyncMock())
    await st.sur_changement_vocal(_bot(FauxDb()), membre, _etat(None),
                                  _etat(_salon(CREATEUR, guild=guild)))
    guild.create_voice_channel.assert_not_awaited()


async def test_deplacement_rate_supprime_le_salon_cree():
    nouveau = _salon(777)
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock(return_value=nouveau))
    membre = SimpleNamespace(id=1, bot=False, display_name="A",
                             move_to=AsyncMock(side_effect=discord.HTTPException(MagicMock(status=400), "parti")))
    db = FauxDb()
    await st.sur_changement_vocal(_bot(db), membre, _etat(None),
                                  _etat(_salon(CREATEUR, guild=guild)))
    nouveau.delete.assert_awaited_once()
    assert db.ids == set()


async def test_quitter_un_salon_gere_vide_le_supprime():
    salon = _salon(777, membres=[])
    db = FauxDb({777})
    membre = SimpleNamespace(id=1, bot=False)
    await st.sur_changement_vocal(_bot(db), membre, _etat(salon), _etat(None))
    salon.delete.assert_awaited_once()
    assert db.ids == set()


async def test_salon_non_gere_vide_jamais_supprime():
    salon = _salon(888, membres=[])
    await st.sur_changement_vocal(_bot(FauxDb({777})), SimpleNamespace(id=1, bot=False),
                                  _etat(salon), _etat(None))
    salon.delete.assert_not_awaited()


async def test_salon_gere_encore_occupe_garde():
    salon = _salon(777, membres=[object()])
    db = FauxDb({777})
    await st.sur_changement_vocal(_bot(db), SimpleNamespace(id=1, bot=False),
                                  _etat(salon), _etat(None))
    salon.delete.assert_not_awaited()
    assert db.ids == {777}


async def test_salon_deja_supprime_retire_la_ligne():
    salon = _salon(777, membres=[])
    salon.delete = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown Channel"))
    db = FauxDb({777})
    await st.sur_changement_vocal(_bot(db), SimpleNamespace(id=1, bot=False),
                                  _etat(salon), _etat(None))
    assert db.ids == set()


async def test_desactive_ne_fait_rien():
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock())
    salon = _salon(777, membres=[])
    db = FauxDb({777})
    await st.sur_changement_vocal(_bot(db, createur=None), SimpleNamespace(id=1, bot=False),
                                  _etat(salon), _etat(_salon(CREATEUR, guild=guild)))
    guild.create_voice_channel.assert_not_awaited()
    salon.delete.assert_not_awaited()


async def test_menage_au_boot():
    vide, occupe = _salon(1, membres=[]), _salon(2, membres=[object()])
    db = FauxDb({1, 2, 3})           # 3 : salon disparu pendant l'arrêt
    bot = _bot(db)
    bot.salons = {1: vide, 2: occupe}
    await st.menage_au_boot(bot)
    vide.delete.assert_awaited_once()
    occupe.delete.assert_not_awaited()
    assert db.ids == {2}


async def test_une_panne_ne_remonte_jamais():
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock(side_effect=RuntimeError("boom")))
    await st.sur_changement_vocal(_bot(FauxDb()), SimpleNamespace(id=1, bot=False, display_name="A"),
                                  _etat(None), _etat(_salon(CREATEUR, guild=guild)))
```

- [ ] **Step 6: Lancer — attendu FAIL (`ImportError: cannot import name 'salons_temporaires'`)**

Run: `python3 -m pytest tests/discord/test_salons_temporaires.py -q -n 0`

- [ ] **Step 7: Config**

`bot/config.py`, après `SpamDetectionConfig` :
```python
@dataclass
class SalonsTemporairesConfig:
    """Salon « créateur » : y entrer ouvre un salon vocal perso, supprimé vide.

    Repris du bot Node `wally-discord`. `salon_createur_id` à None → désactivé,
    ce qui est le bon défaut : deux bots sur le même salon créateur ouvriraient
    chacun un salon pour la même entrée.
    """
    salon_createur_id: int | None = None
    noms: list[str] = field(default_factory=list)
```
Dans `DiscordConfig`, après `spam_detection` :
```python
    salons_temporaires: SalonsTemporairesConfig = field(default_factory=SalonsTemporairesConfig)
```
Dans `Config.load`, après `spam_raw = discord_raw.pop("spam_detection", {})` :
```python
            salons_raw = discord_raw.pop("salons_temporaires", None) or {}
```
et remplacer la construction de `DiscordConfig` par :
```python
                discord=DiscordConfig(
                    **discord_raw,
                    spam_detection=SpamDetectionConfig(**spam_raw),
                    salons_temporaires=SalonsTemporairesConfig(**salons_raw),
                ),
```
`config.yaml` et `config.example.yaml`, dans `discord:` (avant `spam_detection:`) :
```yaml
  salons_temporaires:
    salon_createur_id: null   # allumé à la coupure du bot Node (1105088949887696988)
    noms: []                  # remplis à la coupure (199 noms du Node)
```

- [ ] **Step 8: Module**

`bot/discord/salons_temporaires.py` :
```python
"""Salons vocaux temporaires — repris du bot Node `wally-discord`.

Entrer dans le salon « créateur » ouvre un salon vocal au nom tiré au sort,
dans la même catégorie, dont l'arrivant reçoit la gestion ; le salon est
supprimé dès qu'il se vide. Le registre en base (`SalonsMixin`) est la seule
chose qui autorise une suppression : un salon vocal ordinaire vide n'est
jamais touché.

⚠️ Appelé depuis `WallyDiscord.on_voice_state_update`, jamais enregistré par
`@bot.event` : un second `on_voice_state_update` REMPLACERAIT la méthode de
classe, et l'accueil vocal de Wally disparaîtrait sans erreur.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_NOM_PAR_DEFAUT = "Nouveau salon"


async def sur_changement_vocal(bot: "WallyDiscord", member: Any, before: Any, after: Any) -> None:
    """Crée ou supprime un salon temporaire. Ne lève jamais."""
    createur = bot.config.discord.salons_temporaires.salon_createur_id
    if createur is None:
        return
    try:
        entre = after.channel is not None and after.channel.id == createur
        venait_du_createur = before.channel is not None and before.channel.id == createur
        if entre and not venait_du_createur and not member.bot:
            await _creer(bot, member, after.channel)
        # Pas de filtre `member.bot` ici : si Wally est le dernier à partir,
        # le salon est vide et doit disparaître comme pour n'importe qui.
        if before.channel is not None and not venait_du_createur and not before.channel.members:
            await _supprimer_si_gere(bot, before.channel)
    except Exception as e:  # noqa: BLE001 — un événement vocal ne fait pas tomber le bot
        logger.warning("salons temporaires : événement vocal non traité : {e!r}", e=e)


async def _creer(bot: "WallyDiscord", member: Any, createur: Any) -> None:
    noms = bot.config.discord.salons_temporaires.noms
    nom = random.choice(noms) if noms else _NOM_PAR_DEFAUT
    salon = await createur.guild.create_voice_channel(
        nom,
        category=createur.category,
        overwrites={member: discord.PermissionOverwrite(manage_channels=True, manage_roles=True)},
        reason="Salon vocal temporaire",
    )
    await bot.db.salon_temporaire_ajouter(salon.id, createur.guild.id)
    try:
        await member.move_to(salon)
    except discord.HTTPException as e:
        # Le membre a quitté le vocal entre l'entrée et le déplacement : le
        # salon ne recevra jamais personne, donc jamais d'événement « vidé ».
        logger.info("salons temporaires : déplacement impossible ({e!r}), salon retiré", e=e)
        await _supprimer(bot, salon)
        return
    logger.info("Salon vocal temporaire « {n} » ({c}) créé pour {m}",
                n=salon.name, c=salon.id, m=member.display_name)


async def _supprimer_si_gere(bot: "WallyDiscord", salon: Any) -> None:
    if salon.id not in await bot.db.salons_temporaires():
        return
    await _supprimer(bot, salon)
    logger.info("Salon vocal temporaire « {n} » ({c}) supprimé (vide)", n=salon.name, c=salon.id)


async def _supprimer(bot: "WallyDiscord", salon: Any) -> None:
    try:
        await salon.delete(reason="Salon vocal temporaire vide")
    except discord.NotFound:
        logger.info("salons temporaires : {c} déjà supprimé", c=salon.id)
    await bot.db.salon_temporaire_retirer(salon.id)


async def menage_au_boot(bot: "WallyDiscord") -> None:
    """Retire les salons vidés ou disparus pendant l'arrêt. Ne lève jamais."""
    if bot.config.discord.salons_temporaires.salon_createur_id is None:
        return
    try:
        for channel_id in await bot.db.salons_temporaires():
            salon = bot.get_channel(channel_id)
            if salon is None:
                await bot.db.salon_temporaire_retirer(channel_id)
                logger.info("salons temporaires : {c} disparu pendant l'arrêt, ligne retirée", c=channel_id)
            elif not salon.members:
                await _supprimer(bot, salon)
                logger.info("salons temporaires : « {n} » vide au boot, supprimé", n=salon.name)
    except Exception as e:  # noqa: BLE001 — le ménage ne bloque pas le démarrage
        logger.warning("salons temporaires : ménage au boot interrompu : {e!r}", e=e)
```

- [ ] **Step 9: Branchement dans `bot/discord/bot.py`**

Relire `bot/discord/bot.py` l.660-760 avant d'éditer. En tête de `on_voice_state_update`, AVANT `vs = getattr(self, "voice_service", None)` :
```python
        # Salons temporaires d'abord : ils ne dépendent pas du vocal de Wally,
        # et le `return` ci-dessous les couperait dès qu'il n'est pas connecté.
        from bot.discord.salons_temporaires import sur_changement_vocal
        await sur_changement_vocal(self, member, before, after)
```
Et adapter la docstring : `"""Salons temporaires, puis accueil des arrivants dans le salon vocal de Wally."""`.

Dans `on_ready`, juste après `_fire(self.sondages.reprendre())` :
```python
        from bot.discord.salons_temporaires import menage_au_boot
        _fire(menage_au_boot(self))
```

- [ ] **Step 10: Test d'enchaînement — l'accueil vocal survit**

Ajouter à `tests/discord/test_salons_temporaires.py` :
```python
async def test_l_accueil_vocal_est_toujours_appele(monkeypatch):
    from bot.discord.bot import WallyDiscord

    appels = []

    async def faux_sur_changement(bot, member, before, after):
        appels.append("salons")

    monkeypatch.setattr(st, "sur_changement_vocal", faux_sur_changement)
    vs = SimpleNamespace(is_connected=True, channel_id=42, greet_newcomer=AsyncMock(),
                         members_in_channel=lambda: [object()])
    self = SimpleNamespace(voice_service=vs, user=SimpleNamespace(id=999))
    membre = SimpleNamespace(id=1, bot=False)
    await WallyDiscord.on_voice_state_update(self, membre, _etat(None), _etat(SimpleNamespace(id=42)))
    assert appels == ["salons"]
    vs.greet_newcomer.assert_awaited_once_with(membre)
```

- [ ] **Step 11: Lancer — attendu PASS**

Run: `python3 -m pytest tests/discord/test_salons_temporaires.py tests/test_db_salons_temporaires.py tests/test_config_sans_bouton_mort.py tests/test_config.py -q -n 0`

- [ ] **Step 12: Vérifications complètes (Global Constraints), puis commit + push + rebuild**

```bash
git add bot/config.py config.yaml config.example.yaml bot/db/database.py bot/db/mixins/salons.py \
  bot/db/mixins/__init__.py bot/discord/salons_temporaires.py bot/discord/bot.py \
  tests/discord/test_salons_temporaires.py tests/test_db_salons_temporaires.py
git commit -m "feat(discord): salons vocaux temporaires repris de wally-discord (désactivés)"
```
Vérifier en prod : `docker compose logs --since 5m wally | grep -i "salons temporaires\|Traceback"` → rien (désactivé), boot normal, accueil vocal intact.

**Fin de phase — attendre l'accord de l'owner.**

---

### Task 2: Journal de modération (livré désactivé)

**Files:**
- Modify: `bot/config.py`, `config.yaml`, `config.example.yaml`
- Create: `bot/discord/journal_moderation.py`
- Create: `bot/discord/events/moderation.py` ; Modify: `bot/discord/events/__init__.py`
- Modify: `bot/discord/events/edits.py` (tête de `on_message_edit`)
- Modify: `bot/discord/salons_temporaires.py` (`_creer`, `_supprimer_si_gere`)
- Test: `tests/discord/test_journal_moderation.py`

**Interfaces:**
- Consumes: `salons_temporaires._creer` / `_supprimer_si_gere` (Task 1)
- Produces: `JournalModerationConfig(salon_id: int | None, guild_ids: list[int])` à `config.discord.journal_moderation`
- Produces: `async message_supprime(bot, payload: discord.RawMessageDeleteEvent) -> None`, `async message_modifie(bot, before: discord.Message, after: discord.Message) -> None`, `async vocal_cree(bot, member, salon) -> None`, `async vocal_supprime(bot, salon) -> None` — ne lèvent jamais

- [ ] **Step 1: Tests (échouent)**

`tests/discord/test_journal_moderation.py` :
```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from bot.discord import journal_moderation as jm

LOGS, COMMU = 70, 9


def _bot(salon_id=LOGS, guild_ids=(COMMU,)):
    logs = SimpleNamespace(id=LOGS, send=AsyncMock())
    salons = {LOGS: logs, 5: SimpleNamespace(id=5, name="discussions")}
    cfg = SimpleNamespace(salon_id=salon_id, guild_ids=list(guild_ids))
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(journal_moderation=cfg)))
    bot.get_channel = lambda cid: salons.get(cid)
    return bot, logs


def _message(contenu, *, bot_auteur=False, guild=COMMU, pieces=()):
    return SimpleNamespace(
        id=1, content=contenu, guild=SimpleNamespace(id=guild),
        channel=SimpleNamespace(id=5, name="discussions"),
        author=SimpleNamespace(bot=bot_auteur, name="alice"),
        attachments=[SimpleNamespace(filename=p, url=f"u/{p}") for p in pieces],
    )


def _embed(logs):
    return logs.send.await_args.kwargs["embed"]


async def test_suppression_en_cache_journalisee_sans_mention():
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1,
                              cached_message=_message("salut @everyone", pieces=["a.png"]))
    await jm.message_supprime(bot, payload)
    kwargs = logs.send.await_args.kwargs
    assert kwargs["allowed_mentions"].everyone is False
    valeurs = {f.name: f.value for f in _embed(logs).fields}
    assert valeurs["Contenu"] == "salut @​everyone"
    assert "a.png" in valeurs["Pièces jointes (1)"]


async def test_suppression_hors_cache():
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    valeurs = {f.name: f.value for f in _embed(logs).fields}
    assert valeurs["Contenu"] == "[contenu non disponible]"
    assert valeurs["Auteur"] == "inconnu"


async def test_guild_hors_liste_ignoree():
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=123, channel_id=5, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    logs.send.assert_not_awaited()


async def test_desactive():
    bot, logs = _bot(salon_id=None)
    await jm.message_supprime(bot, SimpleNamespace(guild_id=COMMU, channel_id=5,
                                                   message_id=1, cached_message=None))
    logs.send.assert_not_awaited()


async def test_contenu_tronque_a_1024():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("a"), _message("b" * 3000))
    valeurs = {f.name: f.value for f in _embed(logs).fields}
    assert len(valeurs["Après"]) == 1024


async def test_edition_sans_changement_de_texte_ignoree():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("lien"), _message("lien"))
    logs.send.assert_not_awaited()


async def test_edition_par_un_bot_ignoree():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("a", bot_auteur=True), _message("b", bot_auteur=True))
    logs.send.assert_not_awaited()


async def test_vocal_cree_et_supprime():
    bot, logs = _bot()
    salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
    await jm.vocal_cree(bot, SimpleNamespace(name="alice"), salon)
    await jm.vocal_supprime(bot, salon)
    assert logs.send.await_count == 2


async def test_salon_de_logs_injoignable_ne_leve_pas():
    bot, logs = _bot()
    logs.send.side_effect = discord.HTTPException(SimpleNamespace(status=403, reason="x"), "Forbidden")
    await jm.message_modifie(bot, _message("a"), _message("b"))


async def test_edits_journalise_meme_dans_une_guild_ignoree(monkeypatch):
    """L'appel est posé AVANT le filtre `ignored_guilds` de la perception."""
    from bot.discord.events import edits

    appels = []

    async def faux(bot, before, after):
        appels.append(after.content)

    monkeypatch.setattr(jm, "message_modifie", faux)
    faux_bot = SimpleNamespace(user=SimpleNamespace(id=999),
                               config=SimpleNamespace(discord=SimpleNamespace(ignored_guilds={COMMU})))
    handlers = {}
    faux_bot.event = lambda f: handlers.setdefault(f.__name__, f)
    edits.register(faux_bot)
    await handlers["on_message_edit"](_message("a"), _message("b"))
    assert appels == ["b"]
```
Le module lit `author.name` (jamais `str(author)`) : c'est ce que vérifie `valeurs["Auteur"]`.

- [ ] **Step 2: Lancer — attendu FAIL (import)**

Run: `python3 -m pytest tests/discord/test_journal_moderation.py -q -n 0`

- [ ] **Step 3: Config**

`bot/config.py`, après `SalonsTemporairesConfig` :
```python
@dataclass
class JournalModerationConfig:
    """Embeds « message supprimé / modifié, salon vocal créé / supprimé ».

    `guild_ids` : les serveurs OBSERVÉS (pas celui du salon de logs). Sans cette
    liste, Wally journaliserait les suppressions de tous les serveurs où il est.
    `salon_id` à None → désactivé.
    """
    salon_id: int | None = None
    guild_ids: list[int] = field(default_factory=list)
```
Champ `journal_moderation: JournalModerationConfig = field(default_factory=JournalModerationConfig)` dans `DiscordConfig` ; `journal_raw = discord_raw.pop("journal_moderation", None) or {}` et `journal_moderation=JournalModerationConfig(**journal_raw),` dans `Config.load`.
YAML (`config.yaml` + `config.example.yaml`) :
```yaml
  journal_moderation:
    salon_id: null            # allumé à la coupure (1416714887849185340)
    guild_ids: []             # à la coupure : [875421531415666698]
```

- [ ] **Step 4: Module**

`bot/discord/journal_moderation.py` :
```python
"""Journal de modération — repris du bot Node `wally-discord`.

Un embed par geste dans le salon de logs : message supprimé, message modifié,
salon vocal temporaire créé ou supprimé. C'est un outil de MODÉRATION, pas de
la perception : il couvre aussi les messages de bots et les serveurs que la
perception de Wally ignore (`ignored_guilds`).

Les `@` sont neutralisés ET les mentions coupées : un message supprimé qui
contenait `@everyone` ne doit pas notifier le serveur une seconde fois.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_COULEUR_MESSAGE = 0xE67E22
_COULEUR_VOCAL = 0x3498DB
_MAX_CHAMP = 1024          # limite Discord d'une valeur de champ


def _echapper(texte: str) -> str:
    return texte.replace("@", "@​")


async def _publier(bot: "WallyDiscord", guild_id: int | None, *, titre: str, description: str,
                   couleur: int, champs: list[tuple[str, str, bool]], pied: str | None = None) -> None:
    cfg = bot.config.discord.journal_moderation
    if cfg.salon_id is None or guild_id not in cfg.guild_ids:
        return
    salon = bot.get_channel(cfg.salon_id)
    if salon is None:
        logger.warning("journal de modération : salon {c} introuvable", c=cfg.salon_id)
        return
    embed = discord.Embed(description=description, colour=couleur, timestamp=discord.utils.utcnow())
    embed.set_author(name=titre)
    for nom, valeur, en_ligne in champs:
        embed.add_field(name=nom, value=(valeur or "[vide]")[:_MAX_CHAMP], inline=en_ligne)
    if pied:
        embed.set_footer(text=pied)
    try:
        await salon.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:  # noqa: BLE001 — un journal ne casse pas ce qu'il observe
        logger.warning("journal de modération : envoi impossible dans {c} : {e!r}", c=cfg.salon_id, e=e)


async def message_supprime(bot: "WallyDiscord", payload: Any) -> None:
    try:
        msg = payload.cached_message
        salon = bot.get_channel(payload.channel_id)
        nom_salon = getattr(salon, "name", "inconnu")
        auteur = msg.author.name if msg is not None else "inconnu"
        contenu = _echapper(msg.content) if msg is not None and msg.content.strip() else "[contenu non disponible]"
        champs = [("Auteur", auteur, True), ("Salon", f"#{nom_salon}", True),
                  ("ID Message", str(payload.message_id), True), ("Contenu", contenu, False)]
        pieces = list(msg.attachments) if msg is not None else []
        if pieces:
            champs.append((f"Pièces jointes ({len(pieces)})",
                           "\n".join(p.filename or p.url for p in pieces), False))
        await _publier(bot, payload.guild_id, titre="🗑️ Message supprimé",
                       description=f"Message supprimé dans <#{payload.channel_id}>",
                       couleur=_COULEUR_MESSAGE, champs=champs, pied=f"Auteur: {auteur}")
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : suppression non journalisée : {e!r}", e=e)


async def message_modifie(bot: "WallyDiscord", before: Any, after: Any) -> None:
    try:
        if after.author.bot:
            return
        avant, apres = before.content or "", after.content or ""
        if avant == apres:
            return          # embed de lien, épinglage : le texte n'a pas bougé
        auteur = after.author.name
        guild_id = after.guild.id if after.guild is not None else None
        await _publier(bot, guild_id, titre="✏️ Message modifié",
                       description=f"Message modifié dans <#{after.channel.id}>",
                       couleur=_COULEUR_MESSAGE, pied=f"Auteur: {auteur}",
                       champs=[("Auteur", auteur, True), ("Salon", f"#{after.channel.name}", True),
                               ("ID Message", str(after.id), True),
                               ("Avant", _echapper(avant), False), ("Après", _echapper(apres), False)])
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : modification non journalisée : {e!r}", e=e)


async def vocal_cree(bot: "WallyDiscord", member: Any, salon: Any) -> None:
    await _publier(bot, salon.guild.id, titre="🔊 Canal vocal créé",
                   description=f"Canal **{salon.name}** créé", couleur=_COULEUR_VOCAL,
                   champs=[("Utilisateur", member.name, True), ("Canal", salon.name, True),
                           ("ID", str(salon.id), True)])


async def vocal_supprime(bot: "WallyDiscord", salon: Any) -> None:
    await _publier(bot, salon.guild.id, titre="🔇 Canal vocal supprimé",
                   description=f"Canal **{salon.name}** supprimé (vide)", couleur=_COULEUR_VOCAL,
                   champs=[("Canal", salon.name, True), ("ID", str(salon.id), True)])
```

- [ ] **Step 5: Branchements**

`bot/discord/events/moderation.py` :
```python
# bot/discord/events/moderation.py
"""Suppressions de messages → journal de modération.

`on_raw_message_delete` et non `on_message_delete` : le second ne voit que les
messages en cache, et une suppression de vieux message passerait inaperçue.
Le contenu n'est connu que si le message était en cache (`cached_message`).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bot.discord import journal_moderation

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent) -> None:
        await journal_moderation.message_supprime(bot, payload)
```
`bot/discord/events/__init__.py` : importer `moderation` et appeler `moderation.register(bot)` dans `register_events`.

`bot/discord/events/edits.py` (relire le fichier avant) : première ligne du `try:` de `on_message_edit`, avant `if after.author.bot:` :
```python
            # Modération d'abord : elle couvre les serveurs que la perception
            # ignore, et le filtre `ignored_guilds` ci-dessous la couperait.
            from bot.discord import journal_moderation
            await journal_moderation.message_modifie(bot, before, after)
```
(L'import local permet au test de substituer `journal_moderation.message_modifie`.)

`bot/discord/salons_temporaires.py` : dans `_creer`, après le `logger.info(... créé ...)` :
```python
    from bot.discord.journal_moderation import vocal_cree
    await vocal_cree(bot, member, salon)
```
Dans `_supprimer_si_gere`, après le `logger.info(... supprimé ...)` :
```python
    from bot.discord.journal_moderation import vocal_supprime
    await vocal_supprime(bot, salon)
```
Et dans `tests/discord/test_salons_temporaires.py`, `_bot()` doit porter `journal_moderation=SimpleNamespace(salon_id=None, guild_ids=[])` dans `discord`, et `membre` un attribut `name`.

- [ ] **Step 6: Lancer — attendu PASS**

Run: `python3 -m pytest tests/discord/ tests/test_config_sans_bouton_mort.py -q -n 0`

- [ ] **Step 7: Vérifications complètes, commit, push, rebuild**

```bash
git add bot/config.py config.yaml config.example.yaml bot/discord/journal_moderation.py \
  bot/discord/events/moderation.py bot/discord/events/__init__.py bot/discord/events/edits.py \
  bot/discord/salons_temporaires.py tests/discord/test_journal_moderation.py tests/discord/test_salons_temporaires.py
git commit -m "feat(discord): journal de modération repris de wally-discord (désactivé)"
```
Vérifications complètes (Global Constraints), push + rebuild ; prod : boot normal, aucun `journal de modération` ni `Traceback` dans les logs.

**Fin de phase — attendre l'accord de l'owner.**

---

### Task 3: Salon de statut du stream (livré désactivé)

**Files:**
- Modify: `bot/config.py`, `config.yaml`, `config.example.yaml`
- Create: `bot/discord/statut_stream.py`
- Modify: `bot/main.py` (~l.461-467, `StreamWatcher(... on_poll=...)`)
- Test: `tests/discord/test_statut_stream.py`

**Interfaces:**
- Consumes: `bot.discord.handlers._fire(coro) -> asyncio.Task`
- Produces: `StatutStreamConfig(salon_id: int | None, nom_live: str, nom_hors_live: str)` à `config.discord.statut_stream`
- Produces: `sur_releve(bot, statut: dict) -> None` (synchrone ; planifie le renommage)

- [ ] **Step 1: Tests (échouent)**

`tests/discord/test_statut_stream.py` :
```python
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.discord import statut_stream as ss


def _bot(nom_actuel, *, salon_id=10, pret=True):
    salon = SimpleNamespace(id=10, name=nom_actuel, edit=AsyncMock())
    cfg = SimpleNamespace(salon_id=salon_id, nom_live="🟢live", nom_hors_live="🔴off")
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(statut_stream=cfg)))
    bot.get_channel = lambda cid: salon if cid == 10 else None
    bot.is_ready = lambda: pret
    return bot, salon


async def _laisser_tourner():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def test_nom_deja_bon_aucun_appel():
    bot, salon = _bot("🔴off")
    ss.sur_releve(bot, {"live": False})
    await _laisser_tourner()
    salon.edit.assert_not_awaited()


async def test_bascule_live_renomme():
    bot, salon = _bot("🔴off")
    ss.sur_releve(bot, {"live": True})
    await _laisser_tourner()
    salon.edit.assert_awaited_once()
    assert salon.edit.await_args.kwargs["name"] == "🟢live"


async def test_desactive_ou_discord_pas_pret():
    for bot, salon in (_bot("🔴off", salon_id=None), _bot("🔴off", pret=False)):
        ss.sur_releve(bot, {"live": True})
        await _laisser_tourner()
        salon.edit.assert_not_awaited()


async def test_echec_du_renommage_ne_leve_pas():
    bot, salon = _bot("🔴off")
    salon.edit.side_effect = RuntimeError("429")
    ss.sur_releve(bot, {"live": True})
    await _laisser_tourner()
```

- [ ] **Step 2: Lancer — attendu FAIL (import)**

Run: `python3 -m pytest tests/discord/test_statut_stream.py -q -n 0`

- [ ] **Step 3: Config**

`bot/config.py` :
```python
@dataclass
class StatutStreamConfig:
    """Salon renommé selon que le live est en cours — repris de `wally-discord`.

    `salon_id` à None → désactivé. Les noms sont ceux du salon texte existant,
    en caractères gras Unicode : Discord ne les réécrit pas.
    """
    salon_id: int | None = None
    nom_live: str = "🟢𝗲𝗻-𝘀𝘁𝗿𝗲𝗮𝗺"
    nom_hors_live: str = "🔴𝗵𝗼𝗿𝘀-𝘀𝘁𝗿𝗲𝗮𝗺"
```
Champ `statut_stream: StatutStreamConfig = field(default_factory=StatutStreamConfig)` dans `DiscordConfig` ; `statut_raw = discord_raw.pop("statut_stream", None) or {}` et `statut_stream=StatutStreamConfig(**statut_raw),` dans `Config.load`.
YAML :
```yaml
  statut_stream:
    salon_id: null            # allumé à la coupure (875443145813417984)
    nom_live: "🟢𝗲𝗻-𝘀𝘁𝗿𝗲𝗮𝗺"
    nom_hors_live: "🔴𝗵𝗼𝗿𝘀-𝘀𝘁𝗿𝗲𝗮𝗺"
```

- [ ] **Step 4: Module**

`bot/discord/statut_stream.py` :
```python
"""Le salon qui dit si le live est en cours — repris du bot Node `wally-discord`.

Branché sur `on_poll` du `StreamWatcher` (un relevé par minute), et non sur
`on_transition` : le premier relevé y est volontairement muet, alors que le
salon doit être juste dès le démarrage. On compare le nom avant de renommer :
aucun appel à Discord tant que rien ne bascule — ce qui compte, Discord ne
tolérant que deux renommages par salon toutes les dix minutes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def sur_releve(bot: "WallyDiscord", statut: dict) -> None:
    cfg = bot.config.discord.statut_stream
    if cfg.salon_id is None:
        return
    if not bot.is_ready():
        return  # le watcher relève avant la connexion Discord ; retenté dans 60 s
    salon = bot.get_channel(cfg.salon_id)
    if salon is None:
        logger.warning("statut du stream : salon {c} introuvable", c=cfg.salon_id)
        return
    voulu = cfg.nom_live if statut.get("live") else cfg.nom_hors_live
    if salon.name == voulu:
        return
    from bot.discord.handlers import _fire
    _fire(_renommer(salon, voulu))


async def _renommer(salon: Any, nom: str) -> None:
    try:
        await salon.edit(name=nom, reason="Statut du stream")
        logger.info("statut du stream : salon renommé « {n} »", n=nom)
    except Exception as e:  # noqa: BLE001 — le relevé suivant retente
        logger.warning("statut du stream : renommage impossible : {e!r}", e=e)
```

- [ ] **Step 5: Branchement dans `bot/main.py`**

Relire `bot/main.py` l.440-470. Juste avant `stream_watcher = StreamWatcher(` :
```python
        def _releve_du_stream(status: dict) -> None:
            """Chaque relevé : l'état Twitch du bot, puis le salon de statut Discord."""
            twitch_bot._stream_info = status
            statut_stream.sur_releve(discord_bot, status)
```
Remplacer `on_poll=lambda status: setattr(twitch_bot, "_stream_info", status),` par `on_poll=_releve_du_stream,` et ajouter en tête de fichier, avec les autres imports `bot.discord` : `from bot.discord import statut_stream`.

- [ ] **Step 6: Lancer — attendu PASS**

Run: `python3 -m pytest tests/discord/test_statut_stream.py tests/test_config_sans_bouton_mort.py -q -n 0`

- [ ] **Step 7: Vérifications complètes, commit, push, rebuild**

```bash
git add bot/config.py config.yaml config.example.yaml bot/discord/statut_stream.py bot/main.py \
  tests/discord/test_statut_stream.py
git commit -m "feat(discord): salon de statut du stream repris de wally-discord (désactivé)"
```
Prod : boot normal, `grep -i "statut du stream\|journal de modération\|Traceback"` → rien.

**Fin de phase — attendre l'accord de l'owner.**

---

### Task 4: Embed de bienvenue (livré désactivé)

**Files:**
- Modify: `bot/config.py`, `config.yaml`, `config.example.yaml`
- Create: `bot/discord/bienvenue.py`
- Modify: `bot/discord/events/members.py` (`on_member_join`)
- Test: `tests/discord/test_bienvenue.py`

**Interfaces:**
- Consumes: `bot.core.self_trace.note_act(summary: str) -> None`
- Produces: `BienvenueConfig(salon_id: int | None, guild_ids: list[int], messages: list[str], gifs: list[str])` à `config.discord.bienvenue`
- Produces: `async accueillir(bot, member) -> None` — ne lève jamais

- [ ] **Step 1: Tests (échouent)**

`tests/discord/test_bienvenue.py` :
```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from bot.discord import bienvenue as bv

COMMU = 9


def _bot(guild_ids=(COMMU,), salon_id=20):
    salon = SimpleNamespace(id=20, name="discussions", send=AsyncMock())
    cfg = SimpleNamespace(salon_id=salon_id, guild_ids=list(guild_ids),
                          messages=["Bienvenue !"], gifs=["https://g/1.gif"])
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(bienvenue=cfg)))
    bot.get_channel = lambda cid: salon if cid == 20 else None
    return bot, salon


def _membre(bot_=False, guild=COMMU):
    return SimpleNamespace(bot=bot_, name="alice", display_avatar=SimpleNamespace(url="a"),
                           guild=SimpleNamespace(id=guild, system_channel=None))


async def test_embed_poste_et_acte_consigne(monkeypatch):
    bot, salon = _bot()
    monkeypatch.setattr(bv, "_recuperer_fact", AsyncMock(return_value=("A fact.", "Un fait.")))
    actes = []
    monkeypatch.setattr(bv, "note_act", actes.append)
    await bv.accueillir(bot, _membre())
    embed = salon.send.await_args.kwargs["embed"]
    assert embed.author.name == "BIENVENUE A alice"
    assert embed.title == "Bienvenue !"
    assert embed.image.url == "https://g/1.gif"
    assert [f.value for f in embed.fields] == ["Un fait.", "A fact."]
    assert actes and "alice" in actes[0]


async def test_guild_hors_liste_ou_bot_ignores(monkeypatch):
    monkeypatch.setattr(bv, "_recuperer_fact", AsyncMock(return_value=("x", "y")))
    for bot_, guild in ((False, 123), (True, COMMU)):
        bot, salon = _bot()
        await bv.accueillir(bot, _membre(bot_=bot_, guild=guild))
        salon.send.assert_not_awaited()


async def test_replis_si_les_api_tombent():
    def panne(request):
        raise httpx.ConnectTimeout("x")
    async with httpx.AsyncClient(transport=httpx.MockTransport(panne)) as client:
        assert await bv._recuperer_fact(client) == (bv.FACT_INDISPONIBLE, bv.TRADUCTION_INDISPONIBLE)


async def test_traduction_seule_en_panne():
    def reponse(request):
        if "uselessfacts" in str(request.url):
            return httpx.Response(200, json={"text": "Cats sleep."})
        return httpx.Response(500)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reponse)) as client:
        assert await bv._recuperer_fact(client) == ("Cats sleep.", bv.TRADUCTION_INDISPONIBLE)
```

- [ ] **Step 2: Lancer — attendu FAIL (import)**

Run: `python3 -m pytest tests/discord/test_bienvenue.py -q -n 0`

- [ ] **Step 3: Config**

`bot/config.py` :
```python
@dataclass
class BienvenueConfig:
    """Embed d'accueil d'un nouveau membre — repris de `wally-discord`.

    `guild_ids` vide → désactivé. `salon_id` à None → salon système du serveur.
    """
    salon_id: int | None = None
    guild_ids: list[int] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    gifs: list[str] = field(default_factory=list)
```
Champ `bienvenue: BienvenueConfig = field(default_factory=BienvenueConfig)` dans `DiscordConfig` ; `bienvenue_raw = discord_raw.pop("bienvenue", None) or {}` et `bienvenue=BienvenueConfig(**bienvenue_raw),` dans `Config.load`.
YAML :
```yaml
  bienvenue:
    salon_id: null            # à la coupure : 875421532351000627
    guild_ids: []             # à la coupure : [875421531415666698]
    messages: []              # à la coupure : messages du Node
    gifs: []                  # à la coupure : gifs du Node
```

- [ ] **Step 4: Module**

`bot/discord/bienvenue.py` :
```python
"""Embed de bienvenue — repris du bot Node `wally-discord`.

Un message tiré au sort, un GIF, et une « fact » inutile traduite en français.
La cognition perçoit AUSSI l'arrivée (`_member_join_context`) : l'embed est
donc consigné dans `self_trace`, sans quoi Wally accueillerait une seconde
fois en croyant être le premier.

La fact part dans un embed, jamais dans un prompt : pas de `wrap_untrusted`.
Le jour où elle entre dans un prompt, elle y passe.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import discord
import httpx
from loguru import logger

from bot.core.self_trace import note_act

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_FACT_URL = "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en"
_TRADUCTION_URL = "https://api.mymemory.translated.net/get"
_TIMEOUT = 5.0
FACT_INDISPONIBLE = "Impossible de récupérer une fact."
TRADUCTION_INDISPONIBLE = "Traduction indisponible."


async def _recuperer_fact(client: httpx.AsyncClient) -> tuple[str, str]:
    try:
        r = await client.get(_FACT_URL, timeout=_TIMEOUT)
        r.raise_for_status()
        fact = r.json()["text"]
    except Exception as e:  # noqa: BLE001 — repli affiché dans l'embed
        logger.warning("bienvenue : fact indisponible : {e!r}", e=e)
        return FACT_INDISPONIBLE, TRADUCTION_INDISPONIBLE
    try:
        r = await client.get(_TRADUCTION_URL, params={"q": fact, "langpair": "en|fr"}, timeout=_TIMEOUT)
        r.raise_for_status()
        return fact, r.json()["responseData"]["translatedText"]
    except Exception as e:  # noqa: BLE001 — repli affiché dans l'embed
        logger.warning("bienvenue : traduction indisponible : {e!r}", e=e)
        return fact, TRADUCTION_INDISPONIBLE


async def accueillir(bot: "WallyDiscord", member: Any) -> None:
    """Poste l'embed de bienvenue. Ne lève jamais."""
    cfg = bot.config.discord.bienvenue
    if member.bot or member.guild.id not in cfg.guild_ids:
        return
    try:
        salon = bot.get_channel(cfg.salon_id) if cfg.salon_id is not None else None
        salon = salon or member.guild.system_channel
        if salon is None:
            logger.warning("bienvenue : aucun salon d'accueil pour le serveur {g}", g=member.guild.id)
            return
        async with httpx.AsyncClient() as client:
            fact, traduction = await _recuperer_fact(client)
        embed = discord.Embed(title=random.choice(cfg.messages) if cfg.messages else "Bienvenue !",
                              colour=0x1AD5B6)
        embed.set_author(name=f"BIENVENUE A {member.name}", icon_url=member.display_avatar.url)
        embed.add_field(name="francais :", value=traduction, inline=False)
        embed.add_field(name="original :", value=fact, inline=False)
        embed.set_footer(text="Le Purgatoire")
        if cfg.gifs:
            embed.set_image(url=random.choice(cfg.gifs))
        await salon.send(embed=embed)
        note_act(f"tu as posté l'embed de bienvenue de {member.name} dans #{salon.name} (Discord)")
        logger.info("bienvenue : embed posté pour {m}", m=member.name)
    except Exception as e:  # noqa: BLE001 — un accueil raté ne fait pas tomber le bot
        logger.warning("bienvenue : embed non posté : {e!r}", e=e)
```

- [ ] **Step 5: Branchement dans `bot/discord/events/members.py`**

Relire le fichier. Dans `on_member_join`, remplacer le corps par :
```python
        # Perception cognitive (#A2) : un nouveau venu doit atteindre le cerveau.
        from bot.discord.handlers import _member_join_context

        # L'embed d'abord : il est consigné dans self_trace, et la cognition
        # doit le voir quand elle décide si elle accueille à son tour.
        await bienvenue.accueillir(bot, member)
        await _member_join_context(bot, member)
```
avec `from bot.discord import bienvenue` en tête du fichier.

- [ ] **Step 6: Lancer — attendu PASS**

Run: `python3 -m pytest tests/discord/ tests/test_config_sans_bouton_mort.py -q -n 0`

- [ ] **Step 7: Vérifications complètes, commit**

```bash
git add bot/config.py config.yaml config.example.yaml bot/discord/bienvenue.py \
  bot/discord/events/members.py tests/discord/test_bienvenue.py
git commit -m "feat(discord): embed de bienvenue repris de wally-discord (désactivé)"
```
Push + rebuild ; prod : boot normal, aucun `bienvenue :` ni `Traceback` dans les logs.

**Fin de phase — attendre l'accord de l'owner.**

---

### Task 5: Coupure de wally-discord et allumage

Opérations en prod, dans cet ordre strict. Aucune ne se fait avant l'accord explicite de l'owner.

**Files:**
- Modify: `config.yaml` (valeurs réelles)
- Modify: `CLAUDE.md` (dépôt) — ajouter une section « Serveur Discord communautaire » décrivant les 4 modules
- Modify: `/root/.claude/CLAUDE.md` (CT100 : 16 → 15 containers, retirer `wally-discord`)

- [ ] **Step 1: Arrêter le Node AVANT d'allumer Wally**

```bash
cd /opt/stacks/wally-discord && docker compose stop
docker ps -a --format '{{.Names}}\t{{.Status}}' | grep wally-discord   # attendu : Exited
```

- [ ] **Step 2: Valeurs dans `config.yaml`**

Générer les listes depuis la config du Node (pas de recopie à la main) :
```bash
python3 - <<'EOF'
import yaml
node = yaml.safe_load(open("/opt/stacks/wally-discord/config.yaml"))
wally = yaml.safe_load(open("/opt/stacks/wally-ai/config.yaml"))
d = wally["discord"]
d["salons_temporaires"] = {"salon_createur_id": int(node["channels"]["autoVoice"]),
                           "noms": node["channels"]["randomNames"]}
d["journal_moderation"] = {"salon_id": int(node["channels"]["logs"]),
                           "guild_ids": [875421531415666698]}
d["statut_stream"] = {"salon_id": int(node["channels"]["twitchStatus"]),
                      "nom_live": node["twitch"]["liveStatusName"],
                      "nom_hors_live": node["twitch"]["offlineStatusName"]}
d["bienvenue"] = {"salon_id": int(node["channels"]["welcome"]), "guild_ids": [875421531415666698],
                  "messages": node["welcome"]["messages"], "gifs": node["welcome"]["gifs"]}
yaml.safe_dump(wally, open("/opt/stacks/wally-ai/config.yaml", "w"), allow_unicode=True, sort_keys=False)
EOF
git -C /opt/stacks/wally-ai diff --stat config.yaml
```
⚠️ Relire le diff : `yaml.safe_dump` réécrit tout le fichier ; seule la section `discord` doit changer de fond (c'est déjà ce que fait `config.save()`).

- [ ] **Step 3: Reprendre le salon temporaire en cours**

```bash
python3 - <<'EOF'
import json, sqlite3, time
data = json.load(open("/opt/stacks/wally-discord/data/voice_channels.json"))
con = sqlite3.connect("/opt/stacks/wally-ai/data/wally.db")
for c in data["voice_channels"]:
    con.execute("INSERT OR IGNORE INTO salons_vocaux_temporaires VALUES (?, ?, ?)",
                (c["id"], c["guild_id"], c["created_at"] / 1000))
con.commit(); print(con.execute("SELECT * FROM salons_vocaux_temporaires").fetchall())
EOF
```
(La table existe depuis le rebuild de la Task 1.)

- [ ] **Step 4: Rebuild + push**

```bash
cd /opt/stacks/wally-ai
python3 -m pytest tests/ -q && python3 scripts/lint_types.py && python3 scripts/lint_silences.py \
  && python3 scripts/lint_ruff.py && python3 scripts/lint_logs.py && python3 scripts/lint_mort.py
git add config.yaml && git commit -m "feat(discord): wally-discord éteint, ses quatre fonctions allumées dans Wally"
GIT_HASH=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) docker compose up -d --build wally
git push public feat/site-redesign-arcade:main
```

- [ ] **Step 5: Vérifier en prod (chaque point VU, pas supposé)**

- `docker compose logs --since 3m wally | grep -iE "salons temporaires|statut du stream|Traceback"` : ménage au boot logué, pas d'erreur.
- Nom du salon statut conforme au live :
  `curl -s -H "Authorization: Bot $TOKEN" https://discord.com/api/v10/channels/875443145813417984 | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])'` (token lu dans `.env` au moment, jamais affiché).
- Demander à l'owner : entrer puis sortir du salon créateur → salon créé, déplacé, supprimé ; deux embeds vocaux dans le salon de logs.
- Demander à l'owner : modifier puis supprimer un message test → deux embeds.
- Bienvenue : attendre une vraie arrivée (log `bienvenue : embed posté`) ; à défaut, le signaler comme non vu en prod.
- Slash commands globales toujours présentes (15) : `GET /applications/1114896051321708544/commands`.

- [ ] **Step 6: Archiver le Node et mettre la doc à jour**

```bash
cd /opt/stacks/wally-discord && docker compose down
mkdir -p /opt/stacks/_archives && mv /opt/stacks/wally-discord /opt/stacks/_archives/wally-discord-2026-09-15
```
- `CLAUDE.md` du dépôt : section « Serveur Discord communautaire » (les 4 modules, leur branchement, le piège `on_voice_state_update`, le salon journal `1267122210166935563` à ne jamais purger).
- `/root/.claude/CLAUDE.md` : retirer `wally-discord` de la liste, 16 → 15 containers.
- Mémoire : un fichier projet `project_fusion_wally_discord.md` + ligne dans `MEMORY.md`.
- Commit + push de `CLAUDE.md`.
