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
            accuses=None, onglet=""):
    return svc.battement(actif=actif, joue=joue, titre=titre, artiste=artiste,
                         url=url, accuses=accuses or [], onglet=onglet)


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


def test_une_page_youtube_SANS_lecteur_n_est_pas_un_morceau():
    """L'extension bat même sur une page sans vidéo — la page d'accueil, une
    recherche — pour dire qu'elle est VIVANTE. Ce battement-là n'apprend rien
    sur ce qui passe : sans titre, on ne sait pas, et « je ne sais pas » n'est
    pas « en pause sur «  » ». Sans cette garde, le chat annonce un morceau vide
    et l'overlay reçoit une carte sans texte."""
    svc = _service()
    _battre(svc, joue=False, titre="", artiste="")
    assert svc.etat() is None


# ── Le morceau qui change s'annonce tout seul ───────────────────────────────
#
# Arbitré avec l'owner le 2026-08-19 : pas de bandeau permanent, mais l'écran
# suit les morceaux d'Azraël sans qu'on ait à les demander. Le service ne
# connaît pas l'overlay — il appelle un rappel, et c'est `main.py` qui y branche
# le narrateur. Ce module ne parle ni au réseau ni à l'écran, c'est ce qui le
# rend testable sur des dictionnaires nus.

def _service_ecoute(horloge=None):
    from bot.core.music import MusicService
    vus = []
    svc = MusicService(horloge=horloge or _Horloge(), on_morceau=vus.append)
    return svc, vus


def test_un_nouveau_morceau_est_ANNONCE_sans_qu_on_demande():
    svc, vus = _service_ecoute()
    _battre(svc, titre="Numb", artiste="Linkin Park")
    assert [(m["titre"], m["artiste"]) for m in vus] == [("Numb", "Linkin Park")]


def test_le_MEME_morceau_ne_s_annonce_pas_a_chaque_battement():
    """Le battement passe toutes les deux secondes : sans cette garde, l'écran
    reçoit trente annonces par minute pour un seul morceau."""
    svc, vus = _service_ecoute()
    for _ in range(5):
        _battre(svc, titre="Numb", artiste="Linkin Park")
    assert len(vus) == 1


def test_changer_de_morceau_l_annonce_a_nouveau():
    svc, vus = _service_ecoute()
    _battre(svc, titre="Numb", artiste="Linkin Park")
    _battre(svc, titre="In The End", artiste="Linkin Park")
    assert [m["titre"] for m in vus] == ["Numb", "In The End"]


def test_une_MISE_EN_PAUSE_n_annonce_rien():
    """Mettre en pause n'est pas un nouveau morceau. Et une vidéo à l'arrêt n'a
    rien à faire à l'écran de son propre chef — on ne l'affiche que si quelqu'un
    le demande dans le chat."""
    svc, vus = _service_ecoute()
    _battre(svc, titre="Numb", artiste="Linkin Park")
    _battre(svc, titre="Numb", artiste="Linkin Park", joue=False)
    assert len(vus) == 1


def test_une_page_SANS_lecteur_n_annonce_rien():
    """L'extension bat aussi sur la page d'accueil, pour se dire vivante."""
    svc, vus = _service_ecoute()
    _battre(svc, titre="", artiste="")
    assert vus == []


def test_un_rappel_qui_CASSE_ne_fait_pas_tomber_le_battement():
    """L'écran est un consommateur parmi d'autres : un bus overlay en panne ne
    doit ni perdre l'état ni rendre un 500 à l'extension."""
    from bot.core.music import MusicService

    def casse(_morceau):
        raise RuntimeError("bus overlay mort")

    svc = MusicService(horloge=_Horloge(), on_morceau=casse)
    _battre(svc, titre="Numb", artiste="Linkin Park")
    assert svc.etat()["titre"] == "Numb"


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
    svc = _service()
    # Le délai réel se compte en secondes : on le raccourcit sur CETTE instance
    # plutôt que d'immobiliser la suite de tests pendant ce temps.
    svc.ACCUSE_TIMEOUT_S = 0.05
    resultat = await asyncio.wait_for(svc.commander("pause"), 2)
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


