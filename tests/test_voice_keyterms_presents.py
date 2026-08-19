"""Le STT distant apprend les noms des gens qui sont dans le salon.

xAI accepte cent termes de biais ; on lui en donnait UN, « Wally ». Or les
pseudos sont des noms propres inventés qu'aucun modèle ne peut deviner, et ce
sont précisément les mots qui portent le sens dans une conversation à
plusieurs — « Azraël, à gauche ! » ne veut rien dire si « Azraël » sort en
« as râler ».

Ils ne peuvent pas être figés à la construction : les gens entrent et sortent
du salon toute la soirée, alors que le provider, lui, est construit une fois au
démarrage du service. La liste est donc RELUE à chaque transcription.
"""
import asyncio


class _Rep:
    status_code = 200

    @staticmethod
    def json():
        return {"text": "ok"}


class _Client:
    def __init__(self):
        self.appels = []

    async def post(self, url, **kw):
        self.appels.append(kw)
        return _Rep()


def _termes(appel) -> list[str]:
    return [val[1] for nom, val in appel["files"] if nom == "keyterm"]


def _stt(**kw):
    from bot.discord.voice.providers import XaiSTT

    return XaiSTT(api_key="clé-bidon", **kw)


def test_les_presents_s_ajoutent_au_nom_du_bot():
    stt = _stt(phrases=["Wally"], extra_terms=lambda: ["Azraël", "Iron d'aile"])
    client = _Client()
    asyncio.run(stt._transcrire(client, b"wav"))
    assert _termes(client.appels[0]) == ["Wally", "Azraël", "Iron d'aile"]


def test_la_liste_est_RELUE_a_chaque_enonce():
    """Le provider vit toute la soirée ; le salon se vide et se remplit."""
    salon = ["Azraël"]
    stt = _stt(phrases=["Wally"], extra_terms=lambda: list(salon))
    client = _Client()
    asyncio.run(stt._transcrire(client, b"wav"))
    salon.append("Rina")
    asyncio.run(stt._transcrire(client, b"wav"))
    assert _termes(client.appels[0]) == ["Wally", "Azraël"]
    assert _termes(client.appels[1]) == ["Wally", "Azraël", "Rina"]


def test_le_nom_du_bot_n_est_JAMAIS_evince_par_les_presents():
    """Cent places, et c'est le nom de Wally qui décide s'il est interpellé :
    il passe devant, quel que soit le nombre de gens dans le salon."""
    stt = _stt(phrases=["Wally"], extra_terms=lambda: [f"invite{i}" for i in range(150)])
    client = _Client()
    asyncio.run(stt._transcrire(client, b"wav"))
    envoyes = _termes(client.appels[0])
    assert envoyes[0] == "Wally"
    assert len(envoyes) == 100


def test_un_present_qui_porte_deja_le_nom_du_bot_ne_double_pas():
    stt = _stt(phrases=["Wally"], extra_terms=lambda: ["wally", "Rina"])
    client = _Client()
    asyncio.run(stt._transcrire(client, b"wav"))
    assert _termes(client.appels[0]) == ["Wally", "Rina"]


def test_une_source_qui_leve_ne_coute_PAS_l_enonce():
    """Le salon peut disparaître entre deux énoncés (kick, coupure). Perdre la
    parole pour un biais optionnel serait absurde."""
    def _cassee():
        raise RuntimeError("plus de salon")

    stt = _stt(phrases=["Wally"], extra_terms=_cassee)
    client = _Client()
    assert asyncio.run(stt._transcrire(client, b"wav")) == "ok"
    assert _termes(client.appels[0]) == ["Wally"]


def test_sans_source_le_comportement_ne_change_pas():
    stt = _stt(phrases=["Wally"])
    client = _Client()
    asyncio.run(stt._transcrire(client, b"wav"))
    assert _termes(client.appels[0]) == ["Wally"]
