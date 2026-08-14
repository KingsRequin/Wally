# tests/test_emotes_twitch.py
"""Wally parle le registre du chat où il écrit.

Le seul retour spectateur du live du 2026-08-13 :

    20:14:29  Wally : « C'est parti, mème à l'écran ! 😄 »
    20:14:47  clakernojutsu : « Il m'agace avec ses "😄" LUL »

Il reproche un emoji Unicode EN ÉCRIVANT une emote Twitch. Ce n'est pas
l'expressivité qui gêne, c'est le registre.

Ces tests portent sur le COMPORTEMENT : ce qui peut être proposé, ce qui ne
peut jamais l'être, et ce qui se passe quand l'API se tait. Jamais sur la façon
dont le bloc est rédigé.
"""
import json

import pytest

import bot.core.twitch_emotes as em
from bot.intelligence.prompts import PromptBuilder

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0,
                  "curiosity": 0.0, "boredom": 0.0}


class _FauxAPI:
    """Une API Twitch réduite à ses deux réponses d'emotes."""

    def __init__(self, globales, chaine):
        self._globales, self._chaine = globales, chaine

    async def get_global_emotes(self):
        return self._globales

    async def get_entitled_channel_emotes(self):
        return self._chaine


def _prompt(situation):
    return PromptBuilder().build_system_prompt(
        emotion_state=_EMOTIONS_FLAT, situation=situation
    )


# ── ce qu'il a le droit d'écrire ──────────────────────────────────────────

def test_une_emote_de_chaine_reservee_aux_abonnes_ne_lui_est_jamais_proposee():
    """26 des 27 emotes de la chaîne sont réservées aux abonnés et le bot ne
    l'est pas : écrire « azrael74HYPE » l'afficherait en toutes lettres."""
    registre = em.active_emote_registry()
    registre.set_verified(["LUL"])
    registre.note_chat("azrael74HYPE azrael74HYPE LUL")
    assert "azrael74HYPE" not in registre.render()
    assert "LUL" in registre.render()


def test_une_emote_dune_autre_chaine_ne_lui_est_jamais_proposee():
    """Le chat croise des `sharpy19*` et des `juastr*` : elles existent, elles
    ne sont pas les siennes."""
    registre = em.active_emote_registry()
    registre.set_verified(["LUL"])
    registre.note_chat("sharpy19Smilepepega juastrYIPEEE")
    assert registre.top() == []


@pytest.mark.asyncio
async def test_les_emotes_de_chaine_entrent_des_que_le_bot_y_a_droit():
    """Le jour où Azraël offre un abonnement au bot, elles s'ouvrent seules —
    sans qu'on ait à toucher une ligne de code."""
    await em.refresh_from_api(_FauxAPI(["LUL"], ["azrael74HYPE"]))
    registre = em.active_emote_registry()
    registre.note_chat("azrael74HYPE")
    assert "azrael74HYPE" in registre.top()


@pytest.mark.asyncio
async def test_la_reserve_de_chaine_fonctionne_aussi_depuis_lapi_reelle():
    """`test_les_emotes_de_chaine_gardent_une_place...` le prouve en passant
    par `set_verified(channel_names=...)` directement ; ce test rejoue la même
    pression (huit globales toutes plus employées que la meilleure emote de
    chaîne) mais en passant par `refresh_from_api`, le seul chemin emprunté en
    production — pour qu'un oubli de câblage de `channel_names` s'y voie."""
    globales = ["LUL", "Kappa", "SeemsGood", "HeyGuys", "NotLikeThis",
                "KonCha", "MyAvatar", "PogChamp"]
    chaine = ["azrael74SpongeFuse", "azrael74ChadFuse"]
    await em.refresh_from_api(_FauxAPI(globales, chaine))
    registre = em.active_emote_registry()
    for nom, n in {"LUL": 554, "Kappa": 514, "SeemsGood": 90, "HeyGuys": 65,
                   "NotLikeThis": 60, "KonCha": 56, "MyAvatar": 49,
                   "PogChamp": 40, "azrael74SpongeFuse": 23,
                   "azrael74ChadFuse": 23}.items():
        for _ in range(n):
            registre.note_chat(nom)
    assert set(registre.top()) & set(chaine)


