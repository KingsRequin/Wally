"""Pendu — le chat propose des lettres.

Le mot ne doit JAMAIS partir vers l'overlay tant qu'il n'est pas terminé : les
viewers le liraient à l'écran et le jeu n'aurait aucun intérêt.
"""
from unittest.mock import MagicMock

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _n(live=True):
    feed = OverlayFeed()
    return OverlayNarrator(feed, MagicMock(), lambda: live), feed


def _events(feed_queue):
    return [e for e in (feed_queue.get_nowait() for _ in range(feed_queue.qsize()))
            if e["type"] == "widget"]


def test_le_mot_n_est_jamais_publie_avant_la_fin():
    n, feed = _n()
    q = feed.subscribe()
    n.start_hangman("fusée")
    ev = _events(q)[0]
    assert ev["params"]["word"] == ""
    assert "".join(ev["params"]["mask"]) == ""     # tout est masqué


def test_une_lettre_trouvee_se_revele():
    n, feed = _n()
    n.start_hangman("fusée")
    q = feed.subscribe()
    n._count_hangman("alice", "u")
    ev = _events(q)[-1]
    assert ev["params"]["mask"][1] == "u"
    assert ev["params"]["misses"] == 0


def test_les_accents_sont_ignores():
    """« fusée » se devine avec un « e » : le chat ne tape pas les accents."""
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "e")
    assert "e" in n._hangman["found"]


def test_une_lettre_absente_compte_une_faute():
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "z")
    assert n._hangman["missed"] == ["z"]


def test_une_lettre_deja_proposee_ne_recompte_pas():
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "z")
    n._count_hangman("bob", "z")
    assert n._hangman["missed"] == ["z"]


def test_un_mot_entier_n_est_pas_une_proposition():
    """Sinon chaque message du chat proposerait des lettres."""
    n, _ = _n()
    n.start_hangman("fusée")
    n._count_hangman("alice", "salut les gars")
    assert not n._hangman["found"] and not n._hangman["missed"]


def test_la_partie_est_gagnee_quand_tout_est_trouve():
    n, feed = _n()
    n.start_hangman("fusee")
    q = feed.subscribe()
    for lettre in "fuse":
        n._count_hangman("alice", lettre)
    ev = _events(q)[-1]
    assert ev["params"]["won"] is True
    assert ev["params"]["word"] == "fusee"        # révélé à la fin seulement
    assert n._hangman is None


def test_la_partie_est_perdue_a_six_fautes():
    n, feed = _n()
    n.start_hangman("fusee")
    q = feed.subscribe()
    for lettre in "bcdgkl":
        n._count_hangman("alice", lettre)
    ev = _events(q)[-1]
    assert ev["params"]["lost"] is True and ev["params"]["misses"] == 6
    assert n._hangman is None


def test_un_mot_trop_court_est_refuse():
    n, _ = _n()
    assert n.start_hangman("ok") is False


def test_un_mot_trop_long_est_refuse():
    """Au-delà, les cases débordent du widget."""
    n, _ = _n()
    assert n.start_hangman("anticonstitutionnellement") is False


def test_pas_de_partie_hors_live():
    n, _ = _n(live=False)
    assert n.start_hangman("fusee") is False


def test_un_nouveau_live_efface_la_partie():
    n, _ = _n()
    n.start_hangman("fusee")
    n.reset_live()
    assert n._hangman is None


def test_l_espace_d_un_mot_compose_reste_visible():
    n, feed = _n()
    q = feed.subscribe()
    n.start_hangman("rocket league")
    ev = _events(q)[0]
    assert " " in ev["params"]["mask"]


# ── l'indice ne se donne qu'à la fin ──────────────────────────────────────
#
# Vu en live (2026-08-07) : Wally ouvrait la partie en annonçant l'indice dans
# la foulée — « mot de 7 lettres, indice : tu m'appelles souvent comme ça ».
# Un pendu dont on donne l'indice d'entrée n'est plus un pendu. L'indice devient
# un secours, pas une ouverture : il n'apparaît qu'à 2 essais restants.


def test_l_indice_est_cache_au_lancement():
    n, feed = _n()
    q = feed.subscribe()
    n.start_hangman("mirage", hint="un leurre")
    assert _events(q)[0]["params"]["hint"] == ""


