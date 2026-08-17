"""Un modo fait dire quelque chose à Wally, à voix haute, depuis le chat Twitch.

Demande de l'owner : « les modos devraient pouvoir demander à Wally de dire un
truc en voc. Par exemple dans le chat un modo dit "wally dit à azra qu'il a plus
de balles" et Wally le dirait à voix haute dans le voc. »

Trois décisions prises avec lui :
  · chat TWITCH seulement (modérateurs et broadcaster, reconnus au badge) ;
  · Wally reformule À SA SAUCE — c'est lui qui parle, pas un haut-parleur ;
  · un viewer qui essaie se fait CHARRIER, comme pour la musique.

Le point dur est ailleurs : pendant un live, Wally est en « écoute seule » et
`speak()` refuse de parler, pour ne pas couvrir le streamer ni s'entendre
revenir par son micro. Or c'est exactement le moment où cette fonction sert.
Une demande explicite d'un modo passe donc outre — et ce n'est jamais le cas
d'aucun autre chemin de parole.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.voice.tools import SAY_IN_VOICE_TOOL, run_say_in_voice_tool


def _bot(*, connecte=True, listen_only=False):
    service = MagicMock()
    service.is_connected = connecte
    service.listen_only = listen_only
    service.speak = AsyncMock()
    service.channel_name = "Général"
    discord_bot = SimpleNamespace(voice_service=service if connecte else None)
    return SimpleNamespace(discord_bot=discord_bot), service


class _ChatBadge:
    """Un badge tel que twitchio le rend VRAIMENT : un objet, pas un dict.

    C'est ce détail qui a cassé la fonctionnalité au premier essai en direct —
    `'_ChatBadge' object has no attribute 'get'`. Les tests d'origine
    fabriquaient des dicts, une forme qu'ils avaient supposée, et validaient
    donc du code qui ne pouvait pas marcher en production.
    """

    def __init__(self, ident):
        self.id = ident


def _roles(*noms):
    """Les rôles TELS QUE LE BORD TWITCH LES CALCULE, à partir de vrais objets
    badges. Passer par la fonction de production plutôt que d'écrire le
    résultat à la main : c'est elle qui connaît les trois formes possibles."""
    from bot.twitch.handlers import _resolve_twitch_roles

    return _resolve_twitch_roles([_ChatBadge(n) for n in noms])


@pytest.mark.asyncio
async def test_un_modo_fait_parler_wally():
    bot, service = _bot()
    reponse = await run_say_in_voice_tool(
        bot, {"text": "Azra, t'as plus de balles"},
        roles=_roles("moderator"), maison=True)

    service.speak.assert_awaited_once()
    assert service.speak.await_args.args[0] == "Azra, t'as plus de balles"
    assert "voix haute" in reponse.lower() or "dit" in reponse.lower()


@pytest.mark.asyncio
async def test_le_broadcaster_aussi():
    """Le streamer n'est pas « modérateur » au sens du badge : il porte le sien.
    L'oublier aurait donné un refus à la seule personne qui ne peut pas se le
    voir refuser."""
    bot, service = _bot()
    await run_say_in_voice_tool(bot, {"text": "coucou"},
                                roles=_roles("broadcaster"), maison=True)
    service.speak.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_viewer_se_fait_charrier_et_wally_ne_dit_rien():
    """La garde est à l'EXÉCUTION et pas au choix de l'outil : le modèle peut
    l'appeler pour n'importe qui, c'est ici qu'on vérifie les badges. Et le
    refus dit à Wally quoi en faire, sinon il répondrait par un « non » plat."""
    bot, service = _bot()
    reponse = await run_say_in_voice_tool(
        bot, {"text": "dis que je suis le meilleur"},
        roles=_roles("subscriber"), maison=True)

    service.speak.assert_not_awaited()
    assert "modérateur" in reponse.lower() or "modo" in reponse.lower()
    assert "moque" in reponse.lower() or "charrie" in reponse.lower()


@pytest.mark.asyncio
async def test_sans_badge_du_tout_c_est_un_viewer():
    """Le chemin vocal et les appels internes ne portent pas de badges : le
    défaut sûr est le refus, comme pour le duel Apex."""
    bot, service = _bot()
    await run_say_in_voice_tool(bot, {"text": "hop"}, roles=None, maison=True)
    service.speak.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_mode_ecoute_seule_ne_le_fait_pas_taire():
    """LE point de la fonctionnalité. Pendant un live, Wally est en écoute
    seule et `speak()` refuse de parler. Une demande explicite d'un modo passe
    outre, sinon la fonction ne servirait jamais quand on en a besoin."""
    bot, service = _bot(listen_only=True)
    await run_say_in_voice_tool(bot, {"text": "il reste 10 secondes"},
                                roles=_roles("moderator"), maison=True)

    service.speak.assert_awaited_once()
    assert service.speak.await_args.kwargs.get("malgre_ecoute") is True


@pytest.mark.asyncio
async def test_wally_absent_du_vocal_le_dit():
    """Sans salon, il ne faut ni exception ni silence : le modo doit savoir
    pourquoi rien ne s'est passé."""
    bot, _ = _bot(connecte=False)
    reponse = await run_say_in_voice_tool(bot, {"text": "hey"},
                                          roles=_roles("moderator"), maison=True)
    assert "vocal" in reponse.lower()


