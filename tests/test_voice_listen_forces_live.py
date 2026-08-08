# tests/test_voice_listen_forces_live.py
"""Le mode écoute suppose un live : sans stream, c'est qu'on teste.

Wally en écoute dans un salon vocal, c'est le compagnon de stream. S'il n'y a
pas de live derrière, il n'y a qu'une explication : on est en train de régler
quelque chose. Le mode test s'active donc tout seul, et se coupe quand il sort —
il reste borné par sa présence en vocal, jamais oublié.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.voice.readiness import (
    release_test_mode,
    take_test_mode_if_needed,
)


def _narrateur(live=False, restant=0.0):
    n = MagicMock()
    n.is_active = MagicMock(return_value=live)
    n.force_live = MagicMock(return_value=120.0)
    n.force_live_remaining = MagicMock(return_value=restant)
    n.flush_force_live = AsyncMock()
    return n


@pytest.mark.asyncio
async def test_sans_live_le_mode_test_s_active_tout_seul():
    n = _narrateur(live=False)
    assert await take_test_mode_if_needed(n) is True
    n.force_live.assert_called_once()


@pytest.mark.asyncio
async def test_pendant_un_vrai_live_on_ne_touche_a_rien():
    """Un vrai stream n'a pas besoin d'un mode test par-dessus."""
    n = _narrateur(live=True)
    assert await take_test_mode_if_needed(n) is False
    n.force_live.assert_not_called()


@pytest.mark.asyncio
async def test_un_mode_test_deja_pose_a_la_main_n_est_pas_touche():
    """Sinon on écraserait la durée choisie par le créateur."""
    n = _narrateur(live=True, restant=45.0)
    assert await take_test_mode_if_needed(n) is False
    n.force_live.assert_not_called()


@pytest.mark.asyncio
async def test_en_sortant_il_rend_ce_qu_il_a_pris():
    n = _narrateur(live=False)
    await take_test_mode_if_needed(n)
    await release_test_mode(n, taken=True)
    n.force_live.assert_called_with(0)


@pytest.mark.asyncio
async def test_il_ne_coupe_pas_un_mode_test_qu_il_n_a_pas_pose():
    n = _narrateur(live=False)
    await release_test_mode(n, taken=False)
    n.force_live.assert_not_called()


@pytest.mark.asyncio
async def test_sans_narrateur_rien_ne_casse():
    assert await take_test_mode_if_needed(None) is False
    await release_test_mode(None, taken=True)
