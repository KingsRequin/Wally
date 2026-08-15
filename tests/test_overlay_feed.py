"""OverlayFeed — diffusion vers les overlays connectés."""
import asyncio

import pytest

from bot.core.overlay_feed import OverlayFeed, bubble_duration


# ── durée d'affichage ──

def test_une_bulle_courte_reste_lisible():
    """Un viewer ne fixe pas l'overlay : entre deux coups d'œil au gameplay, une
    bulle de 2 s passait inaperçue."""
    assert bubble_duration("bien joué Azraël") >= 10.0


def test_une_bulle_longue_ne_traine_pas():
    assert bubble_duration(" ".join(["mot"] * 100)) <= 12.0


def test_la_duree_suit_la_longueur():
    """La proportionnalité ne joue qu'au-delà du plancher : en deçà de vingt mots,
    tout dure le minimum — ce qui couvre toutes les bulles réelles."""
    assert bubble_duration(" ".join(["mot"] * 40)) > bubble_duration("ok")


def test_texte_vide_borne_au_minimum():
    assert bubble_duration("") == 10.0


# ── fan-out ──

def test_plusieurs_overlays_recoivent_le_meme_evenement():
    """OBS et un navigateur de prévisualisation doivent voir la même chose —
    c'est ce que la file unique de overlay_image_queue ne permettait pas."""
    feed = OverlayFeed()
    obs, preview = feed.subscribe(), feed.subscribe()
    feed.say("salut")
    assert obs.get_nowait()["text"] == "salut"
    assert preview.get_nowait()["text"] == "salut"


def test_un_abonne_qui_ne_consomme_plus_ne_bloque_pas_les_autres():
    feed = OverlayFeed(queue_maxsize=2)
    bloque, actif = feed.subscribe(), feed.subscribe()
    for i in range(5):
        feed.say(f"message {i}")          # `bloque` sature, `actif` suit
    assert actif.qsize() == 2             # borné, mais alimenté
    assert bloque.qsize() == 2            # saturé sans lever


def test_desabonnement():
    feed = OverlayFeed()
    q = feed.subscribe()
    assert feed.subscriber_count == 1
    feed.unsubscribe(q)
    assert feed.subscriber_count == 0
    feed.say("personne n'écoute")  # ne doit pas lever


def test_un_client_qui_arrive_recupere_le_contexte_recent():
    feed = OverlayFeed(buffer_size=3)
    for i in range(5):
        feed.say(f"message {i}")
    recent = feed.recent()
    assert len(recent) == 3
    assert recent[-1]["text"] == "message 4"


# ── types d'événements ──

def test_deux_modes_de_bulle():
    feed = OverlayFeed()
    q = feed.subscribe()
    feed.say("il a encore raté")
    feed.think_aloud("je me demande s'il va tenir")
    assert q.get_nowait()["mode"] == "speech"
    assert q.get_nowait()["mode"] == "thought"


def test_une_bulle_vide_n_est_pas_diffusee():
    feed = OverlayFeed()
    q = feed.subscribe()
    feed.say("   ")
    assert q.empty()


def test_le_texte_est_normalise():
    feed = OverlayFeed()
    q = feed.subscribe()
    feed.say("  trop   d'espaces \n ici ")
    assert q.get_nowait()["text"] == "trop d'espaces ici"


def test_indicateur_de_reflexion():
    feed = OverlayFeed()
    q = feed.subscribe()
    feed.thinking(True)
    e = q.get_nowait()
    assert e["type"] == "thinking" and e["active"] is True


def test_reaction_de_l_avatar():
    feed = OverlayFeed()
    q = feed.subscribe()
    feed.react("raid")
    e = q.get_nowait()
    assert e["type"] == "react" and e["kind"] == "raid"


def test_widget_transporte_ses_parametres():
    feed = OverlayFeed()
    q = feed.subscribe()
    feed.widget("coinflip", result="heads")
    e = q.get_nowait()
    assert e["type"] == "widget" and e["kind"] == "coinflip"
    assert e["params"]["result"] == "heads"


def test_chaque_evenement_est_horodate():
    feed = OverlayFeed()
    q = feed.subscribe()
    feed.say("test")
    assert isinstance(q.get_nowait()["ts"], float)


