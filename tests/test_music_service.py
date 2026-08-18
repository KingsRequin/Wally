"""Ce que Wally sait de la musique d'Azraël, et ce qu'il peut en faire.

§10 du chantier. Azraël écoute sur YouTube dans un onglet ; une extension Chrome
envoie un battement régulier (ce qui passe) et récupère au passage les ordres en
attente. Un seul canal dans les deux sens : le SSE envisagé d'abord aurait
demandé des tickets à usage unique, une route de flux et sa reconnexion, pour
gagner une latence d'une seconde sur une action qui met déjà plus longtemps à
être décidée.

Trois règles gouvernent ce module, et chacune vient d'un défaut déjà vécu
ailleurs dans ce bot :

  · **On ne prétend pas savoir.** Un état vieux de plusieurs minutes n'est pas
    « ce qui passe » — c'est ce qui passait. Sans cette borne, Wally annonce le
    dernier titre CONNU comme le dernier titre JOUÉ, exactement comme il
    présentait un vieux patch Apex pour une nouveauté.

  · **On n'annonce pas une action non confirmée.** Un ordre part, il faut
    l'accusé de l'extension pour dire qu'il est fait. Sinon Wally annonce des
    gestes qui n'ont pas eu lieu.

  · **La confidentialité se joue à l'ÉCRITURE.** L'extension voit TOUT ce
    qu'Azraël ouvre sur YouTube. Interrupteur éteint, rien n'entre ici — pas
    « rien ne sort ». Même règle que le tampon de conversation vocale.
"""
import asyncio

import pytest


class _Horloge:
    """Le temps, sous contrôle du test."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def avance(self, secondes: float) -> None:
        self.t += secondes


def _service(horloge=None):
    from bot.core.music import MusicService
    return MusicService(horloge=horloge or _Horloge())


def _battre(svc, *, actif=True, joue=True, titre="Ma chanson",
            artiste="Un artiste", url="https://youtube.com/watch?v=abc",
            accuses=None):
    return svc.battement(actif=actif, joue=joue, titre=titre, artiste=artiste,
                         url=url, accuses=accuses or [])


# ── Ce qui passe ────────────────────────────────────────────────────────────

def test_sans_battement_on_ne_sait_RIEN():
    """Et surtout pas un dictionnaire vide, qui se lirait comme « rien ne
    joue » — deux situations opposées pour un viewer qui demande."""
    assert _service().etat() is None


def test_un_battement_donne_le_titre_et_l_artiste():
    svc = _service()
    _battre(svc, titre="Numb", artiste="Linkin Park")
    etat = svc.etat()
    assert etat["titre"] == "Numb"
    assert etat["artiste"] == "Linkin Park"
    assert etat["joue"] is True


def test_un_etat_TROP_VIEUX_ne_compte_plus():
    """Azraël a fermé l'onglet, coupé l'extension, ou son PC a planté : Wally ne
    doit pas annoncer un titre d'il y a une heure comme celui du moment."""
    from bot.core.music import MusicService
    h = _Horloge()
    svc = _service(h)
    _battre(svc)
    assert svc.etat() is not None
    h.avance(MusicService.PERIME_S + 1)
    assert svc.etat() is None


def test_un_hoquet_de_reseau_ne_fait_pas_tout_oublier():
    """Le battement passe toutes les deux secondes : la borne doit tolérer
    quelques ratés sans déclarer l'extension morte."""
    from bot.core.music import MusicService
    h = _Horloge()
    svc = _service(h)
    _battre(svc)
    h.avance(10)
    assert svc.etat() is not None
    assert MusicService.PERIME_S >= 30


