"""À qui va quel moteur de transcription, et dans quel ordre.

Trois moteurs, aux qualités inverses :

- le **GPU distant** (le PC du créateur) transcrit au fil de l'eau et rend le
  meilleur texte, mais ne tient que DEUX locuteurs — une limite de VRAM.
- le **local** (`small` sur CPU) est gratuit et toujours là, mais traite un
  énoncé à la fois et rend un français approximatif.
- **xAI** est rapide et sans file, mais payant à la seconde.

L'ordre décidé par l'owner le 2026-08-19 découle de la rareté du GPU : ses deux
places vont à ceux à qui Wally doit répondre, et les autres ne viennent les
prendre que si le local ne suit plus.

    Azraël et KingsRequin :  GPU → xAI
    les autres            :  local → GPU → xAI

Avant, TOUT LE MONDE ouvrait une session GPU au premier qui parlait, et les
prioritaires devaient déloger un invité pour récupérer leur place — le défaut
du 2026-08-14 (cf. `test_voice_stt_priorite.py`), traité en aval au lieu de
l'être à la source.
"""
import array
from unittest.mock import MagicMock

import pytest

from bot.discord.voice.streaming import _MAX_PENDING_FALLBACK, RemoteStreamingSTT

AZRAEL = "419172225451556874"     # streamer — prioritaire
REQUIN = "610550333042589752"     # créateur — prioritaire
XEFORCE = "432140002109947904"    # invité
TAKI = "528237220327325720"       # invité

_ENONCE = array.array("h", [500] * 16000).tobytes()   # 1 s de parole plausible


@pytest.fixture(autouse=True)
def _pas_de_taches(monkeypatch):
    """Les tâches détachées ne sont pas le sujet : on observe l'aiguillage."""
    import bot.discord.voice.streaming as mod
    monkeypatch.setattr(mod.asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1])


class _Soupape:
    """xAI, vue du pipeline."""

    def __init__(self):
        self.recus = []

    async def transcribe(self, pcm):
        self.recus.append(pcm)
        return "rattrapé"


def _voies(mgr) -> list[str]:
    """Les moteurs réellement sollicités, dans l'ordre.

    Lu sur le nom des coroutines détachées : les lancer pour de vrai
    demanderait une boucle asyncio, et ce qu'on vérifie ici est l'AIGUILLAGE.
    """
    return ["xai" if "overflow" in n else "local" for n in mgr.voies]


def _manager(occupees=(), *, prioritaires=(AZRAEL, REQUIN), places=2,
             soupape=None, en_file=0):
    mgr = RemoteStreamingSTT(
        "ws://stt.test",
        fallback=MagicMock(),
        max_connections=places,
        session_factory=lambda sid: MagicMock(name=f"sess:{sid}", ready=True),
        priority_speakers=set(prioritaires),
        overflow=soupape,
    )
    for sid in occupees:
        mgr._sessions[sid] = MagicMock(name=f"sess:{sid}", ready=True)
    mgr._pending_fallback = en_file
    mgr.voies = []
    mgr._detach = lambda coro: (mgr.voies.append(coro.__qualname__), coro.close())[0]
    return mgr


# --- À l'ouverture de la parole : qui tente le GPU ---------------------------

def test_un_invite_ne_prend_PAS_de_place_gpu_quand_le_local_suit():
    """Les deux places sont rares. Un invité qui parle pendant que le local est
    libre n'a aucune raison d'en occuper une — c'est ce qui obligeait ensuite
    Azraël à l'en déloger."""
    mgr = _manager()

    mgr.feed_sync(XEFORCE, b"audio")

    assert XEFORCE not in mgr._sessions
    assert XEFORCE in mgr._fallback_speakers


def test_un_invite_monte_sur_le_gpu_quand_le_local_est_sature():
    """C'est l'escalade demandée : le local ne suit plus, la place libre sert."""
    mgr = _manager(en_file=_MAX_PENDING_FALLBACK)

    mgr.feed_sync(XEFORCE, b"audio")

    assert XEFORCE in mgr._sessions
    assert XEFORCE not in mgr._fallback_speakers


def test_un_prioritaire_prend_le_gpu_meme_local_libre():
    """Lui n'attend pas que le local sature : le GPU est son premier choix."""
    mgr = _manager()

    mgr.feed_sync(AZRAEL, b"audio")

    assert AZRAEL in mgr._sessions


def test_sans_liste_de_prioritaires_le_gpu_reste_au_premier_qui_parle():
    """La politique existe pour PROTÉGER les places des prioritaires. Sans
    personne à protéger, envoyer tout le monde au local laisserait le GPU
    inutilisé — une installation sans `voice.requesters` ne doit rien perdre."""
    mgr = _manager(prioritaires=())

    mgr.feed_sync(XEFORCE, b"audio")

    assert XEFORCE in mgr._sessions


# --- À la fin de la parole : qui rattrape quoi -------------------------------

def test_un_prioritaire_sans_gpu_va_chez_xai_PAS_au_local():
    """Le local lui rendait « Biri birip » et « Sous-titrage ST' 501 » : ses
    demandes n'atteignaient plus personne. Quand le GPU manque, il vaut mieux
    payer trois centimes que ne pas être compris."""
    soupape = _Soupape()
    mgr = _manager(soupape=soupape)
    mgr._fallback_speakers.add(AZRAEL)      # pas de session distante

    mgr.speech_end_sync(AZRAEL, _ENONCE)

    assert _voies(mgr) == ["xai"], "l'énoncé du streamer doit partir chez xAI"
    assert mgr._pending_fallback == 0, "il ne doit pas occuper la file locale"


def test_un_prioritaire_retombe_sur_le_local_si_xai_ne_peut_pas_prendre():
    """Filet : mieux vaut un texte approximatif que rien. La soupape peut être
    absente (pas de clé) ou saturée."""
    mgr = _manager(soupape=None)
    mgr._fallback_speakers.add(AZRAEL)

    mgr.speech_end_sync(AZRAEL, _ENONCE)

    assert _voies(mgr) == ["local"]
    assert mgr._pending_fallback == 1


def test_un_invite_passe_par_le_local_avant_xai():
    """L'inverse du prioritaire : chez lui le local est le premier choix, et
    xAI ne sert qu'au débordement. Pas de raison de payer pour un invité tant
    que la machine suit."""
    soupape = _Soupape()
    mgr = _manager(soupape=soupape)
    mgr._fallback_speakers.add(XEFORCE)

    mgr.speech_end_sync(XEFORCE, _ENONCE)

    assert _voies(mgr) == ["local"]
    assert mgr._pending_fallback == 1


def test_un_invite_part_chez_xai_quand_le_local_deborde():
    soupape = _Soupape()
    mgr = _manager(soupape=soupape, en_file=_MAX_PENDING_FALLBACK)
    mgr._fallback_speakers.add(XEFORCE)

    mgr.speech_end_sync(XEFORCE, _ENONCE)

    assert _voies(mgr) == ["xai"], "le débordement doit être rattrapé"


def test_le_plancher_s_applique_aussi_aux_prioritaires():
    """Du souffle reste du souffle : on ne le paie pas chez xAI sous prétexte
    qu'il vient du streamer."""
    soupape = _Soupape()
    mgr = _manager(soupape=soupape)
    mgr._fallback_speakers.add(AZRAEL)

    mgr.speech_end_sync(AZRAEL, array.array("h", [30] * 6400).tobytes())  # 0,4 s, rms 30

    assert _voies(mgr) == [], "rien ne doit être transcrit"
    assert mgr._pending_fallback == 0
