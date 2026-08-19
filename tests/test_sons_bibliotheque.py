"""Le dossier des sons de l'overlay, et la barrière de sa route publique.

Demande de l'owner (2026-08-19) : un son à chaque fenêtre du spam de virus, un
autre sur l'écran bleu. Les fichiers sont déposés à la main dans `data/sons/`,
et servis à une page qui tourne dans OBS SANS session — `resolve()` est donc la
seule chose entre une URL publique et le disque du serveur.
"""
from pathlib import Path

import pytest

from bot.core.sons import GENRES, SoundLibrary, media_type


@pytest.fixture
def dossier(tmp_path: Path) -> Path:
    (tmp_path / "popup").mkdir()
    (tmp_path / "bsod").mkdir()
    (tmp_path / "popup" / "ding.mp3").write_bytes(b"\xff\xfb\x00")
    (tmp_path / "popup" / "erreur.wav").write_bytes(b"RIFF")
    (tmp_path / "bsod" / "impact.mp3").write_bytes(b"\xff\xfb\x00")
    return tmp_path


# ── l'inventaire ────────────────────────────────────────────────────────────

def test_chaque_genre_liste_ses_propres_sons(dossier):
    lib = SoundLibrary(dossier)
    assert lib.list("popup") == ["ding.mp3", "erreur.wav"]
    assert lib.list("bsod") == ["impact.mp3"]


def test_un_dossier_absent_rend_une_liste_vide_et_ne_leve_pas(tmp_path):
    """Un overlay muet vaut mieux qu'un overlay en erreur : la page ne saurait
    pas distinguer un dossier vide d'une panne du bot, et s'acharnerait."""
    lib = SoundLibrary(tmp_path / "jamais-creee")
    assert lib.list("popup") == []
    assert lib.inventaire() == {g: [] for g in GENRES}


def test_ce_qui_n_est_pas_un_son_est_ignore(dossier):
    (dossier / "popup" / "LISEZ-MOI.txt").write_text("mode d'emploi")
    (dossier / "popup" / "sous-dossier").mkdir()
    assert "LISEZ-MOI.txt" not in SoundLibrary(dossier).list("popup")
    assert "sous-dossier" not in SoundLibrary(dossier).list("popup")


def test_un_son_trop_lourd_est_ecarte(dossier):
    """Un ding, pas une bande-son : au-delà, le décodage bloque la page du live
    et le fichier n'a de toute façon aucun sens sur une fenêtre qui s'ouvre dix
    fois par seconde."""
    (dossier / "popup" / "album.mp3").write_bytes(b"\x00" * (3 * 1024 * 1024))
    assert "album.mp3" not in SoundLibrary(dossier).list("popup")


def test_l_inventaire_porte_les_deux_genres(dossier):
    inv = SoundLibrary(dossier).inventaire()
    assert set(inv) == set(GENRES)
    assert inv["bsod"] == ["impact.mp3"]


# ── la barrière ─────────────────────────────────────────────────────────────

def test_un_son_reel_se_resout(dossier):
    assert SoundLibrary(dossier).resolve("popup", "ding.mp3") \
        == dossier / "popup" / "ding.mp3"


@pytest.mark.parametrize("nom", [
    "../../.env",
    "../bsod/impact.mp3",
    "/etc/passwd",
    "..%2F..%2F.env",
    "",
])
def test_aucun_nom_ne_sort_du_dossier(dossier, nom):
    assert SoundLibrary(dossier).resolve("popup", nom) is None


def test_un_genre_inconnu_est_refuse(dossier):
    """Le genre vient de l'URL : sans cette garde, `sons/../../data` serait un
    chemin comme un autre."""
    (dossier / "autre").mkdir()
    (dossier / "autre" / "x.mp3").write_bytes(b"\xff")
    assert SoundLibrary(dossier).resolve("autre", "x.mp3") is None
    assert SoundLibrary(dossier).resolve("..", "x.mp3") is None
    assert SoundLibrary(dossier).list("autre") == []


def test_un_lien_symbolique_qui_sort_du_dossier_est_refuse(dossier, tmp_path):
    secret = tmp_path / "secret.mp3"
    secret.write_bytes(b"\xff")
    (dossier / "popup" / "piege.mp3").symlink_to(secret)
    assert SoundLibrary(dossier).resolve("popup", "piege.mp3") is None


def test_une_extension_inconnue_ne_se_sert_pas(dossier):
    (dossier / "popup" / "script.sh").write_text("rm -rf /")
    assert SoundLibrary(dossier).resolve("popup", "script.sh") is None


# ── le type MIME ────────────────────────────────────────────────────────────

def test_le_type_mime_est_annonce_sans_passer_par_mimetypes():
    """`mimetypes` ignore déjà `.webp` dans l'image Docker et rendait
    `application/octet-stream` sur les memes. On ne le laisse pas deviner."""
    assert media_type(Path("a.mp3")) == "audio/mpeg"
    assert media_type(Path("a.wav")) == "audio/wav"
    assert media_type(Path("a.inconnu")) == "application/octet-stream"


# ── ce qui est réellement déployé ───────────────────────────────────────────

def test_le_dossier_de_prod_porte_au_moins_un_son_de_chaque():
    """Le spectacle est muet si un des deux tiroirs est vide, et rien ne le
    signale à l'écran — c'est exactement le genre de panne qu'on ne découvre
    qu'en direct devant le chat."""
    prod = Path(__file__).resolve().parents[1] / "data" / "sons"
    if not prod.exists():
        pytest.skip("dossier de prod absent (dépôt fraîchement cloné)")
    lib = SoundLibrary(prod)
    assert lib.list("popup"), "aucun son de fenêtre dans data/sons/popup"
    assert lib.list("bsod"), "aucun son d'écran bleu dans data/sons/bsod"
