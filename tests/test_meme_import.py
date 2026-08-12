# tests/test_meme_import.py
"""Le module partagé d'import de memes.

La conversion vit ici et non plus dans `scripts/convertir_memes_webp.py` :
deux gardes anti-perte d'animation qui divergent, c'est un GIF aplati en
silence — Pillow le fait sur un fichier sur trois, avec 99 % de gain qui
ressemble à une réussite.
"""
from pathlib import Path

from PIL import Image

from bot.core import meme_import


def _gif_anime(chemin: Path, frames: int = 4, duree: int = 80) -> Path:
    images = []
    for i in range(frames):
        im = Image.new("RGB", (256, 256), (i * 60 % 255, 40, 200))
        images.append(im)
    images[0].save(chemin, "GIF", save_all=True, append_images=images[1:],
                   duration=duree, loop=0)
    return chemin


def test_un_gif_anime_reste_anime(tmp_path):
    src = _gif_anime(tmp_path / "danse.gif")
    dst = tmp_path / "danse.webp"

    meme_import.convertir(src, dst)

    assert meme_import.verifier_conversion(src, dst) == ""
    assert getattr(Image.open(dst), "n_frames", 1) == 4
    assert sum(meme_import.durees_webp(dst)) == 4 * 80


def test_une_conversion_qui_perd_l_animation_est_refusee(tmp_path):
    src = _gif_anime(tmp_path / "danse.gif")
    dst = tmp_path / "aplati.webp"
    Image.open(src).convert("RGB").save(dst, "WEBP")  # une seule frame

    assert "animation perdue" in meme_import.verifier_conversion(src, dst)


def test_le_sidecar_colle_a_l_extension_est_retrouve(tmp_path):
    image = tmp_path / "meme1.webp"
    image.write_bytes(b"x")
    (tmp_path / "meme1.webp.txt").write_text("un chat", encoding="utf-8")

    assert meme_import.sidecar_de(image).name == "meme1.webp.txt"
    assert meme_import.sidecar_de(tmp_path / "meme2.webp") is None


def test_le_script_de_conversion_ne_redefinit_pas_la_garde():
    """Le script partage l'objet, il n'en a pas une copie.

    Une identité d'objet, pas une lecture du source : le cliquet
    `test_aucun_test_ne_fige_une_ligne_de_code_source` refuse la seconde.
    """
    import importlib.util
    from pathlib import Path

    chemin = Path(__file__).resolve().parents[1] / "scripts" / "convertir_memes_webp.py"
    spec = importlib.util.spec_from_file_location("convertir_memes_webp", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.convertir is meme_import.convertir
    assert module.verifier_conversion is meme_import.verifier_conversion
