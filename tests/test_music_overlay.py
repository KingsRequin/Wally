"""Le morceau en cours s'affiche à l'écran quand on le demande.

Quatrième et dernier lot du §10 : « n'importe quel viewer peut demander ce qui
passe : Wally le dit ET l'affiche sur le live ».

Deux choix qui distinguent ce widget de tous ceux ajoutés récemment :

  · Il COHABITE. L'avalanche et le spam de popups prennent l'écran seuls et
    effacent Wally ; une étiquette de titre, non — elle s'affiche pendant que la
    vie continue. C'est la question que le cliquet `wally_visible` force à se
    poser à chaque nouvel élément.

  · Il ne s'affiche QUE sur la chaîne maison. L'overlay appartient au live
    d'Azraël : une demande venue d'un salon Discord ou d'une chaîne invitée
    reçoit une réponse écrite, pas un affichage chez lui.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _narrateur(live: bool = True):
    from bot.intelligence.overlay_narrator import OverlayNarrator
    return OverlayNarrator(overlay_feed=MagicMock(), llm=MagicMock(),
                           is_live=lambda: live)


def _widget(n):
    appels = n._feed.widget.call_args_list
    return appels[-1] if appels else None


def _bot(*, etat=None, narrateur=None):
    bot = MagicMock()
    service = MagicMock()
    service.etat.return_value = etat
    service.commander = AsyncMock(return_value={"ok": True})
    bot.music = service
    bot.discord_bot.overlay_narrator = narrateur
    return bot


# ── le narrateur ────────────────────────────────────────────────────────────

def test_le_morceau_part_a_l_ecran():
    n = _narrateur()
    assert n.show_music("Numb", "Linkin Park", joue=True) is True
    appel = _widget(n)
    assert appel.args[0] == "music_now"
    assert appel.kwargs["title"] == "Numb"
    assert appel.kwargs["artist"] == "Linkin Park"


def test_hors_live_rien_ne_part():
    n = _narrateur(live=False)
    assert n.show_music("Numb", "Linkin Park", joue=True) is False
    assert _widget(n) is None


def test_sans_TITRE_on_n_affiche_pas_une_etiquette_vide():
    """Une carte vide à l'écran est pire que pas de carte."""
    n = _narrateur()
    assert n.show_music("", "Linkin Park", joue=True) is False
    assert _widget(n) is None


def test_le_MEME_morceau_ne_reclignote_pas_a_chaque_demande():
    """Cinq personnes demandent le titre en dix secondes : la carte ne doit pas
    repartir cinq fois. Wally répond quand même à chacune — c'est l'AFFICHAGE
    qu'on rationne, pas la parole."""
    n = _narrateur()
    assert n.show_music("Numb", "Linkin Park", joue=True) is True
    assert n.show_music("Numb", "Linkin Park", joue=True) is False


def test_un_AUTRE_morceau_s_affiche_tout_de_suite():
    """Le rationnement porte sur la répétition, pas sur le temps : quand la
    musique change, l'écran doit suivre."""
    n = _narrateur()
    n.show_music("Numb", "Linkin Park", joue=True)
    assert n.show_music("In The End", "Linkin Park", joue=True) is True


def test_les_textes_sont_bornes():
    """Ils viennent d'une page web et finissent en dur à l'écran."""
    n = _narrateur()
    n.show_music("x" * 500, "y" * 500, joue=True)
    k = _widget(n).kwargs
    assert len(k["title"]) <= 80 and len(k["artist"]) <= 80


# ── depuis le chat ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demander_le_titre_l_AFFICHE_aussi():
    """Le §10 : Wally le dit ET l'affiche."""
    from bot.core.music_tool import run_music_tool
    n = _narrateur()
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True},
               narrateur=n)
    out = await run_music_tool(bot, {"action": "now"}, roles=[], narrateur=n)
    assert "Numb" in out
    assert _widget(n) is not None


@pytest.mark.asyncio
async def test_sans_narrateur_la_reponse_ecrite_marche_QUAND_MEME():
    """Depuis Discord ou une chaîne invitée : on répond, on n'affiche pas chez
    Azraël. Et l'absence d'écran ne doit pas faire échouer la réponse."""
    from bot.core.music_tool import run_music_tool
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True})
    out = await run_music_tool(bot, {"action": "now"}, roles=[], narrateur=None)
    assert "Numb" in out


@pytest.mark.asyncio
async def test_quand_on_ne_sait_pas_on_n_affiche_RIEN():
    """Pas de carte « je ne sais pas » sur le live : c'est une réponse de chat."""
    from bot.core.music_tool import run_music_tool
    n = _narrateur()
    out = await run_music_tool(_bot(etat=None, narrateur=n), {"action": "now"},
                               roles=[], narrateur=n)
    assert "sais pas" in out.lower()
    assert _widget(n) is None


@pytest.mark.asyncio
async def test_un_ECRAN_en_panne_ne_casse_pas_la_reponse():
    """Le narrateur peut lever (bus overlay indisponible). La personne doit
    quand même obtenir son titre."""
    from bot.core.music_tool import run_music_tool
    n = MagicMock()
    n.show_music.side_effect = RuntimeError("bus mort")
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True})
    out = await run_music_tool(bot, {"action": "now"}, roles=[], narrateur=n)
    assert "Numb" in out


