"""La dépense dérive, et personne n'était prévenu.

`log_cost()` écrit chaque appel LLM dans `cost_log` — 98 957 lignes au
2026-08-30 — et rien ne signalait une dérive. DeepSeek est passé de 13,2 à
28,8 $/mois le 2026-08-16 sans que le système le dise.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.cout_veille import VeilleCouts, projection_mensuelle


def _db(total=8.23, plus_ancien_il_y_a_jours=7.0):
    db = MagicMock()
    db.get_cost_since = AsyncMock(return_value=total)
    db.fetch_one = AsyncMock(
        return_value={"t": time.time() - plus_ancien_il_y_a_jours * 86400}
    )
    return db


def _veille(db, seuil=25.0):
    cfg = MagicMock()
    cfg.bot.cost_alert_threshold = seuil
    notifs = MagicMock()
    notifs.send = AsyncMock(return_value=True)
    return VeilleCouts(db, cfg, notifs), notifs


# ── La projection ─────────────────────────────────────────────────────────


async def test_le_rythme_de_sept_jours_est_projete_sur_un_mois():
    """Mesuré en prod : 8,23 $ sur 7 jours → 35,26 $/mois, alors que les
    30 jours écoulés n'affichent que 22,93 $. Un plafond mensuel serait resté
    muet."""
    assert round(await projection_mensuelle(_db(total=8.23)), 1) == 35.3


async def test_une_base_neuve_ne_divise_pas_par_sept():
    """Au premier jour, diviser par 7 sous-estimerait d'un facteur 7 — la veille
    serait aveugle pile quand tout est neuf."""
    projection = await projection_mensuelle(_db(total=2.0, plus_ancien_il_y_a_jours=1.0))

    assert round(projection) == 60      # 2 $/jour × 30, pas 2/7 × 30


async def test_une_base_vide_ne_dit_pas_zero():
    """0,00 $ se lirait « ça ne coûte rien » là où ça veut dire « on ne sait
    pas encore »."""
    assert await projection_mensuelle(_db(total=0.0)) is None


async def test_base_en_panne_ne_fait_pas_tomber_la_veille():
    db = _db()
    db.get_cost_since.side_effect = RuntimeError("base fermée")

    assert await projection_mensuelle(db) is None


# ── L'alerte ──────────────────────────────────────────────────────────────


async def test_au_dessus_du_seuil_le_salon_est_prevenu():
    veille, notifs = _veille(_db(total=8.23), seuil=25.0)

    await veille.un_tour()

    notifs.send.assert_awaited_once()
    # Pas la valeur au centime : la fenêtre réelle glisse de quelques
    # millisecondes entre deux exécutions, et figer « 35.26 » ferait un test
    # qui tombe un jour sur deux.
    assert "35.2" in notifs.send.await_args[0][0]
    assert "25.00" in notifs.send.await_args[0][0]


async def test_sous_le_seuil_personne_n_est_derange():
    veille, notifs = _veille(_db(total=2.0), seuil=25.0)

    await veille.un_tour()

    notifs.send.assert_not_awaited()


async def test_on_ne_previent_qu_au_franchissement():
    """Une alerte qu'on apprend à ignorer ne vaut pas mieux que pas d'alerte."""
    veille, notifs = _veille(_db(total=8.23), seuil=25.0)

    for _ in range(5):
        await veille.un_tour()

    assert notifs.send.await_count == 1


async def test_l_alerte_se_rearme_quand_ca_redescend():
    db = _db(total=8.23)
    veille, notifs = _veille(db, seuil=25.0)
    await veille.un_tour()

    db.get_cost_since.return_value = 1.0        # ~4 $/mois : bien sous le seuil
    await veille.un_tour()
    db.get_cost_since.return_value = 8.23
    await veille.un_tour()

    assert notifs.send.await_count == 2


async def test_un_rythme_qui_oscille_autour_du_seuil_n_alerte_pas_deux_fois():
    """Sans marge de réarmement, une projection qui tremble autour de la valeur
    alerte à chaque oscillation."""
    db = _db(total=8.23)                        # 35,26 $/mois
    veille, notifs = _veille(db, seuil=35.0)
    await veille.un_tour()

    db.get_cost_since.return_value = 8.10       # 34,71 $ — juste sous le seuil
    await veille.un_tour()
    db.get_cost_since.return_value = 8.23
    await veille.un_tour()

    assert notifs.send.await_count == 1


@pytest.mark.parametrize("seuil", [0, 0.0, None])
async def test_un_seuil_a_zero_eteint_la_veille(seuil):
    """Éteindre la surveillance est un réglage valide, pas une panne."""
    db = _db(total=99.0)
    veille, notifs = _veille(db, seuil=seuil)

    assert await veille.un_tour() is None
    notifs.send.assert_not_awaited()
    db.get_cost_since.assert_not_awaited()


async def test_sans_salon_de_notification_la_veille_journalise_quand_meme():
    cfg = MagicMock()
    cfg.bot.cost_alert_threshold = 25.0
    veille = VeilleCouts(_db(total=8.23), cfg, None)

    assert round(await veille.un_tour(), 1) == 35.3


# ── Le réglage et son câblage ─────────────────────────────────────────────


def test_le_seuil_est_un_champ_de_config_lu():
    """Le champ existait à l'ÉCRAN depuis longtemps sans lecteur : le dashboard
    l'envoyait, la route l'ignorait en silence, et le toast disait « sauvegardé »."""
    from bot.config import BotConfig

    assert "cost_alert_threshold" in BotConfig.__dataclass_fields__


def test_la_route_de_config_accepte_le_seuil():
    import inspect

    from bot.dashboard.routes import admin

    source = inspect.getsource(admin._appliquer_config)
    assert "cost_alert_threshold" in source


def test_l_ecran_envoie_bien_ce_champ():
    """Les deux moitiés doivent rester face à face : si le champ disparaît du
    dashboard, ce test dit où regarder."""
    from pathlib import Path

    app_js = Path(__file__).resolve().parent.parent / "bot/dashboard/static/app.js"
    assert "cost_alert_threshold" in app_js.read_text(encoding="utf-8")
