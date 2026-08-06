"""Mise à jour automatique de l'overlay.

OBS garde sa page en mémoire des heures : sans détection de version, chaque
changement demande de penser à rafraîchir la source à la main.
"""
import asyncio

from bot.dashboard.routes.overlay import (
    _STATIC_DIR,
    _version_cache,
    get_overlay_version,
    overlay_version,
)


def test_la_version_est_stable_entre_deux_appels():
    """Sinon l'overlay se rechargerait en boucle pendant le live."""
    assert overlay_version() == overlay_version()


def test_la_version_suit_le_contenu(tmp_path, monkeypatch):
    """Basée sur le contenu, pas sur la date : un redéploiement à l'identique ne
    doit pas provoquer de rechargement."""
    import bot.dashboard.routes.overlay as mod

    html, js = tmp_path / "overlay.html", tmp_path / "overlay.js"
    html.write_text("<html></html>")
    js.write_text("// v1")
    monkeypatch.setattr(mod, "_STATIC_DIR", tmp_path)
    mod._version_cache.update(stamp=None, value="0")

    v1 = mod.overlay_version()
    # Réécriture à l'identique : mtime change, contenu non.
    js.write_text("// v1")
    assert mod.overlay_version() == v1

    js.write_text("// v2")
    assert mod.overlay_version() != v1


def test_un_dossier_absent_ne_leve_pas(tmp_path, monkeypatch):
    """L'overlay ne doit pas tomber parce qu'un fichier manque."""
    import bot.dashboard.routes.overlay as mod

    monkeypatch.setattr(mod, "_STATIC_DIR", tmp_path / "nexiste-pas")
    mod._version_cache.update(stamp=None, value="0")
    assert isinstance(mod.overlay_version(), str)


def test_l_endpoint_rend_la_version():
    out = asyncio.run(get_overlay_version())
    assert out["version"] == overlay_version()
