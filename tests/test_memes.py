"""Bibliothèque de memes déposés à la main.

Wally ne VOIT pas ces images : sa seule prise dessus est la description. Et le
dossier est relu à chaque tirage — redémarrer le bot pour qu'une image apparaisse
serait absurde.
"""
import pytest

from bot.core.memes import MemeLibrary


@pytest.fixture
def lib(tmp_path):
    (tmp_path / "azrael-blame-le-ping.jpg").write_bytes(b"x")
    (tmp_path / "requin_rage.png").write_bytes(b"x")
    (tmp_path / "notes.md").write_text("pas une image")
    return MemeLibrary(tmp_path)


def test_seules_les_images_sont_listees(lib):
    noms = {m["name"] for m in lib.list()}
    assert noms == {"azrael-blame-le-ping.jpg", "requin_rage.png"}


def test_le_nom_du_fichier_sert_de_description(lib):
    m = next(m for m in lib.list() if m["name"].startswith("azrael"))
    assert m["description"] == "azrael blame le ping"


def test_un_fichier_texte_prime_sur_le_nom(tmp_path):
    (tmp_path / "truc.jpg").write_bytes(b"x")
    (tmp_path / "truc.txt").write_text("le jour où il a rage quit en pleine game")
    assert MemeLibrary(tmp_path).list()[0]["description"].startswith("le jour où")


def test_deux_images_de_meme_nom_ont_chacune_leur_description(tmp_path):
    """`chat.gif` et `chat.jpg` sont deux images DIFFÉRENTES.

    Avec le seul `with_suffix(".txt")`, elles se partageaient `chat.txt` et
    héritaient de la même description : Wally en commentait une en décrivant
    l'autre. Dix paires du dossier de prod étaient dans ce cas.
    """
    (tmp_path / "chat.gif").write_bytes(b"x")
    (tmp_path / "chat.jpg").write_bytes(b"x")
    (tmp_path / "chat.gif.txt").write_text("un chat qui tombe du canapé")
    (tmp_path / "chat.jpg.txt").write_text("un chat qui hurle sur son maître")
    par_nom = {m["name"]: m["description"] for m in MemeLibrary(tmp_path).list()}
    assert par_nom["chat.gif"] == "un chat qui tombe du canapé"
    assert par_nom["chat.jpg"] == "un chat qui hurle sur son maître"


def test_l_extension_complete_prime_sur_l_ancienne_forme(tmp_path):
    """L'ancienne forme reste acceptée : les .txt déjà déposés valent toujours."""
    (tmp_path / "truc.jpg").write_bytes(b"x")
    (tmp_path / "truc.txt").write_text("ancienne forme")
    assert MemeLibrary(tmp_path).list()[0]["description"] == "ancienne forme"
    (tmp_path / "truc.jpg.txt").write_text("nouvelle forme")
    assert MemeLibrary(tmp_path).list()[0]["description"] == "nouvelle forme"


def test_un_mot_vide_ne_suffit_pas_a_retenir_un_meme(tmp_path):
    """« qui », « pas », « une » passent le filtre de longueur et figurent dans
    presque toutes les descriptions. En retenant tout meme ayant UN mot en
    commun, « chat qui hurle » retenait quasi tout le dossier et retombait sur
    un tirage au hasard. On garde les meilleurs, pas les vaguement concernés."""
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "a.txt").write_text("un chien qui dort tranquillement")
    (tmp_path / "b.jpg").write_bytes(b"x")
    (tmp_path / "b.txt").write_text("un chat qui hurle sur son maître")
    lib = MemeLibrary(tmp_path)
    assert {lib.pick("chat qui hurle")["name"] for _ in range(12)} == {"b.jpg"}


