"""La source des cartes du TCG.

🚨 Ce module est la SEULE source : l'outil de Wally, le widget overlay et le
site public la lisent tous. Les tests ci-dessous gardent les invariants qui
feraient mal ailleurs — un chemin d'illustration mal formé donne une carte
noire sur un stream, une résolution floue montre la carte de quelqu'un d'autre.
"""
from bot.core import tcg_cartes


def test_les_quatre_cartes_terminees_sont_la():
    assert set(tcg_cartes.CARTES) == {"azrael", "claker", "rhae", "lilith"}


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


def test_le_reflet_holographique_est_reserve_aux_cartes_qui_le_declarent():
    """Un marqueur que tout le monde porterait ne marquerait plus rien.

    Le champ est écrit du CONSOMMATEUR vers l'UI : la couche n'existe dans le
    DOM que si la carte le demande (cf. `chero-holo` dans le composant).
    """
    holos = [c.cle for c in tcg_cartes.CARTES.values() if c.holographique]
    assert holos == ["azrael"], holos


def test_le_defaut_est_sans_reflet():
    """Une carte ajoutée sans y penser ne doit pas hériter du marqueur."""
    from bot.core.tcg_cartes import CarteTcg

    nue = CarteTcg(cle="x", nom="X", legende="X", classe="X", ultime="X",
                   description="", ambiance="", cout=0, atk=0, pv=0, aura=0,
                   accent="#fff", hero="/assets/x", fond="/assets/y")
    assert nue.holographique is False
