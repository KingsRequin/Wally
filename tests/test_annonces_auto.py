"""Les rappels du live, repris de PhantomBot.

Six sujets (TikTok, YouTube, Discord, memes, bonjour, code créateur) publiés en
rotation pendant le stream. Ce qui se teste ici, ce sont les trois écarts avec
l'ancien bot : des variantes plutôt qu'une phrase figée, une rotation qui
n'oublie aucun sujet, et le tour sauté quand le chat est désert.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.stream_feed import StreamFeed
from bot.twitch.annonces_auto import AnnoncesAuto

ANNONCES = {
    "tiktok": ["tik 1", "tik 2"],
    "discord": ["dis 1", "dis 2"],
    "bonjour": ["jour 1", "jour 2"],
}


def _bot(annonces=None, *, live=True, chat=True):
    bot = MagicMock()
    bot.persona.annonces_auto = dict(ANNONCES if annonces is None else annonces)
    bot._stream_info = {"live": live}
    bot.stream_feed = MagicMock()
    bot.stream_feed.a_du_chat_frais.return_value = chat
    bot.twitch_api.send_automatic = AsyncMock(return_value=True)
    return bot


def _annonceur(bot, cadence_s=1800.0):
    return AnnoncesAuto(bot, cadence_s=cadence_s)


def test_les_trois_sujets_passent_avant_quun_seul_revienne():
    """La rotation de PhantomBot, gardée : c'est ce qui empêche trois liens
    TikTok d'affilée alors que le Discord n'a pas été cité de la soirée."""
    a = _annonceur(_bot())
    sujets = [a.choisir()[0] for _ in range(3)]
    assert sorted(sujets) == ["bonjour", "discord", "tiktok"]


def test_une_variante_ne_ressort_pas_avant_que_lautre_soit_passee():
    """Le sac est PAR sujet. Avec un tirage au hasard, « tik 1 » pouvait sortir
    deux passages de suite — soit exactement la répétition qu'on corrige."""
    a = _annonceur(_bot())
    vues = []
    for _ in range(6):  # deux tours complets des trois sujets
        sujet, phrase = a.choisir()
        if sujet == "tiktok":
            vues.append(phrase)
    assert sorted(vues) == ["tik 1", "tik 2"]


def test_un_fichier_vide_eteint_la_fonction():
    """Vider ANNONCES.md est la façon documentée de couper les rappels : ça ne
    doit ni lever, ni publier une chaîne vide."""
    a = _annonceur(_bot({}))
    assert a.choisir() is None


def test_une_section_effacee_entre_deux_tirages_ne_sert_plus():
    """Le sac garde les clés qu'il a tirées au chargement. L'owner qui vide une
    section depuis le dashboard ne doit pas voir passer le sujet supprimé."""
    bot = _bot()
    a = _annonceur(bot)
    a.choisir()                       # amorce le sac avec les trois sujets
    bot.persona.annonces_auto = {"discord": ["dis 1"]}
    for _ in range(3):
        choix = a.choisir()
        assert choix is None or choix[0] == "discord"


async def test_hors_live_rien_ne_part():
    """PhantomBot aussi se taisait hors live. Le rappel s'adresse aux viewers
    d'un stream en cours, pas au vide d'une chaîne éteinte."""
    bot = _bot(live=False)
    a = _annonceur(bot, cadence_s=0.0)
    await a.tour()
    bot.twitch_api.send_automatic.assert_not_called()


async def test_le_chat_desert_saute_son_tour():
    bot = _bot(chat=False)
    a = _annonceur(bot, cadence_s=0.0)
    await a.tour()
    bot.twitch_api.send_automatic.assert_not_called()


async def test_le_chat_desert_naccumule_pas_de_retard():
    """L'horloge avance même quand le tour est sauté : sinon le premier mot
    prononcé après une heure de silence déclencherait un rappel dans la
    seconde, puis un autre au mot suivant."""
    bot = _bot(chat=False)
    a = _annonceur(bot, cadence_s=1800.0)
    a._dernier = time.monotonic() - 3600
    await a.tour()
    bot.stream_feed.a_du_chat_frais.return_value = True
    await a.tour()   # juste après : la cadence n'est pas écoulée
    bot.twitch_api.send_automatic.assert_not_called()


async def test_avant_la_cadence_rien_ne_part():
    bot = _bot()
    a = _annonceur(bot, cadence_s=1800.0)
    await a.tour()
    bot.twitch_api.send_automatic.assert_not_called()


async def test_la_cadence_echue_publie_une_phrase_du_fichier():
    bot = _bot()
    a = _annonceur(bot, cadence_s=1800.0)
    a._dernier = time.monotonic() - 1801
    await a.tour()
    envoye = bot.twitch_api.send_automatic.await_args.args[0]
    assert envoye in [p for phrases in ANNONCES.values() for p in phrases]


