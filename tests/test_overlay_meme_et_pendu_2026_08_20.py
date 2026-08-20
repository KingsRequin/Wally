"""Deux demandes de l'owner du 2026-08-20 : le tirage de meme, et le mot du pendu.

Le tirage : `about` documente « Omets-le pour un tirage au hasard », mais le
code retombait sur `comment` — la réplique de Wally lui-même. Chaque affichage
était donc filtré par les mots de sa propre phrase, jamais tiré au sort.

Le pendu : celui qui a trouvé le mot devait l'épeler lettre par lettre.
"""
from unittest.mock import MagicMock

from bot.core.memes import MemeLibrary
from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _n(live=True, memes=None):
    feed = OverlayFeed()
    return OverlayNarrator(feed, MagicMock(), lambda: live, memes=memes), feed


# ── Le tirage de meme ─────────────────────────────────────────────────────

class _Bibliotheque(MemeLibrary):
    """Une bibliothèque qui retient l'indice reçu, sans toucher au disque."""

    def __init__(self):
        self.indices = []

    def pick(self, hint: str = ""):
        self.indices.append(hint)
        return {"name": "a.webp", "description": "un chat qui hurle"}


def test_sans_about_le_tirage_est_au_hasard():
    """La réplique de Wally n'est PAS un thème de recherche."""
    lib = _Bibliotheque()
    n, _ = _n(memes=lib)
    n.show_widget("meme", comment="Tenez, celui-là m'a toujours fait rire.")
    assert lib.indices == [""]


def test_about_reste_un_theme():
    lib = _Bibliotheque()
    n, _ = _n(memes=lib)
    n.show_widget("meme", comment="Regardez ça.", about="chat")
    assert lib.indices == ["chat"]


# ── Le mot entier au pendu ────────────────────────────────────────────────

def _events(q):
    return [e for e in (q.get_nowait() for _ in range(q.qsize()))
            if e["type"] == "widget"]


def test_le_mot_entier_gagne_la_partie():
    n, feed = _n()
    n.start_hangman("fusée")
    q = feed.subscribe()
    n._count_hangman("alice", "fusee")
    ev = _events(q)[-1]
    assert ev["params"]["won"] is True
    assert "".join(ev["params"]["mask"]) == "fusee"
    assert n._hangman is None


def test_le_mot_entier_avec_accents_et_majuscules():
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "  FuSéE ")
    assert n._hangman is None


def test_un_mot_en_deux_morceaux_est_accepte():
    """`_fold` normalise la casse et les accents, pas les espaces."""
    n, _ = _n()
    n.start_hangman("rocket  league")
    n._count_hangman("alice", "rocket league")
    assert n._hangman is None


def test_un_mot_faux_ne_coute_rien():
    """Sinon la moindre phrase du chat ferait perdre la partie."""
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "chaussette")
    assert n._hangman is not None
    assert n._hangman["missed"] == []
    assert n._hangman["found"] == set()


def test_le_mot_entier_leve_le_filet_de_sortie():
    """Gagné, le mot n'a plus rien de secret — sinon Wally ne peut plus le dire."""
    from bot.core.secret_guard import redact

    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "fusee")
    assert redact("le mot était fusée") == "le mot était fusée"
