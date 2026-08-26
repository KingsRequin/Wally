# tests/test_audit2_phaseA_pannes_muettes.py
"""Phase A du second audit : quatre pannes qui ne disaient rien.

A2-6  — la rotation du token Twitch n'atteignait jamais l'IRC, et `_irc_run`
        attendait à vie une WebSocket morte : muet sur les chaînes invitées.
A2-4  — un EVOLVE pouvait VIDER un fichier persona bind-monté.
A2-10 — un refus explicite du créateur était oublié au redémarrage.
A2-11 — l'OwnerOutreachGate n'était jamais libéré après une réaction.
"""
import asyncio
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.upgrade_registry import DECLINED, DELIVERED, REQUESTED, _BLOCKING


# ────────────────────────────── A2-6 ──────────────────────────────
def _twitch():
    from bot.twitch.bot import WallyTwitch

    b = WallyTwitch.__new__(WallyTwitch)
    b.token_manager = MagicMock(bot_token="ancien", streamer_token="s")
    b.token_manager.startup_validate = AsyncMock()
    b._http = MagicMock(token="ancien")
    b._connection = MagicMock(_token="ancien")
    b._restart_eventsub = AsyncMock()
    b._closing = asyncio.Event()
    return b


@pytest.mark.asyncio
async def test_le_token_irc_suit_la_rotation():
    b = _twitch()

    async def _rotation():
        b.token_manager.bot_token = "nouveau"

    b.token_manager.startup_validate = AsyncMock(side_effect=_rotation)
    await b._refresh_tokens_and_maybe_restart_eventsub()

    assert b._http.token == "nouveau"
    assert b._connection._token == "nouveau"


@pytest.mark.asyncio
async def test_sans_rotation_on_ne_touche_a_rien():
    b = _twitch()
    await b._refresh_tokens_and_maybe_restart_eventsub()
    assert b._http.token == "ancien"
    b._restart_eventsub.assert_not_awaited()


def test_une_sonde_irc_illisible_ne_declenche_pas_de_reconnexion():
    """En cas de doute on répond « vivante » : jamais de boucle sur une sonde muette."""
    b = _twitch()
    del b._connection.is_alive          # attribut absent (versions de twitchio)
    b._connection = MagicMock(spec=[])
    assert b._irc_vivante() is True


def test_une_connexion_morte_est_detectee():
    b = _twitch()
    b._connection.is_alive = False
    assert b._irc_vivante() is False


def test_la_boucle_irc_surveille_au_lieu_d_attendre():
    from bot.twitch.bot import WallyTwitch

    src = inspect.getsource(WallyTwitch._irc_run)
    assert "_irc_vivante()" in src
    assert "asyncio.wait_for(self._closing.wait()" in src


# ────────────────────────────── A2-4 ──────────────────────────────
@pytest.mark.asyncio
async def test_une_reponse_vide_ne_vide_pas_le_fichier_persona(tmp_path):
    from bot.intelligence.persona_manager import PersonaManager, PersonaManagerError

    fichier = tmp_path / "WEEKDAYS.md"
    contenu = "## lundi\nDirective du lundi.\n" * 20
    fichier.write_text(contenu, encoding="utf-8")

    pm = PersonaManager.__new__(PersonaManager)
    pm._llm = MagicMock()
    pm._llm.complete = AsyncMock(return_value="")
    pm._dir = tmp_path
    pm._log = MagicMock()
    pm._log.change_percent_today = MagicMock(return_value=0.0)
    pm._log.count_today = MagicMock(return_value=0)

    with pytest.raises(PersonaManagerError):
        await pm.evolve("WEEKDAYS", "ajoute une nuance")

    assert fichier.read_text(encoding="utf-8") == contenu, "fichier persona vidé"


@pytest.mark.asyncio
async def test_une_reponse_tronquee_est_refusee_aussi(tmp_path):
    from bot.intelligence.persona_manager import PersonaManager, PersonaManagerError

    fichier = tmp_path / "WEEKDAYS.md"
    contenu = "## lundi\nDirective.\n" * 40
    fichier.write_text(contenu, encoding="utf-8")

    pm = PersonaManager.__new__(PersonaManager)
    pm._llm = MagicMock()
    pm._llm.complete = AsyncMock(return_value="## lundi")   # 9 caractères
    pm._dir = tmp_path
    pm._log = MagicMock()
    pm._log.change_percent_today = MagicMock(return_value=0.0)
    pm._log.count_today = MagicMock(return_value=0)

    with pytest.raises(PersonaManagerError):
        await pm.evolve("WEEKDAYS", "resserre")
    assert fichier.read_text(encoding="utf-8") == contenu


# ────────────────────────────── A2-10 ──────────────────────────────
def test_un_refus_bloque_durablement_une_redemande():
    assert DECLINED in _BLOCKING
    assert REQUESTED in _BLOCKING and DELIVERED in _BLOCKING


def test_le_motif_de_blocage_nomme_le_refus():
    from bot.intelligence.self_fix import _motif_de_blocage

    hit = MagicMock(id=3, status=DECLINED, proposal="recevoir des flux RSS",
                    decided_at="2026-07-02", created_at="2026-07-02")
    motif = _motif_de_blocage(hit)
    assert "REFUS" in motif.upper()
    assert "#3" in motif
    # Le statut anglais brut ne doit pas fuiter dans un fait français.
    assert "declined" not in motif


# ────────────────────────────── A2-11 ──────────────────────────────
async def test_le_fil_de_sollicitation_est_referme_dans_tous_les_cas():
    """Le gate owner se rouvre, que la réaction arrive ou qu'elle ne vienne pas.

    ⚠️ Ce test lisait le SOURCE de `_run_upgrade` et y cherchait un `finally:`
    après `mark_sent()`. Il figeait donc la STRUCTURE : sortir l'attente dans sa
    propre méthode — sans rien changer au comportement — le faisait tomber, et
    ce `finally` avait justement été posé parce que le gate restait fermé 40
    minutes après un refus. On guette l'état du gate, pas la mise en page.
    """
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from bot.intelligence.self_fix import SelfFix

    for issue in ("réaction reçue", "aucune réponse"):
        gate = MagicMock()
        sf = SelfFix(bridge=MagicMock(), bot=SimpleNamespace(memory=None), gate=gate)
        sf._apres_decision = AsyncMock()
        if issue == "réaction reçue":
            sf._await_reaction = AsyncMock(return_value="❌")
        else:
            sf._await_reaction = AsyncMock(side_effect=asyncio.TimeoutError)
            sf._set_status = AsyncMock()
            sf._record_outcome = AsyncMock()

        await sf._attendre_et_conclure(
            SimpleNamespace(id=1), SimpleNamespace(id=2), "un but", "un but", 7, 1.0
        )

        assert gate.clear.call_count == 1, f"gate non rouvert — {issue}"
