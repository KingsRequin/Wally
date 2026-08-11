# tests/test_twitch_clips_fenetre.py
"""La fenêtre demandée à Helix doit être celle qu'on croit demander.

`GET /helix/clips` avec `started_at` mais SANS `ended_at` ne renvoie PAS les
clips depuis cette date : Twitch borne la fenêtre à `started_at + 1 semaine`.
Une recherche « sur 30 jours » ne regardait donc que la semaine du 30e au 23e
jour AVANT aujourd'hui — un trou d'exactement trois semaines dans le présent.

Constaté en prod le 2026-08-11 : 3 clips (tous de mai) sur une fenêtre de 90
jours, contre 16 avec `ended_at`.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_twitch_api import make_api

_NOW = datetime.now(timezone.utc)


def _clip(jours: int, ident: str, vues: int = 10) -> dict:
    d = _NOW - timedelta(days=jours)
    return {
        "id": ident,
        "title": f"clip {ident}",
        "creator_name": "KingsRequin",
        "view_count": vues,
        "created_at": d.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# Ce qu'a réellement la chaîne : un clip d'avant-hier, un de la semaine
# dernière, un du mois dernier.
CATALOGUE = [_clip(2, "recent", 50), _clip(9, "semaine", 999), _clip(25, "vieux", 300)]


class _HelixSimule:
    """Un faux Helix qui applique la règle de Twitch sur `ended_at`.

    C'est cette règle, et elle seule, que le test reproduit : sans borne de
    fin, Twitch en pose une à `started_at + 7 jours`.
    """

    def __init__(self):
        self.derniers_params: dict = {}

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.derniers_params = dict(params or {})
        debut = datetime.strptime(params["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        fin = (
            datetime.strptime(params["ended_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if params.get("ended_at")
            else debut + timedelta(days=7)
        )
        visibles = [
            c for c in CATALOGUE
            if debut <= datetime.strptime(
                c["created_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc) <= fin
        ]
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"data": visibles})
        return resp


def _client(helix):
    client = MagicMock()
    client.get = AsyncMock(side_effect=helix)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_une_fenetre_longue_voit_bien_le_present():
    """« Les clips des 90 derniers jours » doit inclure celui d'avant-hier."""
    helix = _HelixSimule()
    api = make_api()
    since = (_NOW - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with patch("httpx.AsyncClient", return_value=_client(helix)):
        clips = await api.get_recent_clips(since, first=100)
    assert {c["id"] for c in clips} == {"recent", "semaine", "vieux"}


@pytest.mark.asyncio
async def test_le_plus_vu_du_mois_ne_rate_pas_le_mois():
    """`get_top_clips(days=30)` sert « affiche le clip le plus vu »."""
    helix = _HelixSimule()
    api = make_api()
    with patch("httpx.AsyncClient", return_value=_client(helix)):
        top = await api.get_top_clips(days=30, first=1)
    # Le plus vu date de la semaine dernière : la fenêtre tronquée ne voyait que
    # le 25e jour et aurait sacré le mauvais clip.
    assert [c["id"] for c in top] == ["semaine"]


@pytest.mark.asyncio
async def test_la_recherche_par_titre_couvre_toute_sa_fenetre():
    helix = _HelixSimule()
    api = make_api()
    with patch("httpx.AsyncClient", return_value=_client(helix)):
        clip = await api.find_clip("clip recent", days=30)
    assert clip is not None and clip["id"] == "recent"


@pytest.mark.asyncio
async def test_le_dernier_clip_ne_se_limite_pas_a_la_journee():
    """Le dernier clip de la chaîne a trois jours ? C'est quand même le dernier.

    Vécu en prod : « aucun clip récent sur la chaîne, même pas de Lolofun »
    alors que deux clips de Lolofun dataient de quatre jours.
    """
    helix = _HelixSimule()
    api = make_api()
    with patch("httpx.AsyncClient", return_value=_client(helix)):
        clip = await api.get_last_clip()
    assert clip is not None and clip["id"] == "recent"
