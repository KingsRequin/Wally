"""« Wally, affiche un mème » se dit autant à voix haute qu'à l'écrit.

Vécu en direct le 2026-08-25, sur le live d'Azraël : trois demandes d'affichage
à voix haute (« affiche le dernier clip », « affiche un mème »), trois réponses
polies, zéro appel d'outil, et pour finir — « il a pas l'air de vouloir afficher
quoi que ce soit, donc tant pis ».

Wally ne refusait rien : `build_voice_tools()` ne lui proposait tout simplement
aucun outil d'overlay. Il les a pourtant sur Discord ET sur Twitch. La panne est
la même que celle de la musique : une capacité branchée d'un côté, oubliée de
l'autre, qui ne casse rien, ne journalise rien, et ne se voit que le jour où
quelqu'un la demande — devant les viewers.

`tests/test_parite_plateformes.py` tenait l'inventaire Discord ↔ Twitch. Le
vocal n'était comparé à rien : c'est par là que le trou est passé.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.voice.tools import build_voice_tools, make_voice_tool_executor


def _noms(outils):
    return {o["function"]["name"] for o in outils}


async def _outils(bot):
    bot.web_search.available = False
    bot.action_service = None
    bot.music = None
    return await build_voice_tools(bot)


def _bot_avec_overlay():
    """Un bot vocal dont l'overlay est branché et le live en cours."""
    bot = MagicMock()
    narrateur = MagicMock()
    # `spec_outil` est async côté prod ; le repli de `_spec_overlay_pour` sert
    # la spec entière si elle lève, ce qui suffit ici.
    narrateur.spec_outil = AsyncMock(side_effect=RuntimeError("pas de base en test"))
    narrateur.is_active = MagicMock(return_value=True)
    bot.overlay_narrator = narrateur
    return bot, narrateur


# ───────────────────────── ce qui est PROPOSÉ ─────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("outil", ["show_overlay", "cancel_overlay", "show_clip"])
async def test_les_outils_d_overlay_sont_proposes_en_vocal(outil):
    bot, _ = _bot_avec_overlay()
    bot.apex_api = None
    assert outil in _noms(await _outils(bot)), (
        f"« {outil} » manque au vocal : Wally répondra poliment sans rien afficher."
    )


@pytest.mark.asyncio
async def test_l_overlay_apex_suit_la_disponibilite_de_l_api():
    bot, _ = _bot_avec_overlay()
    bot.apex_api = MagicMock()
    assert "show_apex" in _noms(await _outils(bot))

    bot.apex_api = None
    assert "show_apex" not in _noms(await _outils(bot))


@pytest.mark.asyncio
async def test_sans_overlay_branche_aucun_outil_d_affichage():
    """Un outil mort ferait promettre un affichage qui n'arriverait jamais."""
    bot, _ = _bot_avec_overlay()
    bot.overlay_narrator = None
    bot.discord_bot = None          # `_overlay_narrator` cherche AUSSI par là
    bot.apex_api = MagicMock()

    proposes = _noms(await _outils(bot))
    for outil in ("show_overlay", "cancel_overlay", "show_clip", "show_apex"):
        assert outil not in proposes


# ───────────────────────── ce qui est EXÉCUTÉ ─────────────────────────
@pytest.mark.asyncio
async def test_afficher_un_meme_a_la_voix_monte_vraiment_a_l_ecran():
    bot, narrateur = _bot_avec_overlay()
    narrateur.show_widget = MagicMock(
        return_value={"widget": "meme", "description": "le chat qui tape"})

    executor = make_voice_tool_executor(bot, MagicMock(), current_speaker_id=lambda: "1")
    rendu = json.loads(await executor("show_overlay", json.dumps({
        "widget": "meme", "comment": "tiens, celui-là"})))

    assert narrateur.show_widget.called, (
        "l'exécuteur vocal n'a pas routé `show_overlay` — Wally répond « ok » "
        "et l'écran reste vide"
    )
    assert rendu["status"] == "ok"
    assert "le chat qui tape" in rendu["message"]


