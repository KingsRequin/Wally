# tests/test_apex_courbe_sorties.py
"""La courbe de progression, de son calcul à ses deux sorties.

Discord reçoit un PNG en pièce jointe ; l'overlay reçoit une URL que le
dashboard trace à la demande. Les deux partent des mêmes relevés.
"""
import pytest
import pytest_asyncio

from bot.core.apex.history import ApexHistory
from bot.core.apex.service import ApexLegendsService
from bot.core.apex.widgets import APEX_PANELS, progress_panel
from bot.db.database import Database

UID = "1002761549602"
HEURE = 3600.0


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


@pytest_asyncio.fixture
async def service(db):
    svc = ApexLegendsService(client=object(), db=db)
    svc.history = ApexHistory(db)
    return svc


async def _serie(svc, n: int = 6) -> None:
    import time
    base = time.time() - 6 * HEURE
    for i in range(n):
        await svc.history.enregistrer(
            UID, {"kills": 1000 + i * 5}, maintenant=base + i * 600
        )


# ── Sortie Discord ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_progression_demandee_laisse_une_courbe(service):
    await _serie(service)
    await service._progression(
        "", "PC", period="live", notion="kills", requester="discord:42", uid=UID,
        peut_joindre_image=True,
    )
    png = await service.derniere_courbe("discord:42")
    assert png is not None and png.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_la_courbe_ne_s_attache_qu_une_fois(service):
    """Sinon la question suivante repartirait avec le graphe de la précédente."""
    await _serie(service)
    await service._progression(
        "", "PC", period="live", notion="kills", requester="discord:42", uid=UID,
        peut_joindre_image=True,
    )
    assert await service.derniere_courbe("discord:42") is not None
    assert await service.derniere_courbe("discord:42") is None


@pytest.mark.asyncio
async def test_sans_demande_il_n_y_a_pas_de_courbe(service):
    assert await service.derniere_courbe("discord:42") is None


@pytest.mark.asyncio
async def test_deux_personnes_ne_se_volent_pas_leur_courbe(service):
    """Discord et Twitch tapent sur le même service en même temps."""
    await _serie(service)
    await service._progression(
        "", "PC", period="live", notion="kills", requester="discord:42", uid=UID,
        peut_joindre_image=True,
    )
    assert await service.derniere_courbe("twitch:99") is None
    assert await service.derniere_courbe("discord:42") is not None


@pytest.mark.asyncio
async def test_les_courbes_en_attente_sont_bornees(service):
    """Un dict de courbes sans plafond grossirait indéfiniment — c'est ce qui
    était arrivé au cache du client Apex."""
    await _serie(service)
    for i in range(service._MAX_COURBES + 5):
        await service._progression(
            "", "PC", period="live", notion="kills", requester=f"discord:{i}", uid=UID,
            peut_joindre_image=True,
        )
    assert len(service._progressions) <= service._MAX_COURBES


@pytest.mark.asyncio
async def test_sans_assez_de_releves_aucune_courbe_n_est_rendue(service):
    """Un point unique ne fait pas une courbe : la réponse reste en chiffres."""
    await service.history.enregistrer(UID, {"kills": 1000})
    await service._progression(
        "", "PC", period="live", notion="kills", requester="discord:42", uid=UID,
        peut_joindre_image=True,
    )
    assert await service.derniere_courbe("discord:42") is None


# ── Sortie overlay ───────────────────────────────────────────────────────────

class _Profil:
    name = "Azrael_TTV"
    avatar = "http://exemple/a.png"
    uid = UID


def test_le_panneau_porte_une_url_pas_des_chiffres():
    """Le modèle ne fournit aucune donnée, et le panneau n'en transporte pas :
    c'est le serveur qui tracera, avec ce qu'il a vraiment mesuré.

    L'URL porte un INSTANT et une clé de fenêtre : un mot comme « stream » y
    serait intraçable, le dashboard ignorant quand le live a commencé."""
    from bot.core.apex.periode import parse_periode

    fenetre = parse_periode("mois")
    panneau = progress_panel(_Profil(), fenetre=fenetre, notion="kills")
    assert panneau is not None
    assert panneau["image_url"].startswith("/api/public/apex/progression.png?")
    assert f"uid={UID}" in panneau["image_url"]
    assert f"depuis={fenetre.depuis:.0f}" in panneau["image_url"]
    assert "libelle=mois" in panneau["image_url"]
    assert panneau["period"] == "ce mois-ci"


