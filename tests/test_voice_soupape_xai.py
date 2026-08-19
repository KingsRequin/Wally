"""La soupape de débordement passe chez xAI (Grok STT).

1min.ai a été abandonné le 2026-08-19, après une soirée d'observation :

- il HALLUCINE dans une autre langue sur les énoncés courts — 15 lignes de
  chinois et de japonais en 28 min (« 喂喂喂喂。», « それでその人。») dans un
  salon où trois personnes parlaient français. Le paramètre `language` était
  pourtant envoyé : l'API l'ignore, comme elle ignore le contexte de Qwen.
- il rendait des HTTP 502 (5 en 28 min), chacun coûtant un énoncé, sans être
  réessayé.
- il demandait DEUX appels (upload d'asset, puis transcription), dont un
  refusait au hasard un fichier valide sur six.

xAI répond en un seul appel REST, en 812 ms mesurées, force réellement la
langue, rend la chaîne vide sur un silence — et surtout accepte `keyterm`, le
biais de vocabulaire qu'aucun des deux autres candidats n'exposait : le nom
« Wally » ressort correctement au lieu de « Wall-E » ou « ou ali ».

Ces tests verrouillent ce qui a mordu : la langue est imposée, le nom part en
biais, un 5xx est réessayé UNE fois, un 4xx ne l'est jamais, et aucun échec ne
part en silence.
"""
import asyncio

import pytest


class _Rep:
    def __init__(self, status, corps=None, texte=""):
        self.status_code = status
        self._corps = corps
        self.text = texte

    def json(self):
        if self._corps is None:
            raise ValueError("Expecting value: line 1 column 1")
        return self._corps


class _ClientVide:
    """Client qui n'a qu'un rôle : capturer l'appel qu'on lui fait."""

    def attrape(self, stt):
        self.appel = None

        async def post(url, **kw):
            self.appel = kw
            return _Rep(200, {"text": ""})

        client = type("C", (), {"post": staticmethod(post)})()
        asyncio.run(stt._transcrire(client, b"wav"))
        return self.appel


class _Client:
    """Faux client httpx : sert la suite de réponses qu'on lui donne."""

    def __init__(self, suite):
        self.suite = list(suite)
        self.appels: list[dict] = []

    async def post(self, url, **kw):
        self.appels.append({"url": url, **kw})
        return self.suite.pop(0)


def _stt(**kw):
    from bot.discord.voice.providers import XaiSTT

    return XaiSTT(api_key="clé-bidon", **kw)


def _champs(appel) -> list[tuple[str, str]]:
    """Les champs du multipart hors fichier, sous forme (nom, valeur)."""
    return [(nom, val[1]) for nom, val in appel["files"] if nom != "file"]


def test_le_texte_transcrit_est_rendu():
    client = _Client([_Rep(200, {"text": "  elle est où la balle  "})])
    assert asyncio.run(_stt()._transcrire(client, b"wav")) == "elle est où la balle"
    assert len(client.appels) == 1


def test_la_langue_est_IMPOSEE_dans_la_requete():
    """Le défaut qui a fait abandonner 1min.ai : trois francophones transcrits
    en chinois. La langue ne doit pas être une suggestion."""
    client = _Client([_Rep(200, {"text": "ok"})])
    asyncio.run(_stt(language="fr-FR")._transcrire(client, b"wav"))
    assert ("language", "fr") in _champs(client.appels[0])


def test_le_nom_de_wally_part_en_BIAIS():
    """Le moteur local reçoit déjà ces mots en `hotwords`. Sans eux ici, un
    énoncé rattrapé perdait le mot qui décide si Wally est interpellé."""
    client = _Client([_Rep(200, {"text": "ok"})])
    asyncio.run(_stt(phrases=["Wally", "Wallou"])._transcrire(client, b"wav"))
    assert ("keyterm", "Wally") in _champs(client.appels[0])
    assert ("keyterm", "Wallou") in _champs(client.appels[0])