@pytest.mark.asyncio
async def test_le_chifoumi_vocal_joue_contre_CELUI_QUI_PARLE():
    """`requester` vient de l'appelant, jamais du modèle.

    Sans lui, la main adverse s'affiche sous le nom de la dernière personne
    entendue — ou sous aucun nom du tout.
    """
    bot, narrateur = _bot_avec_overlay()
    narrateur.show_widget = MagicMock(return_value={"widget": "rps"})

    membre = MagicMock()
    membre.id = 4242
    membre.display_name = "Azraël"
    membre.name = "._.azrael._."
    salon = MagicMock()
    salon.members = [membre]
    service = MagicMock()
    service._channel = salon

    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "4242")
    await executor("show_overlay", json.dumps({"widget": "rps", "comment": "go"}))

    assert "Azraël" in narrateur.show_widget.call_args.kwargs.get("opponent", "")


@pytest.mark.asyncio
async def test_un_refus_de_l_overlay_est_DIT_et_pas_avale():
    """Hors live, l'outil doit rendre un refus explicite.

    C'est la garde qui empêche « c'est affiché ! » devant un écran vide.
    """
    bot, narrateur = _bot_avec_overlay()
    narrateur.show_widget = MagicMock(return_value=None)
    narrateur.is_active = MagicMock(return_value=False)

    executor = make_voice_tool_executor(bot, MagicMock(), current_speaker_id=lambda: "1")
    rendu = json.loads(await executor("show_overlay", json.dumps({"widget": "meme"})))

    assert rendu["status"] == "offline"
    assert "pas de live" in rendu["message"]


@pytest.mark.asyncio
async def test_annuler_a_la_voix_passe_par_le_narrateur():
    bot, narrateur = _bot_avec_overlay()
    narrateur.cancel = MagicMock(return_value={"cancelled": ["sondage"]})

    executor = make_voice_tool_executor(bot, MagicMock(), current_speaker_id=lambda: "1")
    rendu = json.loads(await executor("cancel_overlay", json.dumps({"target": "sondage"})))

    narrateur.cancel.assert_called_once_with("sondage")
    assert rendu["status"] == "ok"


@pytest.mark.asyncio
async def test_le_clip_a_la_voix_passe_par_l_executeur_du_chat():
    """Le clip est le premier des trois refus vécus en direct."""
    bot, _ = _bot_avec_overlay()
    appels = []

    async def _faux_clip(bot_, args):
        appels.append(args)
        return json.dumps({"status": "ok", "message": "Le clip est à l'écran."})

    import bot.discord.handlers as chat
    executor = make_voice_tool_executor(bot, MagicMock(), current_speaker_id=lambda: "1")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(chat, "run_last_clip_tool", _faux_clip)
        rendu = json.loads(await executor("show_clip", json.dumps({})))

    assert appels, "`show_clip` n'a pas été routé en vocal"
    assert rendu["status"] == "ok"


# ───────────────────────── le garde-fou de parité ─────────────────────
@pytest.mark.asyncio
async def test_tout_outil_PROPOSE_en_vocal_est_aussi_EXECUTABLE():
    """Le vrai piège : proposer un outil que l'exécuteur ne route pas.

    Le modèle l'appelle, reçoit « Outil inconnu », et improvise — c'est
    exactement ce qui produit un « c'est affiché » devant un écran vide. Ce test
    tient les deux listes ensemble, pour tout outil présent et à venir.
    """
    bot, narrateur = _bot_avec_overlay()
    bot.apex_api = MagicMock()
    bot.music = MagicMock()
    narrateur.show_widget = MagicMock(return_value={"widget": "meme"})
    narrateur.cancel = MagicMock(return_value={"cancelled": []})

    executor = make_voice_tool_executor(bot, MagicMock(), current_speaker_id=lambda: "1")

    inconnus = []
    for nom in _noms(await _outils(bot)):
        rendu = await executor(nom, "{}")
        if "Outil inconnu" in (rendu or ""):
            inconnus.append(nom)

    assert not inconnus, (
        f"outils proposés au vocal mais non routés par l'exécuteur : {sorted(inconnus)}"
    )


