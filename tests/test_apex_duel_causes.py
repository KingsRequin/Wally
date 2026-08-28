# tests/test_apex_duel_causes.py
"""Un compte non validé : dire la VRAIE raison, et laisser une seconde chance.

Trois causes bien distinctes finissaient dans le même message — « aucun tracker
de kills n'est épinglé sur ce compte » — et, pour une saisie numérique, dans un
refus immédiat sans seconde chance :

  · le compte n'a pas été trouvé (identifiant mal recopié, autre plateforme) ;
  · le compte est là, mais sans tracker de kills épinglé ;
  · l'API n'a pas répondu, et on ne sait donc rien du compte.

Le viewer s'entendait affirmer devant le stream une chose fausse sur son propre
compte. Une capacité sans donnée se répond par un négatif honnête, jamais par une
affirmation commode.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Etat, Evenement
from bot.core.apex.duel_runner import (CAUSE_API, CAUSE_INTROUVABLE,
                                       CAUSE_SANS_TRACKER, CAUSE_SOI_MEME,
                                       DuelRunner)
from bot.twitch.duel_announce import DuelAnnonceur, registre_duel

UID = "1012242925358"
PROFIL_OK = {"global": {"uid": UID}, "realtime": {},
             "total": {"k": {"name": "BR Kills", "value": 10}}}
SANS_TRACKER = {"global": {"uid": UID}, "realtime": {},
                "total": {"d": {"name": "BR Damage", "value": 5}}}
INTROUVABLE = {"Error": "Player not found."}
PANNE_API = "Apex API error: HTTP 500"
AUTRE_ERREUR = {"Error": "Rate limit exceeded, please slow down."}


def _runner(reponse):
    client = MagicMock()
    client.get = AsyncMock(return_value=reponse)
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    api.honorer_redemption = AsyncMock(return_value=True)
    return DuelRunner(client=client, db=db, api=api, annoncer=AsyncMock(),
                      azrael_uid="7", plateforme="PC"), api


def _dernier(runner) -> Evenement:
    return runner._annoncer.await_args.args[0]


# ── La cause, à l'ouverture ─────────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("reponse, attendue", [
    (INTROUVABLE, CAUSE_INTROUVABLE),
    (PANNE_API, CAUSE_API),
    (AUTRE_ERREUR, CAUSE_API),
])
async def test_un_identifiant_numerique_non_resolu_explique_la_vraie_cause(
        reponse, attendue):
    runner, api = _runner(reponse)

    await runner.ouvrir(acheteur="bob", saisie=UID,
                        reward_id="rw", redemption_id="rd")

    assert runner.duel_en_cours.etat is Etat.RESOLUTION, (
        "un identifiant qui ne résout pas ne se refuse plus sèchement")
    api.refund_redemption.assert_not_awaited()
    evt = _dernier(runner)
    assert evt.type == "compte_introuvable"
    assert evt.donnees["cause"] == attendue


@pytest.mark.asyncio
async def test_une_erreur_de_quota_n_est_pas_un_compte_inexistant():
    """`{"Error": …}` ne dit pas toujours « ce compte n'existe pas » : seule la
    mention « not found » parle du compte. Le reste parle de l'API."""
    runner, _ = _runner(AUTRE_ERREUR)
    await runner.ouvrir(acheteur="bob", saisie=UID,
                        reward_id="rw", redemption_id="rd")
    assert _dernier(runner).donnees["cause"] == CAUSE_API


@pytest.mark.asyncio
async def test_un_compte_trouve_sans_tracker_reste_un_refus_rembourse():
    """§8 de la spec, inchangé — et c'est le SEUL cas où ce message se dit."""
    runner, api = _runner(SANS_TRACKER)

    await runner.ouvrir(acheteur="bob", saisie=UID,
                        reward_id="rw", redemption_id="rd")

    api.refund_redemption.assert_awaited_once()
    evt = _dernier(runner)
    assert evt.type == "refus"
    assert "tracker" in evt.donnees["motif"]


