"""Le moteur du sondage Discord : voter, changer d'avis, dépouiller."""
from __future__ import annotations

import pytest

from bot.core.sondage import (
    EMOJIS_VOTE,
    MAX_OPTIONS,
    Sondage,
    Sondages,
    creer,
    emoji_pour,
    index_de_emoji,
)


def _sondage(**kw) -> Sondage:
    s = creer("Quel jeu ce soir ?", ["Apex", "Rocket League", "Minecraft"],
              channel_id=42, **kw)
    assert s is not None
    s.message_id = 7
    return s


# ── création ────────────────────────────────────────────────────────────────

def test_creer_refuse_moins_de_deux_options():
    assert creer("Alors ?", ["seule"], channel_id=1) is None


def test_creer_refuse_une_question_vide():
    assert creer("   ", ["a", "b"], channel_id=1) is None


def test_creer_ignore_les_options_vides_et_dedoublonne_pas():
    s = creer("Q ?", ["a", "  ", "b"], channel_id=1)
    assert s is not None and s.options == ["a", "b"]


def test_creer_plafonne_le_nombre_d_options():
    s = creer("Q ?", [f"opt{i}" for i in range(20)], channel_id=1)
    assert s is not None and len(s.options) == MAX_OPTIONS


def test_creer_pose_l_echeance_en_temps_mural():
    """`monotonic` repart de zéro au rebuild : l'échéance serait absurde."""
    s = creer("Q ?", ["a", "b"], channel_id=1, duree_s=600, maintenant=1_000.0)
    assert s is not None and s.ends_at == 1_600.0


def test_creer_sans_duree_reste_ouvert():
    s = creer("Q ?", ["a", "b"], channel_id=1)
    assert s is not None and s.ends_at is None and not s.expire(1e12)


# ── emoji ↔ index ───────────────────────────────────────────────────────────

def test_les_emojis_couvrent_le_maximum_d_options():
    assert len(EMOJIS_VOTE) == MAX_OPTIONS


def test_aller_retour_emoji_index():
    for i in range(MAX_OPTIONS):
        assert index_de_emoji(emoji_pour(i)) == i


def test_un_emoji_etranger_ne_vaut_pas_un_vote():
    assert index_de_emoji("🍕") is None


def test_l_emoji_sans_variateur_est_reconnu():
    """Certains clients envoient « 1⃣ » sans U+FE0F ; c'est le même vote."""
    assert index_de_emoji("1⃣") == 0


# ── vote ────────────────────────────────────────────────────────────────────

def test_un_vote_compte():
    s = _sondage()
    assert s.voter("u1", 0) is True
    assert s.depouiller().tally == [1, 0, 0]


def test_revoter_la_meme_option_ne_change_rien():
    s = _sondage()
    s.voter("u1", 0)
    assert s.voter("u1", 0) is False


def test_changer_d_avis_annule_le_premier_vote():
    """La demande de l'owner : le premier vote est annulé, seul le second compte."""
    s = _sondage()
    s.voter("u1", 0)
    assert s.voter("u1", 2) is True
    assert s.depouiller().tally == [0, 0, 1]
    assert s.depouiller().total == 1


def test_vote_hors_bornes_ignore():
    s = _sondage()
    assert s.voter("u1", 9) is False
    assert s.voter("u1", -1) is False
    assert s.depouiller().total == 0


def test_un_sondage_clos_ne_prend_plus_de_vote():
    s = _sondage()
    s.clos = True
    assert s.voter("u1", 0) is False


def test_retirer_sa_reaction_retire_son_vote():
    s = _sondage()
    s.voter("u1", 1)
    assert s.retirer("u1", 1) is True
    assert s.depouiller().total == 0


def test_retirer_une_reaction_qui_n_est_plus_son_vote_ne_fait_rien():
    """Quand Wally retire l'ancienne réaction, l'événement revient : sans cette
    garde, le nouveau vote serait effacé par l'écho du précédent."""
    s = _sondage()
    s.voter("u1", 0)
    s.voter("u1", 2)
    assert s.retirer("u1", 0) is False
    assert s.depouiller().tally == [0, 0, 1]


# ── dépouillement ───────────────────────────────────────────────────────────

def test_depouillement_designe_le_gagnant():
    s = _sondage()
    s.voter("u1", 1)
    s.voter("u2", 1)
    s.voter("u3", 0)
    r = s.depouiller()
    assert (r.gagnant, r.total, r.egalite) == (1, 3, False)


