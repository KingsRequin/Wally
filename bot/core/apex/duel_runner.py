# bot/core/apex/duel_runner.py
"""Ce qui entoure la machine à états : réseau, persistance, effets.

La logique du duel est dans `duel.py`, pure et testable sans rien brancher.
Ici on sonde, on range l'état, et on déclenche les annonces.
"""
from __future__ import annotations

import asyncio
import json
import time

from loguru import logger

from bot.core.apex.duel import (ATTENTE_SQUAD_S, PLAFOND_KILLS_MANCHE, Duel,
                                Etat, Evenement, Releve)
from bot.core.apex.reader import _num, read_kill_trackers

# Une clé de `bot_state`, comme `apex:live_baseline` — un seul duel à la fois,
# donc pas de table. L'état survit ainsi aux rebuilds, qui sont fréquents ici.
CLE_ETAT = "apex:duel"

# L'ID de la récompense que Wally a lui-même créée. Twitch réserve la mise à
# jour (donc le remboursement) d'une redemption à l'application qui a créé la
# récompense : cet ID est découvert à l'exécution, jamais configuré.
CLE_RECOMPENSE = "apex:duel_reward_id"

# Collée en dur dans le message, jamais laissée au LLM : un modèle qui
# reformule une adresse finit par la casser, et un lien mort rend le duel
# impossible à démarrer. Le ton est libre, l'adresse ne l'est pas.
URL_APEX_STATUS = "https://apexlegendsstatus.com"

# Étapes exactes et non devinables — fournies au prompt comme des FAITS.
ETAPES_UID = (
    "cherche ton pseudo sur le site, ouvre ton profil, et regarde l'URL : si "
    "elle ne contient pas de numéro, clique sur « Not the profile you are "
    "looking for? Try deep search », puis reclique sur ton compte — l'URL "
    "devient une adresse en profile/uid/… C'est ce numéro qu'il me faut."
)

# Au-delà, on rend les points : mieux vaut un remboursement qu'un viewer qui
# attend indéfiniment.
TENTATIVES_RESOLUTION = 3

# Les badges Twitch qui donnent la main sur un duel. La décision se prend ici,
# sur la donnée du message — jamais dans un prompt : un LLM à qui un viewer
# écrit « je suis modérateur » finira par le croire.
BADGES_CONTROLE = frozenset({"broadcaster", "moderator"})

# Attente entre deux vérifications quand aucun duel ne tourne. La boucle ne
# demande alors RIEN à l'API : la sonde du watcher suffit à entretenir
# l'historique, et un duel consomme déjà 1 req/s à lui seul (deux comptes
# toutes les 2 s).
REPOS_SANS_DUEL_S = 5.0

# Recul après une erreur : une sonde qui repart aussitôt sur une API en panne
# la martèle et remplit les logs.
RECUL_ERREUR_S = 10.0


def peut_controler(auteur: dict) -> bool:
    """Le streamer et ses modérateurs, et personne d'autre.

    `auteur` porte les badges du message RÉEL (`{"badges": [{"set_id": …}]}`),
    normalisés par l'appelant. Rien d'autre n'entre dans la décision : le texte
    du message n'y a aucune part.
    """
    badges = (auteur or {}).get("badges") or []
    if not isinstance(badges, list):
        return False
    return any(isinstance(b, dict) and b.get("set_id") in BADGES_CONTROLE
               for b in badges)


def _uid_valide(saisie: str) -> str | None:
    """Un uid Apex est purement numérique. Validé AVANT tout appel réseau :
    la saisie vient d'un viewer, c'est de l'entrée non fiable."""
    nettoye = (saisie or "").strip()
    return nettoye if nettoye.isdigit() else None


# Même patron que `bot/core/apex/watcher.py` (`_active`/`current_apex_block()`)
# et `bot/core/stream_feed.py` (`_active`/`current_stream_feed_block()`) : le
# runner s'enregistre comme source globale (`activate()`), lisible par
# `prompts.py` et l'`AttentionAgent` sans injection de dépendance. Le runner
# lui-même n'est construit qu'au câblage final (Task 10) — d'ici là,
# `current_duel()` rend toujours None.
_active: DuelRunner | None = None


def current_duel() -> Duel | None:
    """Le duel en cours, si le runner est actif. None sinon."""
    return _active.duel_en_cours if _active is not None else None


