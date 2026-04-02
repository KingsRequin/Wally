# Remove Instances + GHCR Update Polling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supprimer le système multi-instances de Wally et le remplacer par un `UpdateChecker` qui poll GHCR pour détecter automatiquement les mises à jour disponibles.

**Architecture:** `UpdateChecker` est un nouveau service (`bot/core/update_checker.py`) injecté dans `AppState`. Il compare le digest de l'image courante (via `docker inspect`) avec le digest distant (API GHCR publique). `admin.py` lit `state.update_checker.update_available` au lieu du flag fichier. Le `self-update` fait désormais `pull` avant `recreate`. Tout le code instance (provisioner, routes `/instances/*`, onglet JS) est supprimé.

**Tech Stack:** Python asyncio, httpx (déjà dans le projet), subprocess docker, FastAPI, vanilla JS.

---

## Fichiers concernés

| Fichier | Action |
|---|---|
| `bot/core/update_checker.py` | Créer — service de détection de mise à jour |
| `bot/core/provisioner.py` | Supprimer |
| `bot/config.py` | Modifier — ajouter `update_image: str = ""` dans `BotConfig` |
| `bot/dashboard/state.py` | Modifier — ajouter `update_checker` |
| `bot/main.py` | Modifier — wiring UpdateChecker |
| `bot/dashboard/routes/admin.py` | Modifier — supprimer `is_main`, adapter `update_available`, modifier `self_update` |
| `bot/dashboard/routes/setup.py` | Modifier — supprimer toutes routes `/instances/*` et helpers associés |
| `bot/dashboard/static/app.js` | Modifier — supprimer onglet Instances + simplifier Prompts |
| `tests/test_update_checker.py` | Créer |
| `tests/test_setup_provisioner.py` | Supprimer |
| `README.md` | Modifier — mettre à jour sections Dashboard, Docker, Configuration |

---

## Task 1 : UpdateChecker — TDD

**Files:**
- Create: `tests/test_update_checker.py`
- Create: `bot/core/update_checker.py`

- [ ] **Step 1 : Écrire les tests**

Créer `tests/test_update_checker.py` :

```python
# tests/test_update_checker.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── _running_digest ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_running_digest_returns_sha_from_repo_digest():
    """Extrait le sha256 depuis le RepoDigest du container courant."""
    from bot.core.update_checker import UpdateChecker
    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ghcr.io/user/wally-ai@sha256:abc123def456\n"

    with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_result)), \
         patch("os.environ", {"HOSTNAME": "a1b2c3d4e5f6"}):
        digest = await checker._running_digest()

    assert digest == "sha256:abc123def456"


@pytest.mark.asyncio
async def test_running_digest_returns_none_for_local_image():
    """Retourne None si RepoDigests est vide (image construite localement)."""
    from bot.core.update_checker import UpdateChecker
    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "\n"

    with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_result)), \
         patch("os.environ", {"HOSTNAME": "a1b2c3d4e5f6"}):
        digest = await checker._running_digest()

    assert digest is None


@pytest.mark.asyncio
async def test_running_digest_returns_none_when_hostname_missing():
    """Retourne None si HOSTNAME n'est pas défini."""
    from bot.core.update_checker import UpdateChecker
    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")

    with patch("os.environ", {}):
        digest = await checker._running_digest()

    assert digest is None


# ── _remote_digest ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remote_digest_returns_header_on_200():
    """Retourne le Docker-Content-Digest header si la réponse est 200."""
    from bot.core.update_checker import UpdateChecker
    import httpx

    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Docker-Content-Digest": "sha256:remote999"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        digest = await checker._remote_digest()

    assert digest == "sha256:remote999"


@pytest.mark.asyncio
async def test_remote_digest_handles_401_with_token():
    """Effectue le flux token GHCR sur 401 et retourne le digest."""
    from bot.core.update_checker import UpdateChecker

    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")

    unauth_resp = MagicMock()
    unauth_resp.status_code = 401

    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json = MagicMock(return_value={"token": "mytoken"})

    auth_resp = MagicMock()
    auth_resp.status_code = 200
    auth_resp.headers = {"Docker-Content-Digest": "sha256:remote777"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[unauth_resp, token_resp, auth_resp])
        mock_client_cls.return_value = mock_client

        digest = await checker._remote_digest()

    assert digest == "sha256:remote777"


@pytest.mark.asyncio
async def test_remote_digest_returns_none_on_network_error():
    """Retourne None sans planter si la requête échoue."""
    from bot.core.update_checker import UpdateChecker

    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client_cls.return_value = mock_client

        digest = await checker._remote_digest()

    assert digest is None


# ── _check ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_sets_update_available_when_digests_differ():
    """update_available devient True quand les digests diffèrent."""
    from bot.core.update_checker import UpdateChecker

    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")
    checker._running_digest = AsyncMock(return_value="sha256:old")
    checker._remote_digest = AsyncMock(return_value="sha256:new")

    await checker._check()

    assert checker.update_available is True


@pytest.mark.asyncio
async def test_check_clears_update_available_when_digests_match():
    """update_available passe à False quand les digests sont identiques."""
    from bot.core.update_checker import UpdateChecker

    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")
    checker._update_available = True
    checker._running_digest = AsyncMock(return_value="sha256:same")
    checker._remote_digest = AsyncMock(return_value="sha256:same")

    await checker._check()

    assert checker.update_available is False


@pytest.mark.asyncio
async def test_check_skips_when_running_digest_is_none():
    """Ne change pas update_available si l'image locale n'a pas de RepoDigest."""
    from bot.core.update_checker import UpdateChecker

    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")
    checker._running_digest = AsyncMock(return_value=None)
    checker._remote_digest = AsyncMock(return_value="sha256:remote")

    await checker._check()

    assert checker.update_available is False
    checker._remote_digest.assert_not_called()


@pytest.mark.asyncio
async def test_check_does_not_crash_on_exception():
    """Une exception dans _check est catchée et loguée, pas propagée."""
    from bot.core.update_checker import UpdateChecker

    checker = UpdateChecker("ghcr.io/user/wally-ai:latest")
    checker._running_digest = AsyncMock(side_effect=RuntimeError("boom"))

    # Ne doit pas lever
    await checker._check()
```

