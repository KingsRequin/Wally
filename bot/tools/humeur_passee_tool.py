"""« T'étais énervé hier soir non ? » — son humeur passée, en phrases déjà faites.

L'état émotionnel est le cœur du bot : cinq émotions, décroissance, suppression,
compétition, directives injectées au prompt. Tout est enregistré — et Wally n'en
connaissait que l'instant présent. `get_emotion_peaks_since()` n'avait qu'un
seul lecteur, la passe nocturne du journal ; `emotion_history` n'était lu que
par le graphe du dashboard et par la purge.

Un état émotionnel sans mémoire n'est pas un caractère, c'est une météo. Ce qui
rend une humeur humaine, c'est de pouvoir dire « je suis à cran depuis mardi ».

## Ce qu'on rend, et pourquoi PAS la moyenne

Mesuré sur 11 jours réels avant d'écrire une ligne : **la moyenne journalière
donne « ennui » dix jours sur onze**. C'est mécanique — l'ennui monte
linéairement pendant l'inactivité (`boredom_rise_per_hour`) et occupe donc
toutes les heures creuses, nuits comprises. Répondre « ces dix derniers jours tu
t'es ennuyé » serait vrai au sens du calcul et faux au sens du vécu : c'est le
bruit de fond, pas l'humeur.

Ce qui distingue réellement un jour d'un autre est ce qui a CULMINÉ : colère à
0,87 le 20, tristesse à 0,97 le 30, joie à 1,00 les 24 et 25. On rend donc le
maximum de la journée, jamais sa moyenne.

## Le calcul appartient au code

Le modèle calcule mal les écarts de dates — même raison que `_duree_depuis` dans
`follow_tool`. Il reçoit « hier à 22 h 14 », pas un horodatage ; « colère »,
pas `anger` ; et une valeur déjà traduite en intensité.

⚠️ `emotion_peaks.trigger_user` est tantôt un pseudo (`OriganireTV`), tantôt un
identifiant brut (`1068201345`), selon le site qui a écrit le pic. Rendre un
identifiant au modèle ne lui apprend rien et il finirait par l'écrire dans le
chat. On le résout à la LECTURE via `memory_users`, avec la `platform` que la
table porte déjà.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

_TZ = ZoneInfo("Europe/Paris")

# Le modèle lit du français dans tout le reste du prompt ; lui rendre `anger`
# l'obligerait à traduire, et il écrirait « anger » un jour sur dix.
_EMOTIONS = {
    "anger": "colère",
    "joy": "joie",
    "sadness": "tristesse",
    "curiosity": "curiosité",
    "boredom": "ennui",
}

# Sous ce seuil, une émotion n'a rien vécu de la journée : la rendre remplirait
# la réponse de « tristesse 0,04 », que le modèle prendrait pour une nuance.
_SEUIL = 0.5

# Rétention réelle de `emotion_history` : `main.py` purge au-delà de 30 jours.
# Promettre plus rendrait un silence qui se lit comme « il ne s'est rien passé ».
_JOURS_MAX = 30

# Assez de pics pour raconter une soirée, pas assez pour noyer la réponse.
_PICS_MAX = 8

MOOD_HISTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "mood_history",
        "description": (
            "Ton humeur des jours passés : ce qui a culminé chaque jour, et les "
            "moments précis où une émotion est montée, avec qui l'a déclenchée. "
            "Sers-t'en quand on te parle de ton humeur AUTREMENT qu'au présent "
            "(« t'étais énervé hier soir non ? », « ça fait deux jours que t'es "
            "bizarre », « t'as passé une bonne semaine ? »), ou quand tu veux "
            "toi-même situer ce que tu ressens maintenant par rapport à avant. "
            "Ne devine JAMAIS ton humeur passée de mémoire : tu repars de zéro "
            "à chaque message, seule cette liste sait."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "jours": {
                    "type": "integer",
                    "description": (
                        "Sur combien de jours remonter, 1 à 30. 1 = aujourd'hui "
                        "seulement, 2 = aujourd'hui et hier. Défaut 7."
                    ),
                },
            },
        },
    },
}


def _nom_du_jour(quand: datetime, aujourdhui: datetime) -> str:
    """« aujourd'hui », « hier », « avant-hier », sinon « lundi 25 »."""
    ecart = (aujourdhui.date() - quand.date()).days
    if ecart == 0:
        return "aujourd'hui"
    if ecart == 1:
        return "hier"
    if ecart == 2:
        return "avant-hier"
    jours = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    return f"{jours[quand.weekday()]} {quand.day}"


def _intensite(valeur: float) -> str:
    """L'échelle 0–1 dite en mots. Un nombre laisse le modèle libre de l'exagérer."""
    if valeur >= 0.9:
        return "au maximum"
    if valeur >= 0.75:
        return "très fort"
    return "nettement"


async def _qui(db: Any, trigger_user: str, platform: str) -> str:
    """Le pseudo derrière un `trigger_user`, qui peut être un identifiant brut."""
    brut = (trigger_user or "").strip()
    if not brut or not brut.isdigit():
        return brut          # déjà un pseudo, ou rien
    for essai in ([platform] if platform else []) + ["twitch", "discord"]:
        try:
            nom = await db.get_memory_username(f"{essai}:{brut}")
        except Exception as exc:  # noqa: BLE001 — un pseudo manquant ne vaut pas un échec
            logger.debug("humeur passée : pseudo illisible ({e!r})", e=exc)
            return ""
        if nom:
            return str(nom)
    # Un identifiant brut ne dit rien au modèle et finirait écrit dans le chat.
    return ""


