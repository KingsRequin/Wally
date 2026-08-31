"""L'atelier des memes — Live → Médias & sons.

Le DOSSIER est la source de vérité : ces routes déposent, décrivent et
retirent, elles ne tiennent aucun index. Les tests le vérifient sur un vrai
dossier temporaire, pas sur un double : c'est le disque qui décide de ce qui
existe — et c'est aussi ce qui rend l'édition « à chaud », `MemeLibrary`
relisant le dossier à chaque tirage.
"""
import io
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image

from bot.core.memes import MemeLibrary, _describe, description_ecrite
from bot.dashboard.routes.overlay import (
    decrire_meme,
    deposer_meme,
    lister_memes,
    supprimer_meme,
)


class _Req:
    def __init__(self, state, body=None, raw=b"", headers=None):
        self.app = type("A", (), {"state": type("S", (), {"wally": state})()})()
        self._body, self._raw = body, raw
        self.headers = headers or {}

    async def json(self):
        return self._body

    async def body(self):
        return self._raw


def _png(couleur=(200, 30, 30), taille=(64, 64)) -> bytes:
    tampon = io.BytesIO()
    Image.new("RGB", taille, couleur).save(tampon, format="PNG")
    return tampon.getvalue()


@pytest.fixture
def atelier(tmp_path):
    (tmp_path / "chat.png").write_bytes(_png())
    (tmp_path / "chat.png.txt").write_text("un chat qui hurle", encoding="utf-8")
    (tmp_path / "meme7.webp").write_bytes(_png())
    state = type("W", (), {"memes": MemeLibrary(tmp_path)})()
    return tmp_path, state


# ── lister ───────────────────────────────────────────────────────────────────

async def test_la_liste_distingue_ce_qui_est_ecrit_de_ce_qui_est_lu(atelier):
    """Sans cette distinction, l'écran proposerait « meme7 » comme une phrase
    à corriger — alors que personne n'a jamais rien écrit sur ce meme."""
    _, state = atelier
    d = await lister_memes(_Req(state))
    par_nom = {m["nom"]: m for m in d["memes"]}
    assert par_nom["chat.png"]["description"] == "un chat qui hurle"
    assert par_nom["chat.png"]["lue"] == "un chat qui hurle"
    assert par_nom["meme7.webp"]["description"] == ""
    assert par_nom["meme7.webp"]["lue"] == "meme7"
    assert d["max_octets"] > 0 and d["max_description"] > 0


async def test_la_liste_est_triee_par_NUMERO_pas_par_orthographe(atelier):
    """L'import numérote, et l'ordre lexicographique rend `meme1, meme10,
    meme100, …, meme2` : l'ordre d'ajout y est illisible, et deux memes postés
    le même soir se retrouvent à cent cases l'un de l'autre."""
    dossier, state = atelier
    for nom in ("meme2.webp", "meme10.webp", "meme100.webp"):
        (dossier / nom).write_bytes(_png())
    d = await lister_memes(_Req(state))
    numerotes = [m["nom"] for m in d["memes"] if m["nom"].startswith("meme")]
    assert numerotes == ["meme2.webp", "meme7.webp", "meme10.webp", "meme100.webp"]
    # Les noms hors du schéma passent APRÈS : ils n'ont pas de rang à respecter.
    assert d["memes"][-1]["nom"] == "chat.png"