def test_l_indice_reste_cache_tant_qu_il_reste_plus_de_deux_essais():
    n, feed = _n()
    n.start_hangman("mirage", hint="un leurre")
    q = feed.subscribe()
    for lettre in ("z", "k", "w"):          # 3 fautes sur 6 → 3 essais restants
        n._count_hangman("alice", lettre)
    assert _events(q)[-1]["params"]["hint"] == ""


def test_l_indice_apparait_a_deux_essais_restants():
    n, feed = _n()
    n.start_hangman("mirage", hint="un leurre")
    q = feed.subscribe()
    for lettre in ("z", "k", "w", "x"):     # 4 fautes sur 6 → 2 essais restants
        n._count_hangman("alice", lettre)
    assert _events(q)[-1]["params"]["hint"] == "un leurre"


def test_l_indice_est_montre_a_la_fin_de_partie():
    """Perdu, autant savoir ce qu'on cherchait."""
    n, feed = _n()
    n.start_hangman("mirage", hint="un leurre")
    q = feed.subscribe()
    for lettre in ("z", "k", "w", "x", "y", "b"):   # 6 fautes → perdu
        n._count_hangman("alice", lettre)
    dernier = _events(q)[-1]["params"]
    assert dernier["lost"] is True
    assert dernier["hint"] == "un leurre"


def test_sans_indice_fourni_rien_n_est_promis():
    n, feed = _n()
    n.start_hangman("mirage")
    q = feed.subscribe()
    for lettre in ("z", "k", "w", "x"):
        n._count_hangman("alice", lettre)
    assert _events(q)[-1]["params"]["hint"] == ""


# ── ce que le modèle LIT du pendu ─────────────────────────────────────────
#
# Vu en live (2026-08-07) : « Tu veux que je choisisse un mot ou t'as une idée
# en tête ? », `tools_called: []`. Le pendu n'a jamais été lancé, donc les
# lettres tapées ensuite n'étaient comptées par personne — `_count_hangman`
# sort sur `if not game`. Les trois symptômes venaient de là.
#
# `reasoning_system.md` porte bien la consigne « choisis un mot », mais c'est le
# prompt du chemin cognitif `[ACT]`. En CONVERSATION, le modèle ne voit que le
# schéma d'outil, qui ne disait pas qui fournit le mot.


def _hangman_params():
    from bot.intelligence.overlay_narrator import OVERLAY_TOOL_SPEC
    return OVERLAY_TOOL_SPEC["function"]["parameters"]["properties"]


def test_le_schema_dit_que_wally_choisit_le_mot():
    desc = _hangman_params()["word"]["description"].lower()
    assert "toi" in desc and "ne demande jamais" in desc


def test_le_schema_annonce_les_bornes_reellement_appliquees():
    """Il annonçait « 3 à 20 lettres » quand `start_hangman` refuse au-delà de
    16 : un mot de 18 lettres était rejeté sans que le modèle sache pourquoi."""
    assert "3 à 16" in _hangman_params()["word"]["description"]
    n, _ = _n()
    assert n.start_hangman("a" * 17) is False
    assert n.start_hangman("mirage") is True


def test_le_schema_dit_que_l_indice_reste_cache():
    """Sans ça le modèle l'annonce dans le chat, ce qui revient au même."""
    assert "caché" in _hangman_params()["hint"]["description"]


def test_le_bloc_d_etat_porte_le_mot_et_sa_consigne():
    """Le mot était tenu hors du prompt pour qu'il ne puisse pas le lâcher. Le
    prix était trop élevé : Wally ne pouvait ni donner un second indice, ni dire
    où en était la partie — il n'avait qu'un décompte de lettres. Décision de
    l'owner le 2026-08-08 : le mot entre au contexte, et la consigne de ne jamais
    l'écrire voyage avec lui, dans la même phrase."""
    n, _ = _n()
    n.start_hangman("mirage", hint="un leurre")
    block = n.current_state_block()
    assert "mirage" in block.lower()
    assert "un leurre" in block.lower()
    assert "JAMAIS" in block          # la consigne ne part jamais sans le mot
    assert "Pendu" in block


