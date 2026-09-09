"""La source des cartes du TCG.

🚨 Ce module est la SEULE source : l'outil de Wally, le widget overlay et le
site public la lisent tous. Les tests ci-dessous gardent les invariants qui
feraient mal ailleurs — un chemin d'illustration mal formé donne une carte
noire sur un stream, une résolution floue montre la carte de quelqu'un d'autre.
"""
from bot.core import tcg_cartes


def test_les_cartes_terminees_sont_la():
    assert set(tcg_cartes.CARTES) == {
        "azrael", "claker", "rhae", "lilith", "kingsrequin"}


def test_toute_carte_declare_ses_illustrations_sans_extension():
    """Le front sert l'AVIF avec repli WebP : il ajoute l'extension lui-même.
    Un chemin qui en porte une ici donnerait `/assets/x.webp.avif`."""
    for carte in tcg_cartes.CARTES.values():
        for chemin in (carte.hero, carte.fond, carte.avant_plan, carte.hero_3d):
            if chemin is not None:
                assert not chemin.endswith((".avif", ".webp", ".png")), chemin
                assert chemin.startswith("/assets/"), chemin


def test_normaliser_reduit_a_ce_qui_compte():
    """Personne ne tape le tréma d'Azraël dans un chat, et le modèle non plus.
    La résolution qui s'appuie dessus arrive en phase 3, avec son appelant."""
    assert tcg_cartes.normaliser("  AZRAËL ") == "azrael"
    assert tcg_cartes.normaliser("ClakerNoJutsu") == "clakernojutsu"


def test_aucun_alias_ne_designe_deux_cartes():
    """Un alias ambigu ferait dépendre le résultat de l'ordre du registre."""
    vus: dict[str, str] = {}
    for cle, carte in tcg_cartes.CARTES.items():
        for alias in carte.alias:
            norme = tcg_cartes.normaliser(alias)
            # Vaut aussi pour un doublon DANS une carte : « azraël » à côté de
            # « azrael » n'ajoute rien, la normalisation retire déjà l'accent.
            assert norme not in vus, f"{alias} : {cle} et {vus.get(norme)}"
            vus[norme] = cle


def test_l_empreinte_change_avec_le_contenu(tmp_path, monkeypatch):
    """L'URL d'une illustration porte l'empreinte de son CONTENU.

    Sans elle, la zone Cloudflare (`browser_cache_ttl = 14400`, mesuré le
    2026-09-07) écrase le `Cache-Control` de l'origine et fige une
    illustration retouchée quatre heures durant, chez chaque visiteur.
    """
    (tmp_path / "x.avif").write_bytes(b"premier")
    monkeypatch.setattr(tcg_cartes, "DOSSIER_ASSETS", tmp_path)
    tcg_cartes.empreinte.cache_clear()
    avant = tcg_cartes.empreinte("/assets/x")

    (tmp_path / "x.avif").write_bytes(b"second")
    tcg_cartes.empreinte.cache_clear()
    assert tcg_cartes.empreinte("/assets/x") != avant


def test_une_illustration_absente_ne_casse_pas_le_boot(tmp_path, monkeypatch, caplog):
    """Une illustration manquante est un défaut de DÉPLOIEMENT : l'URL doit
    rester servable, non versionnée, et le fait doit être journalisé."""
    monkeypatch.setattr(tcg_cartes, "DOSSIER_ASSETS", tmp_path)
    tcg_cartes.empreinte.cache_clear()
    assert tcg_cartes.empreinte("/assets/fantome") == ""


