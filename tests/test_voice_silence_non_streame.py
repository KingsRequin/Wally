"""On n'envoie plus le silence au serveur STT distant.

Ce que ses propres logs disaient, le 2026-08-17 :

    Processing audio with duration 00:14.912 / VAD filter removed 00:14.912
    Processing audio with duration 00:24.992 / VAD filter removed 00:24.992
    Processing audio with duration 01:03.616 / VAD filter removed 01:03.616
    RealTimeSTT - WARNING - Audio queue size exceeds latency limit.
    Current size: 167. Discarding old audio chunks.

Cent quatre secondes d'audio **intégralement silencieuses** avalées entre deux
prises de parole, et une file qui monte à 167. Le serveur cesse alors de
répondre aux pings, la session meurt sur `keepalive ping timeout`, le client
rouvre — et se heurte à « limite de 2 connexions atteinte », l'ancienne place
n'étant pas encore rendue. C'est la boucle de « crash » que décrit l'owner.

La cause tient en une ligne : le sink relayait TOUTES les frames de 20 ms au
distant, sans jamais demander son avis au VAD local — alors qu'il l'interroge
juste après pour découper les énoncés. Discord ne coupe le silence que si
l'émetteur le fait ; un micro ouvert sur un ventilateur, et le flux ne s'arrête
jamais.

Le PRÉ-ROLL est la contrepartie obligatoire : le VAD ne reconnaît la parole
qu'après coup, et couper net l'aurait amputée de son attaque — « Wally » devenu
« ally ». On garde donc les dernières frames de silence sous le coude, et on les
envoie quand la parole commence.
"""
import threading

import pytest

from bot.discord.voice.sink import _PREROLL_FRAMES, WallyAudioSink


def _sink():
    s = WallyAudioSink.__new__(WallyAudioSink)
    s._lock = threading.Lock()
    s._preroll = {}
    s._relaye = {}
    return s


def _f(n: int) -> bytes:
    """Une frame reconnaissable à son numéro."""
    return bytes([n % 256]) * 4


def test_le_silence_ne_part_pas():
    """Le cas qui saturait le serveur : personne ne parle, rien ne doit partir."""
    s = _sink()
    envoye = [s._frames_a_relayer(1, _f(i), en_parole=False) for i in range(50)]
    assert all(e == () for e in envoye)


def test_la_parole_part():
    s = _sink()
    s._frames_a_relayer(1, _f(0), en_parole=True)          # attaque
    suite = s._frames_a_relayer(1, _f(1), en_parole=True)
    assert suite == (_f(1),)


def test_l_attaque_du_mot_n_est_pas_coupee():
    """Le VAD ne reconnaît la parole qu'APRÈS coup. Sans pré-roll, la première
    syllabe partirait à la poubelle avec le silence qui la précède."""
    s = _sink()
    for i in range(10):                                     # du silence avant
        s._frames_a_relayer(1, _f(i), en_parole=False)
    envoye = s._frames_a_relayer(1, _f(99), en_parole=True)
    assert envoye[-1] == _f(99)                             # la frame parlée
    assert len(envoye) == 11                                # + les 10 retenues
    assert envoye[0] == _f(0)                               # dans l'ordre


def test_le_preroll_est_borne():
    """Sinon une heure de silence partirait d'un coup au premier mot — ce qui
    est exactement le défaut qu'on corrige, en pire."""
    s = _sink()
    for i in range(500):
        s._frames_a_relayer(1, _f(i), en_parole=False)
    envoye = s._frames_a_relayer(1, _f(99), en_parole=True)
    assert len(envoye) == _PREROLL_FRAMES + 1


def test_le_preroll_ne_se_rejoue_pas_pendant_la_parole():
    """Il ne sert qu'à la transition. Rejoué à chaque frame, il enverrait
    l'audio en double et décalerait tout l'énoncé."""
    s = _sink()
    for i in range(10):
        s._frames_a_relayer(1, _f(i), en_parole=False)
    s._frames_a_relayer(1, _f(99), en_parole=True)
    assert s._frames_a_relayer(1, _f(98), en_parole=True) == (_f(98),)


def test_chaque_locuteur_a_son_propre_preroll():
    """Deux personnes dans le salon : l'attaque de l'une ne doit pas emporter le
    silence de l'autre."""
    s = _sink()
    for i in range(5):
        s._frames_a_relayer(1, _f(i), en_parole=False)
    envoye = s._frames_a_relayer(2, _f(200), en_parole=True)
    assert envoye == (_f(200),)


def test_un_nouveau_mot_rouvre_le_preroll():
    """Après un silence, la parole qui reprend doit à nouveau être précédée de
    son attaque — sinon seul le premier mot d'une conversation serait complet."""
    s = _sink()
    s._frames_a_relayer(1, _f(1), en_parole=True)
    for i in range(5):
        s._frames_a_relayer(1, _f(10 + i), en_parole=False)
    envoye = s._frames_a_relayer(1, _f(99), en_parole=True)
    assert len(envoye) == 6                                 # 5 retenues + la parlée