# ── la réponse TENUE (long polling) ─────────────────────────────────────────
#
# Chrome ne laisse pas un onglet caché battre toutes les deux secondes. Dès que
# la page est silencieuse depuis trente secondes et cachée depuis cinq minutes,
# ses `setInterval` tombent à UN PAR MINUTE (« intensive throttling », Chrome
# 88). Mesuré en prod le 2026-08-21 : soixante secondes pile entre deux
# battements, huit fois de suite — et pendant ce temps, « mets lecture » n'a
# jamais pu partir, l'ordre périmant avant qu'un battement vienne le chercher.
#
# Or l'état silencieux est EXACTEMENT celui où `play` a un sens : la commande
# était donc structurellement impossible. La parade ne peut pas être un délai
# plus long — c'est la cadence qui doit changer de camp. Le serveur TIENT la
# réponse jusqu'à ce qu'un ordre arrive ; l'extension repart dès qu'elle l'a
# reçue, en chaînant sur la promesse `fetch`. Un rappel réseau n'est pas un
# timer : il échappe au throttling.


@pytest.mark.asyncio
async def test_un_ordre_REVEILLE_le_battement_TENU_sans_attendre_le_delai():
    """Le cœur du correctif : l'ordre part en une fraction de seconde même si
    l'onglet est caché depuis une heure."""
    svc = _service()
    attente = asyncio.create_task(svc.battement_tenu(
        attente_s=30, actif=True, joue=False, titre="Snakes", artiste="MIYAVI",
        url="https://youtube.com/watch?v=abc"))
    await asyncio.sleep(0)                      # le veilleur se met en place

    asyncio.create_task(svc.commander("play"))
    ordres = await asyncio.wait_for(attente, 1)   # et NON trente secondes
    assert [o["action"] for o in ordres] == ["play"]


@pytest.mark.asyncio
async def test_sans_ordre_le_battement_TENU_rend_la_main_au_bout_du_delai():
    """Sans plafond, la requête resterait ouverte jusqu'à ce qu'un proxy la
    coupe — et l'extension croirait le bot mort."""
    svc = _service()
    ordres = await asyncio.wait_for(svc.battement_tenu(
        attente_s=0.05, actif=True, joue=True, titre="Numb",
        artiste="Linkin Park", url="https://youtube.com/watch?v=abc"), 1)
    assert ordres == []


@pytest.mark.asyncio
async def test_un_ordre_deja_en_file_est_rendu_SANS_attendre():
    svc = _service()
    asyncio.create_task(svc.commander("pause"))
    await asyncio.sleep(0)
    ordres = await asyncio.wait_for(svc.battement_tenu(
        attente_s=30, actif=True, joue=True, titre="Numb",
        artiste="Linkin Park", url="https://youtube.com/watch?v=abc"), 1)
    assert [o["action"] for o in ordres] == ["pause"]


@pytest.mark.asyncio
async def test_un_onglet_en_PAUSE_n_est_pas_reveille_par_ce_qu_il_ne_prendra_pas():
    """« Suivante » ne part pas vers un onglet à l'arrêt (il reste en file pour
    celui qui joue). Le réveiller quand même le ferait repartir aussitôt pour
    rien, et les deux tourneraient en boucle serrée jusqu'à la péremption."""
    svc = _service()
    attente = asyncio.create_task(svc.battement_tenu(
        attente_s=0.2, actif=True, joue=False, titre="Snakes", artiste="MIYAVI",
        url="https://youtube.com/watch?v=abc"))
    await asyncio.sleep(0)

    asyncio.create_task(svc.commander("next"))
    assert await asyncio.wait_for(attente, 2) == []