def test_egalite_ne_designe_personne():
    s = _sondage()
    s.voter("u1", 0)
    s.voter("u2", 1)
    r = s.depouiller()
    assert r.gagnant is None and r.egalite is True


def test_sans_vote_il_n_y_a_pas_d_egalite():
    r = _sondage().depouiller()
    assert r.gagnant is None and r.egalite is False and r.total == 0


def test_ligne_resultat_nomme_le_gagnant():
    s = _sondage()
    s.voter("u1", 0)
    ligne = s.ligne_resultat()
    assert "Apex" in ligne and "Quel jeu ce soir" in ligne


def test_ligne_resultat_dit_l_egalite():
    s = _sondage()
    s.voter("u1", 0)
    s.voter("u2", 1)
    assert "égalité" in s.ligne_resultat().lower()


def test_ligne_resultat_sans_vote():
    assert "aucun vote" in _sondage().ligne_resultat().lower()


# ── recomptage depuis les réactions ─────────────────────────────────────────

def test_recompter_prend_les_reactions_pour_verite():
    """Au boot, les votes rangés peuvent être en retard : Discord fait foi."""
    s = _sondage()
    s.voter("u1", 0)
    s.recompter({"1⃣️": ["u2"], EMOJIS_VOTE[2]: ["u3", "u4"]})
    assert s.depouiller().tally == [1, 0, 2]
    assert s.votes == {"u2": 0, "u3": 2, "u4": 2}


def test_recompter_ignore_un_emoji_etranger():
    s = _sondage()
    s.recompter({"🍕": ["u1"], EMOJIS_VOTE[0]: ["u2"]})
    assert s.depouiller().tally == [1, 0, 0]


def test_recompter_garde_le_premier_vote_d_un_double_votant():
    """Deux réactions survivantes (Wally était éteint) : l'ordre des emojis
    tranche, comme le repli sans `manage_messages`."""
    s = _sondage()
    s.recompter({EMOJIS_VOTE[2]: ["u1"], EMOJIS_VOTE[0]: ["u1"]})
    assert s.votes == {"u1": 0}


# ── expiration ──────────────────────────────────────────────────────────────

def test_expire_quand_l_echeance_est_passee():
    s = creer("Q ?", ["a", "b"], channel_id=1, duree_s=60, maintenant=100.0)
    assert s is not None
    assert not s.expire(159.0)
    assert s.expire(161.0)


def test_restant_ne_descend_pas_sous_zero():
    s = creer("Q ?", ["a", "b"], channel_id=1, duree_s=60, maintenant=100.0)
    assert s is not None and s.restant(500.0) == 0.0


# ── registre + persistance ──────────────────────────────────────────────────

def test_le_registre_retrouve_par_message_et_par_salon():
    reg = Sondages()
    s = _sondage()
    reg.ajouter(s)
    assert reg.par_message(7) is s
    assert reg.ouvert_dans(42) is s


def test_un_sondage_clos_n_est_plus_ouvert_dans_son_salon():
    reg = Sondages()
    s = _sondage()
    reg.ajouter(s)
    s.clos = True
    assert reg.ouvert_dans(42) is None


def test_le_registre_survit_a_un_aller_retour_json():
    reg = Sondages()
    s = _sondage(duree_s=300, maintenant=1_000.0)
    s.voter("u1", 1)
    reg.ajouter(s)

    repris = Sondages()
    repris.from_dict(reg.to_dict())
    r = repris.par_message(7)
    assert r is not None
    assert (r.question, r.options, r.votes) == (s.question, s.options, s.votes)
    assert (r.ends_at, r.channel_id) == (1_300.0, 42)


def test_le_registre_ne_reprend_pas_les_sondages_clos():
    """Rien à rouvrir : un sondage dépouillé n'a plus rien à faire en mémoire."""
    reg = Sondages()
    s = _sondage()
    s.clos = True
    reg.ajouter(s)
    repris = Sondages()
    repris.from_dict(reg.to_dict())
    assert repris.par_message(7) is None


@pytest.mark.parametrize("charge", [None, {}, {"sondages": "pas une liste"},
                                    {"sondages": [{"question": "orpheline"}]}])
def test_une_reprise_abimee_ne_leve_pas(charge):
    reg = Sondages()
    reg.from_dict(charge)
    assert reg.ouverts() == []
