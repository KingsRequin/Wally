# tests/test_recompense_tts_viewer.py
"""Le TTS des viewers : on paie, Wally lit le message à voix haute (2026-08-31).

Cousine de « im out », à ceci près que le texte vient du viewer. Ce qui s'y
joue en plus : le TON est choisi par le viewer (tag de tête, imposé à la
synthèse), le message est plafonné, le pseudo est dit, et un message vidé par
le nettoyage rend les points au lieu de partir mourir dans `_speak_locked`.

Comme partout ailleurs sur les points de chaîne, LE REMBOURSEMENT EST LA MOITIÉ
SÉRIEUSE du module : chaque chemin où le message ne sort PAS rend les points et
le dit.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.events import tts_viewer


@pytest.fixture(autouse=True)
def _cadence_neuve():
    """L'état de cadence vit au niveau MODULE : sans remise à zéro, le premier
    test à faire lire « alice » ferait rembourser tous les suivants."""
    tts_viewer._dernier_achat.clear()
    tts_viewer._lecture_en_cours = False
    yield
    tts_viewer._dernier_achat.clear()
    tts_viewer._lecture_en_cours = False


def _bot(*, connecte=True, speak=None):
    service = MagicMock()
    service.is_connected = connecte
    service.speak = speak or AsyncMock(return_value=True)
    bot = MagicMock()
    bot.discord_bot.voice_service = service
    bot.twitch_api.refund_redemption = AsyncMock(return_value=True)
    bot.twitch_api.send_automatic = AsyncMock(return_value=True)
    bot.stream_feed = MagicMock()
    return bot, service


@pytest.mark.asyncio
async def test_le_message_du_viewer_sort_a_voix_haute():
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="salut les gens",
                                  reward_id="RW", redemption_id="R1")

    dit = service.speak.call_args.args[0]
    assert "salut les gens" in dit
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_pseudo_de_l_acheteur_est_prononce():
    """Un TTS anonyme ne s'attribue à personne : ceux du vocal entendraient
    une phrase surgie de nulle part dans la bouche de Wally."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="coucou",
                                  reward_id="RW", redemption_id="R1")

    assert "alice" in service.speak.call_args.args[0]


@pytest.mark.asyncio
async def test_le_ton_du_viewer_pilote_la_voix():
    """C'est ce que la récompense VEND, et son invite le dit. Le ton voyage en
    donnée jusqu'à `speak(style=...)` : enchâssé dans le gabarit il ne serait
    plus en tête de phrase, et `parse_style_tag` ne le verrait jamais."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="[colère] bonjour",
                                  reward_id="RW", redemption_id="R1")

    assert service.speak.call_args.kwargs["style"] == "angry"
    dit = service.speak.call_args.args[0]
    assert "[" not in dit and "colère" not in dit
    assert "bonjour" in dit


@pytest.mark.asyncio
async def test_le_tag_se_lit_avec_la_table_de_wally():
    """Une seule table pour les deux : sans ça `[colere]` marcherait quand
    Wally se l'écrit et pas quand un viewer l'achète."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="[chuchote] psst",
                                  reward_id="RW", redemption_id="R1")

    assert service.speak.call_args.kwargs["style"] == "whispering"


@pytest.mark.asyncio
async def test_un_ton_inconnu_n_est_pas_une_panne():
    """Le tag est retiré, aucun style n'est imposé, le message part quand même :
    rembourser une phrase parfaitement lisible serait absurde."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="[wtf] bonjour",
                                  reward_id="RW", redemption_id="R1")

    assert service.speak.call_args.kwargs["style"] is None
    assert "bonjour" in service.speak.call_args.args[0]
    assert "wtf" not in service.speak.call_args.args[0]
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_les_crochets_restants_ne_sont_pas_prononces():
    """Une didascalie au milieu n'est pas un ton — elle n'a rien à faire dans
    la bouche de Wally."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="salut [rire] ça va",
                                  reward_id="RW", redemption_id="R1")

    dit = service.speak.call_args.args[0]
    assert "[" not in dit and "rire" not in dit
    assert "salut ça va" in dit


@pytest.mark.asyncio
async def test_un_message_qui_n_est_QUE_des_tags_rembourse():
    """Sans ce garde, il serait vidé bien plus loin, dans `_speak_locked`, où
    plus personne ne sait qu'il y avait des points à rendre."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="[murmure]",
                                  reward_id="RW", redemption_id="R1")

    service.speak.assert_not_awaited()
    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")


@pytest.mark.asyncio
async def test_le_message_est_plafonne():
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="a" * 500,
                                  reward_id="RW", redemption_id="R1")

    dit = service.speak.call_args.args[0]
    assert "a" * tts_viewer.LONGUEUR_MAX in dit
    assert "a" * (tts_viewer.LONGUEUR_MAX + 1) not in dit


@pytest.mark.asyncio
async def test_elle_passe_malgre_le_mode_ecoute():
    """Pendant un live Wally est en écoute seule ; l'achat est une demande
    explicite — même arbitrage que « im out »."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    assert service.speak.call_args.kwargs["malgre_ecoute"] is True


@pytest.mark.asyncio
async def test_hors_vocal_les_points_sont_rendus():
    bot, service = _bot(connecte=False)

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    service.speak.assert_not_awaited()
    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")
    assert "rendus" in bot.twitch_api.send_automatic.call_args.args[0]


@pytest.mark.asyncio
async def test_une_parole_qui_ne_sort_pas_rembourse():
    bot, _ = _bot(speak=AsyncMock(return_value=False))

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")


@pytest.mark.asyncio
async def test_une_panne_du_vocal_rembourse_aussi():
    bot, _ = _bot(speak=AsyncMock(side_effect=RuntimeError("azure down")))

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")


