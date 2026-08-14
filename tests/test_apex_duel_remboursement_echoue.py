# tests/test_apex_duel_remboursement_echoue.py
"""Un remboursement refusé par Twitch ne s'annonce pas comme un succès.

`refund_redemption()` vérifie le CORPS de la réponse Helix — un 200 ne prouve
rien ici, le projet l'a déjà payé avec `is_sent` — et rend un booléen. Les cinq
appelants l'ignoraient : les annonces affirmaient « tes points t'ont été rendus »
même sur un 403 (récompense créée hors de notre application), un scope perdu ou
une redemption déjà soldée. Le viewer s'entendait mentir devant le stream, et la
seule trace était une ligne de log que personne ne lit en direct.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat, Evenement
from bot.core.apex.duel_runner import DuelRunner
from bot.twitch.duel_announce import DuelAnnonceur, registre_duel


def _runner(rendu: bool = False):
    """Un runner dont Twitch REFUSE le remboursement."""
    client = MagicMock()
    client.get = AsyncMock(return_value={})
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=rendu)
    api.honorer_redemption = AsyncMock(return_value=True)
    runner = DuelRunner(client=client, db=db, api=api, annoncer=AsyncMock(),
                        azrael_uid="7", manches=1)
    runner._reward_id = "rw"
    return runner, api


def _evts(runner) -> list:
    return [c.args[0] for c in runner._annoncer.await_args_list]


# ── L'échec remonte jusqu'à l'événement annoncé ──────────────────────────────
@pytest.mark.asyncio
async def test_un_refus_dont_le_remboursement_echoue_ne_promet_pas_les_points():
    """Le compte d'Azraël donné en saisie : refus immédiat, remboursement
    tenté… et refusé. L'annonce doit le savoir."""
    runner, _ = _runner()

    await runner.ouvrir(acheteur="bob", saisie="7",
                        reward_id="rw", redemption_id="rd")

    refus = [e for e in _evts(runner) if e.type == "refus"]
    assert refus, "un refus s'annonce toujours"
    assert refus[0].donnees.get("remboursement_echoue") is True


@pytest.mark.asyncio
async def test_un_refus_rembourse_pour_de_vrai_ne_porte_aucune_alerte():
    """Le cas nominal ne doit pas se mettre à inquiéter tout le monde."""
    runner, _ = _runner(rendu=True)

    await runner.ouvrir(acheteur="bob", saisie="7",
                        reward_id="rw", redemption_id="rd")

    refus = [e for e in _evts(runner) if e.type == "refus"][0]
    assert "remboursement_echoue" not in refus.donnees


@pytest.mark.asyncio
async def test_un_verdict_qui_rembourse_dit_la_verite_si_twitch_refuse():
    """Le duelliste gagne : ses points lui reviennent — sauf que non. Sans
    cette remontée, il entend « tu récupères tes points » et les attend."""
    runner, api = _runner()
    duel = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
                redemption_id="rd", manches=1)
    duel.etat = Etat.MANCHE
    duel._base_azrael = {"career_kills": 0}
    duel._base_viewer = {"career_kills": 0}
    runner.duel_en_cours = duel

    async def _profils(_endpoint, params=None, **_kw):
        n = 2 if str((params or {}).get("uid")) == "7" else 5
        return {"realtime": {"isInGame": 0},
                "total": {"career_kills": {"name": "BR Kills", "value": n}}}

    runner._client.get = AsyncMock(side_effect=_profils)
    # Retour au lobby confirmé (2 relevés), puis la marge laissée aux compteurs.
    for t in (100, 102, 112):
        await runner.tick(maintenant=t)

    assert duel.etat is Etat.VERDICT
    api.refund_redemption.assert_awaited_once()
    verdict = [e for e in _evts(runner) if e.type == "verdict"][0]
    assert verdict.donnees["rembourser"] is True
    assert verdict.donnees.get("remboursement_echoue") is True


@pytest.mark.asyncio
async def test_l_echec_ne_casse_ni_le_nettoyage_ni_la_persistance():
    """L'ordre reste intouchable : remboursement → nettoyage → persistance →
    annonce. Un remboursement refusé ne doit pas laisser un duel fantôme
    derrière lui, sinon tous les acheteurs suivants sont refusés."""
    runner, _ = _runner()
    duel = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
                redemption_id="rd", manches=3)
    duel.etat = Etat.ATTENTE_SQUAD
    duel._t_attente = 0
    runner.duel_en_cours = duel
    runner._client.get = AsyncMock(return_value="Apex API error: timeout")

    await runner.tick(maintenant=16 * 60)

    assert runner.duel_en_cours is None
    runner._db.set_state.assert_awaited_with("apex:duel", "")


