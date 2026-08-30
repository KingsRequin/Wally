"""Le flux cognitif est une VITRINE : ce qu'on y lit passe par le filtre.

Les pensées de Wally s'affichent en direct sur le site public. Elles ne
passaient par aucun nettoyage de sortie — `strip_stage_directions` sert les
messages ADRESSÉS à quelqu'un, et une pensée n'est adressée à personne.

Résultat, vu à l'écran le 2026-08-30 juste après la passe sur les tirets : le
panneau du site en était toujours truffé, alors que les messages n'en avaient
plus. Une vitrine qui échappe au filtre est le pire endroit où le laisser.

Nettoyé au SERVICE et non à l'écriture : le fil de pensée que Wally se relit
garde son texte d'origine, et l'historique déjà en base est couvert lui aussi.
"""
import pytest

from bot.dashboard.routes.cognitive import _pour_le_public


def test_la_prose_d_un_evenement_perd_ses_tirets():
    evt = {"type": "THINK", "text": "je repense à ça — c'est un changement notable"}
    assert _pour_le_public(evt)["text"] == "je repense à ça, c'est un changement notable"


def test_tous_les_champs_de_prose_sont_couverts():
    evt = {
        "type": "DM_SUPPRESSED",
        "detail": "a — b", "message": "c — d", "content_snippet": "e — f",
        "full": "g — h", "reason": "i — j",
    }
    sortie = _pour_le_public(evt)
    for champ in ("detail", "message", "content_snippet", "full", "reason"):
        assert "—" not in sortie[champ], champ


def test_l_evenement_d_origine_n_est_pas_modifie():
    """Le tampon du feed est PARTAGÉ entre tous les abonnés SSE.

    Le nettoyer en place le ferait pour tout le monde, y compris pour les
    relectures internes, et deux fois de suite sur le même objet.
    """
    evt = {"type": "THINK", "text": "a — b"}
    _pour_le_public(evt)
    assert evt["text"] == "a — b"


@pytest.mark.parametrize("evt", [
    {"type": "DECIDE", "actions": ["THINK", "ACT"]},   # pas de prose
    {"type": "SLEEP"},                                  # rien du tout
])
def test_ce_qui_n_est_pas_de_la_prose_traverse_intact(evt):
    assert _pour_le_public(evt) == evt