@pytest.mark.asyncio
async def test_sans_droit_sur_les_emotes_de_chaine_les_globales_restent():
    """`/chat/emotes/user` rend 401 tant que le scope manque : ce refus ne doit
    pas priver Wally des 304 globales, qui n'ont jamais demandé de droit."""
    await em.refresh_from_api(_FauxAPI(["LUL", "KonCha"], None))
    assert em.active_emote_registry().verified == {"LUL", "KonCha"}


def test_une_emote_perdue_cesse_detre_proposee_malgre_son_historique():
    """Fin d'abonnement : elle a beau avoir été la plus employée, il ne peut
    plus l'écrire."""
    registre = em.active_emote_registry()
    registre.set_verified(["azrael74HYPE", "LUL"])
    registre.note_chat("azrael74HYPE")
    registre.note_chat("LUL")
    registre.set_verified(["LUL"])
    assert registre.top() == ["LUL"]


# ── panne d'API : rien d'inventé, rien de perdu ───────────────────────────

@pytest.mark.asyncio
async def test_une_api_muette_au_demarrage_ne_fait_proposer_aucune_emote():
    """Pas de plantage, et surtout pas d'emote sortie de nulle part."""
    await em.refresh_from_api(_FauxAPI(None, None))
    em.note_chat_emotes("LUL LUL LUL")
    assert em.current_emote_block() is None


@pytest.mark.asyncio
async def test_une_api_qui_tombe_ne_vide_pas_ce_quil_savait_deja():
    """Une coupure réseau ne doit pas le faire retomber aux emojis."""
    registre = em.active_emote_registry()
    registre.set_verified(["LUL"])
    registre.note_chat("LUL")
    await em.refresh_from_api(_FauxAPI(None, None))
    assert "LUL" in registre.render()


@pytest.mark.asyncio
async def test_un_catalogue_global_vide_est_une_reponse_malformee_pas_un_etat():
    """Twitch a toujours des emotes globales. Zéro veut dire que la réponse est
    cassée, pas que le monde a changé : on garde ce qu'on savait."""
    registre = em.active_emote_registry()
    registre.set_verified(["LUL"])
    registre.note_chat("LUL")
    await em.refresh_from_api(_FauxAPI([], None))
    assert registre.top() == ["LUL"]


@pytest.mark.asyncio
async def test_une_api_qui_leve_ne_casse_pas_le_bot():
    class _Cassee:
        async def get_global_emotes(self):
            raise RuntimeError("réseau")

        async def get_entitled_channel_emotes(self):
            raise RuntimeError("réseau")

    await em.refresh_from_api(_Cassee())
    assert em.current_emote_block() is None


# ── ce qui vit dans le chat décide du classement ──────────────────────────

def test_une_emote_jamais_vue_ici_ne_part_pas_au_prompt():
    """304 globales existent ; on ne lui souffle que celles qui ont cours ici."""
    registre = em.active_emote_registry()
    registre.set_verified(["LUL", "ResidentSleeper", "GoldPLZ"])
    registre.note_chat("LUL")
    assert registre.top() == ["LUL"]


def test_les_plus_employees_passent_devant():
    registre = em.active_emote_registry()
    registre.set_verified(["LUL", "KonCha"])
    for _ in range(3):
        registre.note_chat("LUL")
    registre.note_chat("KonCha")
    assert registre.top() == ["LUL", "KonCha"]


def test_un_seul_spammeur_ne_decide_pas_du_classement():
    """« LUL LUL LUL LUL » est une personne qui rit fort, pas quatre emplois."""
    registre = em.active_emote_registry()
    registre.set_verified(["LUL", "KonCha"])
    registre.note_chat("LUL LUL LUL LUL LUL")
    registre.note_chat("KonCha")
    registre.note_chat("KonCha")
    assert registre.top() == ["KonCha", "LUL"]


def test_on_lui_donne_une_poignee_pas_un_catalogue():
    """304 emotes en contexte seraient absurdes et il n'en retiendrait aucune."""
    registre = em.active_emote_registry()
    noms = [f"Emote{i:03d}" for i in range(40)]
    registre.set_verified(noms)
    for nom in noms:
        registre.note_chat(nom)
    assert len(registre.top()) <= em.MAX_PROPOSEES


