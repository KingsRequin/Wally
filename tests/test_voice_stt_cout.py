"""Ce qu'on dépense en transcription distante est ÉCRIT, pas estimé.

Jusqu'ici le coût du STT distant n'existait que dans des extrapolations faites
à la main sur les logs (« ~1,50 $/mois si… »). Or l'API rend `duration` à
chaque appel, et `cost_log` attendait déjà en base — il ne manquait que la
ligne qui relie les deux.

Deux pièges verrouillés ici :

- **on paie l'audio traité, pas le texte rendu.** Un énoncé qui revient vide a
  quand même été calculé et facturé. Ne compter que les réussites minorerait la
  facture, et c'est justement le cas qu'on veut voir grossir si le moteur
  déraille.
- **le tarif vient de la config**, pas du code : celui de DeepSeek a doublé du
  jour au lendemain le 2026-08-16, et personne ne redéploie une image pour ça.
"""
import asyncio


class _Rep:
    def __init__(self, corps, statut=200):
        self.status_code = statut
        self._corps = corps
        self.text = ""

    def json(self):
        return self._corps


class _Client:
    def __init__(self, rep):
        self._rep = rep

    async def post(self, url, **kw):
        return self._rep


class _DB:
    def __init__(self, casse=False):
        self.lignes = []
        self._casse = casse

    async def log_cost(self, **kw):
        if self._casse:
            raise RuntimeError("base indisponible")
        self.lignes.append(kw)


def _stt(**kw):
    from bot.discord.voice.providers import XaiSTT

    return XaiSTT(api_key="clé-bidon", **kw)


def test_une_transcription_ecrit_ce_qu_elle_a_coute():
    db = _DB()
    stt = _stt(db=db, usd_per_hour=0.10)
    client = _Client(_Rep({"text": "salut", "duration": 3.6}))

    asyncio.run(stt._transcrire(client, b"wav"))

    assert len(db.lignes) == 1
    ligne = db.lignes[0]
    assert ligne["cost_usd"] == 0.10 * 3.6 / 3600
    assert "stt" in ligne["purpose"]


def test_un_enonce_rendu_VIDE_est_quand_meme_facture():
    """L'audio a été traité : le fournisseur le compte, nous aussi. C'est même
    la dépense la plus utile à voir — celle qui n'a rien rapporté."""
    db = _DB()
    stt = _stt(db=db, usd_per_hour=0.10)
    client = _Client(_Rep({"text": "", "duration": 2.0}))

    asyncio.run(stt._transcrire(client, b"wav"))

    assert len(db.lignes) == 1
    assert db.lignes[0]["cost_usd"] > 0


def test_un_refus_ne_coute_rien():
    db = _DB()
    stt = _stt(db=db, usd_per_hour=0.10)
    client = _Client(_Rep({"error": {"message": "Invalid API Key"}}, statut=401))

    asyncio.run(stt._transcrire(client, b"wav"))

    assert db.lignes == []


def test_le_tarif_vient_de_la_config():
    db = _DB()
    stt = _stt(db=db, usd_per_hour=0.20)
    client = _Client(_Rep({"text": "ok", "duration": 3600.0}))

    asyncio.run(stt._transcrire(client, b"wav"))

    assert db.lignes[0]["cost_usd"] == 0.20


def test_une_base_muette_ne_coute_PAS_l_enonce():
    """Écrire la dépense est un confort ; transcrire est la mission."""
    stt = _stt(db=_DB(casse=True), usd_per_hour=0.10)
    client = _Client(_Rep({"text": "salut", "duration": 1.0}))

    assert asyncio.run(stt._transcrire(client, b"wav")) == "salut"


def test_sans_base_rien_ne_change():
    stt = _stt(usd_per_hour=0.10)
    client = _Client(_Rep({"text": "salut", "duration": 1.0}))

    assert asyncio.run(stt._transcrire(client, b"wav")) == "salut"


def test_une_reponse_sans_duree_n_invente_pas_de_montant():
    """Pas de `duration`, pas de facture : on ne devine pas ce qu'on paie."""
    db = _DB()
    stt = _stt(db=db, usd_per_hour=0.10)
    client = _Client(_Rep({"text": "salut"}))

    asyncio.run(stt._transcrire(client, b"wav"))

    assert db.lignes == []
