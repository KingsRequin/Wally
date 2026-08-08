"""Le type de l'événement doit survivre jusqu'à l'overlay.

Aujourd'hui l'observateur ne reçoit qu'une phrase en français : le type est perdu
à la source. Le prompt compensait en énumérant les types possibles, ce qui sommait
le modèle d'en choisir un — et lui faisait annoncer des raids inexistants
(cf. docs/plans/2026-08-08-overlay-evenements-types.md).

Phase 1 : le type circule. Il n'est pas encore utilisé pour rédiger.
"""
import pytest

from bot.core.stream_feed import StreamFeed


def test_lobservateur_recoit_le_type():
    feed = StreamFeed("Azrael_TTV")
    vus = []
    feed.set_observer(lambda description, kind: vus.append((description, kind)))

    feed.record("raid de bob avec 30 spectateurs", kind="raid")

    assert vus == [("raid de bob avec 30 spectateurs", "raid")]


def test_un_evenement_sans_type_reste_accepte():
    """Tout ne passe pas par un producteur typé — le repli doit rester silencieux."""
    feed = StreamFeed("Azrael_TTV")
    vus = []
    feed.set_observer(lambda description, kind: vus.append((description, kind)))

    feed.record("quelque chose s'est passé")

    assert vus == [("quelque chose s'est passé", "")]


def test_le_type_ne_change_rien_au_rendu_du_contexte():
    """Le bloc passif reste une suite de phrases : le type sert à l'overlay, pas
    au prompt de contexte."""
    feed = StreamFeed("Azrael_TTV")
    feed.record("raid de bob avec 30 spectateurs", kind="raid")

    rendu = feed.render()

    assert "raid de bob avec 30 spectateurs" in rendu
    assert "kind" not in rendu


def test_un_observateur_qui_leve_ne_casse_pas_le_flux():
    feed = StreamFeed("Azrael_TTV")

    def _boom(description, kind):
        raise RuntimeError("overlay HS")

    feed.set_observer(_boom)
    feed.record("raid de bob", kind="raid")  # ne doit pas lever

    assert "raid de bob" in feed.render()


# ── les producteurs typent bien ce qu'ils émettent ──

@pytest.mark.asyncio
async def test_le_watcher_type_ses_changements():
    """Début/fin de live, jeu, titre, audience : cinq registres différents, donc
    cinq types distincts."""
    from bot.core.stream_watcher import StreamWatcher

    emis = []

    def _on_event(description, kind="", *, notify=True):
        emis.append((description, kind))

    w = StreamWatcher.__new__(StreamWatcher)
    w._on_event = _on_event
    w._streamer_name = "Azrael_TTV"

    w._emit("Azrael_TTV a lancé son live", kind="live_start")
    w._emit("Azrael_TTV a terminé son live.", kind="live_end")

    assert [k for _, k in emis] == ["live_start", "live_end"]


def test_les_evenements_sociaux_sont_types():
    """raid, sub, gift_sub, bits, follow_wave : le prompt doit pouvoir les
    distinguer sans les deviner depuis la phrase."""
    from unittest.mock import MagicMock

    from bot.twitch.events.social import _feed

    bot = MagicMock()
    feed = MagicMock()
    bot.stream_feed = feed

    _feed(bot, "raid de bob avec 30 spectateurs", kind="raid")

    _, kwargs = feed.record.call_args
    assert kwargs["kind"] == "raid"
