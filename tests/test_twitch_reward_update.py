# tests/test_twitch_reward_update.py
"""Une récompense déjà créée doit pouvoir être MISE À JOUR.

Sans ça, éditer `apex.duel` dans `config.yaml` n'avait aucun effet : le libellé
n'était écrit qu'à la création, et la récompense en service continuait
d'annoncer autre chose. La seule alternative aurait été de la recréer — or une
récompense recréée perd son historique, et une récompense créée hors de notre
application est irremboursable (403).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

TITRE = "Duel Apex contre Azraël"
PROMPT = "3 manches, le plus de kills gagne. Pseudo ou UID Apex."
COUT = 10000

ACTUELLE = {"id": "RW1", "title": "Duel Apex", "cost": 5000,
            "prompt": "Colle ton UID Apex"}
A_JOUR = {"id": "RW1", "title": TITRE, "cost": COUT, "prompt": PROMPT}


def _api(reponse):
    from bot.twitch.api import TwitchAPI
    tm = MagicMock(); tm.streamer_token = "tok"; tm.refresh = AsyncMock(return_value=True)
    api = TwitchAPI(tm, client_id="cid", bot_id="bot123", broadcaster_id="123")
    client = MagicMock()
    client.patch = AsyncMock(return_value=reponse)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return api, client


def _resp(status, payload):
    r = MagicMock(); r.status_code = status
    r.json.return_value = payload; r.text = str(payload)
    return r


@pytest.mark.asyncio
async def test_le_libelle_qui_a_change_est_reecrit_chez_twitch(monkeypatch):
    api, client = _api(_resp(200, {"data": [A_JOUR]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT, actuelle=ACTUELLE) is True

    envoye = client.patch.call_args.kwargs["json"]
    assert envoye["title"] == TITRE
    assert envoye["cost"] == COUT
    assert envoye["prompt"] == PROMPT
    assert client.patch.call_args.kwargs["params"]["id"] == "RW1"


@pytest.mark.asyncio
async def test_une_recompense_deja_conforme_ne_declenche_aucun_appel(monkeypatch):
    """Un démarrage ne doit pas écrire pour écrire : la récompense est
    republiée à chaque boot du bot."""
    api, client = _api(_resp(200, {"data": [A_JOUR]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT, actuelle=A_JOUR) is True

    client.patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_champ_que_twitch_ne_rend_pas_n_est_pas_un_champ_vide(monkeypatch):
    """Une absence n'est jamais un zéro : une réponse partielle ne prouve pas
    que le libellé diffère, et conclure l'inverse ferait patcher à chaque
    démarrage, pour toujours."""
    api, client = _api(_resp(200, {"data": [A_JOUR]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT,
                                    actuelle={"id": "RW1"}) is True

    client.patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_titre_trop_long_ne_fait_pas_patcher_a_chaque_demarrage(monkeypatch):
    """Twitch tronque à 45 caractères. Comparer la config brute au titre
    tronqué qu'il renvoie donnerait « différent » à chaque boot."""
    from bot.twitch.api import TITRE_MAX
    long_titre = "x" * 200
    api, client = _api(_resp(200, {"data": [A_JOUR]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    actuelle = {**A_JOUR, "title": long_titre[:TITRE_MAX]}
    assert await api.maj_recompense("RW1", long_titre, COUT, PROMPT,
                                    actuelle=actuelle) is True

    client.patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_200_qui_rend_l_ancien_libelle_est_un_echec(monkeypatch):
    """Sur Helix, un 200 ne prouve pas que l'ordre est passé — on lit le
    CORPS, comme partout ailleurs dans ce fichier."""
    api, client = _api(_resp(200, {"data": [ACTUELLE]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT, actuelle=ACTUELLE) is False


@pytest.mark.asyncio
async def test_un_corps_vide_est_un_echec(monkeypatch):
    api, client = _api(_resp(200, {"data": []}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT, actuelle=ACTUELLE) is False


@pytest.mark.asyncio
async def test_une_erreur_http_ne_leve_pas(monkeypatch):
    api, client = _api(_resp(403, {"error": "Forbidden"}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT, actuelle=ACTUELLE) is False


@pytest.mark.asyncio
async def test_un_401_est_retente_apres_renouvellement_du_token(monkeypatch):
    """Même filet que le remboursement : un token expiré ne doit pas laisser
    la récompense sur un libellé périmé."""
    api, client = _api(_resp(200, {"data": [A_JOUR]}))
    client.patch = AsyncMock(side_effect=[_resp(401, {"error": "Unauthorized"}),
                                          _resp(200, {"data": [A_JOUR]})])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT, actuelle=ACTUELLE) is True
    assert client.patch.await_count == 2
    api._tm.refresh.assert_awaited_once_with("streamer")


@pytest.mark.asyncio
async def test_sans_identifiant_aucun_appel_ne_part(monkeypatch):
    api, client = _api(_resp(200, {"data": [A_JOUR]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("", TITRE, COUT, PROMPT) is False
    client.patch.assert_not_awaited()


# ── Côté runner : c'est au démarrage que ça se joue ──────────────────────────
def _runner_avec_recompense(gerables):
    from bot.core.apex.duel_runner import DuelRunner
    db = MagicMock()
    db.get_state = AsyncMock(return_value="RW1")
    db.set_state = AsyncMock()
    api = MagicMock()
    api.recompenses_gerables = AsyncMock(return_value=gerables)
    api.creer_recompense = AsyncMock(return_value="NEUVE")
    api.maj_recompense = AsyncMock(return_value=True)
    runner = DuelRunner(client=MagicMock(), db=db, api=api, annoncer=AsyncMock(),
                        azrael_uid="7")
    return runner, api


@pytest.mark.asyncio
async def test_au_demarrage_la_recompense_est_remise_a_jour():
    """La récompense existe déjà sur la chaîne : changer la configuration doit
    suffire à changer ce que le viewer lit avant de payer."""
    runner, api = _runner_avec_recompense([ACTUELLE])

    rid = await runner.assurer_recompense(TITRE, COUT, PROMPT)

    assert rid == "RW1"
    api.maj_recompense.assert_awaited_once()
    args, kwargs = api.maj_recompense.await_args
    assert args[0] == "RW1"
    assert TITRE in args and PROMPT in args and COUT in args
    assert kwargs["actuelle"] == ACTUELLE


@pytest.mark.asyncio
async def test_la_recompense_n_est_JAMAIS_recreee_pour_etre_mise_a_jour():
    """Une récompense recréée perd son historique, et l'ancienne devient
    irremboursable pour toute redemption encore en vol."""
    runner, api = _runner_avec_recompense([ACTUELLE])

    await runner.assurer_recompense(TITRE, COUT, PROMPT)

    api.creer_recompense.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_mise_a_jour_ratee_ne_prive_pas_le_duel_de_sa_recompense():
    """Le libellé est un confort ; le remboursement ne l'est pas. Un PATCH
    refusé ne doit ni perdre l'identifiant, ni faire recréer la récompense."""
    runner, api = _runner_avec_recompense([ACTUELLE])
    api.maj_recompense = AsyncMock(return_value=False)

    assert await runner.assurer_recompense(TITRE, COUT, PROMPT) == "RW1"
    api.creer_recompense.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_liste_indisponible_ne_declenche_aucune_ecriture():
    """Panne Twitch : on garde l'identifiant connu et on ne touche à rien —
    ni création, ni mise à jour sur un doute."""
    runner, api = _runner_avec_recompense(None)

    assert await runner.assurer_recompense(TITRE, COUT, PROMPT) == "RW1"
    api.maj_recompense.assert_not_awaited()
    api.creer_recompense.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_champ_de_saisie_se_met_a_jour_LUI_AUSSI(monkeypatch):
    """Sinon changer `SAISIE_REQUISE` sur une récompense DÉJÀ créée ne ferait
    rien — silencieusement. La mise à jour ne portait que le titre, le coût et
    l'invite, et la divergence n'aurait sauté aux yeux de personne : la
    récompense continue de marcher, avec son champ de trop.
    """
    api, client = _api(_resp(200, {"data": [{"id": "RW42"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.maj_recompense("RW42", "Titre", 100, "invite",
                             actuelle={"title": "Titre", "cost": 100,
                                       "prompt": "invite",
                                       "is_user_input_required": True},
                             saisie_requise=False)
    corps = client.patch.call_args.kwargs["json"]
    assert corps["is_user_input_required"] is False


@pytest.mark.asyncio
async def test_rien_n_est_envoye_quand_TOUT_concorde_saisie_comprise(monkeypatch):
    """L'autre moitié : un PATCH par démarrage, pour rien, sur une récompense
    déjà conforme — c'est ce que ce fichier existe pour éviter."""
    api, client = _api(_resp(200, {"data": [{"id": "RW42"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.maj_recompense("RW42", "Titre", 100, "invite",
                             actuelle={"title": "Titre", "cost": 100,
                                       "prompt": "invite",
                                       "is_user_input_required": False},
                             saisie_requise=False)
    client.patch.assert_not_awaited()
