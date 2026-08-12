# tests/test_apex_history.py
"""L'historique des compteurs Apex, et les pièges de sa lecture.

L'API ne donne que des totaux à vie : « combien de kills ce mois-ci » se
calcule en relevant les compteurs au fil du temps. Ce qui rend l'exercice
délicat, ce sont les trackers — le joueur les épingle et les dépingle en jeu,
et le total bouge sans qu'une partie ait été jouée.
"""
from datetime import datetime

import pytest
import pytest_asyncio

from bot.core.apex.history import (
    PARIS,
    ApexHistory,
    debut_de_periode,
    plafond_plausible,
)
from bot.db.database import Database

UID = "1002761549602"
HEURE = 3600.0
JOUR = 86400.0


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


@pytest_asyncio.fixture
async def hist(db):
    return ApexHistory(db)


async def _releve(hist, t: float, kills: int, uid: str = UID) -> None:
    await hist.enregistrer(uid, {"kills": kills}, maintenant=t)


# ── Écriture ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_compteur_immobile_n_ecrit_rien(hist):
    """La sonde passe toutes les 30 s. Une nuit sans jouer, c'est 2 800 lignes
    identiques — et autant d'écritures sur une base partagée par tout le bot."""
    assert await hist.enregistrer(UID, {"kills": 500}, maintenant=1000.0) == 1
    assert await hist.enregistrer(UID, {"kills": 500}, maintenant=1030.0) == 0
    assert await hist.enregistrer(UID, {"kills": 500}, maintenant=1060.0) == 0


@pytest.mark.asyncio
async def test_un_changement_est_consigne(hist):
    await hist.enregistrer(UID, {"kills": 500}, maintenant=1000.0)
    assert await hist.enregistrer(UID, {"kills": 507}, maintenant=1030.0) == 1


@pytest.mark.asyncio
async def test_la_valeur_connue_est_relue_de_la_base(db):
    """Après un redémarrage, le cache mémoire est vide : sans relecture, le
    premier passage réécrirait une valeur déjà consignée."""
    await ApexHistory(db).enregistrer(UID, {"kills": 500}, maintenant=1000.0)
    autre = ApexHistory(db)          # process neuf
    assert await autre.enregistrer(UID, {"kills": 500}, maintenant=2000.0) == 0


# ── Calcul du gain ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_gain_est_la_somme_des_ecarts(hist):
    await _releve(hist, 1000.0, 500)
    await _releve(hist, 1000.0 + HEURE, 520)
    await _releve(hist, 1000.0 + 2 * HEURE, 545)
    p = await hist.progression(UID, "kills", 0.0, maintenant=1000.0 + 3 * HEURE)
    assert p is not None and p.gain == 45


@pytest.mark.asyncio
async def test_une_chute_de_tracker_ne_compte_pas_comme_une_regression(hist):
    """Un tracker dépinglé fait tomber le total : le joueur n'a rien perdu."""
    await _releve(hist, 1000.0, 500)
    await _releve(hist, 1000.0 + HEURE, 120)      # tracker retiré
    await _releve(hist, 1000.0 + 2 * HEURE, 130)
    p = await hist.progression(UID, "kills", 0.0)
    assert p is not None and p.gain == 10


@pytest.mark.asyncio
async def test_un_bond_de_tracker_n_est_pas_de_la_progression(hist):
    """Le piège coûteux : « +10 142 kills » annoncé en direct.

    Azraël porte « BR Kills » sur deux trackers (92 182 et 10 142) qui
    s'additionnent. Réépingler l'un d'eux fait bondir le total en une sonde.
    """
    await _releve(hist, 1000.0, 92_182)
    await _releve(hist, 1030.0, 102_324)          # +10 142 en 30 secondes
    p = await hist.progression(UID, "kills", 0.0)
    assert p is not None and p.gain == 0


@pytest.mark.asyncio
async def test_un_gros_gain_sur_une_longue_absence_reste_credible(hist):
    """Deux semaines entre deux consultations : +900 kills est réel.

    Un plafond exprimé en valeur absolue, et non en taux, rejetterait ce gain.
    """
    await _releve(hist, 1000.0, 500)
    await _releve(hist, 1000.0 + 14 * JOUR, 1400)
    p = await hist.progression(UID, "kills", 0.0)
    assert p is not None and p.gain == 900


