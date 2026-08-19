"""La voix MAI a un filet, parce que son quota peut tomber sans prévenir.

La ressource Azure est en SKU **F0** : Azure n'y facture jamais, il BLOQUE une
fois le quota atteint. Or les voix MAI se comptent en tokens et ne sont PAS
couvertes par les 500 000 caractères gratuits du neural standard — c'est
précisément le motif du repli sur Henri décidé le 2026-08-07.

Le jour où ça tombe, le symptôme est le pire du bot : il entend, décide, génère
sa réplique, joue son bip, et aucun son ne sort. Vécu le 2026-08-07, une soirée
entière. Le SDK Azure n'aide pas — il ne lève pas, il rend un flux VIDE.

Ces tests verrouillent deux choses : le filet existe pour les voix MAI, et le
style est RAMENÉ aux capacités de la voix de secours. Sans cette adaptation, le
repli serait muet à son tour — Henri ne connaît ni `softvoice` ni `angry`, et
un `express-as` inconnu fait échouer la synthèse.
"""
import asyncio

from bot.discord.voice.providers import AzureTTS


class _Muette(AzureTTS):
    """Une voix qui ne rend rien — le cas du quota tombé."""

    def _stream_sync(self, text, style, on_chunk):
        return None


class _Sonore(AzureTTS):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.recu = []

    def _stream_sync(self, text, style, on_chunk):
        self.recu.append((text, style))
        on_chunk(b"\x01\x02")


def test_une_voix_muette_bascule_sur_le_secours():
    secours = _Sonore(key="k", region="r", voice="fr-FR-HenriNeural")
    voix = _Muette(key="k", region="r", voice="fr-FR-Marc:MAI-Voice-2-Flash", secours=secours)
    morceaux = []
    asyncio.run(voix.synthesize_stream("dis quelque chose", "cheerful", morceaux.append))

    assert morceaux == [b"\x01\x02"], "sans filet, Wally serait resté muet"


def test_le_style_est_ramene_aux_capacites_du_secours():
    """`softvoice` existe chez Marc, pas chez Henri. Le passer tel quel ferait
    échouer la synthèse de secours — muet pour la raison qu'on rattrapait."""
    secours = _Sonore(key="k", region="r", voice="fr-FR-HenriNeural")
    voix = _Muette(key="k", region="r", voice="fr-FR-Marc:MAI-Voice-2-Flash", secours=secours)
    asyncio.run(voix.synthesize_stream("bah", "softvoice", lambda c: None))

    _texte, style = secours.recu[0]
    from bot.discord.voice.style import supported_styles

    assert style in supported_styles("fr-FR-HenriNeural"), f"style {style!r} inconnu d'Henri"


def test_une_voix_qui_parle_n_appelle_pas_le_secours():
    secours = _Sonore(key="k", region="r", voice="fr-FR-HenriNeural")
    voix = _Sonore(key="k", region="r", voice="fr-FR-Marc:MAI-Voice-2-Flash", secours=secours)
    asyncio.run(voix.synthesize_stream("salut", "angry", lambda c: None))
    assert secours.recu == []


def test_un_texte_vide_ne_reveille_pas_le_secours():
    secours = _Sonore(key="k", region="r", voice="fr-FR-HenriNeural")
    voix = _Muette(key="k", region="r", voice="fr-FR-Marc:MAI-Voice-2-Flash", secours=secours)
    asyncio.run(voix.synthesize_stream("   ", None, lambda c: None))
    assert secours.recu == []


def test_le_filet_est_pose_pour_une_voix_mai(monkeypatch):
    from bot.config import VoiceConfig
    from bot.discord.voice import providers

    monkeypatch.setattr(providers, "_azure_creds", lambda: ("k", "r"))
    tts = providers.build_tts(VoiceConfig(azure_voice="fr-FR-Marc:MAI-Voice-2-Flash"))
    assert tts._secours is not None
    assert ":MAI-Voice-" not in tts._secours._voice, "le secours doit être couvert par le F0"


def test_pas_de_filet_pour_une_voix_deja_couverte(monkeypatch):
    """Adosser Henri à Henri n'apporterait rien et masquerait une vraie panne
    derrière un second essai identique."""
    from bot.config import VoiceConfig
    from bot.discord.voice import providers

    monkeypatch.setattr(providers, "_azure_creds", lambda: ("k", "r"))
    tts = providers.build_tts(VoiceConfig(azure_voice="fr-FR-HenriNeural"))
    assert tts._secours is None
