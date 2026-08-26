"""Sur Twitch, Wally appelait les gens par leur login, pas par leur pseudo.

Twitch sépare le `login` — minuscules, immuable, celui qui sert aux mentions —
du pseudo AFFICHÉ, que la personne choisit (casse, accents, autre alphabet). Le
modèle maison de `channel.chat.message` ne lisait que le login et jetait
`chatter_user_name`, pourtant présent dans la charge utile reçue. En base :
`malef__`, `kingsrequin`, `azrael_ttv` — là où Discord dit « Malef (@malef__) ».
"""

from unittest.mock import MagicMock

from bot.twitch.events.models import ChatMessageData
from bot.twitch.handlers import libelle_chatter


def payload_brut(login="malef__", nom="Malef", avec_nom=True):
    data = {
        "chatter_user_id": "123",
        "chatter_user_login": login,
        "message": {"text": "salut"},
        "broadcaster_user_id": "456",
        "broadcaster_user_login": "azrael_ttv",
        "message_id": "abc",
        "badges": [],
    }
    if avec_nom:
        data["chatter_user_name"] = nom
    return data


def make_client():
    """⚠️ `name=` est réservé par MagicMock (il nomme le mock) : il faut le poser
    APRÈS construction, sinon l'attribut lu est un sous-mock et le test ment."""
    def _user(uid, nom):
        u = MagicMock(id=uid)
        u.name = nom
        return u

    client = MagicMock()
    client.client.create_user = _user
    return client


# --- le modèle garde ce que Twitch envoie -----------------------------------


def test_le_pseudo_affiche_n_est_plus_jete():
    donnees = ChatMessageData(make_client(), payload_brut())

    assert donnees.chatter_display == "Malef"
    assert donnees.chatter.name == "malef__"   # le login reste, il sert aux mentions


def test_sans_pseudo_affiche_on_retombe_sur_le_login():
    """Défaut sûr : mieux vaut le login qu'un nom vide."""
    donnees = ChatMessageData(make_client(), payload_brut(avec_nom=False))

    assert donnees.chatter_display == "malef__"


def test_un_pseudo_en_autre_alphabet_passe_intact():
    donnees = ChatMessageData(make_client(), payload_brut(login="kenshi_ttv", nom="ケンシ"))

    assert donnees.chatter_display == "ケンシ"


# --- le libellé, pendant Twitch de `_author_label` --------------------------


def test_un_pseudo_different_du_login_porte_les_deux():
    assert libelle_chatter("malef__", "Malef") == "Malef (@malef__)"


def test_la_casse_seule_ne_justifie_pas_la_parenthese():
    """« KingsRequin (@kingsrequin) » n'apprend rien et alourdit chaque ligne."""
    assert libelle_chatter("kingsrequin", "KingsRequin") == "KingsRequin"


def test_un_pseudo_absent_vaut_le_login_seul():
    assert libelle_chatter("malef__", None) == "malef__"
    assert libelle_chatter("malef__", "   ") == "malef__"


def test_un_login_absent_ne_produit_pas_une_arobase_orpheline():
    assert libelle_chatter("", "Malef") == "Malef"


def test_le_meme_format_qu_a_l_ecrit_sur_discord():
    """La parité se joue sur la FORME : les deux plateformes nourrissent le même
    prompt, deux conventions de nommage y sont illisibles."""
    from bot.discord.handlers import _author_label

    membre = MagicMock()
    membre.display_name = "Malef"
    membre.name = "malef__"

    assert libelle_chatter("malef__", "Malef") == _author_label(membre)


# --- de bout en bout : ce que Wally LIT -------------------------------------


async def test_le_prelude_et_le_flux_du_stream_portent_le_pseudo_affiche():
    """Les deux endroits où le nom finit sous les yeux du LLM."""
    from unittest.mock import AsyncMock, patch

    from bot.core.stream_feed import StreamFeed
    from bot.twitch.handlers import handle_message
    from tests.test_twitch_handlers import make_bot, make_payload

    feed = StreamFeed("Azrael_TTV")
    bot = make_bot()
    bot.stream_feed = feed
    bot._channel_ids = {}
    bot._stream_info = {"live": True}
    bot._active_visits = {}
    bot.cognitive_loop = None
    bot.fact_extractor = None
    bot.reaction_tracker = None

    with patch("bot.twitch.handlers.dispatch_command", new_callable=AsyncMock,
               return_value=False):
        await handle_message(bot, make_payload(
            content="gg", author_name="malef__", author_display="Malef",
            channel="azrael_ttv",
        ))

    assert "[Malef (@malef__)] gg" in feed.render()
    bot.memory.append_prelude.assert_called_with(
        "twitch:azrael_ttv", "Malef (@malef__)", "gg"
    )