def test_sans_uid_il_n_y_a_pas_de_panneau():
    from bot.core.apex.periode import parse_periode

    class _Anonyme:
        name, avatar, uid = "X", "", ""

    fenetre = parse_periode("jour")
    assert progress_panel(_Anonyme(), fenetre=fenetre) is None
    assert progress_panel(None, fenetre=fenetre) is None


def test_le_panneau_progress_est_declare():
    assert "progress" in APEX_PANELS


def test_l_outil_overlay_propose_la_courbe():
    from bot.core.apex.tool import APEX_OVERLAY_TOOL

    props = APEX_OVERLAY_TOOL["function"]["parameters"]["properties"]
    assert "progress" in props["panel"]["enum"]
    assert "period" in props


# ── Le RP suit la courbe, sur les DEUX sorties ───────────────────────────────
#
# Le mode d'une partie n'existe nulle part dans l'API : un RP qui bouge est le
# seul signal qu'elle était classée. Si une seule des deux sorties le reçoit,
# les mêmes parties s'affichent colorées à l'écran et monochromes sur Discord.

async def _serie_avec_rp(svc, n: int = 6):
    """Des kills, et un RP relevé DÈS AVANT la fenêtre.

    Le premier relevé de RP précède les kills : sans ça, l'observation ne
    couvrirait pas la fenêtre et la courbe refuserait — à raison — de colorer
    des parties dont elle ignore le mode.
    """
    import time
    base = time.time() - 6 * HEURE
    await svc.history.enregistrer(UID, {"rank_score": 6400}, maintenant=base - HEURE)
    for i in range(n):
        await svc.history.enregistrer(
            UID, {"kills": 1000 + i * 5}, maintenant=base + i * 600
        )
    await svc.history.enregistrer(UID, {"rank_score": 6455}, maintenant=base + 700)
    return base


def _espionner_render(monkeypatch):
    """Capture le `rp` que le rendu reçoit, sans empêcher le tracé."""
    from bot.core.apex import chart

    recu: dict = {}
    vrai = chart.render

    def _espion(points, notion, titre, *, rp=None):
        recu["rp"] = rp
        return vrai(points, notion, titre, rp=rp)

    monkeypatch.setattr(chart, "render", _espion)
    return recu


@pytest.mark.asyncio
async def test_la_courbe_discord_emporte_les_releves_de_rp(service, monkeypatch):
    base = await _serie_avec_rp(service)
    recu = _espionner_render(monkeypatch)

    await service._progression(
        "", "PC", period="live", notion="kills", requester="discord:42", uid=UID,
        peut_joindre_image=True,
    )
    await service.derniere_courbe("discord:42")

    assert (pytest.approx(base + 700), 6455) in recu["rp"]


@pytest.mark.asyncio
async def test_la_courbe_de_l_overlay_emporte_les_releves_de_rp(db, monkeypatch):
    """La route publique trace la même fenêtre que la carte affichée : elle doit
    partir des mêmes relevés, RP compris."""
    import time
    import types

    from bot.dashboard.routes.apex_chart import progression_png

    hist = ApexHistory(db)
    base = time.time() - 6 * HEURE
    await hist.enregistrer(UID, {"rank_score": 6400}, maintenant=base - HEURE)
    for i in range(6):
        await hist.enregistrer(UID, {"kills": 1000 + i * 5}, maintenant=base + i * 600)
    await hist.enregistrer(UID, {"rank_score": 6455}, maintenant=base + 700)

    recu = _espionner_render(monkeypatch)
    requete = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(
            wally=types.SimpleNamespace(db=db)))
    )
    reponse = await progression_png(
        requete, uid=UID, depuis=base - 60, notion="kills", libelle="duree"
    )

    assert reponse.media_type == "image/png"
    assert recu["rp"] == [(pytest.approx(base + 700), 6455)]
