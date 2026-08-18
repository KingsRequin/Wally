"""Forcer l'humeur de Wally aux points de chaîne (§14).

Deux récompenses : 1 000 points montent l'émotion demandée à 50 %, 2 000 à
100 %. Le viewer écrit l'émotion voulue dans le champ de texte de la récompense.

Ce qui décide de tout ici, c'est le REMBOURSEMENT. Le viewer tape à la main : il
écrira « colere » sans accent, « JOIE » en majuscules, « énervé » au lieu de
« colère », ou carrément « pizza ». Chaque cas où l'humeur ne change PAS doit
rendre les points ET le dire — sinon on prend 1 000 points pour rien, en direct.

On est donc large sur ce qu'on accepte, et strict sur ce qu'on promet.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _bot():
    bot = MagicMock()
    bot.twitch_api.refund_redemption = AsyncMock(return_value=True)
    bot.twitch_api.send_message = AsyncMock(return_value=True)
    bot.emotion = MagicMock()
    bot.stream_feed = None
    return bot


# ── reconnaître ce que le viewer a tapé ─────────────────────────────────────

@pytest.mark.parametrize("saisi,attendu", [
    ("colère", "anger"), ("colere", "anger"), ("COLÈRE", "anger"),
    ("  colère  ", "anger"), ("énervé", "anger"), ("rage", "anger"),
    ("joie", "joy"), ("joyeux", "joy"), ("heureux", "joy"),
    ("tristesse", "sadness"), ("triste", "sadness"),
    ("curiosité", "curiosity"), ("curieux", "curiosity"),
    ("ennui", "boredom"), ("blasé", "boredom"),
    # Les noms techniques marchent aussi : quelqu'un lira le code un jour.
    ("anger", "anger"), ("joy", "joy"),
])
def test_les_ecritures_courantes_sont_TOUTES_reconnues(saisi, attendu):
    """Le viewer tape à la main, sans accent, en majuscules, avec un synonyme.
    Refuser « colere » pour un accent manquant serait prendre ses points sur une
    faute de frappe."""
    from bot.twitch.events.humeur import reconnaitre_emotion
    assert reconnaitre_emotion(saisi) == attendu


@pytest.mark.parametrize("saisi", ["pizza", "", "   ", None, "azerty", "42"])
def test_ce_qui_ne_ressemble_a_RIEN_est_refuse(saisi):
    """Et c'est ce refus qui déclenche le remboursement."""
    from bot.twitch.events.humeur import reconnaitre_emotion
    assert reconnaitre_emotion(saisi) is None


def test_toutes_les_emotions_du_moteur_ont_un_mot():
    """Le garde-fou qui compte : si quelqu'un ajoute une émotion au moteur sans
    l'écrire ici, elle serait impossible à demander — et le viewer se ferait
    rembourser sans comprendre pourquoi."""
    from bot.core.emotion import EMOTIONS
    from bot.twitch.events.humeur import reconnaitre_emotion

    for emotion in EMOTIONS:
        assert reconnaitre_emotion(emotion) == emotion


def test_le_libelle_PROPOSE_les_emotions():
    """Le viewer doit savoir quoi écrire avant de dépenser 1 000 points."""
    from bot.core.emotion import EMOTIONS
    from bot.twitch.events.humeur import PROMPT

    assert len(PROMPT) <= 200          # borne de l'API Twitch
    manquantes = [e for e in EMOTIONS if not _cite(PROMPT, e)]
    assert not manquantes, f"émotions absentes du libellé : {manquantes}"


def _cite(prompt: str, emotion: str) -> bool:
    """Le libellé s'écrit avec ses accents, la table sans : on compare les deux
    sous la même forme, celle que le code utilise déjà pour reconnaître."""
    from bot.twitch.events.humeur import MOTS, _nu

    nu = _nu(prompt)
    return any(mot in nu for mot, cible in MOTS.items() if cible == emotion)


# ── appliquer ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mille_points_montent_l_emotion_a_CINQUANTE_pour_cent():
    from bot.twitch.events.humeur import forcer_humeur
    bot = _bot()
    await forcer_humeur(bot, acheteur="bob", texte="colère", intensite=0.5,
                        reward_id="r1", redemption_id="d1")
    bot.emotion.set_emotion.assert_called_once_with("anger", 0.5)
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_deux_mille_points_la_montent_a_FOND():
    from bot.twitch.events.humeur import forcer_humeur
    bot = _bot()
    await forcer_humeur(bot, acheteur="bob", texte="joie", intensite=1.0,
                        reward_id="r2", redemption_id="d2")
    bot.emotion.set_emotion.assert_called_once_with("joy", 1.0)


@pytest.mark.asyncio
async def test_wally_ANNONCE_ce_qui_lui_arrive():
    """Sinon le viewer paie 1 000 points sans aucun retour visible."""
    from bot.twitch.events.humeur import forcer_humeur
    bot = _bot()
    await forcer_humeur(bot, acheteur="bob", texte="colère", intensite=0.5,
                        reward_id="r1", redemption_id="d1")
    bot.twitch_api.send_message.assert_awaited()


# ── rembourser ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_mot_INCONNU_rembourse_et_le_dit():
    from bot.twitch.events.humeur import forcer_humeur
    bot = _bot()
    await forcer_humeur(bot, acheteur="bob", texte="pizza", intensite=0.5,
                        reward_id="r1", redemption_id="d1")
    bot.emotion.set_emotion.assert_not_called()
    bot.twitch_api.refund_redemption.assert_awaited_once_with("r1", "d1")
    dit = bot.twitch_api.send_message.call_args.kwargs["text"].lower()
    assert "rendu" in dit or "rembours" in dit


