"""La borne posée sur le comblement de trous RTP de `discord.ext.voice_recv`.

Le 2026-09-05 à 09:54, Wally a été déplacé de salon vocal pendant qu'il
écoutait le live. Deux minutes plus tard il n'entendait plus rien : 15 frames
réelles reçues en soixante secondes, pour 131 082 frames d'audio INVENTÉ jetées
par le filtre du sink. La bibliothèque comble chaque trou de numérotation RTP
en fabriquant un paquet par paquet manquant — son tampon accepte un saut de dix
mille — et sa boucle de routage, dépourvue d'horloge, les rend aussi vite que
le CPU les produit, en gardant le verrou qui sert aussi à ENFOURNER les paquets
réels. Le remplissage ne fait donc pas que du bruit : il affame la réception.

Le filtre du sink (`_MAX_REMPLISSAGE_CONSECUTIF`) jette ces frames, mais APRÈS
qu'elles ont été fabriquées et décodées. Ces tests portent sur la source.
"""

from __future__ import annotations

import pytest

from bot.discord.voice.rtp_borne import MAX_TROU_COMBLE, poser_la_borne_rtp


class _Paquet:
    """Un paquet RTP réel : véridique au sens booléen, ordonnable (heapq)."""

    def __init__(self, sequence: int) -> None:
        self.sequence = sequence
        self.timestamp = sequence * 960
        self.ssrc = 42

    def __lt__(self, autre) -> bool:
        return self.sequence < autre.sequence

    def __bool__(self) -> bool:
        return True


class _Sink:
    def wants_opus(self) -> bool:
        # Évite d'instancier un décodeur Opus : on ne teste pas le décodage.
        return True


class _Reader:
    analysis_stats = None


class _Router:
    def __init__(self) -> None:
        self.sink = _Sink()
        self.reader = _Reader()


def _decodeur_avec_trou(manquants: int):
    """Un décodeur qui a émis le paquet 2 et tient les paquets d'après le trou.

    `manquants` est le nombre de paquets PERDUS, ce que compte `gap()`.
    Le décodeur rend ensuite le paquet `manquants + 2`.
    """
    from discord.ext.voice_recv.opus import PacketDecoder

    decodeur = PacketDecoder(_Router(), 42)
    # Le tampon ne rend un paquet qu'au-delà de `prefsize` : il en faut deux.
    decodeur._buffer.push(_Paquet(1))
    decodeur._buffer.push(_Paquet(2))
    assert decodeur._get_next_packet(0) is not None
    decodeur._buffer._buffer.clear()
    debut = 1 + manquants + 1
    decodeur._buffer.push(_Paquet(debut))
    decodeur._buffer.push(_Paquet(debut + 1))
    return decodeur


def _jusqu_au_vrai(decodeur, tours: int = 200):
    """(nombre de paquets fabriqués, premier paquet réel ressorti)."""
    faux = 0
    for _ in range(tours):
        paquet = decodeur._get_next_packet(0)
        if paquet is None:
            return faux, None
        if paquet:  # un paquet réel : le trou est franchi
            return faux, paquet
        faux += 1
    return faux, None


def _compter_les_faux(decodeur, tours: int = 200) -> int:
    """Combien de paquets fabriqués sortent avant que le vrai revienne."""
    return _jusqu_au_vrai(decodeur, tours)[0]


@pytest.fixture(autouse=True)
def _borne_posee():
    poser_la_borne_rtp()


def test_un_trou_geant_ne_fabrique_pas_un_paquet_par_manquant():
    """5 000 paquets manquants ne valent pas 5 000 paquets inventés.

    Sans la borne, cette boucle rend 4 999 `FakePacket` — cent secondes d'audio
    d'un seul trait, pour un locuteur qui n'a rien dit.
    """
    decodeur = _decodeur_avec_trou(5000)
    assert _compter_les_faux(decodeur) <= 1


def test_le_vrai_paquet_ressort_apres_le_saut():
    """Sauter le trou ne doit pas faire perdre la parole qui suit."""
    decodeur = _decodeur_avec_trou(5000)
    _faux, paquet = _jusqu_au_vrai(decodeur)
    assert paquet is not None and paquet.sequence == 5002


def test_une_perte_ordinaire_est_toujours_dissimulee():
    """Sous la borne, le comportement de la bibliothèque ne change pas :
    un hoquet réseau de deux paquets se comble toujours frame par frame."""
    decodeur = _decodeur_avec_trou(2)
    assert _compter_les_faux(decodeur) == 2


def test_la_borne_est_idempotente():
    """Deux poses ne doivent pas empiler deux couches de patch."""
    from discord.ext.voice_recv.opus import PacketDecoder

    premiere = PacketDecoder._get_next_packet
    poser_la_borne_rtp()
    assert PacketDecoder._get_next_packet is premiere


def test_la_borne_couvre_une_demi_seconde_au_moins():
    """Une frame vaut 20 ms : la borne doit laisser passer les vraies pertes."""
    assert 10 <= MAX_TROU_COMBLE <= 100
