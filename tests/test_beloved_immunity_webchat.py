# tests/test_beloved_immunity_webchat.py
"""
Garde d'immunité "utilisateur aimé" côté web chat (`bot/dashboard/routes/chat.py::_post_process`).

Bug corrigé : `_post_process` n'appelait pas `is_beloved`, ne transmettait pas
`beloved=` à `emotion.process_message`, et n'avait aucune garde sur
`update_trust_score` — un utilisateur aimé (ex. Malef, discord:706837895063011338)
insultant Wally depuis le web chat public dégradait la colère GLOBALE
(`EmotionEngine._state` est partagée par toutes les plateformes) et son propre
trust, alors que les 6 autres chemins (Discord texte/spontané/`/wally ask`,
Twitch x2, vocal) protègent déjà cet utilisateur. Miroir de
tests/test_beloved_immunity_twitch.py (Garde 3, Twitch).

⚠️ PIÈGE MagicMock : un MagicMock non configuré est truthy → `is_beloved()`
semblerait toujours True si on ne fixe pas explicitement `return_value=True/False`.

⚠️ PIÈGE double-préfixe : `sender_id` reçu par `_post_process` vaut déjà
`f"discord:{id}"` (préfixé) — `is_beloved` doit être interrogé avec l'ID BRUT
(`sender_id.split(":")[1]`), jamais `sender_id` tel quel, sinon la clé
construite en interne (`discord:discord:...`) ne matche jamais rien et la
garde est silencieusement morte.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.dashboard.routes.chat import _post_process

MALEF_DISCORD_ID = "706837895063011338"
OTHER_DISCORD_ID = "999999999999999"
INSULT = "connard, ta gueule, je te déteste"


def make_state():
    state = MagicMock()
    state.persona.is_beloved = MagicMock(return_value=False)
    state.db.update_trust_score = AsyncMock()
    state.emotion.process_message = AsyncMock(
        return_value={"trust_delta": -0.08, "love_delta": 0.0, "user_facts": []}
    )
    return state


@pytest.mark.asyncio
async def test_beloved_user_insult_beloved_passed_and_trust_not_dropped():
    """Utilisateur aimé qui insulte : beloved=True transmis à process_message
    (bloque la hausse d'anger globale, cf. EmotionEngine.prepare_deltas) et le
    trust n'est PAS dégradé malgré le trust_delta négatif renvoyé."""
    state = make_state()
    state.persona.is_beloved = MagicMock(return_value=True)

    await _post_process(state, INSULT, f"discord:{MALEF_DISCORD_ID}", trust=0.5)

    state.persona.is_beloved.assert_called_once_with("discord", MALEF_DISCORD_ID)
    call_kwargs = state.emotion.process_message.call_args.kwargs
    assert call_kwargs.get("beloved") is True
    state.db.update_trust_score.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_user_insult_beloved_false_and_trust_drops():
    """Non-régression : un utilisateur normal qui insulte reçoit beloved=False
    et voit son trust baisser normalement."""
    state = make_state()
    state.persona.is_beloved = MagicMock(return_value=False)

    await _post_process(state, INSULT, f"discord:{OTHER_DISCORD_ID}", trust=0.5)

    call_kwargs = state.emotion.process_message.call_args.kwargs
    assert call_kwargs.get("beloved") is False
    state.db.update_trust_score.assert_awaited_once_with("discord", OTHER_DISCORD_ID, -0.08)


@pytest.mark.asyncio
async def test_beloved_user_positive_trust_delta_still_applied():
    """L'immunité ne bloque que le delta NÉGATIF — un delta positif venant
    d'un utilisateur aimé passe normalement."""
    state = make_state()
    state.persona.is_beloved = MagicMock(return_value=True)
    state.emotion.process_message = AsyncMock(
        return_value={"trust_delta": 0.05, "love_delta": 0.0, "user_facts": []}
    )

    await _post_process(state, "merci beaucoup", f"discord:{MALEF_DISCORD_ID}", trust=0.5)

    state.db.update_trust_score.assert_awaited_once_with("discord", MALEF_DISCORD_ID, 0.05)
