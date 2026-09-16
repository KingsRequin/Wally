"""Les noms de la communauté, sous la forme où on les PRONONCE.

Le STT distant biaisait sa reconnaissance vers les pseudos des gens présents
dans le salon. Deux trous : on parle aussi des ABSENTS (« bien le bonsoir
Kassandre », lancé à une viewer du chat Twitch), et un pseudo ne se prononce
pas — `kassandreyunikon` n'aide pas à entendre « Kassandre », qui sortait
« Cassandra » 56 fois dans les journaux vocaux.

La forme parlée existe déjà : ce sont les alias que la mémoire a appris
(`user_aliases`). Ils sont écrits par un modèle, donc bruités (« ma femme »,
« requiiiiiin ») — d'où le seuil de confiance et le tri de forme ci-dessous.
Un mauvais terme de biais coûte peu ; un nom propre absent coûte le sens.
"""
from __future__ import annotations

import re
import time

from loguru import logger

# Lettres (accents compris), espaces, apostrophes et traits d'union ; une lettre
# à chaque bout. Ce qui porte un chiffre, un `_` ou un `@` est un identifiant,
# pas un nom qu'on prononce.
_PRONONCABLE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[' -])*[^\W\d_]$")
# « requiiiiiin », « clakaaaax » : une intonation recopiée, pas l'orthographe.
_LETTRE_ETIREE = re.compile(r"([^\W\d_])\1\1", re.IGNORECASE)
# Les pseudos se terminent souvent par un suffixe d'unicité (`Malef__`,
# `raiky0801`) : on le retire avant de juger la forme.
_SUFFIXE = re.compile(r"[\W\d_]+$")
_PREFIXE = re.compile(r"^[\W\d_]+")

# L'alias le plus sûr passe, le reste est trop souvent une conjecture.
CONFIANCE_MIN = 0.95
# Deux formes par personne au plus : le pseudo nettoyé et le surnom parlé.
# Au-delà, une seule personne très surnommée (Azraël en a trente) mangerait les
# places des autres.
_PAR_PERSONNE = 2
_LONGUEUR = (3, 24)
# Les alias bougent à l'échelle de la journée, pas de l'énoncé : une relecture
# par heure suffit, et le chemin d'un énoncé ne touche jamais la base.
_FRAICHEUR_S = 3600.0
_instantane: list[str] = []
_lu_a: float | None = None


def forme_parlee(brut: str | None) -> str | None:
    """Le nom tel qu'on le dit, ou None s'il ne se prononce pas."""
    nom = _PREFIXE.sub("", _SUFFIXE.sub("", (brut or "").strip()))
    if not (_LONGUEUR[0] <= len(nom) <= _LONGUEUR[1]):
        return None
    if not _PRONONCABLE.match(nom) or _LETTRE_ETIREE.search(nom):
        return None
    # « OMG PLS JOUEZ AVK MWAA » est un pseudo-phrase : personne ne l'appelle ainsi.
    if len(nom.split()) > 3:
        return None
    # Tout en minuscules (les alias le sont) : la casse du terme de biais se
    # retrouve dans la transcription, et un prénom s'écrit avec sa majuscule.
    return nom[0].upper() + nom[1:] if nom.islower() else nom


def choisir_noms(lignes) -> list[str]:
    """Une liste ordonnée de noms, les personnes récemment actives d'abord.

    `lignes` : `(uid, username, nickname, confidence)`, déjà triées par
    activité décroissante ; plusieurs lignes par personne (une par alias).
    """
    par_personne: dict[str, list[str]] = {}
    for uid, username, nickname, confiance in lignes:
        formes = par_personne.setdefault(uid, [])
        candidats = [username]
        if nickname and (confiance or 0) >= CONFIANCE_MIN:
            candidats.append(nickname)
        for brut in candidats:
            nom = forme_parlee(brut)
            if (nom and len(formes) < _PAR_PERSONNE
                    and nom.lower() not in {f.lower() for f in formes}):
                formes.append(nom)
    vus: set[str] = set()
    noms: list[str] = []
    for formes in par_personne.values():  # dict : ordre d'insertion = activité
        for nom in formes:
            if nom.lower() not in vus:
                vus.add(nom.lower())
                noms.append(nom)
    return noms


async def charger_noms_communaute(db) -> list[str]:
    """Relit la base ; rend [] (en le disant) si elle ne répond pas."""
    if db is None:
        return []
    try:
        lignes = await db.lignes_noms_communaute(CONFIANCE_MIN)
    except Exception as e:  # noqa: BLE001 — un biais optionnel ne bloque pas un join
        logger.warning("voice: noms de la communauté illisibles, biais réduit au salon : {e!r}", e=e)
        return []
    noms = choisir_noms((r["user_id"], r["username"], r["nickname"], r["confidence"])
                        for r in lignes)
    logger.info("voice: {n} nom(s) de la communauté soufflés au STT", n=len(noms))
    return noms


async def rafraichir_noms_communaute(db) -> None:
    """Relit la base si l'instantané a plus d'une heure (ou n'existe pas)."""
    global _instantane, _lu_a
    if db is None or (_lu_a is not None and time.monotonic() - _lu_a < _FRAICHEUR_S):
        return
    _lu_a = time.monotonic()
    _instantane = await charger_noms_communaute(db)


def noms_communaute() -> list[str]:
    """Le dernier instantané — synchrone, lu à chaque énoncé par les moteurs."""
    return _instantane


def tete_et_noms(phrases, extra_terms=None) -> tuple[list[str], list[str]]:
    """`(nom de Wally et surnoms, noms des gens)` — les deux moitiés que les
    moteurs à budget de prompt placent différemment (cf. `FasterWhisperSTT._hotwords`)."""
    tete = termes_de_biais(phrases)
    return tete, termes_de_biais(tete, extra_terms)[len(tete):]


def termes_de_biais(phrases, extra_terms=None) -> list[str]:
    """Le nom de Wally d'abord, puis la source de noms ; sans doublon de casse.

    UNE composition pour les trois moteurs (GPU, local, xAI) : un nom connu de
    l'un et ignoré de l'autre changerait ce qu'on entend selon la machine qui
    transcrit. Une source qui lève ne coûte pas l'énoncé : le nom de Wally reste.
    """
    termes = [p for p in (phrases or []) if p]
    if extra_terms is not None:
        try:
            termes += list(extra_terms())
        except Exception as e:  # noqa: BLE001 — un biais optionnel ne coûte pas un énoncé
            logger.debug("voice: source de noms illisible, biais réduit au nom : {e!r}", e=e)
    vus: set[str] = set()
    gardes: list[str] = []
    for terme in termes:
        terme = (terme or "").strip()
        if terme and terme.lower() not in vus:
            vus.add(terme.lower())
            gardes.append(terme)
    return gardes
