# bot/intelligence/thread_sense.py
"""Ce que Wally sait de sa propre place dans un fil de discussion.

Trois angles morts mesurés sur le live du 2026-08-13 et la veille :

· **La profondeur du fil.** Le 12/08, 38 réponses consécutives à la même
  personne entre 23h03 et 23h28 — un tiers de sa production du jour. Rien,
  dans son contexte, ne lui disait qu'il en était au dixième aller-retour :
  chaque message lui arrivait comme le premier.

· **Le marqueur terminal.** 36 messages sur 89 finis par « 😄 » le 13/08,
  38 sur 130 par « :p » la veille. Le tic CHANGE de jour en jour : ce n'est
  pas une formule figée dans un prompt, c'est le modèle qui recopie ses
  propres fins de message, visibles dans le prélude du canal. Un spectateur
  s'en est plaint en direct, 18 secondes après le message de trop.

· **La vanne ressassée.** « prédatrice de 15 saisons » ressortie cinq fois
  en toutes lettres en sept minutes, « diva » dans 19 messages sur 89.

Aucun des trois ne s'écrit dans un prompt : ce sont des MESURES sur ce que
Wally vient d'écrire. Interdire une liste de formules ne servirait à rien —
le modèle en trouve d'autres le lendemain, c'est exactement ce qu'on observe
entre le 12 et le 13. Ce module ne décide de rien : il compte, et le prompt
reçoit le compte. Le seul geste mécanique est `retirer_tic()`, qui empêche
un même marqueur terminal de tenir plus d'un message sur quatre.

État de MODULE, comme `_relances` / `_open_questions` dans les handlers :
la mesure porte sur le process vivant, elle n'a pas à survivre à un restart.
`oublier_tout()` existe pour les tests (cf. la fixture de `conftest.py`, même
précédent que `secret_guard`).
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections import deque

from loguru import logger

# Combien de ses propres répliques Wally garde sous la main, par canal, pour se
# relire. Douze couvre à peu près un quart d'heure de live : assez pour qu'un
# tic se voie, assez court pour qu'une vanne enterrée cesse d'être reprochée.
_FENETRE_REPLIQUES = 12

# Au-delà de ce silence entre deux de ses réponses à la MÊME personne, le fil
# est fini : la suivante rouvre un échange, elle ne le prolonge pas. Le run de
# 38 du 12/08 tenait sur des intervalles de ~37 s.
_FIL_TTL_S = 900.0

# Un marqueur doit revenir au moins ce nombre de fois dans la fenêtre pour
# compter comme un tic. En dessous, c'est une coïncidence : « là. » et « 31. »
# sont sortis une fois chacun sur les 219 messages des deux jours mesurés.
_TIC_MIN = 3

# Idem pour un mot ressassé, compté en NOMBRE DE RÉPLIQUES distinctes qui le
# portent : dire trois fois « couronne » dans une seule phrase est un effet de
# style, le dire dans trois messages d'affilée est un disque rayé.
_RESSASSAGE_MIN = 3

# Combien de mots ressassés on montre. Au-delà, la consigne devient une liste
# de courses et le modèle n'en retient plus aucun.
_RESSASSAGE_MAX = 6

# Longueur minimale d'un mot pris en compte. En dessous de 5 lettres, ce sont
# des outils grammaticaux ; au-dessus, du contenu.
_MOT_MIN = 5

# Ponctuation de phrase. Un message qui finit par « . » ou « ! » ne porte aucun
# marqueur : c'est de la ponctuation, pas une signature.
_PONCTUATION = set(".…,;:!?-–—\"'«»()[]")

# Mots-outils français. Ce n'est PAS une liste de formulations interdites — rien
# ici n'est proscrit — mais un filtre lexical : sans lui, « toujours », « voilà »
# ou « vraiment » remonteraient à chaque fenêtre et noieraient les vraies vannes
# (« prédatrice », « couronne », « statue ») qu'on cherche à faire cesser.
_OUTILS = frozenset("""
alors apres assez aussi autre autres avait avant avec beaucoup bien bonne bonsoir
carrement cela celle celui cette chaque chose comme comment coup dans depuis
deux dire donc elle elles encore enfin entre etait etre faire fais fait faut
genre jamais juste laisse leur leurs meme mieux moins monde ouais parce pareil
parle pense petit peut peux plus pour pourquoi prends premier quand quelque
rien sans seulement soir sinon suis surtout tellement toujours tous tout toute
toutes trop trois trouve vais vers veux vient voila voir vraiment
""".split())

# canal → répliques récentes de Wally (les plus anciennes à gauche)
_REPLIQUES: dict[str, deque] = {}

# canal → {"qui": clé de la personne, "profondeur": int, "quand": monotonic}
_FILS: dict[str, dict] = {}


def _plie(texte: str) -> str:
    """Minuscules sans accents — « écran » et « ecran » sont le même mot."""
    plie = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in plie if unicodedata.category(c) != "Mn")


def mots_porteurs(texte: str) -> set[str]:
    """Les mots de contenu d'une réplique, pour repérer ce qui revient."""
    return {
        m for m in re.findall(r"[a-z]+", _plie(texte))
        if len(m) >= _MOT_MIN and m not in _OUTILS
    }


