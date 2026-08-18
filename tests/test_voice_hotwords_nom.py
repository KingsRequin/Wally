"""Le modèle local doit savoir que « Wally » est un mot.

Sans indice, il rend son nom en « Oali », « Oeli », « Allie » — en live c'était
« Wadi », « Wali », « Weli », « Wallier ». La garde du nom (`address_match`) ne
peut rien pour ça : « wadi » est à trois corrections de « wally », exactement
comme « wait », « what » ou « when ». Élargir la tolérance ferait répondre Wally
à l'anglais courant, dont ce salon est plein. Le raté se joue donc AVANT, au
décodage.

`voice.phrases` (nom du bot + déclencheurs, cf. `VoiceService.__init__`) portait
déjà cet indice pour Azure, et était IGNORÉ par le moteur local depuis toujours.

Mesuré par `scripts/bench_stt.py` sur les phrases réellement ratées en live :
4/8 appels entendus sans, 8/8 avec, zéro faux déclenchement, zéro bavardage sur
du bruit, débit inchangé.

Ces tests portent sur le CONTRAT — l'indice part au moteur, et il vient de la
config — jamais sur la valeur des mots : elle appartient à `config.yaml`.
"""
from bot.discord.voice.providers import FasterWhisperSTT


def test_le_nom_est_souffle_au_moteur():
    stt = FasterWhisperSTT(phrases=["Wally", "wal"])
    assert "Wally" in (stt._hotwords or "")


def test_sans_phrases_aucun_indice():
    """Pas de biais inventé quand la config n'en donne pas : `None`, et non une
    chaîne vide, que faster-whisper traiterait comme un prompt à part entière."""
    assert FasterWhisperSTT()._hotwords is None
    assert FasterWhisperSTT(phrases=[])._hotwords is None
    assert FasterWhisperSTT(phrases=["", None])._hotwords is None


def test_l_indice_atteint_vraiment_la_transcription():
    """Le point où ça se joue. Le paramètre existait déjà côté Azure et n'était
    jamais transmis ici — un réglage qu'on croit posé et qui n'atteint pas le
    moteur ne se voit dans aucun test qui s'arrête au constructeur."""
    recu = {}

    class _FauxModele:
        def transcribe(self, audio, **kw):
            recu.update(kw)
            return ([], None)

    stt = FasterWhisperSTT(phrases=["Wally"])
    stt._model = _FauxModele()
    stt._transcribe_sync(b"\x01\x02" * 8000)

    assert recu["hotwords"] == "Wally"
    # L'autre voie du même prompt reste fermée : c'est elle qui hallucinait.
    assert recu["initial_prompt"] is None
    assert recu["vad_filter"] is True


def test_un_indice_explicite_prime_sur_la_config():
    """Ce que `scripts/bench_stt.py` utilise pour comparer les réglages sans
    toucher au chemin de production."""
    stt = FasterWhisperSTT(phrases=["Wally"], hotwords="Azraël")
    assert stt._hotwords == "Azraël"
