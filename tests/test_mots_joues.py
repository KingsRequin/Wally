"""Mémoire des mots de pendu déjà joués — le sac sans remise à l'envers.

Prod du 2026-08-31 : deux parties d'affilée sur « peacekeeper ». Rien ne
gardait trace de la partie précédente.
"""
import json

from bot.core.mots_joues import MotsJoues


class FakeDB:
    def __init__(self, valeurs=None):
        self.valeurs = dict(valeurs or {})

    async def get_state(self, cle):
        return self.valeurs.get(cle)

    async def set_state(self, cle, valeur):
        self.valeurs[cle] = valeur


async def test_un_mot_joue_est_refuse_a_la_partie_suivante():
    m = MotsJoues(FakeDB(), "k")
    assert not m.deja_joue("peacekeeper")
    m.retenir("peacekeeper")
    assert m.deja_joue("peacekeeper")


async def test_la_casse_et_les_accents_ne_contournent_pas_la_memoire():
    """Sans pliage, « Péacekeeper » passerait pour un mot neuf."""
    m = MotsJoues(FakeDB(), "k")
    m.retenir("Péacekeeper")
    assert m.deja_joue("peacekeeper")
    assert m.deja_joue("PEACEKEEPER")


async def test_un_mot_ancien_redevient_jouable_apres_la_taille_du_sac():
    m = MotsJoues(FakeDB(), "k", taille=3)
    for mot in ("un", "deux", "trois"):
        m.retenir(mot)
    assert m.deja_joue("un")
    m.retenir("quatre")          # « un » sort du sac
    assert not m.deja_joue("un")
    assert m.deja_joue("deux")


async def test_les_recents_sont_du_plus_recent_au_plus_ancien():
    """C'est l'ordre dans lequel le refus les cite à Wally."""
    m = MotsJoues(FakeDB(), "k")
    for mot in ("alpha", "bravo", "charlie"):
        m.retenir(mot)
    assert m.recents == ["charlie", "bravo", "alpha"]


async def test_la_memoire_traverse_un_redemarrage():
    db = FakeDB()
    m = MotsJoues(db, "k")
    m.retenir("gibraltar")
    await m._ecrire()            # le rangement de fond, joué à la main

    suivant = MotsJoues(db, "k")
    await suivant.charger()
    assert suivant.deja_joue("gibraltar")


async def test_une_base_illisible_laisse_jouer_plutot_que_de_bloquer():
    """Sans mémoire on répète — on ne casse pas le jeu pour autant."""
    db = FakeDB({"k": "{ceci n'est pas du JSON"})
    m = MotsJoues(db, "k")
    await m.charger()
    assert not m.deja_joue("peacekeeper")


async def test_rejouer_un_mot_le_remonte_en_tete_au_lieu_de_le_laisser_vieillir():
    m = MotsJoues(FakeDB(), "k", taille=2)
    m.retenir("un")
    m.retenir("deux")
    m.retenir("un")              # rejoué : c'est lui le plus récent
    m.retenir("trois")           # chasse « deux », pas « un »
    assert m.deja_joue("un")
    assert not m.deja_joue("deux")


async def test_le_mot_range_est_du_json_relisible():
    db = FakeDB()
    m = MotsJoues(db, "k")
    m.retenir("wattson")
    await m._ecrire()
    assert json.loads(db.valeurs["k"]) == ["wattson"]
