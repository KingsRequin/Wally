"""Ce que Wally fait quand une action arrive à échéance — exécuté, pas relu.

Ces trois handlers étaient des closures dans le `main()` de mille lignes de
`bot/main.py`. Le seul « test » qui les visait lisait le SOURCE du fichier :

    src = Path("bot/main.py").read_text()
    corps = src[src.index("async def _send_message_to_channel_handler"):][:3000]
    assert "guildes = [guilde_origine]" in corps
    assert "for guild in discord_bot.guilds:" not in corps

Il couvrait une correction de SÉCURITÉ — un ping de masse cross-serveur — en
cherchant une chaîne de caractères. Vert devant n'importe quelle logique
contenant ces mots, et muet sur ce que le code FAIT.

Ici, on envoie vraiment le message et on regarde où il part.
"""
from functools import partial
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.llm.base import FALLBACK_RESPONSE
from bot.intelligence.actions.handlers import (
    join_twitch_channel_handler,
    reminder_handler,
    send_message_to_channel_handler,
)


# ── send_message_to_channel : la faille de ping cross-serveur ───────────────

def _salon(nom: str, ident: int, guilde):
    s = MagicMock()
    s.name = nom
    s.id = ident
    s.guild = guilde
    return s


def _monde():
    """Deux serveurs, chacun avec son « #général ». Le piège en une phrase."""
    maison, ailleurs = MagicMock(), MagicMock()
    general_maison = _salon("général", 111, maison)
    general_ailleurs = _salon("général", 222, ailleurs)
    maison.text_channels = [general_maison]
    ailleurs.text_channels = [general_ailleurs]

    bot = MagicMock()
    bot.guilds = [ailleurs, maison]        # `ailleurs` EN PREMIER, exprès
    bot.get_channel = MagicMock(side_effect=lambda i: general_maison if i == 111 else None)

    executor = MagicMock()
    executor.deliver = AsyncMock()
    return bot, executor


def _envoyer(bot, executor):
    return partial(send_message_to_channel_handler,
                   discord_bot=bot, action_executor=executor)


async def test_le_message_part_dans_le_salon_du_SERVEUR_D_ORIGINE():
    """Le cœur de la faille M34. Deux serveurs ont un « #général » ; la tâche
    vient de celui d'id 111. Sans bornage, le balayage prend le premier trouvé
    — ici volontairement celui d'un AUTRE serveur — et y envoie le message avec
    ses mentions."""
    bot, executor = _monde()
    r = await _envoyer(bot, executor)(
        {"message": "coucou", "channel": "#général"},
        {"channel_id": "111", "platform": "discord"},
    )
    executor.deliver.assert_awaited_once_with("coucou", "discord", "111")
    assert "111" not in r and "envoyé" in r


async def test_un_salon_du_MEME_nom_ailleurs_n_est_jamais_choisi():
    """La contre-épreuve : le salon d'origine n'existe QUE chez `ailleurs`, et
    la tâche vient de `maison` — il ne doit rien partir du tout."""
    maison, ailleurs = MagicMock(), MagicMock()
    maison.text_channels = []
    ailleurs.text_channels = [_salon("secret", 222, ailleurs)]
    origine = _salon("origine", 111, maison)

    bot = MagicMock()
    bot.guilds = [ailleurs, maison]
    bot.get_channel = MagicMock(return_value=origine)
    executor = MagicMock(); executor.deliver = AsyncMock()

    r = await _envoyer(bot, executor)(
        {"message": "coucou", "channel": "#secret"},
        {"channel_id": "111", "platform": "discord"},
    )
    executor.deliver.assert_not_awaited()
    assert "introuvable" in r


async def test_un_id_numerique_part_tel_quel():
    bot, executor = _monde()
    await _envoyer(bot, executor)(
        {"message": "coucou", "channel": "999"}, {"platform": "discord"})
    executor.deliver.assert_awaited_once_with("coucou", "discord", "999")


async def test_sans_salon_d_origine_on_cherche_partout():
    """Comportement conservé : une tâche créée hors d'un salon n'a pas
    d'origine. Resserrer là aussi casserait l'envoi légitime, et ce n'est pas
    le cas qui était exploitable."""
    bot, executor = _monde()
    await _envoyer(bot, executor)(
        {"message": "coucou", "channel": "#général"}, {"platform": "discord"})
    executor.deliver.assert_awaited_once()


