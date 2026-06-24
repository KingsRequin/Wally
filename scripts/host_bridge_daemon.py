#!/usr/bin/env python3
"""Host-side bridge daemon. Listens on a Unix socket, exposes whitelisted Docker/git operations."""
import hmac
import http.server
import json
import logging
import os
import signal
import socketserver
import subprocess
import time
import uuid
from pathlib import Path

SOCKET_PATH = os.environ.get("BRIDGE_SOCKET", "/opt/stacks/wally-ai/data/bridge.sock")
# Le bot tourne dans le conteneur en tant que 1000:1000 et accède au socket via le
# volume ./data. Le daemon (root) doit donc lui en donner la propriété, sinon le
# socket recréé à chaque restart reste root:root et le conteneur perd l'accès.
SOCKET_UID = int(os.environ.get("BRIDGE_SOCKET_UID", "1000"))
SOCKET_GID = int(os.environ.get("BRIDGE_SOCKET_GID", "1000"))
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")
REPO_ROOT = Path(os.environ.get("REPO_ROOT", "/opt/stacks/wally-ai"))
COMPOSE_FILE = str(REPO_ROOT / "docker-compose.yml")
ALLOWED_SERVICES: set[str] = {"wally"}

JOBS_DIR = Path(os.environ.get("CLAUDE_JOBS_DIR", str(REPO_ROOT / "data" / "claude_jobs")))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/root/.local/bin/claude")
CLAUDE_TIMEOUT = float(os.environ.get("CLAUDE_TIMEOUT", "1800"))
# Auteur des commits que Wally se fait à lui-même (self-upgrade), pour les distinguer
# clairement des commits humains dans l'historique git.
WALLY_AUTHOR = os.environ.get(
    "WALLY_GIT_AUTHOR",
    "Wally (self-upgrade) <61652807+KingsRequin@users.noreply.github.com>",
)
_JOBS: dict[str, dict] = {}


def _git_head() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                       capture_output=True, timeout=10)
    return r.stdout.decode().strip()


def _git_status_porcelain() -> str:
    r = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                       capture_output=True, timeout=10)
    return r.stdout.decode().strip()


