# tests/test_apex_service.py
"""Les actions offertes au LLM, et leur rendu."""
import json
import pathlib

import pytest

from bot.core.apex.service import ApexLegendsService

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex"


class _FakeClient:
    """Rend la fixture correspondant à l'endpoint demandé."""

    available = True

    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = []

    async def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        value = self._mapping[endpoint]
        return value(params) if callable(value) else value


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _service(mapping):
    return ApexLegendsService(client=_FakeClient(mapping))


@pytest.mark.asyncio
async def test_le_profil_annonce_l_etat_en_jeu_et_la_legende():
    svc = _service({"bridge": _fixture("bridge_azrael")})
    texte = await svc.execute("player_stats", "Azrael_ttv")
    assert "Azrael_TTV" in texte
    assert "Fuse" in texte
    assert "Gold" in texte


@pytest.mark.asyncio
async def test_le_profil_donne_les_kills():
    texte = await _service({"bridge": _fixture("bridge_azrael")}).execute("player_stats", "Azrael_ttv")
    # Le plus haut de ses deux trackers « BR Kills », pas leur somme : ils
    # comptent la même chose. Ce test a verrouillé « 102 324 » pendant huit
    # jours, en appelant « valeur amputée » le seul chiffre qui existait.
    assert "92 182" in texte


@pytest.mark.asyncio
async def test_le_rang_mondial_s_affiche_quand_il_existe():
    texte = await _service({"bridge": _fixture("bridge_kingsrequin")}).execute("player_stats", "KingsRequin")
    assert "21.41" in texte or "21,41" in texte


@pytest.mark.asyncio
async def test_aucun_rang_mondial_n_est_invente():
    """Azraël n'a pas de bloc Global : ses kills sortent sans classement."""
    texte = await _service({"bridge": _fixture("bridge_azrael")}).execute("player_stats", "Azrael_ttv")
    assert "mondial" not in texte.lower()


@pytest.mark.asyncio
async def test_un_joueur_introuvable_le_dit_sans_inventer():
    svc = _service({"bridge": {"Error": "Player not found"}})
    texte = await svc.execute("player_stats", "PersonneIci")
    assert "PersonneIci" in texte
    assert "trouv" in texte.lower()


@pytest.mark.asyncio
async def test_sans_pseudo_on_ne_part_pas_en_reseau():
    client = _FakeClient({"bridge": {}})
    texte = await ApexLegendsService(client=client).execute("player_stats", "")
    assert client.calls == []
    assert "pseudo" in texte.lower()


@pytest.mark.asyncio
async def test_une_erreur_reseau_remonte_telle_quelle():
    svc = _service({"bridge": "Apex API error (HTTP 500)"})
    assert "500" in await svc.execute("player_stats", "X")


@pytest.mark.asyncio
async def test_une_action_inconnue_ne_plante_pas():
    assert "inconnue" in (await _service({}).execute("danse")).lower()


# ── Les quatre autres actions ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_la_rotation_montre_les_quatre_modes_dont_wildcard():
    texte = (await _service({"maprotation": _fixture("maprotation")}).execute("map_rotation")).lower()
    for mode in ("battle royale", "ranked", "temporaire", "wildcard"):
        assert mode in texte


@pytest.mark.asyncio
async def test_la_rotation_donne_le_temps_restant():
    texte = await _service({"maprotation": _fixture("maprotation")}).execute("map_rotation")
    assert ":" in texte


@pytest.mark.asyncio
async def test_le_predator_ne_cherche_plus_les_arenes():
    """La clé `AP` a disparu de l'API : la moitié de l'ancien rendu était morte."""
    texte = await _service({"predator": _fixture("predator")}).execute("predator")
    assert "PC" in texte
    assert "arena" not in texte.lower()


@pytest.mark.asyncio
async def test_le_craft_liste_les_lots():
    texte = await _service({"crafting": _fixture("crafting")}).execute("crafting")
    assert len(texte.splitlines()) >= 2


@pytest.mark.asyncio
async def test_les_serveurs_rendent_un_etat():
    texte = await _service({"servers": _fixture("servers")}).execute("server_status")
    assert texte.strip()


@pytest.mark.asyncio
async def test_l_action_news_n_existe_plus():
    """L'endpoint répond [] : mieux vaut pas d'action qu'une action muette."""
    assert "inconnue" in (await _service({}).execute("news")).lower()