def test_l_INTERRUPTEUR_eteint_n_ecrit_RIEN():
    """L'extension voit tout ce qu'Azraël ouvre sur YouTube, pas seulement sa
    musique. Éteinte, elle ne doit rien laisser derrière elle : c'est à
    l'écriture que ça se joue, pas à la lecture — un consommateur ajouté plus
    tard trouverait le titre d'une vidéo privée."""
    svc = _service()
    _battre(svc, actif=False, titre="Une vidéo perso très gênante")
    assert svc.etat() is None
    assert "gênante" not in repr(svc.__dict__)


def test_l_interrupteur_eteint_EFFACE_ce_qu_on_savait():
    """Couper l'extension en plein live doit faire oublier le titre en cours,
    pas le figer pour la minute et demie qui suit."""
    svc = _service()
    _battre(svc, titre="Chanson publique")
    _battre(svc, actif=False, titre="")
    assert svc.etat() is None


def test_une_video_en_PAUSE_reste_connue_mais_dite_en_pause():
    """« Qu'est-ce qui passe ? » pendant une pause a une réponse juste, et ce
    n'est ni le silence ni un mensonge."""
    svc = _service()
    _battre(svc, joue=False, titre="Interlude")
    etat = svc.etat()
    assert etat["titre"] == "Interlude"
    assert etat["joue"] is False


def test_les_champs_sont_bornes_en_longueur():
    """Le titre vient d'une page web : c'est une entrée non fiable, et il finit
    dans le chat Twitch et sur l'overlay."""
    svc = _service()
    _battre(svc, titre="x" * 5000, artiste="y" * 5000)
    etat = svc.etat()
    assert len(etat["titre"]) <= 200
    assert len(etat["artiste"]) <= 200


# ── Les ordres ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_ordre_est_remis_au_battement_suivant():
    svc = _service()
    tache = asyncio.create_task(svc.commander("next"))
    await asyncio.sleep(0)
    ordres = _battre(svc)
    assert [o["action"] for o in ordres] == ["next"]
    # L'accusé referme la boucle.
    _battre(svc, accuses=[{"id": ordres[0]["id"], "ok": True, "titre": "La suivante"}])
    resultat = await tache
    assert resultat["ok"] is True
    assert resultat["titre"] == "La suivante"


@pytest.mark.asyncio
async def test_sans_ACCUSE_l_ordre_est_un_ECHEC_et_non_un_succes():
    """Le cœur de la règle : l'extension peut être éteinte, l'onglet fermé, le
    PC en veille. Répondre « c'est fait » sans preuve, c'est ce que Wally a déjà
    fait pour des capacités qu'il croyait avoir."""
    from bot.core.music import MusicService
    svc = _service()
    resultat = await asyncio.wait_for(svc.commander("pause"),
                                      MusicService.ACCUSE_TIMEOUT_S + 2)
    assert resultat["ok"] is False
    assert resultat["raison"]


@pytest.mark.asyncio
async def test_un_ordre_REFUSE_par_l_extension_est_rapporte_tel_quel():
    """Le lecteur peut ne pas savoir faire (pas de suivante hors playlist).
    C'est un échec honnête, pas une panne de liaison."""
    svc = _service()
    tache = asyncio.create_task(svc.commander("next"))
    await asyncio.sleep(0)
    ordres = _battre(svc)
    _battre(svc, accuses=[{"id": ordres[0]["id"], "ok": False,
                           "raison": "pas de vidéo suivante"}])
    resultat = await tache
    assert resultat["ok"] is False
    assert "suivante" in resultat["raison"]


@pytest.mark.asyncio
async def test_un_ordre_n_est_remis_qu_UNE_fois():
    """Deux onglets qui battent, ou un battement rejoué : « suivante » ne doit
    pas sauter deux morceaux."""
    svc = _service()
    asyncio.create_task(svc.commander("next"))
    await asyncio.sleep(0)
    assert len(_battre(svc)) == 1
    assert _battre(svc) == []


