"""Le pouls de l'écoute : distinguer trois surdités qui se ressemblent.

« Wally s'arrête de répondre alors qu'on parle normalement. » Vu de l'extérieur,
trois pannes très différentes donnent exactement ce symptôme :

  1. Discord ne descend plus aucun audio (salon, permissions, voice_recv) ;
  2. l'audio descend, mais le VAD ne referme jamais d'énoncé ;
  3. les énoncés partent, et le modèle les rend VIDES.

Aucune des deux premières ne laissait la moindre trace — ni dans les logs, ni
dans le journal vocal. On ne pouvait donc que deviner. Le pouls les sépare :
frames reçues d'un côté, énoncés clos de l'autre.
"""
import threading
from unittest.mock import MagicMock

from bot.discord.voice.sink import WallyAudioSink


def _sink():
    s = WallyAudioSink.__new__(WallyAudioSink)
    s._lock = threading.Lock()
    s._frames_recues = 0
    s._segments_emis = 0
    s._frames_par_locuteur = {}
    return s


def test_le_pouls_compte_ce_qui_entre_et_ce_qui_sort():
    s = _sink()
    s._frames_recues, s._segments_emis = 150, 2
    s._frames_par_locuteur = {7: 150}
    assert s.pouls() == (150, 2, {7: 150})


def test_le_pouls_repart_de_zero_a_chaque_releve():
    """Sinon le relevé serait un cumul depuis l'arrivée dans le salon, et une
    écoute morte depuis dix minutes afficherait encore les frames du début."""
    s = _sink()
    s._frames_recues, s._segments_emis = 150, 2
    s._frames_par_locuteur = {7: 150}
    s.pouls()
    assert s.pouls() == (0, 0, {})


def test_de_l_audio_sans_aucun_enonce_se_voit():
    """La panne du milieu : ça descend, mais rien ne se referme. C'est celle
    qu'on ne pouvait pas distinguer d'un salon vide."""
    s = _sink()
    s._frames_recues = 3000          # une minute d'audio
    s._frames_par_locuteur = {7: 3000}
    assert s.pouls() == (3000, 0, {7: 3000})
