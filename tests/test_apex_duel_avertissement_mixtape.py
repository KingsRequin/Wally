# tests/test_apex_duel_avertissement_mixtape.py
"""L'avertissement Mixtape est collé par le CODE, comme l'adresse du site.

§2 de la spec : la Mixtape ne compte AUCUN kill (mesuré — 10 kills, zéro
tracker bougé), le mode de jeu n'est lisible nulle part dans l'API, donc
« l'avertissement au lancement est obligatoire : c'est la seule protection qui
existe ». Il était pourtant confié au modèle, dont le socle de rédaction exige
« UNE phrase courte » : rien ne garantissait qu'il survive à la compression.

Et le mode annoncé vient de `config.yaml` (§14), d'un seul endroit : il était
écrit en dur dans le code ET répété dans le registre persona, deux copies libres
de diverger en silence.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Evenement
from bot.twitch.duel_announce import DuelAnnonceur, registre_duel


def _bot(reponse_llm="Bob débarque, ça va saigner."):
    bot = MagicMock()
    bot.twitch_api.send_automatic = AsyncMock(return_value=True)
    bot.llm.complete = AsyncMock(return_value=reponse_llm)
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.persona.build_prompt_block = MagicMock(return_value="persona")
    bot.emotion.get_state = MagicMock(return_value={"joy": 0.3})
    bot._channel_ids = {}
    bot._stream_info = {"live": True, "category": "Apex Legends",
                        "title": "duel", "viewers": 12}
    bot.overlay_narrator = None
    bot.discord_bot = None
    return bot


async def _ouverture(bot, mode_jeu="Battle Royale ou Joker") -> str:
    annonceur = DuelAnnonceur(bot, channel="azrael_ttv", mode_jeu=mode_jeu)
    await annonceur(Evenement("duel_ouvert", {"viewer": "Bob"}))
    return bot.twitch_api.send_automatic.await_args.args[0]


@pytest.mark.asyncio
async def test_lavertissement_part_meme_si_le_modele_nen_parle_pas():
    """Le cas réel : le modèle rend une phrase d'ambiance, courte, sans un mot
    du mode de jeu. C'est très exactement ce que son socle lui demande."""
    bot = _bot("Bob monte sur le ring, on va voir ce qu'il a dans le ventre.")

    texte = await _ouverture(bot)

    assert "Mixtape" in texte, f"la seule protection qui existe : {texte!r}"
    assert "Bob monte sur le ring" in texte, "la réplique reste publiée"


@pytest.mark.asyncio
async def test_lavertissement_part_aussi_quand_le_modele_est_muet():
    """LLM en panne : le fait nu est publié — l'avertissement doit y être
    aussi, c'est justement le moment où rien ne l'habille."""
    bot = _bot()
    bot.llm.complete = AsyncMock(side_effect=RuntimeError("LLM mort"))

    texte = await _ouverture(bot)

    assert "Mixtape" in texte


@pytest.mark.asyncio
async def test_une_replique_bavarde_ne_coupe_pas_lavertissement():
    """Tronquer APRÈS l'avoir collé casserait précisément ce qu'on protège :
    la troncature doit mordre sur la réplique, jamais sur l'avertissement."""
    bot = _bot("Bon. " + "je vous raconte tout ça posément, mes agneaux. " * 20)

    texte = await _ouverture(bot)

    assert "Mixtape" in texte
    assert texte.endswith("AUCUN kill.")
    assert len(texte) <= 500, "plafond d'un message Twitch"


@pytest.mark.asyncio
async def test_le_mode_annonce_vient_de_la_configuration():
    """Une seule source. Le mode change dans `config.yaml`, et c'est ce
    mode-là qui est annoncé — sans rebuild, sans copie ailleurs."""
    bot = _bot()

    texte = await _ouverture(bot, mode_jeu="Trios classés uniquement")

    assert "Trios classés uniquement" in texte
    assert "Joker" not in texte, "aucun mode en dur ne doit survivre"


@pytest.mark.asyncio
async def test_sans_mode_configure_lavertissement_reste_vrai():
    """Une valeur vide ne fabrique pas un mode : ce qui reste dit est ce qui
    reste vrai — la Mixtape ne compte rien."""
    bot = _bot()

    texte = await _ouverture(bot, mode_jeu="")

    assert "Mixtape" in texte


def test_le_registre_persona_ne_redit_pas_le_mode_de_jeu():
    """La seconde copie qui pouvait diverger. Le registre dit au modèle de ne
    pas en parler ; s'il nommait un mode, on aurait deux vérités."""
    duel_ouvert = registre_duel()["duel_ouvert"]
    assert "Battle Royale" not in duel_ouvert
    assert "Joker" not in duel_ouvert


def test_le_mode_par_defaut_de_la_configuration_est_renseigne():
    """Le mode vit dans `DuelConfig` : c'est lui la source unique, et un
    défaut vide priverait l'avertissement de sa moitié la plus utile."""
    from bot.config import DuelConfig

    assert DuelConfig().mode_jeu.strip()
