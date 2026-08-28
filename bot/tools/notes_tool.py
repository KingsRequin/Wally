"""Ranger une note valable pour TOUT LE MONDE — et refuser d'y coller un surnom.

Une note persistante n'est pas un souvenir sur quelqu'un : elle part dans
CHAQUE conversation des trois plateformes, titre compris
(`build_system_prompt` rend « **{titre}** : {contenu} »). C'est le texte le
plus fort de tout le prompt — il est là à tous les appels, et il est rédigé
comme une consigne.

Le 2026-08-26, l'owner constate que Wally l'appelle encore « petit chevreuil »
en plein live. Le garde-fou du 2026-08-25 (`bot/core/surnoms.py`) tenait
pourtant les deux points d'écriture des FAITS. Il manquait celui-ci : la note
n° 30, écrite le 2026-08-20, disait « À employer pour désigner KingsRequin » —
un ordre, réinjecté à chaque tour, qui battait la consigne du prompt exactement
comme un portrait bat une consigne.

L'exécution vivait en TROIS copies (Discord, Twitch, vocal). Les garder
séparées, c'est se condamner à poser le prochain garde-fou deux fois sur
trois : elle est ici, avec un seul écrivain.
"""
import json

from loguru import logger

from bot.core.surnoms import REFUS as REFUS_SURNOM, detecter as detecter_surnom


async def run_save_note_tool(db, args: dict) -> str:
    """Range une note persistante, ou dit pourquoi elle est refusée.

    `db` porte `upsert_persistent_note`. Pas de `user_id` : une note ne
    concerne personne en particulier, donc l'exemption `wally:self` du garde ne
    s'y applique jamais — ce qui est écrit là est réinjecté à tout le monde.
    """
    # `.get()` et non `args["title"]` : `required` au schéma ne garantit rien.
    # Un champ omis levait un KeyError au milieu de `complete_with_tools` — le
    # modèle n'obtenait aucun résultat pour son appel et annonçait quand même
    # « c'est noté ».
    titre = str(args.get("title") or "").strip()
    contenu = str(args.get("content") or "").strip()
    if not titre or not contenu:
        return json.dumps({"status": "error", "message": (
            "Il me faut un titre ET un contenu pour noter. Redemande-les."
        )})

    # Le titre AUTANT que le contenu : « Surnom de KingsRequin » s'affiche en
    # gras dans chaque prompt et suffit à réapprendre l'étiquette.
    refus = detecter_surnom(contenu, None) or detecter_surnom(titre, None)
    if refus is not None:
        # Le refus est DIT, pas avalé : sans cette ligne Wally répondrait
        # « c'est noté » sur une note qui n'existe pas.
        logger.info("save_persistent_note refusé ({r}) : « {t} » — « {c} »",
                    r=refus, t=titre[:60], c=contenu[:120])
        return json.dumps({"status": "denied", "message": REFUS_SURNOM})

    await db.upsert_persistent_note(titre, contenu)
    return json.dumps({"status": "ok", "message": f"Note '{titre}' sauvegardée."})
