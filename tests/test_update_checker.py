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