def test_chaque_illustration_declaree_existe_dans_LES_DEUX_formats():
    """🚨 Le seul geste qui ne suit PAS l'ajout d'une carte au registre.

    Le tableau de `scripts/generer_illustrations_tcg.py` est écrit à la main :
    il porte le cadrage de chaque couche, dont dérive la largeur à générer.
    Une carte ajoutée ici sans y passer laisse ses `.avif` absents — l'URL part
    alors NON VERSIONNÉE (`empreinte()` journalise et rend ""), le fichier
    répond 404, et la carte s'affiche noire sur le site comme sur l'overlay.
    Sans erreur JS, et sans que rien ne le dise.

    C'est la règle écrite en tête du module : une carte n'entre au registre que
    si son illustration EXISTE. Ce test la fait tenir.
    """
    from pathlib import Path

    manquantes = []
    for carte in tcg_cartes.CARTES.values():
        for champ in ("hero", "fond", "avant_plan", "hero_3d"):
            base = getattr(carte, champ)
            if not base:
                continue
            for ext in (".avif", ".webp"):
                fichier = tcg_cartes.DOSSIER_ASSETS / f"{Path(base).name}{ext}"
                if not fichier.exists():
                    manquantes.append(f"{carte.cle}.{champ} → {fichier}")
    assert not manquantes, (
        "illustrations déclarées mais absentes — lancer "
        "`python3 scripts/generer_illustrations_tcg.py` après avoir ajouté "
        "la carte à son tableau :\n  " + "\n  ".join(manquantes))


def test_le_repli_webp_accompagne_toujours_l_avif():
    """Safari ne lit l'AVIF que depuis 16.4 : un AVIF livré seul rend une carte
    VIDE sur un téléphone plus vieux, pas une carte dégradée."""
    from pathlib import Path

    for carte in tcg_cartes.CARTES.values():
        for champ in ("hero", "fond", "avant_plan", "hero_3d"):
            base = getattr(carte, champ)
            if not base:
                continue
            nom = Path(base).name
            avif = (tcg_cartes.DOSSIER_ASSETS / f"{nom}.avif").exists()
            webp = (tcg_cartes.DOSSIER_ASSETS / f"{nom}.webp").exists()
            assert avif == webp, f"{nom} : avif={avif} webp={webp}"


def test_le_reflet_holographique_ne_marque_pas_tout_le_monde():
    """Un marqueur que tout le monde porterait ne marquerait plus rien.

    Le choix est éditorial et se fait CARTE PAR CARTE, au cadrage : Lilith est
    légendaire et ne l'a pas, KingsRequin l'est aussi et le porte. Ce test ne
    fige donc pas une liste — il tient la seule propriété qui compte, que le
    reflet reste l'exception.

    Le champ est écrit du CONSOMMATEUR vers l'UI : la couche n'existe dans le
    DOM que si la carte le demande (cf. `chero-holo` dans le composant).
    """
    holos = [c.cle for c in tcg_cartes.CARTES.values() if c.holographique]
    assert holos, "aucune carte holographique : le marqueur a disparu"
    assert len(holos) < len(tcg_cartes.CARTES), holos


def test_le_chatoiement_des_bords_suppose_le_reflet():
    """`holo_zone` ne dit QUE l'endroit : sans `holographique`, aucune couche
    n'est construite et le réglage serait un bouton branché sur rien."""
    for carte in tcg_cartes.CARTES.values():
        if carte.holo_zone != "surface":
            assert carte.holographique, carte.cle
        assert carte.holo_zone in ("surface", "bords"), carte.cle


def test_le_defaut_est_sans_reflet():
    """Une carte ajoutée sans y penser ne doit pas hériter du marqueur."""
    from bot.core.tcg_cartes import CarteTcg

    nue = CarteTcg(cle="x", nom="X", legende="X", classe="X", ultime="X",
                   description="", ambiance="", cout=0, atk=0, pv=0, aura=0,
                   hero="/assets/x", fond="/assets/y")
    assert nue.holographique is False


# ── Le fichier de cartes : ce qu'il refuse ────────────────────────────────
#
# La donnée a quitté le code le 2026-09-09 (`tcg/cartes.yaml`, bind-monté) :
# une carte se corrige sans rebuild. Le prix de ce gain, c'est qu'une faute de
# frappe ne fait plus planter l'import de Python — elle ne coûte plus rien à
# écrire. Ces tests tiennent la contrepartie : le fichier est REFUSÉ, bruyamment,
# plutôt que chargé à moitié.