# Une réserve de taille réaliste pour les tests du classement et du refus : sur
# cinq memes, les fréquences de mots ne veulent rien dire.
_TAILLE_RESERVE = 30
# Le mot « meme » revient dans un cinquieme des phrases, comme dans le vrai
# dossier (33 descriptions sur 172). Sans ca il serait RARE ici, donc
# discriminant, et « le meme sur les cheaters » se classerait sur lui.
_REMPLISSAGE = [
    "un joueur qui rale sur le ping et qui accuse sa connexion",
    "une equipe qui se dispute sur le loot dans une zone",
    "le meme du joueur qui demande une rez alors qu il pouvait tenir",
    "des joueurs qui courent sur la zone qui se referme",
    "un streamer qui fixe son ecran sans rien dire pendant une minute",
    "le meme de la legende qui saute du dropship avec son escouade",
    "le mec qui prend tout le loot et qui part sans les autres",
    "quelqu un qui rate son tir a bout portant et qui se retourne",
    "le meme sur la partie qui se termine au dernier cercle",
    "un joueur qui se plaint des degats de son arme preferee",
    "le silence gene apres une defaite en finale de tournoi",
    "un chat sur un clavier pendant une partie classee",
    "des amis qui rigolent devant un ecran de fin de partie",
    "le meme sur tout le monde qui parle en meme temps sur le vocal",
]


def _reserve(tmp_path, sujets):
    """Une réserve de taille réaliste : les `sujets` voulus, noyés dans du
    remplissage français, comme le vrai dossier de prod."""
    for nom, description in sujets.items():
        (tmp_path / nom).write_bytes(b"x")
        (tmp_path / f"{nom}.txt").write_text(description, encoding="utf-8")
    for i in range(_TAILLE_RESERVE):
        (tmp_path / f"fond{i}.jpg").write_bytes(b"x")
        (tmp_path / f"fond{i}.jpg.txt").write_text(
            _REMPLISSAGE[i % len(_REMPLISSAGE)], encoding="utf-8"
        )
    return MemeLibrary(tmp_path)


def test_une_demande_totalement_etrangere_est_avouee(tmp_path):
    """Ce test EXIGEAIT l'inverse — « mieux vaut un meme au hasard que pas de
    meme du tout ». Wally sortait un hors-sujet et le commentait comme si
    c'était le bon. Arbitrage de l'owner le 2026-08-31 : il l'avoue.

    Mais SEULEMENT quand rien ne correspond, pas un mot. Deux tentatives de
    refus plus fin ont cassé la prod — cf. le commentaire de `_classer`.
    """
    lib = _reserve(tmp_path, {"chien.jpg": "un chien qui dort tranquillement"})
    assert lib.pick("astrophysique quantique") is None


def test_sous_une_petite_reserve_on_ne_refuse_pas(tmp_path):
    """`les` manque à un dossier de cinq memes, `cheaters` non : il correspond
    quelque chose, donc on montre."""
    petite = dict(enumerate(_REMPLISSAGE[:4]))
    for i, description in petite.items():
        (tmp_path / f"m{i}.jpg").write_bytes(b"x")
        (tmp_path / f"m{i}.jpg.txt").write_text(description, encoding="utf-8")
    (tmp_path / "cheat.jpg").write_bytes(b"x")
    (tmp_path / "cheat.jpg.txt").write_text(
        "Moe jette le sac CHEATERS dehors", encoding="utf-8")
    # `les` manque a ce dossier de cinq, `cheaters` non : on ne doit pas refuser.
    assert MemeLibrary(tmp_path).pick("les cheaters")["name"] == "cheat.jpg"


def test_un_dossier_absent_ne_leve_pas(tmp_path):
    assert MemeLibrary(tmp_path / "nexiste-pas").list() == []
    assert MemeLibrary(tmp_path / "nexiste-pas").pick() is None


def test_une_image_trop_lourde_est_ignoree(tmp_path):
    """Elle mettrait plus de temps à charger que le widget à passer."""
    (tmp_path / "enorme.png").write_bytes(b"x" * (9 * 1024 * 1024))
    assert MemeLibrary(tmp_path).list() == []


