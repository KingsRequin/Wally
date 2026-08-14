# tests/test_apex_duel_trace_memoire.py
"""§11 ter : la trace du duel doit raconter ce qui s'est RÉELLEMENT passé.

« Tu m'avais mis 11–6 le mois dernier » n'a de valeur que si c'est vrai. Deux
façons de fabriquer un faux précédent étaient ouvertes :

  · le drapeau `abandon` du verdict était ignoré — un duelliste qui mène puis
    quitte était mémorisé vainqueur d'un duel régulier, exactement ce que la
    règle du jeu refuse de récompenser ;
  · une fin SANS verdict (abandon remboursé, annulation par un modérateur,
    compte jamais résolu) ne laissait rien, alors que quelqu'un avait bel et
    bien dépensé ses points.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat
from bot.core.apex.duel_runner import DuelRunner

VIEWER_ID = "105904256"


def _runner():
    memory = MagicMock()
    memory.add = AsyncMock()
    client = MagicMock()
    client.get = AsyncMock(return_value="Apex API error: timeout")
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    api.honorer_redemption = AsyncMock(return_value=True)
    runner = DuelRunner(client=client, db=db, api=api, memory=memory,
                        annoncer=AsyncMock(), azrael_uid="7")
    runner._reward_id = "rw"
    return runner, memory


def _duel(manches: int = 3) -> Duel:
    return Duel(viewer_nom="Bob", viewer_uid="42", viewer_id=VIEWER_ID,
                azrael_uid="7", redemption_id="rd", manches=manches)


def _fait(memory) -> str:
    assert memory.add.await_args is not None, "aucune trace écrite"
    return memory.add.await_args.args[2]


@pytest.mark.asyncio
async def test_un_duel_interrompu_nest_pas_memorise_comme_un_duel_gagne():
    """Le duelliste mène 5-2 après la manche 1, puis ne revient jamais.

    Il garde sa victoire sur les manches jouées — mais la trace ne doit pas
    laisser croire qu'il a battu Azraël sur un duel complet : ses points sont
    restés dépensés, et une revanche s'appuierait sur un précédent faux.
    """
    runner, memory = _runner()
    duel = _duel()
    duel.etat = Etat.ENTRE_MANCHES
    duel.scores = [{"azrael": 2, "viewer": 5, "azrael_lu": 2, "viewer_lu": 5}]
    duel._t_attente = 0
    runner.duel_en_cours = duel

    await runner.tick(maintenant=16 * 60)

    assert duel.etat is Etat.VERDICT
    fait = _fait(memory)
    bas = fait.lower()
    assert "interrompu" in bas or "pas allé" in bas, (
        f"la trace doit dire que le duel n'est pas allé au bout : {fait!r}")
    assert "5" in fait and "Bob" in fait, f"le score joué reste dit : {fait!r}"


@pytest.mark.asyncio
async def test_un_duel_mene_a_son_terme_est_memorise_comme_tel():
    """Le contre-exemple : sans lui, une trace qui dirait « interrompu » à
    chaque fois passerait le test précédent."""
    runner, memory = _runner()
    duel = _duel(manches=1)
    duel.etat = Etat.MANCHE
    duel._base_azrael = {"career_kills": 0}
    duel._base_viewer = {"career_kills": 0}
    runner.duel_en_cours = duel

    async def _profils(_endpoint, params=None, **_kw):
        n = 3 if str((params or {}).get("uid")) == "7" else 11
        return {"realtime": {"isInGame": 0},
                "total": {"career_kills": {"name": "BR Kills", "value": n}}}

    runner._client.get = AsyncMock(side_effect=_profils)
    for t in (100, 102, 112):
        await runner.tick(maintenant=t)

    assert duel.etat is Etat.VERDICT
    fait = _fait(memory)
    assert "interrompu" not in fait.lower(), f"le duel est allé au bout : {fait!r}"
    assert "11" in fait and "3" in fait, f"le score final : {fait!r}"


@pytest.mark.asyncio
async def test_un_abandon_rembourse_laisse_une_trace_sans_vainqueur():
    """Personne n'a rejoint le squad : le duel n'a pas eu lieu, mais l'achat,
    lui, a eu lieu. Rien n'était écrit — et surtout, aucun vainqueur ne doit
    être inventé."""
    runner, memory = _runner()
    duel = _duel()
    duel.etat = Etat.ATTENTE_SQUAD
    duel._t_attente = 0
    runner.duel_en_cours = duel

    await runner.tick(maintenant=16 * 60)

    assert duel.etat is Etat.ABANDON
    fait = _fait(memory)
    bas = fait.lower()
    assert "pas de vainqueur" in bas, f"aucun vainqueur à inventer : {fait!r}"
    assert "l'emporte" not in bas, f"aucun vainqueur à inventer : {fait!r}"
    assert "squad" in bas, f"la cause de l'arrêt doit être dite : {fait!r}"


@pytest.mark.asyncio
async def test_une_annulation_par_un_moderateur_laisse_une_trace():
    runner, memory = _runner()
    duel = _duel()
    duel.etat = Etat.ATTENTE_SQUAD
    runner.duel_en_cours = duel

    await runner.annuler("un modérateur a annulé le duel")

    fait = _fait(memory)
    assert "pas de vainqueur" in fait.lower(), f"{fait!r}"
    assert "modérateur" in fait, f"la cause doit être dite : {fait!r}"


@pytest.mark.asyncio
async def test_un_compte_jamais_resolu_laisse_une_trace():
    """Trois essais, pas de compte, remboursement : c'est une fin de duel
    comme une autre pour celui qui a payé."""
    runner, memory = _runner()
    duel = _duel()
    duel.etat = Etat.RESOLUTION
    duel.viewer_uid = ""
    runner.duel_en_cours = duel
    runner._tentatives = 2

    await runner.repondre_resolution("Bob", "pseudo introuvable")

    assert runner.duel_en_cours is None
    fait = _fait(memory)
    assert "pas de vainqueur" in fait.lower(), f"{fait!r}"


@pytest.mark.asyncio
async def test_une_seule_trace_par_fin_de_duel():
    """Le duelliste qui ne revient pas après une manche comptée déclenche un
    abandon PUIS un verdict. Deux écritures se contrediraient l'une l'autre."""
    runner, memory = _runner()
    duel = _duel()
    duel.etat = Etat.ENTRE_MANCHES
    duel.scores = [{"azrael": 6, "viewer": 1, "azrael_lu": 6, "viewer_lu": 1}]
    duel._t_attente = 0
    runner.duel_en_cours = duel

    await runner.tick(maintenant=16 * 60)

    memory.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_la_trace_dun_abandon_prend_lidentifiant_brut():
    """Convention maison, et elle est piégeuse : `memory.add()` construit
    `twitch:<id>` lui-même. La forme préfixée donnerait `twitch:twitch:<id>`,
    donc un utilisateur fantôme que personne ne retrouvera."""
    runner, memory = _runner()
    duel = _duel()
    duel.etat = Etat.ATTENTE_SQUAD
    duel._t_attente = 0
    runner.duel_en_cours = duel

    await runner.tick(maintenant=16 * 60)

    args = memory.add.await_args.args
    assert args[0] == "twitch"
    assert args[1] == VIEWER_ID


@pytest.mark.asyncio
async def test_sans_identifiant_twitch_un_abandon_ne_fabrique_rien():
    """Sans id, il n'y a pas de fiche où ranger ça : deviner par le pseudo
    fabriquerait un utilisateur que rien ne nettoiera."""
    runner, memory = _runner()
    duel = _duel()
    duel.viewer_id = ""
    duel.etat = Etat.ATTENTE_SQUAD
    duel._t_attente = 0
    runner.duel_en_cours = duel

    await runner.tick(maintenant=16 * 60)

    memory.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_memoire_en_panne_nempeche_ni_le_remboursement_ni_lannonce():
    """La trace est un bonus : elle ne passe jamais devant les points."""
    runner, memory = _runner()
    memory.add = AsyncMock(side_effect=RuntimeError("base morte"))
    duel = _duel()
    duel.etat = Etat.ATTENTE_SQUAD
    duel._t_attente = 0
    runner.duel_en_cours = duel

    await runner.tick(maintenant=16 * 60)

    assert runner.duel_en_cours is None
    runner._api.refund_redemption.assert_awaited_once()
    types = [c.args[0].type for c in runner._annoncer.await_args_list]
    assert "abandon" in types