async def test_la_publication_passe_par_send_automatic():
    """Et pas par `send_message` : un rappel que personne n'a demandé sort en
    ANNONCE colorée, avec le repli en message ordinaire que porte déjà
    `send_automatic` quand le scope ou le badge de modérateur manque."""
    bot = _bot()
    a = _annonceur(bot, cadence_s=0.0)
    await a.tour()
    bot.twitch_api.send_automatic.assert_awaited_once()
    bot.twitch_api.send_message.assert_not_called()


async def test_un_envoi_qui_leve_ne_casse_pas_le_tour():
    bot = _bot()
    bot.twitch_api.send_automatic = AsyncMock(side_effect=RuntimeError("helix"))
    a = _annonceur(bot, cadence_s=0.0)
    await a.tour()   # ne lève pas


async def test_sans_flux_de_stream_on_publie_quand_meme():
    """Le flux est une perception de confort, pas une autorisation. Le laisser
    éteindre la fonction par son absence serait une panne silencieuse — la
    signature de défaut que les garde-fous du projet visent."""
    bot = _bot()
    bot.stream_feed = None
    a = _annonceur(bot, cadence_s=0.0)
    await a.tour()
    bot.twitch_api.send_automatic.assert_awaited_once()


async def test_lheure_ne_court_pas_hors_live():
    """Un bot resté allumé une nuit entière ne doit pas lâcher son rappel dans
    la seconde qui suit le lancement du live, avant que quiconque soit arrivé."""
    bot = _bot(live=False)
    a = _annonceur(bot, cadence_s=1800.0)
    a._dernier = time.monotonic() - 36000
    await a.tour()            # hors live : l'horloge est remise à maintenant
    bot._stream_info = {"live": True}
    await a.tour()
    bot.twitch_api.send_automatic.assert_not_called()


# ── La sonde d'activité du chat ──────────────────────────────────────────

def test_le_chat_frais_est_vu():
    feed = StreamFeed(streamer_name="azrael")
    feed.record_chat("viewer", "salut")
    assert feed.a_du_chat_frais(60.0) is True


def test_un_chat_muet_est_vu_comme_desert():
    feed = StreamFeed(streamer_name="azrael")
    assert feed.a_du_chat_frais(1800.0) is False


def test_une_ligne_plus_vieille_que_la_fenetre_ne_compte_pas():
    """La sonde lit le tampon BRUT, pas `_fresh_chat` : le TTL de 15 min borne
    ce que Wally LIT dans son contexte, pas ce qu'on peut savoir de l'activité
    du chat. Une fenêtre de 30 min doit donc pouvoir répondre sur 20 min."""
    feed = StreamFeed(streamer_name="azrael")
    feed.record_chat("viewer", "salut")
    feed._chat[-1] = (time.monotonic() - 1200, "viewer", "salut")
    assert feed.a_du_chat_frais(1800.0) is True
    assert feed.a_du_chat_frais(600.0) is False


# ── Le fichier de production ─────────────────────────────────────────────

@pytest.fixture
def annonces_de_prod():
    from bot.intelligence.persona import PersonaService

    return PersonaService("bot/persona").annonces_auto


def test_les_six_sujets_de_phantombot_sont_tous_repris(annonces_de_prod):
    assert set(annonces_de_prod) == {
        "tiktok", "youtube", "discord", "meme", "bonjour", "code createur",
    }


def test_chaque_sujet_a_plusieurs_variantes(annonces_de_prod):
    """Une section à une seule phrase, c'est PhantomBot : le même texte au mot
    près à chaque passage."""
    maigres = {s: len(v) for s, v in annonces_de_prod.items() if len(v) < 2}
    assert not maigres


def test_aucune_variante_ne_depasse_une_annonce_twitch(annonces_de_prod):
    """500 caractères : au-delà, Twitch tronque, et c'est l'URL en fin de
    phrase qui part en premier."""
    trop_longues = [p for v in annonces_de_prod.values() for p in v if len(p) > 500]
    assert not trop_longues


def test_les_liens_sont_entiers(annonces_de_prod):
    """Une URL abîmée ne renvoie aucune erreur : elle ne mène nulle part, et
    personne ne le signale. C'est la raison pour laquelle ces phrases sont
    écrites à la main plutôt que rédigées par un modèle."""
    import re

    for sujet, variantes in annonces_de_prod.items():
        for phrase in variantes:
            for url in re.findall(r"https?://\S*", phrase):
                assert url.startswith("https://"), (sujet, url)
                assert "…" not in url and ".." not in url, (sujet, url)
