"""« Deux vérités, un mensonge » — et le cloisonnement de ce que Wally invente.

Le test qui compte est celui du CLOISONNEMENT : un mensonge qui entre en base
n'en ressort jamais, et la réconciliation lui donnerait même raison contre le
vrai fait. Le reste du jeu peut échouer bruyamment sans dommage ; ça, non.
"""
import asyncio
import json

import pytest

from bot.core import fiction
from bot.tools import deux_verites as dv


@pytest.fixture(autouse=True)
def _fiction_propre():
    """Le registre vit au niveau module : sans ça, un test en contamine un autre."""
    fiction._ECHEANCES.clear()
    yield
    fiction._ECHEANCES.clear()


# ── Le registre ────────────────────────────────────────────────────────────

def test_une_fiction_ouverte_se_voit():
    fiction.ouvrir("canal-7")
    assert fiction.en_cours("canal-7")


def test_une_fiction_ne_deborde_pas_sur_les_autres_canaux():
    """Une partie sur Twitch ne doit pas rendre Wally amnésique dans un salon
    Discord au même moment."""
    fiction.ouvrir("canal-7")
    assert not fiction.en_cours("canal-8")


def test_une_fiction_fermee_rouvre_la_memoire():
    fiction.ouvrir("canal-7")
    fiction.fermer("canal-7")
    assert not fiction.en_cours("canal-7")


def test_une_fiction_oubliee_expire_delle_meme(monkeypatch):
    """LE filet. Une fiction qu'on oublie de fermer ne se voit pas : Wally
    continue de parler et cesse seulement d'APPRENDRE, en silence, pour
    toujours. L'échéance rend la panne impossible plutôt que rare."""
    faux = [1000.0]
    monkeypatch.setattr(fiction.time, "monotonic", lambda: faux[0])
    fiction.ouvrir("canal-7", duree_s=60)
    faux[0] = 1059.0
    assert fiction.en_cours("canal-7")
    faux[0] = 1061.0
    assert not fiction.en_cours("canal-7")
    # ET purgée : sinon un canal joué une fois resterait dans le dict à vie.
    assert "canal-7" not in fiction._ECHEANCES


def test_un_canal_vide_nest_jamais_en_fiction():
    """`channel_id` est vide sur plusieurs chemins d'appel. Le traiter comme un
    canal ouvrirait une fiction globale que personne ne fermerait."""
    fiction.ouvrir("")
    assert not fiction.en_cours("")
    assert fiction._ECHEANCES == {}


# ── La garde, là où elle mord vraiment ─────────────────────────────────────

# La fenêtre glissante telle qu'elle arrive vraiment : `append_prelude` y a
# déposé la réplique de WALLY, et c'est elle que le LLM d'analyse lit. Sans ce
# contexte, `process_message` n'appelle même pas le modèle — le test aurait
# traversé un chemin qui n'est pas celui du défaut.
_FENETRE = [{"author": "Wally", "content": "Alice a un chat nommé Neige"}]


def _moteur(monkeypatch):
    """Un `EmotionEngine` réel dont SEUL l'appel au LLM est simulé.

    Un `object.__new__` aurait suffi à faire passer le test — et n'aurait rien
    prouvé : la garde vit au milieu de `process_message`, après l'application
    des deltas et l'apprentissage des mots. C'est ce parcours-là qu'on veut
    traverser.
    """
    from unittest.mock import AsyncMock, MagicMock

    from bot.core.emotion import EmotionEngine

    config = MagicMock()
    cfg = MagicMock(decay_lambda=0.1, boredom_rise_per_hour=0.1)
    config.emotions = {e: cfg for e in
                       ("anger", "joy", "sadness", "curiosity", "boredom")}
    config.bot.emotion_inertia_factor = 0.5
    config.bot.emotion_peak_threshold = 0.7
    config.emotional_memory.decay_lambda_per_day = 0.5
    db = MagicMock()
    db.fetch_all = AsyncMock(return_value=[])
    moteur = EmotionEngine(config, db=db)

    async def _analyse(*a, **k):
        return ({e: 0.0 for e in ("anger", "joy", "sadness", "curiosity", "boredom")},
                [], 0.0, 0.0, ["Alice a un chat nommé Neige"])

    monkeypatch.setattr(moteur, "_analyze_llm", _analyse)
    monkeypatch.setattr(moteur, "_openai", object(), raising=False)
    # Le priming se lit dans une config qui est ici un MagicMock : on court-
    # circuite la préparation des deltas, pas le chemin qui nous intéresse — la
    # garde vit APRÈS, juste avant le `return`.
    monkeypatch.setattr(moteur, "prepare_deltas", lambda *a, **k: {})
    return moteur


