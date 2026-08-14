"""EventSub mort silencieusement : personne ne le relançait.

Vécu le 2026-08-08 à 20:11 pendant le live d'Azraël : une coupure réseau brève
(`Failed to fetch Twitch stream status:` sans message) a emporté la WebSocket
EventSub. Twitch a alors révoqué les souscriptions attachées à la session —
`helix/eventsub/subscriptions` renvoyait `total: 0`. Aucun log d'erreur, aucune
reconnexion : Wally est resté SOURD sur Twitch pendant plus de vingt minutes,
jusqu'à ce qu'on le redémarre à la main. Twitchio v2 n'est plus maintenu et sa
reconnexion est notoirement peu fiable ; la doc Twitch impose de toute façon de
se RÉabonner après une perte de connexion.

La source de vérité est donc Twitch lui-même, pas l'état interne de la lib.
"""
import pytest

from bot.twitch.bot import WallyTwitch


_TOKENS = {"bot": "tok-bot", "streamer": "tok-streamer"}


def _bot(monkeypatch, active, streamer_token=_TOKENS["streamer"]):
    """`active` : ce que Twitch répond, par côté.

    Un entier (ou None si la requête échoue) s'applique aux deux côtés ; un dict
    `{"bot": …, "streamer": …}` permet de n'en faire tomber qu'un — c'est le cas
    réel du 2026-08-13.

    Renvoie `(bot, relances, sondes)` où `sondes` liste les côtés interrogés.
    """
    bot = WallyTwitch.__new__(WallyTwitch)
    WallyTwitch._init_eventsub_restart_state(bot)
    bot.token_manager = type(
        "_TM", (), {"bot_token": _TOKENS["bot"], "streamer_token": streamer_token}
    )()
    restarts: list[int] = []
    sondes: list[str] = []
    reponses = active if isinstance(active, dict) else {"bot": active, "streamer": active}

    async def _fake_count(client_id, token):
        cote = next(c for c, t in _TOKENS.items() if t == token)
        sondes.append(cote)
        return reponses[cote]

    async def _fake_restart():
        restarts.append(1)

    monkeypatch.setattr("bot.twitch.events.count_active_subscriptions", _fake_count)
    bot._restart_eventsub = _fake_restart
    return bot, restarts, sondes


@pytest.mark.asyncio
async def test_zero_souscription_declenche_un_redemarrage(monkeypatch):
    """Deux lectures à zéro, pas une.

    La confirmation a été ajoutée après coup : une reconstruction dure une
    quinzaine de secondes et passe elle-même par zéro souscription, donc un
    sondage unique pouvait relancer par-dessus une relance en cours. La
    propriété qui compte — « Twitch ne reconnaît plus rien → on relance » —
    est inchangée, elle demande juste d'être confirmée au tour suivant.
    """
    bot, restarts, _ = _bot(monkeypatch, 0)
    await bot._check_eventsub_alive()
    assert restarts == []          # première lecture : on confirme d'abord
    await bot._check_eventsub_alive()
    assert restarts == [1]


@pytest.mark.asyncio
async def test_souscriptions_vivantes_ne_declenchent_rien(monkeypatch):
    bot, restarts, _ = _bot(monkeypatch, 3)
    await bot._check_eventsub_alive()
    assert restarts == []


@pytest.mark.asyncio
async def test_requete_en_echec_ne_declenche_rien(monkeypatch):
    """Ne pas confondre « je n'ai pas pu demander » et « il n'y a plus rien » :
    c'est justement une coupure réseau qui a tout déclenché."""
    bot, restarts, _ = _bot(monkeypatch, None)
    await bot._check_eventsub_alive()
    assert restarts == []


@pytest.mark.asyncio
async def test_pas_de_relance_pendant_une_reconstruction(monkeypatch):
    """Pendant les ~15 s de reconstruction, Twitch renvoie temporairement 0."""
    bot, restarts, _ = _bot(monkeypatch, 0)
    async with bot._eventsub_restart_lock:
        await bot._check_eventsub_alive()
    assert restarts == []


# ── Les deux jeux de souscriptions meurent séparément ────────────────────────
#
# Vécu le 2026-08-13 en plein live : une récompense de points de chaîne achetée,
# jamais reçue. Les six souscriptions créées avec le token du STREAMER (abos,
# resubs, gifts, bits, points de chaîne) étaient toutes en
# `websocket_disconnected` ; les six du token du BOT répondaient `enabled`. Une
# souscription EventSub n'étant visible que du token qui l'a créée, le chien de
# garde — qui n'interrogeait que le token du bot — voyait tout vert.


@pytest.mark.asyncio
async def test_les_deux_tokens_sont_interroges(monkeypatch):
    bot, _, sondes = _bot(monkeypatch, 3)
    await bot._check_eventsub_alive()
    assert set(sondes) == {"bot", "streamer"}


