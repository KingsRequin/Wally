"""Ce que le STT local n'a pas le temps de transcrire ne se jette plus.

Ces tests portent sur le PIPELINE : qui part à la soupape, et ce qu'il advient
de ce qu'elle ne peut pas prendre. Le fournisseur lui-même est couvert par
`test_voice_soupape_xai.py`.

Le moteur local traite un énoncé à la fois. Mesuré le 2026-08-18 sur trois
locuteurs simultanés — le cas normal d'un live :

    local : 6,3 s pour trois énoncés (file séquentielle), puis des abandons
    soupape distante : 3,5 s pour les mêmes trois, en parallèle

D'où la borne `_MAX_PENDING_FALLBACK`, qui préférait jeter la parole plutôt que
de la rendre avec trente secondes de retard. Elle avait raison sur le fond :
une réponse hors sujet est pire que pas de réponse. Mais jeter n'était le bon
choix que faute de mieux — et « mieux » existe maintenant.

Ces tests verrouillent le contrat : la parole en trop part à la soupape, et
quand la soupape ne peut pas la prendre, elle est ABANDONNÉE AVEC UNE TRACE.
Jamais avalée en silence.
"""
import array
import asyncio

_ENONCE = array.array("h", [500] * 16000).tobytes()  # 1 s de parole plausible


def _pipeline(overflow=None, inflight_max=8):
    from bot.discord.voice.streaming import RemoteStreamingSTT

    p = RemoteStreamingSTT.__new__(RemoteStreamingSTT)
    p._sessions = {}
    p._fallback_speakers = set()
    p._priority_speakers = set()   # aucun prioritaire : l'aiguillage par profil n'est pas le sujet ici
    p._pending_fallback = 0
    p._detached = set()
    p._ferme = False
    p._overflow = overflow
    p._overflow_max_inflight = inflight_max
    p._overflow_inflight = 0
    p._now = lambda: 0.0
    p.on_final = None
    lances = []
    p._detach = lambda coro: (lances.append(coro), coro.close())
    return p, lances


class _Soupape:
    def __init__(self, texte="rattrapé"):
        self.texte = texte
        self.recus = []

    async def transcribe(self, pcm):
        self.recus.append(pcm)
        return self.texte


def test_l_enonce_en_trop_part_a_la_soupape():
    soupape = _Soupape()
    p, lances = _pipeline(overflow=soupape)
    from bot.discord.voice.streaming import _MAX_PENDING_FALLBACK

    p._pending_fallback = _MAX_PENDING_FALLBACK  # local saturé
    p.speech_end_sync("azrael", _ENONCE)

    assert len(lances) == 1, "l'énoncé doit partir, pas être jeté"
    assert p._overflow_inflight == 1


def test_sans_soupape_on_jette_comme_avant():
    """La soupape est une option. Sans elle, le comportement d'hier — et sa
    trace — doivent être exactement conservés."""
    p, lances = _pipeline(overflow=None)
    from bot.discord.voice.streaming import _MAX_PENDING_FALLBACK

    p._pending_fallback = _MAX_PENDING_FALLBACK
    p.speech_end_sync("azrael", _ENONCE)
    assert lances == []


def test_la_soupape_saturee_rend_la_main():
    """Le réseau n'a pas la file du CPU, mais il a un quota. Au plafond, on
    retombe sur l'abandon journalisé plutôt que d'empiler des appels."""
    soupape = _Soupape()
    p, lances = _pipeline(overflow=soupape, inflight_max=2)
    from bot.discord.voice.streaming import _MAX_PENDING_FALLBACK

    p._pending_fallback = _MAX_PENDING_FALLBACK
    p._overflow_inflight = 2
    p.speech_end_sync("azrael", _ENONCE)
    assert lances == [], "au plafond, la soupape ne prend plus"