def marqueur_terminal(texte: str) -> str:
    """Le marqueur qui CLÔT un message, ou "" s'il n'y en a pas.

    Un marqueur est un dernier mot qui ne porte pas de contenu : « 😄 », « :p »,
    « ^^ », « xD ». On le reconnaît mécaniquement — pas plus de deux lettres —
    plutôt qu'en énumérant les emojis, sans quoi le tic du lendemain passerait
    à travers, ce qui est exactement ce qui s'est produit entre le 12 et le 13.

    La ponctuation de phrase seule n'en est pas un : finir par « ! » n'a jamais
    fatigué personne.
    """
    jetons = (texte or "").split()
    if not jetons:
        return ""
    # `rstrip` et non `strip` : la ponctuation qui compte est celle de la FIN
    # de phrase. Rogner aussi le début décapitait « :p » en « p » — soit
    # précisément le tic du 12/08, 38 messages sur 130.
    dernier = jetons[-1].rstrip("".join(_PONCTUATION))
    if not dernier:
        return ""
    if sum(1 for c in dernier if c.isalpha()) > 2:
        return ""
    return dernier


def note_reponse(canal: str, personne: str, texte: str) -> None:
    """Wally vient de répondre à `personne` dans `canal`.

    Appelé APRÈS publication : une réplique jamais partie ne creuse pas un fil
    et ne compte pas comme un tic (même règle que `append_prelude`).
    """
    canal, personne = str(canal), str(personne)
    fil = _FILS.get(canal)
    maintenant = time.monotonic()
    if (
        fil is not None
        and fil["qui"] == personne
        and (maintenant - fil["quand"]) <= _FIL_TTL_S
    ):
        fil["profondeur"] += 1
        fil["quand"] = maintenant
    else:
        _FILS[canal] = {"qui": personne, "profondeur": 1, "quand": maintenant}

    repliques = _REPLIQUES.setdefault(canal, deque(maxlen=_FENETRE_REPLIQUES))
    repliques.append(texte or "")


def profondeur(canal: str, personne: str) -> int:
    """Nombre de réponses consécutives déjà adressées à `personne` ici.

    0 dès que quelqu'un d'autre a été servi entre-temps, ou que le fil a
    dépassé son délai de péremption.
    """
    fil = _FILS.get(str(canal))
    if fil is None or fil["qui"] != str(personne):
        return 0
    if (time.monotonic() - fil["quand"]) > _FIL_TTL_S:
        return 0
    return int(fil["profondeur"])


def tic_terminal(canal: str) -> tuple[str, int]:
    """Le marqueur de fin qui revient le plus, et son compte. ("", 0) sinon."""
    comptes: dict[str, int] = {}
    for texte in _REPLIQUES.get(str(canal), ()):
        if marqueur := marqueur_terminal(texte):
            comptes[marqueur] = comptes.get(marqueur, 0) + 1
    if not comptes:
        return "", 0
    marqueur, compte = max(comptes.items(), key=lambda kv: kv[1])
    return (marqueur, compte) if compte >= _TIC_MIN else ("", 0)


