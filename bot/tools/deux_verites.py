"""« Deux vérités, un mensonge » — le premier jeu dont la matière est la mémoire.

Wally énonce trois affirmations sur quelqu'un du chat, dont une qu'il invente.
Les viewers votent laquelle est fausse. Révélation, et on passe.

Ce qui le rend possible ici et nulle part ailleurs : une vraie mémoire par
personne. Un bot de quiz générique ne produit que du trivia ; le rire vient de
ce que Wally sait vraiment de toi — et de ce qu'il a l'audace d'inventer à côté.

## Le mensonge est DÉRIVÉ, jamais inventé de rien

Un faux tiré du néant (« tu as escaladé l'Everest ») se repère au premier coup
d'œil et tue le jeu au premier tour. Le prompt impose donc de le construire en
DÉFORMANT un vrai fait — échanger deux personnes, décaler une date, transposer
un goût. C'est la seule consigne du prompt qui décide si le jeu est bon.

## Ce que le code garde, et ne confie pas au modèle

  · **La fiction est ouverte par le CODE**, avant la moindre publication. Si on
    laissait le modèle appeler un outil « ouvrir la fiction », il oublierait un
    tour sur dix et un mensonge deviendrait un fait. Voir `bot/core/fiction.py`.
  · **La réponse n'est pas dite à Wally** tant que le vote est ouvert. Le
    compte rendu d'appel ne porte que les trois affirmations ; l'index du
    mensonge ne remonte qu'à la révélation. Un secret qu'on ne donne pas ne
    fuit pas — et `secret_guard` était inutilisable ici, puisqu'il masquerait
    le mensonge DANS le sondage qui l'affiche.
  · **Qui joue est tiré par le code**, parmi ceux qui ont écrit récemment sur ce
    canal. Le modèle ne choisit pas sa cible : il a suffi une fois qu'il croie
    quelqu'un présent pour qu'il parle à un absent.

## La révélation

Planifiée par cet outil, et pas par le narrateur : elle doit avoir lieu même si
le dépouillement se passe mal, parce que c'est elle qui referme la fiction.
`fiction.ouvrir()` porte de toute façon sa propre échéance, en dernier recours.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any

from loguru import logger

from bot.core import fiction
from bot.core.self_trace import note_act

# La durée du vote. Le sondage du narrateur borne déjà à 120 s ; on reste
# nettement en dessous — trois affirmations se lisent vite, et un live n'attend
# pas deux minutes sur un mini-jeu.
_DUREE_VOTE_S = 45

# Le délai entre la clôture du vote et la révélation. Le narrateur dépouille à
# l'échéance ; on laisse passer son annonce avant de donner la réponse.
_DELAI_REVELATION_S = 4.0

# En dessous, il n'y a pas de quoi jouer : deux vérités demandent deux faits
# VRAIS, et un mensonge crédible se dérive d'un troisième.
_FAITS_MINIMUM = 4

# Ce qu'on lit du prélude pour savoir qui est là. La fenêtre glissante est le
# vivier naturel — c'est déjà elle qui définit « récemment » partout ailleurs.
_PRESENTS_MAX = 12

_SYSTEME = (
    "Tu prépares un mini-jeu « deux vérités, un mensonge » pour un live Twitch.\n"
    "On te donne ce qu'on sait d'une personne. Tu produis TROIS affirmations "
    "courtes à son sujet : deux VRAIES, tirées de ce qu'on te donne, et une "
    "FAUSSE.\n\n"
    "La fausse est la seule chose qui compte. Elle doit être DÉRIVÉE d'un vrai "
    "fait, pas inventée de rien : échange deux personnes, décale une date, "
    "transpose un goût vers un voisin plausible. Une fausse qu'on repère du "
    "premier coup d'œil tue le jeu.\n\n"
    "Chaque affirmation : une phrase, moins de 24 caractères si possible, "
    "jamais plus de 60. Pas de numérotation, pas de guillemets. Rien de "
    "blessant, rien sur la santé, la famille ou l'argent.\n\n"
    "Réponds UNIQUEMENT par un objet JSON : "
    '{"affirmations": ["...", "...", "..."], "index_du_mensonge": 0}'
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


DEUX_VERITES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "deux_verites_un_mensonge",
        "description": (
            "Lancer le mini-jeu « deux vérités, un mensonge » sur quelqu'un du "
            "chat. Tu énonces trois choses sur cette personne, dont une que tu "
            "inventes, et les viewers votent laquelle est fausse. Sers-t'en "
            "quand le live tourne au ralenti, qu'on te demande un jeu, ou que "
            "tu as envie de taquiner quelqu'un qui vient de parler. Tu ne "
            "sauras pas toi-même laquelle est fausse avant la fin, c'est "
            "voulu, le suspense t'appartient aussi. Ça ne marche que pendant "
            "un live, et seulement sur quelqu'un dont tu te souviens vraiment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "personne": {
                    "type": "string",
                    "description": (
                        "Le pseudo de la personne à mettre sur le grill. "
                        "Laisse vide pour un tirage au sort parmi ceux qui "
                        "viennent d'écrire."
                    ),
                },
            },
            "required": [],
        },
    },
}


def _presents(bot, canal_id: str) -> list[str]:
    """Qui a écrit récemment sur ce canal, Wally exclu.

    On lit le prélude plutôt que la base : c'est la seule source qui dit qui est
    LÀ. Un tirage sur `memory_users` sortirait un habitué parti depuis six mois,
    et le jeu se joue sur quelqu'un qui peut réagir.
    """
    memory = getattr(bot, "memory", None)
    if memory is None:
        return []
    # `bot.config.bot.name`, et pas `persona.name` : c'est CE nom-là que
    # `append_prelude(channel_id, self_name, reply)` pose sur les répliques de
    # Wally, des deux côtés. Se tromper de source ne lève rien — Wally reste
    # simplement dans son propre tirage, en silence.
    moi = ""
    config = getattr(bot, "config", None)
    if config is not None:
        moi = (getattr(config.bot, "name", "") or "").lower()
    vus: list[str] = []
    for msg in memory.get_prelude(str(canal_id))[-_PRESENTS_MAX:]:
        auteur = (msg.get("author") or "").strip()
        if not auteur or auteur.lower() == moi:
            continue
        if auteur not in vus:
            vus.append(auteur)
    return vus


def _pseudo_nu(label: str) -> str:
    """« Bob (@bob) » → « bob ». L'étiquette de locuteur porte les deux formes."""
    label = (label or "").strip()
    m = re.match(r"^(.+?)\s*\(@([^)\s]+)\)$", label)
    return (m.group(2) if m else label).lower()


