"""Les kills d'Azraël, partie par partie, pendant le live (§12).

Ce module ne RÉÉCRIT aucune règle de comptage : il réutilise `score_manche()` et
`read_kill_trackers()`, écrits pour le duel et payés cher — le maximum des deltas
et jamais leur somme (les quatre trackers bougent ensemble, les additionner
quadruple le score), `None` plutôt que zéro quand rien n'est mesurable, et un
plafond de vraisemblance. Le 2026-08-13, un écart de règle a fait annoncer
« 0 kill » en direct à quelqu'un qui venait d'en faire 39.

Ce qu'il ajoute, c'est le DÉCOUPAGE en parties hors duel, et deux prudences :

  · **On attend que l'API rattrape.** Les compteurs ne bougent qu'après la fin
    de la partie, avec du retard. Figer à la seconde où le joueur quitte donnerait
    zéro à toutes les parties.

  · **Une partie non mesurable n'entre pas dans le cumul** (choix de l'owner) :
    la Mixtape n'incrémente aucun compteur, et des trackers dépinglés sont
    figés. La compter pour zéro rendrait le total du live faux vers le bas sans
    que personne ne le sache.
"""
import pytest


class _Horloge:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def avance(self, s: float) -> None:
        self.t += s


def _suivi(horloge=None):
    from bot.core.apex.kills_live import KillsDuLive
    return KillsDuLive(horloge=horloge or _Horloge())


# Quatre trackers qui bougent ENSEMBLE, comme dans la vraie API.
def _tk(n: int) -> dict:
    return {"career_kills": 10_000 + n, "specialEvent_kills": 90_000 + n,
            "kills": 5_000 + n, "grandsoiree_kills": 700 + n}


# ── une partie ──────────────────────────────────────────────────────────────

def test_une_partie_donne_ses_kills_apres_l_attente():
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    assert s.relever(in_game=True, trackers=_tk(0)) is None      # entrée
    h.avance(600)
    assert s.relever(in_game=True, trackers=_tk(4)) is None      # en jeu
    h.avance(30)
    # Sorti de partie : on ne fige PAS encore, l'API publie après coup.
    assert s.relever(in_game=False, trackers=_tk(4)) is None
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    bilan = s.relever(in_game=False, trackers=_tk(4))
    assert bilan is not None
    assert bilan["partie"] == 4
    assert bilan["total"] == 4
    assert bilan["parties"] == 1


def test_les_kills_publies_EN_RETARD_sont_pris():
    """Tout l'intérêt de l'attente : les compteurs montent après la sortie."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    h.avance(600)
    s.relever(in_game=False, trackers=_tk(0))     # rien encore publié
    h.avance(60)
    s.relever(in_game=False, trackers=_tk(7))     # l'API rattrape
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S)
    assert s.relever(in_game=False, trackers=_tk(7))["partie"] == 7


def test_le_bilan_n_est_rendu_QU_UNE_fois():
    """Sinon le widget repart à chaque relevé de la sonde, toutes les 30 s."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    s.relever(in_game=False, trackers=_tk(3))
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    assert s.relever(in_game=False, trackers=_tk(3)) is not None
    assert s.relever(in_game=False, trackers=_tk(3)) is None


def test_une_partie_commencee_AVANT_qu_on_regarde_n_est_pas_mesuree():
    """Bot redémarré en pleine partie : on ne sait pas d'où elle est partie, et
    inventer un point de départ donnerait un chiffre faux."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    # Le premier relevé le voit DÉJÀ en partie : aucune base.
    s.relever(in_game=True, trackers=_tk(50), premier=True)
    s.relever(in_game=False, trackers=_tk(55))
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    bilan = s.relever(in_game=False, trackers=_tk(55))
    # Un bilan « non mesurable » plutôt que rien : l'appelant sait qu'une partie
    # s'est terminée, et qu'il n'y a rien de juste à en dire. Ce qui compte est
    # qu'aucun chiffre faux ne sorte — surtout pas les 5 de l'écart brut, qui ne
    # couvrent qu'une fraction inconnue de la partie.
    assert bilan["partie"] is None
    assert bilan["total"] == 0 and bilan["parties"] == 0


# ── ce qui n'est pas mesurable ──────────────────────────────────────────────

def test_une_partie_ILLISIBLE_est_signalee_mais_ne_compte_pas():
    """Illisible ≠ zéro, et `score_manche` fait déjà la différence : un témoin
    perdu (tracker disparu entre les deux relevés) avec des deltas nuls ne
    prouve rien — « personne n'a tué » et « ce compteur est mort » s'écrivent
    pareil.

    Choix de l'owner : une telle partie n'entre pas dans le cumul. La compter
    pour zéro fausserait le total du live sans que personne ne le sache.
    """
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    # Un tracker DISPARAÎT (dépinglé en cours de partie) et les autres ne
    # bougent pas : c'est le cas que `score_manche` refuse de trancher.
    partiels = {k: v for k, v in _tk(0).items() if k != "career_kills"}
    s.relever(in_game=False, trackers=partiels)
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    bilan = s.relever(in_game=False, trackers=partiels)
    assert bilan is not None
    assert bilan["partie"] is None                # illisible, pas « zéro »
    assert bilan["total"] == 0
    assert bilan["parties"] == 0                  # elle ne compte pas


def test_une_partie_SANS_KILL_mais_lisible_compte_bel_et_bien():
    """L'autre moitié, et il ne faut pas les confondre : mourir sans tuer est
    une partie réelle. Ses compteurs sont tous lisibles et tous immobiles —
    zéro est alors une MESURE, et elle entre dans le décompte des parties."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    s.relever(in_game=False, trackers=_tk(0))
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    bilan = s.relever(in_game=False, trackers=_tk(0))
    assert bilan["partie"] == 0
    assert bilan["parties"] == 1