async def test_les_faits_sont_ecartes_pendant_une_fiction(monkeypatch):
    """Le chemin de fuite RÉEL, mesuré : `context_messages` est la fenêtre
    glissante du canal, où `append_prelude` dépose les répliques de Wally. Le
    LLM d'analyse les voit et les rend en `user_facts`, qui part droit en
    `memory.add(source="post_process")`.
    """
    moteur = _moteur(monkeypatch)
    fiction.ouvrir("canal-7")
    rendu = await moteur.process_message("coucou", context_messages=_FENETRE,
                                         channel_id="canal-7",
                                         platform="twitch", user_id="42")
    assert rendu["user_facts"] == []


async def test_hors_fiction_les_faits_passent_comme_avant(monkeypatch):
    """Le pendant du test précédent. Sans lui, une garde qui écarterait TOUT
    passerait pour un succès — et Wally n'apprendrait plus jamais rien."""
    moteur = _moteur(monkeypatch)
    rendu = await moteur.process_message("coucou", context_messages=_FENETRE,
                                         channel_id="canal-7",
                                         platform="twitch", user_id="42")
    assert rendu["user_facts"] == ["Alice a un chat nommé Neige"]


async def test_la_garde_ne_regarde_que_le_canal_du_jeu(monkeypatch):
    """Une partie sur un canal ne doit pas suspendre l'apprentissage ailleurs."""
    moteur = _moteur(monkeypatch)
    fiction.ouvrir("canal-7")
    rendu = await moteur.process_message("coucou", context_messages=_FENETRE,
                                         channel_id="canal-8",
                                         platform="twitch", user_id="42")
    assert rendu["user_facts"] == ["Alice a un chat nommé Neige"]


# ── L'outil ────────────────────────────────────────────────────────────────

class _Narrateur:
    def __init__(self, actif=True, accepte=True):
        self._actif, self._accepte = actif, accepte
        self.sondage = None
        self.annonces = []

    def is_active(self):
        return self._actif

    def start_poll(self, question, options, seconds=45):
        if not self._accepte:
            return False
        self.sondage = (question, list(options), seconds)
        return True

    def annoncer_fin(self, genre, fait):
        self.annonces.append((genre, fait))


class _Memory:
    def __init__(self, prelude, faits=""):
        self._prelude, self._faits = prelude, faits

    def get_prelude(self, canal):
        return list(self._prelude)

    async def get_all(self, platform, user_id):
        return self._faits


class _Db:
    def __init__(self, users):
        self._users = users

    async def list_memory_users(self, *a, **k):
        return list(self._users)


class _Llm:
    def __init__(self, rendu):
        self._rendu = rendu

    async def complete(self, *a, **k):
        return self._rendu


class _Config:
    """Fidèle à la vraie forme : `bot.config.bot.name`.

    La version précédente de ce stub portait `persona.name` — un attribut qui
    N'EXISTE PAS. Le test passait, et Wally restait dans son propre tirage.
    """
    bot = type("_B", (), {"name": "Wally"})


def _bot(prelude=None, faits=None, users=None, rendu=None, narrateur=None):
    b = type("B", (), {})()
    b.overlay_narrator = narrateur if narrateur is not None else _Narrateur()
    b.config = _Config()
    b.memory = _Memory(
        prelude if prelude is not None else [{"author": "alice", "content": "yo"}],
        faits if faits is not None else "\n".join(f"fait {i}" for i in range(6)),
    )
    b.db = _Db(users if users is not None else
               [{"user_id": "twitch:42", "username": "alice"}])
    b.llm_secondary = _Llm(rendu if rendu is not None else json.dumps(
        {"affirmations": ["joue à Apex", "déteste le café", "vit à Lyon"],
         "index_du_mensonge": 1}))
    return b


async def test_le_jeu_ouvre_la_fiction_avant_de_publier():
    """L'ordre est la garantie : si le sondage partait d'abord, une réponse du
    chat pourrait être analysée avant que la garde ne soit posée."""
    b = _bot()
    rendu = await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    assert "lancé" in rendu
    assert fiction.en_cours("c1")
    assert b.overlay_narrator.sondage[1] == ["joue à Apex", "déteste le café", "vit à Lyon"]