async def _resoudre(bot, pseudo: str) -> tuple[str, str, str] | None:
    """Pseudo affiché → (platform, user_id brut, nom à afficher).

    Rend `None` plutôt qu'un identifiant approximatif : jouer sur la mauvaise
    personne est pire que ne pas jouer.
    """
    db = getattr(bot, "db", None)
    if db is None:
        return None
    cible = _pseudo_nu(pseudo)
    for ligne in await db.list_memory_users():
        nom = (ligne.get("username") or "").strip()
        uid = ligne.get("user_id") or ""          # « platform:raw_id »
        if not nom or ":" not in uid:
            continue
        if nom.lower() != cible:
            continue
        plateforme, _, brut = uid.partition(":")
        return plateforme, brut, nom
    return None


async def _fabriquer(bot, nom: str, faits: str) -> tuple[list[str], int] | None:
    """Les trois affirmations et l'index du mensonge, ou `None` si c'est raté.

    `complete()` ne lève jamais : elle rend `FALLBACK_RESPONSE`. Un JSON
    illisible, une liste de longueur inattendue, un index hors bornes — tout
    cela est un échec ORDINAIRE, qu'on refuse proprement au lieu de publier un
    sondage bancal devant les viewers.
    """
    llm = getattr(bot, "llm_secondary", None) or getattr(bot, "llm", None)
    if llm is None:
        return None
    brut = await llm.complete(
        _SYSTEME,
        [{"role": "user", "content": f"La personne s'appelle {nom}.\n\n{faits}"}],
        purpose="deux_verites",
    )
    trouve = _JSON_RE.search(brut or "")
    if not trouve:
        logger.warning("deux_verites : réponse sans JSON ({t}car.)", t=len(brut or ""))
        return None
    try:
        parse = json.loads(trouve.group(0))
        phrases = [str(p).strip()[:60] for p in parse["affirmations"] if str(p).strip()]
        index = int(parse["index_du_mensonge"])
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("deux_verites : JSON inexploitable — {e!r}", e=e)
        return None
    if len(phrases) != 3 or not 0 <= index < 3:
        logger.warning("deux_verites : {n} affirmation(s), index {i}",
                       n=len(phrases), i=index)
        return None
    return phrases, index