@pytest.mark.asyncio
async def test_le_cote_streamer_mort_seul_declenche_la_relance(monkeypatch):
    """L'incident exact : le bot entend le chat, le streamer n'entend plus les
    points de chaîne ni les abonnements."""
    bot, restarts, _ = _bot(monkeypatch, {"bot": 6, "streamer": 0})
    await bot._check_eventsub_alive()
    assert restarts == []          # confirmation d'abord
    await bot._check_eventsub_alive()
    assert restarts == [1]


@pytest.mark.asyncio
async def test_le_cote_bot_mort_seul_declenche_la_relance(monkeypatch):
    """La symétrie compte : le chat peut tomber pendant que les abos tiennent."""
    bot, restarts, _ = _bot(monkeypatch, {"bot": 0, "streamer": 6})
    await bot._check_eventsub_alive()
    await bot._check_eventsub_alive()
    assert restarts == [1]


@pytest.mark.asyncio
async def test_un_cote_muet_ne_masque_pas_lautre_cote_mort(monkeypatch):
    """Une sonde sans réponse d'un côté ne dispense pas d'agir sur l'autre."""
    bot, restarts, _ = _bot(monkeypatch, {"bot": None, "streamer": 0})
    await bot._check_eventsub_alive()
    await bot._check_eventsub_alive()
    assert restarts == [1]


@pytest.mark.asyncio
async def test_un_cote_muet_lautre_vivant_ne_declenche_rien(monkeypatch):
    """« Je n'ai pas pu demander » ne devient jamais un diagnostic de panne."""
    bot, restarts, _ = _bot(monkeypatch, {"bot": 6, "streamer": None})
    await bot._check_eventsub_alive()
    await bot._check_eventsub_alive()
    assert restarts == []


@pytest.mark.asyncio
async def test_sans_token_streamer_rien_a_surveiller_de_ce_cote(monkeypatch):
    """`STREAMER_ACCESS_TOKEN` vide : aucune souscription streamer n'existe,
    l'absence de réponse de ce côté ne doit pas passer pour une panne."""
    bot, restarts, sondes = _bot(monkeypatch, {"bot": 6, "streamer": 0}, streamer_token="")
    await bot._check_eventsub_alive()
    await bot._check_eventsub_alive()
    assert sondes == ["bot", "bot"]
    assert restarts == []


@pytest.mark.asyncio
async def test_le_log_de_relance_nomme_le_cote_tombe(monkeypatch):
    """Sans ça, l'incident reste invisible : le message ne disait pas lequel des
    deux jeux de souscriptions était mort."""
    from loguru import logger

    lignes: list[str] = []
    sink = logger.add(lambda m: lignes.append(m.record["message"]), level="WARNING")
    try:
        bot, restarts, _ = _bot(monkeypatch, {"bot": 6, "streamer": 0})
        await bot._check_eventsub_alive()
        await bot._check_eventsub_alive()
    finally:
        logger.remove(sink)

    assert restarts == [1]
    relance = [l for l in lignes if "relance (tentative" in l]
    assert relance and "streamer" in relance[0] and "bot" not in relance[0]


@pytest.mark.asyncio
async def test_une_relance_qui_ne_ramene_quun_cote_reste_un_echec(monkeypatch):
    """La relance n'est réussie que si les DEUX côtés répondent à nouveau :
    sinon le recul progressif doit continuer de croître."""
    bot, restarts, _ = _bot(monkeypatch, {"bot": 6, "streamer": 0})
    await bot._check_eventsub_alive()
    await bot._check_eventsub_alive()
    assert restarts == [1]
    assert bot._eventsub_failed_restarts == 1


@pytest.mark.asyncio
async def test_count_ne_compte_que_les_souscriptions_vivantes(monkeypatch):
    """Une souscription `websocket_disconnected` occupe une place mais ne livre
    plus rien : la compter masquerait exactement la panne qu'on cherche."""
    import bot.twitch.events as ev

    payload = {"data": [
        {"status": "enabled", "transport": {"method": "websocket"}},
        {"status": "websocket_disconnected", "transport": {"method": "websocket"}},
        {"status": "enabled", "transport": {"method": "webhook"}},
    ]}

    class _Resp:
        status_code = 200

        def json(self):
            return payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr(ev.httpx, "AsyncClient", lambda **kw: _Client())
    assert await ev.count_active_subscriptions("cid", "tok") == 1


@pytest.mark.asyncio
async def test_count_renvoie_none_si_twitch_repond_mal(monkeypatch):
    import bot.twitch.events as ev

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            raise RuntimeError("réseau coupé")

    monkeypatch.setattr(ev.httpx, "AsyncClient", lambda **kw: _Client())
    assert await ev.count_active_subscriptions("cid", "tok") is None
