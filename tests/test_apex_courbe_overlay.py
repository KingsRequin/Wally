# tests/test_apex_courbe_overlay.py
"""Le panneau « courbe » de l'overlay ne part que s'il y a une courbe.

Le 2026-08-12 en plein live, « Wally affiche la courbe des kills d'Azra » a mis
à l'écran une carte au nom de KingsRequin, sans graphe — et Wally a annoncé au
chat qu'elle était affichée. Deux défauts sur le même chemin :

- le serveur publiait le panneau sans jamais regarder s'il avait de quoi
  tracer : la décision était laissée au navigateur, qui ne peut que constater
  un 404 après coup, une fois le nom déjà à l'écran ;
- faute de `player`, le panneau (comme l'action `progression`) retombe sur le
  compte de la personne qui parle — ici KingsRequin, qui n'est pas sondé et n'a
  donc aucun relevé — alors que la question portait sur quelqu'un d'autre. Le
  refus ne le disait pas, et Wally a répondu qu'il n'avait « pas de courbe sur
  ce live » alors que celle d'Azraël existait bel et bien.
"""
import json
import pathlib
import time

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex"


def _raw(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class _FakeClient:
    available = True

    def __init__(self, reponse):
        self._reponse = reponse

    async def get(self, endpoint, params=None):
        return self._reponse


class _FakeHistory:
    """Historique réduit à ce que le chemin de la courbe lui demande."""

    def __init__(self, points_par_uid):
        self._points = points_par_uid
        self.demandes = []

    async def rp_de_la_fenetre(self, uid, depuis):
        """Aucun relevé de RP : ces comptes-là ne sont pas sondés, et la courbe
        doit rester monochrome plutôt que d'inventer un mode de jeu."""
        return []

    async def debut_derniere_session(self, uid, **kw):
        """Le début du dernier bloc de jeu — ce sur quoi « ce stream » retombe
        une fois le live terminé."""
        points = self._points.get(str(uid), [])
        return points[0][0] if points else None

    async def progression(self, uid, notion, depuis, **kw):
        from bot.core.apex.history import Progression
        from datetime import datetime

        self.demandes.append((uid, notion, depuis))
        points = self._points.get(str(uid), [])
        if not points:
            return None
        return Progression(
            notion=notion,
            gain=points[-1][1] - points[0][1],
            depuis=datetime.fromtimestamp(points[0][0]),
            jusqua=datetime.fromtimestamp(points[-1][0]),
            points=points,
            complet=True,
        )


def _service(history=None):
    from bot.core.apex.service import ApexLegendsService

    svc = ApexLegendsService(client=_FakeClient(_raw("bridge_azrael")))
    svc.history = history
    return svc


# ── Le panneau ne part que s'il y a de quoi tracer ───────────────────────────


@pytest.mark.asyncio
async def test_sans_aucun_releve_le_panneau_ne_part_pas():
    """Le cas vécu : le compte visé n'est pas sondé, l'image serait un 404."""
    svc = _service(_FakeHistory({}))
    assert await svc.build_panel("progress", "Azrael_ttv") is None


@pytest.mark.asyncio
async def test_un_seul_releve_ne_fait_pas_une_courbe():
    """`render` refuse sous deux points : le panneau doit refuser AVANT lui,
    sinon la carte s'affiche avec un nom et sans graphe."""
    uid = _raw("bridge_azrael")["global"]["uid"]
    svc = _service(_FakeHistory({str(uid): [(time.time() - 600, 100)]}))
    assert await svc.build_panel("progress", "Azrael_ttv") is None


@pytest.mark.asyncio
async def test_avec_des_releves_le_panneau_porte_l_image_du_bon_compte():
    uid = str(_raw("bridge_azrael")["global"]["uid"])
    hist = _FakeHistory({uid: [(time.time() - 600, 100), (time.time() - 60, 104)]})
    panel = await _service(hist).build_panel("progress", "Azrael_ttv")
    assert panel["kind"] == "apex_progress"
    assert f"uid={uid}" in panel["image_url"]


@pytest.mark.asyncio
async def test_la_fenetre_verifiee_est_celle_que_l_image_tracera():
    """Vérifier une fenêtre et en tracer une autre ne vaudrait rien : le
    panneau passerait la garde puis l'image répondrait 404."""
    from bot.core.apex.history import debut_de_fenetre

    uid = str(_raw("bridge_azrael")["global"]["uid"])
    hist = _FakeHistory({uid: [(time.time() - 600, 100), (time.time() - 60, 104)]})
    maintenant = time.time()
    await _service(hist).build_panel("progress", "Azrael_ttv", period="jour")
    assert hist.demandes
    uid_vu, notion_vue, depuis_vu = hist.demandes[-1]
    assert (uid_vu, notion_vue) == (uid, "kills")
    assert depuis_vu == pytest.approx(
        debut_de_fenetre("jour", maintenant=maintenant), abs=2
    )


@pytest.mark.asyncio
async def test_sans_historique_branche_le_panneau_part_comme_avant():
    """L'historique est monté après coup par `main.py` : son absence ne doit
    pas faire disparaître un panneau qui marchait. La fenêtre doit alors être
    datable sans lui — « ce stream » ne l'est pas, une période nommée si."""
    panel = await _service(None).build_panel("progress", "Azrael_ttv", period="jour")
    assert panel["kind"] == "apex_progress"


@pytest.mark.asyncio
async def test_sans_rien_pour_dater_le_stream_aucune_carte_ne_part():
    """Ni live en cours, ni relevé : « la courbe de ce stream » n'a pas de
    début. Une carte partirait sur une fenêtre inventée."""
    assert await _service(None).build_panel(
        "progress", "Azrael_ttv", period="stream"
    ) is None


# ── Le refus dit DE QUI il parle ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_refus_nomme_le_compte_et_signale_le_repli_sur_le_demandeur():
    """Sans pseudo, la progression porte sur le compte de la personne qui
    parle. Le refus doit le dire : sinon Wally annonce au chat qu'il n'a pas de
    courbe d'Azraël alors qu'il vient d'interroger le compte de quelqu'un
    d'autre — c'est exactement ce qui s'est produit."""

    class _DB:
        async def apex_get_account(self, identity):
            return {"apex_name": "KingsRequin", "apex_platform": "PC",
                    "uid": "1012242925358"}

        async def apex_find_by_display_name(self, name):
            return None

    from bot.core.apex.service import ApexLegendsService

    svc = ApexLegendsService(client=_FakeClient(_raw("bridge_azrael")), db=_DB())
    svc.history = _FakeHistory({})
    reponse = await svc.execute(
        "progression", "", period="jour", requester="twitch:105904256",
    )
    assert "KingsRequin" in reponse
    assert "player_name" in reponse


# ── Le chat Twitch ne porte pas d'image, l'écran du stream si ────────────────


def _service_avec_courbe():
    uid = str(_raw("bridge_azrael")["global"]["uid"])
    svc = _service(_FakeHistory({uid: [(time.time() - 600, 100),
                                       (time.time() - 60, 174)]}))

    class _DB:
        async def apex_find_by_display_name(self, name):
            return {"apex_name": "Azrael_TTV", "apex_platform": "PC", "uid": uid}

        async def apex_get_account(self, identity):
            return None

    svc._db = _DB()
    return svc


@pytest.mark.asyncio
async def test_sans_piece_jointe_mais_avec_un_live_la_courbe_va_a_l_ecran():
    """Le cas vécu sur Twitch : « affiche la courbe de kill d'azra » pendant le
    live. L'outil répondait « tu ne peux pas envoyer d'image ici » et s'arrêtait
    là — Wally s'excusait au lieu de la mettre sur l'overlay, qui est pourtant
    la seule sortie visuelle du chat Twitch."""
    reponse = await _service_avec_courbe().execute(
        "progression", "azra", period="live", requester="twitch:105904256",
        peut_joindre_image=False, ecran_disponible=True,
    )
    assert "+74 kills" in reponse
    assert "show_apex" in reponse
    assert "Azrael_TTV" in reponse


@pytest.mark.asyncio
async def test_sans_ecran_ni_piece_jointe_on_reste_aux_chiffres():
    """Hors live, il n'y a aucune sortie visuelle : proposer l'écran ferait
    promettre un affichage qui n'arrivera pas."""
    reponse = await _service_avec_courbe().execute(
        "progression", "azra", period="live", requester="twitch:105904256",
        peut_joindre_image=False, ecran_disponible=False,
    )
    assert "show_apex" not in reponse
    assert "n'invente" in reponse


@pytest.mark.asyncio
async def test_avec_piece_jointe_l_ecran_ne_change_rien():
    """Sur Discord la courbe voyage avec la réponse : on ne renvoie personne
    vers l'overlay, et surtout pas vers un lien à inventer."""
    reponse = await _service_avec_courbe().execute(
        "progression", "azra", period="live", requester="discord:610550333042589752",
        peut_joindre_image=True, ecran_disponible=True,
    )
    assert "pièce jointe" in reponse
    assert "show_apex" not in reponse
