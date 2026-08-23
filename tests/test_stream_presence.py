"""La vanne du tampon vocal : quand elle s'ouvre, quand elle se ferme.

Pourquoi ces tests n'existaient pas. `PresenceDeStream` était deux fonctions
IMBRIQUÉES dans le `main()` de 1071 lignes de `bot/main.py`. Rien ne pouvait les
atteindre — ni un test, ni un lecteur. Ce n'était pas de la négligence, c'était
la forme du fichier.

Ce qui se joue ici. `VoiceTranscriptFeed.record()` refuse tout ce qui n'est pas
diffusé au live : la confidentialité se joue à l'ÉCRITURE, et ce refus-là est
déjà couvert (`test_voice_transcript_alimentation.py`). Mais le geste d'en face
— `open_broadcast()` / `close_broadcast()` — décide si une conversation vocale
PRIVÉE peut ressortir dans le contexte écrit de Wally, sur Twitch. Il n'était
couvert nulle part.

Les tests d'ouverture et de fermeture sont donc les premiers du fichier, et pas
les derniers.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.voice.stream_presence import PresenceDeStream

OFF: dict = {"live": False}
ON: dict = {"live": True, "category": "Apex Legends"}


def _presence(*, connecte=False, listen_only=False, optout=False,
              salon=MagicMock(id=4242), sans_service=False):
    """Une présence gréée de doubles, plus ses pièces pour les assertions."""
    vs = MagicMock()
    vs.is_connected = connecte
    vs.listen_only = listen_only
    vs.listen_optout = optout
    vs.join = AsyncMock()
    vs.leave = AsyncMock()

    bot = MagicMock()
    bot.voice_service = None if sans_service else vs

    transcript = MagicMock()
    config = MagicMock()
    config.bot.stream_voice_channel_id = 1

    p = PresenceDeStream(discord_bot=bot, db=MagicMock(),
                         config=config, voice_transcript=transcript)
    # `resolve_voice_channel` est importée DANS la méthode : on remplace le
    # résolveur plutôt que de patcher un chemin d'import, ce qui casserait au
    # premier déplacement du module.
    p._salon = AsyncMock(return_value=salon)
    return p, vs, transcript


# ── la vanne ────────────────────────────────────────────────────────────────

async def test_le_debut_du_live_OUVRE_la_captation_sur_le_bon_salon():
    p, _, tr = _presence(salon=MagicMock(id=99))
    await p.sur_transition(OFF, ON)
    tr.open_broadcast.assert_called_once_with(99)


async def test_la_fin_du_live_FERME_la_captation():
    """Sans ça, le vocal redevenu privé continuerait d'alimenter le contexte
    écrit — et ressortirait dans le chat Twitch."""
    p, _, tr = _presence(connecte=True, listen_only=True)
    await p.sur_transition(ON, OFF)
    tr.close_broadcast.assert_called_once()
    tr.open_broadcast.assert_not_called()


async def test_la_captation_s_ouvre_MEME_si_wally_est_deja_en_vocal():
    """Le cas le plus fréquent : Wally est dans le salon avant que le live
    démarre. Ouvrir après le retour anticipé la laisserait fermée tout le live."""
    p, vs, tr = _presence(connecte=True)
    await p.sur_transition(OFF, ON)
    tr.open_broadcast.assert_called_once_with(4242)
    vs.join.assert_not_awaited()      # on ne le déplace pas


async def test_sans_salon_joignable_la_captation_s_ouvre_sur_RIEN():
    """`None` et pas un id au hasard : le tampon doit refuser, pas capter le
    premier salon venu."""
    p, vs, tr = _presence(salon=None)
    await p.sur_transition(OFF, ON)
    tr.open_broadcast.assert_called_once_with(None)
    vs.join.assert_not_awaited()


async def test_un_live_qui_CONTINUE_ne_touche_a_rien():
    """Deux relevés « live » de suite ne sont pas une transition."""
    p, vs, tr = _presence()
    await p.sur_transition(ON, ON)
    tr.open_broadcast.assert_not_called()
    tr.close_broadcast.assert_not_called()
    vs.join.assert_not_awaited()


# ── la présence vocale ──────────────────────────────────────────────────────

async def test_le_debut_du_live_fait_rejoindre_en_ECOUTE_SEULE():
    p, vs, _ = _presence()
    await p.sur_transition(OFF, ON)
    vs.join.assert_awaited_once()
    assert vs.join.await_args.kwargs["listen_only"] is True
    assert vs.join.await_args.kwargs["only_if_free"] is True


async def test_la_fin_du_live_ne_coupe_PAS_une_conversation_en_cours():
    """Il ne part que s'il était là POUR le stream. `listen_only=False` veut
    dire qu'on lui parle : le mettre dehors couperait des gens."""
    p, vs, _ = _presence(connecte=True, listen_only=False)
    await p.sur_transition(ON, OFF)
    vs.leave.assert_not_awaited()


async def test_sans_service_vocal_il_ne_se_passe_rien():
    p, _, tr = _presence(sans_service=True)
    await p.sur_transition(OFF, ON)
    tr.open_broadcast.assert_not_called()


async def test_une_panne_de_join_ne_remonte_JAMAIS():
    """Appelé depuis le poller du live : une exception y arrêterait la sonde."""
    p, vs, _ = _presence()
    vs.join = AsyncMock(side_effect=RuntimeError("Discord fâché"))
    await p.sur_transition(OFF, ON)   # ne doit pas lever


