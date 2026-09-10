"""Les cartes TERMINÉES du TCG du Purgatoire — le LECTEUR de leur source.

La donnée vit dans `tcg/cartes.yaml`, pas ici : ce module la lit au boot, la
VALIDE et la sert. Corriger une carte ne demande donc pas de rebuild.

Trois consommateurs lisent ce module, et aucun ne garde de copie :

- l'outil `show_overlay` de Wally, pour résoudre « la carte de claker » ;
- le widget `carte` de l'overlay OBS, dont les valeurs voyagent dans
  l'événement du bus ;
- le site public (`/tcg`, `/demo/carte-azrael`), via
  `GET /api/public/tcg/cartes`.

🚨 Rien ici n'est calculé et rien ne le sera : le moteur de règles vit
ailleurs. Une règle dupliquée est une porte de triche ouverte et un second jeu
à maintenir. Les avertissements sur les CHIFFRES (des placeholders, la vérité
est dans Notion) sont en tête de `tcg/cartes.yaml`, avec les valeurs qu'ils
concernent.

Il n'y a plus qu'UN catalogue depuis le 2026-09-09 : la maquette du plateau
(`/demo/plateau-tcg`) portait le second, avec d'autres chiffres pour les mêmes
héros. Elle a été retirée — c'était un concept, redessiné depuis.
"""

from __future__ import annotations

import colorsys
import hashlib
import unicodedata
from dataclasses import MISSING, dataclass, fields
from functools import lru_cache
from pathlib import Path

import yaml
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
    # carte à collectionner sous une lampe. Choisi CARTE PAR CARTE au moment
    # du cadrage, et pas dérivé de la rareté : Lilith est légendaire et ne
    # l'a pas, KingsRequin l'est aussi et le porte. Par carte et non global —
    # si tout le monde l'avait, il ne marquerait plus rien.
    holographique: bool = False
    # Où court ce reflet : sur la SURFACE de l'illustration, ou seulement dans
    # l'épaisseur du liseré (`"bords"`). Sur un fond déjà très saturé, une
    # irisation de surface se lit comme un voile blanc — d'où la seconde
    # option, choisie carte par carte au moment du cadrage.
    holo_zone: str = "surface"
    # La DOSE de vitrage, entre 0 et 1. Un seul curseur, qui monte ensemble le
    # grain, le contraste et la saturation de la couche — les trois bornes
    # vivent dans `.chero-holo` (`public-ui/partage/tcg-carte.css`) et nulle
    # part ailleurs. Ce nombre ne dit que « à quelle hauteur ».
    #
    # Il existe parce que deux cartes livrées n'ont PAS le même besoin, et
    # c'est un banc à l'écran qui l'a montré (2026-09-09) : le fond d'Azraël
    # est une explosion orange claire où le vitrage se noie, celui de
    # KingsRequin un bleu sombre dont le vitrage court dans le liseré. Une
    # dose unique les force à un compromis.
    #
    # ⚠️ Le défaut est 1,0 — la dose pleine, celle choisie par l'owner sur le
    # banc. Aucune carte n'écrit ce champ aujourd'hui, et c'est normal : il ne
    # se pose que le jour où l'une doit diverger des autres.
    holo_force: float = 1.0
    # Deux nappes de bulles qui montent derrière l'illustration. Aquatique et
    # rien d'autre : ailleurs ce sont des taches claires sans raison.
    bulles: bool = False
    # Le palier de rareté, repris TEL QUEL de la base Notion « 🃏 Cartes du
    # Purgatoire » (propriété « Rareté »), qui en est la source. Six paliers
    # ordonnés, plus `indefinie` — et `indefinie` est la valeur HONNÊTE, pas un
    # repli : deux cartes sur cinq n'ont pas de palier saisi dans Notion au
    # 2026-09-09, et en inventer un ferait mentir la carte sur une donnée de
    # jeu.
    #
    # ⚠️ Il ne pilote PAS l'holographie. `holographique` et `holo_zone`
    # restent choisis carte par carte au moment du cadrage : KingsRequin porte
    # le liseré irisé sans avoir de palier, et lier les deux aujourd'hui le
    # lui retirerait. Le jour où les cinq paliers seront saisis, c'est ici
    # qu'il faudra revenir.
    rarete: str = "indefinie"

    @property
    def accent(self) -> str:
        """La couleur d'accent, DÉRIVÉE du coût de l'ultime.

        🚨 Elle ne s'écrit pas dans le YAML, elle se calcule — arbitrage de
        l'owner du 2026-09-09. Écrite à la main, elle disait l'humeur de
        l'illustration et rien du jeu : Claker en vert, Lilith en rouge,
        Azraël en or, sans qu'aucune des trois ne renseigne le joueur. Dérivée
        du coût, la couleur DIT quelque chose — et elle suivra toute seule le
        jour où les vrais chiffres descendront de Notion.
        """
        return accent_du_cout(self.cout)


# Là où vit la DONNÉE des cartes. Bind-monté (`./tcg:/app/tcg:ro`) et lu au
# BOOT : corriger une carte ne demande pas de rebuild, seulement un
# `docker compose restart wally` — même régime que les prompts de cognition.
CHEMIN_CARTES = Path("tcg/cartes.yaml")

