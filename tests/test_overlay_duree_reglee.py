"""La durée, le délai et les animations réglés par scène.

Le contrôle est TEXTUEL : il n'y a pas de DOM en test ici, et `overlay.js` n'est
pas un module qu'on peut charger sous node sans navigateur. Il vise donc ce qui
se vérifie ainsi et qui compte vraiment — l'ORDRE des gardes. Une garde placée
après la lecture du réglage ne protège de rien, et cela ne se lit pas en
diagonale : c'est le genre de défaut qui coupe une partie de pendu en direct.

Le comportement, lui, se vérifie à l'écran. Un test vert ne prouve pas qu'un
widget sort au bon moment.
"""
from pathlib import Path

_JS = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
       / "overlay.js").read_text(encoding="utf-8")


def _bloc(depuis: str, jusqua: str) -> str:
    return _JS[_JS.index(depuis):_JS.index(jusqua, _JS.index(depuis))]


# ── La durée ────────────────────────────────────────────────────────────────

def test_la_duree_reglee_lemporte_sur_celle_du_serveur():
    """Le choix rendu par l'owner : le streamer décide de son habillage. Un
    simple repli sur `params.duration` n'aurait quasiment jamais rien fait,
    tous les événements portant déjà une durée — un réglage qui ne pilote
    rien."""
    assert "dureeReglee" in _JS
    bloc = _bloc("const dureeReglee", "minuteurs.set(kind")
    assert "params.duration" in bloc, "le repli auto doit rester"


def test_une_partie_en_cours_sort_avant_la_lecture_du_reglage():
    """`sticky` est posé sur un pendu en cours et un sondage ouvert. Une durée
    de 5 s les couperait sous les yeux du chat. La garde EXISTE déjà — ce test
    vérifie qu'elle reste AVANT, ce qui est tout ce qui la rend efficace."""
    assert _JS.index("params.sticky === true") < _JS.index("const dureeReglee")


def test_le_clip_et_le_spam_de_popups_gardent_leur_mecanique():
    """Le clip sort sur la fin de sa VIDÉO (`video.duration + 5`), le spam sur
    la fin d'un PLAN de fenêtres calculé. Une durée posée par-dessus couperait
    l'un au milieu et ferait tomber l'écran bleu de l'autre à côté de son
    plan."""
    assert "DUREE_INTERNE" in _JS
    decl = _bloc("const DUREE_INTERNE", ";")
    assert '"clip"' in decl and '"virus_popup"' in decl


def test_le_spam_de_popups_decale_son_plan_ET_sa_sortie_ensemble():
    """Le serveur publie `seconds` (le plan) et `duration` (la sortie de la
    carte) SÉPARÉS, la seconde valant la première plus la durée de l'écran bleu
    de nettoyage. Ne remplacer que `seconds` ferait partir la carte avant la fin
    de son propre plan : réglé à 60 s là où le serveur en annonce 30, l'écran
    bleu ne serait JAMAIS vu.

    L'écart est CONSERVÉ plutôt que recalculé : la durée du bleu vit en Python
    (`VIRUS_BSOD_S`), et la recopier ici garantirait qu'un jour les deux
    divergent."""
    bloc = _bloc('if (kind === "virus_popup")', "const delai =")
    assert "reglages.virus_popup" in bloc
    assert "seconds:" in bloc and "duration:" in bloc
    assert "ecart" in bloc


def test_le_builder_du_spam_ignore_le_modele():
    """Un seul point de lecture : `showWidget` normalise les paramètres, le
    builder ne connaît que ce qu'on lui passe. Deux lectures du même réglage à
    deux endroits, c'est deux vérités le jour où l'une change."""
    bloc = _bloc("stockFrais((medias)", "lancerSpamVirus(box, medias, duree)")
    assert "reglages" not in bloc


# ── Le délai ────────────────────────────────────────────────────────────────