def test_le_dossier_est_relu_a_chaque_fois(tmp_path):
    """Déposer une image ne doit pas demander de redémarrage."""
    lib = MemeLibrary(tmp_path)
    assert lib.list() == []
    (tmp_path / "nouveau.gif").write_bytes(b"x")
    assert len(lib.list()) == 1


def test_jamais_deux_fois_le_meme_d_affilee(lib):
    """Deux fois la même image passerait pour un bug."""
    premier = lib.pick()["name"]
    assert lib.pick()["name"] != premier


def test_avec_un_seul_meme_il_se_repete_quand_meme(tmp_path):
    (tmp_path / "seul.jpg").write_bytes(b"x")
    lib = MemeLibrary(tmp_path)
    assert lib.pick()["name"] == "seul.jpg"
    assert lib.pick()["name"] == "seul.jpg"


def test_un_indice_oriente_le_choix(lib):
    """« montre le meme du ping » doit tomber sur le bon."""
    for _ in range(5):
        assert lib.pick("le ping")["name"] == "azrael-blame-le-ping.jpg"


def test_un_indice_sans_aucune_correspondance_ne_sort_rien(tmp_path):
    """Même arbitrage, même bornage : aucun des deux mots n'existe nulle part."""
    lib = _reserve(tmp_path, {"chien.jpg": "un chien qui dort tranquillement"})
    assert lib.pick("licorne quantique") is None


# ── classement : le défaut vécu en prod le 2026-08-31 ──

def _reserve_apex(tmp_path):
    """Un dossier qui reproduit la forme du vrai : des descriptions en français,
    donc pleines de mots vides, et un seul meme qui parle vraiment du sujet."""
    return _reserve(tmp_path, {
        "cheat.jpg": "Moe jette le sac CHEATERS dehors et le retrouve derriere lui",
        "pingdur.jpg": "le lag et le pingdur qui ruinent une partie entiere",
    })


def test_les_mots_vides_ne_noient_plus_le_sujet(tmp_path):
    """LE défaut vécu : « le meme sur les cheaters » ne sortait jamais le meme
    sur les cheaters.

    L'ancien tirage comptait les mots de plus de deux lettres trouves dans la
    description. Or « sur », « les », « qui », « une » en font trois et vivent
    dans presque toutes les phrases francaises : ils marquaient un point PARTOUT,
    le meilleur score montait à deux grace à eux seuls, et le seul meme qui
    parlait de triche — à un point — tombait hors du lot retenu. Il était donc
    littéralement impossible à obtenir en le demandant dans une phrase.
    """
    lib = _reserve_apex(tmp_path)
    for demande in ("cheaters", "les cheaters", "le meme sur les cheaters"):
        assert lib.pick(demande)["name"] == "cheat.jpg", demande


def test_une_demande_generique_sort_un_meme(tmp_path):
    """LE défaut qui a cassé la prod le 2026-09-01.

    Le refus comptait la PROPORTION de mots de la demande introuvables dans la
    réserve. « montre un meme » en a deux sur trois — `montre` n'est écrit dans
    aucune description, et pourquoi le serait-il — donc Wally répondait qu'il
    n'avait pas ce meme. Idem « envoie un meme », « balance un meme ». Un verbe
    d'instruction est introuvable pour la même raison qu'un sujet absent : rien
    ne les distingue, il ne faut donc PAS les compter.
    """
    lib = _reserve_apex(tmp_path)
    for demande in ("montre un meme", "envoie un meme", "balance un meme",
                    "montre moi un meme", "wally montre un meme"):
        assert lib.pick(demande) is not None, demande


def test_le_sujet_prime_meme_noye_dans_une_phrase(tmp_path):
    lib = _reserve_apex(tmp_path)
    assert lib.pick("un meme sur le pingdur")["name"] == "pingdur.jpg"