# ── endpoint SSE ──

@pytest.mark.asyncio
async def test_le_desabonnement_a_lieu_a_la_deconnexion():
    """Un overlay fermé (OBS coupé, onglet fermé) ne doit pas laisser sa file
    derrière lui : sinon chaque reconnexion en accumule une de plus."""
    from bot.dashboard.routes.sse import sse_overlay_feed

    feed = OverlayFeed()
    state = type("S", (), {"overlay_feed": feed})()
    request = type("R", (), {"app": type("A", (), {"state": type("St", (), {"wally": state})()})()})()

    feed.say("avant connexion")
    response = await sse_overlay_feed(request)
    gen = response.body_iterator

    # Premier octet : un commentaire SSE qui débloque les en-têtes côté client
    # (GZipMiddleware les retient jusqu'au premier corps).
    assert (await gen.__anext__()).startswith(":")
    first = await gen.__anext__()          # puis le tampon amorce le client
    assert "avant connexion" in first
    assert feed.subscriber_count == 1

    await gen.aclose()                      # déconnexion
    assert feed.subscriber_count == 0


# ── amorçage d'un client qui se (re)connecte ──

def test_un_widget_perime_n_est_pas_rejoue():
    """Vu en prod : la connexion SSE saute, l'overlay se réamorce, et un dé lancé
    dix minutes plus tôt repasse — avec la file d'attente, tous s'enchaînent et
    l'overlay a l'air de tourner en boucle."""
    import time

    f = OverlayFeed()
    f.widget("dice", results=[4])
    for e in f._buffer:
        e["ts"] = time.time() - 600
    assert f.recent() == []


def test_un_widget_encore_a_l_ecran_est_rejoue():
    """C'est la raison d'être de l'amorçage : ne pas démarrer sur du vide."""
    f = OverlayFeed()
    f.widget("poll", question="?", options=["a", "b"], duration=30)
    assert len(f.recent()) == 1


def test_les_evenements_sans_duree_ne_sont_jamais_rejoues():
    """`thinking` et `react` sont instantanés : les rejouer allumerait une
    animation sans suite."""
    f = OverlayFeed()
    f.thinking(True)
    f.react("stream_event")
    assert f.recent() == []


def test_une_bulle_recente_est_rejouee():
    f = OverlayFeed()
    f.say("salut le chat")
    assert len(f.recent()) == 1


# ── la charge utile d'une image de la galerie ───────────────────────────────
#
# Trois chemins la construisaient à la main : `!image` sur Twitch, le bouton de
# test des réglages d'images, et — depuis le portage de la zone dans l'overlay
# principal — le ▶ de la mise en scène. Un champ ajouté à l'une des trois copies
# n'aurait pas existé dans les autres.

class _ConfigImage:
    display_duration = 15
    animation_in = "fadeIn"
    animation_out = "fadeOut"
    animation_duration = 1.0


_IMAGE = {"id": "abc", "username": "KingsRequin", "title": "Bière"}


def test_la_charge_utile_porte_tout_ce_que_la_page_lit():
    from bot.core.overlay_feed import payload_image_galerie

    assert payload_image_galerie(_IMAGE, _ConfigImage()) == {
        "image_url": "/api/public/gallery/abc/image",
        "title": "Bière",
        "username": "KingsRequin",
        "display_duration": 15,
        "animation_in": "fadeIn",
        "animation_out": "fadeOut",
        "animation_duration": 1.0,
    }


def test_sans_scene_l_image_vise_toutes_les_pages():
    """Un vrai `!image` s'affiche partout : la page n'écarte que ce qui porte
    un slug ÉTRANGER au sien. Poser un slug par défaut cacherait l'image sur
    toutes les scènes sauf une."""
    from bot.core.overlay_feed import payload_image_galerie

    assert "scene" not in payload_image_galerie(_IMAGE, _ConfigImage())


def test_un_essai_ne_vise_que_la_scene_qu_on_regle():
    """Sans ce champ, tester le placement de l'image pendant que le live tourne
    la projetterait devant les viewers."""
    from bot.core.overlay_feed import payload_image_galerie

    payload = payload_image_galerie(_IMAGE, _ConfigImage(), scene="fin")
    assert payload["scene"] == "fin"
