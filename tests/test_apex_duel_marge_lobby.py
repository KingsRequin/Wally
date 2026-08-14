# tests/test_apex_duel_marge_lobby.py
"""`marge_lobby_s` : le temps laissé aux compteurs avant de figer une manche.

La spec (§12 bis) la liste avec 10 s par défaut et un plafond DUR de 39 s —
l'intervalle mesuré entre un retour au lobby et le lancement de la partie
suivante. Elle n'existait nulle part : ce qui en tenait lieu était le debounce
anti-hoquet (deux relevés, ~4 s), qui n'est pas réglable et ne fait pas le même
travail — il décide si le retour au lobby est VRAI, il ne laisse pas aux
chiffres le temps d'arriver.

Le pari mesuré le 2026-08-13 (compteurs à jour au relevé même du retour au
lobby) tient sur deux parties d'une seule journée : cette marge est la
couverture de ce pari.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat, Releve
from bot.core.apex.duel_runner import (PLAFOND_MARGE_LOBBY_S, DuelRunner,
                                       marge_lobby_bornee)


def _en_manche(marge: float = 10.0, manches: int = 3) -> Duel:
    """Un duel en pleine manche, baselines à zéro des deux côtés."""
    d = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
             manches=manches, marge_lobby_s=marge)
    d.etat = Etat.MANCHE
    d._base_azrael = {"career_kills": 0}
    d._base_viewer = {"career_kills": 0}
    return d


def _kills(n: int) -> dict:
    return {"career_kills": n}


def test_un_compteur_en_retard_sur_le_lobby_est_quand_meme_compte():
    """Le cas que la marge existe pour couvrir.

    Si l'API publiait un jour les kills quelques secondes APRÈS le retour au
    lobby, le score serait figé sur des compteurs qui n'ont pas encore bougé —
    et la manche perdue pour celui qui venait de tuer. Sans marge, la manche se
    clôt sur le second relevé « hors partie », soit ici un 0 pour tout le monde.
    """
    d = _en_manche(marge=10)
    assert d.avancer(Releve(t=100, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=_kills(0), kills_viewer=_kills(0))) == []
    assert d.avancer(Releve(t=102, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=_kills(0), kills_viewer=_kills(0))) == []
    # Les compteurs se mettent à jour avec du retard.
    assert d.avancer(Releve(t=104, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=_kills(4), kills_viewer=_kills(2))) == []

    evts = d.avancer(Releve(t=112, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=_kills(4), kills_viewer=_kills(2)))

    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["azrael"] == 4
    assert fin.donnees["viewer"] == 2
    assert d.etat is Etat.ENTRE_MANCHES


def test_la_partie_suivante_ferme_la_manche_sans_attendre_la_marge():
    """La marge ne doit JAMAIS mordre sur la manche suivante.

    C'est tout le sens du plafond de 39 s. Si la partie d'après démarre pendant
    que la marge court, le score se fige immédiatement sur les compteurs les
    plus frais — sinon les kills des deux parties finiraient dans la même
    manche, et une seule partie compterait pour deux.
    """
    d = _en_manche(marge=30)
    d.avancer(Releve(t=100, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=_kills(3), kills_viewer=_kills(1)))
    d.avancer(Releve(t=102, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=_kills(3), kills_viewer=_kills(1)))

    # La partie suivante démarre 8 s après le lobby : la marge n'est pas
    # écoulée, mais attendre serait pire.
    evts = d.avancer(Releve(t=110, azrael_in_game=True, viewer_in_game=True,
                            kills_azrael=_kills(3), kills_viewer=_kills(1)))

    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["manche"] == 1
    assert fin.donnees["azrael"] == 3
    assert d.etat is Etat.ENTRE_MANCHES

    # Et la partie qui vient de démarrer ouvre bien une DEUXIÈME manche, avec
    # sa propre baseline : les kills de la première n'y sont pas rejoués.
    d.avancer(Releve(t=112, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=_kills(3), kills_viewer=_kills(1)))
    d.avancer(Releve(t=114, azrael_in_game=True, viewer_in_game=True,
                     kills_azrael=_kills(3), kills_viewer=_kills(1)))
    assert d.etat is Etat.MANCHE
    d.avancer(Releve(t=600, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=_kills(5), kills_viewer=_kills(1)))
    d.avancer(Releve(t=602, azrael_in_game=False, viewer_in_game=False,
                     kills_azrael=_kills(5), kills_viewer=_kills(1)))
    evts = d.avancer(Releve(t=632, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=_kills(5), kills_viewer=_kills(1)))
    fin2 = [e for e in evts if e.type == "manche_fin"][0]
    assert fin2.donnees["manche"] == 2
    assert fin2.donnees["azrael"] == 2, "2 kills de plus, pas les 5 du duel"


def test_un_hoquet_isole_ne_lance_pas_la_marge():
    """Le debounce garde son travail : une lecture « hors partie » isolée en
    pleine partie ne doit rien déclencher du tout. La marge ne commence à
    courir qu'une fois le retour au lobby CONFIRMÉ — sans quoi un hoquet à
    l'instant t clorait la manche 10 s plus tard, partie toujours en cours."""
    d = _en_manche(marge=10)
    assert d.avancer(Releve(t=100, azrael_in_game=False, viewer_in_game=False,
                            kills_azrael=_kills(1), kills_viewer=_kills(0))) == []
    # La partie continue réellement.
    assert d.avancer(Releve(t=102, azrael_in_game=True, viewer_in_game=True,
                            kills_azrael=_kills(1), kills_viewer=_kills(0))) == []
    assert d.etat is Etat.MANCHE
    # Et rien ne se clôt tout seul une fois la marge « écoulée ».
    assert d.avancer(Releve(t=200, azrael_in_game=True, viewer_in_game=True,
                            kills_azrael=_kills(2), kills_viewer=_kills(0))) == []
    assert d.etat is Etat.MANCHE


