# tests/test_twitch_commands_code.py
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# La date de PARIS, comme le code testé — pas `aujourdhui()`, qui suit
# l'horloge machine. L'hôte est en UTC : entre minuit et 02 h heure locale, les
# deux divergent d'un jour et le test aurait échoué une nuit sur deux, sans
# qu'aucune ligne de production n'ait bougé.
from bot.core.temps import aujourdhui


def make_bot(note_value=None):
    bot = MagicMock()
    bot.db.get_persistent_note = AsyncMock(return_value=note_value)
    bot.db.upsert_persistent_note = AsyncMock()
    bot._channel_ids = {}
    bot.twitch_api.send_automatic = AsyncMock()
    irc_channel = MagicMock()
    irc_channel.send = AsyncMock()
    bot.get_channel.return_value = irc_channel
    return bot


def make_mod_badge():
    b = MagicMock()
    b.id = "moderator"
    return b


def make_broadcaster_badge():
    b = MagicMock()
    b.id = "broadcaster"
    return b


def make_viewer_badge():
    b = MagicMock()
    b.id = "subscriber"
    return b


@pytest.fixture(autouse=True)
def clear_state():
    """Vide _daily_codes entre les tests pour éviter les fuites d'état."""
    from bot.twitch.commands import code as code_mod
    code_mod._daily_codes.clear()
    yield
    code_mod._daily_codes.clear()


@pytest.mark.asyncio
async def test_code_no_code_set_shows_no_code_message():
    """!code sans code défini → message 'Pas de code'."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    text = bot.twitch_api.send_automatic.call_args.args[0]
    assert "Pas de code" in text


@pytest.mark.asyncio
async def test_code_displays_code_with_reminder():
    """!code avec code défini → affiche le code + le RAPPEL."""
    from bot.twitch.commands.code import handle_code_command
    today = str(aujourdhui())
    saved = json.dumps({"code": "ABC123", "date": today})
    bot = make_bot(note_value=saved)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    text = bot.twitch_api.send_automatic.call_args.args[0]
    assert "ABC123" in text
    assert "ON DIT BONJOUR" in text
    assert "RAPPEL" in text


@pytest.mark.asyncio
async def test_code_set_by_moderator_saves_and_displays():
    """!code ABC par un modérateur → sauvegarde en DB + affiche le code."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    badges = [make_mod_badge()]
    await handle_code_command(bot, "streamer", "mod1", "NEWCODE", badges)
    # DB sauvegardée
    bot.db.upsert_persistent_note.assert_awaited_once()
    saved_json = bot.db.upsert_persistent_note.call_args.args[1]
    assert "NEWCODE" in saved_json
    # Message affiché
    text = bot.twitch_api.send_automatic.call_args.args[0]
    assert "NEWCODE" in text
    assert "ON DIT BONJOUR" in text


@pytest.mark.asyncio
async def test_code_set_by_broadcaster_saves():
    """!code par broadcaster → accepté."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "owner", "MYCODE", [make_broadcaster_badge()])
    bot.db.upsert_persistent_note.assert_awaited_once()


@pytest.mark.asyncio
async def test_code_set_rejected_for_viewer():
    """!code par un viewer → refusé, DB non touchée."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "viewer", "HACK", [make_viewer_badge()])
    bot.db.upsert_persistent_note.assert_not_awaited()
    text = bot.twitch_api.send_automatic.call_args.args[0]
    assert "modérateurs" in text.lower() or "Seuls" in text


@pytest.mark.asyncio
async def test_code_resets_if_date_changed():
    """Si le code sauvegardé vient d'hier, il est reset à None."""
    from bot.twitch.commands.code import handle_code_command
    yesterday_note = json.dumps({"code": "OLDCODE", "date": "2000-01-01"})
    bot = make_bot(note_value=yesterday_note)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    text = bot.twitch_api.send_automatic.call_args.args[0]
    assert "Pas de code" in text
    # DB mise à jour avec date d'aujourd'hui et code None
    bot.db.upsert_persistent_note.assert_awaited_once()
    saved = json.loads(bot.db.upsert_persistent_note.call_args.args[1])
    assert saved["code"] is None
    assert saved["date"] == str(aujourdhui())


