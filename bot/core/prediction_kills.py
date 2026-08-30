# bot/core/prediction_kills.py
"""Une prédiction Twitch que Wally résout lui-même sur les kills (§13).

Arbitré avec l'owner : c'est **Wally qui compose les tranches** — pas une table
en dur, comme partout ailleurs dans ce projet. Mais pour qu'il puisse résoudre,
chaque choix doit porter ses BORNES, et le découpage doit couvrir tous les cas
sans trou ni recouvrement.

Ce n'est pas de la pédanterie : sur un pari « 0-2 / 4-6 », une partie à 3 kills
n'a aucun gagnant, et les points des viewers restent bloqués dans une prédiction
que personne ne peut plus trancher. La vérification arrive donc AVANT l'appel à
Twitch — une prédiction qu'on ne saurait pas résoudre ne doit jamais s'ouvrir.

Et quand le résultat n'est pas mesurable (compteurs figés, Mixtape), on ANNULE :
Twitch rembourse tout le monde. Résoudre au hasard punirait des gens qui avaient
raison.
"""
from __future__ import annotations

from itertools import pairwise

from loguru import logger

from bot.core.etat_persistant import EtatPersistant


def verifier_tranches(tranches: list[dict] | None) -> str | None:
    """`None` si le découpage est résolvable, sinon ce qui cloche, en français.

    Le message est LU PAR LE MODÈLE : il doit dire quoi corriger, sinon Wally
    réessaie à l'identique.
    """
    propres = []
    for t in tranches or []:
        if not isinstance(t, dict) or not str(t.get("label") or "").strip():
            return "chaque choix a besoin d'un libellé."
        try:
            bas = int(t.get("min"))
        except (TypeError, ValueError):
            return f"le choix « {t.get('label')} » n'a pas de borne basse (`min`)."
        haut = t.get("max")
        try:
            haut = None if haut is None else int(haut)
        except (TypeError, ValueError):
            return f"la borne haute de « {t.get('label')} » n'est pas un nombre."
        if haut is not None and haut < bas:
            return f"« {t.get('label')} » finit avant de commencer."
        propres.append({"label": str(t["label"]).strip(), "min": bas, "max": haut})

    if len(propres) < 2:
        return "il faut au moins deux choix pour un pari."
    propres.sort(key=lambda t: t["min"])
    if propres[0]["min"] != 0:
        return ("il manque le cas ZÉRO kill, mourir sans tuer arrive, et c'est "
                "même ce que le chat commente le plus.")
    # Une seule borne ouverte, et à la fin : sinon deux choix se recouvrent à
    # l'infini.
    for t in propres[:-1]:
        if t["max"] is None:
            return f"« {t['label']} » est ouverte alors qu'un choix la suit."
    if propres[-1]["max"] is not None:
        return (f"le dernier choix (« {propres[-1]['label']} ») doit être ouvert "
                f"(pas de `max`) : une partie à 15 kills doit avoir un gagnant.")
    for precedent, suivant in pairwise(propres):
        attendu = precedent["max"] + 1
        if suivant["min"] < attendu:
            return (f"« {precedent['label']} » et « {suivant['label']} » se "
                    f"chevauchent : deux gagnants pour le même score.")
        if suivant["min"] > attendu:
            return (f"il manque {attendu} entre « {precedent['label']} » et "
                    f"« {suivant['label']} » : ce score n'aurait pas de gagnant.")
    return None


def tranche_gagnante(tranches: list[dict], kills: int) -> dict | None:
    """La tranche qui contient ce score. `None` si le découpage est troué."""
    for t in tranches or []:
        bas = int(t.get("min") or 0)
        haut = t.get("max")
        if kills >= bas and (haut is None or kills <= int(haut)):
            return t
    return None