def test_la_recherche_ignore_les_accents_et_la_casse(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "a.txt").write_text("une equipe qui se dispute", encoding="utf-8")
    (tmp_path / "b.jpg").write_bytes(b"x")
    (tmp_path / "b.txt").write_text("un chien qui dort", encoding="utf-8")
    assert MemeLibrary(tmp_path).pick("ÉQUIPE")["name"] == "a.jpg"


def test_un_mot_entier_et_pas_une_sous_chaine(tmp_path):
    """« chat » ne doit pas ramener « chatouille » : l'ancien filtre testait
    l'appartenance à la chaine, donc tout prefixe interne comptait."""
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "a.txt").write_text("des chatouilles entre amis", encoding="utf-8")
    (tmp_path / "b.jpg").write_bytes(b"x")
    (tmp_path / "b.txt").write_text("un chat sur un clavier", encoding="utf-8")
    assert MemeLibrary(tmp_path).pick("chat")["name"] == "b.jpg"


def test_une_description_ajoutee_est_vue_sans_redemarrage(tmp_path):
    """L'index ne se reconstruit que si le dossier a bouge — encore faut-il
    qu'il voie bouger un SIDECAR, pas seulement l'arrivee d'une image. Sans ca,
    corriger une description depuis l'atelier resterait sans effet sur les
    tirages jusqu'au prochain depot de fichier."""
    lib = _reserve(tmp_path, {"b.jpg": "une photo sans grand interet"})
    assert lib.pick("dinosaure") is None   # le mot n'existe encore nulle part
    (tmp_path / "b.jpg.txt").write_text("un dinosaure en costume", encoding="utf-8")
    assert lib.pick("dinosaure")["name"] == "b.jpg"


# ── sécurité : les fichiers sont servis publiquement ──

def test_un_nom_ne_peut_pas_remonter_l_arborescence(lib, tmp_path):
    (tmp_path.parent / "secret.png").write_bytes(b"x")
    assert lib.resolve("../secret.png") is None


def test_un_nom_valide_est_resolu(lib):
    assert lib.resolve("requin_rage.png") is not None


def test_un_fichier_absent_ou_non_image_est_refuse(lib):
    assert lib.resolve("notes.md") is None
    assert lib.resolve("inconnu.png") is None
    assert lib.resolve("") is None


# ── widget ──

def test_le_widget_choisit_une_image_et_sa_description(tmp_path):
    """La description revient à Wally, l'overlay ne reçoit que l'image.

    Elle existe pour qu'il commente juste une image qu'il ne voit pas — c'est un
    contexte interne. L'afficher en légende doublait à l'écran ce qu'il allait
    dire, et exposait aux spectateurs une note écrite pour lui.
    """
    from unittest.mock import MagicMock

    from bot.core.overlay_feed import OverlayFeed
    from bot.intelligence.overlay_narrator import OverlayNarrator

    (tmp_path / "azrael-blame-le-ping.jpg").write_bytes(b"x")
    feed = OverlayFeed()
    n = OverlayNarrator(feed, MagicMock(), lambda: True, memes=MemeLibrary(tmp_path))
    q = feed.subscribe()
    out = n.show_widget("meme", "")
    assert out["name"] == "azrael-blame-le-ping.jpg"
    assert out["description"] == "azrael blame le ping"
    ev = [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "widget"][0]
    assert ev["params"]["src"].endswith("azrael-blame-le-ping.jpg")
    assert "caption" not in ev["params"]


def test_le_widget_ne_montre_rien_si_le_dossier_est_vide(tmp_path):
    from unittest.mock import MagicMock

    from bot.core.overlay_feed import OverlayFeed
    from bot.intelligence.overlay_narrator import OverlayNarrator

    n = OverlayNarrator(OverlayFeed(), MagicMock(), lambda: True,
                        memes=MemeLibrary(tmp_path))
    assert n.show_widget("meme", "") is None