def test_les_emotes_que_le_tamis_de_forme_ratait_sont_bien_comptees():
    """`Kappa` est l'emote la plus employée du chat (128 emplois en 7 jours) et
    la règle de forme des vagues la rejette : une majuscule en tête seulement.
    L'appartenance au registre vérifié, elle, ne la rate pas."""
    registre = em.active_emote_registry()
    registre.set_verified(["Kappa", "Kreygasm", ":D", "<3"])
    registre.note_chat("Kappa")
    registre.note_chat("Kreygasm :D <3")
    assert set(registre.top()) == {"Kappa", "Kreygasm", ":D", "<3"}


def test_une_emote_mal_capitalisee_nest_pas_la_meme_chose():
    """Twitch est sensible à la casse : « lul » ne s'affiche pas, il s'écrit."""
    registre = em.active_emote_registry()
    registre.set_verified(["LUL"])
    registre.note_chat("lul")
    assert registre.top() == []


# ── la chaîne garde une place, sans se la faire imposer ───────────────────

def test_les_emotes_de_chaine_gardent_une_place_malgre_lecrasement_des_globales():
    """Chiffres réels d'un relevé sur 7 jours de chat : les globales (`LUL`
    554, `Kappa` 514...) écrasent en fréquence pure les emotes de la chaîne
    (23 emplois au mieux) alors que ce sont elles qui font sonner Wally comme
    un habitué de CETTE chaîne plutôt que de Twitch en général."""
    registre = em.active_emote_registry()
    # Huit globales, TOUTES employées davantage que la meilleure emote de la
    # chaîne (23) : sans réserve, elles rempliraient à elles seules les 8
    # places et aucune `azrael74*` n'apparaîtrait jamais.
    globales = {
        "LUL": 554, "Kappa": 514, "SeemsGood": 90, "HeyGuys": 65,
        "NotLikeThis": 60, "KonCha": 56, "MyAvatar": 49, "PogChamp": 40,
    }
    chaine = {
        "azrael74SpongeFuse": 23, "azrael74ChadFuse": 23,
        "azrael74FuZe": 8, "azrael74Potato": 3,
    }
    registre.set_verified(
        [*globales, *chaine, "azrael74Azrael"],  # jamais employée
        channel_names=[*chaine, "azrael74Azrael"],
    )
    for nom, n in {**globales, **chaine}.items():
        for _ in range(n):
            registre.note_chat(nom)

    proposees = registre.top()
    assert len(proposees) == em.MAX_PROPOSEES
    # Les deux globales les plus employées du chat restent en tête : la
    # réserve ne les évince jamais.
    assert {"LUL", "Kappa"}.issubset(proposees)
    # Au moins une emote de la chaîne obtient sa place, malgré un nombre
    # d'emplois sans commune mesure avec les globales.
    assert set(proposees) & set(chaine)
    # Vérifiée mais jamais employée : la réserve ne l'invente pas pour autant.
    assert "azrael74Azrael" not in proposees


def test_une_emote_de_chaine_jamais_employee_ne_prend_pas_la_reserve():
    """Une emote de chaîne à laquelle le bot a droit mais que personne
    n'emploie ne doit pas remonter — la réserve suit l'usage, pas le droit."""
    registre = em.active_emote_registry()
    registre.set_verified(
        ["LUL", "azrael74Azrael"], channel_names=["azrael74Azrael"]
    )
    registre.note_chat("LUL")
    assert registre.top() == ["LUL"]


def test_la_reserve_ne_mord_sur_rien_si_la_chaine_est_silencieuse():
    """Aucune emote de chaîne employée cette semaine : le classement reste
    une pure fréquence, comme si la distinction d'origine n'existait pas."""
    registre = em.active_emote_registry()
    registre.set_verified(
        ["LUL", "KonCha", "azrael74HYPE"], channel_names=["azrael74HYPE"]
    )
    for _ in range(3):
        registre.note_chat("LUL")
    registre.note_chat("KonCha")
    assert registre.top() == ["LUL", "KonCha"]


# ── amorçage depuis les journaux ──────────────────────────────────────────

def _ecrire_journal(tmp_path, canal, evenements, date="2026-08-13"):
    dossier = tmp_path / "twitch" / canal
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{date}.jsonl").write_text(
        "\n".join(json.dumps(e) for e in evenements), encoding="utf-8"
    )


