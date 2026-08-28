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
              "verdict", "refus", "abandon", "recommence", "rattrapage")


def test_le_registre_couvre_tous_les_types_emis():
    registre = registre_duel()
    manquants = [t for t in TYPES_EMIS if not registre.get(t)]
    assert not manquants, f"types sans registre dans apex_duel.md : {manquants}"


def _bot(reponse_llm="Ça commence !"):
    bot = MagicMock()
    bot.twitch_api.send_automatic = AsyncMock(return_value=True)
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
    assert bot.twitch_api.send_automatic.await_args is not None, "rien n'est parti dans le chat"
    return bot.twitch_api.send_automatic.await_args.args[0]


@pytest.mark.asyncio
async def test_l_annonce_part_dans_le_chat():
    """La réplique du modèle est bien ce qui est publié.

    Sur `manche_debut` elle part telle quelle : c'est l'ouverture du duel qui
    porte un suffixe collé par le code (l'avertissement Mixtape), testé à part.
    """
    bot = _bot("Ça repart, manche 2.")
    await DuelAnnonceur(bot, channel="azrael_ttv")(
        Evenement("manche_debut", {"manche": 2, "sur": 3, "manches_jouees": 1,
                                   "total_azrael": 3, "total_viewer": 1,
                                   "total_mesurable": True}))
    assert _envoye(bot) == "Ça repart, manche 2."


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
async def test_une_replique_bavarde_ne_coupe_pas_l_adresse_en_deux():
    """Tronquer APRÈS avoir collé l'URL casserait précisément ce que le code
    dit protéger — et un lien mort rend le duel impossible à démarrer."""
    bot = _bot("Bon. " + "je t'explique posément ce qu'il faut faire. " * 20)
    await DuelAnnonceur(bot, channel="azrael_ttv")(Evenement("compte_introuvable", {
        "viewer": "Bob", "url": URL_APEX_STATUS, "etapes": "ouvre ton profil"}))
    texte = _envoye(bot)
    assert texte.endswith(URL_APEX_STATUS)
    assert len(texte) <= 500          # plafond d'un message Twitch


@pytest.mark.asyncio
async def test_apres_un_redemarrage_le_duelliste_est_encore_nomme():
    """Le nom retenu en mémoire disparaît au rebuild ; le duel repris, lui,
    le porte toujours."""
    from bot.core.apex import duel_runner as mod
    from bot.core.apex.duel import Duel, Etat

    runner = MagicMock()
    runner.duel_en_cours = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
                                etat=Etat.MANCHE)
    mod._active = runner
    try:
        bot = _bot()
        bot.llm.complete = AsyncMock(side_effect=RuntimeError("LLM mort"))
        # Aucun `duel_ouvert` reçu : ce processus vient de démarrer.
        await DuelAnnonceur(bot, channel="azrael_ttv")(Evenement("manche_fin", {
            "manche": 1, "sur": 3, "azrael": 4, "viewer": 2, "mesurable": True,
            "total_azrael": 4, "total_viewer": 2}))
        assert "Bob" in _envoye(bot)
    finally:
        mod._active = None


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


# ── Sous-titres : la légende jouée et le niveau du compte ────────────────────
def _narrateur(bot):
    narrator = MagicMock()
    bot.overlay_narrator = narrator
    return narrator


CAMPS = {"azrael": {"legende": "Fuse", "niveau": 285},
         "viewer": {"legende": "Wraith", "niveau": 120}}


@pytest.mark.asyncio
async def test_le_tableau_porte_la_legende_et_le_niveau_de_chaque_camp():
    """La spec promet « Fuse · niv. 285 » sous chaque joueur. Les deux valeurs
    viennent du profil déjà sondé à chaque relevé."""
    bot = _bot("4 à 2 pour Azraël.")
    narrator = _narrateur(bot)
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("manche_fin", {
        "manche": 1, "sur": 3, "azrael": 4, "viewer": 2, "mesurable": True,
        "total_azrael": 4, "total_viewer": 2, "camps": CAMPS}))

    kwargs = narrator.show_widget.call_args.kwargs
    assert kwargs["left_sub"] == "Fuse · niv. 285"
    assert kwargs["right_sub"] == "Wraith · niv. 120"