# ── le filet, un tour à la fois ─────────────────────────────────────────────

def _avec_watcher(p, live: bool):
    p.brancher_watcher(MagicMock(status={"live": live}))
    return p


async def test_le_filet_ramene_wally_apres_un_redemarrage_en_plein_live():
    """Le cas qui justifie le filet : aucune transition n'a eu lieu, donc
    personne n'a ouvert la captation ni fait rejoindre Wally."""
    p, vs, tr = _presence()
    await _avec_watcher(p, True).un_tour()
    tr.open_broadcast.assert_called_once_with(4242)
    vs.join.assert_awaited_once()


async def test_le_filet_FERME_la_captation_hors_live():
    """Deuxième chance de la transition « fin de live » : elle ne se produit
    qu'une fois, et un flux qui la rate laisserait la vanne ouverte."""
    p, vs, tr = _presence()
    await _avec_watcher(p, False).un_tour()
    tr.close_broadcast.assert_called_once()
    tr.open_broadcast.assert_not_called()
    vs.join.assert_not_awaited()


async def test_hors_live_wally_retrouve_le_droit_de_revenir():
    p, vs, _ = _presence(optout=True)
    await _avec_watcher(p, False).un_tour()
    assert vs.listen_optout is False


async def test_le_filet_n_insiste_pas_si_on_l_a_mis_dehors():
    """`listen_optout` : quelqu'un l'a viré du salon pendant le live. Le filet
    ouvre quand même la captation — le live est diffusé — mais ne le renvoie
    pas s'asseoir toutes les trente secondes."""
    p, vs, tr = _presence(optout=True)
    await _avec_watcher(p, True).un_tour()
    tr.open_broadcast.assert_called_once_with(4242)
    vs.join.assert_not_awaited()


async def test_le_filet_ne_deplace_pas_wally_deja_connecte():
    p, vs, _ = _presence(connecte=True)
    await _avec_watcher(p, True).un_tour()
    vs.join.assert_not_awaited()


async def test_un_tour_en_erreur_ne_tue_pas_le_veilleur():
    """Il tourne dans une boucle sans fin : une exception qui remonte
    l'arrêterait pour de bon, et Wally resterait dehors sans un mot."""
    p, _, _ = _presence()
    p._salon = AsyncMock(side_effect=RuntimeError("Discord fâché"))
    await _avec_watcher(p, True).un_tour()   # ne doit pas lever


async def test_sans_watcher_branche_le_filet_croit_le_live_eteint():
    """Repli sûr : on FERME la captation plutôt que de l'ouvrir sur un état
    inconnu. Se tromper dans ce sens ne fait rien fuiter."""
    p, _, tr = _presence()
    await p.un_tour()
    tr.close_broadcast.assert_called_once()
    tr.open_broadcast.assert_not_called()


# ── le point d'entrée synchrone du StreamWatcher ────────────────────────────

async def test_on_transition_lance_bien_le_travail_de_fond():
    import asyncio
    p, _, tr = _presence()
    p.on_transition(OFF, ON)
    await asyncio.sleep(0)
    tr.open_broadcast.assert_called_once_with(4242)


async def test_on_transition_garde_une_reference_forte_a_sa_tache():
    """Sans référence, le GC peut ramasser la tâche en plein join — le bug
    silencieux par excellence : rien ne se passe, et rien ne le dit."""
    import asyncio
    p, _, _ = _presence()
    lent = asyncio.Event()

    async def _traine():
        await lent.wait()
        return MagicMock(id=4242)

    p._salon = _traine
    p.on_transition(OFF, ON)
    assert len(p._taches) == 1
    lent.set()
    await asyncio.sleep(0)
    await asyncio.gather(*p._taches)      # on la laisse finir, pas d'orpheline
    assert not p._taches                  # et le callback l'a bien retirée


async def test_on_transition_ne_lance_RIEN_sans_transition():
    p, _, _ = _presence()
    p.on_transition(ON, ON)
    assert not p._taches


@pytest.mark.parametrize("old,new", [(OFF, ON), (ON, OFF)])
async def test_on_transition_sans_service_vocal_ne_lance_rien(old, new):
    p, _, _ = _presence(sans_service=True)
    p.on_transition(old, new)
    assert not p._taches


async def test_le_veilleur_dit_UNE_fois_qu_il_est_arme():
    """Hors live, ce filet ne laisse aucune trace : `close_broadcast()` sur un
    tampon déjà fermé ne dit rien, `join()` n'est jamais appelé. Sans cette
    ligne, on ne distinguait pas « il tourne » de « la tâche est morte au
    premier tour » — et une tâche asyncio qui lève meurt EN SILENCE.

    Une fois, pas à chaque tour : à deux tours par minute, ce serait 2880
    lignes par jour, et le log deviendrait illisible."""
    from loguru import logger

    vues: list[str] = []
    sink = logger.add(lambda m: vues.append(m.record["message"]), level="INFO")
    try:
        p, _, _ = _presence()
        _avec_watcher(p, False)
        await p.un_tour()
        await p.un_tour()
        await p.un_tour()
    finally:
        logger.remove(sink)

    armes = [v for v in vues if "veilleur de stream armé" in v]
    assert len(armes) == 1, f"attendu 1 ligne, vu {len(armes)}"