@pytest.mark.asyncio
async def test_un_ordre_qui_MOISIT_ne_s_execute_pas_plus_tard():
    """L'extension revient après cinq minutes d'absence : « musique suivante »
    demandé à ce moment-là n'a plus aucun sens, et surprendrait tout le monde
    en plein autre morceau."""
    from bot.core.music import MusicService
    h = _Horloge()
    svc = _service(h)
    asyncio.create_task(svc.commander("next"))
    await asyncio.sleep(0)
    h.avance(MusicService.ORDRE_TTL_S + 1)
    assert _battre(svc) == []


@pytest.mark.asyncio
async def test_la_file_d_ordres_est_BORNEE():
    """Un modo qui spamme « suivante » ne doit pas remplir la mémoire ni faire
    défiler trente morceaux au retour de l'extension."""
    from bot.core.music import MusicService
    svc = _service()
    for _ in range(MusicService.MAX_ORDRES + 5):
        asyncio.create_task(svc.commander("next"))
    await asyncio.sleep(0)
    assert len(_battre(svc)) <= MusicService.MAX_ORDRES


@pytest.mark.asyncio
async def test_une_action_INCONNUE_est_refusee_avant_de_partir():
    """L'action vient d'un modèle de langage : l'énuméré est la barrière, et il
    est ici, pas dans le prompt."""
    svc = _service()
    resultat = await svc.commander("format_c")
    assert resultat["ok"] is False
    assert _battre(svc) == []


@pytest.mark.asyncio
async def test_lancer_un_titre_precis_porte_sa_recherche():
    svc = _service()
    asyncio.create_task(svc.commander("play_query", query="Linkin Park Numb"))
    await asyncio.sleep(0)
    ordres = _battre(svc)
    assert ordres[0]["action"] == "play_query"
    assert ordres[0]["query"] == "Linkin Park Numb"


@pytest.mark.asyncio
async def test_une_recherche_vide_ne_part_pas():
    """« Wally mets » sans rien derrière : mieux vaut le dire que d'ouvrir une
    recherche vide sur l'écran du live."""
    svc = _service()
    resultat = await svc.commander("play_query", query="   ")
    assert resultat["ok"] is False
    assert _battre(svc) == []


# ── quel onglet obéit ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_onglet_qui_NE_JOUE_PAS_ne_prend_pas_le_suivant():
    """Azraël peut avoir trois onglets YouTube ouverts. « Suivante » ne veut
    rien dire pour ceux qui dorment — et comme un ordre n'est remis qu'une
    fois, le laisser partir vers le mauvais onglet le perdrait pour tout le
    monde. Il reste donc en file jusqu'à ce que le bon batte."""
    svc = _service()
    asyncio.create_task(svc.commander("next"))
    await asyncio.sleep(0)

    assert _battre(svc, joue=False) == []      # l'onglet en pause passe son tour
    ordres = _battre(svc, joue=True)           # celui qui joue le prend
    assert [o["action"] for o in ordres] == ["next"]


@pytest.mark.asyncio
async def test_ce_qui_REVEILLE_part_meme_vers_un_onglet_a_l_arret():
    """`play` et `play_query` s'adressent justement à un lecteur arrêté :
    exiger qu'il joue déjà les rendrait impossibles à exécuter."""
    for action in ("play", "play_query"):
        svc = _service()
        asyncio.create_task(svc.commander(action, query="une chanson"))
        await asyncio.sleep(0)
        assert [o["action"] for o in _battre(svc, joue=False)] == [action]


@pytest.mark.asyncio
async def test_un_ordre_garde_en_file_finit_quand_meme_par_PERIMER():
    """Sinon un « suivante » demandé alors que tout est en pause attendrait
    indéfiniment le premier onglet qui joue, et sauterait un morceau une heure
    plus tard."""
    from bot.core.music import MusicService
    h = _Horloge()
    svc = _service(h)
    asyncio.create_task(svc.commander("next"))
    await asyncio.sleep(0)
    _battre(svc, joue=False)
    h.avance(MusicService.ORDRE_TTL_S + 1)
    assert _battre(svc, joue=True) == []
