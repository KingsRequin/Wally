"""Envoi d'un meme DANS un salon Discord.

Wally n'avait qu'un outil meme, celui de l'overlay OBS. Demandé depuis Discord,
le meme partait donc devant les viewers Twitch et Wally répondait « c'est à
l'écran » — un écran que son interlocuteur ne voit pas. Depuis, la destination
suit la plateforme d'où vient la demande.
"""
import json
from pathlib import Path

import pytest

from bot.core.memes import MemeLibrary
from bot.tools.meme_tool import run_meme_tool_discord


class _Salon:
    """Le strict nécessaire de `discord.TextChannel` : `send(file=…)`."""

    def __init__(self, casse: bool = False):
        self.id = 42
        self.envois: list = []
        self._casse = casse

    async def send(self, *args, **kwargs):
        if self._casse:
            raise RuntimeError("Missing Permissions")
        self.envois.append(kwargs.get("file") or (args[0] if args else None))


class _Bot:
    def __init__(self, library):
        self.dashboard_state = type("S", (), {"memes": library})()


@pytest.fixture
def reserve(tmp_path):
    (tmp_path / "cheat.jpg").write_bytes(b"x")
    (tmp_path / "cheat.jpg.txt").write_text(
        "Moe jette le sac CHEATERS dehors", encoding="utf-8")
    (tmp_path / "chien.jpg").write_bytes(b"x")
    (tmp_path / "chien.jpg.txt").write_text(
        "un chien qui dort tranquillement", encoding="utf-8")
    return _Bot(MemeLibrary(tmp_path))


async def test_le_meme_part_dans_le_salon(reserve):
    salon = _Salon()
    rendu = json.loads(await run_meme_tool_discord(reserve, salon, {"about": "cheaters"}))
    assert rendu["status"] == "ok"
    assert len(salon.envois) == 1
    assert Path(salon.envois[0].filename).name == "cheat.jpg"


async def test_le_compte_rendu_porte_la_description(reserve):
    """Wally ne VOIT pas l'image : sans la description, il commente à l'aveugle."""
    salon = _Salon()
    rendu = json.loads(await run_meme_tool_discord(reserve, salon, {"about": "cheaters"}))
    assert "CHEATERS" in rendu["message"]


async def test_la_description_ne_part_pas_en_legende(reserve):
    """Elle est écrite POUR Wally. En légende, elle doublerait son commentaire
    et montrerait au salon une note qui ne lui était pas destinée."""
    salon = _Salon()
    await run_meme_tool_discord(reserve, salon, {"about": "cheaters"})
    assert all(not isinstance(envoi, str) for envoi in salon.envois)


async def test_un_sujet_absent_est_avoue_sans_rien_envoyer(reserve):
    """Le refus vient de `pick()`, qui rend None. Envoyer un meme au hasard
    ferait exactement ce qu'on vient de retirer du tirage par indice."""
    salon = _Salon()
    rendu = json.loads(
        await run_meme_tool_discord(reserve, salon, {"about": "astrophysique quantique"}))
    assert rendu["status"] == "empty"
    assert salon.envois == []


async def test_sans_indice_un_meme_part_quand_meme(reserve):
    salon = _Salon()
    rendu = json.loads(await run_meme_tool_discord(reserve, salon, {}))
    assert rendu["status"] == "ok" and len(salon.envois) == 1


async def test_sans_bibliotheque_il_le_dit(tmp_path):
    salon = _Salon()
    rendu = json.loads(await run_meme_tool_discord(_Bot(None), salon, {"about": "chat"}))
    assert rendu["status"] == "unavailable" and salon.envois == []


async def test_un_envoi_refuse_par_discord_ne_ment_pas(reserve):
    """Sans permission de joindre un fichier, `send` lève. Rendre « ok » ferait
    annoncer un meme que personne n'a reçu."""
    salon = _Salon(casse=True)
    rendu = json.loads(await run_meme_tool_discord(reserve, salon, {"about": "cheaters"}))
    assert rendu["status"] == "error"


async def test_une_reserve_vide_est_avouee(tmp_path):
    salon = _Salon()
    rendu = json.loads(
        await run_meme_tool_discord(_Bot(MemeLibrary(tmp_path)), salon, {"about": "chat"}))
    assert rendu["status"] == "empty" and salon.envois == []
