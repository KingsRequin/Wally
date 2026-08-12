# tests/test_meme_import.py
"""Le module partagé d'import de memes.

La conversion vit ici et non plus dans `scripts/convertir_memes_webp.py` :
deux gardes anti-perte d'animation qui divergent, c'est un GIF aplati en
silence — Pillow le fait sur un fichier sur trois, avec 99 % de gain qui
ressemble à une réussite.
"""
from pathlib import Path

import pytest
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


def test_le_prochain_numero_suit_le_maximum(tmp_path):
    for nom in ("meme3.webp", "meme7.jpg", "meme7.jpg.txt"):
        (tmp_path / nom).write_bytes(b"x")

    assert meme_import.prochain_numero(tmp_path) == 8


def test_un_sidecar_orphelin_reserve_son_numero(tmp_path):
    """Sinon le numéro est réattribué et l'ancien .txt décrit une autre image."""
    (tmp_path / "meme4.webp").write_bytes(b"x")
    (tmp_path / "meme9.webp.txt").write_text("image supprimée", encoding="utf-8")

    assert meme_import.prochain_numero(tmp_path) == 10


def test_un_dossier_vide_commence_a_un(tmp_path):
    assert meme_import.prochain_numero(tmp_path) == 1


def test_les_memes_sans_sidecar_sont_reperes(tmp_path):
    (tmp_path / "meme1.webp").write_bytes(b"a")
    (tmp_path / "meme1.webp.txt").write_text("décrit", encoding="utf-8")
    (tmp_path / "meme2.png").write_bytes(b"b")
    (tmp_path / "meme3.jpg").write_bytes(b"c")
    (tmp_path / "meme3.txt").write_text("forme sans extension", encoding="utf-8")

    muets = meme_import.memes_sans_description(tmp_path)

    assert [p.name for p in muets] == ["meme2.png"]


def test_les_empreintes_indexent_les_fichiers_presents(tmp_path):
    (tmp_path / "meme1.webp").write_bytes(b"contenu")
    (tmp_path / "meme1.webp.txt").write_text("desc", encoding="utf-8")

    index = meme_import.empreintes(tmp_path)

    import hashlib
    assert index[hashlib.sha256(b"contenu").hexdigest()] == "meme1.webp"
    assert len(index) == 1  # le .txt n'est pas un meme


def test_un_png_est_converti_quand_il_y_gagne(tmp_path):
    src = tmp_path / "gros.png"
    Image.new("RGB", (400, 400), (200, 30, 30)).save(src, "PNG")

    octets, suffixe = meme_import.convertir_si_avantageux(src.read_bytes(), ".png")

    assert suffixe == ".webp"
    assert len(octets) < src.stat().st_size


def test_un_jpeg_n_est_jamais_converti(tmp_path):
    src = tmp_path / "photo.jpg"
    Image.new("RGB", (200, 200), (10, 10, 10)).save(src, "JPEG")
    original = src.read_bytes()

    octets, suffixe = meme_import.convertir_si_avantageux(original, ".jpg")

    assert (octets, suffixe) == (original, ".jpg")


def test_l_import_ecrit_l_image_et_son_sidecar(tmp_path):
    src = tmp_path / "src.png"
    Image.new("RGB", (120, 120), (0, 120, 255)).save(src, "PNG")
    octets = src.read_bytes()
    src.unlink()

    res = meme_import.importer(octets, ".png", "un carré bleu", tmp_path)

    assert res.ok is True
    assert res.nom == "meme1.webp"
    assert res.converti is True
    assert (tmp_path / "meme1.webp").is_file()
    assert (tmp_path / "meme1.webp.txt").read_text(encoding="utf-8") == "un carré bleu"


def test_un_doublon_n_est_pas_range_deux_fois(tmp_path):
    src = tmp_path / "src.png"
    Image.new("RGB", (120, 120), (0, 120, 255)).save(src, "PNG")
    octets = src.read_bytes()
    src.unlink()
    premier = meme_import.importer(octets, ".png", "un carré bleu", tmp_path)

    second = meme_import.importer(octets, ".png", "le même", tmp_path)

    assert second.ok is False
    assert second.doublon == premier.nom
    assert not (tmp_path / "meme2.webp").exists()
    assert not (tmp_path / "meme2.webp.txt").exists()


def test_un_fichier_trop_lourd_est_refuse(tmp_path):
    from bot.core.memes import _MAX_BYTES

    res = meme_import.importer(b"\x00" * (_MAX_BYTES + 1), ".jpg", "trop gros", tmp_path)

    assert res.ok is False
    assert "8" in res.raison  # le plafond figure dans le message
    assert list(tmp_path.iterdir()) == []


def test_une_extension_inconnue_est_refusee(tmp_path):
    res = meme_import.importer(b"MZ", ".exe", "non merci", tmp_path)

    assert res.ok is False
    assert ".exe" in res.raison


def test_une_video_est_acceptee_sans_conversion(tmp_path):
    res = meme_import.importer(b"\x00\x00\x00\x18ftypmp42", ".mp4", "un clip", tmp_path)

    assert res.ok is True
    assert res.nom == "meme1.mp4"
    assert res.converti is False


def test_une_description_vide_n_ecrit_pas_de_sidecar(tmp_path):
    """Sans description, `_describe` retombe sur le nom du fichier — un sidecar
    vide ferait pire, en donnant une description vraiment vide."""
    res = meme_import.importer(b"\x00\x00\x00\x18ftypmp42", ".mp4", "   ", tmp_path)

    assert res.ok is True
    assert not (tmp_path / "meme1.mp4.txt").exists()


def test_un_fichier_au_nom_libre_est_detecte_comme_doublon(tmp_path):
    """Les noms libres sont acceptés : mon-image.jpg est une convention valide."""
    # Créer un fichier au nom libre
    src = tmp_path / "azrael-blame-le-ping.jpg"
    Image.new("RGB", (100, 100), (255, 0, 0)).save(src, "JPEG")
    octets = src.read_bytes()

    # Essayer d'importer les mêmes octets via importer()
    res = meme_import.importer(octets, ".jpg", "mon image", tmp_path)

    # Doit être refusé comme doublon
    assert res.ok is False
    assert res.doublon == "azrael-blame-le-ping.jpg"
    assert not (tmp_path / "meme1.jpg").exists()
    assert not (tmp_path / "meme1.jpg.txt").exists()


def test_un_sidecar_qui_echoue_ne_laisse_pas_l_image_orpheline(tmp_path, monkeypatch):
    """L'écriture est en deux temps (image puis sidecar) : si le second échoue,
    le premier ne doit pas rester seul en rayon — sans description, il ne
    porterait plus que son nom de fichier."""
    original = Path.write_text

    def _write_text_qui_echoue(self, *args, **kwargs):
        if self.suffix == ".txt":
            raise OSError("disque plein")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _write_text_qui_echoue)

    with pytest.raises(OSError):
        meme_import.importer(b"\x00\x00\x00\x18ftypmp42", ".mp4", "un clip", tmp_path)

    assert list(tmp_path.iterdir()) == []