# ── les points de câblage ───────────────────────────────────────────────────

def test_l_element_est_declare_et_placable():
    from bot.core.overlay_elements import LIBELLES
    from bot.core.overlay_layout import _ORDRE_DEFAUT, ELEMENTS

    assert LIBELLES["music_now"]["nom"] and LIBELLES["music_now"]["description"]
    assert "music_now" in ELEMENTS
    assert "music_now" in _ORDRE_DEFAUT


def test_il_COHABITE_et_laisse_Wally_a_l_ecran():
    """Le choix que le cliquet `wally_visible` force à faire. Une étiquette de
    titre n'est pas un spectacle : elle n'a aucune raison d'effacer l'avatar,
    contrairement à l'avalanche ou au spam de popups."""
    from bot.core.overlay_layout import ELEMENTS

    assert ELEMENTS["music_now"]["solo"] is False
    assert ELEMENTS["music_now"]["wally_visible"] is True


def test_la_page_le_connait_et_sait_le_dessiner():
    from pathlib import Path

    statique = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
    assert '"music_now"' in (statique / "overlay_layout.js").read_text(encoding="utf-8")
    html = (statique / "overlay.html").read_text(encoding="utf-8")
    assert 'data-element="music_now"' in html
    assert "music-now" in html          # le style
    assert "music_now(" in (statique / "overlay.js").read_text(encoding="utf-8")


def test_le_bouton_d_essai_a_de_quoi_montrer():
    from bot.dashboard.routes.overlay import _ECHANTILLONS
    assert _ECHANTILLONS["music_now"]["title"]


# ── la pochette ─────────────────────────────────────────────────────────────
#
# Le disque de l'overlay montre la pochette du morceau et lui emprunte sa
# couleur. Elle n'est PAS rapportée par l'extension : elle se dérive de l'url de
# la page, ce qui n'a rien coûté chez Azraël — une extension hors Web Store ne
# se met jamais à jour seule, et lui en demander une n'est jamais gratuit.

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=kXYiU_JCYtU",
    "https://m.youtube.com/watch?v=kXYiU_JCYtU",
    "https://music.youtube.com/watch?v=kXYiU_JCYtU&list=RDAMVM",
    "https://youtu.be/kXYiU_JCYtU",
    "https://youtu.be/kXYiU_JCYtU?t=42",
])
def test_la_pochette_se_derive_de_l_url_du_morceau(url):
    from bot.core.music import vignette
    assert vignette(url) == "https://i.ytimg.com/vi/kXYiU_JCYtU/mqdefault.jpg"


@pytest.mark.parametrize("url", [
    "",
    "https://www.youtube.com/",                       # l'accueil : pas de vidéo
    "https://www.youtube.com/results?search_query=numb",
    "https://www.youtube.com/watch?v=trop_court",
    "https://www.youtube.com/watch?v=beaucoup_trop_long_pour_un_id",
    "https://www.youtube.com/watch?v=onze/carac",     # onze signes, mauvais jeu
])
def test_sans_video_identifiable_il_n_y_a_PAS_de_pochette(url):
    """La chaîne vide et non une image par défaut : l'overlay sait montrer un
    disque neutre, et une pochette FAUSSE sur un morceau serait pire que pas de
    pochette du tout — c'est le chat qui la verrait en premier."""
    from bot.core.music import vignette
    assert vignette(url) == ""


@pytest.mark.parametrize("url", [
    "https://youtube.com.pirate.fr/watch?v=kXYiU_JCYtU",
    "https://notyoutube.com/watch?v=kXYiU_JCYtU",
    "https://evil.example/watch?v=kXYiU_JCYtU",
    "javascript:alert(1)",
    "http://[::1/watch?v=kXYiU_JCYtU",                # url illisible
])
def test_un_HOTE_qui_n_est_pas_youtube_ne_donne_aucune_pochette(url):
    """L'url vient d'une page web — entrée non fiable — et ce qu'on en tire part
    dans un `<img src>` sur le live. La liste des hôtes est BLANCHE et non un
    `in` sur la chaîne : « youtube.com.pirate.fr » contient « youtube.com »."""
    from bot.core.music import vignette
    assert vignette(url) == ""


def test_l_ecran_recoit_la_pochette_du_morceau():
    n = _narrateur()
    n.show_music("Numb", "Linkin Park", joue=True,
                 url="https://www.youtube.com/watch?v=kXYiU_JCYtU")
    assert _widget(n).kwargs["cover"] == \
        "https://i.ytimg.com/vi/kXYiU_JCYtU/mqdefault.jpg"


def test_sans_url_la_carte_part_QUAND_MEME_sans_pochette():
    """Le disque n'est pas une condition d'affichage : un morceau dont on n'a
    pas l'image reste un morceau."""
    n = _narrateur()
    assert n.show_music("Numb", "Linkin Park", joue=True) is True
    assert _widget(n).kwargs["cover"] == ""