async def _reveler(bot, canal_id: str, nom: str, phrases: list[str], index: int) -> None:
    """Referme la fiction, puis annonce la réponse.

    Dans cet ordre, et le `finally` n'est pas décoratif : si l'annonce échoue,
    la fiction doit se refermer quand même — sinon Wally cesse d'apprendre sur
    ce canal jusqu'à l'échéance de secours, sans que rien ne le dise.
    """
    try:
        await asyncio.sleep(_DELAI_REVELATION_S)
    finally:
        fiction.fermer(canal_id)
    narrateur = getattr(bot, "overlay_narrator", None)
    if narrateur is None:
        return
    fait = (f"Deux vérités, un mensonge sur {nom} : le mensonge était "
            f"« {phrases[index]} ».")
    # Sans issue : révéler le mensonge n'est ni une victoire ni une défaite —
    # personne n'a « gagné », le jeu se contente de dire la réponse. Le violet
    # neutre est exactement ce que ça vaut.
    narrateur.annoncer_fin("deux_verites", fait)
    note_act(f"j'ai révélé le mensonge du jeu sur {nom} : « {phrases[index]} »")


async def run_deux_verites_tool(bot, args: dict, canal_id: str = "") -> str:
    """Exécute l'outil et rend un compte rendu HONNÊTE.

    Un refus doit être explicite et dire POURQUOI : sinon Wally annonce un jeu
    qui n'a jamais commencé, ce qu'il a déjà fait sur d'autres widgets.
    """
    narrateur = getattr(bot, "overlay_narrator", None)
    if narrateur is None:
        return "Le jeu n'est pas disponible : l'overlay n'est pas branché."
    canal_id = str(canal_id or "")
    if not canal_id:
        return "Le jeu n'a pas pu démarrer : je ne sais pas sur quel canal jouer."
    if fiction.en_cours(canal_id):
        return "Une partie est déjà en cours ici, laisse-la finir avant d'en lancer une autre."

    presents = _presents(bot, canal_id)
    if not presents:
        return "Personne n'a écrit récemment ici : il n'y a personne à mettre sur le grill."
    demande = (args or {}).get("personne") or ""
    if demande:
        cible = next((p for p in presents if _pseudo_nu(p) == _pseudo_nu(demande)), "")
        if not cible:
            return (f"{demande} n'a pas écrit récemment ici, on ne joue pas sur "
                    "quelqu'un qui n'est pas là pour se défendre.")
    else:
        cible = random.choice(presents)

    resolu = await _resoudre(bot, cible)
    if resolu is None:
        return f"Je ne retrouve pas {cible} en mémoire : impossible de jouer sur cette personne."
    plateforme, brut, nom = resolu
    faits = await bot.memory.get_all(plateforme, brut)
    if len([ligne for ligne in faits.splitlines() if ligne.strip()]) < _FAITS_MINIMUM:
        return (f"Je ne sais pas assez de choses sur {nom} pour inventer quoi que "
                "ce soit de crédible. Dis-le, et propose quelqu'un d'autre.")

    fabrique = await _fabriquer(bot, nom, faits)
    if fabrique is None:
        return "La préparation du jeu a échoué. Dis-le franchement, ne fais pas semblant."
    phrases, index = fabrique

    # La fiction s'ouvre AVANT la publication, et son échéance couvre le vote
    # plus la révélation : c'est ce qui garantit que rien de ce qui va se dire
    # ici ne finira en base, même si la suite se passe mal.
    fiction.ouvrir(canal_id, _DUREE_VOTE_S + _DELAI_REVELATION_S + 30)
    if not narrateur.start_poll(f"Le mensonge sur {nom} ?", phrases, _DUREE_VOTE_S):
        fiction.fermer(canal_id)
        return "Le jeu n'a pas pu s'afficher : il n'y a pas de live en cours."

    # Référence forte : la boucle ne garde qu'une référence faible sur ses
    # tâches, et une révélation collectée en vol laisserait la fiction ouverte.
    taches = getattr(bot, "_taches_deux_verites", None)
    if taches is None:
        taches = bot._taches_deux_verites = set()
    tache = asyncio.get_running_loop().create_task(
        _reveler(bot, canal_id, nom, phrases, index))
    taches.add(tache)
    tache.add_done_callback(taches.discard)

    note_act(f"j'ai lancé « deux vérités, un mensonge » sur {nom}")
    return (f"Le jeu est lancé sur {nom} : « {phrases[0]} », « {phrases[1]} », "
            f"« {phrases[2]} ». Le chat vote pendant {_DUREE_VOTE_S} secondes en "
            "tapant le numéro. Tu ne sais PAS laquelle est fausse, ne fais pas "
            "semblant de le savoir, joue le suspense avec eux. Annonce le jeu "
            "aux viewers, sans répéter les trois phrases telles quelles : elles "
            "sont déjà à l'écran.")