async def test_les_videos_sont_listees_mais_marquees_hors_des_tirages(atelier):
    """Le rotateur les joue, donc l'owner doit pouvoir les retirer d'ici. Wally,
    lui, affiche dans un `<img>` : il ne peut pas les sortir."""
    dossier, state = atelier
    (dossier / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    d = await lister_memes(_Req(state))
    video = next(m for m in d["memes"] if m["nom"] == "clip.mp4")
    assert video["genre"] == "video" and video["montrable"] is False
    image = next(m for m in d["memes"] if m["nom"] == "chat.png")
    assert image["genre"] == "image" and image["montrable"] is True


async def test_sans_bibliotheque_la_route_le_dit(atelier):
    state = type("W", (), {"memes": None})()
    with pytest.raises(HTTPException) as e:
        await lister_memes(_Req(state))
    assert e.value.status_code == 503


# ── décrire ──────────────────────────────────────────────────────────────────

async def test_decrire_ecrit_le_sidecar_et_prend_effet_aussitot(atelier):
    dossier, state = atelier
    d = await decrire_meme("meme7.webp", _Req(state, {"description": "un requin en costume"}))
    assert d["description"] == "un requin en costume"
    assert (dossier / "meme7.webp.txt").read_text(encoding="utf-8") == "un requin en costume"
    # « À chaud » : la bibliothèque relit le dossier, rien à invalider.
    entree = next(m for m in MemeLibrary(dossier).list() if m["name"] == "meme7.webp")
    assert entree["description"] == "un requin en costume"


async def test_la_reponse_rend_ce_que_wally_LIRA_pas_la_saisie(atelier):
    """Une phrase trop longue est ramenée à `MAX_DESCRIPTION`. Réafficher la
    saisie promettrait une phrase que le bot ne lira jamais en entier."""
    from bot.core.memes import MAX_DESCRIPTION

    _, state = atelier
    trop = "wally " * 60
    d = await decrire_meme("meme7.webp", _Req(state, {"description": trop}))
    assert len(d["lue"]) <= MAX_DESCRIPTION
    assert d["lue"] == d["description"]


async def test_effacer_une_description_retire_le_sidecar(atelier):
    dossier, state = atelier
    d = await decrire_meme("chat.png", _Req(state, {"description": "   "}))
    assert not (dossier / "chat.png.txt").exists()
    # Plus rien d'écrit : Wally retombe sur le nom du fichier, et la réponse
    # le DIT plutôt que de laisser croire à une phrase effacée sans effet.
    assert d["description"] == "" and d["lue"] == "chat"


async def test_effacer_redonne_la_main_a_un_vieux_sidecar_partage(atelier):
    """`chat.txt` (forme sans extension) est partagé par `chat.png` et
    `chat.jpg`. L'effacement du sidecar propre le laisse reprendre la main :
    la réponse doit montrer CE QUE WALLY LIRA, pas une chaîne vide."""
    dossier, state = atelier
    (dossier / "chat.txt").write_text("vieille légende", encoding="utf-8")
    d = await decrire_meme("chat.png", _Req(state, {"description": ""}))
    assert d["description"] == "vieille légende"
    assert d["lue"] == "vieille légende"


async def test_decrire_un_meme_inexistant_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await decrire_meme("fantome.png", _Req(state, {"description": "x"}))
    assert e.value.status_code == 404


async def test_un_corps_qui_nest_pas_un_objet_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await decrire_meme("chat.png", _Req(state, ["pas", "un", "objet"]))
    assert e.value.status_code == 400


async def test_un_nom_qui_remonte_larborescence_est_refuse(atelier):
    """`resolve` refuse tout ce qui sortirait du dossier — c'est la barrière."""
    dossier, state = atelier
    (dossier.parent / "voisin.png").write_bytes(_png())
    with pytest.raises(HTTPException) as e:
        await decrire_meme("../voisin.png", _Req(state, {"description": "x"}))
    assert e.value.status_code == 404
    assert not (dossier.parent / "voisin.png.txt").exists()


# ── déposer ──────────────────────────────────────────────────────────────────

async def test_deposer_range_limage_puis_le_PUT_la_decrit(atelier):
    """Le dépôt ne porte PAS de description : les valeurs d'en-tête HTTP sont
    en latin-1, « un carré vert » y arrivait en « un carrÃ© vert » — constaté
    en prod — et `fetch` refuse même d'envoyer un en-tête hors de cette plage.
    Elle se pose donc par le PUT, qui est du JSON."""
    dossier, state = atelier
    d = await deposer_meme("drole.png", _Req(state, raw=_png((10, 200, 10))))
    chemin = dossier / d["nom"]
    assert chemin.is_file()
    assert description_ecrite(chemin) == ""
    await decrire_meme(d["nom"], _Req(state, {"description": "un carré vert"}))
    assert description_ecrite(chemin) == "un carré vert"


async def test_le_depot_passe_par_le_chemin_dimport_commun(atelier):
    """Numérotation, conversion WebP et dédup vivent dans `meme_import` : une
    seconde écriture directe dans le dossier finirait par en diverger."""
    dossier, state = atelier
    d = await deposer_meme("drole.png", _Req(state, raw=_png((10, 200, 10))))
    assert d["nom"] == "meme8.webp", "numéro suivant, et PNG converti en WebP"
    assert d["converti"] is True


async def test_un_doublon_est_refuse_en_le_nommant(atelier):
    dossier, state = atelier
    octets = _png((10, 200, 10))
    premier = await deposer_meme("a.png", _Req(state, raw=octets))
    with pytest.raises(HTTPException) as e:
        await deposer_meme("b.png", _Req(state, raw=octets))
    assert e.value.status_code == 400
    assert premier["nom"] in e.value.detail


async def test_un_format_inconnu_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await deposer_meme("virus.exe", _Req(state, raw=b"MZ"))
    assert e.value.status_code == 400


async def test_un_nom_sans_extension_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await deposer_meme("sansextension", _Req(state, raw=b"0"))
    assert e.value.status_code == 400


async def test_un_fichier_vide_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await deposer_meme("vide.png", _Req(state, raw=b""))
    assert e.value.status_code == 400


async def test_un_fichier_trop_lourd_est_refuse_avant_la_conversion(atelier):
    from bot.core.meme_import import MAX_TELECHARGEMENT

    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await deposer_meme("gros.png",
                           _Req(state, raw=b"0" * (MAX_TELECHARGEMENT + 1)))
    assert e.value.status_code == 413


# ── supprimer ────────────────────────────────────────────────────────────────

async def test_supprimer_emporte_le_fichier_ET_sa_description(atelier):
    """Un sidecar orphelin réserve son numéro : `prochain_numero()` compte les
    `.txt`, et cette vieille phrase se collerait sinon à l'image suivante."""
    dossier, state = atelier
    d = await supprimer_meme("chat.png", _Req(state))
    assert d == {"supprime": "chat.png"}
    assert not (dossier / "chat.png").exists()
    assert not (dossier / "chat.png.txt").exists()


async def test_supprimer_un_meme_inconnu_est_refuse(atelier):
    _, state = atelier
    with pytest.raises(HTTPException) as e:
        await supprimer_meme("fantome.png", _Req(state))
    assert e.value.status_code == 404


# ── La page Live › Memes ────────────────────────────────────────────────────

def _page_memes_js() -> str:
    js = (Path(__file__).resolve().parents[1]
          / "bot/dashboard/static/app.js").read_text(encoding="utf-8")
    return js[js.index("// ── Live › Memes"):js.index("// ── Atelier des sons")]


def test_aucun_onclick_ninterpole_un_nom_de_meme():
    """`escHtml` n'échappe PAS l'apostrophe, et le nom vient d'un FICHIER que
    l'owner dépose lui-même. Un `x');alert(1);a.webp` s'exécuterait au rendu —
    le piège a déjà été payé sur les sons. Le RANG voyage dans un `data-`, le
    nom ne quitte jamais le tableau JavaScript où il est arrivé."""
    page = _page_memes_js()
    for interdit in ("onclick=\"ouvrirMeme(", "onclick=\"supprimerMeme(",
                     "onclick=\"enregistrerMeme("):
        assert interdit not in page, f"{interdit} remet un nom de fichier dans du JS"
    assert "data-rang=" in page and "closest('.meme-case')" in page


def test_la_grille_est_declaree_en_classe_pas_en_style_en_ligne():
    """Un `grid-template-columns` posé en attribut bat la media query : la
    section garderait ses colonnes jusqu'à 320 px, en débordant de l'écran et
    sans lever la moindre erreur JS."""
    page = _page_memes_js()
    assert "grid-template-columns" not in page
    assert 'class="meme-grille"' in page
    css = (Path(__file__).resolve().parents[1]
           / "bot/dashboard/static/style.css").read_text(encoding="utf-8")
    assert ".meme-grille" in css
    # La fiche passe en UNE colonne sur téléphone : côte à côte, sa colonne de
    # texte garde son `minmax(320px, …)` et la pousse à 700 px de large.
    responsive = css[css.index("/* ══ RESPONSIVE"):]
    assert ".meme-fiche-boite" in responsive


def test_la_page_est_cablee_aux_quatre_endroits():
    """Une page se câble à quatre endroits : la route, la sidebar, le panneau
    et le dispatcher. Il en manque un, et l'entrée mène à un écran blanc — sans
    la moindre erreur JS."""
    racine = Path(__file__).resolve().parents[1]
    js = (racine / "bot/dashboard/static/app.js").read_text(encoding="utf-8")
    html = (racine / "bot/dashboard/static/index.html").read_text(encoding="utf-8")
    assert "'live/memes': {" in js, "route absente de ROUTES"
    assert "pane: 'admin-memes'" in js
    assert "def.pane === 'admin-memes') renderMemes()" in js, "dispatcher"
    assert 'data-route="live/memes"' in html, "entrée de sidebar"
    assert 'id="tab-admin-memes"' in html, "panneau"


def test_la_galerie_nest_plus_dans_la_page_medias():
    """173 vignettes noyaient « Médias & sons » et repoussaient l'atelier des
    sons hors d'atteinte — c'est ce qui a motivé la page dédiée."""
    js = (Path(__file__).resolve().parents[1]
          / "bot/dashboard/static/app.js").read_text(encoding="utf-8")
    medias = js[js.index("// ── Live › Médias & sons"):js.index("// ── Mise en scène")]
    assert "meme" not in medias.lower()


def test_le_smoke_test_ouvre_vraiment_une_fiche():
    """Un panneau MONTÉ n'est pas UTILISABLE : le volet des réglages de
    l'overlay était monté, visible, et inatteignable à la souris. Le smoke test
    doit donc CLIQUER une vignette, pas compter des nœuds."""
    smoke = (Path(__file__).resolve().parents[1]
             / "scripts/smoke_front.py").read_text(encoding="utf-8")
    assert '("Memes", "live/memes")' in smoke
    assert "#meme-grille .meme-case" in smoke
    assert "#meme-fiche-desc" in smoke


def test_le_repli_sur_le_nom_du_fichier_reste_le_dernier_mot():
    """`_describe` a toujours une réponse : Wally doit pouvoir parler d'un meme
    que personne n'a décrit."""
    assert _describe(Path("/tmp/chat_qui_hurle.webp")) == "chat qui hurle"
