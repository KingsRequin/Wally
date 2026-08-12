# tests/test_canari.py
"""Le canari de démarrage : ce qu'aucun test ne peut voir.

Ces invariants dépendent de l'état RÉEL de la base et du disque, pas du code —
c'est pourquoi les deux audits du 2026-08-10 ne les ont trouvés qu'en
interrogeant la production. Le canari les regarde à chaque boot et le DIT.

Il a d'ailleurs prouvé sa valeur immédiatement : dès sa première exécution, il a
remonté 111 dates en format aware réapparues APRÈS la migration, révélant deux
points d'écriture (`action_dispatcher`, `reasoning_agent`) que la première passe
avait manqués.
"""
import sqlite3
from types import SimpleNamespace

import pytest

from bot.core.canari import verifier_invariants


def _config(owner="610550333042589752", vision="gpt-5-nano"):
    return SimpleNamespace(
        bot=SimpleNamespace(owner_discord_id=owner),
        openai=SimpleNamespace(vision_model=vision),
    )


def _base(tmp_path, avec_index=True, dates_aware=0):
    chemin = tmp_path / "test.db"
    c = sqlite3.connect(chemin)
    c.execute(
        "CREATE TABLE atomic_facts(id INTEGER PRIMARY KEY, user_id TEXT, "
        "status TEXT, scheduled_at TEXT, created_at TEXT, last_seen_at TEXT)"
    )
    if avec_index:
        c.execute("CREATE INDEX idx_facts_scheduled ON atomic_facts(scheduled_at) "
                  "WHERE scheduled_at IS NOT NULL")
        c.execute("CREATE INDEX idx_facts_user_status ON atomic_facts(user_id, status)")
    for i in range(dates_aware):
        c.execute("INSERT INTO atomic_facts(created_at, last_seen_at) VALUES(?,?)",
                  ("2026-08-01T10:00:00+00:00", "2026-08-01T10:00:00+00:00"))
    c.commit()
    c.close()
    return str(chemin)


@pytest.mark.asyncio
async def test_une_installation_saine_ne_produit_aucune_alerte(tmp_path):
    # Créer une racine vierge pour isoler du dossier réel de memes
    (tmp_path / "data" / "memes").mkdir(parents=True)
    (tmp_path / "bot" / "persona" / "prompts").mkdir(parents=True)
    (tmp_path / "bot" / "intelligence" / "persona" / "prompts").mkdir(parents=True)
    assert (
        await verifier_invariants(_config(), _base(tmp_path), racine=tmp_path)
        == []
    )


@pytest.mark.asyncio
async def test_un_index_manquant_est_signale(tmp_path):
    alertes = await verifier_invariants(_config(), _base(tmp_path, avec_index=False))
    assert any("idx_facts_scheduled" in a for a in alertes)
    # L'alerte doit dire la CONSÉQUENCE, pas seulement le symptôme.
    assert any("scanne toute la table" in a for a in alertes)


@pytest.mark.asyncio
async def test_deux_formats_de_date_sont_signales(tmp_path):
    alertes = await verifier_invariants(_config(), _base(tmp_path, dates_aware=7))
    assert any("7 dates en format aware" in a for a in alertes)
    # Et doit pointer vers le remède.
    assert any("normaliser_dates_faits" in a for a in alertes)


@pytest.mark.asyncio
async def test_un_reglage_qui_rend_une_fonction_muette_est_signale(tmp_path):
    chemin = _base(tmp_path)
    sans_owner = await verifier_invariants(_config(owner=""), chemin)
    assert any("owner_discord_id" in a for a in sans_owner)

    sans_vision = await verifier_invariants(_config(vision=""), chemin)
    assert any("vision_model" in a for a in sans_vision)


@pytest.mark.asyncio
async def test_le_canari_ne_bloque_jamais_le_demarrage(tmp_path):
    """Un bot qui tourne avec un index manquant vaut mieux qu'un bot qui refuse
    de démarrer. Le canari ne doit lever sous AUCUNE circonstance."""
    corrompue = tmp_path / "corrompue.db"
    corrompue.write_bytes(b"ceci n'est pas une base SQLite")

    alertes = await verifier_invariants(_config(), str(corrompue))
    assert isinstance(alertes, list)          # a rendu la main, sans lever