class DuelRunner:
    def __init__(self, client, db, api, annoncer, *,
                 azrael_uid: str, plateforme: str = "PC", cadence_s: float = 2.0,
                 manches: int = 3, attente_squad_s: float = ATTENTE_SQUAD_S,
                 plafond_kills_manche: int = PLAFOND_KILLS_MANCHE):
        self._client = client
        self._db = db
        self._api = api
        # `feed` a disparu de cette signature au câblage : il n'était jamais lu.
        # Tout ce qui sort du duel — chat, overlay — passe par `annoncer`, la
        # seule sortie que le runner connaisse.
        self._annoncer = annoncer          # coroutine(evenement) -> None
        self._azrael_uid = azrael_uid
        self._plateforme = plateforme
        self._cadence_s = cadence_s
        # Les réglages du duel voyagent jusqu'au `Duel`, qui les porte en
        # CHAMPS et non en constantes. Sans ce passage, `manches`,
        # `attente_squad_min` et `plafond_kills_manche` restaient décoratifs
        # dans `config.yaml` : on les éditait sans effet.
        self._manches = manches
        self._attente_squad_s = attente_squad_s
        self._plafond_kills_manche = plafond_kills_manche
        self.duel_en_cours: Duel | None = None
        self._reward_id = ""
        # Compteur d'essais en phase RESOLUTION — remis à zéro à chaque
        # ouverture d'une nouvelle attente d'uid, jamais partagé entre deux
        # viewers successifs.
        self._tentatives = 0
        # Dernier JSON écrit en base — `_ranger()` évite de réécrire un état
        # inchangé : sonde à 2 s pendant potentiellement une demi-heure de
        # duel, et la plupart des tours ne changent rien (partie toujours en
        # cours, aucun événement rendu par `avancer()`).
        self._dernier_etat_range: str | None = None

    @property
    def cadence_s(self) -> float:
        """L'intervalle entre deux relevés pendant un duel, en secondes.

        Lisible par la boucle de sonde sans qu'elle aille chercher un attribut
        privé — c'est le seul réglage qu'elle a besoin de connaître.
        """
        return self._cadence_s

    def _nouveau_duel(self, **champs) -> Duel:
        """Un `Duel` neuf, réglé par la configuration du runner."""
        return Duel(azrael_uid=self._azrael_uid, manches=self._manches,
                    attente_squad_s=self._attente_squad_s,
                    plafond_kills_manche=self._plafond_kills_manche, **champs)

    def activate(self) -> None:
        """S'enregistre comme source globale, lisible par `prompts.py` /
        l'`AttentionAgent` — cf. `current_duel()`."""
        global _active
        _active = self

    # -- Annonce --------------------------------------------------------------
    async def _annoncer_sur(self, evt: Evenement) -> None:
        """Une annonce ratée (LLM, envoi Twitch…) ne doit JAMAIS empêcher la
        suite : à chaque appel, le remboursement et la persistance sont déjà
        faits avant qu'elle soit seulement tentée."""
        try:
            await self._annoncer(evt)
        except Exception as exc:  # noqa: BLE001 — une annonce ratée n'est pas fatale
            logger.warning("Annonce de duel en erreur ({t}) : {e}", t=evt.type, e=exc)

    # -- Récompense -----------------------------------------------------------
    async def assurer_recompense(self, titre: str, cout: int, prompt: str) -> str:
        """L'ID de notre récompense, créée si besoin. `""` si impossible.

        Appelée au boot. Si un ID est déjà connu, on vérifie qu'il figure
        toujours parmi les récompenses GÉRABLES — celles créées par notre
        client_id. Une récompense supprimée par le streamer, ou créée à la
        main dans la console, ne l'est pas : on en crée alors une neuve, faute
        de quoi les remboursements échoueraient en 403.

        Si la vérification elle-même échoue (`recompenses_gerables()` rend
        `None`, panne Twitch), on ne recrée JAMAIS sur ce doute : ce serait
        perdre l'ID connu, écraser la clé persistée, et rendre irremboursable
        (403) toute redemption en vol sur l'ancienne récompense.
        """
        connu = await self._db.get_state(CLE_RECOMPENSE)
        if connu:
            gerables = await self._api.recompenses_gerables()
            if gerables is None:
                logger.warning(
                    "Liste des récompenses gérables indisponible — on garde l'ID connu {i}",
                    i=connu)
                self._reward_id = connu
                return connu
            if connu in {r.get("id") for r in gerables}:
                self._reward_id = connu
                return connu
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
            brut = ""
        else:
            etat = self.duel_en_cours.to_dict()
            # `_reward_id` voyage AVEC le duel : sans lui, un remboursement
            # après rebuild dépend de la chance qu'`assurer_recompense()`
            # retombe sur le même ID au redémarrage — sinon
            # `refund_redemption("", …)` échoue.
            etat["reward_id"] = self._reward_id
            brut = json.dumps(etat)
        if brut == self._dernier_etat_range:
            return
        await self._db.set_state(CLE_ETAT, brut)
        self._dernier_etat_range = brut

    async def charger(self) -> None:
        """Reprend un duel interrompu par un rebuild."""
        try:
            brut = await self._db.get_state(CLE_ETAT)
            if not brut:
                return
            data = json.loads(brut)
            self.duel_en_cours = Duel.from_dict(data)
            self._reward_id = str(data.get("reward_id") or "")
            # Base de comparaison pour la déduplication de `_ranger()` : sans
            # elle, le premier tick après reprise réécrirait un JSON identique.
            self._dernier_etat_range = brut
            logger.info("Duel Apex repris après redémarrage : {v} en état {e}",
                        v=self.duel_en_cours.viewer_nom, e=self.duel_en_cours.etat.value)
        except Exception as exc:  # noqa: BLE001 — un état illisible ne bloque pas le boot
            logger.warning("État de duel illisible, ignoré : {e}", e=exc)
            self.duel_en_cours = None

    # -- Ouverture ----------------------------------------------------------
    async def _refuser(self, reward_id: str, redemption_id: str, motif: str) -> None:
        """Un refus se rembourse ET s'annonce — dans cet ordre.

        Le remboursement d'abord : si l'annonce lève (appel LLM, envoi
        Twitch…), le viewer doit avoir récupéré ses points malgré tout. C'est
        déjà la règle suivie par `annuler()` ; elle doit valoir partout.
        """
        logger.info("Duel refusé : {m}", m=motif)
        await self._api.refund_redemption(reward_id, redemption_id)
        await self._annoncer_sur(Evenement("refus", {"motif": motif}))

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
            # Pas de remboursement au premier essai : la recherche par pseudo
            # de l'API rate des comptes bien réels, ce serait punir le viewer
            # pour un défaut qui n'est pas le sien.
            await self._demander_uid(acheteur, reward_id, redemption_id)
            return
        if uid == self._azrael_uid:
            await self._refuser(reward_id, redemption_id,
                                "un duel contre soi-même n'a pas de vainqueur")
            return

        profil = await self._profil(uid)
        if profil is None or not read_kill_trackers(profil):
            await self._refuser(
                reward_id, redemption_id,
                "aucun tracker de kills n'est épinglé sur ce compte")
            return

        self._reward_id = reward_id
        self.duel_en_cours = self._nouveau_duel(
            viewer_nom=acheteur, viewer_uid=uid,
            redemption_id=redemption_id, etat=Etat.ATTENTE_SQUAD)
        await self._ranger()
        await self._annoncer_sur(Evenement("duel_ouvert", {"viewer": acheteur}))

    async def _demander_uid(self, acheteur: str, reward_id: str,
                            redemption_id: str) -> None:
        """Explique comment trouver son uid, et garde le duel en attente.

        Pas de remboursement ici : c'est le point même de cette étape (§9 de
        la spec) — le viewer garde ses points dépensés pendant qu'on lui
        laisse une vraie chance de répondre correctement.
        """
        self._reward_id = reward_id
        self._tentatives = 0
        self.duel_en_cours = self._nouveau_duel(
            viewer_nom=acheteur, viewer_uid="",
            redemption_id=redemption_id, etat=Etat.RESOLUTION)
        await self._ranger()
        await self._annoncer_sur(Evenement("compte_introuvable", {
            "viewer": acheteur, "url": URL_APEX_STATUS, "etapes": ETAPES_UID,
        }))

    async def repondre_resolution(self, auteur: str, texte: str) -> bool:
        """Une réponse du duelliste pendant la phase de résolution.

        Rend `True` si le message a été consommé par le duel — l'appelant
        sait alors qu'il n'a pas à le traiter comme un message ordinaire
        (donc ni cooldown, ni appel LLM dessus).
        """
        duel = self.duel_en_cours
        if duel is None or duel.etat is not Etat.RESOLUTION:
            return False
        if auteur.lower() != duel.viewer_nom.lower():
            return False

        uid = _uid_valide(texte)
        if uid is not None and uid != self._azrael_uid:
            profil = await self._profil(uid)
            if profil is not None and read_kill_trackers(profil):
                duel.viewer_uid = uid
                duel.etat = Etat.ATTENTE_SQUAD
                await self._ranger()
                await self._annoncer_sur(Evenement("duel_ouvert", {"viewer": duel.viewer_nom}))
                return True

        self._tentatives += 1
        if self._tentatives >= TENTATIVES_RESOLUTION:
            # Rembourser D'ABORD, nettoyer et persister ENSUITE, annoncer
            # SEULEMENT après — même ordre que `_avancer()` : une annonce qui
            # lève ne doit jamais laisser un remboursement en suspens ni un
            # duel fantôme derrière elle.
            await self._api.refund_redemption(self._reward_id, duel.redemption_id)
            self.duel_en_cours = None
            await self._ranger()
            await self._annoncer_sur(Evenement("abandon", {
                "rembourser": True,
                "motif": "impossible de retrouver ce compte Apex"}))
            return True

        await self._annoncer_sur(Evenement("compte_introuvable", {
            "viewer": duel.viewer_nom, "url": URL_APEX_STATUS, "etapes": ETAPES_UID}))
        return True

    # -- Sonde --------------------------------------------------------------
    async def _profil(self, uid: str) -> dict | None:
        """Le profil, ou `None` si la sonde n'a rien donné d'exploitable.

        Deux formes d'échec à écarter, pas une seule : `client.get` peut
        rendre une CHAÎNE d'erreur (panne réseau, cf. `ApexClient.get`), mais
        peut aussi rendre un dict `{"Error": "Player not found."}` avec un
        200 tout à fait normal — piège documenté du projet (`reader.py`,
        `service.py`). Un `_profil()` qui acceptait ce second cas comme un
        relevé valide donnait `isInGame` absent → `False`, et deux relevés
        d'erreur consécutifs suffisaient à faire croire à un retour au lobby
        en pleine manche réelle.
        """
        p = await self._client.get(
            "bridge", {"uid": uid, "platform": self._plateforme}, sans_cache=True)
        if not isinstance(p, dict) or "Error" in p:
            return None
        return p

    async def _avancer(self, duel: Duel, releve: Releve) -> None:
        """Fait avancer la machine d'un relevé, et applique les effets.

        Ordre STRICT : remboursement(s) → nettoyage de `duel_en_cours` →
        persistance → annonces. Si l'annonce d'un abandon levait AVANT le
        remboursement et le nettoyage, l'exception sortirait avec les points
        du viewer non rendus, `duel_en_cours` toujours peuplé (donc tous les
        viewers suivants refusés indéfiniment) et l'état persisté périmé — un
        rebuild ressusciterait ce duel fantôme via `charger()`.
        """
        evts = duel.avancer(releve)
        for evt in evts:
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
        for evt in evts:
            await self._annoncer_sur(evt)

    async def tick(self, maintenant: float) -> None:
        """Un tour de sonde. Appelé toutes les `cadence_s` pendant un duel.

        `maintenant` DOIT venir d'une horloge MURALE (`time.time()`), jamais
        monotone : cet instant est persisté dans l'état du duel
        (`Duel._t_attente`, via `to_dict()`/`from_dict()`) et doit rester
        comparable après un redémarrage — une horloge monotone y repart de
        zéro, ce qui rendrait la comparaison absurde. Piège déjà payé sur ce
        projet (bug_monotonic_uptime).
        """
        duel = self.duel_en_cours
        if duel is None or duel.etat in (Etat.RESOLUTION, Etat.VERDICT, Etat.ABANDON):
            return
        azrael = await self._profil(duel.azrael_uid)
        viewer = await self._profil(duel.viewer_uid)
        if azrael is None or viewer is None:
            # L'API muette ou en erreur est tolérée : la machine à états ne
            # voit simplement rien passer CE tour-ci. Mais le minuteur
            # d'attente doit continuer d'avancer pendant ATTENTE_SQUAD et
            # ENTRE_MANCHES — sinon une panne prolongée gèlerait le duel pour
            # toujours (jamais de timeout, jamais de remboursement, et le
            # viewer suivant resterait refusé indéfiniment). On s'en abstient
            # en MANCHE : y injecter un relevé fictif "hors partie" risquerait
            # de clore une manche réellement en cours via le debounce de fin
            # de partie, sur un simple hoquet de l'API.
            logger.debug("Duel : relevé incomplet, tour sauté")
            if duel.etat in (Etat.ATTENTE_SQUAD, Etat.ENTRE_MANCHES):
                await self._avancer(duel, Releve(
                    t=maintenant, azrael_in_game=False, viewer_in_game=False,
                    kills_azrael={}, kills_viewer={}))
            return

        releve = Releve(
            t=maintenant,
            # `_num` et non `bool()` nu : cette API glisse des chaînes là où
            # on attend un nombre, et `bool("0")` vaut `True` — ça ferait
            # démarrer des manches qui n'ont jamais eu lieu. Même garde que
            # `reader.py` sur le même piège.
            azrael_in_game=bool(_num((azrael.get("realtime") or {}).get("isInGame"))),
            viewer_in_game=bool(_num((viewer.get("realtime") or {}).get("isInGame"))),
            kills_azrael=read_kill_trackers(azrael),
            kills_viewer=read_kill_trackers(viewer),
        )
        await self._avancer(duel, releve)

    # -- Contrôle (streamer et modérateurs) ---------------------------------
    async def annuler(self, motif: str) -> None:
        duel = self.duel_en_cours
        if duel is None:
            return
        await self._api.refund_redemption(self._reward_id, duel.redemption_id)
        self.duel_en_cours = None
        await self._ranger()
        await self._annoncer_sur(Evenement("abandon", {"motif": motif, "rembourser": True}))

    async def recommencer(self) -> None:
        """Compteurs à zéro, même duelliste — pas de remboursement, il garde sa place."""
        if self.duel_en_cours is None:
            return
        self.duel_en_cours.recommencer()
        await self._ranger()
        await self._annoncer_sur(Evenement("recommence", {
            "viewer": self.duel_en_cours.viewer_nom}))


