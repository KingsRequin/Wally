"""La liste des médias du rotateur.

La page la demande une fois puis tourne seule : elle doit donc être servie même
quand tout va mal, et surtout ne jamais lever une erreur qui laisserait la
source vide pour le reste du live.
"""
import pytest

from bot.core.memes import MemeLibrary
from bot.dashboard.routes.overlay import get_rotation


def _requete(state):
    return type("R", (), {
        "app": type("A", (), {"state": type("S", (), {"wally": state})()})()
    })()


@pytest.mark.asyncio
async def test_la_liste_donne_le_nom_et_le_genre(tmp_path):
    (tmp_path / "chat.webp").write_bytes(b"x")
    (tmp_path / "requin.mp4").write_bytes(b"x")
    state = type("W", (), {"memes": MemeLibrary(tmp_path)})()

    assert await get_rotation(_requete(state)) == {"medias": [
        {"nom": "chat.webp", "genre": "image"},
        {"nom": "requin.mp4", "genre": "video"},
    ]}


@pytest.mark.asyncio
async def test_un_dossier_absent_donne_une_liste_vide(tmp_path):
    """Et non une erreur : la page saurait quoi faire d'une liste vide, pas
    d'un 500 — elle réessaierait indéfiniment en croyant le bot cassé."""
    state = type("W", (), {"memes": MemeLibrary(tmp_path / "nexistepas")})()

    assert await get_rotation(_requete(state)) == {"medias": []}


@pytest.mark.asyncio
async def test_sans_bibliotheque_la_liste_est_vide():
    """Le bot peut démarrer sans bibliothèque de memes."""
    state = type("W", (), {})()

    assert await get_rotation(_requete(state)) == {"medias": []}
