"""Quand Wally n'entend plus, ça se VOIT : il se coupe le micro.

Demande de l'owner : « ajouter des indications à Wally — si le STT crash, le
mute sur Discord pour le signaler, qu'on puisse le voir ».

Le signal existait déjà pour le démarrage : Wally reste muet tant que le modèle
STT chauffe, et se démute quand une transcription à blanc a traversé toute la
chaîne. Ce lot étend le même geste à la panne — muet veut dire « je n'entends
pas », quelle qu'en soit la raison.

La détection se fonde sur le POULS de l'écoute, ajouté en diagnostiquant la
surdité intermittente : des énoncés se referment (donc des gens parlent, et le
VAD les découpe) mais AUCUN ne ressort transcrit. C'est la signature d'un STT
mort — le distant injoignable et le repli local en échec.

⚠️ Ne PAS confondre avec un salon silencieux : sans énoncé, il n'y a rien à
transcrire, et se couper le micro annoncerait une panne qui n'existe pas.
"""
import pytest

from bot.discord.voice.service import verdict_ecoute


def test_des_enonces_sans_aucune_transcription_c_est_la_surdite():
    assert verdict_ecoute(enonces=12, transcriptions=0, deja_signale=False) == "sourd"


def test_un_salon_silencieux_n_est_pas_une_panne():
    """Personne ne parle : il n'y a rien à transcrire. Se couper le micro
    annoncerait une panne qui n'existe pas — et l'annonce perdrait tout sens le
    jour où il y en a vraiment une."""
    assert verdict_ecoute(enonces=0, transcriptions=0, deja_signale=False) is None


def test_une_ecoute_qui_marche_ne_dit_rien():
    assert verdict_ecoute(enonces=12, transcriptions=9, deja_signale=False) is None


def test_la_panne_ne_se_re_signale_pas_a_chaque_releve():
    """Sinon Wally se couperait le micro toutes les minutes, et le journal
    répéterait la même ligne toute la soirée."""
    assert verdict_ecoute(enonces=12, transcriptions=0, deja_signale=True) is None


def test_le_retour_de_l_ecoute_est_annonce():
    """Le rétablissement compte autant que la panne : un micro qui reste coupé
    après le retour du STT ferait croire à une panne qui n'est plus là."""
    assert verdict_ecoute(enonces=5, transcriptions=3, deja_signale=True) == "retabli"


def test_le_silence_ne_retablit_pas_a_lui_seul():
    """Un salon qui se tait ne prouve pas que l'écoute est revenue : sans
    énoncé, on n'a aucune preuve dans un sens ni dans l'autre."""
    assert verdict_ecoute(enonces=0, transcriptions=0, deja_signale=True) is None


@pytest.mark.asyncio
async def test_le_micro_se_coupe_et_se_retablit_pour_de_vrai():
    """Le bout du chemin : c'est le micro Discord que l'owner regarde, pas un
    log. Ce test vérifie le geste, pas seulement la décision."""
    from unittest.mock import AsyncMock, MagicMock

    from bot.discord.voice import service as mod

    appels = []

    async def _faux_mute(vc, muted):
        appels.append(muted)

    monkeypatched = MagicMock()
    monkeypatched.is_connected.return_value = True

    svc = mod.VoiceService.__new__(mod.VoiceService)
    svc._vc = monkeypatched
    svc._surdite_signalee = False

    import bot.discord.voice.readiness as readiness
    origine = readiness.set_muted
    readiness.set_muted = _faux_mute
    try:
        await svc._signaler_ecoute(enonces=12, transcriptions=0)
        await svc._signaler_ecoute(enonces=12, transcriptions=0)   # pas deux fois
        await svc._signaler_ecoute(enonces=8, transcriptions=6)    # rétabli
    finally:
        readiness.set_muted = origine

    assert appels == [True, False]
    assert svc._surdite_signalee is False
