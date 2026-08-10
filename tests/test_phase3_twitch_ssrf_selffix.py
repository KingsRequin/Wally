# tests/test_phase3_twitch_ssrf_selffix.py
"""Phase 3 de l'audit du 2026-08-10 : trois défauts critiques.

C8 — `_eventsub_restart_pending` reste à True à vie si l'appelant est annulé
     pendant l'attente du verrou → le watchdog EventSub se désarme en silence.
C9 — la garde SSRF ne résout aucun nom d'hôte : Firecrawl, auto-hébergé et sans
     filtre, pouvait lire le réseau du LXC et le recracher dans le chat.
C10 — un run Claude au-delà de 30 min condamnait le self-fix jusqu'au
      redémarrage du daemon hôte.
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.scrape import ScrapeService


# ────────────────────────────── C8 ──────────────────────────────
class _FauxTwitch:
    _restart_eventsub = None  # remplacé plus bas

    def __init__(self):
        self._eventsub_restart_pending = False
        self._eventsub_restart_lock = asyncio.Lock()
        self.redemarrages = 0

    async def _do_restart_eventsub(self):
        self.redemarrages += 1


def _lier_methode(obj):
    from bot.twitch.bot import WallyTwitch
    obj._restart_eventsub = WallyTwitch._restart_eventsub.__get__(obj)
    return obj


@pytest.mark.asyncio
async def test_une_annulation_pendant_l_attente_ne_condamne_pas_le_watchdog():
    b = _lier_methode(_FauxTwitch())
    await b._eventsub_restart_lock.acquire()          # le verrou est pris ailleurs
    tache = asyncio.create_task(b._restart_eventsub())
    await asyncio.sleep(0)                            # elle attend le verrou
    tache.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tache
    b._eventsub_restart_lock.release()

    assert b._eventsub_restart_pending is False, "drapeau verrouillé à vie"

    await b._restart_eventsub()                       # le watchdog doit repasser
    assert b.redemarrages == 1


@pytest.mark.asyncio
async def test_un_redemarrage_normal_remet_le_drapeau_a_zero():
    b = _lier_methode(_FauxTwitch())
    await b._restart_eventsub()
    await b._restart_eventsub()
    assert b.redemarrages == 2
    assert b._eventsub_restart_pending is False


# ────────────────────────────── C9 ──────────────────────────────
def _service():
    config = MagicMock()
    config.firecrawl.api_url = "http://firecrawl-api:3002"
    config.firecrawl.daily_limit = 100
    return ScrapeService(config, MagicMock())


@pytest.mark.asyncio
async def test_un_nom_d_hote_qui_pointe_vers_le_reseau_local_est_refuse():
    s = _service()
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.1.185", 80))]):
        assert await s.cible_autorisee("http://interne.attaquant.fr/") is False


@pytest.mark.asyncio
async def test_un_nom_d_hote_qui_pointe_vers_loopback_est_refuse():
    s = _service()
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]):
        assert await s.cible_autorisee("http://truc.example.com/") is False


@pytest.mark.asyncio
async def test_une_seule_ip_interne_parmi_plusieurs_suffit_a_refuser():
    """DNS rebinding : un hôte peut rendre une IP publique ET une privée."""
    s = _service()
    reponses = [(2, 1, 6, "", ("93.184.216.34", 80)), (2, 1, 6, "", ("10.0.0.5", 80))]
    with patch("socket.getaddrinfo", return_value=reponses):
        assert await s.cible_autorisee("http://double.example.com/") is False


@pytest.mark.asyncio
async def test_un_hote_irresolvable_est_refuse():
    s = _service()
    with patch("socket.getaddrinfo", side_effect=OSError("NXDOMAIN")):
        assert await s.cible_autorisee("http://nexistepas.example.com/") is False


@pytest.mark.asyncio
async def test_un_site_public_reste_lisible():
    s = _service()
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]):
        assert await s.cible_autorisee("https://example.com/article") is True


@pytest.mark.asyncio
async def test_le_scrape_refuse_la_cible_interne_sans_appeler_firecrawl():
    s = _service()
    s._base_url = "http://firecrawl-api:3002"
    s._config.firecrawl.enabled = True
    s.daily_limit_reached = AsyncMock(return_value=False)
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.1.185", 80))]), \
         patch("httpx.AsyncClient") as client:
        out = await s.scrape("http://interne.attaquant.fr/")
    client.assert_not_called()
    assert "ne peut pas être lue" in out


# ────────────────────────────── C10 ──────────────────────────────
def _daemon():
    chemin = Path(__file__).parent.parent / "scripts" / "host_bridge_daemon.py"
    spec = importlib.util.spec_from_file_location("host_bridge_daemon", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["host_bridge_daemon"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_un_job_termine_mais_jamais_relu_ne_bloque_plus_les_suivants():
    d = _daemon()
    proc = MagicMock()
    proc.poll.return_value = 0          # le process est fini
    proc.returncode = 0
    d._JOBS.clear()
    d._JOBS["abc"] = {"state": "running", "proc": proc,
                      "started_at": 0.0, "outf": MagicMock()}

    assert d._job_reellement_en_cours() is False
    assert d._JOBS["abc"]["state"] == "done"


def test_un_job_qui_tourne_vraiment_bloque_bien_les_suivants():
    d = _daemon()
    proc = MagicMock()
    proc.poll.return_value = None       # toujours vivant
    d._JOBS.clear()
    d._JOBS["abc"] = {"state": "running", "proc": proc,
                      "started_at": float(os.times().elapsed), "outf": MagicMock()}
    import time
    d._JOBS["abc"]["started_at"] = time.time()

    assert d._job_reellement_en_cours() is True


def test_un_job_au_dela_du_timeout_est_tue_et_liberé():
    d = _daemon()
    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 999999
    d._JOBS.clear()
    d._JOBS["abc"] = {"state": "running", "proc": proc,
                      "started_at": 0.0, "outf": MagicMock()}

    with patch.object(d.os, "killpg"), patch.object(d.os, "getpgid", return_value=1):
        assert d._job_reellement_en_cours() is False
    assert d._JOBS["abc"]["state"] == "failed"