- [ ] **Step 2 : Vérifier que les tests échouent (module inexistant)**

```bash
cd /opt/stacks/wally-ai
python3 -m pytest tests/test_update_checker.py -v 2>&1 | head -20
```

Résultat attendu : `ModuleNotFoundError: No module named 'bot.core.update_checker'`

- [ ] **Step 3 : Créer `bot/core/update_checker.py`**

```python
# bot/core/update_checker.py
from __future__ import annotations

import asyncio
import os
import subprocess

import httpx
from loguru import logger


class UpdateChecker:
    """Vérifie périodiquement si une nouvelle image est disponible sur GHCR.

    Usage :
        checker = UpdateChecker("ghcr.io/user/wally-ai:latest")
        checker.start()           # démarre la boucle asyncio
        checker.update_available  # True si mise à jour détectée
        checker.update_available = False  # reset après déclenchement
        await checker.stop()
    """

    def __init__(self, image_ref: str, check_interval_seconds: int = 3600) -> None:
        self._image_ref = image_ref
        self._interval = check_interval_seconds
        self._update_available: bool = False
        self._task: asyncio.Task | None = None

    @property
    def update_available(self) -> bool:
        return self._update_available

    @update_available.setter
    def update_available(self, value: bool) -> None:
        self._update_available = value

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("UpdateChecker started — image={} interval={}s", self._image_ref, self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await self._check()
            await asyncio.sleep(self._interval)

    async def _check(self) -> None:
        try:
            current = await self._running_digest()
            if not current:
                return  # image locale sans RepoDigest — skip
            remote = await self._remote_digest()
            if remote and current != remote:
                if not self._update_available:
                    logger.info("Update available: {} → {}", current[:19], remote[:19])
                self._update_available = True
            elif remote:
                self._update_available = False
        except Exception as exc:
            logger.warning("UpdateChecker: check failed: {}", exc)

    async def _running_digest(self) -> str | None:
        """Retourne le digest manifest de l'image courante (RepoDigests via docker inspect)."""
        container_id = os.environ.get("HOSTNAME", "")
        if not container_id:
            return None
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["/usr/bin/docker", "inspect", "--format", "{{index .RepoDigests 0}}", container_id],
                capture_output=True, text=True, timeout=5,
            )
            raw = result.stdout.strip()
            if not raw or "@" not in raw:
                return None
            return raw.split("@", 1)[1]  # sha256:abc123...
        except Exception as exc:
            logger.warning("UpdateChecker: docker inspect failed: {}", exc)
            return None

    async def _remote_digest(self) -> str | None:
        """Retourne le digest manifest de la dernière image sur GHCR (sans auth pour images publiques)."""
        ref = self._image_ref
        if ref.startswith("ghcr.io/"):
            ref = ref[8:]
        name, tag = (ref.rsplit(":", 1) if ":" in ref else (ref, "latest"))

        manifest_url = f"https://ghcr.io/v2/{name}/manifests/{tag}"
        accept = "application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.v2+json"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(manifest_url, headers={"Accept": accept})
                if r.status_code == 401:
                    token_url = f"https://ghcr.io/token?scope=repository:{name}:pull&service=ghcr.io"
                    tr = await client.get(token_url)
                    if tr.status_code != 200:
                        return None
                    token = tr.json().get("token", "")
                    r = await client.get(manifest_url, headers={"Accept": accept, "Authorization": f"Bearer {token}"})
                if r.status_code == 200:
                    return r.headers.get("Docker-Content-Digest")
        except Exception as exc:
            logger.warning("UpdateChecker: GHCR request failed: {}", exc)
        return None
```

