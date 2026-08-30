"""Les messages vocaux Discord arrivaient comme des messages VIDES.

Désir écrit par Wally lui-même le 2026-08-20 : « les gens m'en envoient et je ne
peux rien en faire ». C'était pire — un vocal est une pièce jointe `audio/ogg`
au `content` vide, il n'arrivait donc pas comme un média illisible mais comme
un message vide. Wally ne savait même pas qu'on lui avait parlé.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.core import message_vocal
from bot.core.message_vocal import (
    DUREE_MAX_S, TAILLE_MAX_OCTETS, duree_annoncee, marqueur, piece_jointe_vocale,
)


def _piece(content_type="audio/ogg", duration=5.0, size=20000, donnees=b"ogg"):
    piece = MagicMock()
    piece.content_type = content_type
    piece.duration = duration
    piece.size = size
    piece.read = AsyncMock(return_value=donnees)
    return piece


def _message(*pieces):
    return SimpleNamespace(attachments=list(pieces), content="")


@pytest.fixture(autouse=True)
def _moteur_neuf():
    """Le moteur STT est un singleton de module : sans ça, un test en garde un
    d'un autre."""
    message_vocal._stt = None
    yield
    message_vocal._stt = None


# ── Reconnaître le son ────────────────────────────────────────────────────


def test_une_piece_jointe_audio_est_reconnue():
    piece = _piece()
    assert piece_jointe_vocale(_message(piece)) is piece


def test_un_mp3_depose_compte_aussi():
    """On ne se limite pas au drapeau `MessageFlags.voice` : un fichier audio
    glissé dans le salon pose exactement le même problème."""
    piece = _piece(content_type="audio/mpeg")
    assert piece_jointe_vocale(_message(piece)) is piece


def test_une_image_n_est_pas_du_son():
    assert piece_jointe_vocale(_message(_piece(content_type="image/png"))) is None


def test_un_message_sans_piece_jointe():
    assert piece_jointe_vocale(SimpleNamespace(attachments=[])) is None


# ── La durée ──────────────────────────────────────────────────────────────


def test_la_duree_vient_de_discord_quand_il_la_donne():
    assert duree_annoncee(_piece(duration=12.5)) == 12.5


def test_sans_duree_annoncee_on_ne_devine_PAS():
    """Estimer sur la taille serait faux : un `.mp3` à 128 kbit/s pèse quatre
    fois un Opus à 32, et un vocal de 20 s se ferait rejeter comme s'il en
    durait 80. `None` veut dire « on ne sait pas », jamais « c'est court »."""
    assert duree_annoncee(_piece(duration=None, size=40000)) is None


def test_une_duree_illisible_vaut_ne_pas_savoir():
    assert duree_annoncee(_piece(duration="beaucoup")) is None


async def test_un_fichier_sans_duree_est_transcrit_quand_meme():
    """Le seul verdict sûr se lit après décodage — refuser faute de durée
    annoncée rejetterait tous les `.mp3`."""
    with patch.object(message_vocal, "transcrire", AsyncMock(return_value="coucou")):
        contexte, nu = await marqueur(_message(_piece(duration=None)), MagicMock())

    assert nu == "coucou"


async def test_un_fichier_trop_lourd_n_est_pas_telecharge():
    piece = _piece(duration=None, size=TAILLE_MAX_OCTETS + 1)

    contexte, nu = await marqueur(_message(piece), MagicMock())

    assert "trop lourd" in contexte
    piece.read.assert_not_awaited()


async def test_la_duree_EXACTE_est_relue_apres_decodage():
    """Le décodage est bon marché, la transcription non : c'est là qu'on
    abandonne, sur la durée réelle plutôt qu'une devinette."""
    moteur = MagicMock()
    moteur.transcribe = AsyncMock(return_value="jamais appelé")
    trop_long = b"\x00" * int(2 * 16000 * (DUREE_MAX_S + 10))
    with patch.object(message_vocal, "_en_pcm", AsyncMock(return_value=trop_long)), \
         patch.object(message_vocal, "_moteur", AsyncMock(return_value=moteur)):
        texte = await message_vocal.transcrire(_piece(duration=None), MagicMock())

    assert texte == ""
    moteur.transcribe.assert_not_awaited()


# ── Le marqueur : trois sorties, trois vérités ────────────────────────────


