# bot/intelligence/pending_question.py
"""Les questions posées au chat que personne n'a relevées.

Le 13/08, 89 réponses sur 89 partaient d'une mention explicite de son nom.
Zéro prise de parole de toute la journée — pendant que l'overlay parlait
toutes les 46 secondes. Conséquence concrète, à 21h14 :

    nicopsg93100 : « comment on fait pour remettre le jeu en français
                     depuis la maj ? »

Le chat a répondu « utilise Duolingo ». Wally s'est tu. C'était exactement le
moment où il servait à quelque chose.

Ce module ne rend PAS la parole spontanée : la coupure du 2026-07-14
(`spontaneous_channel_speak_enabled: false`) tient toujours, et pour une raison
mécanique intacte — un SPEAK cognitif est encore redirigé vers la chambre, où
les gardes « ne crie pas dans le vide » sont sautées. Ce qu'on rouvre est
beaucoup plus étroit : **une vraie question, posée à la cantonade, encore sans
réponse au bout d'un délai**. Ce n'est pas un monologue né de l'ennui, c'est un
besoin réel de quelqu'un qui est là.

La décision finale n'est PAS ici : elle revient au `ResponseGate`, qui voit ce
qui s'est dit depuis et garde le droit de se taire. Ce module tient seulement
le registre.

État de MODULE, comme `_open_questions` dans les handlers. `oublier_tout()`
existe pour les tests (fixture de `conftest.py`).
"""

from __future__ import annotations

import re
import time

from loguru import logger

# En dessous de ce nombre de mots, « quoi ? », « hein ? » ou « ah bon ? » : une
# ponctuation de conversation, pas une demande à laquelle on peut répondre.
_MOTS_MIN = 4

# canal → questions en attente, les plus anciennes d'abord
_EN_ATTENTE: dict[str, list[dict]] = {}

# Une adresse explicite à quelqu'un (« @machin tu fais quoi ? ») : la question
# a déjà son destinataire, s'y inviter n'est pas rendre service.
_ADRESSEE = re.compile(r"@\w")

_URL = re.compile(r"https?://\S+")


def ressemble_a_une_question(texte: str) -> bool:
    """Vrai si ce message pose une question ouverte au canal.

    Mécanique et volontairement pauvre : le point d'interrogation, un minimum
    de matière, personne de nommé. Le jugement — « est-ce que quelqu'un y a
    répondu, et est-ce que je sais ? » — n'appartient pas à un test de forme,
    il revient au gate qui lit le fil.
    """
    texte = (texte or "").strip()
    if "?" not in texte:
        return False
    if _ADRESSEE.search(texte):
        return False
    sans_liens = _URL.sub(" ", texte)
    # Les jetons qui portent quelque chose. Le « ? » détaché compte pour un mot
    # dans un `split()` nu : « c'est quoi ça ? » passait alors le plancher.
    mots = [j for j in sans_liens.split() if any(c.isalnum() for c in j)]
    return len(mots) >= _MOTS_MIN


def noter(canal: str, auteur: str, texte: str, charge=None) -> bool:
    """Enregistre une question restée en l'air. Vrai si elle a été retenue.

    `charge` voyage avec la question sans être regardée : côté Discord, c'est
    le `discord.Message` d'origine, dont la réponse a besoin pour répondre EN
    CITATION plutôt que de lâcher un message orphelin dans le salon.
    """
    if not ressemble_a_une_question(texte):
        return False
    _EN_ATTENTE.setdefault(str(canal), []).append({
        "auteur": auteur,
        "texte": texte,
        "quand": time.monotonic(),
        "charge": charge,
    })
    return True


def relever(canal: str, delai_s: float, oubli_s: float) -> dict | None:
    """La plus ancienne question mûre de ce canal, retirée du registre.

    « Mûre » = posée il y a au moins `delai_s` — laisser au chat le temps de
    répondre lui-même est tout l'intérêt — et pas plus de `oubli_s` : au-delà,
    répondre à une question de cinq minutes d'âge, c'est déterrer.

    Retirée dans TOUS les cas, mûre ou périmée : le registre ne doit pas
    proposer deux fois la même question, sans quoi un refus du gate se rejoue à
    chaque message du canal.
    """
    file = _EN_ATTENTE.get(str(canal))
    if not file:
        return None
    maintenant = time.monotonic()
    mure = None
    restantes = []
    for question in file:
        age = maintenant - question["quand"]
        if age > oubli_s:
            continue                       # trop vieille : on l'oublie
        if mure is None and age >= delai_s:
            question["age_s"] = age
            mure = question
            continue                       # relevée : elle sort du registre
        restantes.append(question)
    if restantes:
        _EN_ATTENTE[str(canal)] = restantes
    else:
        _EN_ATTENTE.pop(str(canal), None)
    if mure is not None:
        logger.info(
            "Question sans réponse relevée dans {c} ({a}) : « {t} »",
            c=canal, a=mure["auteur"], t=mure["texte"][:80],
        )
    return mure


async def le_gate_veut_repondre(
    gate,
    question: dict,
    *,
    auteur_uid: str,
    emotion_state: dict,
    fil: list[dict] | None = None,
    relationship_facts: list | None = None,
) -> tuple[bool, str]:
    """Soumet la question relevée au `ResponseGate`. (répondre ?, motif)

    Partagé par les deux adaptateurs : c'est le même Wally qui décide de se
    taire, qu'on soit sur Twitch ou sur Discord. Sans ce point commun, la
    brèche s'ouvrirait d'un côté et pas de l'autre — le défaut qu'on corrige.

    Le gate ne connaît que RESPOND / IGNORE / REACT / DEFER : sur ce chemin,
    seul RESPOND vaut prise de parole. Un emoji ou un « plus tard » venant de
    quelqu'un qu'on n'a pas sollicité ne veut rien dire.
    """
    if gate is None:
        return False, "gate absent"
    try:
        decision = await gate.decide(
            message_content=question["texte"],
            author_user_id=auteur_uid,
            emotion_state=emotion_state,
            relationship_facts=relationship_facts or [],
            active_desires=[],
            is_triggered=False,
            is_mentioned=False,
            recent_messages=fil,
            unanswered_question_age_s=question.get("age_s", 0.0),
        )
    except Exception as exc:  # noqa: BLE001
        # Repli SILENCIEUX, à l'inverse du chemin « on t'a appelé » où le gate
        # retombe sur RESPOND. Une panne ne doit pas faire parler Wally là où
        # personne ne lui a rien demandé.
        logger.warning("Question sans réponse : gate en échec, on se tait ({e!r})", e=exc)
        return False, f"gate en échec ({exc})"
    motif = decision.reason or ""
    return decision.decision == "RESPOND", motif


def en_attente(canal: str) -> int:
    """Combien de questions dorment encore dans ce canal."""
    return len(_EN_ATTENTE.get(str(canal), ()))


def oublier_canal(canal: str) -> None:
    _EN_ATTENTE.pop(str(canal), None)


def oublier_tout() -> None:
    """Remet le registre à neuf — appelé entre deux tests."""
    _EN_ATTENTE.clear()
