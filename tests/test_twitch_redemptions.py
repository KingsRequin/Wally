"""L'achat de la récompense ouvre un duel — ou rembourse, mais ne se tait jamais."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.events.redemptions import _est_notre_recompense, handle_redemption


def _bot(reward_id="RW", duel_en_cours=None, persisted_reward_id=None):
    bot = MagicMock()
    bot.twitch_api.refund_redemption = AsyncMock(return_value=True)
    bot.twitch_api.send_message = AsyncMock(return_value=True)
    bot.duel_runner = MagicMock()
    bot.duel_runner._reward_id = reward_id
    bot.duel_runner.duel_en_cours = duel_en_cours
    bot.duel_runner.ouvrir = AsyncMock()
    bot.db.get_state = AsyncMock(return_value=persisted_reward_id)
    return bot


def _event(reward_id="RW", user="bob", texte="1012242925358", user_id="105904256"):
    e = MagicMock()
    e.reward.id = reward_id
    e.id = "RD1"
    e.user.name = user
    e.user.id = user_id
    e.input = texte
    return e


@pytest.mark.asyncio
async def test_une_autre_recompense_est_ignoree():
    assert await _est_notre_recompense(_bot("RW"), "AUTRE") is False
    assert await _est_notre_recompense(_bot("RW"), "RW") is True


@pytest.mark.asyncio
async def test_reward_id_non_configure_n_attrape_rien():
    """Vide = duel désactivé. Sans ce garde, toute récompense de la chaîne
    lancerait un duel."""
    assert await _est_notre_recompense(_bot("", persisted_reward_id=None), "") is False
    assert await _est_notre_recompense(_bot("", persisted_reward_id=None), "RW") is False


@pytest.mark.asyncio
async def test_duel_deja_en_cours_est_delegue_a_ouvrir():
    """Le refus « déjà en cours » n'est plus court-circuité ici (Task 8 —
    revue) : `ouvrir()` est le seul endroit qui détient à la fois le
    remboursement ET le canal d'annonce, un court-circuit muet dans ce
    handler laissait le viewer sans un mot d'explication."""
    bot = _bot(duel_en_cours=object())
    await handle_redemption(bot, _event())
    bot.duel_runner.ouvrir.assert_awaited_once()
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_achat_valide_ouvre_le_duel():
    bot = _bot()
    await handle_redemption(bot, _event(texte="1012242925358"))
    bot.duel_runner.ouvrir.assert_awaited_once()
    args = bot.duel_runner.ouvrir.await_args.kwargs
    assert args["saisie"] == "1012242925358"
    assert args["redemption_id"] == "RD1"
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_exception_ne_remonte_jamais():
    """Un handler d'événement ne crashe pas le bot."""
    bot = _bot()
    bot.duel_runner.ouvrir = AsyncMock(side_effect=RuntimeError("boum"))
    await handle_redemption(bot, _event())  # ne doit pas lever


@pytest.mark.asyncio
async def test_runner_absent_rembourse_via_lid_persiste():
    """CRITICAL : sans repli sur `bot_state`, cette branche était du code mort —
    `_est_notre_recompense` rendait False avant que `handle_redemption` puisse
    seulement atteindre son `if runner is None`. Un achat pendant que le runner
    est indisponible (Apex down au boot) n'était donc JAMAIS remboursé."""
    bot = _bot(persisted_reward_id="RW")
    bot.duel_runner = None
    await handle_redemption(bot, _event(reward_id="RW"))
    bot.twitch_api.refund_redemption.assert_awaited_once()


@pytest.mark.asyncio
async def test_exception_dans_ouvrir_rembourse():
    """Un crash réseau au milieu d'`ouvrir()` ne doit pas avaler les points du
    viewer : à ce stade reward_id/redemption_id sont connus, aucun duel n'est
    ouvert."""
    bot = _bot()
    bot.duel_runner.ouvrir = AsyncMock(side_effect=RuntimeError("timeout"))
    await handle_redemption(bot, _event())
    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "RD1")


# ── Revue finale — CRITICAL 2 : un remboursement muet reste un silence ───────
# La récompense reste achetable en permanence : rien ne la désactive, et elle
# est toujours reconnue via l'identifiant persisté. Sur ces deux chemins, le
# viewer voyait ses points revenir sans jamais savoir pourquoi.
def _dit(bot) -> str:
    return " ".join(str(c.kwargs.get("text", ""))
                    for c in bot.twitch_api.send_message.await_args_list)