async def test_la_transcription_entre_dans_le_contexte():
    with patch.object(message_vocal, "transcrire", AsyncMock(return_value="salut Wally")):
        contexte, nu = await marqueur(_message(_piece()), MagicMock())

    assert contexte == "[message vocal] salut Wally"
    assert nu == "salut Wally"


async def test_un_vocal_trop_long_est_annonce_avec_sa_duree():
    """Quatre minutes d'attente ne sont pas une réponse ; « un vocal de 240 s »
    est une information que Wally peut donner."""
    transcrire = AsyncMock()
    with patch.object(message_vocal, "transcrire", transcrire):
        contexte, nu = await marqueur(_message(_piece(duration=DUREE_MAX_S + 180)), MagicMock())

    assert "240 s" in contexte and "trop long" in contexte
    assert nu == ""
    transcrire.assert_not_awaited()        # on ne paie pas le calcul


async def test_un_vocal_inintelligible_le_dit_au_lieu_de_disparaitre():
    with patch.object(message_vocal, "transcrire", AsyncMock(return_value="")):
        contexte, nu = await marqueur(_message(_piece()), MagicMock())

    assert "message vocal" in contexte and nu == ""


async def test_pile_au_plafond_on_transcrit_encore():
    with patch.object(message_vocal, "transcrire", AsyncMock(return_value="ok")) as t:
        await marqueur(_message(_piece(duration=DUREE_MAX_S)), MagicMock())

    t.assert_awaited_once()


async def test_sans_vocal_rien_n_est_ajoute():
    assert await marqueur(_message(_piece(content_type="image/png")), MagicMock()) == ("", "")


# ── Le décodage et les replis ─────────────────────────────────────────────


async def test_le_son_est_decode_avant_d_etre_transcrit():
    """`FasterWhisperSTT` attend du PCM 16 kHz mono ; Discord envoie de l'Opus."""
    moteur = MagicMock()
    moteur.transcribe = AsyncMock(return_value="bonjour")
    with patch.object(message_vocal, "_en_pcm", AsyncMock(return_value=b"\x00" * 32000)), \
         patch.object(message_vocal, "_moteur", AsyncMock(return_value=moteur)):
        texte = await message_vocal.transcrire(_piece(), MagicMock())

    assert texte == "bonjour"
    assert moteur.transcribe.await_args[0][0] == b"\x00" * 32000


async def test_un_decodage_rate_ne_fait_pas_tomber_le_message():
    with patch.object(message_vocal, "_en_pcm", AsyncMock(return_value=b"")):
        assert await message_vocal.transcrire(_piece(), MagicMock()) == ""


async def test_un_telechargement_rate_ne_fait_pas_tomber_le_message():
    piece = _piece()
    piece.read.side_effect = RuntimeError("Discord ne répond pas")

    assert await message_vocal.transcrire(piece, MagicMock()) == ""


async def test_un_moteur_en_panne_ne_fait_pas_tomber_le_message():
    with patch.object(message_vocal, "_en_pcm", AsyncMock(return_value=b"\x00" * 32000)), \
         patch.object(message_vocal, "_moteur", AsyncMock(side_effect=RuntimeError("pas de modèle"))):
        assert await message_vocal.transcrire(_piece(), MagicMock()) == ""


async def test_le_modele_n_est_charge_qu_une_fois():
    """Deux vocaux simultanés chargeraient deux fois le modèle et doubleraient
    la mémoire."""
    import asyncio

    cfg = MagicMock()
    with patch("bot.discord.voice.providers.FasterWhisperSTT") as classe:
        classe.return_value = MagicMock()
        await asyncio.gather(*[message_vocal._moteur(cfg) for _ in range(4)])

    assert classe.call_count == 1


# ── Le câblage : la transcription doit ATTEINDRE le déclenchement ─────────


def test_le_handler_declenche_sur_le_texte_transcrit():
    """`message.content` d'un vocal est VIDE : sans la transcription dans le
    contenu qui décide, « Wally, tu peux… » dit à l'oral n'interpellerait
    personne."""
    import inspect

    from bot.discord import handlers

    source = inspect.getsource(handlers.handle_message)
    assert "_texte_vocal" in source
    assert 'content_lower = f"{message.content} {_texte_vocal}".lower()' in source


def test_la_cognition_percoit_le_contenu_enrichi():
    """Elle recevait `message.content` — donc un message VIDE quand quelqu'un
    parlait."""
    import inspect

    from bot.discord import handlers

    source = inspect.getsource(handlers.handle_message)
    assert "content=_context_content," in source
