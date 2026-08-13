"""Les annonces du duel : le registre `apex_duel.md`, et une parole qui part.

Le duel se joue devant des spectateurs qui ont payé des points de chaîne :
chaque étape doit s'entendre dans le chat. Un appel LLM raté ne doit donc pas
avaler l'annonce — le texte factuel part alors tel quel.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Evenement
from bot.core.apex.duel_runner import URL_APEX_STATUS
from bot.core.llm import FALLBACK_RESPONSE
from bot.twitch.duel_announce import DuelAnnonceur, registre_duel

# Tous les types que `duel.py` et `duel_runner.py` savent émettre. Un type sans
# section serait annoncé sans registre de ton — donc au hasard.
TYPES_EMIS = ("duel_ouvert", "compte_introuvable", "manche_debut", "manche_fin",
              "verdict", "refus", "abandon", "recommence")


def test_le_registre_couvre_tous_les_types_emis():
    registre = registre_duel()
    manquants = [t for t in TYPES_EMIS if not registre.get(t)]
    assert not manquants, f"types sans registre dans apex_duel.md : {manquants}"


def _bot(reponse_llm="Ça commence !"):
    bot = MagicMock()
    bot.twitch_api.send_message = AsyncMock(return_value=True)
    bot.llm.complete = AsyncMock(return_value=reponse_llm)
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.persona.build_prompt_block = MagicMock(return_value="persona")
    bot.emotion.get_state = MagicMock(return_value={"joy": 0.3})
    bot._channel_ids = {}
    bot._stream_info = {"live": True, "category": "Apex Legends",
                        "title": "duel", "viewers": 12}
    bot.overlay_narrator = None
    bot.discord_bot = None
    return bot


def _envoye(bot) -> str:
    assert bot.twitch_api.send_message.await_args is not None, "rien n'est parti dans le chat"
    return bot.twitch_api.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_l_annonce_part_dans_le_chat():
    bot = _bot("Bob débarque, ça va saigner.")
    await DuelAnnonceur(bot, channel="azrael_ttv")(
        Evenement("duel_ouvert", {"viewer": "Bob"}))
    assert _envoye(bot) == "Bob débarque, ça va saigner."


@pytest.mark.asyncio
async def test_un_LLM_en_panne_n_avale_pas_l_annonce():
    """Le viewer a payé : l'étape s'annonce, avec ou sans habillage."""
    bot = _bot()
    bot.llm.complete = AsyncMock(side_effect=RuntimeError("LLM mort"))
    await DuelAnnonceur(bot, channel="azrael_ttv")(
        Evenement("refus", {"motif": "un duel est déjà en cours"}))
    assert "déjà en cours" in _envoye(bot)


@pytest.mark.asyncio
async def test_l_adresse_du_site_est_collee_par_le_code():
    """Un modèle qui reformule une adresse la casse, et le duel devient
    impossible à démarrer."""
    bot = _bot("File chercher ton numéro de profil.")
    await DuelAnnonceur(bot, channel="azrael_ttv")(Evenement("compte_introuvable", {
        "viewer": "Bob", "url": URL_APEX_STATUS, "etapes": "ouvre ton profil"}))
    assert URL_APEX_STATUS in _envoye(bot)


@pytest.mark.asyncio
async def test_une_manche_non_mesurable_n_est_pas_un_zero():
    """Les deltas bruts voyagent dans l'événement même quand rien n'est
    mesurable : les annoncer donnerait « 3 à None, total 0-0 »."""
    bot = _bot()
    bot.llm.complete = AsyncMock(side_effect=RuntimeError("LLM mort"))
    await DuelAnnonceur(bot, channel="azrael_ttv")(Evenement("manche_fin", {
        "manche": 1, "sur": 3, "azrael": 3, "viewer": None, "mesurable": False,
        "total_azrael": 0, "total_viewer": 0}))
    texte = _envoye(bot)
    assert "None" not in texte
    assert "compt" in texte.lower()


@pytest.mark.asyncio
async def test_une_excuse_technique_ne_remplace_pas_le_score():
    """`complete()` ne lève pas : sur panne totale il rend « problème
    technique ». Publier ça à la place du score perdrait l'information."""
    bot = _bot(FALLBACK_RESPONSE)
    await DuelAnnonceur(bot, channel="azrael_ttv")(Evenement("manche_fin", {
        "manche": 1, "sur": 3, "azrael": 4, "viewer": 2, "mesurable": True,
        "total_azrael": 4, "total_viewer": 2}))
    texte = _envoye(bot)
    assert "4" in texte and FALLBACK_RESPONSE not in texte


@pytest.mark.asyncio
async def test_le_nom_du_duelliste_n_est_pas_son_score():
    """`donnees["viewer"]` vaut un PSEUDO à l'ouverture et un nombre de kills
    en fin de manche : les confondre annonçait « 2 » comme duelliste."""
    bot = _bot()
    bot.llm.complete = AsyncMock(side_effect=RuntimeError("LLM mort"))
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("manche_fin", {
        "manche": 1, "sur": 3, "azrael": 4, "viewer": 2, "mesurable": True,
        "total_azrael": 4, "total_viewer": 2}))
    assert "Bob" in _envoye(bot)


@pytest.mark.asyncio
async def test_le_score_d_une_manche_mesuree_est_donne_au_modele():
    bot = _bot("4 à 2 pour Azraël.")
    await DuelAnnonceur(bot, channel="azrael_ttv")(Evenement("manche_fin", {
        "manche": 1, "sur": 3, "azrael": 4, "viewer": 2, "mesurable": True,
        "total_azrael": 4, "total_viewer": 2}))
    donne = bot.llm.complete.await_args.args[1][0]["content"]
    assert "4" in donne and "2" in donne


@pytest.mark.asyncio
async def test_le_tableau_va_a_l_ecran_a_la_fin_d_une_manche():
    bot = _bot("4 à 2 pour Azraël.")
    narrator = MagicMock()
    bot.overlay_narrator = narrator
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("manche_fin", {
        "manche": 1, "sur": 3, "azrael": 4, "viewer": 2, "mesurable": True,
        "total_azrael": 4, "total_viewer": 2}))

    widget, kwargs = narrator.show_widget.call_args.args[0], narrator.show_widget.call_args.kwargs
    assert widget == "versus"
    assert kwargs["left_value"] == 4 and kwargs["right_value"] == 2
    assert kwargs["right_name"] == "Bob"


@pytest.mark.asyncio
async def test_un_overlay_en_panne_n_empeche_pas_le_chat():
    bot = _bot("4 à 2 pour Azraël.")
    narrator = MagicMock()
    narrator.show_widget = MagicMock(side_effect=RuntimeError("overlay mort"))
    bot.overlay_narrator = narrator
    await DuelAnnonceur(bot, channel="azrael_ttv")(Evenement("verdict", {
        "azrael": 7, "viewer": 4, "gagnant": "azrael",
        "scores": [{"azrael": 7, "viewer": 4}]}))
    assert _envoye(bot)
