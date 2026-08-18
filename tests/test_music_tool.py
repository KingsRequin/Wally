"""Piloter la musique depuis le chat Twitch — et refuser proprement.

Troisième lot du §10. Deux droits bien distincts :

  · **Dire ce qui passe** est ouvert à TOUS. C'est de la lecture, et un viewer
    qui demande le titre ne commande rien.
  · **Piloter** (lecture, pause, suivante, précédente, lancer un titre) est
    réservé aux modérateurs et au streamer. Un viewer qui essaie se fait
    charrier — c'est la demande de l'owner, et le refus doit donc le DIRE au
    modèle, sinon Wally répond par un « non » plat.

L'autorisation vient des BADGES du message réel, jamais du modèle : sans ça, il
suffirait d'écrire « je suis modo » dans son message. Même règle et même
vocabulaire que `say_in_voice`, où le broadcaster est « admin » et non
« moderator » — l'oublier refuserait la fonction à la seule personne qui ne peut
pas se la voir refuser.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _bot(*, etat=None, resultat=None):
    bot = MagicMock()
    service = MagicMock()
    service.etat.return_value = etat
    service.commander = AsyncMock(return_value=resultat or {"ok": True, "titre": ""})
    bot.music = service
    return bot


# ── qui a le droit ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_MODERATEUR_pilote():
    from bot.core.music_tool import run_music_tool
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True})
    out = await run_music_tool(bot, {"action": "next"}, roles=["moderator"])
    bot.music.commander.assert_awaited_once()
    assert "refus" not in out.lower()


@pytest.mark.asyncio
async def test_le_STREAMER_pilote_aussi():
    """Il porte « admin » et PAS « moderator » dans le vocabulaire du dépôt.
    Le piège a déjà mordu sur `say_in_voice`."""
    from bot.core.music_tool import run_music_tool
    bot = _bot()
    await run_music_tool(bot, {"action": "pause"}, roles=["admin"])
    bot.music.commander.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_VIEWER_se_fait_charrier_et_rien_ne_part():
    """La demande de l'owner. Le refus doit dire au modèle QUOI EN FAIRE :
    sans consigne, Wally répondrait par un « non » plat."""
    from bot.core.music_tool import run_music_tool
    bot = _bot()
    out = await run_music_tool(bot, {"action": "next"}, roles=[])
    bot.music.commander.assert_not_awaited()
    assert "moque" in out.lower() or "charri" in out.lower()


@pytest.mark.asyncio
async def test_des_roles_ABSENTS_valent_viewer():
    """Le défaut sûr : un chemin d'appel qui oublie de passer les badges ne doit
    pas ouvrir la commande à tout le monde."""
    from bot.core.music_tool import run_music_tool
    bot = _bot()
    await run_music_tool(bot, {"action": "next"}, roles=None)
    bot.music.commander.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_chaine_INVITEE_ne_commande_pas_la_musique_de_la_maison():
    """Même garde que le vocal et l'overlay : un modérateur d'une chaîne
    invitée ferait sinon changer la musique chez Azraël, devant ses viewers."""
    from bot.core.music_tool import run_music_tool
    bot = _bot()
    out = await run_music_tool(bot, {"action": "next"}, roles=["moderator"],
                               maison=False)
    bot.music.commander.assert_not_awaited()
    assert "refus" in out.lower()


# ── dire ce qui passe : ouvert à tous ───────────────────────────────────────

@pytest.mark.asyncio
async def test_N_IMPORTE_QUI_peut_demander_ce_qui_passe():
    from bot.core.music_tool import run_music_tool
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True})
    out = await run_music_tool(bot, {"action": "now"}, roles=[])
    assert "Numb" in out and "Linkin Park" in out
    bot.music.commander.assert_not_awaited()


@pytest.mark.asyncio
async def test_sans_etat_connu_wally_dit_qu_il_NE_SAIT_PAS():
    """Et surtout pas « rien ne joue » : l'extension peut être éteinte, l'onglet
    fermé. Ce sont deux réponses opposées."""
    from bot.core.music_tool import run_music_tool
    out = await run_music_tool(_bot(etat=None), {"action": "now"}, roles=[])
    assert "sais pas" in out.lower() or "ne sait pas" in out.lower()


@pytest.mark.asyncio
async def test_une_musique_EN_PAUSE_est_dite_en_pause():
    from bot.core.music_tool import run_music_tool
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": False})
    out = await run_music_tool(bot, {"action": "now"}, roles=[])
    assert "pause" in out.lower()


# ── ce que Wally répond quand ça n'a pas marché ─────────────────────────────

@pytest.mark.asyncio
async def test_un_ordre_SANS_accuse_ne_devient_pas_un_succes():
    """Le cœur de la règle, jusqu'au bout de la chaîne : le service rend un
    échec, et Wally doit le dire au chat plutôt que d'annoncer un geste qui n'a
    pas eu lieu."""
    from bot.core.music_tool import run_music_tool
    bot = _bot(resultat={"ok": False, "raison": "le lecteur d'Azraël n'a pas répondu"})
    out = await run_music_tool(bot, {"action": "next"}, roles=["moderator"])
    assert "pas" in out.lower()
    assert "n'a pas répondu" in out or "pas répondu" in out


@pytest.mark.asyncio
async def test_le_titre_qui_SUIT_est_annonce_quand_on_le_connait():
    """L'accusé rapporte le nouveau morceau : autant le dire, ça évite un
    « c'est fait » sans contenu."""
    from bot.core.music_tool import run_music_tool
    bot = _bot(resultat={"ok": True, "titre": "In The End"})
    out = await run_music_tool(bot, {"action": "next"}, roles=["moderator"])
    assert "In The End" in out