def test_le_delai_est_annulable_par_un_clear():
    """Un widget qui surgit APRÈS un `clear` est un fantôme, et ce fichier en a
    déjà payé plusieurs. `clearAll()` vide `minuteurs` : le rendez-vous du
    délai doit donc y être rangé, pas gardé dans une variable à part."""
    bloc = _bloc("const delai =", "renderWidget(kind, params, build)")
    # L'INVARIANT, pas la ligne : le rendez-vous est rangé dans `minuteurs`,
    # sous une clé préfixée qui ne peut pas écraser le minuteur de SORTIE du
    # même `kind`. Exiger la forme exacte de l'appel figerait une écriture, et
    # ce dépôt a déjà payé six fois des tests qui verrouillaient le défaut.
    assert "minuteurs.set(" in bloc
    assert '"delai:"' in bloc


def test_le_delai_ne_se_rejoue_pas_en_boucle():
    """Le second passage doit tomber droit dans le montage, sinon `showWidget`
    se rappelle indéfiniment et le widget n'apparaît jamais."""
    bloc = _bloc("const delai =", "renderWidget(kind, params, build)")
    assert "_delai_consomme" in bloc
    assert bloc.count("_delai_consomme") >= 2, "il faut poser le drapeau ET le lire"


# ── Les animations ──────────────────────────────────────────────────────────

def test_glitch_reste_le_defaut_des_deux_bouts():
    """Personne ne doit voir son overlay changer parce qu'on a rendu
    l'animation réglable."""
    bloc = _bloc("function animDe(", "async function chargerLayout(")
    assert bloc.count('"glitch"') >= 2


def test_animDe_est_declaree_avec_les_autres_lectrices_de_reglages():
    """`reglages` est un `let` : le lire avant sa ligne lève une TDZ, que
    `node --check` ne détecte pas — l'incident buildSections est dans ce dépôt.
    Les trois fonctions qui le lisent sont donc groupées SOUS sa déclaration."""
    assert _JS.index("let reglages = {}") < _JS.index("function animDe(")
    assert _JS.index("function estSolo(") < _JS.index("function animDe(")


def test_le_relais_suit_la_duree_de_la_sortie_reellement_jouee():
    """`playNext` était rappelé après `GLITCH_MS` en dur (150 ms). Avec une
    sortie d'une seconde, la carte suivante entrerait pendant que la précédente
    finit de partir : deux cartes pleines l'une sur l'autre, illisibles."""
    assert "sortieMs" in _JS
    bloc = _bloc("relaisTimer = setTimeout(playNext", ");")
    assert "GLITCH_MS" not in bloc, "le relais ne doit plus être figé"


def test_une_sortie_en_glitch_garde_la_duree_du_glitch():
    """La rafale dure 5 × 30 ms, quoi qu'on règle : `anim_duree` ne la pilote
    pas. Faire suivre le relais à une durée réglée ferait attendre la carte
    suivante pour rien."""
    bloc = _bloc("const sortieMs", ";")
    assert "GLITCH_MS" in bloc


def test_linsistance_se_rejoue_en_boucle_et_pas_sur_la_carte():
    """Deux `animation` sur le même nœud se remplacent au lieu de se cumuler :
    posée sur la carte, l'insistance effacerait l'animation d'entrée."""
    assert "animate__infinite" in _JS
    bloc = _bloc("anim.insistance !==", "}")
    assert "firstElementChild" in bloc


def test_les_classes_dentree_sont_retirees_avant_la_sortie():
    """Sans ce ménage, la classe d'entrée reste posée et la sortie — une
    seconde `animation` sur le même nœud — ne se joue jamais."""
    bloc = _bloc("box.classList.add(\"leaving\")", "relaisTimer")
    assert "classList.remove" in bloc


# ── La bulle et la galerie ──────────────────────────────────────────────────

def test_la_bulle_lit_la_duree_reglee_dans_la_scene():
    bloc = _bloc("function say(", "function makeDots(")
    assert "reglages.bubble" in bloc
    assert "durationSeconds" in bloc, "le repli du serveur doit rester"


def test_la_galerie_lit_ses_quatre_reglages_dans_la_scene():
    """Ils vivaient dans `config.yaml`, globalement : deux autorités sur la même
    question. La graine qui les y recopie arrive en phase 5 — dès maintenant,
    c'est la scène qui décide."""
    bloc = _bloc("function montrer(data)", "boite.style.display = \"block\"")
    assert "reglages.image" in bloc
    for champ in ("duree", "anim_entree", "anim_sortie", "anim_duree"):
        assert champ in bloc, f"la galerie ignore {champ}"