def test_l_url_BRUTE_ne_part_jamais_a_l_ecran():
    """Seule l'adresse RECONSTRUITE traverse. L'url reçue peut pointer n'importe
    où : elle sert à dériver, jamais à afficher."""
    n = _narrateur()
    n.show_music("Numb", "Linkin Park", joue=True,
                 url="https://www.youtube.com/watch?v=kXYiU_JCYtU&secret=x")
    envoye = " ".join(str(v) for v in _widget(n).kwargs.values())
    assert "secret=x" not in envoye
    assert "youtube.com/watch" not in envoye


@pytest.mark.asyncio
async def test_demander_le_titre_affiche_AUSSI_la_pochette():
    """L'autre chemin d'affichage : « c'est quoi la musique ? » dans le chat. Il
    a sa propre construction d'appel — une pochette branchée d'un seul côté est
    exactement la panne que les tests de parité cherchent."""
    from bot.core.music_tool import run_music_tool
    n = _narrateur()
    bot = _bot(etat={"titre": "Numb", "artiste": "Linkin Park", "joue": True,
                     "url": "https://www.youtube.com/watch?v=kXYiU_JCYtU"},
               narrateur=n)
    await run_music_tool(bot, {"action": "now"}, roles=[], narrateur=n)
    assert _widget(n).kwargs["cover"].endswith("/kXYiU_JCYtU/mqdefault.jpg")


def test_le_bouton_d_essai_montre_une_VRAIE_pochette():
    """Sinon le panneau de mise en scène mesure et montre une carte que le vrai
    chemin ne sait pas produire."""
    from bot.dashboard.routes.overlay import _ECHANTILLONS
    assert _ECHANTILLONS["music_now"]["cover"].startswith("https://i.ytimg.com/vi/")


def test_la_page_sait_dessiner_le_disque_et_en_tirer_la_couleur():
    from pathlib import Path

    statique = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
    js = (statique / "overlay.js").read_text(encoding="utf-8")
    html = (statique / "overlay.html").read_text(encoding="utf-8")
    assert "music-disque" in html and "music-disque" in js
    assert "couleurDominante" in js
    # La couleur est posée sur la CARTE : sur `:root`, elle survivrait au départ
    # du widget et teinterait le suivant.
    assert "--accent-morceau" in html
    assert 'box.style.setProperty("--accent-morceau"' in js


def test_l_ombre_et_la_DECOUPE_ne_sont_jamais_sur_le_meme_element():
    """Le déroulé de la pilule se fait au `clip-path`, qui coupe TOUT ce que
    porte son élément — `box-shadow` compris, et pas seulement le temps de
    l'animation : `inset(0 0 0 0)` colle à la boîte, donc la lueur colorée
    resterait amputée pour toujours. Un `filter: drop-shadow` ne sauve rien, il
    s'applique AVANT le clip. Même famille de piège que l'`overflow: hidden` qui
    avalait la pointe de bulle : d'où deux couches, l'ombre dehors et la découpe
    dedans."""
    from pathlib import Path
    import re

    html = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
            / "overlay.html").read_text(encoding="utf-8")

    def regle(selecteur):
        return re.search(re.escape(selecteur) + r"\s*\{([^}]*)\}", html).group(1)

    porteur = regle(".music-now")
    assert "box-shadow" in porteur
    assert "clip-path" not in porteur

    pilule = regle(".music-now .music-pilule")
    assert "clip-path" in pilule
    # `inset` seul est permis ici : la pilule n'a pas d'ombre PORTÉE à protéger.
    # L'ombre interne (`inset 0 1px 0 …`) reste dans la boîte, le clip ne la
    # touche pas.
    ombres = re.findall(r"box-shadow:([^;]*);", pilule)
    assert all("inset" in o for o in ombres), ombres

    # Et le JS monte bien les deux couches, sans quoi le style ne s'applique à
    # rien : un test vert ne prouve pas qu'une carte MONTE.
    js = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
          / "overlay.js").read_text(encoding="utf-8")
    assert 'el("div", "music-pilule")' in js


def test_la_bordure_suit_la_couleur_de_la_pochette():
    """Demandé par l'owner. Elle est DILUÉE — à pleine opacité, le contour de la
    carte deviendrait un liseré fluo. Sans pochette, elle retombe sur le trait
    des autres cartes de l'overlay plutôt que de disparaître."""
    from pathlib import Path
    import re

    statique = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
    html = (statique / "overlay.html").read_text(encoding="utf-8")
    js = (statique / "overlay.js").read_text(encoding="utf-8")

    pilule = re.search(r"\.music-now \.music-pilule\s*\{([^}]*)\}", html).group(1)
    assert "border: 1px solid var(--bord-morceau)" in pilule
    # Le repli, sur la carte : sans lui, une pochette absente laisserait une
    # bordure vide, donc pas de bordure du tout.
    carte = re.search(r"\n    \.music-now\s*\{([^}]*)\}", html).group(1)
    assert "--bord-morceau: var(--line)" in carte
    assert 'box.style.setProperty("--bord-morceau"' in js
