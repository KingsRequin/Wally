"""Tests for TwitchAPI.send_message — Helix POST with 401 retry."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loguru import logger as _loguru

from bot.twitch.api import TwitchAPI


def make_api(bot_token="bot_tok") -> TwitchAPI:
    tm = MagicMock()
    tm.bot_token = bot_token
    tm.refresh = AsyncMock(return_value=True)
    return TwitchAPI(
        token_manager=tm,
        client_id="cid",
        bot_id="bot_id",
        broadcaster_id="bc_id",
    )


def make_http_response(status=200, payload=None):
    resp = MagicMock()
    resp.status_code = status
    # Corps réel de l'API : c'est LUI qui dit si le message a été publié, le
    # statut HTTP valant seulement « la requête était recevable ».
    resp.json = MagicMock(return_value=payload if payload is not None else {
        "data": [{"message_id": "abc", "is_sent": True, "drop_reason": None}]
    })
    if status == 200:
        resp.raise_for_status = MagicMock()
    else:
        import httpx as _httpx
        resp.raise_for_status = MagicMock(
            side_effect=_httpx.HTTPStatusError(
                f"HTTP {status}", request=MagicMock(), response=MagicMock()
            )
        )
    return resp


@pytest.mark.asyncio
async def test_send_message_calls_helix():
    api = make_api()
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("hello world")
    mock_http.post.assert_awaited_once()
    call_kwargs = mock_http.post.call_args
    body = call_kwargs.kwargs["json"]
    assert body["broadcaster_id"] == "bc_id"
    assert body["sender_id"] == "bot_id"
    assert body["message"] == "hello world"


@pytest.mark.asyncio
async def test_send_message_uses_bot_token_in_header():
    api = make_api(bot_token="my_token")
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("test")
    headers = mock_http.post.call_args.kwargs["headers"]
    assert "Bearer my_token" in headers["Authorization"]


@pytest.mark.asyncio
async def test_send_message_retries_on_401():
    api = make_api()
    unauthorized = make_http_response(401)
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(side_effect=[unauthorized, ok])
        await api.send_message("retry me")
    assert mock_http.post.await_count == 2
    api._tm.refresh.assert_awaited_once_with("bot")


@pytest.mark.asyncio
async def test_send_message_gives_up_after_second_401():
    api = make_api()
    unauthorized = make_http_response(401)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(side_effect=[unauthorized, unauthorized])
        await api.send_message("fail")
    assert mock_http.post.await_count == 2
    api._tm.refresh.assert_awaited_once_with("bot")


@pytest.mark.asyncio
async def test_send_message_no_retry_if_refresh_fails():
    api = make_api()
    api._tm.refresh = AsyncMock(return_value=False)
    unauthorized = make_http_response(401)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=unauthorized)
        await api.send_message("fail")
    assert mock_http.post.await_count == 1


@pytest.mark.asyncio
async def test_send_message_with_reply_parent():
    """reply_parent_message_id is included in the JSON body when provided."""
    api = make_api()
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("hello", reply_parent_message_id="msg-abc-123")
    body = mock_http.post.call_args.kwargs["json"]
    assert body["reply_parent_message_id"] == "msg-abc-123"


@pytest.mark.asyncio
async def test_send_message_without_reply_parent_omits_field():
    """reply_parent_message_id is NOT in the JSON body when not provided."""
    api = make_api()
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("hello")
    body = mock_http.post.call_args.kwargs["json"]
    assert "reply_parent_message_id" not in body


# --- get_last_clip : le plus récent, éventuellement d'une personne précise ---
#
# Helix trie les clips par nombre de vues et ne sait PAS filtrer par créateur :
# les deux tris se font ici.

CLIPS = [
    {"id": "a", "creator_name": "KingsRequin", "created_at": "2026-08-08T10:00:00Z"},
    {"id": "b", "creator_name": "Azrael", "created_at": "2026-08-08T09:00:00Z"},
    {"id": "c", "creator_name": "azrael_ttv", "created_at": "2026-08-07T20:00:00Z"},
]


@pytest.mark.asyncio
async def test_get_last_clip_prend_le_plus_recent():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    assert (await api.get_last_clip())["id"] == "a"


@pytest.mark.asyncio
async def test_get_last_clip_filtre_sur_le_clippeur():
    """« le dernier clip fait par azra » : le plus récent d'Azrael, pas celui
    de la chaîne."""
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    assert (await api.get_last_clip(creator="azra"))["id"] == "b"


@pytest.mark.asyncio
async def test_get_last_clip_sans_clip_de_cette_personne():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    assert await api.get_last_clip(creator="taki") is None


@pytest.mark.asyncio
async def test_get_last_clip_sans_aucun_clip():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=[])
    assert await api.get_last_clip() is None


# ── Un message refusé par Twitch ─────────────────────────────────────────────
# `POST /helix/chat/messages` répond 200 même quand il ne publie RIEN : le refus
# vit dans le corps, sous `is_sent: false` et `drop_reason`. AutoMod, mode
# abonnés/followers, bot en timeout — autant de cas où la réponse de Wally
# n'atteint personne. Sans cette lecture, il posait son cooldown, notait sa
# question ouverte et rangeait en mémoire une réplique que personne n'a lue.


async def _envoi(resp):
    """Joue un send_message contre une réponse HTTP donnée.

    L'`await` reste DANS le `with` : rendre la coroutine sans l'attendre
    laissait le patch se refermer avant l'appel, `httpx` partait pour de vrai,
    et l'échec réseau faisait passer le test du refus pour la mauvaise raison.
    """
    api = make_api()
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=resp)
        return await api.send_message("coucou")


@pytest.mark.asyncio
async def test_send_message_rend_faux_quand_twitch_refuse():
    refuse = make_http_response(200, {"data": [{
        "message_id": "abc", "is_sent": False,
        "drop_reason": {"code": "channel_settings",
                        "message": "follower only mode"},
    }]})
    assert await _envoi(refuse) is False


@pytest.mark.asyncio
async def test_send_message_dit_pourquoi_le_message_est_tombe():
    """La raison vient de Twitch : la deviner coûtait une soirée (cf. le 429
    EventSub, en réalité un 400 déguisé). On la journalise telle quelle.

    Capture par un puits loguru et non `caplog` : loguru ne passe pas par le
    module `logging`, où le test aurait constaté un silence trompeur.
    """
    refuse = make_http_response(200, {"data": [{
        "message_id": "abc", "is_sent": False,
        "drop_reason": {"code": "msg_rejected", "message": "held by AutoMod"},
    }]})
    lignes: list[str] = []
    jeton = _loguru.add(lambda m: lignes.append(str(m)), level="WARNING")
    try:
        await _envoi(refuse)
    finally:
        _loguru.remove(jeton)
    assert any("msg_rejected" in l and "AutoMod" in l for l in lignes), lignes


@pytest.mark.asyncio
async def test_send_message_rend_vrai_quand_twitch_publie():
    assert await _envoi(make_http_response(200)) is True


@pytest.mark.asyncio
async def test_un_corps_illisible_ne_fait_pas_perdre_un_message_parti():
    """Le doute profite à l'envoi : Twitch a répondu 200, et rendre `False` ici
    effacerait de la mémoire de Wally une réplique bel et bien publiée."""
    muet = make_http_response(200)
    muet.json = MagicMock(side_effect=ValueError("pas du JSON"))
    assert await _envoi(muet) is True


@pytest.mark.asyncio
async def test_une_reponse_sans_drop_reason_reste_un_refus():
    """`drop_reason` peut être absent ou nul : c'est `is_sent` qui tranche.
    Un `.get(clé, défaut)` ne couvre pas `clé: null`."""
    refuse = make_http_response(200, {"data": [{"is_sent": False, "drop_reason": None}]})
    assert await _envoi(refuse) is False


# ── create_clip : POST asynchrone, puis attente que le clip EXISTE ──
# La réponse de `POST /helix/clips` rend un `id`, pas un clip. Annoncer l'URL
# tout de suite, c'est promettre une page qui rendra 404 au premier qui clique.

def _api_streamer(streamer_token="str_tok") -> TwitchAPI:
    tm = MagicMock()
    tm.bot_token = "bot_tok"
    tm.streamer_token = streamer_token
    tm.refresh = AsyncMock(return_value=True)
    return TwitchAPI(token_manager=tm, client_id="cid",
                     bot_id="bot_id", broadcaster_id="bc_id")


class _FauxHTTP:
    """Un client httpx qui rend des réponses scriptées, et note les appels."""

    def __init__(self, post_resp, get_resps):
        self.post_resp = post_resp
        self.get_resps = list(get_resps)
        self.posts: list[dict] = []
        self.gets = 0

    def __call__(self, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, params=None, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "params": params, "json": json,
                           "headers": headers})
        return self.post_resp

    async def get(self, url, params=None, headers=None, timeout=None):
        self.gets += 1
        return self.get_resps.pop(0) if self.get_resps else make_http_response(
            200, {"data": []})


@pytest.mark.asyncio
async def test_create_clip_poste_titre_et_duree():
    api = _api_streamer()
    http = _FauxHTTP(
        make_http_response(202, {"data": [{"id": "ClipId", "edit_url": "e"}]}),
        [make_http_response(200, {"data": [{"id": "ClipId",
                                            "url": "https://clips.twitch.tv/ClipId",
                                            "title": "kill au wingman"}]})],
    )
    with patch("bot.twitch.api.httpx.AsyncClient", http), \
         patch("bot.twitch.api.asyncio.sleep", AsyncMock()):
        clip = await api.create_clip("kill au wingman", 40)

    assert clip["url"] == "https://clips.twitch.tv/ClipId"
    envoye = http.posts[0]
    assert envoye["json"] == {"duration": 40, "title": "kill au wingman"}
    assert envoye["params"] == {"broadcaster_id": "bc_id"}
    # Token STREAMER : c'est lui qui porte `channel:manage:clips`.
    assert "str_tok" in envoye["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_create_clip_borne_la_duree_au_lieu_de_refuser():
    """« clippe les 2 dernières minutes » est légitime ; Twitch plafonne à 60 s."""
    api = _api_streamer()
    http = _FauxHTTP(
        make_http_response(202, {"data": [{"id": "C"}]}),
        [make_http_response(200, {"data": [{"id": "C", "url": "u"}]})],
    )
    with patch("bot.twitch.api.httpx.AsyncClient", http), \
         patch("bot.twitch.api.asyncio.sleep", AsyncMock()):
        await api.create_clip("", 120)
    assert http.posts[0]["json"]["duration"] == 60

    http2 = _FauxHTTP(
        make_http_response(202, {"data": [{"id": "C"}]}),
        [make_http_response(200, {"data": [{"id": "C", "url": "u"}]})],
    )
    with patch("bot.twitch.api.httpx.AsyncClient", http2), \
         patch("bot.twitch.api.asyncio.sleep", AsyncMock()):
        await api.create_clip("", 1)
    assert http2.posts[0]["json"]["duration"] == 5


@pytest.mark.asyncio
async def test_create_clip_sans_titre_n_envoie_pas_le_champ():
    """Un `title: ""` poserait un titre VIDE au lieu de laisser celui de Twitch."""
    api = _api_streamer()
    http = _FauxHTTP(
        make_http_response(202, {"data": [{"id": "C"}]}),
        [make_http_response(200, {"data": [{"id": "C", "url": "u"}]})],
    )
    with patch("bot.twitch.api.httpx.AsyncClient", http), \
         patch("bot.twitch.api.asyncio.sleep", AsyncMock()):
        await api.create_clip("")
    assert "title" not in http.posts[0]["json"]
    assert http.posts[0]["json"]["duration"] == 30      # le défaut documenté


@pytest.mark.asyncio
async def test_create_clip_hors_live_rend_none_sans_bruit():
    """404 = aucun stream en cours. C'est le cas NORMAL, pas une panne."""
    api = _api_streamer()
    http = _FauxHTTP(make_http_response(404, {}), [])
    with patch("bot.twitch.api.httpx.AsyncClient", http), \
         patch("bot.twitch.api.asyncio.sleep", AsyncMock()):
        assert await api.create_clip("peu importe") is None
    assert http.gets == 0          # rien à attendre, on n'interroge pas