_CHAMPS = {f.name for f in fields(CarteTcg)}
_OBLIGATOIRES = {f.name for f in fields(CarteTcg) if f.default is MISSING}
# Vocabulaires FERMÉS, tenus par le rendu : `particules()` et `.chero-holo`
# dans `public-ui/partage/tcg-carte.js`. Une valeur hors liste ne lève rien
# côté JS — elle rend simplement l'effet par défaut, en silence.
_PARTICULES = {"braises", "poussiere", "aucune"}
_HOLO_ZONES = {"surface", "bords"}
# Les six paliers de la base Notion, dans l'ordre, plus l'absence de palier.
# 🚨 L'ORDRE compte : c'est celui de la rareté croissante, et c'est lui que le
# rendu lira le jour où il en dérivera quoi que ce soit. `indefinie` est
# volontairement HORS de l'échelle et pas à son pied — une carte sans palier
# saisi n'est pas une carte du palier le plus bas.
RARETES = ("ame", "fidele", "ame_promise", "elu", "ange", "archange")
_RARETES = {*RARETES, "indefinie"}

# ── Le budget d'une carte-héros ───────────────────────────────────────────
# `atk + pv + aura = BUDGET_BASE + bonus de rareté`.
#
# 🚨 C'est la SEULE règle d'équilibre encore vérifiable mécaniquement. Les
# chiffres sortaient d'une formule tirée de la mémoire de Wally jusqu'au
# 2026-09-10, où l'owner l'a retirée : ils s'écrivent désormais à la main.
# Une formule se relit, une opinion non — si le budget n'est pas tenu ici,
# plus rien ne rattrape une carte qui en écrase une autre, et ça ne se voit
# qu'après vingt parties.
BUDGET_BASE = 12
BONUS_RARETE = {"ame": 0, "fidele": 1, "ame_promise": 2,
                "elu": 3, "ange": 5, "archange": 8}

# ── L'accent, dérivé du coût de l'ultime ──────────────────────────────────
# Une rampe FROID → CHAUD sur la plage des coûts : 1 en bleu, 12 en rouge.
# C'est le mécanisme qui est écrit ici, jamais les douze couleurs — ajouter un
# palier de coût ne demande donc rien.
#
# 🚨 Un coût hors plage rend le NEUTRE, et zéro est hors plage : quatre cartes
# sur cinq n'ont pas de coût saisi dans Notion au 2026-09-09. Elles portent
# donc toutes le même gris, et c'est le but — une carte dont le coût n'est pas
# décidé ne doit pas s'annoncer d'une couleur qui prétend le contraire.
COUT_MIN = 1
COUT_MAX = 12
_TEINTE_FROIDE = 210.0
_TEINTE_CHAUDE = 0.0
# Sur le fond encre de la carte, l'accent sert de FOND au chiffre du coût
# (texte `#12100c`) et de liseré. D'où une luminosité tenue haut et une
# saturation forte : sous 0,5 de luminosité, le chiffre devient illisible.
_ACCENT_LUM = 0.58
_ACCENT_SAT = 0.72
ACCENT_INDEFINI = "#8a8578"


def accent_du_cout(cout: int) -> str:
    """La couleur d'accent d'un coût d'ultime, ou le neutre hors plage."""
    if not COUT_MIN <= cout <= COUT_MAX:
        return ACCENT_INDEFINI
    part = (cout - COUT_MIN) / (COUT_MAX - COUT_MIN)
    teinte = _TEINTE_FROIDE + (_TEINTE_CHAUDE - _TEINTE_FROIDE) * part
    rouge, vert, bleu = colorsys.hls_to_rgb(teinte / 360.0, _ACCENT_LUM, _ACCENT_SAT)
    return "#{:02x}{:02x}{:02x}".format(
        round(rouge * 255), round(vert * 255), round(bleu * 255))


def _exiger(condition: bool, cle: str, probleme: str) -> None:
    """Refuse le fichier en NOMMANT la carte et le problème.

    🚨 On lève, et le bot ne démarre pas. C'est délibéré : une carte ignorée
    en silence, c'est une carte noire sur un stream ou un tirage qui saute,
    découverts en direct. Le fichier est en git et la suite de tests le lit —
    une faute n'arrive donc en prod que si elle a été écrite À LA MAIN sur
    l'hôte, et dans ce cas le message de boot est exactement ce qu'on veut.
    """
    if not condition:
        raise ValueError(f"{CHEMIN_CARTES} — carte {cle} : {probleme}")


