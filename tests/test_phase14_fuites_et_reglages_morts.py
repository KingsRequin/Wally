# tests/test_phase14_fuites_et_reglages_morts.py
"""Phase 14 de l'audit du 2026-08-10 : ce que les « mineurs » cachaient.

m-gallery — la galerie PUBLIQUE renvoyait la ligne entière : ID Discord réel du
            créateur, chemin du fichier sur le disque, coût en dollars.
            Vérifié en prod avant correction, sans authentification.
m-logs    — `?lines=0` donnait `all_lines[-0:]`, soit le fichier ENTIER.
m-boredom — `/wally setup` proposait de régler `boredom decay_lambda`, que le
            moteur saute : le réglage n'avait aucun effet.
m-roadmap — `ROADMAP.md` exclu de l'image Docker : endpoint mort.
"""
import inspect
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ────────────────────────── galerie publique ──────────────────────────
_LIGNE_COMPLETE = {
    "id": "img-1", "title": "Gâteau", "prompt": "un gâteau", "revised_prompt": None,
    "username": "zeddo", "user_id": "925492558262599680", "platform": "discord",
    "file_path": "/data/gallery/img-1.png", "model": "gpt-image-1.5",
    "quality": "low", "size": "1024x1024", "cost_usd": 0.009,
    "created_at": "2026-03-27", "votes": 1,
}
_INTERDITS = ("user_id", "file_path", "cost_usd", "platform", "revised_prompt")


@pytest.mark.asyncio
async def test_la_liste_publique_ne_fuit_ni_identite_ni_chemin_ni_cout():
    from bot.dashboard.routes.gallery import list_gallery

    requete = MagicMock()
    requete.app.state.wally.db.get_gallery_images = AsyncMock(return_value=[dict(_LIGNE_COMPLETE)])

    out = await list_gallery(requete)
    image = out["images"][0]

    for champ in _INTERDITS:
        assert champ not in image, f"{champ} exposé publiquement"
    # …tout en gardant ce dont le front a besoin.
    for champ in ("id", "title", "prompt", "username", "model", "quality", "size", "votes"):
        assert champ in image


@pytest.mark.asyncio
async def test_le_detail_public_ne_fuit_pas_non_plus():
    from bot.dashboard.routes import gallery

    requete = MagicMock()
    requete.app.state.wally.db.get_gallery_image = AsyncMock(return_value=dict(_LIGNE_COMPLETE))
    requete.app.state.wally.db.has_voted = AsyncMock(return_value=True)

    with patch.object(gallery, "_extract_user_id_from_jwt", return_value=("discord:1", {})):
        image = await gallery.get_image_detail(requete, "img-1")

    for champ in _INTERDITS:
        assert champ not in image
    assert image["user_voted"] is True


@pytest.mark.asyncio
async def test_l_image_aleatoire_ne_fuit_pas_non_plus():
    from bot.dashboard.routes.gallery import random_image

    requete = MagicMock()
    requete.app.state.wally.db.get_random_gallery_image = AsyncMock(
        return_value=dict(_LIGNE_COMPLETE)
    )
    image = await random_image(requete)
    for champ in _INTERDITS:
        assert champ not in image


def test_l_admin_garde_l_acces_complet():
    """Le filtrage est posé sur les routes PUBLIQUES seulement."""
    from bot.dashboard.routes import gallery

    src = inspect.getsource(gallery)
    i_public = src.index("# --- Public routes ---")
    i_admin = src.index("admin_router", i_public)
    assert "_vue_publique" not in src[i_admin:]


# ────────────────────────────── logs ──────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("demande", [0, -5])
async def test_un_nombre_de_lignes_absurde_ne_renvoie_pas_tout_le_log(demande, tmp_path):
    from bot.dashboard.routes import sse

    fichier = tmp_path / "app.log"
    fichier.write_text("\n".join(f"ligne {i}" for i in range(500)), encoding="utf-8")

    requete = MagicMock()
    with patch.object(sse, "_find_latest_log", return_value=fichier), \
         patch.object(sse, "_parse_log_line", side_effect=lambda ligne: {"m": ligne}):
        out = await sse.log_history(requete, lines=demande)

    assert 0 < len(out["entries"]) < 500


@pytest.mark.asyncio
async def test_une_demande_normale_est_respectee(tmp_path):
    from bot.dashboard.routes import sse

    fichier = tmp_path / "app.log"
    fichier.write_text("\n".join(f"ligne {i}" for i in range(500)), encoding="utf-8")

    requete = MagicMock()
    with patch.object(sse, "_find_latest_log", return_value=fichier), \
         patch.object(sse, "_parse_log_line", side_effect=lambda ligne: {"m": ligne}):
        out = await sse.log_history(requete, lines=10)

    assert len(out["entries"]) == 10


# ────────────────────────────── ennui ──────────────────────────────
def test_le_reglage_de_l_ennui_agit_sur_ce_qui_compte():
    from bot.discord.commands.setup import advanced

    # Le moteur saute `boredom` dans `_apply_decay` : régler son λ ne fait rien.
    # C'est le LABEL montré à l'owner qui doit dire la vérité.
    assert "decay_lambda" not in advanced.DecayModal.boredom.label
    assert "montée par heure" in advanced.DecayModal.boredom.label

    src = inspect.getsource(advanced.DecayModal.on_submit)
    assert 'self.bot.config.emotions["boredom"].boredom_rise_per_hour = value' in src


def test_le_moteur_ignore_bien_le_lambda_de_l_ennui():
    """La raison d'être du correctif précédent, vérifiée sur le moteur."""
    from bot.core.emotion import EmotionEngine

    src = inspect.getsource(EmotionEngine._apply_decay)
    assert 'if emotion == "boredom":' in src
    assert "continue" in src


# ────────────────────────────── roadmap ──────────────────────────────
def test_le_fichier_roadmap_entre_dans_l_image():
    """Deux conditions, et la première seule ne suffit pas.

    Ne vérifier que le `.dockerignore` donnait une fausse assurance : le
    Dockerfile ne copie que `bot/` et `scripts/`, si bien que le fichier
    n'entrait toujours pas dans l'image après avoir levé l'exclusion.
    """
    ignore = Path(".dockerignore").read_text(encoding="utf-8")
    assert "!ROADMAP.md" in ignore
    # L'exception doit venir APRÈS l'exclusion, sinon elle ne s'applique pas.
    assert ignore.index("*.md") < ignore.index("!ROADMAP.md")

    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "COPY ROADMAP.md" in dockerfile


def test_le_chemin_attendu_par_la_route_correspond_a_l_image():
    """`parents[3]` depuis bot/dashboard/routes/ doit donner la racine /app."""
    from bot.dashboard.routes import roadmap

    depuis_module = Path(roadmap.__file__).parents[3]
    assert (depuis_module / "ROADMAP.md").exists()
