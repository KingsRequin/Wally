"""Un renommage garde l'ancien pseudo en alias.

Même identifiant, pseudo différent : la personne s'est renommée. Les faits
suivent l'ID, mais l'ANCIEN nom disparaissait sans laisser de trace — plus
personne ne pouvait dire « c'est l'ancien untel ».
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.intelligence.memory.service import MemoryService


def _service() -> MemoryService:
    cfg = MagicMock()
    cfg.bot.context_window_size = 10
    cfg.bot.prelude_window_size = 5
    cfg.bot.context_token_threshold = 2000
    return MemoryService(cfg)


async def test_pseudo_different_pose_un_alias():
    svc = _service()
    db = AsyncMock()

    assert await svc.noter_renommage(db, "twitch:42", "KingsRequin", "Azrael") is True

    db.upsert_alias.assert_awaited_once_with(
        "kingsrequin", "twitch:42", "Azrael", "renommage", 1.0
    )


async def test_alias_pose_est_resolvable_sans_redemarrage():
    """Le cache en mémoire doit bouger, pas seulement la base.

    Sinon la résolution ne marche qu'au prochain boot, en silence.
    """
    svc = _service()
    await svc.noter_renommage(AsyncMock(), "twitch:42", "KingsRequin", "Azrael")

    assert svc._alias_cache["nickname:kingsrequin"] == "twitch:42"
    assert svc._alias_cache["unknown:kingsrequin"] == "twitch:42"


async def test_changement_de_casse_n_est_pas_un_renommage():
    svc = _service()
    db = AsyncMock()

    assert await svc.noter_renommage(db, "twitch:42", "kingsrequin", "KingsRequin") is False

    db.upsert_alias.assert_not_awaited()
    assert svc._alias_cache == {}


@pytest.mark.parametrize(
    ("ancien", "nouveau"),
    [("", "Azrael"), ("KingsRequin", ""), ("  ", "Azrael"), ("KingsRequin", "   ")],
)
async def test_un_pseudo_vide_ne_pose_rien(ancien, nouveau):
    svc = _service()
    db = AsyncMock()

    assert await svc.noter_renommage(db, "twitch:42", ancien, nouveau) is False

    db.upsert_alias.assert_not_awaited()


async def test_base_en_echec_ne_touche_pas_au_cache():
    """Une écriture ratée ne doit pas laisser un alias vivant en RAM seule."""
    svc = _service()
    db = AsyncMock()
    db.upsert_alias.side_effect = RuntimeError("base verrouillée")

    assert await svc.noter_renommage(db, "twitch:42", "KingsRequin", "Azrael") is False
    assert svc._alias_cache == {}


# ── Câblage Discord : on_user_update ──────────────────────────────────────


def _bot_discord(pseudo_connu: str | None = "KingsRequin"):
    """Capture le handler on_user_update enregistré via @bot.event."""
    bot = MagicMock()
    bot.db.get_memory_username = AsyncMock(return_value=pseudo_connu)
    bot.memory.noter_renommage = AsyncMock(return_value=True)

    captured = {}
    bot.event = lambda fn: captured.__setitem__(fn.__name__, fn) or fn

    from bot.discord.events import members

    members.register(bot)
    return bot, captured["on_user_update"]


# ⚠️ `name=` est un paramètre RÉSERVÉ de MagicMock (il nomme le mock) : il ne
# devient jamais un attribut. D'où SimpleNamespace.
def _user(uid: int, name: str):
    return SimpleNamespace(id=uid, name=name)


async def test_discord_renommage_range_l_ancien_pseudo():
    bot, on_user_update = _bot_discord()

    await on_user_update(_user(7, "KingsRequin"), _user(7, "Azrael"))

    bot.memory.noter_renommage.assert_awaited_once_with(
        bot.db, "discord:7", "KingsRequin", "Azrael"
    )


async def test_discord_avatar_change_ne_declenche_rien():
    """`on_user_update` part aussi pour un avatar : le pseudo seul compte."""
    bot, on_user_update = _bot_discord()

    await on_user_update(_user(7, "KingsRequin"), _user(7, "KingsRequin"))

    bot.db.get_memory_username.assert_not_awaited()
    bot.memory.noter_renommage.assert_not_awaited()


async def test_discord_inconnu_de_la_memoire_est_ignore():
    """L'événement arrive pour tout le cache — on ne suit que les connus."""
    bot, on_user_update = _bot_discord(pseudo_connu=None)

    await on_user_update(_user(7, "KingsRequin"), _user(7, "Azrael"))

    bot.memory.noter_renommage.assert_not_awaited()


async def test_discord_base_en_echec_ne_fait_pas_tomber_l_event():
    bot, on_user_update = _bot_discord()
    bot.db.get_memory_username.side_effect = RuntimeError("base fermée")

    await on_user_update(_user(7, "KingsRequin"), _user(7, "Azrael"))

    bot.memory.noter_renommage.assert_not_awaited()


# ── Câblage Twitch : détection au fil des messages ────────────────────────


async def test_twitch_pseudo_different_en_base_declenche_la_detection(monkeypatch):
    """Le handler compare AVANT d'écraser : c'est le seul endroit où les deux
    pseudos se rencontrent."""
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    from tests.test_twitch_handlers import make_bot, make_payload
    from bot.twitch.handlers import handle_message

    bot = make_bot()
    bot.db.get_memory_username = AsyncMock(return_value="KingsRequin")
    bot.memory.noter_renommage = AsyncMock(return_value=True)

    await handle_message(bot, make_payload(content="salut", author_id="42",
                                           author_name="azrael",
                                           author_display="Azrael"))

    bot.memory.noter_renommage.assert_awaited_once_with(
        bot.db, "twitch:42", "KingsRequin", "Azrael"
    )
    bot.db.upsert_memory_user.assert_awaited_with(
        "twitch:42", "twitch", username="Azrael"
    )


async def test_twitch_personne_inconnue_ne_declenche_rien(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    from tests.test_twitch_handlers import make_bot, make_payload
    from bot.twitch.handlers import handle_message

    bot = make_bot()
    bot.db.get_memory_username = AsyncMock(return_value=None)
    bot.memory.noter_renommage = AsyncMock()

    await handle_message(bot, make_payload(content="salut", author_id="42"))

    bot.memory.noter_renommage.assert_not_awaited()