- [ ] **Step 4 : Lancer les tests**

```bash
cd /opt/stacks/wally-ai
python3 -m pytest tests/test_update_checker.py -v
```

Résultat attendu : **10 tests PASSED**

- [ ] **Step 5 : Suite complète — vérifier aucune régression**

```bash
python3 -m pytest tests/ -x -q 2>&1 | tail -5
```

Résultat attendu : même nombre de tests qu'avant + 10 nouveaux.

- [ ] **Step 6 : Commit**

```bash
git add bot/core/update_checker.py tests/test_update_checker.py
git commit -m "feat(update): UpdateChecker — polling digest GHCR via docker inspect"
```

---

## Task 2 : Wiring — config, state, main

**Files:**
- Modify: `bot/config.py` (classe `BotConfig`, dernier champ ~ligne 34)
- Modify: `bot/dashboard/state.py` (dataclass `AppState`, ~ligne 46)
- Modify: `bot/main.py` (section lifespan/gather, ~ligne 380+)

- [ ] **Step 1 : Ajouter `update_image` dans `BotConfig`**

Dans `bot/config.py`, à la fin de la dataclass `BotConfig` (après `love_decay_lambda`), ajouter :

```python
    update_image: str = ""          # ex: "ghcr.io/user/wally-ai:latest" — vide = polling désactivé
```

- [ ] **Step 2 : Ajouter `update_checker` dans `AppState`**

Dans `bot/dashboard/state.py` :

Ajouter dans le bloc `TYPE_CHECKING` :
```python
    from bot.core.update_checker import UpdateChecker
```

Ajouter dans la dataclass `AppState`, après `graph: Optional["GraphService"] = None` :
```python
    update_checker: Optional["UpdateChecker"] = None
```

- [ ] **Step 3 : Wirer UpdateChecker dans `bot/main.py`**

Lis `bot/main.py` pour trouver la section où `AppState` est construit. Elle ressemble à :
```python
    state = AppState(
        config=config, db=db, emotion=emotion, ...
    )
```

Juste avant la construction de l'AppState, ajouter :
```python
    # ── UpdateChecker ─────────────────────────────────────────────────────────
    update_checker = None
    if config.bot.update_image:
        from bot.core.update_checker import UpdateChecker
        update_checker = UpdateChecker(config.bot.update_image)
        logger.info("UpdateChecker configured — image={}", config.bot.update_image)
    else:
        logger.info("UpdateChecker disabled — set bot.update_image in config.yaml to enable")
```

Dans la construction de l'AppState, passer `update_checker=update_checker`.

Trouver le bloc lifespan/startup du dashboard (chercher `create_dashboard_app`). Dans ce bloc, après le démarrage des autres services, ajouter :
```python
    if state.update_checker:
        state.update_checker.start()
```

Et dans le shutdown (chercher `await bot.close()` ou équivalent) :
```python
    if state.update_checker:
        await state.update_checker.stop()
```

