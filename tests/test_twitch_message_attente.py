"""Sur Twitch, une réponse lente ressemble à un silence.

Discord affiche « Wally écrit… ». Le chat Twitch n'a pas d'équivalent : passé
quelques secondes, le viewer voit du vide et conclut qu'il est ignoré, puis la
réponse tombe dans un fil qui a déjà défilé. Mesuré sur 1 407 réponses de
juillet-août 2026 : 12,6 % dépassent 5 s, et le p99 est à 12,5 s.

Une phrase brève part alors, chaînée à son message. Elle ne promet rien de
précis — à cet instant Wally ne sait pas encore ce qu'il va répondre, et il lui
arrive de conclure qu'il n'a pas l'information.
"""
import asyncio
from unittest.mock import MagicMock

import pytest

from bot.twitch import handlers as H


@pytest.fixture(autouse=True)
def _etat_propre():
    """Le cooldown et les sacs vivent au niveau module : sans ce nettoyage, un
    test hériterait du cooldown posé par le précédent et passerait pour de
    mauvaises raisons."""
    H._attente_derniere.clear()
    H._attente_sacs.clear()
    yield
    H._attente_derniere.clear()
    H._attente_sacs.clear()


def _bot(seuil=0.05, phrases=("attends une seconde",)):
    bot = MagicMock()
    bot.config.twitch.attente_seuil_s = seuil
    bot.persona.attente_phrases = list(phrases)
    return bot


@pytest.fixture
def _envoi(monkeypatch):
    """Intercepte la sortie Twitch : rien ne doit partir en vrai."""
    envoye = []

    async def _faux(bot, channel_name, texte, *, author, parent_msg_id):
        envoye.append({"canal": channel_name, "texte": texte, "author": author,
                       "parent": parent_msg_id})
        return "helix"

    monkeypatch.setattr(H, "_envoyer_reponse_twitch", _faux)
    monkeypatch.setattr(H, "_clog", MagicMock())
    return envoye


async def _cycle(bot, *, duree_reponse: float) -> None:
    """Rejoue le motif exact de `handle_message` : armer, générer, désarmer.

    Le `finally` en fait partie — c'est lui qui garantit qu'une panne du LLM ne
    laisse pas partir un « deux secondes » que rien ne suivra.
    """
    tache = H._armer_attente(bot, "azrael_ttv", author="jubeii",
                             parent_msg_id="msg-1", trace="t1")
    try:
        await asyncio.sleep(duree_reponse)
    finally:
        await H._desarmer_attente(tache)


# --- la course entre la réponse et le seuil ---------------------------------


async def test_une_reponse_rapide_ne_previent_de_rien(_envoi):
    """Le cas courant — 87 % des réponses. Un signal ici serait du bruit."""
    await _cycle(_bot(seuil=0.2), duree_reponse=0.01)

    assert _envoi == []


async def test_une_reponse_lente_previent_avant_de_repondre(_envoi):
    await _cycle(_bot(seuil=0.02), duree_reponse=0.15)

    assert len(_envoi) == 1
    assert _envoi[0]["texte"] == "attends une seconde"
    # Chaîné au message de l'intéressé : dans un chat qui défile, une phrase
    # d'attente non rattachée ne s'adresse visiblement à personne.
    assert _envoi[0]["author"] == "jubeii"
    assert _envoi[0]["parent"] == "msg-1"


async def test_une_panne_du_llm_ne_laisse_pas_partir_la_phrase(_envoi):
    """Sinon Wally annonce « deux secondes » et ne dit plus jamais rien."""
    bot = _bot(seuil=0.02)
    tache = H._armer_attente(bot, "azrael_ttv", author="jubeii",
                             parent_msg_id=None, trace="t1")
    try:
        raise RuntimeError("LLM tombé")
    except RuntimeError:
        pass
    finally:
        await H._desarmer_attente(tache)

    assert _envoi == []


async def test_rien_ne_part_plus_apres_le_desarmement(_envoi):
    """Le contrat de `_desarmer_attente` : à son retour, la tâche est résolue.

    Ce qui est vérifiable ici, c'est qu'aucune phrase ne sort APRÈS lui — une
    phrase publiée derrière la réponse serait pire que le silence qu'on
    cherchait à combler. Le `await tache` du désarmement sert aussi de point de
    synchronisation dans le cas limite où l'envoi est déjà en vol ; ce cas-là,
    ce test ne le distingue pas, et il ne prétend pas le faire.
    """
    bot = _bot(seuil=0.05)
    tache = H._armer_attente(bot, "azrael_ttv", author="jubeii",
                             parent_msg_id=None, trace="t1")
    await asyncio.sleep(0.01)          # la réponse arrive avant le seuil
    await H._desarmer_attente(tache)

    assert tache.done()
    await asyncio.sleep(0.15)          # bien au-delà du seuil
    assert _envoi == []


# --- ce qui éteint la fonction ----------------------------------------------


async def test_un_seuil_a_zero_eteint_la_fonction(_envoi):
    assert H._armer_attente(_bot(seuil=0), "azrael_ttv", author="a",
                            parent_msg_id=None, trace="t") is None
    assert _envoi == []


async def test_un_seuil_illisible_eteint_la_fonction_sans_lever(_envoi):
    """Un `attente_seuil_s: null` en YAML ne doit pas casser le chat.

    `.get(clé, défaut)` ne couvre pas `clé: null` — piège déjà payé ailleurs.
    """
    bot = _bot()
    bot.config.twitch.attente_seuil_s = None
    assert H._armer_attente(bot, "azrael_ttv", author="a",
                            parent_msg_id=None, trace="t") is None

    bot.config.twitch.attente_seuil_s = "beaucoup"
    assert H._armer_attente(bot, "azrael_ttv", author="a",
                            parent_msg_id=None, trace="t") is None


