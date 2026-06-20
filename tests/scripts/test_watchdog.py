import subprocess
import urllib.request


class _MockResponse:
    def __init__(self, status: int):
        self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): pass


def test_check_bot_returns_true_on_200(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda url, timeout: _MockResponse(200)
    )
    # import after patching so module-level globals use test values
    import importlib
    import scripts.watchdog as wd
    importlib.reload(wd)
    assert wd.check_bot() is True


def test_check_bot_returns_false_on_error(monkeypatch):
    def raise_error(url, timeout):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", raise_error)
    import importlib
    import scripts.watchdog as wd
    importlib.reload(wd)
    assert wd.check_bot() is False


def test_restart_bot_calls_docker_compose(monkeypatch):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
    monkeypatch.setattr(subprocess, "run", fake_run)
    import importlib
    import scripts.watchdog as wd
    importlib.reload(wd)
    wd.restart_bot()
    assert len(calls) == 1
    assert "up" in calls[0]
    assert "wally" in calls[0]


def test_run_restarts_after_threshold(monkeypatch):
    """Simulates 3 failures then 1 success; asserts restart_bot called exactly once."""
    import importlib
    import scripts.watchdog as wd
    importlib.reload(wd)

    check_results = [False, False, False, True]
    check_iter = iter(check_results)
    sleep_calls = []
    restart_calls = []

    def fake_check():
        try:
            return next(check_iter)
        except StopIteration:
            raise SystemExit(0)

    def fake_sleep(n):
        sleep_calls.append(n)
        # After the 5th sleep (index 4), stop the loop
        if len(sleep_calls) >= 5:
            raise SystemExit(0)

    def fake_restart():
        restart_calls.append(1)

    monkeypatch.setattr(wd, "check_bot", fake_check)
    monkeypatch.setattr(wd, "restart_bot", fake_restart)
    monkeypatch.setattr("time.sleep", fake_sleep)

    try:
        wd.run()
    except SystemExit:
        pass

    assert len(restart_calls) == 1