@pytest.mark.asyncio
async def test_un_remboursement_refuse_est_dit_franchement():
    bot, _ = _bot(connecte=False)
    bot.twitch_api.refund_redemption = AsyncMock(return_value=False)

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    assert "PAS pu te rendre tes points" in bot.twitch_api.send_automatic.call_args.args[0]


# ── Cadence : une lecture à la fois, une minute par personne ──────────────

@pytest.mark.asyncio
async def test_un_second_achat_pendant_une_lecture_est_refuse():
    """`speak()` sérialise ses appelants : sans drapeau, le second achat ne
    serait pas refusé — il ATTENDRAIT, et sa phrase sortirait bien plus tard,
    sans que personne comprenne pourquoi."""
    bot, service = _bot()
    pendant = {}

    async def _parle_longuement(*args, **kwargs):
        # Pendant que la première lecture passe, un autre viewer achète.
        await tts_viewer.lire_message(bot, acheteur="bob", saisie="moi aussi",
                                      reward_id="RW", redemption_id="R2")
        pendant["refus"] = bot.twitch_api.refund_redemption.await_args
        return True

    service.speak = AsyncMock(side_effect=_parle_longuement)

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    assert pendant["refus"].args == ("RW", "R2")
    assert service.speak.await_count == 1
    assert "déjà en train de lire" in bot.twitch_api.send_automatic.call_args.args[0]


@pytest.mark.asyncio
async def test_la_meme_personne_attend_sa_recharge():
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="un",
                                  reward_id="RW", redemption_id="R1")
    await tts_viewer.lire_message(bot, acheteur="alice", saisie="deux",
                                  reward_id="RW", redemption_id="R2")

    assert service.speak.await_count == 1
    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R2")
    assert "attends encore" in bot.twitch_api.send_automatic.call_args.args[0]


@pytest.mark.asyncio
async def test_la_recharge_ne_vise_QUE_l_acheteur():
    """C'est toute la raison de la garde maison : la recharge de Twitch est
    GLOBALE et aurait bloqué tout le chat pour l'achat d'une seule personne."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="un",
                                  reward_id="RW", redemption_id="R1")
    await tts_viewer.lire_message(bot, acheteur="bob", saisie="deux",
                                  reward_id="RW", redemption_id="R2")

    assert service.speak.await_count == 2
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_la_casse_du_pseudo_ne_contourne_pas_la_recharge():
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="Alice", saisie="un",
                                  reward_id="RW", redemption_id="R1")
    await tts_viewer.lire_message(bot, acheteur="alice", saisie="deux",
                                  reward_id="RW", redemption_id="R2")

    assert service.speak.await_count == 1


@pytest.mark.asyncio
async def test_un_achat_rembourse_n_arme_pas_la_recharge():
    """Bloquer une minute quelqu'un qui n'a RIEN entendu — et qu'on vient de
    rembourser — serait une double peine."""
    bot, service = _bot(connecte=False)

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")
    service.is_connected = True
    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R2")

    service.speak.assert_awaited_once()


@pytest.mark.asyncio
async def test_la_recharge_expire():
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="un",
                                  reward_id="RW", redemption_id="R1")
    # Le temps passe : l'entrée est vieillie d'une recharge complète.
    tts_viewer._dernier_achat["alice"] -= tts_viewer.RECHARGE_PERSONNE_S
    await tts_viewer.lire_message(bot, acheteur="alice", saisie="deux",
                                  reward_id="RW", redemption_id="R2")

    assert service.speak.await_count == 2
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_panne_de_voix_libere_le_verrou():
    """Sinon la récompense resterait morte jusqu'au prochain redémarrage."""
    bot, _ = _bot(speak=AsyncMock(side_effect=RuntimeError("azure down")))

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    assert tts_viewer._lecture_en_cours is False


@pytest.mark.asyncio
async def test_les_recharges_expirees_ne_s_accumulent_pas():
    """Une entrée par viewer à vie, pour une valeur qui ne dit plus rien passé
    la minute : c'est une fuite, lente mais certaine."""
    bot, _ = _bot()
    tts_viewer._dernier_achat["parti_depuis_longtemps"] = (
        time.monotonic() - 10 * tts_viewer.RECHARGE_PERSONNE_S)

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    assert list(tts_viewer._dernier_achat) == ["alice"]



# ── La récompense est reconnue par son ID, jamais par son titre ───────────

@pytest.mark.asyncio
async def test_l_achat_est_route_vers_le_bon_module(monkeypatch):
    from bot.twitch.events import redemptions

    appels = []

    async def _faux(bot, **kwargs):
        appels.append(kwargs)

    monkeypatch.setattr(tts_viewer, "lire_message", _faux)

    bot = MagicMock()
    bot.db.get_state = AsyncMock(
        side_effect=lambda cle: "RW-TTS" if cle == tts_viewer.CLE_RECOMPENSE else "")
    event = MagicMock()
    event.reward.id = "RW-TTS"
    event.id = "R1"
    event.user.name = "alice"
    event.input = "coucou"

    await redemptions.handle_redemption(bot, event)

    assert appels and appels[0]["acheteur"] == "alice"
    assert appels[0]["saisie"] == "coucou"


@pytest.mark.asyncio
async def test_sans_id_connu_aucune_recompense_ne_la_declenche():
    """Un ID vide DÉSACTIVE : sinon n'importe quel achat de la chaîne ferait
    lire sa saisie à voix haute."""
    from bot.twitch.events import redemptions

    bot = MagicMock()
    bot.db.get_state = AsyncMock(return_value="")

    assert await redemptions._est_le_tts_viewer(bot, "RW-AUTRE") is False
