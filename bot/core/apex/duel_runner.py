# bot/core/apex/duel_runner.py
"""Ce qui entoure la machine à états : réseau, persistance, effets.

La logique du duel est dans `duel.py`, pure et testable sans rien brancher.
Ici on sonde, on range l'état, et on déclenche les annonces.
"""
from __future__ import annotations

import json

from loguru import logger

from bot.core.apex.duel import Duel, Etat, Evenement, Releve
from bot.core.apex.reader import read_kill_trackers

# Une clé de `bot_state`, comme `apex:live_baseline` — un seul duel à la fois,
# donc pas de table. L'état survit ainsi aux rebuilds, qui sont fréquents ici.
CLE_ETAT = "apex:duel"

# L'ID de la récompense que Wally a lui-même créée. Twitch réserve la mise à
# jour (donc le remboursement) d'une redemption à l'application qui a créé la
# récompense : cet ID est découvert à l'exécution, jamais configuré.
CLE_RECOMPENSE = "apex:duel_reward_id"


def _uid_valide(saisie: str) -> str | None:
    """Un uid Apex est purement numérique. Validé AVANT tout appel réseau :
    la saisie vient d'un viewer, c'est de l'entrée non fiable."""
    nettoye = (saisie or "").strip()
    return nettoye if nettoye.isdigit() else None