@pytest.mark.asyncio
async def test_une_base_absente_nest_pas_une_anomalie(tmp_path):
    """Première installation : la base n'existe pas encore, ce n'est pas un défaut."""
    alertes = await verifier_invariants(_config(), str(tmp_path / "jamais_creee.db"))
    assert not any("index" in a or "aware" in a for a in alertes)


def test_le_canari_signale_un_meme_sans_description(tmp_path):
    from bot.core.canari import _verifier_memes

    memes = tmp_path / "data" / "memes"
    memes.mkdir(parents=True)
    (memes / "meme1.webp").write_bytes(b"a")

    alertes = _verifier_memes(tmp_path)

    assert any("meme1.webp" in a for a in alertes)


@pytest.mark.parametrize("nom", ["enorme.webp", "enorme.mp4"])
def test_le_canari_signale_un_media_au_dessus_du_plafond(tmp_path, nom):
    """Quel que soit son format : `list_medias()` applique le MÊME plafond.

    Le balayage ne regardait que les formats affichables. Un `.mp4` de 12 Mo
    passait donc l'import, était annoncé « rangé », n'apparaissait ni dans
    `list()` ni dans `list_medias()`, et le canari se taisait.
    """
    from bot.core.canari import _verifier_memes
    from bot.core.memes import _MAX_BYTES

    memes = tmp_path / "data" / "memes"
    memes.mkdir(parents=True)
    (memes / nom).write_bytes(b"\x00" * (_MAX_BYTES + 1))
    (memes / f"{nom}.txt").write_text("d", encoding="utf-8")

    alertes = _verifier_memes(tmp_path)

    assert any(nom in a and "jamais montré" in a for a in alertes)


def test_le_canari_se_tait_sur_une_banque_saine(tmp_path):
    from bot.core.canari import _verifier_memes

    memes = tmp_path / "data" / "memes"
    memes.mkdir(parents=True)
    (memes / "meme1.webp").write_bytes(b"a")
    (memes / "meme1.webp.txt").write_text("un chat", encoding="utf-8")

    assert _verifier_memes(tmp_path) == []


def test_le_canari_ne_signale_pas_une_video_saine(tmp_path):
    from bot.core.canari import _verifier_memes

    memes = tmp_path / "data" / "memes"
    memes.mkdir(parents=True)
    (memes / "video.mp4").write_bytes(b"fake mp4")
    (memes / "video.mp4.txt").write_text("une vidéo drôle", encoding="utf-8")

    assert _verifier_memes(tmp_path) == []


def test_une_video_sans_description_ne_fait_pas_crier_le_canari(tmp_path):
    """Une alerte qu'on ne peut pas faire taire détruit la valeur du canari.

    `pick(hint)` ne tire jamais de vidéo et `list_medias()` ne lit aucune
    description : le sidecar d'un `.mp4` n'est lu par personne. La seule
    « correction » possible serait d'écrire un fichier que rien ne consulte —
    le canari signalait donc `meme35.mp4` à chaque démarrage, pour rien.
    """
    from bot.core.canari import _verifier_memes

    memes = tmp_path / "data" / "memes"
    memes.mkdir(parents=True)
    (memes / "meme35.mp4").write_bytes(b"fake mp4")

    assert _verifier_memes(tmp_path) == []


def test_le_rattrapage_liste_toujours_la_video_muette(tmp_path):
    """Le filtre est chez l'APPELANT : le script, lui, doit encore la voir.

    C'est lui qui affiche « laissé — pas d'analyse possible sur une vidéo », ce
    qui suppose de la trouver parmi les muets.
    """
    from bot.core.meme_import import memes_sans_description

    (tmp_path / "meme35.mp4").write_bytes(b"fake mp4")

    assert [p.name for p in memes_sans_description(tmp_path)] == ["meme35.mp4"]


def test_le_canari_est_bien_branche_au_demarrage():
    import inspect

    from bot import bootstrap

    src = inspect.getsource(bootstrap.build_core_services)
    assert "verifier_invariants(config, _db_path)" in src