Note : si main.py n'a pas de lifespan explicite, ajouter `update_checker.start()` juste après `state = AppState(...)` et `update_checker.stop()` dans la section cleanup en fin de `main()`.

- [ ] **Step 4 : Vérifier que le bot démarre toujours**

```bash
python3 -m pytest tests/ -x -q 2>&1 | tail -5
```

Résultat attendu : tous les tests passent.

- [ ] **Step 5 : Commit**

```bash
git add bot/config.py bot/dashboard/state.py bot/main.py
git commit -m "feat(update): wiring UpdateChecker dans config/state/main"
```

---

## Task 3 : Modifier admin.py

**Files:**
- Modify: `bot/dashboard/routes/admin.py`

Contexte : ce fichier a 3 endroits à modifier.
1. Ligne ~18 : `from bot.core.provisioner import INSTANCES_DIR` → à supprimer
2. Ligne ~39 dans `GET /config` : `"is_main": INSTANCES_DIR.exists()` → à supprimer
3. Ligne ~528 dans `GET /bot/status` : `"update_available": Path("/app/data/update_available").exists()` → à remplacer
4. Lignes ~751-773 : `POST /api/admin/self-update` → ajouter le pull avant recreate

- [ ] **Step 1 : Écrire les tests**

Ajouter dans `tests/test_dashboard_routes.py` (ou créer `tests/test_admin_update.py`) :

```python
# tests/test_admin_update.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from tests.test_dashboard_routes import _make_state


def _make_state_with_checker(update_available: bool):
    state = _make_state()
    checker = MagicMock()
    checker.update_available = update_available
    state.update_checker = checker
    return state


@pytest.fixture
async def client_with_update():
    state = _make_state_with_checker(update_available=True)
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def client_no_update():
    state = _make_state_with_checker(update_available=False)
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def client_no_checker():
    state = _make_state()
    state.update_checker = None
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_bot_status_update_available_true(client_with_update):
    r = await client_with_update.get(
        "/api/admin/bot/status",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert r.json()["update_available"] is True


@pytest.mark.asyncio
async def test_bot_status_update_available_false(client_no_update):
    r = await client_no_update.get(
        "/api/admin/bot/status",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert r.json()["update_available"] is False


@pytest.mark.asyncio
async def test_bot_status_no_checker_returns_false(client_no_checker):
    r = await client_no_checker.get(
        "/api/admin/bot/status",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert r.json()["update_available"] is False


@pytest.mark.asyncio
async def test_config_has_no_is_main_field(client_no_checker):
    """Le champ is_main ne doit plus exister dans GET /config."""
    r = await client_no_checker.get(
        "/api/admin/config",
        headers={"Authorization": "Bearer testtoken"},
    )
    assert r.status_code == 200
    assert "is_main" not in r.json()
```

- [ ] **Step 2 : Vérifier que les tests échouent (état actuel)**

```bash
cd /opt/stacks/wally-ai
python3 -m pytest tests/test_admin_update.py -v 2>&1 | head -30
```

Résultat attendu : `FAILED` — `is_main` est présent, `update_available` lit le flag fichier.

- [ ] **Step 3 : Modifier `admin.py`**

**3a. Supprimer l'import INSTANCES_DIR** (ligne ~18) :
```python
# Supprimer cette ligne :
from bot.core.provisioner import INSTANCES_DIR
```

**3b. Supprimer `is_main` dans `GET /config`** (ligne ~39) :
```python
# Supprimer cette ligne dans le return de get_config() :
        "is_main": INSTANCES_DIR.exists(),
```

**3c. Remplacer `update_available` dans `GET /bot/status`** (ligne ~528) :

Remplacer :
```python
        "update_available": Path("/app/data/update_available").exists(),
```
Par :
```python
        "update_available": (
            state.update_checker.update_available
            if state.update_checker is not None
            else False
        ),
```

**3d. Modifier `POST /api/admin/self-update`** (lignes ~751-773) :

