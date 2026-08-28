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
import time
from unittest.mock import MagicMock

from bot.discord.voice.sink import WallyAudioSink


def _sink():
    s = WallyAudioSink.__new__(WallyAudioSink)
    s._lock = threading.Lock()
    s._frames_recues = 0
    s._segments_emis = 0
    s._frames_par_locuteur = {}
    # Les frames JETÉES par le plafond de débit. Elles comptent au relevé :
    # un flot qu'on écarte en silence est un flot qu'on ne diagnostique jamais.
    s._frames_jetees = {}
    s._fenetre_debut = {}
    s._fenetre_frames = {}
    s._now = time.monotonic
    return s


def test_le_pouls_compte_ce_qui_entre_et_ce_qui_sort():
    s = _sink()
    s._frames_recues, s._segments_emis = 150, 2
    s._frames_par_locuteur = {7: 150}
    assert s.pouls() == (150, 2, {7: 150}, {})


def test_le_pouls_repart_de_zero_a_chaque_releve():
    """Sinon le relevé serait un cumul depuis l'arrivée dans le salon, et une
    écoute morte depuis dix minutes afficherait encore les frames du début."""
    s = _sink()
    s._frames_recues, s._segments_emis = 150, 2
    s._frames_par_locuteur = {7: 150}
    s.pouls()
    assert s.pouls() == (0, 0, {}, {})


def test_de_l_audio_sans_aucun_enonce_se_voit():
    """La panne du milieu : ça descend, mais rien ne se referme. C'est celle
    qu'on ne pouvait pas distinguer d'un salon vide."""
    s = _sink()
    s._frames_recues = 3000          # une minute d'audio
    s._frames_par_locuteur = {7: 3000}
    assert s.pouls() == (3000, 0, {7: 3000}, {})


# ── Le plafond de débit par locuteur ────────────────────────────────────────
#
# Vécu le 2026-08-28 en plein live : UN locuteur a délivré 8 261 secondes
# d'audio en soixante — 137 fois le maximum physique d'un client Discord —
# pendant vingt minutes, sans qu'un seul énoncé en sorte transcrit. Le décodage
# a saturé le CPU du conteneur, et toutes les écritures en base ont commencé à
# échouer. Une panne de vocal avait emporté la mémoire et la facturation.

def test_un_debit_normal_passe_entierement():
    """50 frames par seconde, c'est ce qu'un locuteur produit. Rien ne doit
    tomber — un plafond qui coupe de la parole réelle est pire que pas de
    plafond."""
    s = _sink()
    horloge = {"t": 0.0}
    s._now = lambda: horloge["t"]
    jetees = sum(s._depasse_le_plafond(7) for _ in range(50))
    assert jetees == 0


def test_au_dela_du_plafond_on_jette_et_on_le_compte():
    from bot.discord.voice.sink import _MAX_FRAMES_PAR_SECONDE

    s = _sink()
    horloge = {"t": 0.0}
    s._now = lambda: horloge["t"]
    total = _MAX_FRAMES_PAR_SECONDE + 300
    jetees = sum(s._depasse_le_plafond(7) for _ in range(total))
    assert jetees == 300
    # Et ça se VOIT au relevé, sinon on écarterait un flot sans jamais savoir
    # qu'il existe.
    assert s.pouls()[3] == {7: 300}


def test_la_fenetre_se_rouvre_a_la_seconde_suivante():
    """Le plafond borne un DÉBIT, pas un total : un locuteur qui parle deux
    minutes ne doit pas être coupé à la première seconde."""
    from bot.discord.voice.sink import _MAX_FRAMES_PAR_SECONDE

    s = _sink()
    horloge = {"t": 0.0}
    s._now = lambda: horloge["t"]
    for _ in range(_MAX_FRAMES_PAR_SECONDE):
        s._depasse_le_plafond(7)
    assert s._depasse_le_plafond(7) is True
    horloge["t"] = 1.5
    assert s._depasse_le_plafond(7) is False


def test_un_locuteur_qui_deborde_nempeche_pas_les_autres_de_parler():
    """LE point du plafond PAR locuteur. Un seul client fautif ne doit pas
    rendre Wally sourd à tout le salon."""
    from bot.discord.voice.sink import _MAX_FRAMES_PAR_SECONDE

    s = _sink()
    horloge = {"t": 0.0}
    s._now = lambda: horloge["t"]
    for _ in range(_MAX_FRAMES_PAR_SECONDE + 500):
        s._depasse_le_plafond(7)
    assert s._depasse_le_plafond(9) is False
