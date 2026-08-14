# tests/test_apex_duel_points.py
"""Le sort des points : gagner rembourse, perdre consomme.

Règle du propriétaire (2026-08-14) : le duelliste qui gagne récupère ses points
de chaîne — c'est ça, la récompense — et celui qui perd les a dépensés. Une
égalité rembourse : il n'a pas perdu, et le doute lui profite.

Le pendant du remboursement n'est pas décoratif : une redemption non remboursée
doit être marquée HONORÉE, faute de quoi elle reste dans la file de validation
du streamer et s'y empile duel après duel.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat, Releve
from bot.core.apex.duel_runner import DuelRunner
from bot.twitch.duel_announce import DuelAnnonceur


def kills(n: int) -> dict:
    return {"career_kills": n}


def _duel(manches: int = 1) -> Duel:
    d = Duel(viewer_nom="Bob", viewer_uid="42", viewer_id="105904256",
             azrael_uid="7", redemption_id="rd", manches=manches)
    d.etat = Etat.ATTENTE_SQUAD
    return d


def _manche(d: Duel, t: float, azrael: int, viewer: int) -> list:
    """Une manche complète, jouée puis close au lobby."""
    d.avancer(Releve(t=t, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=kills(0), kills_viewer=kills(0)))
    d.avancer(Releve(t=t + 2, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=kills(0), kills_viewer=kills(0)))
    d.avancer(Releve(t=t + 480, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=kills(azrael), kills_viewer=kills(viewer)))
    return d.avancer(Releve(t=t + 482, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=kills(azrael), kills_viewer=kills(viewer)))


def _verdict(evts) -> dict:
    return [e for e in evts if e.type == "verdict"][0].donnees


# ── La règle, au niveau de la machine à états ────────────────────────────────
def test_le_duelliste_qui_gagne_recupere_ses_points():
    d = _duel()
    verdict = _verdict(_manche(d, 0, azrael=2, viewer=5))
    assert verdict["gagnant"] == "viewer"
    assert verdict["rembourser"] is True


def test_le_duelliste_qui_perd_a_depense_ses_points():
    d = _duel()
    verdict = _verdict(_manche(d, 0, azrael=6, viewer=1))
    assert verdict["gagnant"] == "azrael"
    assert verdict["rembourser"] is False


def test_une_egalite_rembourse_le_duelliste():
    """Il n'a pas perdu : le doute lui profite."""
    d = _duel()
    verdict = _verdict(_manche(d, 0, azrael=3, viewer=3))
    assert verdict["gagnant"] is None
    assert verdict["rembourser"] is True


# ── Ce qui part réellement vers Twitch ───────────────────────────────────────
def _runner():
    client = MagicMock()
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    api.honorer_redemption = AsyncMock(return_value=True)
    runner = DuelRunner(client=client, db=db, api=api, annoncer=AsyncMock(),
                        azrael_uid="7", manches=1)
    runner._reward_id = "rw"
    return runner, api


def _profils(azrael: int, viewer: int):
    """Deux comptes qui rentrent au lobby avec ces compteurs."""
    async def _get(_endpoint, params=None, **_kw):
        n = azrael if str((params or {}).get("uid")) == "7" else viewer
        return {"realtime": {"isInGame": 0},
                "total": {"career_kills": {"name": "BR Kills", "value": n}}}
    return AsyncMock(side_effect=_get)


async def _clore(runner, azrael: int, viewer: int):
    """Un duel d'une manche, mené jusqu'au verdict."""
    duel = Duel(viewer_nom="Bob", viewer_uid="42", viewer_id="105904256",
                azrael_uid="7", redemption_id="rd", manches=1)
    duel.etat = Etat.MANCHE
    duel._base_azrael = {"career_kills": 0}
    duel._base_viewer = {"career_kills": 0}
    runner.duel_en_cours = duel
    runner._client.get = _profils(azrael, viewer)
    await runner.tick(maintenant=100)
    await runner.tick(maintenant=102)
    assert duel.etat is Etat.VERDICT, "le duel doit être allé jusqu'au bout"