def _fichier(tmp_path, entrees):
    import yaml
    chemin = tmp_path / "cartes.yaml"
    chemin.write_text(yaml.safe_dump(entrees, allow_unicode=True), encoding="utf-8")
    return chemin


def _carte_valide(**extra):
    base = {
        "cle": "essai", "nom": "ESSAI", "legende": "E · ESSAI", "classe": "ESSAI",
        "ultime": "ESSAI", "description": "d", "ambiance": "a",
        "cout": 1, "atk": 1, "pv": 1, "aura": 1,
        "hero": "/assets/essai-hero", "fond": "/assets/essai-fond",
    }
    base.update(extra)
    return base


def test_le_fichier_livre_se_lit():
    """Le chemin déclaré doit exister : c'est lui que le Dockerfile copie et
    que `docker-compose.yml` bind-monte. Une faute dans l'un des trois et le
    bot ne démarre plus."""
    assert tcg_cartes.CHEMIN_CARTES.exists(), tcg_cartes.CHEMIN_CARTES
    assert tcg_cartes._lire(tcg_cartes.CHEMIN_CARTES)


def test_un_champ_inconnu_refuse_le_fichier(tmp_path):
    """🚨 Le défaut que ce fichier rend possible, et le seul qui compte.

    `holographic: true` au lieu de `holographique` : en Python, l'erreur était
    immédiate. Dans un YAML lu avec des `.get()`, le réglage serait ignoré en
    SILENCE — l'owner tourne un bouton, rien ne bouge, rien ne le dit. C'est la
    signature exacte des huit boutons morts du 2026-08-26.
    """
    import pytest
    chemin = _fichier(tmp_path, [_carte_valide(holographic=True)])
    with pytest.raises(ValueError, match="holographic"):
        tcg_cartes._lire(chemin)


def test_un_champ_obligatoire_manquant_refuse_le_fichier(tmp_path):
    import pytest
    entree = _carte_valide()
    del entree["fond"]
    with pytest.raises(ValueError, match="fond"):
        tcg_cartes._lire(_fichier(tmp_path, [entree]))


def test_une_valeur_hors_vocabulaire_refuse_le_fichier(tmp_path):
    """`particules` et `holo_zone` sont des vocabulaires FERMÉS tenus par le
    rendu. Une valeur inconnue ne lève rien côté JS : elle rend l'effet par
    défaut, sans le dire."""
    import pytest
    with pytest.raises(ValueError, match="particules"):
        tcg_cartes._lire(_fichier(tmp_path, [_carte_valide(particules="neige")]))
    with pytest.raises(ValueError, match="holo_zone"):
        tcg_cartes._lire(_fichier(
            tmp_path, [_carte_valide(holographique=True, holo_zone="coin")]))


def test_une_illustration_avec_extension_refuse_le_fichier(tmp_path):
    """Le front ajoute `.avif` / `.webp` lui-même : une extension écrite ici
    donnerait `/assets/x.webp.avif`, donc une carte noire."""
    import pytest
    with pytest.raises(ValueError, match="mal formée"):
        tcg_cartes._lire(_fichier(
            tmp_path, [_carte_valide(hero="/assets/essai-hero.webp")]))


def test_une_cle_en_double_refuse_le_fichier(tmp_path):
    """Sans ce refus, la seconde écraserait la première sans un mot — et
    l'ordre du fichier, qui EST celui de la collection à l'écran, mentirait."""
    import pytest
    with pytest.raises(ValueError, match="double"):
        tcg_cartes._lire(_fichier(tmp_path, [_carte_valide(), _carte_valide()]))


def test_l_ordre_du_fichier_est_celui_du_registre(tmp_path):
    """L'ordre dit dans quel ordre les cartes ont été finies : c'est celui de
    la collection sur `/tcg`, pas un détail de sérialisation."""
    cartes = tcg_cartes._lire(_fichier(tmp_path, [
        _carte_valide(cle="un"), _carte_valide(cle="deux"), _carte_valide(cle="trois")]))
    assert list(cartes) == ["un", "deux", "trois"]