@pytest.mark.asyncio
async def test_create_clip_attend_que_le_clip_existe():
    """Les premières interrogations rendent une liste vide : c'est l'attente."""
    api = _api_streamer()
    http = _FauxHTTP(
        make_http_response(202, {"data": [{"id": "C"}]}),
        [make_http_response(200, {"data": []}),
         make_http_response(200, {"data": []}),
         make_http_response(200, {"data": [{"id": "C", "url": "enfin"}]})],
    )
    with patch("bot.twitch.api.httpx.AsyncClient", http), \
         patch("bot.twitch.api.asyncio.sleep", AsyncMock()):
        clip = await api.create_clip("")
    assert clip["url"] == "enfin"
    assert http.gets == 3


@pytest.mark.asyncio
async def test_un_clip_jamais_revenu_n_est_PAS_annonce():
    api = _api_streamer()
    http = _FauxHTTP(make_http_response(202, {"data": [{"id": "C"}]}), [])
    with patch("bot.twitch.api.httpx.AsyncClient", http), \
         patch("bot.twitch.api.asyncio.sleep", AsyncMock()):
        assert await api.create_clip("") is None


@pytest.mark.asyncio
async def test_le_titre_passe_par_le_filet_du_mot_secret():
    """Un titre de clip est PUBLIC et définitif — la dernière place où laisser
    filer le mot du pendu en cours."""
    from bot.core.secret_guard import clear_secrets, guard_secret

    api = _api_streamer()
    http = _FauxHTTP(
        make_http_response(202, {"data": [{"id": "C"}]}),
        [make_http_response(200, {"data": [{"id": "C", "url": "u"}]})],
    )
    guard_secret("gibraltar")
    try:
        with patch("bot.twitch.api.httpx.AsyncClient", http), \
             patch("bot.twitch.api.asyncio.sleep", AsyncMock()):
            await api.create_clip("le mot était gibraltar")
    finally:
        clear_secrets()
    assert "gibraltar" not in http.posts[0]["json"]["title"].lower()