def test_un_nom_avec_espaces_est_encode_dans_l_url(tmp_path):
    """Sans encodage, l'overlay demanderait une URL tronquée au premier espace."""
    from unittest.mock import MagicMock

    from bot.core.overlay_feed import OverlayFeed
    from bot.intelligence.overlay_narrator import OverlayNarrator

    (tmp_path / "le chat de requin.png").write_bytes(b"x")
    feed = OverlayFeed()
    n = OverlayNarrator(feed, MagicMock(), lambda: True, memes=MemeLibrary(tmp_path))
    q = feed.subscribe()
    n.show_widget("meme", "")
    ev = [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "widget"][0]
    assert ev["params"]["src"].endswith("le%20chat%20de%20requin.png")


def test_le_webp_est_servi_comme_une_image(tmp_path):
    """Sans type explicite, l'overlay recevait `application/octet-stream`.

    L'image Docker (Python 3.12, sans /etc/mime.types) ignore `.webp` :
    `FileResponse` retombait alors sur le type générique. Le navigateur d'OBS
    renifle le contenu d'un `<img>` et affichait quand même, mais rien ne
    l'oblige — et le dossier de prod compte seize webp.
    """
    from bot.core.memes import media_type

    assert media_type(tmp_path / "requin.webp") == "image/webp"
    assert media_type(tmp_path / "requin.WEBP") == "image/webp"
    assert media_type(tmp_path / "requin.gif") == "image/gif"
    assert media_type(tmp_path / "requin.jpeg") == "image/jpeg"


@pytest.mark.asyncio
async def test_la_route_annonce_le_type_meme_sans_table_mime_systeme(tmp_path, monkeypatch):
    """Le test simule l'image Docker : `mimetypes` y ignore tout.

    Sans ce décor, le test passerait sur la machine de dev (Debian fournit
    /etc/mime.types, qui connaît `.webp`) et raterait le défaut là où il vit :
    dans le conteneur.
    """
    import starlette.responses

    from bot.dashboard.routes.overlay import get_meme

    # On patche la référence de starlette, pas `mimetypes.guess_type` : le module
    # importe le symbole directement, et patcher la table d'origine ne changeait
    # rien — le test passait alors même sur le code défaillant.
    monkeypatch.setattr(starlette.responses, "guess_type", lambda *a, **k: (None, None))
    (tmp_path / "requin.webp").write_bytes(b"x")
    state = type("W", (), {"memes": MemeLibrary(tmp_path)})()
    req = type("R", (), {"app": type("A", (), {"state": type("S", (), {"wally": state})()})()})()

    resp = await get_meme("requin.webp", req)
    assert resp.media_type == "image/webp"


def test_les_videos_sont_listees_a_part_des_images(tmp_path):
    """Wally affiche dans un <img> : une vidéo dans sa liste serait cassée.

    Le rotateur, lui, sait jouer les deux. Deux consommateurs, deux besoins —
    d'où deux listes.
    """
    (tmp_path / "chat.png").write_bytes(b"x")
    (tmp_path / "requin.mp4").write_bytes(b"x")
    lib = MemeLibrary(tmp_path)

    assert [m["name"] for m in lib.list()] == ["chat.png"]
    assert [(m["name"], m["genre"]) for m in lib.list_medias()] == [
        ("chat.png", "image"),
        ("requin.mp4", "video"),
    ]


def test_la_route_peut_servir_une_video(tmp_path):
    """`resolve` sert un fichier ; il n'a pas à savoir l'afficher."""
    (tmp_path / "requin.mp4").write_bytes(b"x")
    lib = MemeLibrary(tmp_path)

    assert lib.resolve("requin.mp4") == tmp_path / "requin.mp4"
    assert lib.resolve("requin.exe") is None


def test_le_type_mime_des_videos(tmp_path):
    from bot.core.memes import media_type

    assert media_type(tmp_path / "a.mp4") == "video/mp4"
    assert media_type(tmp_path / "a.WEBM") == "video/webm"
