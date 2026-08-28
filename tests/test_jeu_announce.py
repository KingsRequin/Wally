"""Les fins de partie s'annoncent toutes seules, sur fond violet.

Avant, un sondage se dépouillait à l'ÉCRAN et mourait là : Wally n'en parlait
que si quelqu'un pensait à demander « ça a donné quoi ? ». Le pendu pareil. Le
moment le plus collectif du jeu n'atteignait pas le chat.

Deux règles reprises de l'annonceur du duel, pour les mêmes raisons :
  · **le fait part toujours** — un appel LLM raté ne doit pas avaler le
    résultat, c'est le texte factuel qui est publié nu ;
  · **le résultat n'est jamais laissé au modèle** — il est calculé par le
    narrateur et écrit en toutes lettres ; le modèle ne fait que l'habiller.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.twitch.jeu_announce import JeuAnnouncer


def _bot(rediction="Personne n'a trouvé, c'était GIBRALTAR LUL", annonce_ok=True):
    bot = MagicMock()
    bot.llm.complete = AsyncMock(return_value=rediction)
    bot.twitch_api.send_announcement = AsyncMock(return_value=annonce_ok)
    bot.twitch_api.send_message = AsyncMock(return_value=True)
    bot.persona.get_system_prompt = MagicMock(return_value="tu es Wally")
    return bot


@pytest.mark.asyncio
async def test_la_fin_de_partie_part_en_annonce_violette():
    bot = _bot()
    await JeuAnnouncer(bot).annoncer("pendu", "Personne n'a trouvé le mot : GIBRALTAR.")

    bot.twitch_api.send_announcement.assert_awaited_once()
    assert bot.twitch_api.send_announcement.await_args.kwargs["color"] == "purple"
    bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_redaction_en_panne_publie_le_fait_NU():
    """`complete()` ne lève pas : sur panne totale il rend une excuse technique.
    La publier à la place du résultat, c'est perdre ce que le chat attend."""
    from bot.core.llm import FALLBACK_RESPONSE

    bot = _bot(rediction=FALLBACK_RESPONSE)
    fait = "Personne n'a trouvé le mot : GIBRALTAR."
    await JeuAnnouncer(bot).annoncer("pendu", fait)

    assert bot.twitch_api.send_announcement.await_args.args[0] == fait


@pytest.mark.asyncio
async def test_une_annonce_refusee_retombe_sur_un_message_ordinaire():
    """Le scope peut manquer, ou le bot ne pas être modérateur. Le résultat, lui,
    doit sortir quand même : un canal indisponible n'est pas une raison de se
    taire."""
    bot = _bot(annonce_ok=False)
    await JeuAnnouncer(bot).annoncer("sondage", "Le sondage est plié : « oui » gagne.")

    bot.twitch_api.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_fait_vide_ne_publie_rien():
    bot = _bot()
    await JeuAnnouncer(bot).annoncer("sondage", "   ")

    bot.twitch_api.send_announcement.assert_not_awaited()
    bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_l_annonce_ne_depasse_pas_le_plafond_twitch():
    bot = _bot(rediction="x" * 900)
    await JeuAnnouncer(bot).annoncer("pendu", "peu importe")

    assert len(bot.twitch_api.send_announcement.await_args.args[0]) <= 500


# ── le câblage : le narrateur déclenche, il ne publie pas ──────────────────

def _narrateur(annonces: list):
    """Un narrateur en live, dont le hook de fin de partie note ce qu'il reçoit."""
    from unittest.mock import MagicMock as _M

    from bot.core.overlay_feed import OverlayFeed
    from bot.intelligence.overlay_narrator import OverlayNarrator

    async def _hook(genre, fait):
        annonces.append((genre, fait))

    n = OverlayNarrator(OverlayFeed(), _M(), lambda: True)
    n.set_annonceur_fin(_hook)
    return n


@pytest.mark.asyncio
async def test_le_pendu_perdu_s_annonce_avec_le_mot():
    """Perdu, le mot n'est plus un secret : c'est même TOUT l'intérêt de
    l'annonce — le chat apprend enfin ce qu'il cherchait."""
    import asyncio

    annonces: list = []
    n = _narrateur(annonces)
    n.start_hangman("fusée")
    for lettre in "bcdghj":                       # 6 ratés = perdu
        n._count_hangman("alice", lettre)
    await asyncio.sleep(0)

    assert len(annonces) == 1
    genre, fait = annonces[0]
    assert genre == "pendu"
    assert "fusée" in fait.lower()


@pytest.mark.asyncio
async def test_le_pendu_gagne_nomme_qui_a_trouve():
    import asyncio

    annonces: list = []
    n = _narrateur(annonces)
    n.start_hangman("fusee")
    for lettre in "fusej":                        # le `j` ne sert qu'à finir
        n._count_hangman("bob", lettre)
    await asyncio.sleep(0)

    assert annonces and "bob" in annonces[0][1]


@pytest.mark.asyncio
async def test_le_sondage_clos_s_annonce():
    import asyncio

    annonces: list = []
    n = _narrateur(annonces)
    n.start_poll("café ou thé ?", ["café", "thé"], seconds=0)
    n._count_vote("alice", "1")
    n.close_poll()
    await asyncio.sleep(0)

    assert annonces and annonces[0][0] == "sondage"


@pytest.mark.asyncio
async def test_sans_hook_le_narrateur_tourne_comme_avant():
    """Le hook est optionnel : les tests, le mode hors ligne et toute
    instanciation qui l'ignore doivent continuer à marcher."""
    from unittest.mock import MagicMock as _M

    from bot.core.overlay_feed import OverlayFeed
    from bot.intelligence.overlay_narrator import OverlayNarrator

    n = OverlayNarrator(OverlayFeed(), _M(), lambda: True)
    n.start_hangman("fusee")
    for lettre in "bcdghj":
        n._count_hangman("alice", lettre)
    assert n._hangman is None


def test_le_hook_est_pose_LA_OU_le_narrateur_naît():
    """Le câblage doit vivre dans `discord/bot.py`, jamais dans `main.py`.

    Payé en prod le 2026-08-28 : posé depuis `main.py`, où le bot Twitch EST
    disponible, `set_annonceur_fin` n'était jamais appelé — le narrateur, lui,
    n'y est pas encore né (il se construit dans le `setup_hook` de Discord, qui
    tourne après le `gather`). Les tests étaient tous verts, la ligne de
    journal n'apparaissait dans aucun log, et la fonctionnalité était morte.

    L'inverse du branchement `stream_feed.set_observer` : celui-là marche parce
    qu'il résout le narrateur À CHAQUE APPEL. Ici c'est le bot Twitch qui doit
    être résolu tard, pas le narrateur.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parents[1] / "bot"
    assert "set_annonceur_fin" in (racine / "discord" / "bot.py").read_text(encoding="utf-8")
    assert "set_annonceur_fin" not in (racine / "main.py").read_text(encoding="utf-8")