def test_le_bloc_d_etat_previent_que_les_lettres_sont_comptees():
    """Sinon Wally répond « hein ? » à chaque lettre tapée dans le chat."""
    n, _ = _n()
    n.start_hangman("mirage")
    assert "lettre" in n.current_state_block().lower()


# ── le filet doit être levé, sinon le mot est censuré à vie ───────────────────
#
# `guard_secret` inscrit le mot dans un dict de module lu par les QUATRE points
# de sortie (chat Twitch, Discord, TTS vocal, bulles d'overlay). Un chemin qui
# oublie une partie sans lever son filet rend donc ce mot — et toute suite de
# ses lettres — invisible dans TOUT ce que Wally dit, jusqu'au redémarrage du
# process. Avec un mot de l'univers de la chaîne (« apex », « ping »), la casse
# est permanente et silencieuse.

import pytest

from bot.core.secret_guard import clear_secrets, redact


@pytest.fixture(autouse=True)
def _filet_propre():
    clear_secrets()
    yield
    clear_secrets()


def test_un_nouveau_live_leve_le_filet_de_la_partie_abandonnee():
    """Une partie non terminée quand le live se coupe : `reset_live` l'oubliait
    sans lever le filet, et le mot restait interdit en sortie pour toujours."""
    n, _ = _n()
    n.start_hangman("fusee")
    assert "fusee" not in redact("le mot est fusee")     # protégé pendant la partie

    n.reset_live()

    assert redact("le mot est fusee") == "le mot est fusee"


def test_relancer_une_partie_leve_le_filet_de_la_precedente():
    n, _ = _n()
    n.start_hangman("fusee")
    n.start_hangman("planete")

    assert redact("une fusee dans le ciel") == "une fusee dans le ciel"
    assert "planete" not in redact("le mot est planete")


def test_la_victoire_ne_laisse_aucun_residu_dans_le_filet():
    """`guard_secret` recevait `word` brut et les levées passaient `display`,
    qui normalise les espaces : deux clés différentes, donc un `pop()` qui
    échoue sans un bruit et un secret qui traîne indéfiniment dans le dict de
    module. On vérifie le dict, pas seulement une phrase de sortie — un résidu
    ne se voit que sur le texte qui le déclenche."""
    from bot.core import secret_guard

    n, _ = _n()
    n.start_hangman("rocket  league")            # double espace, comme un LLM en produit
    for lettre in "rocketlagu":
        n._count_hangman("alice", lettre)

    assert n._hangman is None                    # partie gagnée
    assert secret_guard._SECRETS == {}           # et le filet est vraiment vide
    assert redact("on lance rocket league") == "on lance rocket league"


def test_l_abandon_leve_le_filet():
    n, _ = _n()
    n.start_hangman("fusee")
    n.cancel("pendu")
    assert redact("le mot est fusee") == "le mot est fusee"


def test_la_defaite_leve_le_filet():
    n, _ = _n()
    n.start_hangman("fusee")
    for lettre in "bcdghj":                      # 6 ratés = perdu
        n._count_hangman("alice", lettre)

    assert n._hangman is None
    assert redact("le mot est fusee") == "le mot est fusee"


def test_le_nombre_de_lettres_annonce_est_celui_du_mot():
    """« N lettres à deviner » doit compter les emplacements, pas les lettres
    distinctes — l'overlay dessine un slot par caractère, et le chat les voit.

    Onze annonces sur quinze étaient fausses en juillet-août 2026 : le narrateur
    rendait `len(set(...))`, donc « replicator » s'annonçait à 9 devant 10 tirets.
    """
    n, feed = _n()
    shown = n.show_widget("hangman", word="replicator", hint="on y craft",
                          sollicite=True)
    assert shown is not None
    assert shown["letters"] == 10

    q = feed.subscribe()
    n.show_widget("hangman", sollicite=True)      # « remontre le pendu »
    ev = _events(q)[-1]
    assert len(ev["params"]["mask"]) == 10        # autant de slots que d'annonce


def test_les_lettres_repetees_et_les_espaces_sont_comptes_juste():
    """« knuckle cluster » : 9 lettres distinctes, 14 emplacements alphabétiques."""
    n, _ = _n()
    shown = n.show_widget("hangman", word="knuckle cluster", hint="Apex",
                          sollicite=True)
    assert shown is not None
    assert shown["letters"] == 14
