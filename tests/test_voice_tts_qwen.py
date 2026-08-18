"""La voix d'Arthur, en français forcé, et découpée pour ne pas faire attendre.

Mesuré le 2026-08-18 : Azure sort le premier son en 0,3 s parce qu'il streame ;
Qwen3-TTS-Flash rend un fichier complet, en 3,2 s pour une réplique courte et
4,0 s pour une longue. L'API n'ayant pas de streaming, le seul levier est de
découper le texte : la première phrase se joue pendant que les suivantes se
synthétisent, donc l'attente devient celle d'UNE phrase, pas de tout le texte.

Deux renoncements assumés, verrouillés ici pour qu'ils restent des choix :
le style émotionnel d'Azure n'existe pas chez Qwen (le paramètre est ignoré,
pas mal appliqué), et la langue est TOUJOURS forcée — en « Auto », le modèle se
trompe sur les répliques courtes ou mêlées d'anglais, ce qui décrit à peu près
toutes les phrases d'un salon Apex.
"""
from bot.discord.voice.providers import OneMinTTS


def _tts(**kw):
    return OneMinTTS(api_key="fausse-clé", **kw)


def test_la_langue_est_forcee_jamais_auto():
    assert _tts(language="fr-FR")._langue == "French"
    assert _tts(language="en-US")._langue == "English"


def test_une_langue_inconnue_retombe_sur_le_francais():
    """Ce salon parle français. Un code exotique ne doit pas rendre la main à
    « Auto », qui est précisément le mode qui se trompe."""
    assert _tts(language="xx-YY")._langue == "French"


def test_la_voix_par_defaut_est_arthur():
    assert _tts()._voice == "Arthur"


def test_une_reponse_courte_part_en_un_seul_appel():
    """Découper une réplique de chat en trois appels coûterait plus d'attente
    qu'il n'en ferait gagner."""
    assert _tts()._decouper("Ouais je suis là, qu'est-ce qu'il te faut ?") == [
        "Ouais je suis là, qu'est-ce qu'il te faut ?"
    ]


def test_une_longue_reponse_est_decoupee_en_phrases():
    """Le premier morceau est ce que Wally peut dire tout de suite."""
    texte = ("Alors mensonge non, j'ai les relevés sous les yeux et ils sont formels. "
             "T'es à dix-huit kills depuis le début du stream, ce qui est déjà pas si mal. "
             "Franchement pour une soirée de ranked je trouve que tu t'en sors bien.")
    morceaux = _tts()._decouper(texte)
    assert len(morceaux) >= 2
    assert morceaux[0].startswith("Alors mensonge non")
    assert " ".join(morceaux) == texte, "aucun mot ne doit se perdre au découpage"


def test_les_phrases_tres_courtes_sont_regroupees():
    """Sinon « Ah. Bon. Ok. » ferait trois allers-retours réseau."""
    assert _tts()._decouper("Ah. Bon. Ok.") == ["Ah. Bon. Ok."]


def test_une_phrase_plus_longue_que_la_limite_est_coupee_aux_espaces():
    """L'API refuse au-delà de 600 caractères. Couper au milieu d'un mot
    s'entendrait — la synthèse prononcerait deux moitiés de mot."""
    texte = "mot " * 300  # 1200 caractères sans ponctuation
    morceaux = _tts()._decouper(texte)
    assert all(len(m) <= 600 for m in morceaux)
    assert all(not m.startswith(" ") and "  " not in m for m in morceaux)
    assert "".join(m.replace(" ", "") for m in morceaux) == texte.replace(" ", "")


def test_un_texte_vide_ne_declenche_aucun_appel():
    assert _tts()._decouper("") == []
    assert _tts()._decouper("   ") == []


def test_le_repli_prend_la_main_quand_rien_ne_sort():
    """Muet est le pire symptôme de ce bot : il se croit en train de parler,
    personne ne l'entend, et on cherche ailleurs pendant une heure."""
    import asyncio

    class _Secours:
        def __init__(self):
            self.appele = False

        async def synthesize_stream(self, texte, style, on_chunk):
            self.appele = True
            on_chunk(b"\x01\x02")

    secours = _Secours()
    tts = OneMinTTS(api_key="fausse-clé", secours=secours)
    morceaux = []
    asyncio.run(tts.synthesize_stream("dis quelque chose", None, morceaux.append))

    assert secours.appele, "sans filet, Wally serait resté muet"
    assert morceaux == [b"\x01\x02"]


def test_un_texte_vide_ne_reveille_pas_le_repli():
    """Rien à dire n'est pas une panne : réveiller Azure ici ferait parler Wally
    dans le vide et paierait une synthèse pour du blanc."""
    import asyncio

    class _Secours:
        def __init__(self):
            self.appele = False

        async def synthesize_stream(self, texte, style, on_chunk):
            self.appele = True

    secours = _Secours()
    asyncio.run(OneMinTTS(api_key="k", secours=secours).synthesize_stream("  ", None, lambda c: None))
    assert not secours.appele