@pytest.mark.asyncio
async def test_la_victoire_du_duelliste_rend_les_points():
    runner, api = _runner()
    await _clore(runner, azrael=2, viewer=5)
    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    api.honorer_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_la_defaite_du_duelliste_honore_la_redemption():
    """Ne pas rembourser ne veut pas dire ne rien faire : une redemption
    laissée en attente s'accumule dans la file de validation du streamer."""
    runner, api = _runner()
    await _clore(runner, azrael=6, viewer=1)
    api.honorer_redemption.assert_awaited_once_with("rw", "rd")
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_l_egalite_rend_les_points():
    runner, api = _runner()
    await _clore(runner, azrael=3, viewer=3)
    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    api.honorer_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_duel_ne_recoit_jamais_deux_ordres_contradictoires():
    """Le duelliste qui ne revient pas après une manche comptée déclenche un
    abandon PUIS un verdict. Deux ordres sur la même redemption feraient
    perdre le second : une redemption honorée ne redevient jamais annulée."""
    runner, api = _runner()
    duel = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
                redemption_id="rd", manches=3)
    duel.etat = Etat.ENTRE_MANCHES
    duel.scores = [{"azrael": 6, "viewer": 1}]
    duel._t_attente = 0
    runner.duel_en_cours = duel
    runner._client.get = AsyncMock(return_value="Apex API error: timeout")

    await runner.tick(maintenant=16 * 60)

    assert duel.etat is Etat.VERDICT
    total = (api.refund_redemption.await_count + api.honorer_redemption.await_count)
    assert total == 1, "un seul ordre doit partir vers Twitch"
    api.honorer_redemption.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_abandon_sans_rien_de_mesurable_rend_toujours_les_points():
    """Chemin inchangé : sans mesure, il n'y a rien à arbitrer — on rembourse,
    et on n'honore surtout pas une redemption pour un duel qui n'a pas eu
    lieu."""
    runner, api = _runner()
    duel = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
                redemption_id="rd", manches=3)
    duel.etat = Etat.ATTENTE_SQUAD
    duel._t_attente = 0
    runner.duel_en_cours = duel
    runner._client.get = AsyncMock(return_value="Apex API error: timeout")

    await runner.tick(maintenant=16 * 60)

    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    api.honorer_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_manche_en_cours_ne_solde_rien():
    """Les points sont encore en jeu : ni rendus, ni consommés."""
    runner, api = _runner()
    duel = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
                redemption_id="rd", manches=3)
    duel.etat = Etat.ATTENTE_SQUAD
    runner.duel_en_cours = duel
    runner._client.get = AsyncMock(side_effect=lambda *a, **k: {
        "realtime": {"isInGame": 1},
        "total": {"career_kills": {"name": "BR Kills", "value": 3}}})

    await runner.tick(maintenant=100)
    await runner.tick(maintenant=102)

    assert duel.etat is Etat.MANCHE
    api.refund_redemption.assert_not_awaited()
    api.honorer_redemption.assert_not_awaited()


# ── Ce que le duelliste ENTEND ──────────────────────────────────────────────
def _bot():
    bot = MagicMock()
    bot.twitch_api.send_message = AsyncMock(return_value=True)
    # LLM coupé : c'est le texte FACTUEL qui part, celui que le code garantit.
    bot.llm.complete = AsyncMock(side_effect=RuntimeError("LLM mort"))
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.persona.build_prompt_block = MagicMock(return_value="persona")
    bot.emotion.get_state = MagicMock(return_value={"joy": 0.3})
    bot._channel_ids = {}
    bot._stream_info = {"live": True, "category": "Apex Legends",
                        "title": "duel", "viewers": 12}
    bot.overlay_narrator = None
    bot.discord_bot = None
    return bot


async def _annonce_du_verdict(rembourser: bool, gagnant: str | None) -> str:
    from bot.core.apex.duel import Evenement
    bot = _bot()
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("verdict", {
        "azrael": 6, "viewer": 1, "gagnant": gagnant, "rembourser": rembourser,
        "scores": [{"azrael": 6, "viewer": 1}]}))
    return bot.twitch_api.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_le_verdict_annonce_que_les_points_sont_rendus():
    texte = await _annonce_du_verdict(rembourser=True, gagnant="viewer")
    assert "rendus" in texte.lower()


@pytest.mark.asyncio
async def test_le_verdict_annonce_que_les_points_sont_consommes():
    """Ne rien dire laisserait le duelliste attendre un remboursement qui ne
    viendra pas."""
    texte = await _annonce_du_verdict(rembourser=False, gagnant="azrael")
    assert "consomm" in texte.lower()
    assert "rendus" not in texte.lower()


@pytest.mark.asyncio
async def test_le_registre_dit_au_modele_quoi_faire_des_points():
    """Les chiffres et l'issue ne sont pas laissés au modèle ; le ton, si."""
    from bot.twitch.duel_announce import registre_duel
    verdict = registre_duel()["verdict"].lower()
    assert "point" in verdict