async def test_une_origine_illisible_ne_fait_pas_tout_planter():
    """`channel_id` peut valoir n'importe quoi : `int()` lèverait."""
    bot, executor = _monde()
    r = await _envoyer(bot, executor)(
        {"message": "coucou", "channel": "#général"},
        {"channel_id": "pas-un-nombre", "platform": "discord"},
    )
    assert "envoyé" in r


async def test_twitch_part_sur_la_chaine_en_minuscules():
    bot, executor = _monde()
    await _envoyer(bot, executor)(
        {"message": "yo", "channel": "AzraeL_TTV", "platform": "twitch"}, {})
    executor.deliver.assert_awaited_once_with("yo", "twitch", "azrael_ttv")


@pytest.mark.parametrize("payload,attendu", [
    ({"message": "", "channel": "#g"}, "vide"),
    ({"message": "x", "channel": ""}, "non spécifié"),
    ({"message": "x", "channel": "#g", "platform": "irc"}, "non reconnue"),
])
async def test_les_refus_ne_delivrent_rien(payload, attendu):
    bot, executor = _monde()
    r = await _envoyer(bot, executor)(payload, {})
    executor.deliver.assert_not_awaited()
    assert attendu in r


# ── reminder : le repli compte plus que la reformulation ────────────────────

def _rappel(reponse):
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=reponse) if not isinstance(reponse, Exception) \
        else AsyncMock(side_effect=reponse)
    prompts = MagicMock(); prompts.build_system_prompt = MagicMock(return_value="SYS")
    return partial(reminder_handler, prompts=prompts, emotion=MagicMock(),
                   persona=MagicMock(), secondary_llm=llm), llm


async def test_le_rappel_est_reformule_et_mentionne_son_destinataire():
    h, _ = _rappel("N'oublie pas le pain.")
    r = await h({"message": "acheter du pain"},
                {"platform": "discord", "creator_id": "42"})
    assert r == "<@42> N'oublie pas le pain."


async def test_un_LLM_en_REPLI_envoie_le_texte_demandé():
    """`complete()` ne lève pas, il rend FALLBACK_RESPONSE. Sans ce test,
    l'utilisateur recevait « Je rencontre un problème technique » à la place de
    son rappel — et la tâche `once` était consommée : il ne repartait jamais."""
    h, _ = _rappel(FALLBACK_RESPONSE)
    r = await h({"message": "acheter du pain"},
                {"platform": "discord", "creator_id": "42"})
    assert r == "<@42> acheter du pain"


async def test_une_reponse_VIDE_envoie_aussi_le_texte_demandé():
    h, _ = _rappel("   ")
    assert await h({"message": "le pain"}, {}) == "le pain"


async def test_un_LLM_qui_LÈVE_envoie_le_texte_demandé():
    h, _ = _rappel(RuntimeError("API morte"))
    assert await h({"message": "le pain"}, {}) == "le pain"


async def test_hors_discord_il_n_y_a_pas_de_mention():
    """Un `<@42>` dans le chat Twitch ne mentionne personne, il pollue."""
    h, _ = _rappel("N'oublie pas.")
    r = await h({"message": "x"}, {"platform": "twitch", "creator_id": "42"})
    assert r == "N'oublie pas."


async def test_sans_message_le_rappel_a_quand_meme_un_texte():
    h, llm = _rappel("Rappel !")
    await h({}, {})
    envoye = llm.complete.await_args.args[1][0]["content"]
    assert "Rappel!" in envoye


# ── join_twitch_channel ─────────────────────────────────────────────────────

def _twitch(resultat):
    bot = MagicMock()
    bot.add_guest_channel = AsyncMock(return_value=resultat)
    return partial(join_twitch_channel_handler, twitch_bot=bot), bot


async def test_rejoindre_une_chaine_la_normalise():
    h, bot = _twitch("ok")
    r = await h({"channel": "  AzraeL_TTV "}, {})
    bot.add_guest_channel.assert_awaited_once_with("azrael_ttv")
    assert "azrael_ttv" in r