# ── Le plafond dur de 39 s ──────────────────────────────────────────────────
def test_une_marge_qui_approche_le_plafond_est_bornee():
    """39 s est le temps TOTAL disponible entre un retour au lobby et le
    lancement suivant. Le debounce en consomme déjà deux relevés : la somme des
    deux temporisations doit tenir dedans, sinon elles se marchent dessus."""
    for cadence in (1.0, 2.0, 5.0):
        marge = marge_lobby_bornee(600.0, cadence)
        assert 2 * cadence + marge <= PLAFOND_MARGE_LOBBY_S, (
            "la manche mordrait sur la suivante")
        assert marge > 0, "une marge bornée reste utilisable"


def test_une_marge_raisonnable_passe_intacte():
    assert marge_lobby_bornee(10.0, 2.0) == 10.0


def test_une_marge_negative_est_ramenee_a_zero():
    """Une absence de marge est un réglage acceptable ; une marge négative
    n'est rien du tout, et figerait le score avant le relevé."""
    assert marge_lobby_bornee(-30.0, 2.0) == 0.0


def test_une_cadence_qui_mange_tout_le_budget_annule_la_marge():
    """Sonder toutes les 30 s laisse déjà 60 s de debounce : il n'y a plus rien
    à distribuer, et rallonger encore ferait mordre la manche suivante."""
    assert marge_lobby_bornee(10.0, 30.0) == 0.0


# ── Du réglage jusqu'à la machine ───────────────────────────────────────────
def _runner(marge: float, cadence: float = 2.0) -> DuelRunner:
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    client = MagicMock()
    client.get = AsyncMock(return_value={
        "realtime": {"isOnline": 1, "isInGame": 0},
        "global": {"uid": "42"},
        "total": {"career_kills": {"name": "BR Kills", "value": 10}}})
    return DuelRunner(client=client, db=db, api=api, annoncer=AsyncMock(),
                      azrael_uid="7", cadence_s=cadence, marge_lobby_s=marge)


@pytest.mark.asyncio
async def test_le_reglage_atteint_le_duel_ouvert():
    """Un paramètre qui n'arrive pas jusqu'à `avancer()` est décoratif : on
    l'édite dans `config.yaml` sans le moindre effet."""
    runner = _runner(marge=7.0)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw",
                        redemption_id="rd")
    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.marge_lobby_s == 7.0


@pytest.mark.asyncio
async def test_le_reglage_survit_a_un_rebuild():
    runner = _runner(marge=7.0)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw",
                        redemption_id="rd")
    repris = Duel.from_dict(runner.duel_en_cours.to_dict())
    assert repris.marge_lobby_s == 7.0


def test_un_etat_persiste_avant_ce_reglage_se_recharge():
    """Un duel écrit par la version en production ne porte pas la clé. Il doit
    se recharger sans lever, et continuer à compter ses manches."""
    ancien = _en_manche(marge=10).to_dict()
    ancien.pop("marge_lobby_s")

    repris = Duel.from_dict(ancien)
    repris.avancer(Releve(t=100, azrael_in_game=False, viewer_in_game=False,
                          kills_azrael=_kills(4), kills_viewer=_kills(2)))
    repris.avancer(Releve(t=102, azrael_in_game=False, viewer_in_game=False,
                          kills_azrael=_kills(4), kills_viewer=_kills(2)))
    evts = repris.avancer(Releve(t=140, azrael_in_game=False, viewer_in_game=False,
                                 kills_azrael=_kills(4), kills_viewer=_kills(2)))
    fin = [e for e in evts if e.type == "manche_fin"][0]
    assert fin.donnees["azrael"] == 4