def test_un_bond_INVRAISEMBLABLE_ne_passe_pas():
    """Le ré-épinglage d'un tracker fait bondir un compteur de milliers d'un
    coup. `score_manche` a son plafond : on ne le contourne pas."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    s.relever(in_game=False, trackers=_tk(9000))
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    assert s.relever(in_game=False, trackers=_tk(9000))["partie"] is None


def test_les_trackers_ne_sont_JAMAIS_additionnes():
    """Le piège symétrique de celui des totaux carrière : quatre trackers qui
    montent de 4 chacun, c'est 4 kills — pas 16."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    s.relever(in_game=False, trackers=_tk(4))
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    assert s.relever(in_game=False, trackers=_tk(4))["partie"] == 4


# ── le cumul du live ────────────────────────────────────────────────────────

def test_le_cumul_additionne_les_parties_MESUREES():
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    for depart, arrivee in ((0, 3), (3, 8), (8, 10)):
        s.relever(in_game=True, trackers=_tk(depart))
        s.relever(in_game=False, trackers=_tk(arrivee))
        h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
        bilan = s.relever(in_game=False, trackers=_tk(arrivee))
    assert bilan["total"] == 3 + 5 + 2
    assert bilan["parties"] == 3


def test_un_NOUVEAU_live_repart_de_zero():
    """Le cumul du soir ne traîne pas jusqu'au lendemain."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    s.relever(in_game=False, trackers=_tk(6))
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    assert s.relever(in_game=False, trackers=_tk(6))["total"] == 6

    s.nouveau_live()
    s.relever(in_game=True, trackers=_tk(6))
    s.relever(in_game=False, trackers=_tk(8))
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    bilan = s.relever(in_game=False, trackers=_tk(8))
    assert bilan["total"] == 2 and bilan["parties"] == 1


def test_une_partie_qui_ENCHAINE_pendant_l_attente_est_quand_meme_figee():
    """Azraël relance tout de suite. Sans ce cas, la partie précédente reste en
    suspens pour toujours et son bilan n'arrive jamais."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    s.relever(in_game=False, trackers=_tk(5))
    h.avance(10)                                   # bien avant la fin de l'attente
    bilan = s.relever(in_game=True, trackers=_tk(5))
    assert bilan is not None and bilan["partie"] == 5


# ── quand le bilan tombe ────────────────────────────────────────────────────

def test_le_bilan_tombe_DES_QUE_les_compteurs_se_sont_tus():
    """Le défaut vu en direct le 2026-08-19 : le bilan n'arrivait pas au retour
    au lobby mais au lancement de la partie SUIVANTE.

    Mesuré dans l'historique de la soirée : l'API avait déjà publié les kills au
    tick où la sortie est détectée (21:57:14 → bilan 21:58:47, trois fois de
    suite exactement 93 s plus tard). L'attente fixe de 90 s était donc perdue,
    et le matchmaking la battait — d'où l'affichage en pleine partie suivante.

    Ce qu'on attend n'est pas un délai, c'est que les compteurs ARRÊTENT de
    bouger : un relevé identique au précédent, et un mouvement constaté.
    """
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    h.avance(600)
    # Retour au lobby : l'API a déjà publié les kills, comme en vrai.
    assert s.relever(in_game=False, trackers=_tk(5)) is None
    sortie = h.t
    h.avance(30)                                   # un seul tour de sonde
    bilan = s.relever(in_game=False, trackers=_tk(5))
    assert bilan is not None, "le bilan attend encore alors que rien ne bouge"
    assert bilan["partie"] == 5
    assert h.t - sortie < KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S