async def test_le_compte_rendu_ne_dit_pas_laquelle_est_fausse():
    """Un secret qu'on ne donne pas ne fuit pas. `secret_guard` était
    inutilisable ici : il masquerait le mensonge DANS le sondage qui l'affiche."""
    b = _bot()
    rendu = await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    # Les trois phrases SONT dans le compte rendu — elles doivent l'être, Wally
    # va en parler. Ce qui ne doit pas y être, c'est laquelle est fausse.
    assert all(p in rendu for p in ("joue à Apex", "déteste le café", "vit à Lyon"))
    assert "Tu ne sais PAS laquelle est fausse" in rendu
    for indice in ("index", "la fausse est", "le mensonge est", "mensonge était"):
        assert indice not in rendu


async def test_la_revelation_ferme_la_fiction_et_annonce(monkeypatch):
    monkeypatch.setattr(dv, "_DELAI_REVELATION_S", 0.0)
    b = _bot()
    await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    await asyncio.sleep(0.05)
    assert not fiction.en_cours("c1")
    genre, fait = b.overlay_narrator.annonces[-1]
    assert genre == "deux_verites"
    assert "déteste le café" in fait


async def test_un_sondage_refuse_referme_la_fiction():
    """Hors live, `start_poll` rend False. Sans ce retour en arrière, la garde
    resterait posée sur un jeu qui n'a jamais commencé."""
    b = _bot(narrateur=_Narrateur(accepte=False))
    rendu = await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    assert "pas de live" in rendu
    assert not fiction.en_cours("c1")


async def test_on_ne_joue_pas_sur_quelquun_dabsent():
    b = _bot(prelude=[{"author": "alice", "content": "yo"}])
    rendu = await dv.run_deux_verites_tool(b, {"personne": "bob"}, canal_id="c1")
    assert "pas écrit récemment" in rendu
    assert b.overlay_narrator.sondage is None
    assert not fiction.en_cours("c1")


async def test_on_ne_joue_pas_sur_quelquun_quon_connait_a_peine():
    """Deux vérités demandent deux faits VRAIS ; un mensonge crédible se dérive
    d'un troisième. En dessous, le jeu produit du n'importe quoi sur quelqu'un
    de réel, devant tout le monde."""
    b = _bot(faits="un seul fait")
    rendu = await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    assert "pas assez de choses" in rendu
    assert not fiction.en_cours("c1")


async def test_wally_nest_jamais_tire_au_sort():
    """Ses propres répliques sont dans le prélude, sous son nom."""
    b = _bot(prelude=[{"author": "Wally", "content": "salut"}])
    rendu = await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    assert "Personne n'a écrit" in rendu


async def test_une_reponse_llm_illisible_ne_publie_rien():
    """`complete()` rend `FALLBACK_RESPONSE`, jamais une exception : un JSON
    absent est un échec ORDINAIRE, pas un cas rare."""
    b = _bot(rendu="je ne sais pas trop quoi répondre")
    rendu = await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    assert "échoué" in rendu
    assert b.overlay_narrator.sondage is None
    assert not fiction.en_cours("c1")


async def test_un_index_hors_bornes_ne_publie_rien():
    b = _bot(rendu=json.dumps({"affirmations": ["a", "b", "c"],
                               "index_du_mensonge": 7}))
    rendu = await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    assert "échoué" in rendu
    assert not fiction.en_cours("c1")


async def test_deux_parties_ne_se_chevauchent_pas():
    b = _bot()
    await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    rendu = await dv.run_deux_verites_tool(b, {}, canal_id="c1")
    assert "déjà en cours" in rendu


async def test_sans_canal_le_jeu_refuse():
    """Un canal vide ouvrirait une fiction que `fiction.ouvrir` ignore, donc une
    garde qui ne garde rien — le jeu tournerait sans cloisonnement."""
    b = _bot()
    rendu = await dv.run_deux_verites_tool(b, {}, canal_id="")
    assert "quel canal" in rendu
    assert b.overlay_narrator.sondage is None


def test_le_pseudo_nu_prend_la_forme_arobase():
    assert dv._pseudo_nu("Bob (@bob_ttv)") == "bob_ttv"
    assert dv._pseudo_nu("Bob (le vrai)") == "bob (le vrai)"