def _porcelain_paths() -> set[str]:
    """Ensemble des chemins modifiés/ajoutés/supprimés dans le working tree.

    Sert à isoler ce que Claude a touché PENDANT un run : on compare l'ensemble
    avant le run et après. Évite qu'un fichier déjà modifié (non lié au run)
    déclenche un faux commit/rebuild.

    On lit la sortie BRUTE (pas via _git_status_porcelain qui .strip() le bloc et
    retirerait l'espace de tête du statut de la 1re ligne → chemin décalé d'un char).
    Format porcelain v1 : 2 chars de statut + 1 espace + chemin.
    """
    r = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                       capture_output=True, timeout=10)
    paths: set[str] = set()
    for line in r.stdout.decode().split("\n"):
        if len(line) <= 3:
            continue
        rest = line[3:]  # retire "XY " (statut + espace), sans toucher au reste
        if " -> " in rest:  # rename : "orig -> new"
            rest = rest.split(" -> ", 1)[1]
        paths.add(rest.strip().strip('"'))
    return paths


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
            # Passe GIT_HASH/BUILD_DATE pour que BOT_GIT_HASH ne soit pas 'unknown'
            # après un rebuild autonome (sinon la version affichée est fausse).
            env = dict(os.environ)
            env["GIT_HASH"] = _git_head()[:7]
            env["BUILD_DATE"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            subprocess.Popen(cmd, shell=True, start_new_session=True, env=env)
            self._send(200, {"status": "rebuilding"})

        elif self.path == "/docker-restart":
            svc = body.get("service", "wally")
            if svc not in ALLOWED_SERVICES:
                self._send(400, {"error": "service not allowed"})
                return
            cmd = f"docker compose -f '{COMPOSE_FILE}' up -d --force-recreate {svc}"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
            self._send(200, {"status": "restarting"})

        elif self.path == "/claude-run":
            goal = body.get("goal", "").strip()
            if not goal:
                self._send(400, {"error": "goal vide"})
                return
            if any(j.get("state") == "running" for j in _JOBS.values()):
                self._send(409, {"error": "un job Claude est déjà en cours"})
                return
            job_id = uuid.uuid4().hex
            JOBS_DIR.mkdir(parents=True, exist_ok=True)
            out_path = JOBS_DIR / f"{job_id}.out"
            env = dict(os.environ)
            env["IS_SANDBOX"] = "1"
            outf = open(out_path, "wb")
            try:
                proc = subprocess.Popen(
                    [CLAUDE_BIN, "--dangerously-skip-permissions", "-p", goal,
                     "--output-format", "json"],
                    cwd=REPO_ROOT, env=env, stdout=outf, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as e:
                outf.close()
                logging.error("claude-run échec spawn: %s", e)
                self._send(500, {"error": f"impossible de lancer claude: {e}"})
                return
            _JOBS[job_id] = {
                "state": "running", "proc": proc, "outf": outf,
                "out_path": str(out_path), "head_before": _git_head(),
                "dirty_before": _porcelain_paths(),
                "goal": goal, "started_at": time.time(),
            }
            logging.info("claude-run job %s lancé (goal=%.60s)", job_id, goal)
            self._send(200, {"job_id": job_id})

        elif self.path == "/claude-status":
            job = _JOBS.get(body.get("job_id", ""))
            if job is None:
                self._send(404, {"error": "job inconnu"})
                return
            proc = job["proc"]
            rc = proc.poll()
            if rc is None:
                if time.time() - job["started_at"] > CLAUDE_TIMEOUT:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                    try:
                        job["outf"].close()
                    except OSError:
                        pass
                    job["state"] = "failed"
                    self._send(200, {"state": "failed", "exit_code": -1,
                                     "result": "", "changed": False,
                                     "head_changed": False,
                                     "output_tail": "timeout dépassé"})
                    return
                self._send(200, {"state": "running"})
                return
            try:
                job["outf"].close()
            except OSError:
                pass
            raw = Path(job["out_path"]).read_text(errors="replace")
            head_after = _git_head()
            state = "done" if rc == 0 else "failed"
            job["state"] = state
            # changed = uniquement ce que Claude a touché pendant le run
            # (diff vs l'état sale d'avant), pas les fichiers déjà modifiés.
            new_paths = _porcelain_paths() - job.get("dirty_before", set())
            self._send(200, {
                "state": state, "exit_code": rc,
                "result": _extract_claude_result(raw),
                "changed": bool(new_paths),
                "head_changed": head_after != job["head_before"],
                "output_tail": raw[-2000:],
            })

        elif self.path == "/claude-commit":
            job = _JOBS.get(body.get("job_id", ""))
            if job is None:
                self._send(404, {"error": "job inconnu"})
                return
            # On ne commit QUE les fichiers que Claude a touchés pendant le run,
            # pas les changements pré-existants (sinon commit bidon).
            new_paths = sorted(_porcelain_paths() - job.get("dirty_before", set()))
            if not new_paths:
                self._send(200, {"committed": False, "reason": "aucun changement de Claude"})
                return
            subprocess.run(["git", "add", "--", *new_paths], cwd=REPO_ROOT,
                           check=True, timeout=30)
            r = subprocess.run(
                ["git", "commit", "--author", WALLY_AUTHOR,
                 "-m", f"self-upgrade: {job.get('goal', '')}"[:200]],
                cwd=REPO_ROOT, capture_output=True, timeout=30,
            )
            if r.returncode != 0:
                self._send(500, {"error": r.stderr.decode()})
                return
            self._send(200, {"committed": True, "hash": _git_head(),
                             "files": new_paths})

        else:
            self._send(404, {"error": "not found"})


class UnixServer(socketserver.UnixStreamServer):
    def server_bind(self) -> None:
        sock = Path(SOCKET_PATH)
        if sock.exists():
            sock.unlink()
        super().server_bind()
        sock.chmod(0o660)
        try:
            os.chown(SOCKET_PATH, SOCKET_UID, SOCKET_GID)
        except OSError as exc:
            logging.warning("chown du socket impossible (%s) — le conteneur risque "
                            "de ne pas pouvoir y accéder", exc)


if __name__ == "__main__":
    if not BRIDGE_SECRET:
        raise SystemExit("BRIDGE_SECRET env var must be set — refusing to start")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with UnixServer(SOCKET_PATH, BridgeHandler) as s:
        logging.info("Bridge daemon listening on %s", SOCKET_PATH)
        s.serve_forever()
