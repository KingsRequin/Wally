"""Ce que Wally sait faire sur Discord, il doit savoir le faire sur Twitch.

Les deux adaptateurs construisent chacun leur liste d'outils LLM, à la main, dans
deux fichiers de ~2 900 et ~1 100 lignes. Rien ne les tient synchronisés. Un
outil branché d'un côté et oublié de l'autre ne casse rien, ne journalise rien,
ne fait échouer aucun test : Wally est simplement incapable sur une plateforme de
ce qu'il sait faire sur l'autre, et personne ne le remarque avant que quelqu'un
le lui demande.

Ce test ne réclame pas l'identité — certaines divergences sont justes, et deux
d'entre elles protègent quelque chose :

  · `search_history` fouille les JSONL de conversation DISCORD. L'offrir à un
    chat Twitch public laisserait n'importe quel viewer exhumer ce qui s'est dit
    sur le serveur Discord.
  · `request_self_modification` engage une modification du code, réservée au
    créateur — identifié par son id Discord. Un pseudo Twitch ne prouve rien.
  · les outils vocaux pilotent un salon Discord.

Ce qu'il réclame, c'est que la liste des écarts soit TENUE. Toute divergence
absente de cet inventaire échoue, avec le nom de l'outil concerné.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.handlers import build_chat_tools as outils_discord
from bot.discord.voice.tools import build_voice_tools as outils_vocal
from bot.twitch.handlers import build_chat_tools as outils_twitch

# Écarts assumés, avec leur raison. Modifier cette table est un acte délibéré.
_DISCORD_SEULEMENT = {
    "search_history": "fouille les logs Discord — fuiterait vers un chat public",
    "request_self_modification": "réservé au créateur, identifié par son id Discord",
    "join_voice": "pilote un salon vocal Discord",
    "leave_voice": "pilote un salon vocal Discord",
}
_TWITCH_SEULEMENT: dict[str, str] = {
    # L'autorisation d'annuler ou de recommencer se lit sur le badge de
    # modérateur du message Twitch. Un salon Discord n'en porte pas : offrir
    # l'outil là-bas ne donnerait qu'un refus systématique.
    "duel_apex": "l'autorisation vient du badge de modérateur Twitch",
    # Un pari engage les POINTS DE CHAÎNE des viewers Twitch, et son
    # autorisation se lit sur le badge du message. Contrairement à la musique,
    # dont la moitié « dire ce qui passe » a du sens partout, ouvrir un pari
    # n'a aucune part lisible depuis Discord : l'offrir là-bas ne rendrait
    # qu'un refus systématique.
    "open_prediction": "engage les points de chaîne, autorisation par badge Twitch",
    # Faire parler Wally à voix haute pendant un live est un pouvoir de
    # modérateur, et l'autorisation se lit sur le badge du message Twitch. Un
    # salon Discord n'en porte pas : l'offrir là-bas ne rendrait qu'un refus
    # systématique. Décision de l'owner le 2026-08-17 — « chat Twitch ».
    "say_in_voice": "l'autorisation vient du badge de modérateur Twitch",
}


def _bot_avec_tout():
    """Un bot où TOUT est branché : c'est là que les écarts se voient."""
    dispo = MagicMock()
    dispo.available = True
    dispo.is_quota_exceeded = AsyncMock(return_value=False)
    dispo.daily_limit_reached = AsyncMock(return_value=False)
    dispo.get_tool_definitions = MagicMock(return_value=[])
    dispo.get_tool_definition = MagicMock(
        return_value={"type": "function", "function": {"name": "apex_legends"}}
    )

    bot = MagicMock()
    bot.web_search = dispo
    bot.scrape = dispo
    bot.apex_api = dispo
    bot.action_service = dispo
    bot.tally = MagicMock()
    bot.predictions = MagicMock()
    bot.quotes = MagicMock()
    bot.voice_service = MagicMock()
    bot.self_fix = MagicMock()
    bot.overlay_narrator = MagicMock()
    bot.config = SimpleNamespace(bot=SimpleNamespace(owner_discord_id="42"))

    historique = MagicMock()
    historique.available = True
    historique.get_tool_definitions = MagicMock(
        return_value=[{"type": "function", "function": {"name": "search_history"}}]
    )
    bot.history_search = historique
    return bot


def _noms(outils) -> set[str]:
    return {o.get("function", {}).get("name", "") for o in outils} - {""}