async def test_un_fichier_de_phrases_vide_eteint_la_fonction(_envoi):
    """Vider ATTENTE.md est une façon légitime de couper la fonctionnalité."""
    await _cycle(_bot(seuil=0.02, phrases=()), duree_reponse=0.15)

    assert _envoi == []


# --- ne pas inonder le chat -------------------------------------------------


async def test_deux_reponses_lentes_rapprochees_ne_previennent_qu_une_fois(_envoi):
    """Le garde est par CANAL : c'est le chat qui serait spammé si cinq
    questions lentes tombaient ensemble."""
    bot = _bot(seuil=0.02)
    await asyncio.gather(
        _cycle(bot, duree_reponse=0.15),
        _cycle(bot, duree_reponse=0.15),
        _cycle(bot, duree_reponse=0.15),
    )

    assert len(_envoi) == 1


async def test_deux_chats_differents_ne_se_bloquent_pas(_envoi):
    """Le cooldown d'une chaîne invitée ne doit pas faire taire la maison."""
    bot = _bot(seuil=0.02)
    for canal in ("azrael_ttv", "keychka"):
        tache = H._armer_attente(bot, canal, author="jubeii",
                                 parent_msg_id=None, trace="t")
        await asyncio.sleep(0.15)
        await H._desarmer_attente(tache)

    assert {e["canal"] for e in _envoi} == {"azrael_ttv", "keychka"}


# --- la phrase n'est pas un tour de parole ----------------------------------


async def test_la_phrase_n_entre_ni_en_memoire_ni_au_prelude(_envoi):
    """Même statut que « Wally écrit… » sur Discord : un artefact d'interface.

    L'injecter au contexte encombrerait chaque prompt suivant d'un « deux
    secondes » sans contenu, et Wally pourrait s'y référer comme à une promesse.
    """
    bot = _bot(seuil=0.02)
    bot.memory = MagicMock()
    bot.memory.append_prelude = MagicMock()
    bot.memory.append_message = MagicMock()

    await _cycle(bot, duree_reponse=0.15)

    assert len(_envoi) == 1
    bot.memory.append_prelude.assert_not_called()
    bot.memory.append_message.assert_not_called()


async def test_la_phrase_ne_pose_ni_cooldown_ni_question_ouverte(_envoi):
    """Wally n'a pas encore répondu : rien ne doit se comporter comme s'il l'avait fait."""
    bot = _bot(seuil=0.02)
    bot.set_cooldown = MagicMock()

    await _cycle(bot, duree_reponse=0.15)

    bot.set_cooldown.assert_not_called()


# --- les phrases elles-mêmes ------------------------------------------------


async def test_les_phrases_ne_se_repetent_pas_avant_epuisement(_envoi):
    """« Un message aléatoire pour ne pas faire de répétition » : un sac, pas un
    tirage avec remise."""
    bot = _bot(seuil=0.02, phrases=tuple(f"phrase {i}" for i in range(5)))
    H._attente_sacs.clear()
    sorties = [H._phrase_attente(bot, "azrael_ttv") for _ in range(5)]

    assert sorted(sorties) == sorted(f"phrase {i}" for i in range(5))


async def test_chaque_canal_a_son_propre_sac(_envoi):
    """Un sac partagé ferait que deux chats se renvoient l'écho, et le
    sans-remise ne voudrait plus rien dire vu de chacun."""
    bot = _bot(phrases=("une", "deux"))
    a = H._phrase_attente(bot, "azrael_ttv")
    b = H._phrase_attente(bot, "keychka")

    assert a is not None and b is not None
    assert H._attente_sacs.keys() == {"azrael_ttv", "keychka"}


async def test_les_phrases_sont_relues_apres_un_reload_persona(_envoi):
    """Bind-mount + /reload-persona : éditer ATTENTE.md ne doit pas demander de
    redémarrage."""
    bot = _bot(phrases=("ancienne",))
    assert H._phrase_attente(bot, "azrael_ttv") == "ancienne"

    bot.persona.attente_phrases = ["nouvelle"]
    assert H._phrase_attente(bot, "azrael_ttv") == "nouvelle"


def test_le_fichier_livre_porte_les_deux_registres():
    """ATTENTE.md est éditorial, mais deux invariants comptent : il existe, et
    il est assez fourni pour qu'une phrase ne revienne pas dans la soirée."""
    from bot.intelligence.persona import PersonaService

    phrases = PersonaService().attente_phrases

    assert len(phrases) >= 50, "trop peu de phrases : la répétition se verrait"
    # Aucune consigne de rédaction ne doit avoir fui du préambule vers le chat.
    assert not [p for p in phrases if p.startswith(">") or len(p) > 120]


async def test_la_phrase_ne_promet_pas_de_chercher_quelque_chose():
    """À l'instant où elle part, Wally ne sait pas encore ce qu'il va répondre —
    il lui arrive de conclure qu'il n'a pas l'info. « Je vais te chercher ça »
    suivi de « j'ai pas le relevé » est pire que le silence."""
    from bot.intelligence.persona import PersonaService

    interdits = ("je vais chercher", "je te sors", "je te trouve",
                 "je vais te dire le", "je regarde dans")
    fautives = [p for p in PersonaService().attente_phrases
                if any(mot in p.lower() for mot in interdits)]

    assert not fautives, f"phrases qui promettent un résultat : {fautives}"