def test_une_publication_ETALEE_ne_fige_pas_trop_tot():
    """L'autre moitié, et c'est elle qui interdit de figer à la sortie sèche :
    le 2026-08-19 à 22:37, le RP est arrivé au tick 22:37:04 et les kills au
    suivant, 31 s plus tard. Figer sur le premier mouvement aurait annoncé
    « 0 kill » à une partie qui en comptait 4."""
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0), rp=9000)
    h.avance(600)
    s.relever(in_game=False, trackers=_tk(0), rp=9000)   # sortie, rien publié
    h.avance(30)
    # Le RP bouge en premier : ça bouge encore, on ne fige pas.
    assert s.relever(in_game=False, trackers=_tk(0), rp=9042) is None
    h.avance(30)
    bilan = s.relever(in_game=False, trackers=_tk(4), rp=9042)
    assert bilan is None, "figé alors que les kills venaient juste d'arriver"
    h.avance(30)
    bilan = s.relever(in_game=False, trackers=_tk(4), rp=9042)
    assert bilan["partie"] == 4 and bilan["rp"] == 42


def test_sans_le_moindre_mouvement_le_PLAFOND_tranche():
    """Une partie sans kill et sans classé ne fait bouger aucun compteur : la
    stabilité y est vraie dès le premier tour, et ne prouve rien. Le délai reste
    le filet — c'est le seul cas où l'on attend encore."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    h.avance(600)
    s.relever(in_game=False, trackers=_tk(0))
    h.avance(30)
    assert s.relever(in_game=False, trackers=_tk(0)) is None
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S)
    assert s.relever(in_game=False, trackers=_tk(0))["partie"] == 0


# ── les points de rang ──────────────────────────────────────────────────────

def test_le_RP_GAGNE_accompagne_le_bilan():
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0), rp=9000)
    h.avance(600)
    s.relever(in_game=False, trackers=_tk(3), rp=9087)
    h.avance(30)
    assert s.relever(in_game=False, trackers=_tk(3), rp=9087)["rp"] == 87


def test_le_RP_PERDU_est_rendu_NEGATIF():
    """Une partie classée ratée coûte des points, et c'est ce qui se commente le
    mieux en direct."""
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0), rp=9000)
    h.avance(600)
    s.relever(in_game=False, trackers=_tk(0), rp=8965)
    h.avance(30)
    assert s.relever(in_game=False, trackers=_tk(0), rp=8965)["rp"] == -35


def test_un_RP_IMMOBILE_ne_dit_RIEN():
    """Demande de l'owner : « si les points ne bougent pas, ne rien afficher —
    ça veut dire qu'il ne fait pas de rank ». Un zéro affiché ferait croire à
    une partie classée blanche, ce qui n'existe pas."""
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0), rp=9000)
    h.avance(600)
    s.relever(in_game=False, trackers=_tk(4), rp=9000)
    h.avance(30)
    assert s.relever(in_game=False, trackers=_tk(4), rp=9000)["rp"] is None


def test_un_compte_SANS_RANG_ne_dit_rien_non_plus():
    """`rp=None` — le compte n'a pas de rang, ou l'API ne l'a pas donné. Un
    absent ne se lit pas comme un zéro."""
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0))
    h.avance(600)
    s.relever(in_game=False, trackers=_tk(4))
    h.avance(30)
    assert s.relever(in_game=False, trackers=_tk(4))["rp"] is None


def test_une_partie_commencee_AVANT_qu_on_regarde_ne_chiffre_pas_son_RP():
    """Même règle que pour les kills : sans point de départ, le RP du live entier
    passerait pour celui d'une seule partie.

    Sans base, il n'y a rien à guetter non plus — aucun mouvement ne peut être
    constaté — donc c'est le plafond qui tranche, et il faut l'attendre."""
    from bot.core.apex.kills_live import KillsDuLive
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(50), rp=9000, premier=True)
    h.avance(600)
    s.relever(in_game=False, trackers=_tk(55), rp=9100)
    h.avance(KillsDuLive.ATTENTE_MAX_APRES_PARTIE_S + 1)
    assert s.relever(in_game=False, trackers=_tk(55), rp=9100)["rp"] is None


def test_un_SAUT_de_RP_invraisemblable_est_ecarte():
    """Un changement de saison remet le RP à plat : le delta n'est plus le
    résultat d'une partie. Même prudence que le plafond des kills."""
    h = _Horloge()
    s = _suivi(h)
    s.relever(in_game=True, trackers=_tk(0), rp=9000)
    h.avance(600)
    s.relever(in_game=False, trackers=_tk(2), rp=1000)
    h.avance(30)
    bilan = s.relever(in_game=False, trackers=_tk(2), rp=1000)
    assert bilan["rp"] is None
    assert bilan["partie"] == 2          # les kills, eux, restent mesurés


# ── les entrées tordues ─────────────────────────────────────────────────────

@pytest.mark.parametrize("trackers", [None, {}, {"kills": "beaucoup"}])
def test_des_trackers_ILLISIBLES_ne_font_pas_lever(trackers):
    """Ils viennent d'une API tierce qui glisse des chaînes là où on attend des
    nombres — piège déjà payé ici."""
    s = _suivi()
    s.relever(in_game=True, trackers=trackers)
    s.relever(in_game=False, trackers=trackers)