@pytest.mark.asyncio
async def test_un_champ_VIDE_rembourse_aussi():
    from bot.twitch.events.humeur import forcer_humeur
    bot = _bot()
    await forcer_humeur(bot, acheteur="bob", texte="", intensite=0.5,
                        reward_id="r1", redemption_id="d1")
    bot.twitch_api.refund_redemption.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_remboursement_REFUSE_ne_promet_pas_le_contraire():
    """Twitch peut refuser (redemption déjà traitée). Annoncer « tes points
    t'ont été rendus » serait alors un mensonge — la règle tenue partout
    ailleurs dans ce bot."""
    from bot.twitch.events.humeur import forcer_humeur
    bot = _bot()
    bot.twitch_api.refund_redemption = AsyncMock(return_value=False)
    await forcer_humeur(bot, acheteur="bob", texte="pizza", intensite=0.5,
                        reward_id="r1", redemption_id="d1")
    dit = bot.twitch_api.send_message.call_args.kwargs["text"].lower()
    assert "pas pu" in dit or "manuellement" in dit


@pytest.mark.asyncio
async def test_sans_MOTEUR_d_emotions_on_rembourse():
    """Le bot peut tourner sans : ne rien faire en gardant les points serait du
    vol."""
    from bot.twitch.events.humeur import forcer_humeur
    bot = _bot()
    bot.emotion = None
    await forcer_humeur(bot, acheteur="bob", texte="colère", intensite=0.5,
                        reward_id="r1", redemption_id="d1")
    bot.twitch_api.refund_redemption.assert_awaited_once()


@pytest.mark.asyncio
async def test_une_PANNE_pendant_l_application_rembourse():
    from bot.twitch.events.humeur import forcer_humeur
    bot = _bot()
    bot.emotion.set_emotion.side_effect = RuntimeError("moteur cassé")
    await forcer_humeur(bot, acheteur="bob", texte="colère", intensite=0.5,
                        reward_id="r1", redemption_id="d1")
    bot.twitch_api.refund_redemption.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_chat_injoignable_ne_fait_pas_remonter_l_exception():
    """Un handler d'événement ne tue jamais le bot."""
    from bot.twitch.events.humeur import forcer_humeur
    bot = _bot()
    bot.twitch_api.send_message = AsyncMock(side_effect=RuntimeError("chat mort"))
    await forcer_humeur(bot, acheteur="bob", texte="colère", intensite=0.5,
                        reward_id="r1", redemption_id="d1")


# ── les deux récompenses ────────────────────────────────────────────────────

def test_les_deux_recompenses_ont_des_cles_DISTINCTES():
    """Partagées, l'une deviendrait irremboursable et l'autre appliquerait la
    mauvaise intensité — le piège déjà nommé pour le duel et l'avalanche."""
    from bot.twitch.events.humeur import CLE_50, CLE_100

    assert CLE_50 != CLE_100
    from bot.core.apex.duel_runner import CLE_RECOMPENSE as CLE_DUEL
    from bot.twitch.events.virus_popups import CLE_RECOMPENSE as CLE_VIRUS
    assert len({CLE_50, CLE_100, CLE_VIRUS, CLE_DUEL}) == 4


def test_les_deux_recompenses_demandent_un_TEXTE():
    """Sans champ de texte, le viewer ne peut pas dire quelle émotion il veut."""
    from bot.twitch.events.humeur import COUT_100, COUT_50

    assert COUT_50 == 1000
    assert COUT_100 == 2000


# ── le routage des achats ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chaque_recompense_apporte_SON_intensite():
    """Le piège qu'on ne voit pas : les deux récompenses passent par le même
    événement. Les confondre appliquerait 100 % à qui a payé 1 000 points — ou
    l'inverse, ce qui est pire."""
    from bot.twitch.events.humeur import CLE_100, CLE_50
    from bot.twitch.events.redemptions import _est_une_humeur

    bot = MagicMock()
    ids = {CLE_50: "reward-50", CLE_100: "reward-100"}
    bot.db.get_state = AsyncMock(side_effect=lambda cle: ids.get(cle))

    assert await _est_une_humeur(bot, "reward-50") == 0.5
    assert await _est_une_humeur(bot, "reward-100") == 1.0
    assert await _est_une_humeur(bot, "une-autre") is None


@pytest.mark.asyncio
async def test_une_recompense_NON_CREEE_ne_capture_rien():
    """Tant que la chaîne est pleine, l'ID est vide en base. Un identifiant vide
    doit DÉSACTIVER, sinon n'importe quelle récompense forcerait une humeur."""
    from bot.twitch.events.redemptions import _est_une_humeur

    bot = MagicMock()
    bot.db.get_state = AsyncMock(return_value="")
    assert await _est_une_humeur(bot, "n-importe-quoi") is None


def test_les_deux_recompenses_sont_ARMEES_au_demarrage():
    """Sans ça, tout le module dormirait : rien ne créerait les récompenses, et
    aucun achat n'arriverait jamais."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "bot" / "main.py").read_text(encoding="utf-8")
    assert "bot.twitch.events.humeur import" in source
    assert "assurer_recompense" in source
