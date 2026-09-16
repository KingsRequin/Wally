"""Chaque morceau TTS est une COPIE du tampon de lecture.

`AzureTTS._stream_sync` relit le flux Azure dans un tampon réutilisé ; une
tranche pleine `chunk[:n]` d'un `bytes` rend le MÊME objet. Un appelant qui
GARDE les morceaux (`synthesize`, donc le banc STT) recevait N fois le dernier
— du silence, 16 échantillons du banc synthétisés muets le 2026-09-16.
"""
from unittest.mock import MagicMock, patch

from bot.discord.voice.providers import AzureTTS


class _Flux:
    """Écrit dans le tampon fourni, comme le SDK (qui ignore l'immuabilité)."""

    def __init__(self, blocs):
        self._blocs = list(blocs)

    def read_data(self, tampon):
        if not self._blocs:
            return 0
        bloc = self._blocs.pop(0)
        import ctypes
        ctypes.memmove(ctypes.c_char_p(tampon), bloc, len(bloc))
        return len(bloc)


def test_les_morceaux_gardes_ne_sont_pas_ecrases_par_la_lecture_suivante():
    tts = AzureTTS.__new__(AzureTTS)
    tts._key, tts._region, tts._voice, tts._secours = "k", "r", "fr-FR-HenriNeural", None
    blocs = [b"\x01" * 3840, b"\x02" * 3840, b"\x03" * 100]
    faux_sdk = MagicMock()
    faux_sdk.AudioDataStream.return_value = _Flux(blocs)
    gardes: list[bytes] = []
    with patch("bot.discord.voice.providers.speechsdk", faux_sdk):
        tts._stream_sync("salut", None, gardes.append)
    assert gardes == [b"\x01" * 3840, b"\x02" * 3840, b"\x03" * 100]
