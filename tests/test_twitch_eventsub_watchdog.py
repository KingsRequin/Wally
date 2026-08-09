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


def _bot(monkeypatch, active):
    """`active` : ce que Twitch répond (nombre de souscriptions, ou None si la
    requête échoue)."""
    bot = WallyTwitch.__new__(WallyTwitch)
    WallyTwitch._init_eventsub_restart_state(bot)
    bot.token_manager = type("_TM", (), {"bot_token": "tok"})()
    restarts = []

    async def _fake_count(client_id, token):
        return active

    async def _fake_restart():
        restarts.append(1)

    monkeypatch.setattr("bot.twitch.events.count_active_subscriptions", _fake_count)
    bot._restart_eventsub = _fake_restart
    return bot, restarts


@pytest.mark.asyncio
async def test_zero_souscription_declenche_un_redemarrage(monkeypatch):
    """Deux lectures à zéro, pas une.

    La confirmation a été ajoutée après coup : une reconstruction dure une
    quinzaine de secondes et passe elle-même par zéro souscription, donc un
    sondage unique pouvait relancer par-dessus une relance en cours. La
    propriété qui compte — « Twitch ne reconnaît plus rien → on relance » —
    est inchangée, elle demande juste d'être confirmée au tour suivant.
    """
    bot, restarts = _bot(monkeypatch, 0)
    await bot._check_eventsub_alive()
    assert restarts == []          # première lecture : on confirme d'abord
    await bot._check_eventsub_alive()
    assert restarts == [1]


@pytest.mark.asyncio
async def test_souscriptions_vivantes_ne_declenchent_rien(monkeypatch):
    bot, restarts = _bot(monkeypatch, 3)
    await bot._check_eventsub_alive()
    assert restarts == []


@pytest.mark.asyncio
async def test_requete_en_echec_ne_declenche_rien(monkeypatch):
    """Ne pas confondre « je n'ai pas pu demander » et « il n'y a plus rien » :
    c'est justement une coupure réseau qui a tout déclenché."""
    bot, restarts = _bot(monkeypatch, None)
    await bot._check_eventsub_alive()
    assert restarts == []


@pytest.mark.asyncio
async def test_pas_de_relance_pendant_une_reconstruction(monkeypatch):
    """Pendant les ~15 s de reconstruction, Twitch renvoie temporairement 0."""
    bot, restarts = _bot(monkeypatch, 0)
    async with bot._eventsub_restart_lock:
        await bot._check_eventsub_alive()
    assert restarts == []


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
