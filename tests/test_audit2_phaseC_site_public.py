# tests/test_audit2_phaseC_site_public.py
"""Phase C du second audit : le site public.

A2-14 — le bouton « Déconnexion » ne retirait que le JWT : `mount()` rebattait
        un jeton neuf depuis le refresh token, et le visiteur suivant d'un
        navigateur partagé reprenait la session Discord du précédent.
A2-13 — EventSource jamais fermée sur erreur : les flux doublaient à chaque
        incident.
A2-15 — dates construites en local, sérialisées en UTC : « Préc. » reculait de
        deux jours, « Suiv. » n'avançait jamais.
A2-js — WebSocket zombie au remontage, `buildSections` sans garde.
"""
import subprocess
from pathlib import Path

import pytest

_CHAT = Path("bot/dashboard/static/public-starter/tabs/chat.js")
_APP = Path("bot/dashboard/static/public-starter/app.js")


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ────────────────────────────── A2-14 ──────────────────────────────
def test_la_deconnexion_retire_les_deux_jetons():
    src = _src(_CHAT)
    i = src.index("logoutBtn.addEventListener")
    bloc = src[i:i + 700]
    assert "removeItem('discord_jwt')" in bloc
    assert "removeItem('discord_refresh')" in bloc, "le refresh token survivait 30 jours"


def test_la_deconnexion_ferme_aussi_la_socket():
    src = _src(_CHAT)
    i = src.index("logoutBtn.addEventListener")
    assert "_ws.close()" in src[i:i + 700]


# ────────────────────────────── A2-13 ──────────────────────────────
def test_l_eventsource_est_fermee_avant_toute_relance():
    src = _src(_APP)
    assert "es.close(); setTimeout(connectSSE" in src
    # Plus de relance nue.
    assert "es.onerror = () => setTimeout(connectSSE" not in src


# ────────────────────────────── A2-15 ──────────────────────────────
def test_la_navigation_par_date_ne_passe_plus_par_utc():
    src = _src(_CHAT)
    assert "function ymd(dt)" in src
    # `toISOString` ne doit plus servir à fabriquer une date de navigation.
    i_nav = src.index("function prevDay")
    fin = src.index("function getAvatarUrl")
    assert "toISOString" not in src[i_nav:fin]


def test_la_borne_minimale_est_construite_en_local():
    src = _src(_CHAT)
    assert "const DATE_MIN = new Date(2026, 2, 1);" in src


@pytest.mark.skipif(
    subprocess.run(["which", "node"], capture_output=True).returncode != 0,
    reason="node absent",
)
def test_les_jours_s_enchainent_correctement_en_heure_de_paris():
    """La preuve, exécutée : avant, prev sautait un jour et next n'avançait pas."""
    script = """
    function ymd(dt){return dt.getFullYear()+'-'+String(dt.getMonth()+1).padStart(2,'0')+'-'+String(dt.getDate()).padStart(2,'0');}
    function prevDay(s){const [y,m,d]=s.split('-').map(Number);const dt=new Date(y,m-1,d);dt.setDate(dt.getDate()-1);return ymd(dt);}
    function nextDay(s){const [y,m,d]=s.split('-').map(Number);const dt=new Date(y,m-1,d);dt.setDate(dt.getDate()+1);return ymd(dt);}
    console.log(prevDay('2026-08-10'), nextDay('2026-08-08'), nextDay(prevDay('2026-08-10')));
    """
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True,
        env={"TZ": "Europe/Paris", "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    prev, suiv, aller_retour = out.stdout.split()
    assert prev == "2026-08-09"
    assert suiv == "2026-08-09"
    assert aller_retour == "2026-08-10", "aller-retour non idempotent"


# ────────────────────────────── divers JS ──────────────────────────────
def test_le_remontage_ferme_la_socket_precedente():
    src = _src(_CHAT)
    i = src.index("export function mount(el)")
    bloc = src[i:i + 700]
    assert "_ws.close()" in bloc
    assert "clearTimeout(_retryTimer)" in bloc


def test_une_section_cassee_n_emporte_pas_la_page():
    src = _src(_APP)
    i = src.index("function buildSections")
    bloc = src[i:i + 900]
    assert "try {" in bloc and "TABS[name](sec);" in bloc
    assert "Section indisponible." in bloc


@pytest.mark.skipif(
    subprocess.run(["which", "node"], capture_output=True).returncode != 0,
    reason="node absent",
)
@pytest.mark.parametrize("fichier", [_CHAT, _APP])
def test_le_javascript_reste_syntaxiquement_valide(fichier):
    r = subprocess.run(["node", "--check", str(fichier)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
