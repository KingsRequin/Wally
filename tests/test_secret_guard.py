"""Le mot du pendu ne doit pas pouvoir sortir, même si le modèle le lâche.

Le mot est dans le contexte de Wally — sans lui, pas de second indice ni d'état
de partie. La consigne de ne pas l'écrire voyage collée au mot, mais une consigne
se contourne : ceci est la ceinture mécanique, appliquée aux points de sortie.

Elle ne retire rien à ce qu'il SAIT ; elle l'empêche seulement de le publier.
"""
import pytest

from bot.core.secret_guard import (
    clear_secrets,
    guard_secret,
    redact,
    release_secret,
)


@pytest.fixture(autouse=True)
def _clean():
    clear_secrets()
    yield
    clear_secrets()


def test_sans_secret_le_texte_ressort_intact():
    assert redact("bonjour tout le monde") == "bonjour tout le monde"


def test_le_mot_protege_est_masque():
    guard_secret("ordinateur")
    assert "ordinateur" not in redact("le mot c'est ordinateur voilà").lower()


def test_la_casse_ne_protege_pas():
    guard_secret("ordinateur")
    assert "ORDINATEUR" not in redact("c'est ORDINATEUR")


def test_les_accents_ne_protegent_pas():
    """Le secret est stocké replié : sans variantes, « flèche » passait."""
    guard_secret("flèche")
    assert "flèche" not in redact("la réponse est flèche").lower()


def test_epeler_revient_a_dire():
    guard_secret("chat")
    assert "c h a t" not in redact("ça commence par c h a t").lower()
    assert "c-h-a-t" not in redact("c'est c-h-a-t").lower()


def test_le_reste_de_la_phrase_survit():
    guard_secret("ordinateur")
    out = redact("indice : c'est un ordinateur, tu chauffes")
    assert out.startswith("indice : c'est un ")
    assert out.endswith(", tu chauffes")


def test_une_partie_finie_libere_le_mot():
    guard_secret("ordinateur")
    release_secret("ordinateur")
    assert redact("c'était ordinateur") == "c'était ordinateur"


def test_un_mot_trop_court_nest_pas_protege():
    """Masquer « et » ou « le » abîmerait toutes les phrases sans rien protéger."""
    guard_secret("et")
    assert redact("et voilà, et donc") == "et voilà, et donc"


def test_plusieurs_secrets_coexistent():
    guard_secret("ordinateur")
    guard_secret("clavier")
    out = redact("ordinateur et clavier")
    assert "ordinateur" not in out and "clavier" not in out


def test_un_texte_vide_ne_casse_rien():
    guard_secret("ordinateur")
    assert redact("") == ""
    assert redact(None) is None


# ── bout en bout : le pendu arme et désarme le filet ──

def _narrator():
    from unittest.mock import MagicMock

    from bot.intelligence.overlay_narrator import OverlayNarrator

    n = OverlayNarrator.__new__(OverlayNarrator)
    n._feed = MagicMock()
    n._live = lambda: True
    n._hangman = None
    return n


def test_ouvrir_un_pendu_protege_le_mot():
    n = _narrator()
    n.start_hangman("ordinateur", hint="ça chauffe")

    assert "ordinateur" not in redact("le mot est ordinateur").lower()


def test_gagner_le_pendu_libere_le_mot():
    """Une fois la partie finie, le mot n'a plus à être caché — il est même
    affiché à l'écran."""
    n = _narrator()
    n.start_hangman("chat")
    for lettre in "chat":
        n._count_hangman("bob", lettre)

    assert n._hangman is None
    assert redact("c'était chat") == "c'était chat"


def test_abandonner_le_pendu_libere_le_mot():
    n = _narrator()
    n.start_hangman("ordinateur")
    n.cancel("pendu")

    assert redact("c'était ordinateur") == "c'était ordinateur"


@pytest.mark.asyncio
async def test_le_mot_ne_part_pas_dans_le_chat_twitch():
    """Le point de sortie qui compte le plus : le chat où se joue la partie."""
    from unittest.mock import MagicMock

    import httpx

    from bot.twitch.api import TwitchAPI

    envoye = {}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, timeout=None):
            envoye["message"] = json["message"]
            return MagicMock(status_code=200, raise_for_status=MagicMock())

    api = TwitchAPI.__new__(TwitchAPI)
    api._tm = MagicMock(); api._tm.bot_token = "t"
    api._client_id = "c"; api._bot_id = "b"; api._broadcaster_id = "42"

    guard_secret("ordinateur")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "AsyncClient", lambda **kw: _Client())
        await api.send_message("le mot était ordinateur")

    assert "ordinateur" not in envoye["message"].lower()


def test_le_mot_ne_part_pas_dans_une_bulle_doverlay():
    """`say()` est le point de passage unique de TOUTES les bulles."""
    from unittest.mock import MagicMock

    from bot.core.overlay_feed import OverlayFeed

    feed = OverlayFeed.__new__(OverlayFeed)
    feed.publish = MagicMock()

    guard_secret("ordinateur")
    feed.say("bien joué, c'était ordinateur")

    publie = feed.publish.call_args.args[0]["text"]
    assert "ordinateur" not in publie.lower()
    assert "bien joué" in publie      # le reste de la bulle survit
