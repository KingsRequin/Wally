"""`GET /api/admin/connexions` — l'état des deux adaptateurs, avec ses faits.

« Connecté » ne suffit pas. Un bot Discord prêt sur zéro serveur et un EventSub
vivant sans souscription allument le même voyant vert : c'est exactement le
genre d'état où quelque chose ne marche plus et où personne n'est prévenu.
Chaque adaptateur rend donc des FAITS chiffrés.

L'autre sujet de ces tests est la ROBUSTESSE de la lecture. Les objets bot
n'ont pas la même forme selon qu'ils démarrent, qu'ils sont arrêtés, ou qu'ils
sont absents de la config — et une carte ne doit jamais emporter l'autre.
"""
from __future__ import annotations

import types

from bot.dashboard.routes.admin import etat_connexions


def _requete(discord_bot=None, twitch_bot=None, invitees=()):
    wally = types.SimpleNamespace(
        discord_bot=discord_bot,
        twitch_bot=twitch_bot,
        config=types.SimpleNamespace(
            twitch=types.SimpleNamespace(guest_channels=list(invitees))
        ),
    )
    return types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(wally=wally))
    )


class _FauxDiscord:
    def __init__(self, pret=True, serveurs=(), latence=0.099, arbre=True):
        self._pret = pret
        self.guilds = list(serveurs)
        self.user = "Wally#0058"
        self.latency = latence
        self.tree = types.SimpleNamespace(get_commands=lambda: [1, 2, 3]) if arbre else None

    def is_ready(self):
        return self._pret

    def is_closed(self):
        return not self._pret


def _serveur(n_salons):
    return types.SimpleNamespace(text_channels=[object()] * n_salons)


async def test_un_adaptateur_absent_est_dit_non_configure():
    d = await etat_connexions(_requete())
    assert d["discord"]["configure"] is False
    assert d["twitch"]["configure"] is False


async def test_discord_rend_ses_faits_chiffres():
    d = await etat_connexions(_requete(
        discord_bot=_FauxDiscord(serveurs=[_serveur(40), _serveur(41)])))
    faits = dict(d["discord"]["faits"])
    assert d["discord"]["pret"] is True
    assert d["discord"]["nom"] == "Wally#0058"
    assert faits["Serveurs"] == "2"
    assert faits["Salons texte"] == "81"
    assert faits["Commandes /"] == "3"
    assert faits["Latence"] == "99 ms"


async def test_un_bot_ferme_nest_pas_pret_meme_sil_dit_etre_ready():
    """`is_ready()` reste vrai après un `close()` : c'est `is_closed()` qui
    tranche, et un voyant vert sur un bot arrêté serait un mensonge."""
    bot = _FauxDiscord(pret=True)
    bot.is_closed = lambda: True
    d = await etat_connexions(_requete(discord_bot=bot))
    assert d["discord"]["pret"] is False


async def test_une_latence_non_mesurable_ne_sinvente_pas():
    """`latency` vaut NaN tant que la connexion n'est pas établie. Affiché,
    ça donne « nan ms »."""
    d = await etat_connexions(_requete(discord_bot=_FauxDiscord(latence=float("nan"))))
    assert "Latence" not in dict(d["discord"]["faits"])


async def test_un_arbre_de_commandes_illisible_ne_casse_pas_la_carte():
    bot = _FauxDiscord()
    bot.tree = types.SimpleNamespace()          # pas de `get_commands`
    d = await etat_connexions(_requete(discord_bot=bot))
    assert d["discord"]["pret"] is True
    assert "Serveurs" in dict(d["discord"]["faits"])


async def test_twitch_dit_par_quelle_voie_il_est_muet():
    """EventSub et IRC sont les DEUX chemins par lesquels Wally devient muet.
    N'en montrer qu'un laisse chercher du mauvais côté."""
    bot = types.SimpleNamespace(
        _eventsub_client=object(), nick="wallytebully", _irc_vivante=lambda: False)
    d = await etat_connexions(_requete(twitch_bot=bot, invitees=["a", "b"]))
    faits = dict(d["twitch"]["faits"])
    assert d["twitch"]["pret"] is True
    assert faits["EventSub"] == "actif"
    assert faits["IRC"] == "muet"
    assert faits["Chaînes invitées"] == "2"


async def test_un_eventsub_absent_est_dit_absent():
    bot = types.SimpleNamespace(_eventsub_client=None, nick="x")
    d = await etat_connexions(_requete(twitch_bot=bot))
    assert d["twitch"]["pret"] is False
    assert dict(d["twitch"]["faits"])["EventSub"] == "absent"


async def test_un_etat_irc_qui_leve_nemporte_pas_la_carte_discord():
    def _casse():
        raise RuntimeError("connexion à demi montée")

    bot = types.SimpleNamespace(_eventsub_client=None, nick="x", _irc_vivante=_casse)
    d = await etat_connexions(_requete(discord_bot=_FauxDiscord(), twitch_bot=bot))
    assert d["discord"]["pret"] is True
    assert "IRC" not in dict(d["twitch"]["faits"])