# ── La cause, sur les essais suivants ───────────────────────────────────────
@pytest.mark.asyncio
async def test_un_compte_sans_tracker_donne_en_reponse_est_dit_comme_tel():
    """Le duelliste peut encore épingler un tracker et répondre : le lui dire
    est la seule chose qui débloque la situation."""
    runner, _ = _runner(INTROUVABLE)
    await runner.ouvrir(acheteur="bob", saisie="un pseudo",
                        reward_id="rw", redemption_id="rd")
    runner._client.get = AsyncMock(return_value=SANS_TRACKER)

    assert await runner.repondre_resolution("bob", UID) is True

    assert runner.duel_en_cours.etat is Etat.RESOLUTION
    assert _dernier(runner).donnees["cause"] == CAUSE_SANS_TRACKER


@pytest.mark.asyncio
async def test_le_compte_du_streamer_donne_en_reponse_est_dit_comme_tel():
    """Ce chemin annonçait « compte introuvable » — faux : le compte existe,
    c'est celui d'Azraël."""
    runner, _ = _runner(INTROUVABLE)
    await runner.ouvrir(acheteur="bob", saisie="un pseudo",
                        reward_id="rw", redemption_id="rd")

    assert await runner.repondre_resolution("bob", "7") is True

    assert _dernier(runner).donnees["cause"] == CAUSE_SOI_MEME


@pytest.mark.asyncio
async def test_un_compte_valide_donne_en_reponse_lance_toujours_le_duel():
    """Le contre-exemple : la voie nominale ne doit pas être emportée par les
    branches de cause."""
    runner, _ = _runner(INTROUVABLE)
    await runner.ouvrir(acheteur="bob", saisie="un pseudo",
                        reward_id="rw", redemption_id="rd")
    runner._client.get = AsyncMock(return_value=PROFIL_OK)

    await runner.repondre_resolution("bob", UID)

    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    assert runner.duel_en_cours.viewer_uid == UID


# ── Ce que le viewer ENTEND ─────────────────────────────────────────────────
def _bot():
    bot = MagicMock()
    bot.twitch_api.send_automatic = AsyncMock(return_value=True)
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


async def _annonce(cause: str) -> str:
    bot = _bot()
    await DuelAnnonceur(bot, channel="azrael_ttv")(Evenement(
        "compte_introuvable", {"viewer": "Bob", "url": "https://x.test",
                               "etapes": "les étapes exactes", "cause": cause}))
    return bot.twitch_api.send_automatic.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_une_api_muette_ne_fait_pas_dire_qu_il_manque_un_tracker():
    texte = await _annonce(CAUSE_API)
    assert "api" in texte
    assert "tracker" not in texte, f"rien ne prouve ça : {texte!r}"
    assert "n'a pas été retrouvé" not in texte, f"rien ne prouve ça non plus : {texte!r}"


@pytest.mark.asyncio
async def test_un_compte_introuvable_ne_parle_pas_de_tracker():
    texte = await _annonce(CAUSE_INTROUVABLE)
    assert "tracker" not in texte, f"on n'a même pas vu le compte : {texte!r}"


@pytest.mark.asyncio
async def test_le_message_du_tracker_ne_se_dit_que_quand_c_est_vrai():
    texte = await _annonce(CAUSE_SANS_TRACKER)
    assert "tracker" in texte
    assert "trouvé" in texte, (
        f"le compte EXISTE, c'est tout l'intérêt de ce message : {texte!r}")


def test_le_registre_distingue_les_causes():
    """Sans directive, la persona choisirait la formulation la plus commode —
    et c'est celle qui affirme le plus."""
    texte = registre_duel()["compte_introuvable"].lower()
    for mot in ("introuvable", "tracker", "api"):
        assert mot in texte, f"le registre ne dit rien de la cause « {mot} »"