@pytest.mark.parametrize("resultat,attendu", [
    ("already_added", "déjà"),
    (None, "Impossible"),
])
async def test_les_refus_de_twitch_sont_dits(resultat, attendu):
    h, _ = _twitch(resultat)
    assert attendu in await h({"channel": "x"}, {})


async def test_sans_bot_twitch_on_le_dit_au_lieu_de_planter():
    h = partial(join_twitch_channel_handler, twitch_bot=None)
    assert "non disponible" in await h({"channel": "x"}, {})


async def test_un_nom_de_chaine_vide_est_refuse_avant_l_appel():
    h, bot = _twitch("ok")
    assert "manquant" in await h({"channel": "   "}, {})
    bot.add_guest_channel.assert_not_awaited()


# ── le CÂBLAGE lui-même ─────────────────────────────────────────────────────
#
# C'est la partie que rien ne testait, et c'est de cette famille qu'était le
# défaut du 2026-08-23 : une fonction de module qui rangeait sa tâche dans une
# locale de `main()`, `NameError` au premier appel réel, invisible aux 5872
# tests. Le test appelle `enregistrer_actions()` — la VRAIE, celle que `main()`
# appelle — et exécute les handlers qui en sortent. Recopier les `partial()`
# ici prouverait seulement que la copie marche.

class _Registre:
    """Le minimum du registre : retenir ce qu'on lui déclare."""

    def __init__(self):
        self.defs = {}

    async def register(self, nom, definition):
        self.defs[nom] = definition


async def _registre_cable(**remplacements):
    from bot.intelligence.actions.handlers import enregistrer_actions

    bot_discord, executor = _monde()
    deps = dict(
        prompts=MagicMock(), emotion=MagicMock(), persona=MagicMock(),
        secondary_llm=MagicMock(), twitch_bot=MagicMock(),
        discord_bot=bot_discord, action_executor=executor,
    )
    deps["prompts"].build_system_prompt = MagicMock(return_value="SYS")
    deps["secondary_llm"].complete = AsyncMock(return_value="reformulé")
    deps["twitch_bot"].add_guest_channel = AsyncMock(return_value="ok")
    deps.update(remplacements)

    r = _Registre()
    await enregistrer_actions(r, **deps)
    return r, deps, executor


async def test_les_quatre_actions_sont_declarees():
    r, _, _ = await _registre_cable()
    assert set(r.defs) == {"reminder", "reminder_recurring",
                           "join_twitch_channel", "send_message_to_channel"}


async def test_les_deux_rappels_partagent_le_MEME_handler():
    """`ActionService.create()` route vers l'un ou l'autre selon
    `schedule.type` : deux handlers différents divergeraient en silence."""
    r, _, _ = await _registre_cable()
    assert r.defs["reminder"].handler is r.defs["reminder_recurring"].handler


async def test_chaque_handler_declare_S_APPELLE_vraiment():
    """Le test qui aurait attrapé le défaut du jour. Un `partial()` mal lié ne
    se voit ni à la lecture, ni au boot : il lève au PREMIER appel réel, des
    semaines plus tard."""
    r, _, executor = await _registre_cable()

    assert "reformulé" in await r.defs["reminder"].handler(
        {"message": "le pain"}, {"platform": "discord", "creator_id": "7"})
    assert "azrael" in await r.defs["join_twitch_channel"].handler(
        {"channel": "Azrael"}, {})
    await r.defs["send_message_to_channel"].handler(
        {"message": "coucou", "channel": "#général"},
        {"channel_id": "111", "platform": "discord"})
    executor.deliver.assert_awaited_once_with("coucou", "discord", "111")


async def test_le_cablage_transmet_les_BONNES_dependances():
    """Un `partial()` peut être valide et pourtant lier le mauvais objet — deux
    services de même forme se ressemblent. On vérifie que c'est bien CELUI-LÀ
    qui a été appelé."""
    llm = MagicMock(); llm.complete = AsyncMock(return_value="via le bon LLM")
    r, _, _ = await _registre_cable(secondary_llm=llm)
    await r.defs["reminder"].handler({"message": "x"}, {})
    llm.complete.assert_awaited_once()
