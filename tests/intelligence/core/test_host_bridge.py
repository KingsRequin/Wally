import json
import pytest
import httpx
from unittest.mock import patch

from bot.intelligence.host_bridge import HostBridgeClient, HostBridgeError


def make_transport(responses: dict):
    """responses: {"GET /health": (200, {...}), "POST /git-apply": (200, {...}), ...}"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.headers.get("X-Bridge-Secret") == "secret", \
                f"Missing X-Bridge-Secret on {request.url.path}"
        key = f"{request.method} {request.url.path}"
        if key in responses:
            code, body = responses[key]
            return httpx.Response(code, json=body)
        return httpx.Response(404, json={"error": "not found"})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_health_returns_true_on_200():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"GET /health": (200, {"status": "ok"})})
    with patch.object(client, "_transport", return_value=transport):
        assert await client.health() is True


@pytest.mark.asyncio
async def test_health_returns_false_on_connection_error():
    client = HostBridgeClient("/tmp/nonexistent.sock", "secret")
    # No patch — real UDS connect will fail
    result = await client.health()
    assert result is False


@pytest.mark.asyncio
async def test_git_apply_success():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"POST /git-apply": (200, {"status": "applied"})})
    with patch.object(client, "_transport", return_value=transport):
        await client.git_apply("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")


@pytest.mark.asyncio
async def test_git_apply_raises_on_error():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"POST /git-apply": (400, {"error": "patch does not apply"})})
    with patch.object(client, "_transport", return_value=transport):
        with pytest.raises(HostBridgeError, match="patch does not apply"):
            await client.git_apply("bad diff")


@pytest.mark.asyncio
async def test_docker_restart_success():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"POST /docker-restart": (200, {"status": "restarting"})})
    with patch.object(client, "_transport", return_value=transport):
        await client.docker_restart("wally")


@pytest.mark.asyncio
async def test_docker_rebuild_success():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"POST /docker-rebuild": (200, {"status": "rebuilding"})})
    with patch.object(client, "_transport", return_value=transport):
        await client.docker_rebuild("wally")