class DuelRunner:
    def __init__(self, client, db, api, feed, annoncer, *,
                 azrael_uid: str, plateforme: str = "PC", cadence_s: float = 2.0):
        self._client = client
        self._db = db
        self._api = api
        self._feed = feed
        self._annoncer = annoncer          # coroutine(evenement) -> None
        self._azrael_uid = azrael_uid
        self._plateforme = plateforme
        self._cadence_s = cadence_s
        self.duel_en_cours: Duel | None = None
        self._reward_id = ""

    # -- Récompense -----------------------------------------------------------
    async def assurer_recompense(self, titre: str, cout: int, prompt: str) -> str:
        """L'ID de notre récompense, créée si besoin. `""` si impossible.

        Appelée au boot. On vérifie que l'ID retenu figure toujours parmi les
        récompenses GÉRABLES — celles créées par notre client_id. Une récompense
        supprimée par le streamer, ou créée à la main dans la console, ne l'est
        pas : dans les deux cas on en crée une neuve, faute de quoi les
        remboursements échoueraient en 403.
        """
        connu = await self._db.get_state(CLE_RECOMPENSE)
        gerables = {r.get("id") for r in await self._api.recompenses_gerables()}
        if connu and connu in gerables:
            self._reward_id = connu
            return connu
        if connu:
            logger.warning("Récompense de duel {i} introuvable côté Twitch — on recrée", i=connu)
        nouvel_id = await self._api.creer_recompense(titre, cout, prompt)
        if not nouvel_id:
            logger.error("Récompense de duel impossible à créer — duel indisponible")
            return ""
        await self._db.set_state(CLE_RECOMPENSE, nouvel_id)
        self._reward_id = nouvel_id
        return nouvel_id

    # -- Persistance --------------------------------------------------------
    async def _ranger(self) -> None:
        if self.duel_en_cours is None:
            await self._db.set_state(CLE_ETAT, "")
            return
        await self._db.set_state(CLE_ETAT, json.dumps(self.duel_en_cours.to_dict()))

    async def charger(self) -> None:
        """Reprend un duel interrompu par un rebuild."""
        try:
            brut = await self._db.get_state(CLE_ETAT)
            if not brut:
                return
            self.duel_en_cours = Duel.from_dict(json.loads(brut))
            logger.info("Duel Apex repris après redémarrage : {v} en état {e}",
                        v=self.duel_en_cours.viewer_nom, e=self.duel_en_cours.etat.value)
        except Exception as exc:  # noqa: BLE001 — un état illisible ne bloque pas le boot
            logger.warning("État de duel illisible, ignoré : {e}", e=exc)
            self.duel_en_cours = None

    # -- Ouverture ----------------------------------------------------------
    async def _refuser(self, reward_id: str, redemption_id: str, motif: str) -> None:
        """Un refus s'annonce ET se rembourse. Jamais un silence."""
        logger.info("Duel refusé : {m}", m=motif)
        await self._annoncer(Evenement("refus", {"motif": motif}))
        await self._api.refund_redemption(reward_id, redemption_id)

    async def ouvrir(self, *, acheteur: str, saisie: str,
                     reward_id: str, redemption_id: str) -> None:
        if self.duel_en_cours is not None:
            # Un duel tourne déjà : le remboursement seul laissait le viewer
            # sans un mot d'explication (Task 7, faute de canal d'annonce).
            # Ne JAMAIS écraser le duel en cours au passage.
            await self._refuser(reward_id, redemption_id, "un duel est déjà en cours")
            return

        uid = _uid_valide(saisie)
        if uid is None:
            await self._refuser(reward_id, redemption_id,
                                "l'identifiant fourni n'est pas un uid Apex")
            return
        if uid == self._azrael_uid:
            await self._refuser(reward_id, redemption_id,
                                "un duel contre soi-même n'a pas de vainqueur")
            return

        profil = await self._client.get(
            "bridge", {"uid": uid, "platform": self._plateforme}, sans_cache=True)
        if not isinstance(profil, dict) or not read_kill_trackers(profil):
            await self._refuser(
                reward_id, redemption_id,
                "aucun tracker de kills n'est épinglé sur ce compte")
            return

        self._reward_id = reward_id
        self.duel_en_cours = Duel(
            viewer_nom=acheteur, viewer_uid=uid, azrael_uid=self._azrael_uid,
            redemption_id=redemption_id, etat=Etat.ATTENTE_SQUAD)
        await self._ranger()
        await self._annoncer(Evenement("duel_ouvert", {"viewer": acheteur}))

    # -- Sonde --------------------------------------------------------------
    async def _profil(self, uid: str) -> dict | None:
        p = await self._client.get(
            "bridge", {"uid": uid, "platform": self._plateforme}, sans_cache=True)
        return p if isinstance(p, dict) else None

    async def tick(self, maintenant: float) -> None:
        """Un tour de sonde. Appelé toutes les `cadence_s` pendant un duel."""
        duel = self.duel_en_cours
        if duel is None or duel.etat in (Etat.RESOLUTION, Etat.VERDICT, Etat.ABANDON):
            return
        azrael = await self._profil(duel.azrael_uid)
        viewer = await self._profil(duel.viewer_uid)
        if azrael is None or viewer is None:
            # L'API muette quelques relevés est tolérée : la machine à états ne
            # voit simplement rien passer.
            logger.debug("Duel : relevé incomplet, tour sauté")
            return

        releve = Releve(
            t=maintenant,
            azrael_in_game=bool((azrael.get("realtime") or {}).get("isInGame")),
            viewer_in_game=bool((viewer.get("realtime") or {}).get("isInGame")),
            kills_azrael=read_kill_trackers(azrael),
            kills_viewer=read_kill_trackers(viewer),
        )
        for evt in duel.avancer(releve):
            await self._annoncer(evt)
            if evt.type == "abandon":
                # `manches_jouees` n'existe que sur les abandons issus
                # d'ENTRE_MANCHES — jamais un accès direct.
                logger.info(
                    "Duel Apex : abandon — {m} (manches jouées : {n})",
                    m=evt.donnees.get("motif"), n=evt.donnees.get("manches_jouees", 0))
                if evt.donnees.get("rembourser"):
                    await self._api.refund_redemption(self._reward_id, duel.redemption_id)
        # Terminal = VERDICT ou ABANDON : après un abandon survenu alors qu'au
        # moins une manche a été mesurée, l'état final est VERDICT et non
        # ABANDON (le duel tranche sur les manches jouées). Nettoyer sur « le
        # duel est terminal » et non sur un état précis évite de rater ce cas.
        if duel.etat in (Etat.VERDICT, Etat.ABANDON):
            self.duel_en_cours = None
        await self._ranger()

    # -- Contrôle (streamer et modérateurs) ---------------------------------
    async def annuler(self, motif: str) -> None:
        duel = self.duel_en_cours
        if duel is None:
            return
        await self._api.refund_redemption(self._reward_id, duel.redemption_id)
        await self._annoncer(Evenement("abandon", {"motif": motif, "rembourser": True}))
        self.duel_en_cours = None
        await self._ranger()

    async def recommencer(self) -> None:
        """Compteurs à zéro, même duelliste — pas de remboursement, il garde sa place."""
        if self.duel_en_cours is None:
            return
        self.duel_en_cours.recommencer()
        await self._annoncer(Evenement("recommence", {
            "viewer": self.duel_en_cours.viewer_nom}))
        await self._ranger()