@pytest.mark.asyncio
async def test_l_extension_ETEINTE_ne_tient_aucune_reponse():
    """Partage coupé : rien à attendre, et surtout pas trente secondes."""
    svc = _service()
    ordres = await asyncio.wait_for(svc.battement_tenu(
        attente_s=30, actif=False, joue=False, titre="", artiste="",
        url=""), 1)
    assert ordres == []


@pytest.mark.asyncio
async def test_le_delai_d_attente_est_BORNE_par_le_service():
    """La valeur vient du navigateur d'un tiers : elle se borne ici, pas là-bas."""
    from bot.core.music import MusicService
    svc = _service()
    assert svc.borner_attente(9999) == MusicService.ATTENTE_MAX_S
    assert svc.borner_attente(-5) == 0.0
    assert svc.borner_attente("bavure") == 0.0
    assert svc.borner_attente(None) == 0.0
    # `float("nan")` traverse le `try` sans lever, et toute comparaison avec lui
    # est fausse : un `min`/`max` le laisserait passer tel quel, et
    # `wait_for(..., nan)` rendrait la main aussitôt à chaque battement.
    assert svc.borner_attente(float("nan")) == 0.0


@pytest.mark.asyncio
async def test_un_ordre_ne_SURVIT_PAS_a_celui_qui_l_attendait():
    """Le défaut vu en prod le 2026-08-21 : « next » annoncé raté à 10:29:05,
    puis EXÉCUTÉ à 10:29:10 — le morceau a changé cinq secondes après que Wally
    a dit que ça n'avait pas marché. Un ordre que plus personne n'attend ne doit
    plus pouvoir partir : sa durée de vie est celle de l'attente."""
    from bot.core.music import MusicService
    assert MusicService.ORDRE_TTL_S <= MusicService.ACCUSE_TIMEOUT_S


@pytest.mark.asyncio
async def test_un_partage_ETEINT_ne_se_voit_servir_AUCUN_ordre():
    """Un ordre n'est remis qu'une fois : le donner à une extension qui vient de
    dire qu'elle n'exécutera rien le perdrait pour tout le monde. Il attend en
    file celui qui pourra le prendre."""
    svc = _service()
    asyncio.create_task(svc.commander("play"))
    await asyncio.sleep(0)
    assert _battre(svc, actif=False) == []
    assert [o["action"] for o in _battre(svc, joue=False)] == ["play"]


# ── plusieurs onglets YouTube ───────────────────────────────────────────────
#
# Azraël peut en avoir trois ouverts : celui qui joue, et deux autres où il
# cherche quelque chose. L'état était GLOBAL — le dernier qui battait écrasait
# les autres, et une page d'accueil sans lecteur effaçait donc le morceau en
# cours toutes les deux secondes. Wally répondait « je ne sais pas ce qui
# passe » à côté d'une musique qui tournait.


def test_un_onglet_SANS_LECTEUR_n_efface_pas_le_morceau_qui_joue():
    svc = _service()
    _battre(svc, onglet="a", titre="Numb", artiste="Linkin Park", joue=True)
    _battre(svc, onglet="b", titre="", artiste="", joue=False,
            url="https://youtube.com/results?search_query=chat")
    assert svc.etat()["titre"] == "Numb"


def test_l_onglet_qui_JOUE_l_emporte_sur_celui_qui_est_en_pause():
    """Deux vidéos ouvertes, une seule tourne : c'est celle-là qu'on écoute."""
    svc = _service()
    _battre(svc, onglet="a", titre="Numb", artiste="Linkin Park", joue=True)
    _battre(svc, onglet="b", titre="Snakes", artiste="MIYAVI", joue=False)
    assert svc.etat()["titre"] == "Numb"