async def armer_le_duel(runner: DuelRunner, *, titre: str, cout: int,
                        prompt: str) -> str:
    """Le démarrage du duel, dans l'ORDRE — rend l'ID de la récompense.

    Cet ordre n'est pas un détail de style :

      1. `charger()` d'abord. Il écrase `_reward_id` avec ce qu'il trouve dans
         l'état persisté, y compris une valeur vide : appelé en second, il
         effacerait l'identifiant tout juste obtenu et chaque remboursement
         échouerait — un viewer qui perd ses points sans recours.
      2. `assurer_recompense()` ensuite, qui recolle un identifiant valide.
      3. `activate()` enfin : sans lui `current_duel()` rend toujours None, et
         Wally arbitre un duel dont il est incapable de parler.

    Rassemblé ici, et non déroulé dans `main.py`, pour que cet ordre soit
    JOUABLE en test — c'est le seul endroit où il se vérifie.
    """
    await runner.charger()
    reward_id = await runner.assurer_recompense(titre, cout, prompt)
    runner.activate()
    return reward_id


async def boucle_sonde(runner: DuelRunner | None, *, sleep=asyncio.sleep) -> None:
    """Sonde le duel en cours, et RIEN quand il n'y en a pas.

    Hors duel, aucune requête ne part : l'`ApexWatcher` entretient déjà
    l'historique du streamer, et un duel coûte à lui seul 1 requête/seconde
    (deux comptes toutes les 2 s, soit 20 % du débit autorisé).

    `time.time()` et jamais `time.monotonic()` : l'instant transmis est persisté
    dans l'état du duel et doit rester comparable après un redémarrage — une
    horloge monotone y repart de zéro (piège déjà payé ici,
    `bug_monotonic_uptime`).

    Vit tant que le bot vit : elle attrape, journalise et repart. Une boucle de
    fond qui meurt en silence laisse le duel figé sans que rien ne le signale.
    """
    if runner is None:
        return          # Apex indisponible au boot : pas de duel, pas de sonde
    while True:
        try:
            if runner.duel_en_cours is None:
                await sleep(REPOS_SANS_DUEL_S)
                continue
            await runner.tick(time.time())
            await sleep(runner.cadence_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — la sonde ne meurt jamais en silence
            logger.error("Boucle de duel en erreur : {e}", e=exc)
            await sleep(RECUL_ERREUR_S)