def mots_ressasses(canal: str) -> list[str]:
    """Les mots que Wally réemploie de réplique en réplique, les plus repris d'abord."""
    comptes: dict[str, int] = {}
    for texte in _REPLIQUES.get(str(canal), ()):
        for mot in mots_porteurs(texte):
            comptes[mot] = comptes.get(mot, 0) + 1
    repris = sorted(
        ((m, n) for m, n in comptes.items() if n >= _RESSASSAGE_MIN),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return [m for m, _ in repris[:_RESSASSAGE_MAX]]


def retirer_tic(canal: str, texte: str) -> str:
    """Le texte privé de son marqueur final quand celui-ci est déjà un tic ici.

    Le seul geste mécanique du module, et le plus étroit possible : les emojis
    restent entièrement disponibles, c'est leur usage en SIGNATURE — le même
    marqueur en fin de trois messages sur quatre — qui devient impossible.
    Informer le modèle ne suffisait pas : `VOICE.md` lui demande de varier ses
    fins de message depuis des semaines, et 38 % des messages du 13/08 se
    terminaient pareil.

    Une réplique qui n'est QUE son marqueur est rendue intacte : rendre le vide
    impossible passe avant la chasse au tic.
    """
    marqueur = marqueur_terminal(texte)
    if not marqueur:
        return texte
    tic, _ = tic_terminal(canal)
    if marqueur != tic:
        return texte
    coupe = (texte or "").rstrip()
    coupe = coupe[: coupe.rfind(marqueur)].rstrip()
    if not coupe:
        return texte
    logger.info("Fil : marqueur « {m} » retiré (tic du canal {c})", m=marqueur, c=canal)
    return coupe


def _palier(profondeur_fil: int, paliers: dict[str, str]) -> str:
    """La directive de `FIL.md` qui correspond à cette profondeur.

    Les clés sont des SEUILS numériques (« ## 4 ») : le palier retenu est le plus
    grand seuil atteint. Le fichier est monté en volume — ajouter, déplacer ou
    supprimer un palier ne demande aucun rebuild, et aucun seuil n'est écrit dans
    ce fichier-ci.
    """
    retenue = ""
    meilleur = -1
    for cle, texte in (paliers or {}).items():
        try:
            seuil = int(str(cle).strip())
        except (TypeError, ValueError):
            logger.warning("FIL.md : palier non numérique ignoré ({c!r})", c=cle)
            continue
        if seuil <= profondeur_fil and seuil > meilleur:
            retenue, meilleur = texte, seuil
    return retenue


def bloc_fil(
    canal: str,
    personne: str,
    nom_personne: str = "",
    paliers: dict[str, str] | None = None,
) -> str:
    """Le bloc de prompt qui rend Wally conscient de son propre fil.

    Vide quand il n'y a rien à signaler — un premier message dans un canal
    calme ne doit pas coûter un token.
    """
    lignes: list[str] = []

    fond = profondeur(canal, personne)
    if fond >= 2:
        qui = nom_personne or "la même personne"
        lignes.append(
            f"Tu as déjà répondu {fond} fois d'affilée à {qui}, sans que personne "
            f"d'autre ne t'occupe entre-temps."
        )
        if directive := _palier(fond, paliers or {}):
            lignes.append(directive)

    tic, compte = tic_terminal(canal)
    if tic:
        lignes.append(
            f"Tu as fini {compte} de tes {len(_REPLIQUES.get(str(canal), ()))} derniers "
            f"messages par « {tic} ». C'est devenu ta signature, et ça se voit. "
            f"Ne finis pas celui-ci pareil."
        )

    if repris := mots_ressasses(canal):
        lignes.append(
            "Ces mots reviennent d'un message à l'autre chez toi en ce moment : "
            + ", ".join(f"« {m} »" for m in repris)
            + ". Une vanne ne marche qu'une fois — passe à autre chose plutôt que "
            "de la resservir."
        )

    if not lignes:
        return ""
    return "\n--- Où tu en es dans ce fil ---\n" + "\n".join(lignes)


def oublier_canal(canal: str) -> None:
    """Efface la mesure d'un canal (départ, purge)."""
    _REPLIQUES.pop(str(canal), None)
    _FILS.pop(str(canal), None)


def oublier_tout() -> None:
    """Remet le module à neuf — appelé entre deux tests."""
    _REPLIQUES.clear()
    _FILS.clear()
