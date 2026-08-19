# tests/test_voice_last_channel.py
"""Après un redémarrage, Wally retourne là où il était.

Il rejoignait le salon vocal écrit en config, quel que soit celui où on l'avait
déplacé avant la coupure — et un rebuild d'image suffit à le déplacer.
"""
import pytest
import pytest_asyncio

from bot.db.database import Database
from bot.discord.voice.channel_memory import (
    LAST_CHANNEL_KEY,
    remember_voice_channel,
    resolve_voice_channel,
    resolve_voice_channel_id,
)


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


@pytest.mark.asyncio
async def test_sans_souvenir_on_prend_le_salon_configure(db):
    assert await resolve_voice_channel_id(db, configured=1267757914953875487) == 1267757914953875487


@pytest.mark.asyncio
async def test_le_dernier_salon_rejoint_l_emporte(db):
    await remember_voice_channel(db, 999888777)
    assert await resolve_voice_channel_id(db, configured=1267757914953875487) == 999888777


@pytest.mark.asyncio
async def test_le_souvenir_se_met_a_jour(db):
    await remember_voice_channel(db, 111)
    await remember_voice_channel(db, 222)
    assert await resolve_voice_channel_id(db, configured=1) == 222


@pytest.mark.asyncio
async def test_sans_rien_du_tout_il_n_y_a_pas_de_salon(db):
    assert await resolve_voice_channel_id(db, configured=None) is None


@pytest.mark.asyncio
async def test_une_base_muette_ne_bloque_pas_le_demarrage(db):
    """Une lecture d'état ratée ne doit pas empêcher de rejoindre le configuré."""

    class _Cassee:
        async def get_state(self, *a, **k):
            raise RuntimeError("base indisponible")

    assert await resolve_voice_channel_id(_Cassee(), configured=42) == 42


@pytest.mark.asyncio
async def test_l_etat_est_bien_range_sous_sa_cle(db):
    await remember_voice_channel(db, 777)
    assert await db.get_state(LAST_CHANNEL_KEY) == "777"


# --- Un salon retenu peut avoir DISPARU -------------------------------------
# Constaté le 2026-08-19 : Wally avait rejoint la veille un salon vocal
# ÉPHÉMÈRE (créé à la volée, supprimé dès qu'il se vide). L'identifiant retenu
# ne désignait plus rien, `get_channel()` rendait None, le veilleur passait son
# tour EN SILENCE — et le repli sur le salon de config n'était jamais atteint.
# Trois heures de live sans Wally, sans une ligne de log.


class _Disparu(Exception):
    """Ce que Discord lève pour un salon qui n'existe plus."""
    status = 404


class _Panne(Exception):
    """Discord injoignable : on ne sait RIEN du salon."""
    status = 500


class _FauxBot:
    def __init__(self, cache=None, api=None):
        self._cache = cache or {}
        self._api = api or {}
        self.fetched: list[int] = []

    def get_channel(self, channel_id):
        return self._cache.get(channel_id)

    async def fetch_channel(self, channel_id):
        self.fetched.append(channel_id)
        found = self._api.get(channel_id)
        if found is None:
            raise _Disparu()
        if isinstance(found, Exception):
            raise found
        return found


@pytest.mark.asyncio
async def test_un_salon_retenu_encore_vivant_est_rendu_sans_appel_api(db):
    await remember_voice_channel(db, 555)
    bot = _FauxBot(cache={555: "salon-du-soir"})
    assert await resolve_voice_channel(bot, db, configured=1) == "salon-du-soir"
    assert bot.fetched == []          # le cache suffit : aucun aller-retour


@pytest.mark.asyncio
async def test_un_salon_retenu_disparu_est_oublie_et_on_retombe_sur_la_config(db):
    await remember_voice_channel(db, 1539351262355652690)
    bot = _FauxBot(cache={1267757914953875487: "salon-de-stream"})
    got = await resolve_voice_channel(bot, db, configured=1267757914953875487)
    assert got == "salon-de-stream"
    assert await db.get_state(LAST_CHANNEL_KEY) is None   # le souvenir mort est effacé


@pytest.mark.asyncio
async def test_le_souvenir_mort_est_oublie_meme_sans_repli(db):
    await remember_voice_channel(db, 42)
    bot = _FauxBot()
    assert await resolve_voice_channel(bot, db, configured=None) is None
    assert await db.get_state(LAST_CHANNEL_KEY) is None


@pytest.mark.asyncio
async def test_discord_injoignable_ne_fait_PAS_oublier_le_salon(db):
    """Une panne réseau ne doit pas coûter le salon du soir."""
    await remember_voice_channel(db, 777)
    bot = _FauxBot(api={777: _Panne()})
    with pytest.raises(_Panne):
        await resolve_voice_channel(bot, db, configured=1)
    assert await db.get_state(LAST_CHANNEL_KEY) == "777"


@pytest.mark.asyncio
async def test_un_salon_hors_cache_mais_vivant_est_rendu(db):
    """Cache froid au démarrage : l'appel API tranche, sans rien oublier."""
    await remember_voice_channel(db, 888)
    bot = _FauxBot(api={888: "salon-froid"})
    assert await resolve_voice_channel(bot, db, configured=1) == "salon-froid"
    assert await db.get_state(LAST_CHANNEL_KEY) == "888"
