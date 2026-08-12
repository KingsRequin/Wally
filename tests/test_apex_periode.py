# tests/test_apex_periode.py
"""Le parseur de périodes : un seul endroit qui décide de quelle fenêtre on parle.

L'action `progression`, le panneau d'overlay et la route image passent tous par
lui. Trois calculs séparés, c'est trois occasions qu'une carte passe la garde et
que l'image refuse ensuite de la tracer.
"""
import time

import pytest

from bot.core.apex.periode import (
    MAX_DUREE_S,
    Fenetre,
    libelle_de,
    parse_periode,
)

T0 = 1786500000.0        # un instant fixe : le parseur ne doit rien lire à l'horloge


def _depuis(texte, **kw):
    return parse_periode(texte, maintenant=T0, **kw).depuis


# ── Les durées libres ────────────────────────────────────────────────────────


@pytest.mark.parametrize("texte,secondes", [
    ("5m", 300), ("5min", 300), ("5 minutes", 300), ("45 minutes", 2700),
    ("2h", 7200), ("2 heures", 7200), ("1h30", 5400), ("3j", 3 * 86400),
    ("3 jours", 3 * 86400), ("90MIN", 5400), ("  2 h  ", 7200),
])
def test_une_duree_se_dit_comme_on_la_dit(texte, secondes):
    assert _depuis(texte) == pytest.approx(T0 - secondes)


def test_une_duree_porte_son_propre_libelle():
    assert parse_periode("30m", maintenant=T0).libelle == "sur les 30 dernières minutes"
    assert parse_periode("2h", maintenant=T0).libelle == "sur les 2 dernières heures"
    assert parse_periode("1j", maintenant=T0).libelle == "sur les dernières 24 heures"


# ── Les périodes nommées ─────────────────────────────────────────────────────


def test_les_periodes_nommees_gardent_leur_sens():
    from bot.core.apex.history import debut_de_periode

    for mot, cle in (("jour", "jour"), ("aujourd'hui", "jour"),
                     ("semaine", "semaine"), ("mois", "mois")):
        f = parse_periode(mot, maintenant=T0)
        assert f.cle == cle
        assert f.depuis == pytest.approx(debut_de_periode(cle, maintenant=T0))


def test_stream_part_du_debut_du_live():
    debut = T0 - 3 * 3600
    f = parse_periode("stream", maintenant=T0, debut_stream=debut)
    assert (f.depuis, f.cle) == (debut, "stream")
    assert f.libelle == "depuis le début du stream"


def test_live_et_session_disent_la_meme_chose_que_stream():
    debut = T0 - 600
    for mot in ("live", "session", "ce stream", "Ce Stream"):
        assert _depuis(mot, debut_stream=debut) == debut


def test_sans_stream_connu_on_refuse_au_lieu_d_inventer():
    """Un repli silencieux sur douze heures glissantes est exactement ce qu'on
    corrige : « la courbe de ce stream » rendait une image de quinze heures."""
    with pytest.raises(ValueError):
        parse_periode("stream", maintenant=T0, debut_stream=None)


# ── Les bornes et les refus ──────────────────────────────────────────────────


def test_une_periode_illisible_est_refusee_avec_les_formes_valides():
    with pytest.raises(ValueError) as erreur:
        parse_periode("depuis mardi dernier", maintenant=T0)
    message = str(erreur.value)
    assert "stream" in message and "jour" in message and "2h" in message


@pytest.mark.parametrize("texte", ["0m", "30s", "10 secondes"])
def test_sous_la_minute_on_refuse(texte):
    """Deux relevés espacés de 30 s au mieux : une fenêtre plus courte ne peut
    rien contenir, autant le dire plutôt que rendre une image vide."""
    with pytest.raises(ValueError):
        parse_periode(texte, maintenant=T0)


def test_au_dela_de_la_retention_on_refuse():
    with pytest.raises(ValueError):
        parse_periode("500j", maintenant=T0)
    assert _depuis("400j") == pytest.approx(T0 - MAX_DUREE_S)


# ── Le libellé reconstruit côté route image ──────────────────────────────────


def test_le_libelle_se_reconstruit_depuis_la_cle_et_l_instant():
    """La route image ne reçoit qu'un instant et une clé de liste blanche : son
    titre ne doit jamais venir d'un texte libre, il finit dessiné dans le PNG."""
    assert libelle_de("jour", T0 - 3600, maintenant=T0) == "aujourd'hui"
    assert libelle_de("stream", T0 - 3600, maintenant=T0) == "depuis le début du stream"
    assert libelle_de("duree", T0 - 1800, maintenant=T0) == "sur les 30 dernières minutes"


def test_une_cle_inconnue_ne_donne_pas_de_titre_menteur():
    assert libelle_de("licorne", T0 - 60, maintenant=T0) == ""


def test_la_fenetre_est_immuable():
    f = Fenetre(depuis=T0, cle="jour", libelle="aujourd'hui")
    with pytest.raises(Exception):
        f.depuis = 0        # type: ignore[misc]


def test_sans_horloge_fournie_le_parseur_utilise_maintenant():
    avant = time.time()
    depuis = parse_periode("1h").depuis
    assert avant - 3600 <= depuis <= time.time() - 3600 + 1


# ── Le début du live, tel que Twitch le date ─────────────────────────────────


def test_une_date_twitch_devient_un_instant():
    from datetime import datetime, timezone

    from bot.core.apex.periode import epoch_depuis_iso

    attendu = datetime(2026, 8, 12, 8, 3, tzinfo=timezone.utc).timestamp()
    assert epoch_depuis_iso("2026-08-12T08:03:00Z") == attendu
    assert epoch_depuis_iso("2026-08-12T08:03:00+00:00") == attendu


@pytest.mark.parametrize("valeur", [None, "", "bientôt", 0, {}])
def test_une_date_absente_ou_illisible_ne_devient_pas_un_instant(valeur):
    """Hors live, `started_at` est vide : rendre 0 ferait commencer « ce
    stream » en 1970 et tracerait toute l'histoire du compte."""
    from bot.core.apex.periode import epoch_depuis_iso

    assert epoch_depuis_iso(valeur) is None
