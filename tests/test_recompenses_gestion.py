"""Récompenses pilotées depuis le panneau, et prix dynamique du TTS (2026-09-16).

Ce qui compte ici :
  · un prix modifié part chez Twitch SANS redémarrage ;
  · une récompense supprimée n'est jamais recréée au boot suivant ;
  · le prix du TTS monte à chaque achat ENTENDU et redescend avec le temps,
    et la chauffe survit à un redémarrage.
"""
from __future__ import annotations

import json
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import PrixDynamiqueConfig, RecompenseConfig
from bot.twitch.recompenses import DEFINITIONS, GestionRecompenses, PrixDynamique


class _Etat:
    def __init__(self, **valeurs):
        self.v = dict(valeurs)

    async def get_state(self, cle):
        return self.v.get(cle)

    async def set_state(self, cle, valeur):
        self.v[cle] = valeur


def _config(**recompenses):
    rec = {"tts_viewer": RecompenseConfig(titre="tts wally", cout=500, prompt="p")}
    rec.update(recompenses)
    return types.SimpleNamespace(
        twitch=types.SimpleNamespace(
            recompenses=rec, prix_dynamique_tts=PrixDynamiqueConfig(20.0, 10.0)),
        save=MagicMock())


class _Horloge:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def _api(gerables=None):
    api = MagicMock()
    api.recompenses_gerables = AsyncMock(return_value=gerables or [])
    api.maj_recompense = AsyncMock(return_value=True)
    api.creer_recompense = AsyncMock(return_value="NEUF")
    api.supprimer_recompense = AsyncMock(return_value=True)
    return api


# ── le prix dynamique ───────────────────────────────────────────────────────

async def test_le_prix_monte_de_la_hausse_a_chaque_achat():
    h = _Horloge()
    prix = PrixDynamique(_Etat(), _config(), horloge=h)
    assert prix.prix() == 500
    await prix.ajouter_achat()
    assert prix.prix() == 600
    await prix.ajouter_achat()
    assert prix.prix() == 700


async def test_la_chauffe_fond_de_moitie_par_demi_vie():
    h = _Horloge()
    prix = PrixDynamique(_Etat(), _config(), horloge=h)
    await prix.ajouter_achat()
    await prix.ajouter_achat()
    h.t += 600
    assert prix.prix() == 600
    h.t += 6000
    assert prix.prix() == 500


async def test_une_hausse_a_zero_rend_le_prix_fixe():
    conf = _config()
    conf.twitch.prix_dynamique_tts.hausse_pct = 0
    prix = PrixDynamique(_Etat(), conf, horloge=_Horloge())
    await prix.ajouter_achat()
    assert prix.prix() == 500


async def test_la_chauffe_survit_au_redemarrage():
    h, etat = _Horloge(), _Etat()
    await PrixDynamique(etat, _config(), horloge=h).ajouter_achat()
    relu = PrixDynamique(etat, _config(), horloge=h)
    await relu.charger()
    assert relu.prix() == 600
    assert json.loads(etat.v[PrixDynamique.CLE_ETAT])["chauffe"] == 1


async def test_le_prix_de_base_se_lit_a_chaud():
    conf = _config()
    prix = PrixDynamique(_Etat(), conf, horloge=_Horloge())
    conf.twitch.recompenses["tts_viewer"].cout = 800
    assert prix.prix() == 800


# ── la gestion ──────────────────────────────────────────────────────────────

async def test_un_achat_pousse_le_nouveau_prix_a_twitch():
    cle = DEFINITIONS["tts_viewer"].cle_etat
    api = _api()
    g = GestionRecompenses(api, _Etat(**{cle: "RW"}), _config())
    g._prix_pousse = 500
    avant, apres = await g.apres_achat_tts()
    assert (avant, apres) == (500, 600)
    assert api.maj_recompense.await_args.args[:3] == ("RW", "tts wally", 600)


async def test_un_prix_inchange_n_appelle_pas_twitch():
    cle = DEFINITIONS["tts_viewer"].cle_etat
    api = _api()
    g = GestionRecompenses(api, _Etat(**{cle: "RW"}), _config())
    g._prix_pousse = 500
    assert await g.pousser_prix_tts() == 500
    api.maj_recompense.assert_not_awaited()