Remplacer le corps de la fonction `self_update` par :
```python
@router.post("/self-update")
async def self_update(request: Request) -> dict:
    """Déclenche la mise à jour de ce container : pull puis recreate via Docker Compose.

    Requiert COMPOSE_FILE dans l'environnement et /var/run/docker.sock monté.
    Lance la commande en arrière-plan pour que la réponse HTTP parte avant l'arrêt du container.
    """
    compose_file = os.getenv("COMPOSE_FILE", "")
    if not compose_file:
        raise HTTPException(status_code=503, detail="COMPOSE_FILE non configuré")
    if not Path("/var/run/docker.sock").exists():
        raise HTTPException(status_code=503, detail="Docker socket non disponible")

    state = request.app.state.wally
    if state.update_checker is not None:
        state.update_checker.update_available = False  # reset optimiste

    cmd = (
        f"/usr/bin/docker compose -f {compose_file} pull && "
        f"/usr/bin/docker compose -f {compose_file} up -d --force-recreate"
    )
    subprocess.Popen(
        ["sh", "-c", cmd],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("Self-update triggered (pull + recreate) for COMPOSE_FILE={}", compose_file)
    return {"ok": True}
```

- [ ] **Step 4 : Lancer les tests**

```bash
python3 -m pytest tests/test_admin_update.py -v
```

Résultat attendu : **4 tests PASSED**

- [ ] **Step 5 : Suite complète**

```bash
python3 -m pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 6 : Commit**

```bash
git add bot/dashboard/routes/admin.py tests/test_admin_update.py
git commit -m "feat(update): admin.py — supprimer is_main, update_available via UpdateChecker, self-update pull+recreate"
```

---

## Task 4 : Nettoyer setup.py

**Files:**
- Modify: `bot/dashboard/routes/setup.py`

Supprimer tout le code instance (routes, helpers) et simplifier `submit_wizard`.

- [ ] **Step 1 : Supprimer les imports inutiles**

En haut de `setup.py`, supprimer :
- La ligne : `from bot.core.provisioner import INSTANCES_DIR, provision_instance`
- Les imports `asyncio`, `json`, `subprocess` (utilisés uniquement par les routes instances)

Conserver tous les autres imports.

- [ ] **Step 2 : Supprimer les helpers et routes instances**

Supprimer les éléments suivants dans `setup.py` (dans l'ordre d'apparition) :

**Helpers à supprimer** (lignes ~108-114) :
```python
_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")

def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Slug invalide.")
```

Note : `_validate_slug` sera réintroduit dans `submit_wizard` en inline si nécessaire, ou le wizard sera simplifié pour ne plus en avoir besoin (voir step 3).

**Routes admin instances à supprimer** (environ lignes 117–350) :
- `GET /instances` — `list_instances`
- `POST /instances/{slug}/stop` — `stop_instance`
- `POST /instances/{slug}/start` — `start_instance`
- `GET /persona-template/{filename}` — `persona_template`
- Bloc `_PERSONA_FILES` + `GET /instances/{slug}/persona` — `get_instance_persona`
- `POST /instances/{slug}/persona/{filename}` — `save_instance_persona`
- `_update_config_path`, `_load_update_config`, `_make_update_view`
- `POST /instances/{slug}/notify-update` — `notify_instance_update`
- `POST /notify-all-updates` — `notify_all_instances_update`
- `POST /instances/{slug}/update` — `update_instance_now`
- `POST /instances/{slug}/publish-update` — `publish_instance_update`
- `DELETE /instances/{slug}/publish-update` — `cancel_instance_update`
- `POST /instances/publish-all-updates` — `publish_all_instance_updates`
- `POST /webhook/update` — `webhook_update`

Garder uniquement dans `admin_router` : `POST /invite`, `GET /invites`, `DELETE /invite/{token}`.

- [ ] **Step 3 : Simplifier `submit_wizard`**

La fonction `submit_wizard` appelle `provision_instance` qui est supprimé. Remplacer le corps par :

```python
@wizard_router.post("/{token}/submit")
async def submit_wizard(request: Request, token: str, body: dict) -> dict:
    _check_preview_auth(request, token)
    db = request.app.state.wally.db
    row = await _get_valid_invite(token, db)
    session = await db.get_setup_session(token)
    is_dry_run = row["is_preview"] and body.get("dry_run", True)
    slug = session.get("bot_name", "bot").lower().replace(" ", "_")
    if not is_dry_run:
        await db.use_setup_invite(token, slug=slug, port=0)
    logger.info("Setup wizard completed for slug={} dry_run={}", slug, is_dry_run)
    return {"status": "ok", "slug": slug, "dry_run": is_dry_run}