def _lire(chemin: Path) -> dict[str, CarteTcg]:
    """Le fichier des cartes, validé, dans son ordre d'écriture.

    L'ordre est celui de la collection à l'écran : un `dict` le conserve.
    """
    entrees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    cartes: dict[str, CarteTcg] = {}
    for rang, entree in enumerate(entrees or [], start=1):
        cle = entree.get("cle", f"sans clé, en position {rang}")
        # Un champ inconnu est une ERREUR et pas un réglage ignoré : c'est
        # tout l'intérêt d'avoir sorti ces valeurs du code, où une faute de
        # frappe ne compilait pas.
        _exiger(not (set(entree) - _CHAMPS), cle,
                f"champ inconnu {sorted(set(entree) - _CHAMPS)}")
        _exiger(not (_OBLIGATOIRES - set(entree)), cle,
                f"champ obligatoire manquant {sorted(_OBLIGATOIRES - set(entree))}")
        _exiger(entree["cle"] not in cartes, cle, "clé en double")
        alias = entree.get("alias") or []
        carte = CarteTcg(**{**entree, "alias": tuple(alias)})
        _exiger(carte.particules in _PARTICULES, cle,
                f"particules={carte.particules!r} hors de {sorted(_PARTICULES)}")
        _exiger(carte.holo_zone in _HOLO_ZONES, cle,
                f"holo_zone={carte.holo_zone!r} hors de {sorted(_HOLO_ZONES)}")
        _exiger(carte.rarete in _RARETES, cle,
                f"rarete={carte.rarete!r} hors de {sorted(_RARETES)}")
        # Le budget, seule règle d'équilibre encore vérifiable (cf. BUDGET_BASE).
        # Deux cartes y échappent, et pour la même raison — il n'y a rien à
        # vérifier : celle dont la rareté n'est pas décidée (le budget n'existe
        # pas encore) et celle dont les stats sont toutes à zéro (pas écrite).
        # ⚠️ Wally, lui, est le BOSS : ses PV ne tiennent aucun budget de héros.
        # Il porte `rarete: indefinie` et passe donc à travers aujourd'hui. Le
        # jour où on lui posera un palier, c'est ICI qu'il faudra l'excepter.
        somme = carte.atk + carte.pv + carte.aura
        if carte.rarete != "indefinie" and somme:
            budget = BUDGET_BASE + BONUS_RARETE[carte.rarete]
            _exiger(somme == budget, cle,
                    f"budget non tenu : atk+pv+aura = {carte.atk}+{carte.pv}"
                    f"+{carte.aura} = {somme}, attendu {budget} "
                    f"({BUDGET_BASE} + {BONUS_RARETE[carte.rarete]} pour "
                    f"{carte.rarete})")
        # Hors bornes, le `calc()` de la feuille rendrait un filtre absurde —
        # un `saturate` négatif est INVALIDE et fait tomber la propriété
        # entière, donc le vitrage disparaît en silence. On refuse ici.
        _exiger(0.0 <= carte.holo_force <= 1.0, cle,
                f"holo_force={carte.holo_force!r} hors de [0, 1]")
        # Les chemins d'illustration sont SANS extension : le front ajoute la
        # sienne (`x.avif` / `x.webp`). Une extension écrite ici donnerait
        # `/assets/x.webp.avif`, soit une carte noire.
        for chemin_illu in (carte.hero, carte.fond, carte.avant_plan, carte.hero_3d):
            if chemin_illu is not None:
                _exiger(chemin_illu.startswith("/assets/")
                        and not chemin_illu.endswith((".avif", ".webp", ".png")),
                        cle, f"illustration mal formée : {chemin_illu!r}")
        cartes[carte.cle] = carte
    return cartes


CARTES: dict[str, CarteTcg] = _lire(CHEMIN_CARTES)


def par_prestige() -> list[CarteTcg]:
    """Les cartes de la plus haute à la plus basse, pour la collection.

    🚨 Le classement dérive de l'HOLOGRAPHIE, pas du champ `rarete`, et c'est
    une décision de l'owner (2026-09-09) et non un raccourci. Trier par palier
    donnerait Azraël, rhae, Claker, puis Lilith et KingsRequin — alors que
    KingsRequin doit venir TROISIÈME. Son palier n'est pas saisi dans Notion,
    et il ne le sera peut-être pas de sitôt ; son traitement visuel, lui, est
    déjà tranché. C'est le liseré irisé qui dit son rang, pas une case vide.

    Trois rangs, et pas six : ce sont exactement les trois traitements que le
    rendu sait faire — le vitrage en surface, le vitrage au liseré, rien. Un
    quatrième rang serait un classement que l'écran ne saurait pas montrer.

    ⚠️ `sorted` est STABLE : à rang égal, l'ordre du fichier départage, et il
    dit dans quel ordre les cartes ont été finies. C'est ce qui met Azraël
    avant rhae et Claker avant Lilith, sans qu'aucune règle ne l'écrive.
    """
    def rang(carte: CarteTcg) -> int:
        if not carte.holographique:
            return 0
        return 1 if carte.holo_zone == "bords" else 2

    return sorted(CARTES.values(), key=rang, reverse=True)


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
# `random.choice` : avec CINQ cartes, un tirage uniforme en répète une une
# fois sur cinq, et deux fois de suite une fois sur vingt-cinq. Sur un stream,
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
        "holoZone": carte.holo_zone,
        "holoForce": carte.holo_force,
        "bulles": carte.bulles,
        "rarete": carte.rarete,
    }