@pytest.mark.asyncio
async def test_un_niveau_inconnu_ne_devient_pas_un_niv_0():
    """Une donnée absente n'est jamais un zéro : elle est omise."""
    bot = _bot("et voilà.")
    narrator = _narrateur(bot)
    await DuelAnnonceur(bot, channel="azrael_ttv")(Evenement("verdict", {
        "azrael": 7, "viewer": 4, "gagnant": "azrael",
        "scores": [{"azrael": 7, "viewer": 4}],
        "camps": {"azrael": {"legende": "Fuse"}, "viewer": {"niveau": 120}}}))

    kwargs = narrator.show_widget.call_args.kwargs
    assert kwargs["left_sub"] == "Fuse"
    assert kwargs["right_sub"] == "niv. 120"


# ── Le tableau reparaît au DÉBUT de chaque manche ───────────────────────────
@pytest.mark.asyncio
async def test_le_tableau_reparait_au_debut_d_une_manche():
    """Le widget n'est pas `sticky` et un duel dure une heure : le cycle normal
    des widgets l'efface entre deux manches. Sans réapparition au lancement de
    la suivante, le score n'est à l'écran qu'une poignée de secondes par
    manche."""
    bot = _bot("manche 2, ça repart.")
    narrator = _narrateur(bot)
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("manche_debut", {
        "manche": 2, "sur": 3, "manches_jouees": 1, "total_mesurable": True,
        "total_azrael": 4, "total_viewer": 2, "camps": CAMPS}))

    assert narrator.show_widget.called, "rien n'est allé à l'écran"
    kwargs = narrator.show_widget.call_args.kwargs
    assert kwargs["left_value"] == 4 and kwargs["right_value"] == 2
    assert kwargs["right_name"] == "Bob"


@pytest.mark.asyncio
async def test_le_debut_de_la_premiere_manche_affiche_le_tableau_a_zero():
    """Avant la première manche, « 0 — 0 » ne prétend rien : rien n'a été joué.
    C'est le moment où les deux camps se présentent à l'écran."""
    bot = _bot("c'est parti.")
    narrator = _narrateur(bot)
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("manche_debut", {
        "manche": 1, "sur": 3, "manches_jouees": 0, "total_mesurable": False,
        "total_azrael": 0, "total_viewer": 0, "camps": CAMPS}))

    assert narrator.show_widget.called


# ── Le verdict ne se lit pas comme un score de mi-parcours ──────────────────
@pytest.mark.asyncio
async def test_le_tableau_du_verdict_annonce_qu_il_est_final():
    """Sans ce marqueur, le score final s'affiche exactement comme celui de la
    manche 2 : mêmes barres, même couleur, et rien ne dit au spectateur qu'il
    n'y aura pas de manche suivante."""
    bot = _bot("7 à 4, Azraël l'emporte.")
    narrator = _narrateur(bot)
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("verdict", {
        "azrael": 7, "viewer": 4, "gagnant": "azrael", "abandon": False,
        "scores": [{"azrael": 7, "viewer": 4}], "camps": CAMPS}))

    kwargs = narrator.show_widget.call_args.kwargs
    assert kwargs["duel"] is True
    assert kwargs["final"] is True


@pytest.mark.asyncio
async def test_un_score_de_mi_parcours_ne_se_declare_pas_final():
    """Le duel continue : rien ne doit se refermer à l'écran. C'est ce qui
    permet au verdict, lui, de vouloir dire quelque chose."""
    bot = _bot("4 à 2 pour Azraël.")
    narrator = _narrateur(bot)
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("manche_fin", {
        "manche": 1, "sur": 3, "azrael": 4, "viewer": 2, "mesurable": True,
        "total_azrael": 4, "total_viewer": 2, "camps": CAMPS}))

    kwargs = narrator.show_widget.call_args.kwargs
    assert kwargs["duel"] is True
    assert kwargs["final"] is False


@pytest.mark.asyncio
async def test_pas_de_tableau_au_debut_d_une_manche_si_rien_n_a_ete_compte():
    """Une manche jouée sans qu'aucun kill n'ait pu être compté (Mixtape, API
    muette) : afficher « 0 — 0 » au lancement de la suivante affirmerait un
    score que personne n'a mesuré."""
    bot = _bot("on repart.")
    narrator = _narrateur(bot)
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv")
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    await annonceur(Evenement("manche_debut", {
        "manche": 2, "sur": 3, "manches_jouees": 1, "total_mesurable": False,
        "total_azrael": 0, "total_viewer": 0, "camps": CAMPS}))

    narrator.show_widget.assert_not_called()
    assert _envoye(bot), "le chat, lui, doit toujours annoncer la manche"