class PredictionKills:
    """La prédiction en cours, et sa résolution automatique."""

    # Un pari ouvert engage les POINTS DES VIEWERS : tant qu'il n'est ni résolu
    # ni annulé, leurs mises sont bloquées chez Twitch. Il vivait en RAM, et les
    # rebuilds sont fréquents (cinq le 19/08 entre 20 h et 23 h) — un seul
    # suffisait à l'oublier pour de bon.
    #
    # PAS borné à la session du live, contrairement au suivi des kills : une
    # prédiction ouverte chez Twitch le reste, live ou pas. Seul l'âge la périme,
    # et douze heures couvrent large une soirée de stream.
    CLE_ETAT = "twitch:prediction_kills"
    AGE_MAX_S = 12 * 3600

    def __init__(self, db=None) -> None:
        self.en_cours: dict | None = None
        self._etat = EtatPersistant(db, self.CLE_ETAT, session=lambda: "",
                                    age_max_s=self.AGE_MAX_S)

    async def charger(self) -> None:
        """Reprend le pari laissé ouvert par le process précédent."""
        donnees = await self._etat.charger()
        pari = donnees.get("pari") if isinstance(donnees, dict) else None
        if not isinstance(pari, dict) or not pari.get("id"):
            return
        tranches = pari.get("tranches")
        if not isinstance(tranches, list) or not tranches:
            return
        self.en_cours = {"id": str(pari["id"]),
                         "titre": str(pari.get("titre") or ""),
                         "tranches": [t for t in tranches if isinstance(t, dict)]}
        logger.info("Prédiction kills reprise du process précédent : « {t} »",
                    t=self.en_cours["titre"])

    async def ranger(self) -> None:
        """Range l'état courant. Appelé à CHAQUE mutation d'`en_cours`.

        Y compris quand il repasse à `None` : un pari soldé qui resterait rangé
        ressusciterait au prochain démarrage et bloquerait le suivant
        (« une prédiction est déjà en cours »).
        """
        if self.en_cours is None:
            await self._etat.oublier()
            return
        await self._etat.ranger({"pari": self.en_cours})

    async def ouvrir(self, bot, titre: str, tranches: list[dict],
                     fenetre_s: int) -> dict:
        """Ouvre le pari. Rend `{"ok": ..., "raison": ...}`."""
        if self.en_cours is not None:
            return {"ok": False,
                    "raison": "une prédiction est déjà en cours sur cette chaîne."}
        faute = verifier_tranches(tranches)
        if faute:
            # AVANT tout appel à Twitch : une prédiction ouverte qu'on ne saurait
            # pas résoudre bloquerait les points de tout le monde.
            return {"ok": False, "raison": f"découpage inutilisable, {faute}"}

        api = getattr(bot, "twitch_api", None)
        if api is None:
            return {"ok": False, "raison": "l'API Twitch n'est pas disponible."}
        pred = await api.creer_prediction(titre, [t["label"] for t in tranches],
                                          fenetre_s)
        if not pred:
            # Rien n'est retenu : une prédiction fantôme ferait refuser la
            # suivante « une prédiction est déjà en cours » alors qu'il n'y en a
            # aucune.
            return {"ok": False,
                    "raison": "Twitch a refusé d'ouvrir la prédiction "
                              "(autorisation manquante ? voir les logs)."}

        # On relie chaque tranche à l'identifiant rendu par Twitch : c'est avec
        # LUI qu'on résout, les libellés ne suffisent pas.
        par_libelle = {o["title"]: o["id"] for o in pred.get("outcomes") or []}
        self.en_cours = {
            "id": pred["id"],
            "titre": pred.get("title") or titre,
            "tranches": [{**t, "outcome_id": par_libelle.get(t["label"], "")}
                         for t in tranches],
        }
        await self.ranger()
        logger.info("Prédiction kills ouverte : « {t} »", t=self.en_cours["titre"])
        return {"ok": True, "titre": self.en_cours["titre"]}

    async def sur_bilan(self, bot, bilan: dict) -> bool:
        """Appelé à chaque fin de partie. Vrai si la prédiction a été soldée."""
        if self.en_cours is None:
            return False
        api = getattr(bot, "twitch_api", None)
        if api is None:
            return False
        pred = self.en_cours
        kills = (bilan or {}).get("partie")

        if not isinstance(kills, int) or isinstance(kills, bool) or kills < 0:
            # Non mesurable : personne ne peut dire qui avait raison, donc tout
            # le monde récupère ses points.
            logger.info("Prédiction kills : partie non mesurable — annulation")
            if await api.annuler_prediction(pred["id"]):
                self.en_cours = None
                await self.ranger()
                return True
            return False

        gagnante = tranche_gagnante(pred["tranches"], kills)
        if gagnante is None or not gagnante.get("outcome_id"):
            # Le découpage a été vérifié à l'ouverture : y arriver signifie que
            # Twitch n'a pas rendu l'identifiant d'un choix. Rembourser reste
            # plus juste que de désigner un gagnant au hasard.
            logger.warning("Prédiction kills : aucun choix pour {k} kill(s) — annulation",
                           k=kills)
            if await api.annuler_prediction(pred["id"]):
                self.en_cours = None
                await self.ranger()
                return True
            return False

        if not await api.resoudre_prediction(pred["id"], gagnante["outcome_id"]):
            # Gardée : on réessaiera à la partie suivante plutôt que de
            # l'abandonner avec les points des viewers dedans.
            return False
        logger.info("Prédiction kills résolue : {k} kill(s) → « {l} »",
                    k=kills, l=gagnante["label"])
        self.en_cours = None
        await self.ranger()
        return True