@pytest.mark.asyncio
async def test_les_deux_plateformes_offrent_les_memes_outils():
    bot = _bot_avec_tout()

    d = _noms(await outils_discord(bot, author_id="42"))   # 42 = le créateur
    t = _noms(await outils_twitch(bot))

    surplus_discord = (d - t) - set(_DISCORD_SEULEMENT)
    surplus_twitch = (t - d) - set(_TWITCH_SEULEMENT)

    assert not surplus_discord, (
        f"outils offerts sur Discord et absents de Twitch : {sorted(surplus_discord)}. "
        "Soit c'est un oubli — branche-les côté Twitch — soit c'est un choix, et "
        "il faut l'inscrire dans _DISCORD_SEULEMENT avec sa raison."
    )
    assert not surplus_twitch, (
        f"outils offerts sur Twitch et absents de Discord : {sorted(surplus_twitch)}."
    )


@pytest.mark.asyncio
async def test_les_ecarts_declares_existent_vraiment():
    """Un inventaire qui décrit des écarts disparus finit par mentir.

    Si `search_history` était un jour branché des deux côtés, la ligne resterait
    dans la table et masquerait un vrai oubli portant le même nom.
    """
    bot = _bot_avec_tout()
    d = _noms(await outils_discord(bot, author_id="42"))
    t = _noms(await outils_twitch(bot))

    perimes = {n for n in _DISCORD_SEULEMENT if n in t or n not in d}
    assert not perimes, (
        f"écarts déclarés qui n'existent plus : {sorted(perimes)} — retire-les de "
        "_DISCORD_SEULEMENT, sinon ils couvriront un futur oubli."
    )


@pytest.mark.asyncio
async def test_le_chat_twitch_ne_peut_pas_fouiller_le_discord():
    """L'écart le plus important de la table, vérifié pour lui-même."""
    bot = _bot_avec_tout()

    assert "search_history" not in _noms(await outils_twitch(bot))
    assert "search_history" in _noms(await outils_discord(bot, author_id="42"))


@pytest.mark.asyncio
async def test_seul_le_createur_obtient_la_self_modification():
    bot = _bot_avec_tout()

    assert "request_self_modification" in _noms(await outils_discord(bot, author_id="42"))
    assert "request_self_modification" not in _noms(await outils_discord(bot, author_id="999"))


@pytest.mark.asyncio
async def test_une_chaine_invitee_ne_pilote_pas_loverlay_du_stream_maison():
    """Garde existant côté Twitch, verrouillé ici : sans lui, le chat d'un
    invité faisait afficher bulles et clips chez Azraël."""
    bot = _bot_avec_tout()

    chez_nous = _noms(await outils_twitch(bot, overlay=True))
    chez_un_invite = _noms(await outils_twitch(bot, overlay=False))

    assert "show_overlay" in chez_nous
    assert "show_overlay" not in chez_un_invite


# ────────────────────────────── le VOCAL ──────────────────────────────
#
# Le troisième chemin, et celui que cet inventaire ne regardait pas. Il a coûté
# exactement ce que ce fichier existe pour éviter : le 2026-08-25 en direct,
# Azraël a demandé trois fois un affichage à voix haute (« affiche le dernier
# clip », « affiche un mème ») et Wally a répondu poliment sans rien afficher —
# `build_voice_tools()` ne lui proposait aucun outil d'overlay, alors qu'il les
# a sur Discord ET sur Twitch. Rien n'a échoué, rien n'a été journalisé.
#
# Les écarts vocaux restants sont RÉELS et non arbitrés (apex_legends, quote,
# les compteurs, show_planning, predict) : ils ne sont pas inscrits ici, parce
# qu'un inventaire sert à consigner des choix, pas à ranger des oublis.
_OVERLAY_EN_VOCAL = ("show_overlay", "cancel_overlay", "show_clip")


@pytest.mark.asyncio
@pytest.mark.parametrize("outil", _OVERLAY_EN_VOCAL)
async def test_ce_qui_s_affiche_depuis_le_chat_s_affiche_aussi_a_la_voix(outil):
    bot = _bot_avec_tout()
    bot.music = MagicMock()

    au_chat = _noms(await outils_discord(bot, author_id="42"))
    a_la_voix = _noms(await outils_vocal(_bot_avec_tout()))

    assert outil in au_chat, f"« {outil} » a disparu du chat — ce test ne compare plus rien"
    assert outil in a_la_voix, (
        f"« {outil} » manque au vocal alors que le chat l'a. Wally répondra "
        "poliment à « affiche-moi ça » sans rien afficher, et personne ne le "
        "saura avant que quelqu'un le lui demande en direct."
    )


@pytest.mark.asyncio
async def test_l_overlay_apex_suit_l_api_sur_les_TROIS_chemins():
    bot = _bot_avec_tout()
    assert "show_apex" in _noms(await outils_discord(bot, author_id="42"))
    assert "show_apex" in _noms(await outils_twitch(bot))
    assert "show_apex" in _noms(await outils_vocal(_bot_avec_tout()))