@pytest.mark.asyncio
async def test_code_loaded_from_db_on_first_access():
    """Au premier accès, le code est chargé depuis la DB."""
    from bot.twitch.commands.code import handle_code_command
    today = str(aujourdhui())
    saved = json.dumps({"code": "DBCODE", "date": today})
    bot = make_bot(note_value=saved)
    await handle_code_command(bot, "newchannel", "viewer1", "", [])
    bot.db.get_persistent_note.assert_awaited_once_with("twitch_code:newchannel")
    text = bot.twitch_api.send_automatic.call_args.args[0]
    assert "DBCODE" in text


@pytest.mark.asyncio
async def test_code_not_reloaded_from_db_on_second_call():
    """Au deuxième appel, la DB n'est plus consultée (cache mémoire)."""
    from bot.twitch.commands.code import handle_code_command
    today = str(aujourdhui())
    saved = json.dumps({"code": "CACHED", "date": today})
    bot = make_bot(note_value=saved)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    assert bot.db.get_persistent_note.await_count == 1  # chargé une seule fois


# ─── Annonce Discord de partie privée ────────────────────────────────────────
# `pp.js` (PhantomBot) poussait cette annonce par webhook. Vérifié le 2026-08-28 :
# il ne l'a JAMAIS fait — le script enregistre ses commandes sous
# `./custom/pp.js` alors qu'il vit dans `./custom/custom/pp.js`, donc PhantomBot
# n'associe la commande à aucun script et se tait. Zéro occurrence dans les logs
# de chat de février à août 2026. Wally reprend donc une fonctionnalité qui
# n'existait que sur le papier — et sans webhook : il est déjà dans la guilde.


def make_bot_avec_discord(note_value=None, channel_id=42, role_id=7):
    """Bot Twitch avec un bot Discord branché et la config d'annonce posée."""
    bot = make_bot(note_value=note_value)
    salon = MagicMock()
    salon.send = AsyncMock()
    discord_bot = MagicMock()
    discord_bot.get_channel.return_value = salon
    bot.discord_bot = discord_bot
    bot.config.bot.partie_privee_channel_id = channel_id
    bot.config.bot.partie_privee_role_id = role_id
    return bot, salon


@pytest.mark.asyncio
async def test_pose_de_code_annonce_sur_discord_avec_ping():
    """Un modérateur pose le code → annonce Discord avec le ping de rôle."""
    from bot.twitch.commands.code import handle_code_command
    bot, salon = make_bot_avec_discord()
    await handle_code_command(bot, "streamer", "mod1", "CP7YL6Y8", [make_mod_badge()])
    salon.send.assert_awaited_once()
    texte = salon.send.call_args.args[0]
    assert "CP7YL6Y8" in texte
    assert "<@&7>" in texte


@pytest.mark.asyncio
async def test_annonce_ne_pingue_que_le_role_vise():
    """Le ping est restreint à CE rôle : ni @everyone, ni les membres cités.

    Le garde global du projet (`_ALLOWED_MENTIONS`) pose `roles=False` : sans
    autorisation explicite, le `<@&…>` s'afficherait sans notifier personne —
    et le ping est précisément ce qui fait venir les gens.
    """
    from bot.twitch.commands.code import handle_code_command
    bot, salon = make_bot_avec_discord(role_id=1138818671876255764)
    await handle_code_command(bot, "streamer", "mod1", "ABC", [make_mod_badge()])
    mentions = salon.send.call_args.kwargs["allowed_mentions"]
    assert mentions.everyone is False
    assert mentions.users is False
    assert [r.id for r in mentions.roles] == [1138818671876255764]


