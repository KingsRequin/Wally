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