# ── La rareté et l'accent dérivé (2026-09-09) ─────────────────────────────

def test_la_rarete_hors_vocabulaire_est_refusee(tmp_path):
    """Six paliers plus `indefinie`, et rien d'autre.

    Un palier mal orthographié ne doit pas être chargé en silence : c'est une
    donnée de JEU, reprise de Notion, et une carte qui s'annonce d'un palier
    qui n'existe pas ment au joueur.
    """
    import pytest
    with pytest.raises(ValueError, match="rarete"):
        tcg_cartes._lire(_fichier(tmp_path, [_carte_valide(rarete="legendaire")]))


def test_la_rarete_par_defaut_est_indefinie(tmp_path):
    """Une carte ajoutée sans palier ne doit pas en hériter d'un.

    `indefinie` est la valeur HONNÊTE : deux cartes sur cinq n'ont pas de
    palier saisi dans Notion, et le défaut ne doit pas prétendre le contraire.
    """
    cartes = tcg_cartes._lire(_fichier(tmp_path, [_carte_valide()]))
    assert cartes["essai"].rarete == "indefinie"


def test_l_accent_derive_du_cout_et_ne_s_ecrit_pas(tmp_path):
    """🚨 `accent` n'est plus un champ : l'écrire lève.

    C'est le seul garde-fou contre la rechute — le fichier en portait un par
    carte jusqu'au 2026-09-09, et rien n'empêcherait de le remettre.
    """
    import pytest
    with pytest.raises(ValueError, match="accent"):
        tcg_cartes._lire(_fichier(tmp_path, [_carte_valide(accent="#ffffff")]))


def test_l_accent_va_du_froid_au_chaud_et_le_neutre_dit_l_absence():
    """La rampe est ordonnée, et hors plage rend le neutre.

    On teste le MÉCANISME (l'ordre des teintes, le neutre hors plage), jamais
    les codes hexadécimaux : figer « le coût 10 vaut #e1a947 » interdirait de
    retoucher la rampe sans réécrire le test.
    """
    from bot.core.tcg_cartes import (ACCENT_INDEFINI, COUT_MAX, COUT_MIN,
                                     accent_du_cout)

    def rouge(hexa: str) -> int:
        return int(hexa[1:3], 16)

    # Du bleu vers le rouge : la composante rouge ne peut que monter.
    rampe = [rouge(accent_du_cout(c)) for c in range(COUT_MIN, COUT_MAX + 1)]
    assert rampe == sorted(rampe), rampe
    assert rampe[0] < rampe[-1]
    # Zéro n'est pas « le coût le plus bas », c'est « pas de coût ».
    assert accent_du_cout(0) == ACCENT_INDEFINI
    assert accent_du_cout(COUT_MAX + 1) == ACCENT_INDEFINI


def test_les_cartes_livrees_ne_portent_que_ce_que_notion_porte():
    """Relevé Notion du 2026-09-09 : seul Azraël a des chiffres.

    Ce test tient l'arbitrage de l'owner — tout ce qui n'est pas décidé vaut 0
    ou « INDÉFINI ». Il tombera le jour où Notion se remplira, et c'est
    exactement à ce moment-là qu'il faut relire le fichier.
    """
    cartes = tcg_cartes.CARTES
    assert cartes["azrael"].cout == 10
    for cle in ("claker", "rhae", "lilith", "kingsrequin"):
        carte = cartes[cle]
        assert (carte.cout, carte.atk, carte.pv, carte.aura) == (0, 0, 0, 0), cle
        assert carte.ultime == "INDÉFINI", cle
        assert carte.accent == tcg_cartes.ACCENT_INDEFINI, cle


def test_la_rarete_part_au_front():
    """Un champ que le front ne reçoit pas n'existe pas pour lui."""
    from bot.core.tcg_cartes import en_json
    assert en_json(tcg_cartes.CARTES["azrael"])["rarete"] == "archange"
