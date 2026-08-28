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


# Les trois outils de mémoire, offerts en bloc aux trois plateformes. Leur
# DÉFINITION vivait dans `discord/handlers.py` — un adapter que Twitch et le
# vocal importaient — pendant que leur exécution était ici. Les deux moitiés
# du même outil, dans deux dossiers différents.
NOTE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_persistent_note",
            "description": (
                "Quand quelqu'un te demande de retenir, noter ou mémoriser quelque chose "
                "qui concerne tout le serveur ou la communauté (un événement, une règle, "
                "une info partagée, un engagement que tu prends), utilise cet outil. "
                "La note sera injectée dans TOUTES tes futures conversations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre court et unique de la note"},
                    "content": {"type": "string", "description": "Contenu de la note"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_persistent_note",
            "description": "Supprimer une note persistante par son titre",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titre exact de la note à supprimer"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_user_memory",
            "description": (
                "Quand quelqu'un te demande de retenir, noter ou mémoriser quelque chose "
                "qui le concerne personnellement (préférence, fait biographique, opinion, "
                "habitude, info privée), utilise cet outil. Le souvenir sera associé "
                "uniquement à cet utilisateur."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Fait ou information à retenir sur cet utilisateur, formulé comme une phrase factuelle courte",
                    },
                },
                "required": ["content"],
            },
        },
    },
]


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


async def run_delete_note_tool(db, args: dict) -> str:
    """Retire une note persistante. Un seul écrivain pour les trois plateformes.

    Ce corps existait en TROIS copies strictement identiques — Discord, Twitch,
    vocal — alors que rien n'y est propre à une plateforme.

    Les deux issues sont distinctes et le RESTENT : « supprimée » et
    « introuvable » ne disent pas la même chose, et les confondre ferait annoncer
    la suppression d'une note toujours en place.
    """
    titre = str(args.get("title") or "").strip()
    if not titre:
        return json.dumps({"status": "error", "message": (
            "Il me faut le titre de la note à supprimer."
        )})
    if await db.delete_persistent_note(titre):
        return json.dumps({"status": "ok", "message": f"Note '{titre}' supprimée."})
    return json.dumps({"status": "not_found", "message": f"Note '{titre}' introuvable."})


async def run_save_user_memory_tool(
    memory, args: dict, *, platform: str, user_id: str,
    username: str | None, origin: str,
) -> str:
    """Retient un fait sur QUELQU'UN — par opposition à la note, qui vaut pour tous.

    Ce corps aussi vivait en trois copies, garde anti-surnom comprise : celle-là
    même qui a motivé ce module. Un garde-fou recopié trois fois est un garde-fou
    qu'on oubliera de poser deux fois sur trois.

    Ce qui est vraiment propre à la plateforme — l'identité de la personne et
    l'origine du souvenir — arrive par paramètres. `user_id` est l'id BRUT :
    `memory.add()` construit `platform:user_id` lui-même.
    """
    contenu = str(args.get("content") or "").strip()
    if not contenu:
        return json.dumps({"status": "error",
                           "message": "Il me faut ce que je dois retenir."})

    # Le refus est DIT, pas avalé : le store refuserait d'écrire de toute façon,
    # mais en silence — Wally répondrait « c'est noté » sur un souvenir absent.
    refus = detecter_surnom(contenu, f"{platform}:{user_id}")
    if refus is not None:
        logger.info("save_user_memory refusé ({r}) : « {c} »", r=refus, c=contenu[:120])
        return json.dumps({"status": "denied", "message": REFUS_SURNOM})

    await memory.add(platform, user_id, contenu, username=username, origin=origin)
    return json.dumps({"status": "ok", "message": "Souvenir sauvegardé."})
