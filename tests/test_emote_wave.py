"""Vagues d'emotes dans le chat.

Le signal n'est pas le nombre de messages mais le nombre de PERSONNES : dix
« KEKW » d'un seul viewer, c'est un habitué qui s'amuse ; quatre viewers
différents, c'est le chat qui réagit ensemble.
"""
import time

from bot.core.emote_wave import EmoteWaveDetector, _looks_like_emote


def _d():
    return EmoteWaveDetector()


# ── ce qui ressemble à un emote ──

def test_les_emotes_sont_reconnues():
    assert _looks_like_emote("KEKW")
    assert _looks_like_emote("PogChamp")
    assert _looks_like_emote("azrael74HYPE")


def test_les_mots_ordinaires_ne_le_sont_pas():
    """Sinon la moindre phrase déclencherait une vague."""
    for mot in ("bonjour", "ptdr", "Salut", "ok", "a"):
        assert not _looks_like_emote(mot)


def test_une_emote_verifiee_est_reconnue_quelle_qu_en_soit_la_forme():
    """La règle de forme exige une majuscule ailleurs qu'en tête : elle rejette
    72 des 304 globales, dont `Kappa` — 128 emplois en sept jours, l'emote la
    plus utilisée du chat. Le registre vérifié par l'API tranche avant elle."""
    from bot.core.twitch_emotes import active_emote_registry

    active_emote_registry().set_verified(["Kappa", "Kreygasm", ":D"])
    for nom in ("Kappa", "Kreygasm", ":D"):
        assert _looks_like_emote(nom)


def test_une_vague_de_kappa_atteint_enfin_lecran():
    from bot.core.twitch_emotes import active_emote_registry

    active_emote_registry().set_verified(["Kappa"])
    d, now = _d(), time.time()
    for qui in ("a", "b", "c"):
        assert d.feed(qui, "Kappa", now=now) is None
    assert d.feed("d", "Kappa", now=now) == "Kappa"


def test_le_registre_nouvre_pas_la_porte_aux_mots_ordinaires():
    """Il ne contient que des emotes réelles : un mot français n'y entre pas,
    et la règle de forme reste seule juge pour tout le reste."""
    from bot.core.twitch_emotes import active_emote_registry

    active_emote_registry().set_verified(["Kappa"])
    for mot in ("bonjour", "Salut", "ptdr"):
        assert not _looks_like_emote(mot)


# ── détection ──

def test_quatre_personnes_font_une_vague():
    d = _d()
    now = time.time()
    assert d.feed("a", "KEKW", now=now) is None
    assert d.feed("b", "KEKW", now=now) is None
    assert d.feed("c", "KEKW", now=now) is None
    assert d.feed("d", "KEKW", now=now) == "KEKW"


def test_une_seule_personne_qui_spamme_ne_compte_pas():
    """C'est un habitué qui s'amuse, pas le chat qui réagit."""
    d = _d()
    now = time.time()
    for _ in range(10):
        assert d.feed("a", "KEKW", now=now) is None


def test_une_vague_etalee_dans_le_temps_ne_compte_pas():
    d = _d()
    now = time.time()
    for i, who in enumerate("abcd"):
        assert d.feed(who, "KEKW", now=now + i * 20) is None


def test_une_vague_n_est_signalee_qu_une_fois():
    """L'emote reste souvent en fond une minute après."""
    d = _d()
    now = time.time()
    for who in "abcd":
        d.feed(who, "KEKW", now=now)
    for who in "efgh":
        assert d.feed(who, "KEKW", now=now + 2) is None


def test_deux_emotes_differentes_sont_suivies_separement():
    d = _d()
    now = time.time()
    for who in "abc":
        d.feed(who, "KEKW", now=now)
    for who in "abc":
        d.feed(who, "PogChamp", now=now)
    assert d.feed("d", "PogChamp", now=now) == "PogChamp"


def test_un_emote_noye_dans_une_phrase_compte():
    d = _d()
    now = time.time()
    for who in "abc":
        d.feed(who, f"mdr KEKW trop fort", now=now)
    assert d.feed("d", "ah KEKW", now=now) == "KEKW"


def test_un_auteur_vide_est_ignore():
    assert _d().feed("", "KEKW") is None