def test_chaque_terme_de_biais_a_son_propre_champ():
    """`keyterm` se répète dans le multipart. Rangé dans un dict, seul le
    dernier terme serait parti — et le nom de Wally aurait pu être celui-là."""
    stt = _stt(phrases=["Wally", "Wallou", "Wall"])
    assert [v for n, v in _champs(_ClientVide().attrape(stt))] .count("Wally") == 1
    assert sum(1 for n, _ in _champs(_ClientVide().attrape(stt)) if n == "keyterm") == 3


def test_les_plafonds_de_l_api_sont_respectes():
    """Cent termes, cinquante caractères chacun : au-delà, l'API refuse tout
    l'appel — et on perdrait l'énoncé pour un surnom de trop."""
    stt = _stt(phrases=["x" * 80] + [f"surnom{i}" for i in range(200)])
    assert len(stt.keyterms) == 100
    assert all(len(k) <= 50 for k in stt.keyterms)


def test_un_surnom_vide_n_entre_pas():
    assert _stt(phrases=["Wally", "", "   ", None]).keyterms == ["Wally"]


def test_un_5xx_est_reessaye_une_fois():
    """5 × HTTP 502 en 28 min chez le précédent fournisseur, chacun coûtant un
    énoncé faute d'être réessayé."""
    client = _Client([_Rep(502, texte="<!DOCTYPE html>"), _Rep(200, {"text": "repêché"})])
    assert asyncio.run(_stt()._transcrire(client, b"wav")) == "repêché"
    assert len(client.appels) == 2


def test_on_n_insiste_pas_au_dela_du_second_essai():
    """Deux 5xx d'affilée, ce n'est plus un aléa : c'est une panne. Insister
    ferait attendre une parole que plus personne n'écoutera."""
    client = _Client([_Rep(503, texte="busy"), _Rep(503, texte="busy")])
    assert asyncio.run(_stt()._transcrire(client, b"wav")) == ""
    assert len(client.appels) == 2


def test_un_4xx_n_est_JAMAIS_reessaye():
    """Une clé invalide ou un fichier refusé ne se répare pas en insistant :
    on paierait une seconde attente pour le même refus."""
    client = _Client([_Rep(401, {"error": {"message": "Invalid API Key"}})])
    assert asyncio.run(_stt()._transcrire(client, b"wav")) == ""
    assert len(client.appels) == 1


def test_une_reponse_non_json_dit_ce_qu_elle_etait():
    """« Expecting value: line 1 column 1 » ne dit pas si c'est une passerelle
    en vrac, un quota, ou un corps vide. Le statut et l'extrait les séparent."""
    from loguru import logger

    client = _Client([_Rep(502, None, texte="<html>Bad Gateway</html>"),
                      _Rep(502, None, texte="<html>Bad Gateway</html>")])
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(m), level="WARNING")
    try:
        assert asyncio.run(_stt()._transcrire(client, b"wav")) == ""
    finally:
        logger.remove(sink)
    trace = "".join(messages)
    assert "502" in trace and "Bad Gateway" in trace


def test_un_wav_valide_est_bien_ce_qui_part():
    """Le pipeline ne manipule que du PCM nu ; l'API veut un fichier."""
    import io
    import wave

    from bot.discord.voice.providers import XaiSTT

    wav = XaiSTT._wav(b"\x00\x01" * 16000)
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000


@pytest.mark.parametrize("bruit", [ConnectionError("réseau"), TimeoutError()])
def test_une_soupape_qui_tombe_ne_casse_jamais_l_ecoute(monkeypatch, bruit):
    """Réseau coupé, DNS en vrac, délai dépassé : l'écoute continue sans elle."""
    import httpx

    class _Explose:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise bruit

    monkeypatch.setattr(httpx, "AsyncClient", _Explose)
    assert asyncio.run(_stt().transcribe(b"\x00" * 3200)) == ""
