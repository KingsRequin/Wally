# tests/test_apex_duel_pannes.py
"""Une panne n'est pas un abandon : elle rembourse, et elle se nomme.

Deux chemins produisaient un abandon SANS remboursement, annoncé « ses points
restent dépensés : il n'est pas allé au bout du duel » — pour des causes dont le
duelliste n'était pas l'auteur :

  · le stream d'Azraël se coupe en cours de duel (§8 de la spec : remboursement,
    mais rien ne le branchait) ;
  · l'API Apex devient muette ENTRE deux manches, où le garde-fou `_api_muette`
    n'était pas appelé — le minuteur d'attente finissait sur « pas de retour
    dans le délai ».

Dans les deux cas le duelliste, même vainqueur, perdait sa mise et se faisait
accuser.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat
from bot.core.apex.duel_runner import DuelRunner

PANNE = "Apex API error: timeout"


def _runner(stream_en_ligne=None, **kw):
    client = MagicMock()
    client.get = AsyncMock(return_value=PANNE)
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    api.honorer_redemption = AsyncMock(return_value=True)
    runner = DuelRunner(client=client, db=db, api=api, annoncer=AsyncMock(),
                        azrael_uid="7", stream_en_ligne=stream_en_ligne, **kw)
    runner._reward_id = "rw"
    return runner, api


def _duel(runner, etat, *, scores=None):
    """Un duel en cours. Le minuteur d'attente démarre au PREMIER tick, comme
    en vrai — le poser à zéro ferait expirer le duel dès le premier tour et
    masquerait ce que ces tests observent."""
    duel = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
                redemption_id="rd", manches=3)
    duel.etat = etat
    duel.scores = list(scores or [])
    runner.duel_en_cours = duel
    return duel


def _abandon(runner):
    evts = [c.args[0] for c in runner._annoncer.await_args_list]
    abandons = [e for e in evts if e.type == "abandon"]
    assert abandons, f"aucun abandon annoncé (types : {[e.type for e in evts]})"
    return abandons[0]


# ── Le stream coupé rembourse ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_le_stream_coupe_rembourse_meme_apres_une_manche_gagnee():
    """Le pire cas : le duelliste MÈNE, et le stream s'éteint. Sans ce
    chemin, il finissait au timeout d'attente — points consommés et « il n'est
    pas allé au bout du duel » annoncé devant tout le monde."""
    runner, api = _runner(stream_en_ligne=lambda: False)
    duel = _duel(runner, Etat.ENTRE_MANCHES, scores=[{"azrael": 2, "viewer": 5}])

    await runner.tick(maintenant=1000)          # premier relevé hors ligne
    assert runner.duel_en_cours is duel, "un seul relevé ne suffit pas"
    api.refund_redemption.assert_not_awaited()

    await runner.tick(maintenant=1000 + 121)    # confirmé

    assert runner.duel_en_cours is None
    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    api.honorer_redemption.assert_not_awaited()
    assert _abandon(runner).donnees["rembourser"] is True


@pytest.mark.asyncio
async def test_le_motif_du_stream_coupe_n_accuse_pas_le_duelliste():
    runner, _ = _runner(stream_en_ligne=lambda: False, api_muette_max_s=10_000)
    _duel(runner, Etat.MANCHE)

    await runner.tick(maintenant=1000)
    await runner.tick(maintenant=1000 + 121)

    motif = _abandon(runner).donnees["motif"].lower()
    assert "stream" in motif, f"la cause réelle doit être dite : {motif!r}"
    assert "pas de retour" not in motif and "n'est pas revenu" not in motif, (
        f"le duelliste n'a rien abandonné : {motif!r}")


@pytest.mark.asyncio
async def test_un_stream_allume_ne_solde_jamais_rien():
    runner, api = _runner(stream_en_ligne=lambda: True)
    duel = _duel(runner, Etat.ENTRE_MANCHES, scores=[{"azrael": 2, "viewer": 5}])
    runner._client.get = AsyncMock(return_value={
        "realtime": {"isInGame": 0},
        "total": {"career_kills": {"name": "BR Kills", "value": 3}}})

    for t in range(0, 400, 60):
        await runner.tick(maintenant=1000 + t)

    assert runner.duel_en_cours is duel
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_statut_INCONNU_n_est_pas_un_stream_eteint():
    """Le `StreamWatcher` n'a pas encore sondé : son défaut porte
    `live: False`, ce qui ne veut pas dire « éteint ». Un rebuild en plein duel
    solderait sinon un duel dont le live tourne."""
    runner, api = _runner(stream_en_ligne=lambda: None, api_muette_max_s=10_000)
    duel = _duel(runner, Etat.MANCHE)

    await runner.tick(maintenant=1000)
    await runner.tick(maintenant=1000 + 121)

    assert runner.duel_en_cours is duel
    assert duel.etat is Etat.MANCHE
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_relevé_en_ligne_efface_le_hors_ligne_accumulé():
    """Le seuil porte sur une coupure CONTINUE : `/helix/streams` rend parfois
    une liste vide sur une chaîne allumée."""
    statut = {"live": False}
    runner, api = _runner(stream_en_ligne=lambda: statut["live"],
                          api_muette_max_s=10_000)
    _duel(runner, Etat.MANCHE)

    await runner.tick(maintenant=1000)
    statut["live"] = True
    await runner.tick(maintenant=1060)
    statut["live"] = False
    await runner.tick(maintenant=1100)
    await runner.tick(maintenant=1180)          # 80 s seulement depuis 1100

    assert runner.duel_en_cours is not None
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_statut_qui_leve_ne_solde_pas_le_duel():
    def _boum():
        raise RuntimeError("statut illisible")

    runner, api = _runner(stream_en_ligne=_boum, api_muette_max_s=10_000)
    duel = _duel(runner, Etat.MANCHE)

    await runner.tick(maintenant=1000)
    await runner.tick(maintenant=1000 + 200)

    assert runner.duel_en_cours is duel
    api.refund_redemption.assert_not_awaited()


# ── L'API muette ENTRE deux manches rembourse comme pendant une manche ──────
@pytest.mark.asyncio
async def test_l_api_muette_entre_deux_manches_rembourse():
    """Le duelliste a gagné la manche 1 et attend la suivante ; l'API se tait.
    Le minuteur d'attente le déclarait « pas revenu dans le délai » : abandon
    sans remboursement, et une accusation en prime."""
    runner, api = _runner()
    duel = _duel(runner, Etat.ENTRE_MANCHES, scores=[{"azrael": 2, "viewer": 5}])

    await runner.tick(maintenant=1000)
    await runner.tick(maintenant=1000 + 179)
    assert runner.duel_en_cours is duel, "quelques relevés ratés restent tolérés"
    api.refund_redemption.assert_not_awaited()

    await runner.tick(maintenant=1000 + 181)

    assert runner.duel_en_cours is None
    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    api.honorer_redemption.assert_not_awaited()
    abandon = _abandon(runner)
    assert abandon.donnees["rembourser"] is True
    motif = abandon.donnees["motif"].lower()
    assert "api" in motif, f"la cause réelle doit être dite : {motif!r}"
    assert "pas de retour" not in motif, f"le viewer n'a rien abandonné : {motif!r}"


@pytest.mark.asyncio
async def test_un_duelliste_qui_ne_revient_pas_est_toujours_traite_comme_tel():
    """Le contre-exemple, sans quoi on aurait remplacé un défaut par un autre :
    quand l'API RÉPOND et que le duelliste ne relance pas, l'abandon reste le
    sien — et il ne rembourse pas."""
    runner, api = _runner()
    duel = _duel(runner, Etat.ENTRE_MANCHES, scores=[{"azrael": 2, "viewer": 5}])
    runner._client.get = AsyncMock(return_value={
        "realtime": {"isInGame": 0},
        "total": {"career_kills": {"name": "BR Kills", "value": 3}}})

    await runner.tick(maintenant=100)
    await runner.tick(maintenant=100 + 16 * 60)

    assert duel.etat is Etat.VERDICT
    api.refund_redemption.assert_not_awaited()
    api.honorer_redemption.assert_awaited_once()


@pytest.mark.asyncio
async def test_le_seuil_de_silence_entre_manches_vient_de_la_configuration():
    runner, api = _runner(api_muette_max_s=10.0)
    _duel(runner, Etat.ENTRE_MANCHES, scores=[{"azrael": 2, "viewer": 5}])

    await runner.tick(maintenant=500)
    await runner.tick(maintenant=505)
    assert runner.duel_en_cours is not None, "sous le seuil réglé : toléré"

    await runner.tick(maintenant=512)

    assert runner.duel_en_cours is None
    api.refund_redemption.assert_awaited_once()
