# tests/test_twitch_ignored_users.py
"""Les comptes que Wally ne doit pas écouter.

La liste des bots connus (nightbot, streamelements…) vivait en dur dans le code :
ajouter un bot croisé sur une chaîne invitée demandait une modification et un
rebuild. Elle reste comme SOCLE — elle est la même pour tout le monde — mais une
liste de config s'y ajoute, modifiable à chaud depuis le dashboard.
"""
from bot.twitch.handlers import _KNOWN_BOTS, is_ignored_chatter


def test_les_bots_connus_restent_ignores():
    """Le socle ne dépend d'aucune config : il vaut sur toutes les chaînes."""
    assert is_ignored_chatter("nightbot", []) is True
    assert is_ignored_chatter("streamelements", []) is True


def test_un_pseudo_de_la_config_est_ignore():
    assert is_ignored_chatter("wzbot", ["wzbot"]) is True


def test_un_spectateur_ordinaire_n_est_pas_ignore():
    assert is_ignored_chatter("kingsrequin", ["wzbot"]) is False


def test_la_casse_n_a_pas_d_importance():
    """Twitch affiche « WZBot », le login est « wzbot » : les deux doivent
    marcher, sinon la saisie au dashboard est un piège."""
    assert is_ignored_chatter("WZBot", ["wzbot"]) is True
    assert is_ignored_chatter("wzbot", ["WZBot"]) is True


def test_les_espaces_de_saisie_sont_tolerés():
    """Une liste tapée à la main contient des espaces parasites."""
    assert is_ignored_chatter("wzbot", [" wzbot ", ""]) is True


def test_une_config_absente_ne_casse_rien():
    assert is_ignored_chatter("kingsrequin", None) is False
    assert is_ignored_chatter("nightbot", None) is True


def test_un_auteur_vide_n_est_pas_ignore():
    """Pas de faux positif sur une chaîne vide présente dans la liste."""
    assert is_ignored_chatter("", ["", "wzbot"]) is False


def test_le_socle_est_au_niveau_module():
    """Reconstruit à chaque message, il coûtait un frozenset par ligne de chat."""
    assert isinstance(_KNOWN_BOTS, frozenset)
    assert "nightbot" in _KNOWN_BOTS


# ── la config ────────────────────────────────────────────────────────────────


def test_la_config_expose_la_liste_avec_un_defaut():
    """`TwitchConfig(**raw)` doit accepter un YAML qui n'a pas encore la clé."""
    from bot.config import TwitchConfig

    cfg = TwitchConfig(guest_channels=[], cooldown_seconds=10)
    assert cfg.ignored_users == []

    cfg2 = TwitchConfig(guest_channels=[], cooldown_seconds=10,
                        ignored_users=["wzbot"])
    assert cfg2.ignored_users == ["wzbot"]


# ── l'endpoint d'administration ──────────────────────────────────────────────


def _app_config():
    """Une app FastAPI minimale portant une vraie config Twitch."""
    from types import SimpleNamespace
    from bot.config import TwitchConfig

    cfg = SimpleNamespace(
        twitch=TwitchConfig(guest_channels=[], cooldown_seconds=10),
        save=lambda: None,
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        wally=SimpleNamespace(config=cfg))))


def _post(request, body):
    import asyncio
    from bot.dashboard.routes.admin import update_config
    return asyncio.run(update_config(request, body))


def test_l_endpoint_enregistre_la_liste():
    req = _app_config()
    _post(req, {"twitch": {"ignored_users": ["wzbot"]}})
    assert req.app.state.wally.config.twitch.ignored_users == ["wzbot"]


def test_l_endpoint_normalise_la_saisie():
    """« @WZBot » tapé au dashboard doit devenir « wzbot » : le filtre compare
    en minuscules, et une liste relue différemment de ce qu'on a tapé déroute."""
    req = _app_config()
    _post(req, {"twitch": {"ignored_users": ["  @WZBot ", "wzbot", ""]}})
    assert req.app.state.wally.config.twitch.ignored_users == ["wzbot"]


def test_l_endpoint_refuse_un_pseudo_invalide():
    """La liste est réaffichée dans le dashboard : pas de saisie libre."""
    import pytest
    from fastapi import HTTPException

    req = _app_config()
    with pytest.raises(HTTPException) as exc:
        _post(req, {"twitch": {"ignored_users": ["<img src=x onerror=alert(1)>"]}})
    assert exc.value.status_code == 400


def test_l_endpoint_n_ecrase_pas_les_chaines_invitees():
    """Le merge est partiel : régler les ignorés ne doit pas vider les invitées."""
    req = _app_config()
    req.app.state.wally.config.twitch.guest_channels = ["potitewonder"]
    _post(req, {"twitch": {"ignored_users": ["wzbot"]}})
    assert req.app.state.wally.config.twitch.guest_channels == ["potitewonder"]
