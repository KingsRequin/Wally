# tests/test_rattraper_memes.py
"""Le rattrapage de la banque de memes.

Le script touche un dossier bind-monté que le rotateur relit à chaque tirage, et
appelle un modèle de vision facturé à l'image. Ses deux promesses — « rien n'a
été écrit », « rien n'a été facturé » — ne tenaient ni l'une ni l'autre : la
simulation décrivait quand même (donc facturait), et la conversion écrivait ses
`.webp` d'essai DANS `data/memes/` avant de les supprimer.
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image

_CHEMIN = Path(__file__).resolve().parents[1] / "scripts" / "rattraper_memes.py"


def _module():
    spec = importlib.util.spec_from_file_location("rattraper_memes", _CHEMIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png(chemin: Path) -> Path:
    Image.new("RGB", (300, 300), (12, 200, 90)).save(chemin, "PNG")
    return chemin


def _vision_qui_compte(reponse="une description"):
    """Un faux `_vision` : `(service, base, modèle)`, et il note ce qu'on lui donne."""
    svc = AsyncMock()
    svc.available = True
    svc.analyze = AsyncMock(return_value=reponse)
    db = AsyncMock()

    async def _fabrique(_db_path):
        return svc, db, "gpt-5-nano"

    return _fabrique, svc


async def _lancer(module, monkeypatch, dossier: Path, *options):
    monkeypatch.setattr(
        sys, "argv", ["rattraper_memes.py", "--dossier", str(dossier), *options]
    )
    return await module.main()


@pytest.mark.asyncio
async def test_la_simulation_n_ecrit_rien_et_ne_facture_rien(tmp_path, monkeypatch, capsys):
    """Un appel « pour voir » est une dépense réelle sous un message qui dit
    l'inverse ; un `.webp` d'essai dans le dossier live est un orphelin que
    `empreintes()` prendra pour un meme à la moindre interruption."""
    module = _module()
    dossier = tmp_path / "memes"
    dossier.mkdir()
    _png(dossier / "meme1.png")

    def _interdit(*_a, **_k):
        raise AssertionError("aucun appel au modèle en simulation")

    monkeypatch.setattr(module, "_vision", _interdit)
    avant = {p.name for p in dossier.iterdir()}

    assert await _lancer(module, monkeypatch, dossier) == 0

    assert {p.name for p in dossier.iterdir()} == avant
    assert list(tmp_path.glob(".rattrapage-*")) == []  # l'atelier est nettoyé
    sortie = capsys.readouterr().out
    assert "rien n'a été facturé" in sortie
    assert "serait décrit" in sortie


@pytest.mark.asyncio
async def test_un_meme_deja_decrit_n_est_pas_redecrit(tmp_path, monkeypatch):
    module = _module()
    dossier = tmp_path / "memes"
    dossier.mkdir()
    # Des JPEG : le projet ne les convertit pas, le nom reste stable.
    _png(dossier / "meme1.jpg")
    (dossier / "meme1.jpg.txt").write_text("déjà décrit", encoding="utf-8")
    _png(dossier / "meme2.jpg")
    fabrique, svc = _vision_qui_compte()
    monkeypatch.setattr(module, "_vision", fabrique)

    await _lancer(module, monkeypatch, dossier, "--apply")

    assert svc.analyze.await_count == 1
    assert (dossier / "meme1.jpg.txt").read_text(encoding="utf-8") == "déjà décrit"
    assert (dossier / "meme2.jpg.txt").read_text(encoding="utf-8") == "une description"


@pytest.mark.asyncio
async def test_une_video_muette_est_laissee_sans_appel(tmp_path, monkeypatch, capsys):
    module = _module()
    dossier = tmp_path / "memes"
    dossier.mkdir()
    (dossier / "meme35.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    fabrique, svc = _vision_qui_compte()
    monkeypatch.setattr(module, "_vision", fabrique)

    await _lancer(module, monkeypatch, dossier, "--apply")

    assert svc.analyze.await_count == 0
    assert "pas d'analyse possible sur une vidéo" in capsys.readouterr().out
    assert not (dossier / "meme35.mp4.txt").exists()


@pytest.mark.asyncio
async def test_la_conversion_met_le_webp_en_place_sans_atelier_dans_la_banque(
    tmp_path, monkeypatch
):
    module = _module()
    dossier = tmp_path / "memes"
    dossier.mkdir()
    _png(dossier / "meme1.png")
    (dossier / "meme1.png.txt").write_text("un carré vert", encoding="utf-8")

    await _lancer(module, monkeypatch, dossier, "--apply", "--sans-decrire")

    assert (dossier / "meme1.webp").is_file()
    assert not (dossier / "meme1.png").exists()
    # Le sidecar suit le fichier, sinon la description se perd au renommage.
    assert (dossier / "meme1.webp.txt").read_text(encoding="utf-8") == "un carré vert"
    assert sorted(p.name for p in dossier.iterdir()) == ["meme1.webp", "meme1.webp.txt"]


@pytest.mark.asyncio
async def test_une_description_trop_longue_est_tronquee_a_l_ecriture(tmp_path, monkeypatch):
    """Même règle que `importer()` : `_describe` ne relira pas au-delà."""
    from bot.core.memes import MAX_DESCRIPTION

    module = _module()
    dossier = tmp_path / "memes"
    dossier.mkdir()
    _png(dossier / "meme1.jpg")
    fabrique, _ = _vision_qui_compte("Un chat très mécontent devant un écran. " * 10)
    monkeypatch.setattr(module, "_vision", fabrique)

    await _lancer(module, monkeypatch, dossier, "--apply")

    ecrit = (dossier / "meme1.jpg.txt").read_text(encoding="utf-8")
    assert len(ecrit) <= MAX_DESCRIPTION