```

Supprimer également `_PERSONA_DIR` et `_validate_slug` si plus référencés.

- [ ] **Step 4 : Vérifier que les imports cassés sont résolus**

```bash
cd /opt/stacks/wally-ai
python3 -c "from bot.dashboard.routes.setup import admin_router, wizard_router; print('OK')"
```

Résultat attendu : `OK`

- [ ] **Step 5 : Lancer les tests setup existants**

```bash
python3 -m pytest tests/test_setup_routes.py -v
```

Résultat attendu : les tests d'invites passent. Les tests appelant `/instances/` échoueront avec 404 — c'est attendu si de tels tests existent, sinon tout passe.

- [ ] **Step 6 : Suite complète**

```bash
python3 -m pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 7 : Commit**

```bash
git add bot/dashboard/routes/setup.py
git commit -m "feat(cleanup): setup.py — supprimer routes instances, simplifier submit_wizard"
```

---

## Task 5 : Nettoyer app.js — supprimer instances, simplifier Prompts

**Files:**
- Modify: `bot/dashboard/static/app.js`

C'est une chirurgie sur 8045 lignes. Procède par suppression de blocs identifiés par leur commentaire/nom de fonction.

- [ ] **Step 1 : Supprimer la logique `is_main` dans l'onglet Système (lignes ~4870-4879)**

Trouver dans `renderSystemeTab()` le bloc :
```javascript
    // Afficher le bouton Instances uniquement sur le bot principal
    apiFetch('/api/admin/bot/status').then(async function(r) {
      if (r && r.ok) {
        var data = await r.json();
        if (data.is_main) {
          const btn = el.querySelector('[data-subtab="instances"]');
          if (btn) btn.style.display = '';
        }
      }
    });
```
Supprimer ce bloc entier.

- [ ] **Step 2 : Supprimer le bouton et conteneur "Instances" du sous-nav Système**

Dans le même `renderSystemeTab()`, trouver et supprimer :
```javascript
        <button class="mem-subnav-pill" data-subtab="instances" onclick="switchSystemeSubTab('instances')" style="display:none">Instances</button>
```
Et supprimer :
```javascript
      <div class="mem-subnav-content" id="systeme-sub-instances"></div>
```

- [ ] **Step 3 : Supprimer le case "instances" dans `switchSystemeSubTab`**

Trouver dans `switchSystemeSubTab` :
```javascript
  } else if (subtab === 'instances') {
    _renderSystemeInstances(panel);
  }
```
Supprimer ce bloc.

- [ ] **Step 4 : Supprimer `_renderSystemeInstances` (~ligne 5262)**

Supprimer la fonction entière :
```javascript
function _renderSystemeInstances(panel) {
  if (!panel) return;
  // Delegate to renderInstancesTab — move content
  const instEl = document.getElementById('tab-admin-instances');
  if (panel.children.length === 0) {
    renderInstancesTab();
    if (instEl && instEl.children.length > 0) {
      while (instEl.firstChild) panel.appendChild(instEl.firstChild);
    }
  } else {
    // Refresh invites and instances
    loadInvites();
    loadInstances();
  }
}
```

- [ ] **Step 5 : Supprimer le redirect legacy `admin-instances` (~ligne 342)**

Dans `showTab()`, trouver et supprimer :
```javascript
    'admin-instances': 'admin-systeme',
```

- [ ] **Step 6 : Supprimer le case `admin-instances` dans `showTab`**

Trouver et supprimer :
```javascript
    else if (tabId === 'admin-instances') _systemeSubTab = 'instances';
```
Et :
```javascript
  if (tabId === 'admin-instances') renderInstancesTab();
```

- [ ] **Step 7 : Supprimer le bloc entier "Instances tab" (~lignes 7454-7793)**

Supprimer depuis le commentaire `// ── Instances tab ──────────...` jusqu'à la fin de `instanceAction()` (inclusif). Conserver tout ce qui vient après (`// ── Prompts & Persona Management`).

Fonctions supprimées dans ce bloc :
- `_makeGlassCard`
- `renderInstancesTab`
- `loadInstances`
- `notifyAllInstancesUpdate`
- `instanceAction`