def test_le_plafond_croit_avec_l_intervalle():
    assert plafond_plausible(30) < plafond_plausible(HEURE) < plafond_plausible(JOUR)


# ── Fenêtres ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_releve_precedant_la_fenetre_sert_de_depart(hist):
    """Sans lui, le premier gain de la période serait invisible.

    Encore faut-il qu'il soit PROCHE : un relevé d'il y a des heures ne dit pas
    quand son gain a été fait (cf. le test du relevé lointain)."""
    await _releve(hist, 3800.0, 500)                    # 200 s avant la fenêtre
    await _releve(hist, 5000.0, 530)
    p = await hist.progression(UID, "kills", 4000.0)
    assert p is not None and p.gain == 30 and p.complet


@pytest.mark.asyncio
async def test_une_fenetre_non_couverte_est_signalee(hist):
    """« Ce mois-ci » alors qu'on ne mesure que depuis le 12 : le total est
    exact pour ce qu'il couvre, mais il ne couvre pas le mois."""
    await _releve(hist, 4000.0 + 3 * JOUR, 500)
    await _releve(hist, 4000.0 + 3 * JOUR + 600, 530)
    p = await hist.progression(UID, "kills", 4000.0)
    assert p is not None and p.couverture_partielle


@pytest.mark.asyncio
async def test_sans_aucun_releve_il_n_y_a_pas_de_progression(hist):
    assert await hist.progression(UID, "kills", 0.0) is None


def test_les_periodes_se_decoupent_a_l_heure_de_paris():
    """La machine tourne en UTC : découper « aujourd'hui » là-dessus ferait
    commencer la journée à 2 h du matin, en plein live du soir."""
    t = datetime(2026, 8, 11, 0, 30, tzinfo=PARIS).timestamp()
    debut = datetime.fromtimestamp(debut_de_periode("jour", maintenant=t), PARIS)
    assert (debut.day, debut.hour) == (11, 0)


def test_le_mois_commence_au_premier():
    t = datetime(2026, 8, 11, 14, 0, tzinfo=PARIS).timestamp()
    debut = datetime.fromtimestamp(debut_de_periode("mois", maintenant=t), PARIS)
    assert (debut.day, debut.month, debut.hour) == (1, 8, 0)


# ── Consultations manuelles ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_depuis_la_derniere_consultation(hist):
    """Les comptes non sondés n'ont pour historique que leurs consultations."""
    await _releve(hist, 1000.0, 500)
    await _releve(hist, 1000.0 + 4 * HEURE, 624)
    p = await hist.depuis_derniere_consultation(
        UID, "kills", avant=1000.0 + 4 * HEURE
    )
    assert p is not None and p.gain == 124


@pytest.mark.asyncio
async def test_redemander_tout_de_suite_ne_dit_rien(hist):
    """« +0 kill depuis tout à l'heure » n'apprend rien, et on redemande souvent."""
    await _releve(hist, 1000.0, 500)
    await _releve(hist, 1060.0, 502)
    assert await hist.depuis_derniere_consultation(UID, "kills", avant=1060.0) is None


@pytest.mark.asyncio
async def test_une_premiere_consultation_n_a_pas_de_precedent(hist):
    await _releve(hist, 1000.0, 500)
    assert await hist.depuis_derniere_consultation(UID, "kills", avant=1000.0) is None


@pytest.mark.asyncio
async def test_les_comptes_ne_se_melangent_pas(hist):
    await _releve(hist, 1000.0, 500, uid="aaa")
    await _releve(hist, 1000.0 + HEURE, 999, uid="bbb")
    p = await hist.progression("aaa", "kills", 0.0)
    assert p is not None and p.gain == 0


# ── Rétention ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_les_vieux_releves_sont_purges(db):
    hist = ApexHistory(db, retention_jours=30)
    await hist.enregistrer(UID, {"kills": 1}, maintenant=1000.0)
    # Un an plus tard : la purge tourne (au plus une fois par jour).
    await hist.enregistrer(UID, {"kills": 2}, maintenant=1000.0 + 365 * JOUR)
    rows = await db.fetch_all("SELECT value FROM apex_stat_points ORDER BY value")
    assert [int(r["value"]) for r in rows] == [2]