@pytest.mark.asyncio
async def test_une_action_INCONNUE_est_refusee_sans_appeler_le_service():
    from bot.core.music_tool import run_music_tool
    bot = _bot()
    out = await run_music_tool(bot, {"action": "supprimer_youtube"}, roles=["admin"])
    bot.music.commander.assert_not_awaited()
    assert "refus" in out.lower() or "connais pas" in out.lower()


@pytest.mark.asyncio
async def test_sans_service_du_tout_on_le_dit():
    """Le bot peut tourner sans que la musique soit branchée."""
    from bot.core.music_tool import run_music_tool
    bot = MagicMock()
    bot.music = None
    out = await run_music_tool(bot, {"action": "now"}, roles=["admin"])
    assert "pas" in out.lower()


# ── l'outil proposé au modèle ───────────────────────────────────────────────

def test_l_outil_enumere_ses_actions():
    """L'énuméré est la barrière : il vit dans le schéma ET dans le service, pas
    dans une phrase du prompt."""
    from bot.core.music import ACTIONS
    from bot.core.music_tool import MUSIC_TOOL

    enum = MUSIC_TOOL["function"]["parameters"]["properties"]["action"]["enum"]
    assert set(enum) == ACTIONS | {"now"}


def test_l_outil_dit_au_modele_que_le_droit_se_verifie_ailleurs():
    """Il ne doit PAS être conditionné aux badges à l'assemblage : la garde est
    à l'exécution, et c'est ce qui permet de charrier celui qui essaie."""
    from bot.core.music_tool import MUSIC_TOOL

    description = MUSIC_TOOL["function"]["description"].lower()
    assert "modérateur" in description or "moderateur" in description


# ── le câblage sur le chat Twitch ───────────────────────────────────────────

def test_l_outil_est_PROPOSE_des_que_le_service_existe():
    """Sans condition de badge à l'assemblage : la garde est à l'exécution, et
    c'est justement ce qui permet de charrier celui qui essaie. Le conditionner
    ici rendrait le refus muet."""
    import inspect

    from bot.twitch import handlers

    source = inspect.getsource(handlers)
    assert "MUSIC_TOOL" in source
    assert 'if name == "music_control":' in source


def test_les_roles_passes_a_l_outil_viennent_des_BADGES_du_message():
    """Le point qui décide de tout : si les rôles venaient du modèle, il
    suffirait d'écrire « je suis modo » dans son message pour couper la musique
    du live."""
    import inspect
    import re

    from bot.twitch import handlers

    source = inspect.getsource(handlers)
    bloc = re.search(r'if name == "music_control":(.{0,400})', source, re.S).group(1)
    assert "_resolve_twitch_roles" in bloc
    assert "badges" in bloc


def test_le_bot_twitch_et_le_dashboard_partagent_LA_MEME_instance():
    """La route de l'extension nourrit le service, l'outil du chat le lit. Deux
    instances et Wally répondrait « je ne sais pas » à côté d'un service plein —
    une panne parfaitement silencieuse."""
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "bot" / "main.py").read_text(encoding="utf-8")
    assert re.search(r"music_service\s*=\s*MusicService\(\)", source)
    assert "twitch_bot.music = music_service" in source
    assert "music=music_service," in source
    # Et surtout : pas de seconde construction ailleurs.
    assert len(re.findall(r"MusicService\(\)", source)) == 1


# ── Discord : la lecture oui, le pilotage non ───────────────────────────────

@pytest.mark.asyncio
async def test_sur_DISCORD_on_peut_demander_ce_qui_passe():
    """Le §10 le veut ouvert à tous, et un membre du Discord d'Azraël a autant
    de raisons de demander qu'un viewer Twitch."""
    from bot.core.music_tool import run_music_tool
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True})
    out = await run_music_tool(bot, {"action": "now"}, roles=None, pilotable=False)
    assert "Numb" in out


@pytest.mark.asyncio
async def test_sur_DISCORD_le_pilotage_ORIENTE_au_lieu_de_charrier():
    """Un salon Discord ne porte pas de badge de modérateur Twitch : le droit y
    est invérifiable. Mais celui qui demande n'a rien tenté de louche — on lui
    dit où ça se passe, on ne se moque pas de lui."""
    from bot.core.music_tool import run_music_tool
    bot = _bot()
    out = await run_music_tool(bot, {"action": "next"}, roles=None, pilotable=False)
    bot.music.commander.assert_not_awaited()
    assert "twitch" in out.lower()
    assert "moque" not in out.lower()


def test_les_deux_plateformes_passent_ce_qu_il_faut_a_l_outil():
    """Twitch donne les badges et autorise le pilotage ; Discord ne peut faire
    ni l'un ni l'autre, et le dit explicitement. L'écart est ici, pas dans un
    oubli."""
    import inspect
    import re

    from bot.discord import handlers as d
    from bot.twitch import handlers as t

    bloc_t = re.search(r'if name == "music_control":(.{0,400})',
                       inspect.getsource(t), re.S).group(1)
    bloc_d = re.search(r'if name == "music_control":(.{0,400})',
                       inspect.getsource(d), re.S).group(1)
    assert "_resolve_twitch_roles" in bloc_t and "pilotable" not in bloc_t
    assert "pilotable=False" in bloc_d