@pytest.mark.asyncio
async def test_retenir_quelque_chose_a_la_voix_ecrit_VRAIMENT_en_memoire():
    """`save_user_memory` était proposé au vocal et routé nulle part.

    Le modèle l'appelait, recevait « Outil inconnu », et répondait « c'est
    noté » — sur un souvenir que personne n'avait écrit.
    """
    bot, _ = _bot_avec_overlay()
    bot.memory.add = AsyncMock()

    membre = MagicMock()
    membre.id = 4242
    membre.display_name = "Azraël"
    membre.name = "._.azrael._."
    salon = MagicMock()
    salon.members = [membre]
    salon.name = "vocal"
    service = MagicMock()
    service._channel = salon

    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "4242")
    rendu = json.loads(await executor("save_user_memory", json.dumps({
        "content": "Azraël stream matin et soir"})))

    assert rendu["status"] == "ok"
    bot.memory.add.assert_awaited_once()
    args, kwargs = bot.memory.add.await_args
    # `user_id` BRUT : `memory.add` préfixe la plateforme lui-même. Le passer
    # déjà préfixé range le souvenir sous « discord:discord:4242 ».
    assert args[0] == "discord" and args[1] == "4242"
    assert "matin et soir" in args[2]


@pytest.mark.asyncio
async def test_un_outil_qui_leve_ne_casse_PAS_le_tour_de_parole():
    """Sans filet, l'exception remonte et le modèle n'obtient aucun résultat —
    il enchaîne alors sur un « c'est fait » portant sur rien."""
    bot, _ = _bot_avec_overlay()
    bot.memory.add = AsyncMock(side_effect=RuntimeError("base fermée"))
    service = MagicMock()
    service._channel = None

    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "1")
    rendu = json.loads(await executor("save_user_memory", json.dumps({"content": "x"})))

    assert rendu["status"] == "error"
    assert "prétends pas" in rendu["message"]


@pytest.mark.asyncio
async def test_une_note_sans_titre_est_refusee_au_lieu_de_lever():
    bot, _ = _bot_avec_overlay()
    bot.db.upsert_persistent_note = AsyncMock()

    executor = make_voice_tool_executor(bot, MagicMock(), current_speaker_id=lambda: "1")
    rendu = json.loads(await executor("save_persistent_note", json.dumps({"content": "seul"})))

    assert rendu["status"] == "error"
    assert not bot.db.upsert_persistent_note.called


@pytest.mark.asyncio
async def test_le_panneau_apex_recoit_un_IDENTIFIANT_pas_un_pseudo():
    """`requester` ne veut pas dire la même chose selon l'outil.

    `show_overlay` y attend un nom affichable — il nomme la main adverse du
    chifoumi. `show_apex` y attend un identifiant : il descend jusqu'à
    `_resolve_uid`, qui cherche le compte Apex LIÉ à la personne. Confondre les
    deux n'échoue pas — le panneau sort simplement sans le compte du demandeur.
    """
    bot, _ = _bot_avec_overlay()
    vus = {}

    async def _faux_apex(bot_, args, requester=None):
        vus["requester"] = requester
        return json.dumps({"status": "ok", "message": "Panneau affiché."})

    membre = MagicMock()
    membre.id = 4242
    membre.display_name = "Azraël"
    membre.name = "._.azrael._."
    salon = MagicMock()
    salon.members = [membre]
    service = MagicMock()
    service._channel = salon

    import bot.discord.handlers as chat
    executor = make_voice_tool_executor(bot, service, current_speaker_id=lambda: "4242")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(chat, "run_apex_overlay_tool", _faux_apex)
        await executor("show_apex", json.dumps({"panel": "rank"}))

    assert vus["requester"] == "discord:4242", (
        "un pseudo affichable ne résout aucun compte Apex — il faut l'identifiant"
    )