def test_a_egalite_c_est_le_plus_RECEMMENT_vu_qui_compte():
    h = _Horloge()
    svc = _service(h)
    _battre(svc, onglet="a", titre="Numb", artiste="Linkin Park", joue=False)
    h.avance(1)
    _battre(svc, onglet="b", titre="Snakes", artiste="MIYAVI", joue=False)
    assert svc.etat()["titre"] == "Snakes"


def test_l_onglet_qui_JOUE_finit_par_PERIMER_comme_les_autres():
    """Azraël a fermé l'onglet sans rien dire : au bout d'un moment, ce n'est
    plus « ce qui passe », c'est ce qui passait."""
    from bot.core.music import MusicService
    h = _Horloge()
    svc = _service(h)
    _battre(svc, onglet="a", titre="Numb", artiste="Linkin Park", joue=True)
    h.avance(MusicService.PERIME_S + 1)
    _battre(svc, onglet="b", titre="Snakes", artiste="MIYAVI", joue=False)
    assert svc.etat()["titre"] == "Snakes"


def test_un_onglet_FERME_ne_reste_pas_en_memoire_pour_toujours():
    from bot.core.music import MusicService
    h = _Horloge()
    svc = _service(h)
    for n in range(20):
        _battre(svc, onglet=f"onglet-{n}", titre=f"Morceau {n}")
        h.avance(MusicService.PERIME_S + 1)
    _battre(svc, onglet="dernier", titre="Le bon")
    assert len(svc._onglets) <= 2


def test_le_MEME_morceau_sur_DEUX_onglets_ne_s_annonce_pas_deux_fois():
    """Sinon l'écran clignoterait à chaque battement de l'un puis de l'autre."""
    from bot.core.music import MusicService
    vus = []
    svc = MusicService(horloge=_Horloge(), on_morceau=vus.append)
    _battre(svc, onglet="a", titre="Numb", artiste="Linkin Park", joue=True)
    _battre(svc, onglet="b", titre="Numb", artiste="Linkin Park", joue=True)
    assert len(vus) == 1


@pytest.mark.asyncio
async def test_un_onglet_SANS_LECTEUR_ne_prend_pas_le_play():
    """Azraël a mis sa vidéo en pause et cherche autre chose dans un second
    onglet. « Lecture » servi à celui-là rendrait « aucune vidéo sur cette
    page » — un échec annoncé dans le chat alors que le lecteur était juste à
    côté, prêt à repartir."""
    svc = _service()
    asyncio.create_task(svc.commander("play"))
    await asyncio.sleep(0)

    assert _battre(svc, onglet="b", titre="", joue=False) == []
    assert [o["action"] for o in
            _battre(svc, onglet="a", titre="Numb", joue=False)] == ["play"]


@pytest.mark.asyncio
async def test_lancer_un_TITRE_part_meme_vers_une_page_sans_lecteur():
    """Celui-là ne réveille pas un lecteur : il NAVIGUE. Exiger une vidéo
    ouverte rendrait « mets du Linkin Park » impossible depuis une page
    d'accueil, qui est pourtant l'endroit le plus banal où être."""
    svc = _service()
    asyncio.create_task(svc.commander("play_query", query="Linkin Park"))
    await asyncio.sleep(0)
    assert [o["action"] for o in
            _battre(svc, onglet="b", titre="", joue=False)] == ["play_query"]


@pytest.mark.asyncio
async def test_un_onglet_sans_lecteur_n_est_pas_REVEILLE_par_un_play():
    """Réveillé pour rien, il repartirait les mains vides et rappellerait
    aussitôt : les deux tourneraient en boucle serrée jusqu'à la péremption."""
    svc = _service()
    attente = asyncio.create_task(svc.battement_tenu(
        attente_s=0.2, actif=True, joue=False, titre="", artiste="",
        url="https://youtube.com/", onglet="b"))
    await asyncio.sleep(0)
    asyncio.create_task(svc.commander("play"))
    assert await asyncio.wait_for(attente, 2) == []
