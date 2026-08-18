"""Ce que le STT local n'a pas le temps de transcrire ne se jette plus.

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


def test_une_reponse_non_json_dit_ce_qu_elle_etait():
    """Vu en prod le soir même : « Expecting value: line 1 column 1 » remontait
    par l'attrape-tout, et l'énoncé était perdu sans qu'on sache pourquoi. Une
    passerelle qui rend du HTML, un 429 et un corps vide sont trois pannes
    différentes — le statut et l'extrait du corps les séparent."""
    from bot.discord.voice.providers import OneMinSTT

    class _Rep:
        status_code = 502
        text = "<html>Bad Gateway</html>"

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    messages = []
    from loguru import logger

    sink = logger.add(lambda m: messages.append(m), level="WARNING")
    try:
        assert OneMinSTT._corps(_Rep(), "upload") == {}
    finally:
        logger.remove(sink)

    trace = "".join(messages)
    assert "502" in trace and "Bad Gateway" in trace and "upload" in trace


def test_un_upload_refuse_au_hasard_est_reessaye():
    """Mesuré en rafale sur un fichier identique et valide : ~1 upload sur 6
    repart en « The file may be corrupt », sans rapport avec la durée. Sept
    énoncés perdus en une soirée pour un aléa serveur."""
    import asyncio

    from bot.discord.voice.providers import OneMinSTT

    class _Rep:
        def __init__(self, ok):
            self.status_code = 200 if ok else 400
            self._corps = ({"fileContent": {"path": "audios/ok.wav"}} if ok
                           else {"errorCode": "UNKNOWN_ERROR",
                                 "message": "The file may be corrupt."})

        def json(self):
            return self._corps

    class _Client:
        def __init__(self, suite):
            self.suite = list(suite)
            self.appels = 0

        async def post(self, *a, **kw):
            self.appels += 1
            return _Rep(self.suite.pop(0))

    stt = OneMinSTT(api_key="k")
    client = _Client([False, True])          # refus puis succès
    assert asyncio.run(stt._televerser(client, b"wav")) == "audios/ok.wav"
    assert client.appels == 2


def test_on_n_insiste_pas_au_dela_du_second_essai():
    """Deux refus d'affilée, ce n'est plus un aléa : c'est une panne. Insister
    ferait attendre une parole que plus personne n'écoutera."""
    import asyncio

    from bot.discord.voice.providers import OneMinSTT

    class _Rep:
        status_code = 400

        def json(self):
            return {"errorCode": "UNKNOWN_ERROR"}

    class _Client:
        appels = 0

        async def post(self, *a, **kw):
            _Client.appels += 1
            return _Rep()

    client = _Client()
    assert asyncio.run(OneMinSTT(api_key="k")._televerser(client, b"wav")) == ""
    assert client.appels == 2