Fonctions **conservées** juste avant le bloc Prompts :
- `generateInvite`
- `copyInviteLink`
- `revokeInvite`

- [ ] **Step 8 : Simplifier `renderPromptsTab` — supprimer le fetch instances**

Dans `renderPromptsTab` (~ligne 7802), remplacer :
```javascript
  // Charger instances + config modèles en parallèle
  var [ri] = await Promise.all([
    apiFetch('/api/admin/setup/instances'),
    _loadPromptsModels(),
  ]);
  _promptsInstances = (ri && ri.ok) ? (await ri.json()).instances || [] : [];
```
Par :
```javascript
  await _loadPromptsModels();
```

- [ ] **Step 9 : Simplifier `_renderPromptsUI` — supprimer le sélecteur d'instance**

Dans `_renderPromptsUI` (~ligne 7836), trouver et supprimer :
```javascript
  // Sélecteur de bot
  var instanceOpts = '<option value="main">Bot principal</option>';
  _promptsInstances.forEach(function(inst) {
    instanceOpts += '<option value="' + inst.slug + '"' + (_promptsInstance === inst.slug ? ' selected' : '') + '>' + inst.slug + '</option>';
  });
```

Dans le template HTML de `_renderPromptsUI`, supprimer le `<select>` d'instance :
```javascript
        <select onchange="switchPromptsInstance(this.value)" style="...">
          ${instanceOpts}
        </select>
```

Supprimer aussi la condition `_promptsInstance === 'main'` sur le bouton Système — toujours afficher le bouton Système :
```javascript
        ${_promptsInstance === 'main' ? '<button class="mem-subnav-pill ...' : ''}
```
Remplacer par :
```javascript
        <button class="mem-subnav-pill ${_promptsSection==='system'?'active':''}" onclick="switchPromptsSection('system')">Système</button>
```

- [ ] **Step 10 : Simplifier `_loadPromptsData` — toujours utiliser 'main'**

Remplacer la fonction entière par :
```javascript
async function _loadPromptsData() {
  var r = await apiFetch('/api/admin/prompts');
  _promptsData = (r && r.ok) ? await r.json() : { persona: {}, system_prompts: {} };
  var files = _promptsSection === 'persona'
    ? Object.keys(_promptsData.persona)
    : Object.keys(_promptsData.system_prompts);
  if (!_promptsFile || !files.includes(_promptsFile)) {
    _promptsFile = files[0] || null;
  }
}
```

- [ ] **Step 11 : Supprimer `switchPromptsInstance` et `_promptsInstances`**

Supprimer la fonction `switchPromptsInstance` entière (~ligne 8003-8009).
Supprimer la variable `var _promptsInstances = [];`.
Supprimer `var _promptsInstance = 'main';` (plus besoin du switcher).

- [ ] **Step 12 : Simplifier `savePromptFile` — supprimer la branche instance**

Dans `savePromptFile` (~ligne 8018), remplacer :
```javascript
  var url, r;
  if (_promptsInstance === 'main') {
    var type = _promptsSection === 'persona' ? 'persona' : 'system';
    url = '/api/admin/prompts/' + type + '/' + _promptsFile;
  } else {
    url = '/api/admin/setup/instances/' + _promptsInstance + '/persona/' + _promptsFile;
  }
```
Par :
```javascript
  var type = _promptsSection === 'persona' ? 'persona' : 'system';
  var url = '/api/admin/prompts/' + type + '/' + _promptsFile;
```

- [ ] **Step 13 : Vérifier que le JS ne contient plus de références instances**

```bash
grep -n "instances\|is_main\|INSTANCES\|renderInstancesTab\|loadInstances\|notifyAllInstances\|instanceAction\|_promptsInstances\|switchPromptsInstance\|_promptsInstance" \
  /opt/stacks/wally-ai/bot/dashboard/static/app.js | grep -v "// " | head -20
```

Résultat attendu : aucune ligne (ou uniquement des commentaires inoffensifs).

- [ ] **Step 14 : Lancer les tests**

```bash
python3 -m pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 15 : Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(cleanup): app.js — supprimer onglet Instances, simplifier onglet Prompts"
```

---

## Task 6 : Supprimer provisioner.py + tests + README