# ── L'outil du chat Twitch ──────────────────────────────────────────────────

# Mêmes rôles que la musique et le vocal, et pour la même raison : un pari
# engage les points des viewers. Le broadcaster porte « admin ».
_ROLES_AUTORISES = {"moderator", "admin"}

# Ce que dure la fenêtre de pari si personne n'en demande une. Deux minutes :
# le temps du lobby entre deux parties, pas plus — au-delà, la partie a
# commencé et on parie sur ce qu'on voit déjà.
FENETRE_DEFAUT_S = 120

PREDICTION_TOOL = {
    "type": "function",
    "function": {
        "name": "open_prediction",
        "description": (
            "Ouvre un PARI Twitch où les viewers misent leurs points de chaîne, "
            "sur le nombre de kills que va faire le streamer dans sa prochaine "
            "partie (« combien de kills ? », « on parie ? »). Tu composes "
            "toi-même les tranches. Tu le RÉSOUS tout seul à la fin de la "
            "partie, donc chaque choix doit porter ses bornes. Réservé aux "
            "MODÉRATEURS et au streamer : appelle quand même l'outil si "
            "quelqu'un d'autre le demande, tu sauras quoi répondre."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "titre": {
                    "type": "string",
                    "description": "La question posée aux viewers, 45 caractères max.",
                },
                "choix": {
                    "type": "array",
                    "description": (
                        "Les tranches, dans l'ordre. Elles doivent couvrir TOUS "
                        "les scores possibles sans trou ni chevauchement : la "
                        "première part de 0, la dernière n'a pas de `max`."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string",
                                      "description": "Ce que les viewers lisent (25 car. max)."},
                            "min": {"type": "integer",
                                    "description": "Nombre de kills minimum de cette tranche."},
                            "max": {"type": "integer",
                                    "description": "Maximum inclus. À OMETTRE sur la dernière."},
                        },
                        "required": ["label", "min"],
                    },
                },
                "secondes": {
                    "type": "integer",
                    "description": "Durée des paris (30 à 1800). 120 par défaut.",
                },
            },
            "required": ["titre", "choix"],
        },
    },
}


async def run_prediction_tool(bot, args: dict, *, roles=None,
                              maison: bool = True) -> str:
    """Ouvre un pari sur les kills. Rend ce que le modèle lira."""
    if not maison:
        return ("Refusé : les paris appartiennent au live d'Azraël, on ne les "
                "ouvre pas depuis une chaîne invitée. Dis-le simplement.")
    if not (set(roles or ()) & _ROLES_AUTORISES):
        return ("Refusé : cette personne n'est ni modérateur ni le streamer, "
                "elle ne peut pas engager les points des viewers. Moque-toi "
                "gentiment d'elle dans le chat, en une phrase.")

    suivi = getattr(bot, "prediction_kills", None)
    if suivi is None:
        # Repli : en temps normal l'objet est créé au démarrage (`main.py`) avec
        # sa base, justement pour qu'un pari laissé ouvert soit repris. Ce
        # chemin-là ne sert plus qu'aux tests et aux montages partiels — il
        # prend quand même la base, sans quoi le pari ouvert ici ne serait rangé
        # nulle part.
        suivi = PredictionKills(getattr(bot, "db", None))
        bot.prediction_kills = suivi

    out = await suivi.ouvrir(bot, str((args or {}).get("titre") or ""),
                             list((args or {}).get("choix") or []),
                             int((args or {}).get("secondes") or FENETRE_DEFAUT_S))
    if not out.get("ok"):
        return (f"Le pari n'est PAS ouvert : {out.get('raison')} "
                "Corrige et réessaie, ou explique-le à la personne.")
    return (f"Pari ouvert : « {out.get('titre')} ». Annonce-le au chat en une "
            "phrase, et dis que tu le résoudras toi-même à la fin de la partie.")
