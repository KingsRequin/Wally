#!/usr/bin/env python3
"""Host-side watchdog: restarts wally-bot if health check fails 3 times in a row."""
import logging
import os
import subprocess
import time
import urllib.request

BOT_URL = os.environ.get("WATCHDOG_BOT_URL", "http://127.0.0.1:8080/api/admin/bot/status")
COMPOSE_FILE = os.environ.get("WATCHDOG_COMPOSE_FILE", "/opt/stacks/wally-ai/docker-compose.yml")
FAIL_THRESHOLD = int(os.environ.get("WATCHDOG_FAIL_THRESHOLD", "3"))
CHECK_INTERVAL = int(os.environ.get("WATCHDOG_INTERVAL", "60"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("watchdog")


def check_bot() -> bool:
    try:
        with urllib.request.urlopen(BOT_URL, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        log.warning("Health check failed: %s", e)
        return False


def restart_bot() -> None:
    log.warning("Restarting wally service via docker compose...")
    try:
        subprocess.run(
            ["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "wally"],
            timeout=60,
            check=True,
        )
        log.info("Restart command sent")
    except subprocess.CalledProcessError as e:
        log.error("Restart failed: %s", e)


def run() -> None:
    failures = 0
    log.info(
        "Watchdog started (url=%s, threshold=%d, interval=%ds)",
        BOT_URL, FAIL_THRESHOLD, CHECK_INTERVAL,
    )
    while True:
        if check_bot():
            if failures > 0:
                log.info("Bot recovered after %d failures", failures)
            failures = 0
        else:
            failures += 1
            log.warning("Bot unhealthy (%d/%d)", failures, FAIL_THRESHOLD)
            if failures >= FAIL_THRESHOLD:
                restart_bot()
                failures = 0
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
