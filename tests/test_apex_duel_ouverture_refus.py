# tests/test_apex_duel_ouverture_refus.py
"""Les deux refus d'ouverture que la spec (§8) veut immédiats.

« Stream offline » et « Azraël pas sur Apex » y sont rangés depuis toujours à
côté de « duel déjà en cours » : refus annoncé + remboursement immédiat. Aucun
des deux n'était testé — un achat stream éteint ouvrait un vrai duel, annonçait
dans un chat vide, sondait un quart d'heure pour rien, et refusait tous les
autres acheteurs pendant ce temps.

Le contre-exemple compte autant que le cas : une absence de donnée ne vaut
jamais un « non », et Azraël entre deux parties n'est pas Azraël absent.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Etat
from bot.core.apex.duel_runner import DuelRunner

PROFIL_VIEWER = {
    "global": {"uid": "42", "name": "Bob"},
    "realtime": {"isOnline": 1, "isInGame": 0},
    "total": {"career_kills": {"name": "BR Kills", "value": 10}},
}


def _azrael(**realtime) -> dict:
    return {
        "global": {"uid": "7", "name": "Azrael"},
        "realtime": realtime,
        "total": {"career_kills": {"name": "BR Kills", "value": 18782}},
    }


def _runner(azrael=None, stream=None):
    """Un runner dont l'API répond selon le compte sondé.

    `stream` est la sonde du live telle que `main.py` la branche : `True`,
    `False`, ou `None` quand le `StreamWatcher` n'a encore rien relevé.
    """
    profils = {"42": PROFIL_VIEWER,
               "7": azrael if azrael is not None else _azrael(isOnline=1, isInGame=1)}

    async def _get(_endpoint, params=None, **_kw):
        return profils.get(str((params or {}).get("uid")),
                           "Apex API error: compte inconnu")

    client = MagicMock()
    client.get = AsyncMock(side_effect=_get)
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    api.honorer_redemption = AsyncMock(return_value=True)
    annoncer = AsyncMock()
    runner = DuelRunner(client=client, db=db, api=api, annoncer=annoncer,
                        azrael_uid="7", stream_en_ligne=(lambda: stream))
    return runner, api, annoncer


async def _acheter(runner) -> None:
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw",
                        redemption_id="rd")


def _refus(annoncer):
    return [c.args[0] for c in annoncer.await_args_list if c.args[0].type == "refus"]


# ── Stream éteint ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_un_achat_stream_eteint_est_refuse_rembourse_et_annonce():
    runner, api, annoncer = _runner(stream=False)

    await _acheter(runner)

    assert runner.duel_en_cours is None, "aucun duel ne doit s'ouvrir"
    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    refus = _refus(annoncer)
    assert refus, "un refus muet est le pire résultat possible"
    assert "stream" in refus[0].donnees["motif"].lower(), (
        f"le motif doit dire la vraie raison : {refus[0].donnees['motif']!r}")


@pytest.mark.asyncio
async def test_un_statut_de_live_inconnu_ne_refuse_rien():
    """`None` = le watcher n'a pas encore sondé. Une absence de donnée n'est
    pas un stream éteint — sans ça, tout achat suivant un redémarrage serait
    refusé pendant la minute qui le suit."""
    runner, api, _ = _runner(stream=None)

    await _acheter(runner)

    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_en_ligne_le_duel_s_ouvre():
    runner, api, _ = _runner(stream=True)

    await _acheter(runner)

    assert runner.duel_en_cours is not None
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_sonde_de_live_en_erreur_ne_refuse_rien():
    """Un `stream_en_ligne` qui lève ne doit pas coûter son duel au viewer."""
    runner, api, _ = _runner(stream=True)

    def _casse():
        raise RuntimeError("watcher mort")

    runner._stream_en_ligne = _casse
    await _acheter(runner)

    assert runner.duel_en_cours is not None
    api.refund_redemption.assert_not_awaited()


# ── Azraël pas sur Apex ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_azrael_hors_dapex_le_duel_est_refuse_rembourse_et_annonce():
    runner, api, annoncer = _runner(azrael=_azrael(isOnline=0, isInGame=0))

    await _acheter(runner)

    assert runner.duel_en_cours is None
    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    refus = _refus(annoncer)
    assert refus, "un refus muet est le pire résultat possible"
    assert "apex" in refus[0].donnees["motif"].lower()


@pytest.mark.asyncio
async def test_azrael_entre_deux_parties_ne_fait_pas_refuser_le_duel():
    """LE contre-exemple. Azraël dans un menu, un lobby, une file d'attente :
    il est en ligne, il n'est simplement pas en partie — et c'est le moment le
    plus normal du monde pour acheter un duel. Refuser là-dessus (en lisant
    `isInGame` au lieu d'`isOnline`) casserait le cas nominal."""
    runner, api, _ = _runner(azrael=_azrael(isOnline=1, isInGame=0,
                                            currentStateAsText="In lobby"))

    await _acheter(runner)

    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_profil_dazrael_illisible_ne_refuse_rien():
    """L'API muette ne dit pas qu'Azraël est absent : elle ne dit rien. Une
    absence de donnée n'est jamais un zéro."""
    runner, api, _ = _runner(azrael="Apex API error: HTTP 500")

    await _acheter(runner)

    assert runner.duel_en_cours is not None
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_profil_sans_le_drapeau_en_ligne_ne_refuse_rien():
    """`isOnline` est présent dans tous les profils authentiques (bloc
    `realtime` listé exhaustivement le 2026-08-13). Son absence signe un
    payload dégradé, pas un compte hors ligne."""
    runner, api, _ = _runner(azrael=_azrael(isInGame=0))

    await _acheter(runner)

    assert runner.duel_en_cours is not None
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_la_saisie_du_viewer_ne_part_jamais_au_reseau_pour_autant():
    """La sonde du compte d'Azraël ne doit pas devenir un prétexte à envoyer
    une saisie aberrante à une API tierce : elle vient APRÈS la validation."""
    runner, api, _ = _runner()

    await runner.ouvrir(acheteur="bob", saisie="'; DROP TABLE--",
                        reward_id="rw", redemption_id="rd")

    envoye = str(runner._client.get.await_args_list)
    assert "DROP TABLE" not in envoye
    api.refund_redemption.assert_not_awaited()