@pytest.mark.asyncio
async def test_la_troisieme_tentative_ratee_dit_aussi_l_echec():
    """Le duelliste n'a jamais donné de compte lisible : on rembourse, et
    Twitch refuse. Ce chemin-là ignorait le retour lui aussi."""
    runner, _ = _runner()
    await runner.ouvrir(acheteur="bob", saisie="un pseudo introuvable",
                        reward_id="rw", redemption_id="rd")
    for _ in range(3):
        await runner.repondre_resolution("bob", "toujours pas un compte")

    abandons = [e for e in _evts(runner) if e.type == "abandon"]
    assert abandons, "un abandon s'annonce toujours"
    assert abandons[-1].donnees.get("remboursement_echoue") is True


@pytest.mark.asyncio
async def test_annuler_rend_faux_quand_les_points_ne_reviennent_pas():
    runner, _ = _runner()
    duel = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
                redemption_id="rd")
    duel.etat = Etat.ATTENTE_SQUAD
    runner.duel_en_cours = duel

    assert await runner.annuler("le streamer a annulé") is False
    abandon = [e for e in _evts(runner) if e.type == "abandon"][0]
    assert abandon.donnees.get("remboursement_echoue") is True


# ── Ce que le viewer ENTEND ─────────────────────────────────────────────────
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


async def _annonce(evt: Evenement) -> str:
    bot = _bot()
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(evt)
    return bot.twitch_api.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("evt", [
    Evenement("refus", {"motif": "un duel est déjà en cours",
                        "remboursement_echoue": True}),
    Evenement("abandon", {"motif": "le stream s'est coupé", "rembourser": True,
                          "remboursement_echoue": True}),
    Evenement("verdict", {"azrael": 2, "viewer": 5, "gagnant": "viewer",
                          "rembourser": True, "abandon": False, "scores": [],
                          "remboursement_echoue": True}),
])
async def test_l_annonce_ne_pretend_jamais_que_les_points_sont_revenus(evt):
    texte = (await _annonce(evt)).lower()
    assert "échoué" in texte, f"l'échec doit être dit : {texte!r}"
    assert "pas été rendus" in texte, f"et dit sans ambiguïté : {texte!r}"
    assert "streamer" in texte, (
        f"le viewer doit savoir à qui s'adresser : {texte!r}")


@pytest.mark.asyncio
async def test_l_annonce_nominale_annonce_bien_le_remboursement():
    """Le contre-exemple : sans lui, un message qui ne parlerait plus jamais de
    remboursement passerait le test ci-dessus."""
    texte = (await _annonce(
        Evenement("refus", {"motif": "un duel est déjà en cours"}))).lower()
    assert "ont été rendus" in texte
    assert "échoué" not in texte


def test_le_registre_sait_habiller_un_remboursement_rate():
    """Le ton s'édite sans rebuild, mais la persona doit savoir que ce cas
    existe : sans directive, elle habillerait l'échec d'un « tu récupères tes
    points » de politesse."""
    registre = registre_duel()
    for section in ("refus", "abandon", "verdict"):
        texte = registre[section].lower()
        assert "échoué" in texte, f"section {section} muette sur l'échec"


# ── Le chat : annuler ne ment pas au modérateur ─────────────────────────────
@pytest.mark.asyncio
async def test_l_outil_du_chat_ne_dit_pas_ok_quand_les_points_restent_dus():
    from bot.twitch.handlers import run_duel_tool

    bot = MagicMock()
    bot.duel_runner = MagicMock()
    bot.duel_runner.duel_en_cours = Duel(viewer_nom="Bob", viewer_uid="42",
                                         azrael_uid="7")
    bot.duel_runner.annuler = AsyncMock(return_value=False)

    reponse = json.loads(await run_duel_tool(
        bot, {"action": "annuler"},
        auteur={"badges": [{"set_id": "moderator"}]}))

    assert reponse["status"] != "ok"
    assert "main" in reponse["message"].lower(), (
        "le modérateur doit savoir qu'il reste quelque chose à faire")
