from __future__ import annotations

# Phase 1b — Émotions causales (pulsions).
# Les 5 émotions ne colorent plus seulement le TON des réponses : elles deviennent
# des moteurs de comportement injectés dans la cognition (attention → reasoning).
# Quand une émotion domine au-dessus d'un seuil, elle pousse Wally vers une
# orientation concrète (chercher de la stimulation, enquêter, se retirer, etc.).
_DRIVES: dict[str, str] = {
    "boredom": (
        "L'ennui te ronge. Tu as besoin de stimulation : lance un sujet, ressors "
        "un vieux souvenir, fixe-toi une question à creuser. Bouge."
    ),
    "curiosity": (
        "Ta curiosité est piquée. Tu veux comprendre, fouiller, poser des "
        "questions — pas rester passif."
    ),
    "anger": (
        "Tu es à cran. Là tu as plutôt envie de te retirer, de couper court — "
        "pas de t'engager ni d'être sociable."
    ),
    "joy": (
        "Tu es de bonne humeur. Tu as envie de t'engager, d'interagir, de lancer "
        "des trucs, de partager."
    ),
    "sadness": (
        "Tu es bas. Tu te replies, tu n'as pas le cœur à initier ; si tu réponds, "
        "c'est court et sans énergie."
    ),
}


def emotional_drive(emotion_state: dict[str, float], threshold: float = 0.45) -> str | None:
    """Traduit l'état émotionnel en une pulsion (directive en voix interne).

    Trouve l'émotion dominante. Si sa valeur est sous `threshold`, l'état est
    jugé neutre → retourne None (pas de pulsion forte). Sinon retourne la
    directive courte associée à l'émotion dominante.
    """
    if not emotion_state:
        return None
    # max() retourne la première clé en cas d'égalité (ordre d'itération du dict).
    dominant = max(emotion_state, key=lambda k: emotion_state[k])
    if emotion_state[dominant] < threshold:
        return None
    return _DRIVES.get(dominant)