@pytest.mark.asyncio
async def test_consulter_le_code_n_annonce_rien():
    """`!code` sans argument consulte : aucune annonce, sinon chaque curieux
    republierait le ping."""
    from bot.twitch.commands.code import handle_code_command
    today = str(aujourdhui())
    bot, salon = make_bot_avec_discord(note_value=json.dumps({"code": "X", "date": today}))
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    salon.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_refuse_n_annonce_rien():
    """Un viewer qui tente de poser un code est refusé — et rien ne part sur Discord."""
    from bot.twitch.commands.code import handle_code_command
    bot, salon = make_bot_avec_discord()
    await handle_code_command(bot, "streamer", "viewer", "HACK", [make_viewer_badge()])
    salon.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_chaine_invitee_n_annonce_pas():
    """Depuis une chaîne invitée, aucune annonce.

    `!code` répond sur les chaînes invitées aussi. Sans ce garde, un modérateur
    d'une autre chaîne pingerait le Discord d'Azraël pour SA partie privée.
    Même réflexe que `!image` et les outils d'overlay.
    """
    from bot.twitch.commands.code import handle_code_command
    bot, salon = make_bot_avec_discord()
    bot._channel_ids = {"invitee": 999}
    await handle_code_command(bot, "invitee", "mod1", "ABC", [make_mod_badge()])
    salon.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_annonce_ignoree_si_salon_non_configure():
    """Sans salon configuré, la commande fait son travail sans lever."""
    from bot.twitch.commands.code import handle_code_command
    bot, salon = make_bot_avec_discord(channel_id=None)
    await handle_code_command(bot, "streamer", "mod1", "ABC", [make_mod_badge()])
    salon.send.assert_not_awaited()
    assert "ABC" in bot.twitch_api.send_automatic.call_args.args[0]


@pytest.mark.asyncio
async def test_echec_discord_ne_casse_pas_la_commande():
    """Discord injoignable → le code part quand même dans le chat Twitch.

    L'annonce est un bonus ; le chat est la fonction. L'inverse ferait perdre le
    code à tout le monde parce qu'un salon Discord a été renommé.
    """
    from bot.twitch.commands.code import handle_code_command
    bot, salon = make_bot_avec_discord()
    salon.send = AsyncMock(side_effect=RuntimeError("boom"))
    await handle_code_command(bot, "streamer", "mod1", "ABC", [make_mod_badge()])
    assert "ABC" in bot.twitch_api.send_automatic.call_args.args[0]


@pytest.mark.asyncio
async def test_pp_donne_la_regle_des_demandes_d_ami():
    """`!pp` rend le message d'organisation — la partie utile que Wally perdait."""
    from bot.twitch.commands.code import handle_pp_command
    bot = make_bot()
    await handle_pp_command(bot, "streamer")
    texte = bot.twitch_api.send_automatic.call_args.args[0]
    assert "samedis" in texte
    assert "en amis" in texte


@pytest.mark.asyncio
async def test_code_sans_code_donne_aussi_la_regle():
    """`!code` sans code du jour : le rendez-vous ET la règle des demandes d'ami."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    texte = bot.twitch_api.send_automatic.call_args.args[0]
    assert "Pas de code" in texte
    assert "en amis" in texte
    # Twitch coupe à 500 caractères : un message tronqué perdrait la fin de la règle.
    assert len(texte) <= 500


@pytest.mark.asyncio
async def test_le_chat_twitch_passe_avant_l_annonce_discord():
    """Le code part dans le chat AVANT l'annonce Discord.

    L'inverse ferait attendre le live pendant un aller-retour vers une guilde,
    pour un salon que personne devant le stream ne regarde à cet instant.
    """
    from bot.twitch.commands.code import handle_code_command
    ordre = []
    bot, salon = make_bot_avec_discord()
    bot.twitch_api.send_automatic = AsyncMock(side_effect=lambda *a, **k: ordre.append("twitch"))
    salon.send = AsyncMock(side_effect=lambda *a, **k: ordre.append("discord"))
    await handle_code_command(bot, "streamer", "mod1", "ABC", [make_mod_badge()])
    assert ordre == ["twitch", "discord"]
