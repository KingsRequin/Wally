# tests/test_apex_widgets.py
"""Les panneaux Apex de l'overlay, construits par le SERVEUR.

Le point de cette couche : Wally choisit d'afficher et commente, mais ne recopie
plus aucun chiffre. Ce qui va à l'écran vient de l'API, pas du modèle — donc
aucune erreur de recopie n'est possible.
"""
import json
import pathlib

import pytest

from bot.core.apex.reader import read_profile
from bot.core.apex.widgets import (
    APEX_PANELS,
    craft_panel,
    map_panel,
    predator_panel,
    rank_panel,
    servers_panel,
    stats_panel,
    status_panel,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex"


def _raw(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _profile(who):
    return read_profile(_raw(f"bridge_{who}"))


def test_le_panneau_de_rang_porte_l_image_officielle():
    panel = rank_panel(_profile("azrael"))
    assert panel["rank_name"] == "Gold"
    assert panel["div"] == 3
    assert panel["score"] == 6422
    assert panel["img"].startswith("https://")
    assert panel["top_percent"] == pytest.approx(49.45)


def test_sans_rang_classe_le_panneau_le_dit_sans_inventer():
    panel = rank_panel(_profile("kingsrequin"))
    assert panel["rank_name"] == "Unranked"
    assert panel["top_percent"] is None


def test_le_panneau_d_etat_donne_la_legende_le_skin_et_l_avatar():
    """La fixture a été prise pendant une partie : l'état en jeu doit ressortir."""
    panel = status_panel(_profile("azrael"))
    assert panel["state"] == "In match"
    assert panel["in_game"] is True
    assert panel["legend"] == "Fuse"
    assert panel["skin"] == "Apex Inferno"
    assert panel["level"] == 1354
    assert panel["avatar"].startswith("https://")


def test_le_panneau_de_stats_ne_rend_que_ce_qui_existe():
    """Azraël n'a pas de tracker de réanimation : la ligne ne doit pas exister."""
    rows = {r["label"] for r in stats_panel(_profile("azrael"))["rows"]}
    assert "BR Kills" in rows
    assert not any("Revive" in label for label in rows)


def test_le_panneau_de_stats_porte_le_rang_mondial_quand_il_existe():
    rows = {r["label"]: r for r in stats_panel(_profile("kingsrequin"))["rows"]}
    assert rows["Career Kills"]["top_percent"] == pytest.approx(21.41)
    assert rows["Career Kills"]["world_pos"] == 432897


def test_le_panneau_de_cartes_montre_les_quatre_modes():
    modes = map_panel(_raw("maprotation"))["modes"]
    assert [m["name"] for m in modes] == ["Battle Royale", "Ranked", "Mode temporaire", "Wildcard"]
    assert all(m["map"] for m in modes)


def test_le_panneau_de_cartes_donne_un_decompte_en_secondes():
    """Le minuteur doit vivre à l'écran : le front a besoin de secondes, pas de « 01:26:30 »."""
    premier = map_panel(_raw("maprotation"))["modes"][0]
    assert isinstance(premier["remaining_s"], int)
    assert premier["remaining_s"] > 0


def test_le_panneau_de_craft_liste_les_lots():
    bundles = craft_panel(_raw("crafting"))["bundles"]
    assert bundles
    assert all(b["items"] for b in bundles)


def test_le_panneau_predator_ne_parle_que_de_rp():
    rows = predator_panel(_raw("predator"))["rows"]
    assert {r["platform"] for r in rows} == {"PC", "PS4", "Xbox"}
    assert all(isinstance(r["rp"], int) for r in rows)


def test_le_panneau_serveurs_marque_ce_qui_est_debout():
    rows = servers_panel(_raw("servers"))["rows"]
    assert rows
    assert all(isinstance(r["up"], bool) for r in rows)


def test_un_panneau_vide_ne_donne_rien_plutot_qu_une_carte_creuse():
    assert map_panel({}) is None
    assert craft_panel([]) is None
    assert predator_panel({}) is None
    assert servers_panel({}) is None
    assert rank_panel(None) is None
    assert stats_panel(None) is None
    assert status_panel(None) is None


def test_la_liste_des_panneaux_est_celle_qu_on_sait_rendre():
    assert APEX_PANELS == ("rank", "status", "stats", "progress", "map", "craft",
                           "predator", "servers")


# ── La façade du service (va chercher la donnée du panneau demandé) ──────────


class _FakeClient:
    available = True

    def __init__(self, reponse):
        self._reponse = reponse
        self.calls = []

    async def get(self, endpoint, params=None):
        self.calls.append(endpoint)
        return self._reponse


@pytest.mark.asyncio
async def test_le_service_construit_un_panneau_de_rang():
    from bot.core.apex.service import ApexLegendsService

    svc = ApexLegendsService(client=_FakeClient(_raw("bridge_azrael")))
    panel = await svc.build_panel("rank", "Azrael_ttv")
    assert panel["kind"] == "apex_rank"
    assert panel["rank_name"] == "Gold"


@pytest.mark.asyncio
async def test_le_service_construit_un_panneau_de_cartes():
    from bot.core.apex.service import ApexLegendsService

    client = _FakeClient(_raw("maprotation"))
    panel = await ApexLegendsService(client=client).build_panel("map")
    assert panel["kind"] == "apex_map"
    assert client.calls == ["maprotation"]


@pytest.mark.asyncio
async def test_un_panneau_inconnu_ne_declenche_aucun_appel():
    from bot.core.apex.service import ApexLegendsService

    client = _FakeClient({})
    assert await ApexLegendsService(client=client).build_panel("licorne") is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_une_erreur_reseau_ne_donne_pas_de_carte_vide():
    from bot.core.apex.service import ApexLegendsService

    svc = ApexLegendsService(client=_FakeClient("Apex API error (HTTP 500)"))
    assert await svc.build_panel("map") is None


@pytest.mark.asyncio
async def test_fetch_profile_est_la_brique_commune():
    """Le watcher, les panneaux et le texte passent tous par là."""
    from bot.core.apex.service import ApexLegendsService

    svc = ApexLegendsService(client=_FakeClient(_raw("bridge_azrael")))
    profil = await svc.fetch_profile("Azrael_ttv")
    assert profil.name == "Azrael_TTV"
    assert await svc.fetch_profile("") is None


@pytest.mark.asyncio
async def test_fetch_profile_rend_none_sur_erreur_reseau():
    from bot.core.apex.service import ApexLegendsService

    svc = ApexLegendsService(client=_FakeClient("Apex API error (HTTP 500)"))
    assert await svc.fetch_profile("X") is None
