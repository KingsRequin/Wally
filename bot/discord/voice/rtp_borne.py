"""Borne le comblement des trous de numérotation RTP de `discord.ext.voice_recv`.

La bibliothèque dissimule une perte de paquets en fabriquant un `FakePacket`
par paquet manquant. C'est le bon geste pour un hoquet réseau d'un ou deux
paquets. Mais rien ne borne la taille du trou : son tampon accepte un saut de
séquence allant jusqu'à dix mille (`HeapJitterBuffer._threshold`), et la boucle
de `PacketRouter._do_run` — sans horloge, et tenant le verrou qui sert AUSSI à
enfourner les paquets reçus — les rend aussi vite que le CPU les produit.

Un seul saut de séquence coûte donc jusqu'à dix mille frames inventées, soit
deux cents secondes d'audio, en rafale. Vu deux fois en prod :

* 2026-08-28 — 232 s d'audio en une minute au nom d'un locuteur muet, aucune
  transcription. Le filtre du sink (`_MAX_REMPLISSAGE_CONSECUTIF`) a été posé
  ce jour-là : il JETTE ces frames, mais après leur fabrication et leur
  décodage. Il borne la casse, il ne tarit pas la source.
* 2026-09-05 — Wally déplacé de salon vocal pendant le live : deux minutes plus
  tard, 15 frames réelles reçues en soixante secondes contre 131 082 inventées.
  Le remplissage ne fait pas que du bruit, il AFFAME la réception : Wally
  devient sourd sans une seule erreur, et le seul remède était le redémarrage.

Au-delà de la borne, un trou n'est plus une perte à dissimuler : c'est un
décrochage. On le franchit d'un coup, en avançant le curseur du tampon, et un
unique paquet fabriqué suffit à recoller.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

# En frames de 20 ms : une demi-seconde de vraie perte reste dissimulée comme
# avant. Au-delà, plus personne n'entend une reprise crédible — et c'est
# exactement là que la rafale commence.
MAX_TROU_COMBLE = 25

_POSEE = "_wally_borne_rtp"


def _get_next_packet(self: Any, timeout: float = 0) -> Any:
    """Version bornée de `PacketDecoder._get_next_packet`.

    Reprend la sémantique d'origine — un paquet réel s'il est prêt, un paquet
    fabriqué pour combler, rien du tout sinon — en sautant d'un coup les trous
    qui dépassent la borne.
    """
    packet = self._buffer.pop(timeout=timeout)

    if packet is None:
        if self._buffer:
            # `gap()` rend le nombre de paquets MANQUANTS avant le prochain
            # paquet retenu — zéro quand il est déjà séquentiel.
            trou = self._buffer.gap()
            if trou > MAX_TROU_COMBLE:
                # Tout le trou d'un coup : le curseur se pose juste avant le
                # paquet retenu, qui redevient séquentiel. Un unique paquet
                # fabriqué tient lieu de dissimulation pour le décrochage.
                self._buffer.advance(trou)
                logger.info(
                    "voice: trou RTP de {n} paquet(s) SAUTÉ sur le flux {s} "
                    "({d:.0f} s d'audio non inventé)",
                    n=trou, s=self.ssrc, d=trou * 0.02,
                )
                self._stats_inc("jitter_synthetic_packets")
                return self._make_fakepacket()
            if trou > 0:
                self._buffer.advance()
                self._stats_inc("jitter_synthetic_packets")
                return self._make_fakepacket()
        return None

    if not packet:
        packet = self._make_fakepacket()

    return packet


def poser_la_borne_rtp() -> None:
    """Remplace `PacketDecoder._get_next_packet` par sa version bornée.

    Idempotent : une seconde pose ne réempile rien.
    """
    from discord.ext.voice_recv.opus import PacketDecoder

    if getattr(PacketDecoder, _POSEE, False):
        return
    PacketDecoder._get_next_packet = _get_next_packet  # type: ignore[method-assign]
    setattr(PacketDecoder, _POSEE, True)
    logger.info(
        "voice: borne de remplissage RTP posée — un trou de plus de {n} "
        "paquets est sauté, plus comblé frame par frame", n=MAX_TROU_COMBLE,
    )