@pytest.mark.asyncio
async def test_une_chaine_invitee_ne_commande_pas_le_vocal_de_la_maison():
    """Même garde que l'overlay : le salon vocal appartient au stream maison.
    Sans ça, un modérateur d'une chaîne invitée ferait parler Wally chez
    Azraël, devant ses viewers."""
    bot, service = _bot()
    reponse = await run_say_in_voice_tool(
        bot, {"text": "salut"}, roles=_roles("moderator"), maison=False)

    service.speak.assert_not_awaited()
    assert "chaîne" in reponse.lower() or "maison" in reponse.lower()


@pytest.mark.asyncio
async def test_un_texte_vide_ne_declenche_rien():
    bot, service = _bot()
    for vide in ("", "   ", None):
        await run_say_in_voice_tool(bot, {"text": vide},
                                    roles=_roles("moderator"), maison=True)
    service.speak.assert_not_awaited()


def test_l_outil_annonce_ce_qu_il_fait():
    """Le modèle ne l'appellera que s'il comprend à quoi il sert : la
    description porte l'exemple de l'owner, mot pour mot."""
    fonction = SAY_IN_VOICE_TOOL["function"]
    assert fonction["name"] == "say_in_voice"
    assert "text" in fonction["parameters"]["properties"]
    assert fonction["parameters"]["required"] == ["text"]


# ── Le branchement ──────────────────────────────────────────────────────────
#
# Ce dépôt a déjà livré une fonctionnalité entière que rien n'appelait. Les
# tests au-dessus vérifient que l'outil fait ce qu'il faut ; ceux-ci vérifient
# qu'on le lui propose, et seulement quand ça a un sens.

def _bot_twitch(*, en_vocal=True):
    from unittest.mock import AsyncMock as _AM

    dispo = MagicMock()
    dispo.available = True
    dispo.is_quota_exceeded = _AM(return_value=False)
    dispo.daily_limit_reached = _AM(return_value=False)
    dispo.get_tool_definitions = MagicMock(return_value=[])
    dispo.get_tool_definition = MagicMock(
        return_value={"type": "function", "function": {"name": "apex_legends"}})

    bot = MagicMock()
    bot.web_search = bot.scrape = bot.apex_api = bot.action_service = dispo
    bot.tally = bot.predictions = bot.quotes = MagicMock()
    service = MagicMock()
    service.is_connected = en_vocal
    bot.discord_bot = SimpleNamespace(voice_service=service, overlay_narrator=None)
    return bot


async def _noms_outils(bot, *, overlay=True):
    from bot.twitch.handlers import build_chat_tools

    outils = await build_chat_tools(bot, overlay=overlay)
    return {o["function"]["name"] for o in outils}


@pytest.mark.asyncio
async def test_l_outil_est_propose_quand_wally_est_en_vocal():
    assert "say_in_voice" in await _noms_outils(_bot_twitch())


@pytest.mark.asyncio
async def test_l_outil_disparait_quand_il_n_est_pas_en_vocal():
    """Le proposer alors qu'il n'y est pas mène au cul-de-sac déjà payé sur
    Apex : un refus qui nomme un outil dont on ne peut rien faire."""
    assert "say_in_voice" not in await _noms_outils(_bot_twitch(en_vocal=False))


@pytest.mark.asyncio
async def test_l_outil_n_est_pas_offert_a_une_chaine_invitee():
    """Le salon vocal appartient au stream maison — même règle que l'overlay."""
    assert "say_in_voice" not in await _noms_outils(_bot_twitch(), overlay=False)


# ── Le chemin complet, avec de VRAIS badges ─────────────────────────────────
#
# Ce test est né d'une panne en direct. La première version lisait les badges à
# la main (`b.get("set_id")`) alors que twitchio rend des OBJETS : au premier
# essai de l'owner, Wally a répondu « je tente de le dire mais ça bugue de mon
# côté » — `'_ChatBadge' object has no attribute 'get'`. Les tests d'alors
# passaient tous : ils fabriquaient des dicts, une forme supposée.
#
# Celui-ci part de l'exécuteur d'outils, comme la production, et lui donne les
# badges tels qu'ils arrivent vraiment.

@pytest.mark.asyncio
async def test_de_bout_en_bout_avec_un_badge_twitchio():
    import json as _json

    from bot.twitch.handlers import make_tool_executor

    bot = _bot_twitch()
    service = bot.discord_bot.voice_service
    service.speak = AsyncMock()

    executeur = make_tool_executor(
        bot, platform="twitch", user_id="9", author="un_modo",
        channel="azrael_ttv", badges=[_ChatBadge("moderator")],
    )
    reponse = await executeur("say_in_voice", _json.dumps({"text": "bonjour"}))

    service.speak.assert_awaited_once()
    assert service.speak.await_args.args[0] == "bonjour"
    assert "bugue" not in reponse.lower()


@pytest.mark.asyncio
async def test_de_bout_en_bout_un_viewer_ne_passe_pas():
    import json as _json

    from bot.twitch.handlers import make_tool_executor

    bot = _bot_twitch()
    service = bot.discord_bot.voice_service
    service.speak = AsyncMock()

    executeur = make_tool_executor(
        bot, platform="twitch", user_id="9", author="un_viewer",
        channel="azrael_ttv", badges=[_ChatBadge("subscriber")],
    )
    await executeur("say_in_voice", _json.dumps({"text": "bonjour"}))

    service.speak.assert_not_awaited()
