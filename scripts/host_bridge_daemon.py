#!/usr/bin/env python3
"""Host-side bridge daemon. Listens on a Unix socket, exposes whitelisted Docker/git operations."""
import hmac
import http.server
import json
import logging
import os
import socketserver
import subprocess
import time
import uuid
from pathlib import Path

SOCKET_PATH = os.environ.get("BRIDGE_SOCKET", "/opt/stacks/wally-ai/data/bridge.sock")
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")
REPO_ROOT = Path(os.environ.get("REPO_ROOT", "/opt/stacks/wally-ai"))
COMPOSE_FILE = str(REPO_ROOT / "docker-compose.yml")
ALLOWED_SERVICES: set[str] = {"wally"}

JOBS_DIR = Path(os.environ.get("CLAUDE_JOBS_DIR", str(REPO_ROOT / "data" / "claude_jobs")))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/root/.local/bin/claude")
CLAUDE_TIMEOUT = float(os.environ.get("CLAUDE_TIMEOUT", "1800"))
_JOBS: dict[str, dict] = {}


def _git_head() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                       capture_output=True, timeout=10)
    return r.stdout.decode().strip()


def _git_status_porcelain() -> str:
    r = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                       capture_output=True, timeout=10)
    return r.stdout.decode().strip()


def _extract_claude_result(raw: str) -> str:
    """claude -p --output-format json émet un objet JSON ; on en extrait le résultat."""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            val = obj.get("result") or obj.get("text") or ""
            return str(val)[:1500]
    except (json.JSONDecodeError, ValueError):
        pass
    return raw[-1500:]


class BridgeHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: N802
        logging.info(fmt, *args)

    def _auth(self) -> bool:
        return bool(BRIDGE_SECRET) and hmac.compare_digest(
            self.headers.get("X-Bridge-Secret", ""), BRIDGE_SECRET
        )

    def _send(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except json.JSONDecodeError:
            return {}

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._auth():
            self._send(401, {"error": "unauthorized"})
            return
        body = self._read_body()

        if self.path == "/git-apply":
            diff = body.get("diff", "")
            r = subprocess.run(
                ["git", "apply", "--check", "-"],
                input=diff.encode(),
                cwd=REPO_ROOT,
                capture_output=True,
                timeout=30,
            )
            if r.returncode != 0:
                self._send(400, {"error": r.stderr.decode()})
                return
            subprocess.run(
                ["git", "apply", "-"],
                input=diff.encode(),
                cwd=REPO_ROOT,
                check=True,
                timeout=30,
            )
            self._send(200, {"status": "applied"})

        elif self.path == "/docker-rebuild":
            svc = body.get("service", "wally")
            if svc not in ALLOWED_SERVICES:
                self._send(400, {"error": "service not allowed"})
                return
            cmd = f"docker compose -f '{COMPOSE_FILE}' build {svc} && docker compose -f '{COMPOSE_FILE}' up -d --force-recreate {svc}"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
            self._send(200, {"status": "rebuilding"})

        elif self.path == "/docker-restart":
            svc = body.get("service", "wally")
            if svc not in ALLOWED_SERVICES:
                self._send(400, {"error": "service not allowed"})
                return
            cmd = f"docker compose -f '{COMPOSE_FILE}' up -d --force-recreate {svc}"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
            self._send(200, {"status": "restarting"})

        else:
            self._send(404, {"error": "not found"})


class UnixServer(socketserver.UnixStreamServer):
    def server_bind(self) -> None:
        sock = Path(SOCKET_PATH)
        if sock.exists():
            sock.unlink()
        super().server_bind()
        sock.chmod(0o660)


if __name__ == "__main__":
    if not BRIDGE_SECRET:
        raise SystemExit("BRIDGE_SECRET env var must be set — refusing to start")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with UnixServer(SOCKET_PATH, BridgeHandler) as s:
        logging.info("Bridge daemon listening on %s", SOCKET_PATH)
        s.serve_forever()