async def test_un_patch_refuse_sera_retente():
    cle = DEFINITIONS["tts_viewer"].cle_etat
    api = _api()
    api.maj_recompense = AsyncMock(return_value=False)
    g = GestionRecompenses(api, _Etat(**{cle: "RW"}), _config())
    g._prix_pousse = 500
    await g.prix_tts.ajouter_achat()
    assert await g.pousser_prix_tts() == 500
    api.maj_recompense = AsyncMock(return_value=True)
    assert await g.pousser_prix_tts() == 600


async def test_supprimer_retire_de_twitch_et_bloque_la_recreation():
    cle = DEFINITIONS["tts_viewer"].cle_etat
    api, etat, conf = _api(), _Etat(**{cle: "RW"}), _config()
    g = GestionRecompenses(api, etat, conf)
    assert await g.supprimer("tts_viewer")
    api.supprimer_recompense.assert_awaited_once_with("RW")
    assert etat.v[cle] == ""
    assert conf.twitch.recompenses["tts_viewer"].active is False
    conf.save.assert_called_once()

    await g.armer_au_boot()
    api.creer_recompense.assert_not_awaited()


async def test_une_suppression_refusee_ne_touche_a_rien():
    cle = DEFINITIONS["tts_viewer"].cle_etat
    api, etat, conf = _api(), _Etat(**{cle: "RW"}), _config()
    api.supprimer_recompense = AsyncMock(return_value=False)
    assert not await GestionRecompenses(api, etat, conf).supprimer("tts_viewer")
    assert etat.v[cle] == "RW"
    assert conf.twitch.recompenses["tts_viewer"].active is True


async def test_appliquer_passe_la_recharge_et_la_saisie_du_registre():
    api = _api()
    conf = _config(attaque_meme=RecompenseConfig(titre="A", cout=30000, prompt="x",
                                                 recharge_s=300))
    await GestionRecompenses(api, _Etat(), conf).appliquer("attaque_meme")
    kw = api.creer_recompense.await_args.kwargs
    assert kw["cooldown_s"] == 300
    assert kw["saisie_requise"] is False


async def test_le_duel_passe_par_son_runner_quand_il_existe():
    runner = MagicMock()
    runner.assurer_recompense = AsyncMock(return_value="DUEL")
    conf = _config(duel_apex=RecompenseConfig(titre="D", cout=10000, prompt="p"))
    g = GestionRecompenses(_api(), _Etat(), conf, duel_runner=lambda: runner)
    assert await g.appliquer("duel_apex") == "DUEL"
    runner.assurer_recompense.assert_awaited_once_with("D", 10000, "p", cooldown_s=0)


async def test_une_entree_absente_de_la_config_n_est_pas_armee_en_silence():
    api = _api()
    await GestionRecompenses(api, _Etat(), _config()).armer_au_boot()
    # Seul le TTS est configuré : lui seul est créé.
    assert api.creer_recompense.await_count == 1


@pytest.mark.parametrize("cle", list(DEFINITIONS))
def test_chaque_definition_a_sa_propre_cle_d_etat(cle):
    autres = [d.cle_etat for c, d in DEFINITIONS.items() if c != cle]
    assert DEFINITIONS[cle].cle_etat not in autres


# ── le TTS annonce la hausse ────────────────────────────────────────────────

async def test_le_tts_annonce_la_hausse_dans_le_chat():
    from bot.twitch.events import tts_viewer

    bot = MagicMock()
    bot.recompenses.apres_achat_tts = AsyncMock(return_value=(500, 600))
    bot.twitch_api.send_automatic = AsyncMock()
    await tts_viewer._faire_monter_le_prix(bot)
    texte = bot.twitch_api.send_automatic.await_args.args[0]
    assert "600" in texte


async def test_le_tts_se_tait_si_le_prix_n_a_pas_monte():
    from bot.twitch.events import tts_viewer

    bot = MagicMock()
    bot.recompenses.apres_achat_tts = AsyncMock(return_value=(500, 500))
    bot.twitch_api.send_automatic = AsyncMock()
    await tts_viewer._faire_monter_le_prix(bot)
    bot.twitch_api.send_automatic.assert_not_awaited()
