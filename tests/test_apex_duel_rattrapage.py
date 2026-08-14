# tests/test_apex_duel_rattrapage.py
"""Un achat fait pendant que le bot était arrêté ne disparaît plus en silence.

EventSub ne rejoue AUCUN événement manqué. Un viewer qui achetait pendant un
rebuild — la spec dit elle-même qu'ils sont fréquents — perdait sa mise : pas de
duel, pas de remboursement, pas un mot, et une redemption coincée dans la file de
validation du streamer.

Au démarrage, les redemptions encore `UNFULFILLED` de NOTRE récompense sont
relues et remboursées. Pas de duel rétroactif : l'achat peut dater d'hier.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat, Evenement
from bot.core.apex.duel_runner import DuelRunner, armer_le_duel
from bot.twitch.duel_announce import DuelAnnonceur


def _runner(en_attente, *, rendu=True):
    client = MagicMock()
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=rendu)
    api.honorer_redemption = AsyncMock(return_value=True)
    api.recompenses_gerables = AsyncMock(return_value=[{"id": "RW"}])
    api.maj_recompense = AsyncMock(return_value=True)
    api.creer_recompense = AsyncMock(return_value="RW")
    api.redemptions_en_attente = AsyncMock(return_value=en_attente)
    runner = DuelRunner(client=client, db=db, api=api, annoncer=AsyncMock(),
                        azrael_uid="7")
    runner._reward_id = "RW"
    return runner, api


def _evts(runner) -> list:
    return [c.args[0] for c in runner._annoncer.await_args_list]


@pytest.mark.asyncio
async def test_un_achat_manque_est_rembourse_et_annonce():
    runner, api = _runner([{"id": "RD-PERDUE", "user_name": "bob"}])

    assert await runner.rattraper_les_achats_manques() == 1

    api.refund_redemption.assert_awaited_once_with("RW", "RD-PERDUE")
    evt = _evts(runner)[0]
    assert evt.type == "rattrapage"
    assert evt.donnees["viewer"] == "bob"


@pytest.mark.asyncio
async def test_seule_notre_recompense_est_interrogee():
    """Les redemptions des autres récompenses de la chaîne ne nous regardent
    pas — et Twitch les rembourserait tout aussi bien si on les lui donnait."""
    runner, api = _runner([])
    await runner.rattraper_les_achats_manques()
    api.redemptions_en_attente.assert_awaited_once_with("RW")


@pytest.mark.asyncio
@pytest.mark.parametrize("en_attente", [[], None])
async def test_rien_en_attente_ne_rembourse_rien(en_attente):
    """`None` (panne Twitch) comme `[]` (vraiment rien) : dans les deux cas il
    n'y a rien à rembourser, et surtout rien à inventer."""
    runner, api = _runner(en_attente)
    assert await runner.rattraper_les_achats_manques() == 0
    api.refund_redemption.assert_not_awaited()
    assert _evts(runner) == []


@pytest.mark.asyncio
async def test_le_duel_repris_du_rebuild_n_est_PAS_rembourse():
    """Sa redemption est encore `UNFULFILLED` — elle n'est soldée qu'à la fin.
    La rembourser ici solderait un duel en cours d'arbitrage, et le duelliste
    jouerait ses trois manches pour rien."""
    runner, api = _runner([{"id": "RD-EN-COURS", "user_name": "bob"},
                           {"id": "RD-PERDUE", "user_name": "carol"}])
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7",
                redemption_id="RD-EN-COURS")
    duel.etat = Etat.MANCHE
    runner.duel_en_cours = duel

    assert await runner.rattraper_les_achats_manques() == 1

    api.refund_redemption.assert_awaited_once_with("RW", "RD-PERDUE")


@pytest.mark.asyncio
async def test_plusieurs_achats_manques_sont_tous_traites():
    runner, api = _runner([{"id": "RD1", "user_name": "a"},
                           {"id": "RD2", "user_login": "b"},
                           {"id": "RD3"}])

    assert await runner.rattraper_les_achats_manques() == 3

    rendus = {c.args[1] for c in api.refund_redemption.await_args_list}
    assert rendus == {"RD1", "RD2", "RD3"}
    assert [e.type for e in _evts(runner)] == ["rattrapage"] * 3


@pytest.mark.asyncio
async def test_un_remboursement_refuse_est_dit_et_n_arrete_pas_les_suivants():
    runner, api = _runner([{"id": "RD1", "user_name": "a"},
                           {"id": "RD2", "user_name": "b"}], rendu=False)

    assert await runner.rattraper_les_achats_manques() == 2

    assert all(e.donnees.get("remboursement_echoue") for e in _evts(runner))


@pytest.mark.asyncio
async def test_sans_recompense_connue_on_ne_demande_rien():
    """Sans identifiant de récompense, Twitch refuserait la requête — et rien
    ne dit que les redemptions qu'on lirait seraient les nôtres."""
    runner, api = _runner([{"id": "RD1"}])
    runner._reward_id = ""
    assert await runner.rattraper_les_achats_manques() == 0
    api.redemptions_en_attente.assert_not_awaited()


# ── Le démarrage ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_le_rattrapage_a_lieu_au_demarrage_apres_la_recompense():
    runner, api = _runner([{"id": "RD-PERDUE", "user_name": "bob"}])
    runner._reward_id = ""
    runner._db.get_state = AsyncMock(return_value="RW")

    await armer_le_duel(runner, titre="Duel", cout=10000, prompt="ton UID")

    api.redemptions_en_attente.assert_awaited_once_with("RW")
    api.refund_redemption.assert_awaited_once_with("RW", "RD-PERDUE")


@pytest.mark.asyncio
async def test_un_rattrapage_en_erreur_ne_bloque_jamais_le_demarrage():
    """Un bot qui tourne sans rattrapage vaut mieux qu'un bot qui refuse de
    démarrer — même règle que le canari de boot."""
    runner, api = _runner([])
    api.redemptions_en_attente = AsyncMock(side_effect=RuntimeError("Twitch down"))

    rid = await armer_le_duel(runner, titre="Duel", cout=10000, prompt="ton UID")

    assert rid == "RW"
    from bot.core.apex.duel_runner import current_duel
    current_duel()          # `activate()` a bien eu lieu malgré l'erreur


# ── Ce que le viewer ENTEND ─────────────────────────────────────────────────
def _bot():
    bot = MagicMock()
    bot.twitch_api.send_message = AsyncMock(return_value=True)
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


@pytest.mark.asyncio
async def test_l_annonce_nomme_l_acheteur_et_l_indisponibilite():
    bot = _bot()
    await DuelAnnonceur(bot, channel="azrael_ttv")(
        Evenement("rattrapage", {"viewer": "carol"}))
    texte = bot.twitch_api.send_message.await_args.kwargs["text"].lower()
    assert "carol" in texte
    assert "rendus" in texte
    assert "hors ligne" in texte, f"la raison doit être dite : {texte!r}"


@pytest.mark.asyncio
async def test_l_annonce_ne_parle_pas_du_duelliste_precedent():
    """L'annonceur retient le nom du duelliste en cours pour les événements qui
    ne le portent pas. Un rattrapage ne suit AUCUN duel : lui appliquer ce
    repli attribuerait l'achat à quelqu'un d'autre."""
    bot = _bot()
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("rattrapage", {"viewer": ""}))
    texte = bot.twitch_api.send_message.await_args.kwargs["text"].lower()
    assert "bob" not in texte, f"personne ne dit que c'était Bob : {texte!r}"
