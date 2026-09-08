"""Les cartes TERMINÉES du TCG du Purgatoire — la source unique.

Trois consommateurs lisent ce module, et aucun ne garde de copie :

- l'outil `show_overlay` de Wally, pour résoudre « la carte de claker » ;
- le widget `carte` de l'overlay OBS, dont les valeurs voyagent dans
  l'événement du bus ;
- le site public (`/tcg`, `/demo/carte-azrael`), via
  `GET /api/public/tcg/cartes`.

🚨 **LES CHIFFRES SONT DES PLACEHOLDERS.** Coût, Attaque, PV, Aura, classe :
ce sont les valeurs de la maquette, écrites pour avoir quelque chose de lisible
à l'écran. Les vraies vivent dans la base Notion « 🃏 Cartes du Purgatoire »,
qui est la SEULE source, et y sont recopiées carte par carte au fur et à
mesure. La page `/tcg` le dit aux visiteurs, en toutes lettres.

🚨 Corollaire : ne JAMAIS justifier une valeur d'ici par le barème (« budget 12
+ rareté », « ce palier vaut +8 »). Trois commentaires de ce genre ont été
écrits le 2026-09-07 sur des chiffres qui ne sortaient d'aucun calcul — une
justification fausse coûte plus cher qu'une absence de justification, elle
envoie vérifier une règle qui n'a jamais été appliquée.

🚨 Rien ici n'est calculé et rien ne le sera : le moteur de règles vit ailleurs.
Une règle dupliquée est une porte de triche ouverte et un second jeu à
maintenir.

⚠️ Une carte n'entre au registre que si son ILLUSTRATION EXISTE. Ce n'est pas
la liste des cartes prévues, c'est la liste de celles qu'on peut montrer : le
site affiche exactement son contenu et son compteur en dérive. Une entrée sans
image donnerait une carte noire annoncée comme terminée.

⚠️ Ne pas confondre avec `public-ui/pages/tcg-demo.js`, qui porte les six héros
PLACEHOLDER de la maquette du plateau (`/demo/plateau-tcg`) : ceux-là sont là
pour avoir quelque chose à l'écran, pas pour être exacts.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from loguru import logger

from bot.core.tirage import SacSansRemise

# Là où vivent les AVIF et les WebP, produits par
# `scripts/generer_illustrations_tcg.py`. Chemin relatif au dépôt, comme
# `PUBLIC_UI_DIR` dans le dashboard — le conteneur y bind-monte `public-ui/`.
DOSSIER_ASSETS = Path("public-ui/assets")


@dataclass(frozen=True, slots=True)
class CarteTcg:
    """Une carte de héros, telle qu'elle s'affiche.

    Les champs d'illustration portent un chemin **sans extension**
    (`/assets/tcg-azrael-hero`) : le front sert l'AVIF avec repli WebP et
    ajoute l'extension lui-même. En écrire une ici donnerait
    `/assets/x.webp.avif`.

    Les réglages de cadrage (`hero_cote`, `hero_echelle`, `avant_plan_*`…)
    calent une illustration donnée dans le cadre de la carte. Ils sont propres
    à chaque image et n'ont aucun sens de règle — c'est aussi eux qui décident
    de la largeur à générer, cf. le tableau de
    `scripts/generer_illustrations_tcg.py`.
    """

    cle: str
    nom: str
    legende: str
    classe: str
    ultime: str
    description: str
    ambiance: str
    cout: int
    atk: int
    pv: int
    aura: int
    accent: str
    hero: str
    fond: str
    # Les alias sont ÉCRITS À LA MAIN, et la correspondance est exacte : une
    # distance d'édition finirait par montrer la carte de quelqu'un d'autre,
    # en public, sur un stream. Le lien pseudo → carte est éditorial, ce n'est
    # pas la table d'alias de la mémoire (qui lie un pseudo à une PERSONNE).
    alias: tuple[str, ...] = ()
    avant_plan: str | None = None
    avant_plan_largeur: str = "86%"
    avant_plan_bas: str = "-6%"
    hero_cote: str = "-14%"
    hero_haut: str = "4%"
    hero_echelle: float = 1.12
    # Le calque de SURVOL peut porter une autre illustration, avec son propre
    # cadrage : rhae___ montre un portrait assis au repos et un bond griffes
    # en avant quand la carte s'ouvre. À None, il reprend le visuel du repos.
    hero_3d: str | None = None
    hero_3d_cote: str | None = None
    hero_3d_haut: str | None = None
    particules: str = "braises"
    parallaxe: float = 1.0
    intensite: float = 1.0
    # Le reflet irisé qui court sur la carte quand elle se penche, comme une
    # carte à collectionner sous une lampe. C'est le marqueur des DEUX raretés
    # les plus hautes — arbitrage de l'owner du 2026-09-08. Par carte et non
    # global : si tout le monde l'avait, il ne marquerait plus rien.
    holographique: bool = False


CARTES: dict[str, CarteTcg] = {}


def _poser(carte: CarteTcg) -> None:
    CARTES[carte.cle] = carte


_poser(CarteTcg(
    cle="azrael",
    nom="AZRAËL",
    legende="AZRAËL · ARCHANGE",
    classe="ARCHANGE · UNIQUE",
    ultime="REWORK",
    description="Rework : désigne un héros adverse. Pour le reste de la "
                "partie, son Ultime coûte +3 et tous ses nombres baissent de 2.",
    ambiance="Il ne te dit jamais non. Il attend le prochain patch, et un "
             "matin plus personne ne te craint.",
    cout=10, atk=5, pv=10, aura=5,
    accent="#ffb02e",
    hero="/assets/tcg-azrael-hero",
    fond="/assets/tcg-azrael-fond",
    alias=(),
    particules="braises",
    holographique=True,
))

_poser(CarteTcg(
    cle="claker",
    nom="CLAKER",
    legende="CLAKERNOJUTSU · ÂME",
    classe="ÂME · NO JUTSU",
    ultime="NO JUTSU",
    description="Annule la prochaine tactique jouée par un adversaire.",
    ambiance="La technique, c'est de ne pas en avoir.",
    cout=8, atk=5, pv=4, aura=3,
    accent="#7de3a4",
    hero="/assets/tcg-claker-hero",
    fond="/assets/tcg-claker-fond",
    # Ses pieds passent DEVANT lui : c'est la couche d'avant-plan, et c'est
    # elle qui donne la profondeur quand la carte s'ouvre.
    avant_plan="/assets/tcg-claker-pieds",
    avant_plan_largeur="100%",
    avant_plan_bas="15%",
    alias=("claker", "clakernojutsu", "clacker", "clackernojutsu"),
    hero_cote="5%",
    hero_haut="-8%",
    hero_echelle=1.1,
    particules="poussiere",
    parallaxe=0.9,
    intensite=0.6,
))

_poser(CarteTcg(
    cle="rhae",
    nom="RHAE",
    legende="RHAE___ · FÉLIN",
    classe="FÉLIN · UNIQUE",
    ultime="GRIFFE",
    description="Inflige 3 au héros ciblé. Il ne peut plus bloquer jusqu'à la "
                "fin du tour.",
    ambiance="Il dort vingt heures par jour. Les quatre autres, tu les paies.",
    cout=6, atk=8, pv=5, aura=4,
    accent="#ffb02e",
    fond="/assets/tcg-rhae-fond",
    # La seule carte à DEUX visuels : portrait assis, cadré serré, au repos ;
    # bond griffes en avant, bien plus large que la carte, au survol.
    hero="/assets/tcg-rhae-hero-2d",
    hero_cote="8%",
    hero_haut="-2%",
    hero_3d="/assets/tcg-rhae-hero-3d",
    hero_3d_cote="-26%",
    hero_3d_haut="6%",
    hero_echelle=1.12,
    alias=("rhae", "rhae_", "rhae__", "rhae___"),
    particules="poussiere",
    parallaxe=1.1,
    intensite=0.8,
    holographique=True,
))

_poser(CarteTcg(
    cle="lilith",
    nom="LILITH",
    legende="LILITH · DÉMON",
    classe="DÉMON · LÉGENDAIRE",
    ultime="MORSURE",
    description="Vole 2 PV au héros ciblé et les ajoute aux tiens.",
    ambiance="Elle demande toujours avant de prendre. Une fois.",
    cout=7, atk=6, pv=6, aura=5,
    accent="#e0332b",
    # Ailes déployées : l'illustration fait presque deux fois la largeur de la
    # carte. Au repos les pointes sont rognées, au survol elles sortent.
    hero="/assets/tcg-lilith-hero",
    fond="/assets/tcg-lilith-fond",
    alias=("lilith",),
    hero_cote="-40%",
    # 5 % et non 4 % : plus bas, le bas de l'illustration (elle s'arrête aux
    # mollets) sort de derrière la fiche quand le parallaxe déplace le calque
    # libre, et les jambes ont l'air coupées net.
    hero_haut="5%",
    hero_echelle=1.08,
    particules="poussiere",
    parallaxe=1.0,
    intensite=0.75,
))


def normaliser(nom: str) -> str:
    """Un nom réduit à ce qui compte : minuscules, sans accent, sans marges.

    Les accents partent parce que personne ne tape le tréma d'Azraël dans un
    chat — et le modèle non plus.
    """
    sans_marques = "".join(
        c for c in unicodedata.normalize("NFD", nom.strip())
        if unicodedata.category(c) != "Mn"
    )
    return sans_marques.casefold()


def resoudre(nom: str) -> CarteTcg | None:
    """La carte que désigne `nom`, ou None.

    ⚠️ Correspondance EXACTE sur la table normalisée, jamais floue ni par
    préfixe : accepter les approximations, c'est afficher devant les viewers
    une carte que personne n'a demandée.
    """
    cible = normaliser(nom)
    if not cible:
        return None
    for carte in CARTES.values():
        if cible in (carte.cle, normaliser(carte.nom)):
            return carte
        if any(cible == normaliser(a) for a in carte.alias):
            return carte
    return None


def noms_disponibles() -> list[str]:
    """Ce qu'on peut ÉCRIRE pour désigner une carte, pour le message de refus.

    Les CLÉS et non les noms d'affichage : un refus doit lister ce qui est
    accepté en entrée, pas ce qui apparaît à l'écran en capitales. Sans cette
    liste, Wally réessaie au hasard.
    """
    return list(CARTES)


# Le tirage « une carte, n'importe laquelle ». Un sac sans remise et non un
# `random.choice` : avec QUATRE cartes, un tirage uniforme en répète une une
# fois sur quatre, et deux fois de suite une fois sur seize. Sur un stream,
# cette répétition-là se voit tout de suite — c'est le défaut payé sur le pendu
# (deux « peacekeeper » d'affilée), et la leçon y était déjà : un vivier élargi
# sans mémoire répète quand même.
#
# La source est relue à chaque rechargement du sac, donc une carte terminée
# entre dans le tirage sans redémarrage.
_SAC = SacSansRemise(lambda: list(CARTES))


def tirer_au_hasard() -> CarteTcg | None:
    """Une carte au hasard, en épuisant le registre avant d'en répéter une.

    None si le registre est vide — ce qui n'arrive pas aujourd'hui, mais reste
    la réponse honnête plutôt qu'une exception.
    """
    cle = _SAC.tirer()
    return CARTES.get(cle) if cle else None


@lru_cache(maxsize=64)
def empreinte(base: str) -> str:
    """Les 8 premiers caractères du sha256 de l'illustration, ou "".

    🚨 C'est ce qui VERSIONNE l'URL (`…-hero.avif?v=a1b2c3d4`). Mesuré en prod
    le 2026-09-07 : la zone Cloudflare porte `browser_cache_ttl = 14400`, qui
    ÉCRASE le `Cache-Control` de l'origine pour tout ce qu'elle juge cacheable
    — les en-têtes `CDN-Cache-Control` n'y changent rien. Sans empreinte, une
    illustration retouchée reste quatre heures figée chez chaque visiteur.

    ⚠️ Calculée sur le seul `.avif` et servie aux DEUX formats : le script les
    régénère toujours ensemble, et lire deux fichiers doublerait les I/O sans
    rien garantir de plus.

    ⚠️ Un fichier manquant ne doit pas empêcher le boot. C'est un défaut de
    DÉPLOIEMENT : on journalise et on rend une empreinte vide, l'URL reste
    servable, simplement pas versionnée.
    """
    chemin = DOSSIER_ASSETS / f"{Path(base).name}.avif"
    try:
        return hashlib.sha256(chemin.read_bytes()).hexdigest()[:8]
    except OSError as exc:
        logger.warning("TCG : illustration illisible, URL non versionnée "
                       "({p}) : {e!r}", p=chemin, e=exc)
        return ""


def url(base: str) -> str:
    """Le chemin d'une illustration, empreinte comprise quand elle est lisible."""
    marque = empreinte(base)
    return f"{base}?v={marque}" if marque else base


