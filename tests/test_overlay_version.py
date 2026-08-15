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


# ── tous les scripts servis, pas seulement overlay.js ───────────────────────


def test_les_vendors_comptent_dans_la_version(tmp_path, monkeypatch):
    """Une bibliothèque tierce mise à jour doit finir par arriver dans OBS.
    Hors de l'empreinte, l'ancienne version restait en cache pour toujours."""
    import bot.dashboard.routes.overlay as mod

    (tmp_path / "overlay.html").write_text("<html></html>")
    (tmp_path / "overlay.js").write_text("// v1")
    (tmp_path / "overlay_apex.js").write_text("// apex v1")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "spin-wheel.js").write_text("// roue v1")
    (vendor / "canvas-confetti.js").write_text("// confetti v1")
    monkeypatch.setattr(mod, "_STATIC_DIR", tmp_path)
    mod._version_cache.update(stamp=None, value="0")

    v1 = mod.overlay_version()
    (vendor / "spin-wheel.js").write_text("// roue v2")
    assert mod.overlay_version() != v1, "un vendor modifié doit changer la version"


def test_le_panneau_apex_compte_aussi(tmp_path, monkeypatch):
    """`overlay_apex.js` change souvent et n'était ni versionné ni surveillé."""
    import bot.dashboard.routes.overlay as mod

    (tmp_path / "overlay.html").write_text("<html></html>")
    (tmp_path / "overlay.js").write_text("// v1")
    (tmp_path / "overlay_apex.js").write_text("// apex v1")
    monkeypatch.setattr(mod, "_STATIC_DIR", tmp_path)
    mod._version_cache.update(stamp=None, value="0")

    v1 = mod.overlay_version()
    (tmp_path / "overlay_apex.js").write_text("// apex v2")
    assert mod.overlay_version() != v1


def test_un_redeploiement_a_l_identique_ne_recharge_rien(tmp_path, monkeypatch):
    """LA garantie qui compte : l'overlay se rafraîchit le moins possible. Tous
    les fichiers réécrits à l'identique — mtime neufs, contenu inchangé."""
    import bot.dashboard.routes.overlay as mod

    fichiers = {
        "overlay.html": "<html></html>",
        "overlay.js": "// v1",
        "overlay_apex.js": "// apex v1",
    }
    for nom, contenu in fichiers.items():
        (tmp_path / nom).write_text(contenu)
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "spin-wheel.js").write_text("// roue v1")
    monkeypatch.setattr(mod, "_STATIC_DIR", tmp_path)
    mod._version_cache.update(stamp=None, value="0")

    v1 = mod.overlay_version()
    for nom, contenu in fichiers.items():
        (tmp_path / nom).write_text(contenu)
    (vendor / "spin-wheel.js").write_text("// roue v1")
    assert mod.overlay_version() == v1


# ── la réécriture des balises <script> ──────────────────────────────────────


def test_chaque_script_statique_recoit_la_version():
    from bot.dashboard.routes.overlay import version_static_scripts

    html = (
        '<script src="/static/vendor/spin-wheel.js"></script>'
        '<script src="/static/overlay_apex.js"></script>'
        '<script src="/static/overlay.js"></script>'
    )
    out = version_static_scripts(html, "abc123")
    assert out.count("?v=abc123") == 3
    assert 'src="/static/vendor/spin-wheel.js?v=abc123"' in out


def test_les_ressources_non_js_sont_laissees_tranquilles():
    """La vidéo de l'avatar pèse lourd : la re-télécharger à chaque changement
    de script serait absurde."""
    from bot.dashboard.routes.overlay import version_static_scripts

    html = '<source src="/static/avatar/wally.webm" type="video/webm">'
    assert version_static_scripts(html, "abc123") == html


def test_une_version_n_est_jamais_ajoutee_deux_fois():
    from bot.dashboard.routes.overlay import version_static_scripts

    html = '<script src="/static/overlay.js?v=vieux"></script>'
    out = version_static_scripts(html, "neuf")
    assert out.count("?v=") == 1


def test_la_feuille_de_style_recoit_la_version_sans_perdre_son_attribut():
    """La page charge `animate.min.css` depuis que l'image de la galerie y a été
    portée : ses animations sont nommées dans la configuration. Une ressource
    sans empreinte resterait dans le cache d'OBS pour toujours.

    L'attribut est capturé et réécrit tel quel : transformer le `href` d'un
    `<link>` en `src` sortirait la feuille de la page sans un mot.
    """
    from bot.dashboard.routes.overlay import version_static_scripts

    html = '<link rel="stylesheet" href="/static/animate.min.css">'
    out = version_static_scripts(html, "abc123")
    assert out == '<link rel="stylesheet" href="/static/animate.min.css?v=abc123">'


def test_la_feuille_de_style_compte_dans_l_empreinte():
    from bot.dashboard.routes.overlay import _OVERLAY_FILES

    assert "animate.min.css" in _OVERLAY_FILES