# ── Le dernier bloc de jeu ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_derniere_session_commence_apres_le_dernier_grand_trou(hist):
    """« La courbe de ce stream » quand le stream est fini : on repart du
    dernier bloc de relevés, pas d'une fenêtre glissante de douze heures."""
    for i, kills in enumerate((500, 503, 506)):        # une soirée d'hier
        await _releve(hist, 1000.0 + i * 600, kills)
    debut_soir = 1000.0 + 3 * JOUR                     # deux jours plus tard
    for i, kills in enumerate((510, 514, 520)):
        await _releve(hist, debut_soir + i * 600, kills)
    assert await hist.debut_derniere_session(
        UID, maintenant=debut_soir + 3600
    ) == pytest.approx(debut_soir)


@pytest.mark.asyncio
async def test_une_pause_courte_ne_coupe_pas_la_session(hist):
    """Un lobby, un pipi, une partie qui traîne : dix minutes sans relevé ne
    sont pas la fin du stream."""
    await _releve(hist, 1000.0, 500)
    await _releve(hist, 1000.0 + 600, 505)
    await _releve(hist, 1000.0 + 1200, 509)
    assert await hist.debut_derniere_session(
        UID, maintenant=1000.0 + 1800
    ) == pytest.approx(1000.0)


@pytest.mark.asyncio
async def test_sans_aucun_releve_il_n_y_a_pas_de_session(hist):
    assert await hist.debut_derniere_session("inconnu") is None


@pytest.mark.asyncio
async def test_la_session_ne_melange_pas_les_comptes(hist):
    await _releve(hist, 1000.0, 500, uid="aaa")
    await _releve(hist, 1000.0 + 5 * JOUR, 900, uid="bbb")
    assert await hist.debut_derniere_session(
        "aaa", maintenant=1000.0 + 3600
    ) == pytest.approx(1000.0)


# ── Le point de contexte, et jusqu'où il est légitime ────────────────────────

@pytest.mark.asyncio
async def test_un_releve_juste_avant_la_fenetre_donne_le_vrai_depart(hist):
    """Deux relevés à cheval sur minuit : le gain du premier appartient bien à
    la journée qui commence — sans lui, il serait perdu."""
    debut = debut_de_periode("jour")
    await _releve(hist, debut - 300, 500)
    await _releve(hist, debut + 300, 507)
    p = await hist.progression(UID, "kills", debut)
    assert p is not None and p.gain == 7
    assert p.complet is True


@pytest.mark.asyncio
async def test_un_releve_lointain_n_est_pas_le_depart_de_la_fenetre(hist):
    """Le cas vécu : « la courbe de ce stream » annonçait +74 kills quand
    l'image en traçait 63. Le relevé précédent datait de neuf heures — les onze
    kills de la nuit tombaient dans le stream du matin. On ne sait pas QUAND ils
    ont été faits : on ne les attribue pas."""
    debut = debut_de_periode("jour")
    await _releve(hist, debut - 9 * HEURE, 500)     # la veille au soir
    await _releve(hist, debut + 300, 511)           # première partie du matin
    await _releve(hist, debut + 900, 514)
    p = await hist.progression(UID, "kills", debut)
    assert p is not None and p.gain == 3


@pytest.mark.asyncio
async def test_une_fenetre_qui_commence_a_son_premier_releve_est_complete(hist):
    """« Ce stream » commence quelques minutes avant la première partie : rien
    n'est manquant, et annoncer un minimum serait une réserve inutile."""
    debut = 100_000.0
    await _releve(hist, debut - 9 * HEURE, 500)
    await _releve(hist, debut + 120, 505)
    p = await hist.progression(UID, "kills", debut)
    assert p is not None and p.complet is True


@pytest.mark.asyncio
async def test_une_fenetre_qui_precede_les_mesures_reste_partielle(hist):
    """« Ce mois-ci » alors qu'on ne mesure que depuis le 12 : c'est un
    minimum, et la réponse doit le dire."""
    debut = debut_de_periode("mois")
    await _releve(hist, debut + 10 * JOUR, 500)
    await _releve(hist, debut + 10 * JOUR + 600, 505)
    p = await hist.progression(UID, "kills", debut)
    assert p is not None and p.couverture_partielle is True