def en_json(carte: CarteTcg) -> dict:
    """Une carte telle que le front la lit.

    🚨 Les clés partent en **camelCase** : c'est le vocabulaire que le composant
    de rendu lit déjà (`heroCote`, `avantPlanBas`…). Renommer de son côté
    ferait toucher le rendu pendant un refactor dont le critère est « rien ne
    change à l'écran ».

    🚨 Les **alias ne sortent pas**. Cette route est publique : tout ce qu'elle
    rend part à n'importe quel visiteur, et la liste des fautes d'orthographe
    qu'on accepte sur un pseudo n'a rien à y faire.

    Les illustrations sortent **versionnées** par l'empreinte de leur contenu
    (`tcg_cartes.url`) : la zone Cloudflare écrase le `Cache-Control` de
    l'origine, et sans ça une illustration retouchée resterait quatre heures
    figée chez chaque visiteur.
    """
    return {
        "cle": carte.cle,
        "nom": carte.nom,
        "legende": carte.legende,
        "classe": carte.classe,
        "ultime": carte.ultime,
        "description": carte.description,
        "ambiance": carte.ambiance,
        "cout": carte.cout,
        "atk": carte.atk,
        "pv": carte.pv,
        "aura": carte.aura,
        "accent": carte.accent,
        "hero": url(carte.hero),
        "fond": url(carte.fond),
        # `None` et non `""` : le front teste la présence, et une chaîne vide
        # est fausse en JavaScript sans pour autant dire « absent ».
        "avantPlan": url(carte.avant_plan) if carte.avant_plan else None,
        "hero3d": url(carte.hero_3d) if carte.hero_3d else None,
        "heroCote": carte.hero_cote,
        "heroHaut": carte.hero_haut,
        "heroEchelle": carte.hero_echelle,
        "hero3dCote": carte.hero_3d_cote,
        "hero3dHaut": carte.hero_3d_haut,
        "avantPlanLargeur": carte.avant_plan_largeur,
        "avantPlanBas": carte.avant_plan_bas,
        "particules": carte.particules,
        "parallaxe": carte.parallaxe,
        "intensite": carte.intensite,
        "holographique": carte.holographique,
    }