def test_il_arrive_au_live_en_sachant_deja_ce_que_le_chat_emploie(tmp_path):
    """Le process est reconstruit presque tous les jours : sans amorçage, la
    première demi-heure de chaque live se passait sans une emote."""
    _ecrire_journal(tmp_path, "azrael_ttv", [
        {"type": "message_in", "content": "LUL"},
        {"type": "message_in", "content": "LUL"},
        {"type": "message_in", "content": "KonCha"},
    ])
    registre = em.active_emote_registry()
    registre.set_verified(["LUL", "KonCha"])
    registre.seed_from_logs(tmp_path)
    assert registre.top() == ["LUL", "KonCha"]


def test_lamorcage_ne_compte_pas_ses_propres_messages(tmp_path):
    """Sinon il se confirme à lui-même les emotes qu'il vient d'employer, et le
    classement mesure ses tics au lieu de ceux du chat."""
    _ecrire_journal(tmp_path, "azrael_ttv", [
        {"type": "message_out", "content": "LUL LUL LUL"},
        {"type": "message_in", "content": "KonCha"},
    ])
    registre = em.active_emote_registry()
    registre.set_verified(["LUL", "KonCha"])
    registre.seed_from_logs(tmp_path)
    assert registre.top() == ["KonCha"]


def test_lamorcage_regarde_les_derniers_JOURS_pas_les_derniers_fichiers(tmp_path):
    """Un vocabulaire d'il y a six mois n'est plus celui d'aujourd'hui — et la
    fenêtre doit couvrir tous les canaux d'une même journée, pas une journée par
    canal."""
    _ecrire_journal(tmp_path, "azrael_ttv",
                    [{"type": "message_in", "content": "Kappa"}], date="2026-02-01")
    _ecrire_journal(tmp_path, "azrael_ttv",
                    [{"type": "message_in", "content": "LUL"}], date="2026-08-13")
    _ecrire_journal(tmp_path, "kingsrequin",
                    [{"type": "message_in", "content": "KonCha"}], date="2026-08-13")
    registre = em.active_emote_registry()
    registre.set_verified(["LUL", "KonCha", "Kappa"])
    registre.seed_from_logs(tmp_path, days=1)
    assert set(registre.top()) == {"LUL", "KonCha"}


def test_un_journal_illisible_ne_casse_pas_le_demarrage(tmp_path):
    _ecrire_journal(tmp_path, "azrael_ttv", [{"type": "message_in", "content": "LUL"}])
    (tmp_path / "twitch" / "azrael_ttv" / "2026-08-12.jsonl").write_text(
        "{ceci n'est pas du json\n", encoding="utf-8"
    )
    registre = em.active_emote_registry()
    registre.set_verified(["LUL"])
    registre.seed_from_logs(tmp_path)
    assert registre.top() == ["LUL"]


def test_lamorcage_sans_journal_ne_leve_pas(tmp_path):
    registre = em.active_emote_registry()
    registre.set_verified(["LUL"])
    assert registre.seed_from_logs(tmp_path / "vide") == 0


# ── branchement : au prompt Twitch, et nulle part ailleurs ────────────────

def test_le_bloc_arrive_dans_le_prompt_du_chat_twitch():
    em.active_emote_registry().set_verified(["LUL"])
    em.note_chat_emotes("LUL")
    assert "LUL" in _prompt({"platform": "Twitch", "channel": "#azrael_ttv"})


def test_le_prompt_discord_nen_recoit_rien():
    """Une emote Twitch écrite sur Discord n'est qu'un mot bizarre."""
    em.active_emote_registry().set_verified(["LUL"])
    em.note_chat_emotes("LUL")
    assert "LUL" not in _prompt({"platform": "Discord", "channel": "#général"})


def test_le_prompt_vocal_nen_recoit_rien():
    """À l'oral, une emote ne veut rien dire du tout."""
    em.active_emote_registry().set_verified(["LUL"])
    em.note_chat_emotes("LUL")
    assert "LUL" not in _prompt({"platform": "discord_vocal"})


def test_sans_emote_sure_le_prompt_ne_coute_pas_un_jeton():
    assert "emotes de ce chat" not in _prompt({"platform": "Twitch"})


def test_le_chat_de_la_chaine_alimente_le_registre():
    """Branchement vérifié à la source : l'exécuter demanderait de monter un
    adaptateur Twitch entier. Même précédent que `test_thread_sense`."""
    import inspect

    import bot.twitch.handlers as handlers

    source = inspect.getsource(handlers)
    assert "note_chat_emotes(" in source