@pytest.mark.asyncio
async def test_runner_absent_le_dit_dans_le_chat():
    bot = _bot(persisted_reward_id="RW")
    bot.duel_runner = None

    await handle_redemption(bot, _event(user="bob", reward_id="RW"))

    bot.twitch_api.refund_redemption.assert_awaited_once()
    dit = _dit(bot)
    assert dit.strip(), "un remboursement sans un mot est le pire résultat possible"
    assert "bob" in dit, "le viewer qui a payé doit savoir que ça le concerne"
    # Ces chemins existent quand la machinerie du duel n'est PAS disponible :
    # y appeler le modèle serait la dernière chose à tenter.
    bot.llm.complete.assert_not_called()
    bot.llm.complete_with_tools.assert_not_called()


@pytest.mark.asyncio
async def test_un_crash_pendant_l_ouverture_est_dit_dans_le_chat():
    bot = _bot()
    bot.duel_runner.ouvrir = AsyncMock(side_effect=RuntimeError("timeout"))

    await handle_redemption(bot, _event(user="carol"))

    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "RD1")
    assert _dit(bot).strip(), "le viewer doit apprendre que sa demande a échoué"


@pytest.mark.asyncio
async def test_un_chat_injoignable_ne_fait_pas_remonter_l_exception():
    """L'annonce est un bonus : le remboursement, lui, est déjà passé."""
    bot = _bot(persisted_reward_id="RW")
    bot.duel_runner = None
    bot.twitch_api.send_message = AsyncMock(side_effect=RuntimeError("Twitch down"))

    await handle_redemption(bot, _event(reward_id="RW"))  # ne doit pas lever

    bot.twitch_api.refund_redemption.assert_awaited_once()


@pytest.mark.asyncio
async def test_l_identifiant_twitch_du_duelliste_est_transmis():
    """Le duelliste est connu par son pseudo, mais la mémoire s'indexe par id :
    sans lui, la trace de fin de duel n'a nulle part où se ranger. La
    redemption le porte — inutile d'aller le rechercher ailleurs."""
    bot = _bot()
    await handle_redemption(bot, _event(user="bob", user_id="105904256"))
    assert bot.duel_runner.ouvrir.await_args.kwargs["acheteur_id"] == "105904256"


# ── Un remboursement REFUSÉ ne s'annonce pas comme un succès ────────────────
# `refund_redemption()` lit le corps de la réponse Helix et rend un booléen —
# ces deux chemins l'ignoraient et promettaient les points quoi qu'il arrive.
@pytest.mark.asyncio
async def test_runner_absent_et_remboursement_refuse_ne_promet_rien():
    bot = _bot(persisted_reward_id="RW")
    bot.duel_runner = None
    bot.twitch_api.refund_redemption = AsyncMock(return_value=False)

    await handle_redemption(bot, _event(user="bob", reward_id="RW"))

    dit = _dit(bot).lower()
    assert "rendus." not in dit, f"les points ne sont pas revenus : {dit!r}"
    assert "streamer" in dit, "le viewer doit savoir à qui s'adresser"


@pytest.mark.asyncio
async def test_un_crash_dont_le_remboursement_est_refuse_ne_promet_rien():
    bot = _bot()
    bot.duel_runner.ouvrir = AsyncMock(side_effect=RuntimeError("timeout"))
    bot.twitch_api.refund_redemption = AsyncMock(return_value=False)

    await handle_redemption(bot, _event(user="carol"))

    dit = _dit(bot).lower()
    assert "rendus." not in dit
    assert "streamer" in dit


@pytest.mark.asyncio
async def test_le_remboursement_reussi_est_toujours_annonce_comme_tel():
    """Le contre-exemple : sans lui, un message qui ne parlerait plus jamais de
    remboursement satisferait les deux tests ci-dessus."""
    bot = _bot(persisted_reward_id="RW")
    bot.duel_runner = None

    await handle_redemption(bot, _event(user="bob", reward_id="RW"))

    assert "rendus." in _dit(bot).lower()
