# tests/test_twitch_clips_fenetre.py
"""La fenêtre demandée à Helix doit être celle qu'on croit demander.

`GET /helix/clips` avec `started_at` mais SANS `ended_at` ne renvoie PAS les
clips depuis cette date : Twitch borne la fenêtre à `started_at + 1 semaine`.
Une recherche « sur 30 jours » ne regardait donc que la semaine du 30e au 23e
jour AVANT aujourd'hui — un trou d'exactement trois semaines dans le présent.

Constaté en prod le 2026-08-11 : 3 clips (tous de mai) sur une fenêtre de 90
jours, contre 16 avec `ended_at`.

Deuxième règle, mesurée le 2026-09-04 : Helix ne compare pas `ended_at` au
`created_at` du clip, mais à la FIN DU CRÉNEAU DE 10 MINUTES qui le contient.
Un `ended_at` posé à « maintenant » rend donc invisibles tous les clips des dix
dernières minutes — ceux dont on parle pendant le live. La borne se pose dans
le FUTUR.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_twitch_api import make_api

_NOW = datetime.now(timezone.utc)


def _clip(jours: int, ident: str, vues: int = 10, minutes: int = 0) -> dict:
    d = _NOW - timedelta(days=jours, minutes=minutes)
    return {
        "id": ident,
        "title": f"clip {ident}",
        "creator_name": "KingsRequin",
        "view_count": vues,
        "created_at": d.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# Ce qu'a réellement la chaîne : un clip d'avant-hier, un de la semaine
# dernière, un du mois dernier.
CATALOGUE = [
    # Celui-ci vient d'être créé : c'est celui que le live réclame, et le seul
    # que la borne « maintenant » faisait disparaître.
    _clip(0, "frais", 0, minutes=1),
    _clip(2, "recent", 50),
    _clip(9, "semaine", 999),
    _clip(25, "vieux", 300),
]


class _HelixSimule:
    """Un faux Helix qui applique les DEUX règles de Twitch sur `ended_at`.

    1. Sans borne de fin, Twitch en pose une à `started_at + 7 jours`.
    2. La borne de fin est comparée à la fin du créneau de 10 minutes qui
       contient le `created_at` du clip, jamais au `created_at` lui-même.

    Les deux ont été mesurées contre le vrai Helix — la seconde à la seconde
    près, sur un clip du jour ET sur un clip vieux de quatre jours.
    """

    def __init__(self, catalogue: list[dict] | None = None):
        self.derniers_params: dict = {}
        self._catalogue = CATALOGUE if catalogue is None else catalogue

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
        visibles = []
        for c in self._catalogue:
            cree = datetime.strptime(
                c["created_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
            # Fin du créneau de 10 min : 07:21:16 → 07:30:00.
            creneau = cree.replace(second=0, microsecond=0) + timedelta(
                minutes=10 - cree.minute % 10
            )
            if debut <= cree and creneau <= fin:
                visibles.append(c)
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
    assert {c["id"] for c in clips} == {"frais", "recent", "semaine", "vieux"}


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
    # Sans clip du jour : le plus récent a deux jours, et c'est le bon.
    helix = _HelixSimule([c for c in CATALOGUE if c["id"] != "frais"])
    api = make_api()
    with patch("httpx.AsyncClient", return_value=_client(helix)):
        clip = await api.get_last_clip()
    assert clip is not None and clip["id"] == "recent"


@pytest.mark.asyncio
async def test_le_clip_de_la_minute_est_visible():
    """Le clip créé il y a une minute DOIT sortir. C'est le cas d'usage.

    Vécu en prod le 2026-09-04, en plein live : Taki clippe, demande à Wally de
    l'afficher, et Wally joue « Le cerveau de Rina a bug » — du 14 août — en
    annonçant « le dernier clip de Taki ». Helix n'avait rien renvoyé du jour,
    parce que `ended_at` valait « maintenant » et que le clip appartenait au
    créneau de 10 minutes en cours.
    """
    helix = _HelixSimule()
    api = make_api()
    with patch("httpx.AsyncClient", return_value=_client(helix)):
        clip = await api.get_last_clip()
    assert clip is not None and clip["id"] == "frais"


@pytest.mark.asyncio
async def test_la_borne_de_fin_est_dans_le_futur():
    """La borne demandée à Helix doit dépasser le créneau en cours.

    Le test au-dessus passerait aussi avec une marge de 10 min pile posée au
    mauvais endroit ; celui-ci nomme l'invariant : `ended_at` est dans le
    futur, donc au-delà de la fin du créneau de 10 minutes courant.
    """
    helix = _HelixSimule()
    api = make_api()
    with patch("httpx.AsyncClient", return_value=_client(helix)):
        await api.get_recent_clips(
            (_NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    fin = datetime.strptime(
        helix.derniers_params["ended_at"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    maintenant = datetime.now(timezone.utc)
    creneau = maintenant.replace(second=0, microsecond=0) + timedelta(
        minutes=10 - maintenant.minute % 10
    )
    assert fin >= creneau