def test_le_local_reste_prioritaire():
    """La soupape ne doit PAS court-circuiter le moteur local quand il est
    libre : il est deux fois plus rapide à un seul locuteur (1,3 s contre
    2,6 s). Elle ne sert qu'au débordement."""
    soupape = _Soupape()
    p, lances = _pipeline(overflow=soupape)
    p.speech_end_sync("azrael", _ENONCE)   # file vide
    assert len(lances) == 1
    assert p._overflow_inflight == 0, "c'est le local qui prend, pas la soupape"
    assert p._pending_fallback == 1


def test_le_texte_rattrape_remonte_comme_une_transcription_normale():
    """Sinon la soupape transcrirait dans le vide : le rattrapage n'a de valeur
    que s'il atteint le cerveau par le même chemin que le reste."""
    soupape = _Soupape("salut wally")
    p, _ = _pipeline(overflow=soupape)
    remontes = []

    async def on_final(sid, texte, ms):
        remontes.append((sid, texte))

    p.on_final = on_final
    asyncio.run(p._overflow_transcribe("azrael", _ENONCE))

    assert remontes == [("azrael", "salut wally")]
    assert p._overflow_inflight == 0, "la place doit être rendue"


def test_une_soupape_qui_echoue_rend_sa_place():
    """Sans ce décrément garanti, quelques erreurs réseau fermeraient la soupape
    définitivement — la panne exacte déjà vue sur `_pending_fallback`."""
    class _Cassee:
        async def transcribe(self, pcm):
            raise RuntimeError("réseau")

    p, _ = _pipeline(overflow=_Cassee())
    p._overflow_inflight = 1
    try:
        asyncio.run(p._overflow_transcribe("azrael", _ENONCE))
    except RuntimeError:
        pass
    assert p._overflow_inflight == 0


def test_le_plancher_s_applique_avant_la_soupape():
    """On ne paie pas un appel réseau pour du souffle : la porte de
    `est_sous_le_plancher` est en amont des DEUX moteurs."""
    soupape = _Soupape()
    p, lances = _pipeline(overflow=soupape)
    from bot.discord.voice.streaming import _MAX_PENDING_FALLBACK

    p._pending_fallback = _MAX_PENDING_FALLBACK
    p.speech_end_sync("azrael", array.array("h", [30] * 6400).tobytes())  # 0,4 s, rms 30
    assert lances == []



def test_un_fragment_court_mais_audible_ne_consomme_pas_de_place_payante():
    """Le plancher local (0,3 s) laisse passer ce que le moteur local sait
    rendre — mesuré, son plus court énoncé transcrit tient en 0,4 s. La soupape
    PAYANTE, elle, rend du vide sur ces durées : 40 succès sur 6 297 appels
    sous 0,5 s (logs d'août). Ces fragments occupaient les places et affamaient
    les énoncés de 2–5 s, qui réussissaient à 77 %.

    On vérifie donc le CONTRAT, pas le seuil : un fragment audible mais trop
    court n'atteint jamais le fournisseur et ne prend aucune place en vol."""
    soupape = _Soupape()
    p, lances = _pipeline(overflow=soupape)

    # 0,4 s à rms 500 : au-dessus du plancher local, sous celui de la soupape.
    fragment = array.array("h", [500] * 6400).tobytes()
    assert p._deborder("azrael", fragment) is False
    assert soupape.recus == []
    assert p._overflow_inflight == 0
    assert lances == []


def test_un_enonce_assez_long_passe_toujours_a_la_soupape():
    """Garde-fou du garde-fou : le plancher de la soupape ne doit pas se
    refermer sur ce qu'elle transcrit correctement. Sans ce test, monter la
    constante par mégarde couperait le chemin sans qu'aucun test ne bronche."""
    soupape = _Soupape()
    p, lances = _pipeline(overflow=soupape)

    assert p._deborder("azrael", _ENONCE) is True   # 1 s
    assert p._overflow_inflight == 1
    assert len(lances) == 1