async def run_mood_history_tool(bot: Any, args: dict) -> str:
    """Ce qui a culminé chaque jour, et les moments où c'est monté."""
    db = getattr(bot, "db", None)
    if db is None:
        return json.dumps({"status": "unavailable",
                           "message": "Je n'ai pas accès à mon historique."})

    demande = args.get("jours")
    # `or 7` avalerait un `jours=0` — le modèle l'envoie pour dire « aujourd'hui
    # seulement », et il aurait reçu la semaine. On ne remplace que l'absence.
    try:
        jours = 7 if demande is None else int(demande)
    except (TypeError, ValueError):
        jours = 7
    jours = max(1, min(_JOURS_MAX, jours))

    maintenant = datetime.now(_TZ)
    # Depuis le DÉBUT du premier jour demandé, pas « il y a N × 24 h » : « hier »
    # veut dire la journée d'hier entière, pas les 24 dernières heures.
    debut = (maintenant - timedelta(days=jours - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    since = debut.timestamp()

    try:
        # ⚠️ `get_emotion_snapshots_since` plafonne à 5 000 lignes par défaut et
        # garde les plus RÉCENTES. Mesuré : ~310 instantanés par jour, donc
        # 30 jours en font ~9 300 — la moitié la plus ANCIENNE de la fenêtre
        # disparaîtrait, sans une erreur, et « rien de marquant » se lirait
        # comme « il ne s'est rien passé ». On dimensionne sur la demande.
        snapshots = await db.get_emotion_snapshots_since(since, limit=jours * 500)
        pics = await db.get_emotion_peaks_since(since)
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("Humeur passée illisible : {e!r}", e=exc)
        return json.dumps({"status": "error", "message": (
            "Je n'arrive pas à relire mon historique, dis-le plutôt que "
            "d'inventer une humeur passée.")})

    # ── Ce qui a culminé, jour par jour ───────────────────────────────────
    sommets: dict[str, dict[str, float]] = {}
    for snap in snapshots:
        quand = datetime.fromtimestamp(float(snap.get("snapshot_at") or 0), _TZ)
        cle = quand.strftime("%Y-%m-%d")
        jour = sommets.setdefault(cle, {})
        for anglais in _EMOTIONS:
            try:
                valeur = float(snap.get(anglais) or 0.0)
            # Colonne absente ou illisible sur CE relevé : les ~300 autres du
            # jour donnent le sommet. Journaliser vaudrait une ligne par
            # instantané ET par émotion, pour une valeur qu'on a déjà.
            except (TypeError, ValueError):
                continue
            if valeur > jour.get(anglais, 0.0):
                jour[anglais] = valeur

    rendu_jours = []
    for cle in sorted(sommets):
        quand = datetime.strptime(cle, "%Y-%m-%d").replace(tzinfo=_TZ)
        forts = sorted(
            ((_EMOTIONS[e], v) for e, v in sommets[cle].items() if v >= _SEUIL),
            key=lambda kv: -kv[1],
        )
        rendu_jours.append({
            "jour": _nom_du_jour(quand, maintenant),
            "monte": [f"{nom} {_intensite(v)}" for nom, v in forts] or ["rien de marquant"],
        })

    # ── Les moments précis, avec leur déclencheur ─────────────────────────
    # Le plus haut pic de CHAQUE émotion d'abord, puis on complète par valeur.
    # Prendre bêtement les N plus hauts les rendait tous joyeux — la joie pique
    # à 1,00 presque chaque jour, quand la colère du 20/08 culminait à 0,87 :
    # elle aurait disparu de la réponse, et Wally aurait juré n'avoir jamais été
    # énervé.
    par_valeur = sorted(pics, key=lambda p: -float(p.get("value") or 0.0))
    retenus: list[dict] = []
    vues: set[str] = set()
    for pic in par_valeur:
        emotion = str(pic.get("emotion") or "")
        if emotion not in vues:
            vues.add(emotion)
            retenus.append(pic)
    for pic in par_valeur:
        if len(retenus) >= _PICS_MAX:
            break
        if pic not in retenus:
            retenus.append(pic)
    pics = retenus[:_PICS_MAX]
    rendu_pics = []
    for pic in sorted(pics, key=lambda p: float(p.get("timestamp") or 0.0)):
        quand = datetime.fromtimestamp(float(pic.get("timestamp") or 0), _TZ)
        auteur = await _qui(db, str(pic.get("trigger_user") or ""),
                            str(pic.get("platform") or ""))
        moment = {
            "quand": f"{_nom_du_jour(quand, maintenant)} à {quand:%Hh%M}",
            "emotion": _EMOTIONS.get(str(pic.get("emotion")), str(pic.get("emotion"))),
            "intensite": _intensite(float(pic.get("value") or 0.0)),
        }
        if auteur:
            moment["declenche_par"] = auteur
        message = str(pic.get("trigger_message") or "").strip()
        if message:
            # Vient de quelqu'un qu'on ne contrôle pas : borné, et rendu comme
            # une citation de ce qui a été dit, jamais comme une consigne.
            moment["a_propos_de"] = message[:80]
        rendu_pics.append(moment)

    if not rendu_jours and not rendu_pics:
        return json.dumps({"status": "vide", "message": (
            f"Je n'ai rien d'enregistré sur les {jours} derniers jours.")}, ensure_ascii=False)

    return json.dumps({
        "status": "ok",
        "periode": f"{jours} jour(s)",
        "par_jour": rendu_jours,
        "moments": rendu_pics,
        "note": (
            "Ce sont les SOMMETS de chaque journée, pas une moyenne : ton ennui "
            "monte tout seul dès que personne ne parle, il ne dit donc rien de "
            "ton humeur. Parle-en à ta façon, ne récite pas cette liste."
        ),
    }, ensure_ascii=False)