**Files:**
- Delete: `bot/core/provisioner.py`
- Delete: `tests/test_setup_provisioner.py`
- Modify: `README.md`

- [ ] **Step 1 : Vérifier qu'aucun import de provisioner ne reste**

```bash
grep -rn "from bot.core.provisioner\|import provisioner" /opt/stacks/wally-ai/bot/ /opt/stacks/wally-ai/tests/ | grep -v ".pyc"
```

Résultat attendu : aucune ligne.

- [ ] **Step 2 : Supprimer `bot/core/provisioner.py`**

```bash
rm /opt/stacks/wally-ai/bot/core/provisioner.py
```

- [ ] **Step 3 : Supprimer `tests/test_setup_provisioner.py`**

```bash
rm /opt/stacks/wally-ai/tests/test_setup_provisioner.py
```

- [ ] **Step 4 : Mettre à jour `README.md`**

**Section "Dashboard Web" → Mode admin** :

Remplacer la ligne :
```
- **Barre de contrôle** : statut Discord/Twitch, boutons stop/start, restart container
```
Par :
```
- **Barre de contrôle** : statut Discord/Twitch, boutons stop/start, bouton "Mise à jour disponible" (amber, auto-détecté via GHCR)
```

Supprimer la mention des instances dans cette section si présente.

**Section "Docker"** :

Remplacer :
```
Trois services : `wally` (bot principal), `qdrant` (base vectorielle), `cloudflared` (tunnel optionnel).

Le socket Docker est monté dans le container Wally pour permettre le restart depuis le dashboard.
```
Par :
```
Deux services : `wally` (bot principal) et `qdrant` (base vectorielle). `cloudflared` peut être ajouté optionnellement pour un tunnel.

Le socket Docker est monté dans le container Wally pour permettre le restart et la mise à jour depuis le dashboard.
```

**Nouvelle section "Mise à jour" après "Docker"** :

Ajouter :
```markdown
## Mise à jour

Configurer `bot.update_image` dans `config.yaml` avec la référence de l'image GHCR :

```yaml
bot:
  update_image: "ghcr.io/ton-user/wally-ai:latest"
```

Le bot vérifie toutes les heures si une nouvelle image est disponible. Quand c'est le cas, un bouton amber "Mise à jour disponible" apparaît dans le panel admin. Un clic déclenche `docker compose pull && docker compose up -d --force-recreate` — le container se recrée avec la nouvelle image.

Laisser `update_image` vide pour désactiver le polling.
```

**Section "Configuration — `config.yaml`" → tableau Section `bot`** :

Ajouter la ligne :
```
| `update_image` | `""` | Référence image GHCR pour la détection auto de mise à jour (ex: `ghcr.io/user/wally-ai:latest`) |
```

- [ ] **Step 5 : Lancer la suite complète**

```bash
python3 -m pytest tests/ -x -q 2>&1 | tail -5
```

Résultat attendu : tous les tests passent, moins les tests provisioner supprimés.

- [ ] **Step 6 : Commit**

```bash
git add README.md
git commit -m "docs/cleanup: supprimer provisioner.py + tests, README mise à jour"
```

---

## Self-Review

### Couverture spec

| Exigence spec | Tâche |
|---|---|
| Supprimer `bot/core/provisioner.py` | Task 6 |
| Supprimer routes `/instances/*` de setup.py | Task 4 |
| Supprimer onglet Instances du dashboard JS | Task 5 |
| Supprimer `is_main` de GET /config | Task 3 |
| Remplacer flag fichier par UpdateChecker | Tasks 1, 2, 3 |
| Modifier self-update : pull avant recreate | Task 3 |
| `update_image` dans config.yaml | Task 2 |
| `UpdateChecker` avec polling GHCR | Task 1 |
| README mis à jour | Task 6 |
| Tests UpdateChecker | Task 1 |

Toutes les exigences sont couvertes. ✅

### Cohérence des types

- `UpdateChecker.update_available` → `bool` → utilisé dans `admin.py` comme `state.update_checker.update_available`
- `AppState.update_checker` → `Optional["UpdateChecker"]` → gardes `if state.update_checker is not None` en place
- `BotConfig.update_image` → `str = ""` → condition `if config.bot.update_image:` correcte
