# bot/core/apex/duel_runner.py
"""Ce qui entoure la machine à états : réseau, persistance, effets.

La logique du duel est dans `duel.py`, pure et testable sans rien brancher.
Ici on sonde, on range l'état, et on déclenche les annonces.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import replace

from loguru import logger

from bot.core.apex.duel import (ATTENTE_SQUAD_S, MARGE_LOBBY_S,
                                PLAFOND_KILLS_MANCHE, Duel, Etat, Evenement,
                                Releve)
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

# Le compte du streamer, quelle que soit la façon dont on l'a désigné.
MOTIF_SOI_MEME = "un duel contre soi-même n'a pas de vainqueur"

# Pourquoi une saisie n'a pas donné de compte jouable. Les quatre étaient
# confondues : une saisie numérique qui ne résolvait pas s'entendait répondre
# « aucun tracker de kills n'est épinglé sur ce compte », alors que la cause
# pouvait être un identifiant erroné, un compte d'une autre plateforme, ou un
# simple hoquet de l'API. Le viewer se voyait affirmer devant le stream une
# chose fausse sur son propre compte.
CAUSE_INTROUVABLE = "introuvable"       # l'API a répondu : ce compte n'existe pas
CAUSE_API = "api"                       # l'API n'a pas répondu, ou pas lisiblement
CAUSE_SANS_TRACKER = "sans_tracker"     # compte trouvé, mais aucun tracker de kills
CAUSE_SOI_MEME = "soi_meme"             # c'est le compte d'Azraël

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

# Une manche ne peut se clore que sur un relevé : tant que l'API est muette,
# rien n'avance. Quelques relevés ratés sont tolérés — c'est une API publique —
# mais au-delà de ce délai le duel n'a plus AUCUN moyen de se terminer. Sans
# ce plafond, une panne prolongée (ou un profil devenu illisible) gèle le duel
# pour toujours : pas de timeout, pas de remboursement, et `duel_en_cours`
# reste peuplé donc tout acheteur suivant est refusé « un duel est déjà en
# cours ». La seule issue serait qu'un modérateur pense à dire « annule ».
API_MUETTE_MAX_S = 180.0

# Le stream doit être vu éteint pendant ce temps AVANT de solder le duel. La
# sonde du `StreamWatcher` tourne à 60 s : deux relevés concordants, donc, sur
# le patron du debounce d'entrée/sortie de manche. Un `/helix/streams` qui rend
# une liste vide sur une chaîne pourtant allumée existe, et abandonner un duel
# là-dessus coûterait au duelliste une partie qu'il est en train de jouer.
STREAM_COUPE_MAX_S = 120.0

# Contrainte DURE, et pas un réglage de confort : 39 s est l'intervalle mesuré
# le 2026-08-13 entre un retour au lobby et le lancement de la partie suivante.
# Tout ce qui s'écoule entre le retour au lobby et l'instant où le score est
# figé doit tenir là-dedans, sans quoi une manche mord sur la suivante et son
# score compte les kills de deux parties.
PLAFOND_MARGE_LOBBY_S = 39.0


def marge_lobby_bornee(marge: float, cadence_s: float) -> float:
    """La marge de lobby réellement applicable, plafond dur compris.

    Le budget n'est pas la marge seule : le debounce anti-hoquet consomme DEUX
    relevés avant qu'elle ne démarre, donc `2 × cadence + marge` doit rester
    sous les 39 s mesurées. C'est le seul endroit où les deux temporisations se
    rencontrent — les empiler sans compter leur somme reviendrait à les laisser
    se marcher dessus.

    Une valeur qui déborde n'est pas refusée en silence : elle est bornée, et
    dite en log. Un duel qui refuserait de démarrer parce qu'un délai est mal
    réglé serait pire que le délai mal réglé.
    """
    budget = PLAFOND_MARGE_LOBBY_S - 2 * max(0.0, cadence_s)
    if budget <= 0:
        logger.error(
            "Duel Apex : la cadence de sonde ({c:.0f} s) mange à elle seule les "
            "{p:.0f} s entre un retour au lobby et la partie suivante — marge de "
            "lobby ramenée à 0", c=cadence_s, p=PLAFOND_MARGE_LOBBY_S)
        return 0.0
    if marge < 0:
        logger.error("Duel Apex : marge de lobby négative ({m}) — ramenée à 0", m=marge)
        return 0.0
    if marge > budget:
        logger.error(
            "Duel Apex : marge de lobby de {m:.0f} s trop proche du plafond dur "
            "de {p:.0f} s (le debounce consomme déjà 2 × {c:.0f} s) — bornée à "
            "{b:.0f} s, sinon une manche mordrait sur la suivante",
            m=marge, p=PLAFOND_MARGE_LOBBY_S, c=cadence_s, b=budget)
        return budget
    return marge


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


def _id_twitch(valeur) -> str:
    """L'identifiant Twitch BRUT, ou `""` si ce n'en est pas un.

    Un id Twitch est purement numérique. Le filtrer ici évite d'écrire en
    mémoire sous une clé fantaisiste : le namespace `twitch:` est indexé par
    id, et une clé inventée fabrique un utilisateur qui n'existe pas — que
    personne ne retrouvera jamais et que rien ne nettoiera.

    Jamais préfixé (`twitch:…`) : `memory.add()` construit `platform:user_id`
    lui-même, et lui passer la forme préfixée donne `twitch:twitch:…`.
    """
    brut = str(valeur or "").strip()
    return brut if brut.isdigit() else ""


def _tranche_les_points(evts: list[Evenement]) -> Evenement | None:
    """L'événement qui SOLDE les points de la redemption — un seul par salve.

    Une salve peut en porter deux : quand le duelliste ne revient pas après une
    manche mesurée, `avancer()` rend un `abandon` PUIS un `verdict`. C'est
    l'ABANDON qui tranche, et c'est un arbitrage du propriétaire : depuis que
    le vainqueur récupère ses points, laisser le verdict trancher ferait de
    « mener 5-2 après la manche 1 puis quitter » la stratégie optimale — on
    empocherait le verdict partiel ET le remboursement, sans jouer la suite.
    Le verdict reste rendu et annoncé ; seul le sort des points lui échappe.

    Solder deux fois enverrait à Twitch deux ordres contradictoires sur la même
    redemption, et le second serait perdu : une redemption `FULFILLED` ne
    redevient jamais `CANCELED`.
    """
    for type_evt in ("abandon", "verdict"):
        for evt in evts:
            if evt.type == type_evt:
                return evt
    return None


def _trace_de_fin(evts: list[Evenement]) -> Evenement | None:
    """L'événement qui raconte la FIN du duel — un seul par salve.

    Le VERDICT d'abord quand il y en a un : il porte les chiffres et le drapeau
    `abandon`, donc il sait dire « interrompu » aussi bien que l'abandon qui le
    précède. Sinon l'abandon, qui n'a pas de vainqueur à raconter.

    L'ordre est l'inverse de `_tranche_les_points()`, et c'est voulu : là-bas
    c'est l'anti-abandon qui doit primer sur les points ; ici c'est le récit le
    plus complet qui doit primer, et il ne s'agit plus d'argent.
    """
    for type_evt in ("verdict", "abandon"):
        for evt in evts:
            if evt.type == type_evt:
                return evt
    return None


def _echec_de_remboursement(evt: Evenement) -> Evenement:
    """Le même événement, mais qui dit que les points ne sont PAS revenus.

    `refund_redemption()` vérifie déjà le CORPS de la réponse Helix et rend un
    booléen — personne ne le lisait. Un remboursement refusé (403, scope perdu,
    redemption déjà soldée) faisait donc annoncer « tes points t'ont été
    rendus » à un viewer qui ne les reverra jamais, avec pour seule trace une
    ligne de log que personne ne lit en direct.

    L'événement voyage jusqu'à l'annonceur : c'est lui, et lui seul, qui parle
    aux spectateurs.
    """
    return replace(evt, donnees={**(evt.donnees or {}),
                                 "remboursement_echoue": True})


def _camp(profil: dict) -> dict:
    """La légende jouée et le niveau du compte, lus dans le profil déjà sondé.

    Ces deux valeurs vont sous le nom de chaque joueur à l'écran (« Fuse ·
    niv. 285 »). Elles voyagent donc par le même chemin que les kills — relevé,
    machine à états, événement — plutôt que par une requête de plus : elles
    sont dans le MÊME payload.

    Une clé absente est OMISE, jamais rendue en zéro : le sous-titre s'écourte
    alors tout seul, et un « niv. 0 » serait une affirmation fausse.
    """
    if not isinstance(profil, dict):
        return {}
    legende = str((profil.get("realtime") or {}).get("selectedLegend") or "").strip()
    niveau = int(_num((profil.get("global") or {}).get("level")) or 0)
    camp: dict = {}
    if legende:
        camp["legende"] = legende
    if niveau > 0:
        camp["niveau"] = niveau
    return camp


def _uid_valide(saisie: str) -> str | None:
    """Un uid Apex est purement numérique. Validé AVANT tout appel réseau :
    la saisie vient d'un viewer, c'est de l'entrée non fiable."""
    nettoye = (saisie or "").strip()
    return nettoye if nettoye.isdigit() else None


# Un pseudo Apex plausible : lettres (accents compris), chiffres, et les
# quelques signes que les identifiants EA tolèrent. Tout le reste — ponctuation
# de requête, guillemets, caractères de contrôle — est écarté SANS appel réseau :
# la saisie vient d'un viewer, et rien ne justifie d'envoyer « '; DROP TABLE-- »
# à une API tierce. Le pseudo retenu part ensuite en PARAMÈTRE de requête
# (`params=`, échappé par httpx), jamais concaténé dans une URL.
_PSEUDO_APEX = re.compile(r"[\w .\-\[\]|]{3,32}", re.UNICODE)


def _pseudo_valide(saisie: str) -> str | None:
    """Un pseudo Apex exploitable, ou None. Validé AVANT tout appel réseau.

    Les espaces multiples sont réduits et les bords rognés : un viewer colle
    souvent son pseudo avec un retour à la ligne. Ce qui ne ressemble pas à un
    pseudo tombe sur le repli « voici comment trouver ton UID » (§9 de la
    spec) — jamais sur un refus, la recherche par pseudo de cette API ratant
    par ailleurs des comptes parfaitement réels.
    """
    nettoye = " ".join((saisie or "").split())
    return nettoye if _PSEUDO_APEX.fullmatch(nettoye) else None


def _uid_du_profil(profil: dict) -> str:
    """L'identifiant Apex porté par un profil `/bridge`, `""` s'il n'y en a pas.

    Sans lui, un compte résolu par pseudo n'aurait aucun identifiant à sonder
    ensuite — et surtout, la comparaison avec le compte du streamer se ferait
    sur un pseudo, qui s'écrit de dix façons.
    """
    if not isinstance(profil, dict):
        return ""
    return str((profil.get("global") or {}).get("uid") or "").strip()


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
    def __init__(self, client, db, api, annoncer, *, memory=None,
                 azrael_uid: str, plateforme: str = "PC", cadence_s: float = 2.0,
                 manches: int = 3, attente_squad_s: float = ATTENTE_SQUAD_S,
                 plafond_kills_manche: int = PLAFOND_KILLS_MANCHE,
                 marge_lobby_s: float = MARGE_LOBBY_S,
                 api_muette_max_s: float = API_MUETTE_MAX_S,
                 stream_en_ligne: Callable[[], bool | None] | None = None,
                 stream_coupe_max_s: float = STREAM_COUPE_MAX_S):
        self._client = client
        self._db = db
        self._api = api
        # `feed` a disparu de cette signature au câblage : il n'était jamais lu.
        # Tout ce qui sort du duel — chat, overlay — passe par `annoncer`, la
        # seule sortie que le runner connaisse.
        self._annoncer = annoncer          # coroutine(evenement) -> None
        # `MemoryService`, pour la trace de fin de duel (§11 ter). Facultatif :
        # un duel doit pouvoir se jouer sans mémoire branchée, jamais échouer
        # parce qu'elle manque.
        self._memory = memory
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
        # Bornée ICI, une fois, à la construction : la valeur qui atteint la
        # machine à états est déjà jouable, et l'état persisté la porte telle
        # quelle. La borne dépend de la cadence, que seul le runner connaît.
        self._marge_lobby_s = marge_lobby_bornee(marge_lobby_s, cadence_s)
        self._api_muette_max_s = api_muette_max_s
        # Le statut du live, tel que le `StreamWatcher` le tient déjà à jour
        # (60 s). TROIS réponses possibles, et la troisième compte autant que
        # les deux autres : True, False, et None — « on ne sait pas », avant le
        # premier relevé. Une absence de donnée n'est pas un stream éteint.
        # Absent (None en construction), le garde-fou est simplement inactif :
        # un duel doit pouvoir tourner sans lui.
        self._stream_en_ligne = stream_en_ligne
        self._stream_coupe_max_s = stream_coupe_max_s
        # Instant du premier relevé « hors ligne » d'une série. Même patron que
        # `_muet_depuis`, et pas persisté pour la même raison : un rebuild ne
        # fait qu'accorder de la tolérance en plus.
        self._offline_depuis: float | None = None
        self.duel_en_cours: Duel | None = None
        self._reward_id = ""
        # Instant du PREMIER relevé raté d'une série, pendant une manche.
        # Remis à None dès qu'un relevé passe — ce qui suffit à ne jamais
        # transmettre un silence d'un duel au suivant : on n'entre en MANCHE
        # que sur des relevés réussis. Volontairement pas persisté : un
        # rebuild remet le compteur à zéro, ce qui ne fait qu'accorder de la
        # tolérance en plus, jamais un abandon prématuré.
        self._muet_depuis: float | None = None
        # Deux achats à moins d'une seconde d'intervalle passaient tous les
        # deux le test « un duel est-il déjà en cours ? » : il précède un appel
        # réseau d'environ une seconde, et `duel_en_cours` n'était affecté
        # qu'après. Le second écrasait le premier, dont le `redemption_id`
        # était perdu — points jamais rendus.
        self._verrou_ouverture = asyncio.Lock()
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
        """L'intervalle entre deux relevés pendant une manche, en secondes."""
        return self._cadence_s

    @property
    def cadence_courante(self) -> float:
        """Le sommeil qui convient à l'état du duel.

        Rapprochée seulement quand il y a quelque chose à mesurer. En
        RESOLUTION on attend un message du duelliste, pas un relevé : se
        réveiller toutes les deux secondes n'y sert qu'à faire tourner un
        minuteur.
        """
        duel = self.duel_en_cours
        if duel is None or duel.etat is Etat.RESOLUTION:
            return REPOS_SANS_DUEL_S
        return self._cadence_s

    def _nouveau_duel(self, **champs) -> Duel:
        """Un `Duel` neuf, réglé par la configuration du runner."""
        return Duel(azrael_uid=self._azrael_uid, manches=self._manches,
                    attente_squad_s=self._attente_squad_s,
                    plafond_kills_manche=self._plafond_kills_manche,
                    marge_lobby_s=self._marge_lobby_s, **champs)

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

        Une récompense retrouvée est aussi REMISE À JOUR si son titre, son coût
        ou son invite ont bougé en configuration. Sans ça, éditer `apex.duel`
        n'avait aucun effet : le libellé n'était écrit qu'à la création, et la
        récompense en service continuait d'annoncer autre chose. On la modifie,
        jamais on ne la recrée — une récompense recréée perd son historique, et
        une récompense créée hors de notre application est irremboursable.
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
            actuelle = next((r for r in gerables if r.get("id") == connu), None)
            if actuelle is not None:
                self._reward_id = connu
                # Une mise à jour ratée ne coûte que le libellé : le duel reste
                # jouable et remboursable sur la récompense existante.
                await self._api.maj_recompense(connu, titre, cout, prompt,
                                               actuelle=actuelle)
                return connu
            logger.warning("Récompense de duel {i} introuvable côté Twitch — on recrée", i=connu)
        nouvel_id = await self._api.creer_recompense(titre, cout, prompt)
        if not nouvel_id:
            logger.error("Récompense de duel impossible à créer — duel indisponible")
            return ""
        await self._db.set_state(CLE_RECOMPENSE, nouvel_id)
        self._reward_id = nouvel_id
        return nouvel_id

    async def rattraper_les_achats_manques(self) -> int:
        """Rembourse les achats faits pendant que le bot était arrêté.

        EventSub ne rejoue RIEN : un viewer qui achète pendant un rebuild — la
        spec dit elle-même qu'ils sont fréquents — perdait sa mise en silence.
        Pas de duel, pas de remboursement, pas un mot, et une redemption
        coincée dans la file de validation du streamer.

        On ne rouvre PAS un duel rétroactivement : l'achat peut dater d'hier,
        le viewer n'est peut-être plus là, et Azraël ne joue peut-être plus.
        On rend les points, et on dit pourquoi.

        Le duel repris de `bot_state`, lui, est épargné : sa redemption est
        encore `UNFULFILLED` puisqu'elle n'est soldée qu'à la fin — la
        rembourser ici solderait un duel en cours d'arbitrage.

        Ne fait jamais échouer le démarrage : `None` (panne Twitch) est traité
        comme une liste vide, et l'appelant enveloppe le tout.
        """
        if not self._reward_id:
            return 0
        en_attente = await self._api.redemptions_en_attente(self._reward_id)
        if not en_attente:
            # `None` (panne) comme `[]` (rien en attente) : dans les deux cas
            # il n'y a rien à rembourser MAINTENANT, et surtout rien à inventer.
            return 0
        en_cours = (self.duel_en_cours.redemption_id
                    if self.duel_en_cours is not None else "")
        rattrapees = 0
        for redemption in en_attente:
            rid = str((redemption or {}).get("id") or "")
            if not rid or rid == en_cours:
                continue
            acheteur = str((redemption or {}).get("user_name")
                           or (redemption or {}).get("user_login") or "")
            logger.warning(
                "Duel Apex : achat manqué pendant une indisponibilité "
                "(redemption {i}, {u}) — remboursement", i=rid, u=acheteur or "?")
            donnees: dict = {"viewer": acheteur}
            if not await self._rembourser(self._reward_id, rid,
                                          quoi="achat manqué pendant l'arrêt du bot"):
                donnees["remboursement_echoue"] = True
            await self._annoncer_sur(Evenement("rattrapage", donnees))
            rattrapees += 1
        return rattrapees

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
    async def _rembourser(self, reward_id: str, redemption_id: str,
                          *, quoi: str) -> bool:
        """Rend les points, et dit si Twitch a VRAIMENT obéi.

        Le seul endroit du runner qui appelle `refund_redemption` : le retour y
        est lu une fois pour toutes, et le `logger.error` est écrit une fois
        pour toutes. Cinq appelants l'ignoraient, chacun à sa façon.
        """
        if await self._api.refund_redemption(reward_id, redemption_id):
            return True
        logger.error(
            "Duel Apex : REMBOURSEMENT REFUSÉ par Twitch ({q}) — redemption {i} "
            "sur la récompense {r} : les points du viewer ne sont pas revenus, "
            "il faut les rendre à la main",
            q=quoi, i=redemption_id or "?", r=reward_id or "?")
        return False

    async def _refuser(self, reward_id: str, redemption_id: str, motif: str) -> None:
        """Un refus se rembourse ET s'annonce — dans cet ordre.

        Le remboursement d'abord : si l'annonce lève (appel LLM, envoi
        Twitch…), le viewer doit avoir récupéré ses points malgré tout. C'est
        déjà la règle suivie par `annuler()` ; elle doit valoir partout.

        Et si le remboursement ÉCHOUE, l'annonce le dit : promettre des points
        qui ne reviendront pas est pire que le refus lui-même.
        """
        logger.info("Duel refusé : {m}", m=motif)
        evt = Evenement("refus", {"motif": motif})
        if not await self._rembourser(reward_id, redemption_id, quoi="refus"):
            evt = _echec_de_remboursement(evt)
        await self._annoncer_sur(evt)

    async def ouvrir(self, *, acheteur: str, saisie: str,
                     reward_id: str, redemption_id: str,
                     acheteur_id: str = "") -> None:
        """Sérialisée : deux achats simultanés s'ouvrent l'un APRÈS l'autre.

        Sans ce verrou, le test « un duel est-il déjà en cours ? » et
        l'affectation de `duel_en_cours` étaient séparés par un appel réseau
        d'environ une seconde. Deux achats à moins d'une seconde d'intervalle
        passaient donc tous les deux : le second écrasait le premier, dont le
        `redemption_id` était perdu définitivement — ses points n'étaient
        jamais rendus, et l'annonce d'ouverture parlait de quelqu'un d'autre.
        Le second entre maintenant après le premier, voit le duel en cours et
        se fait refuser proprement : remboursé ET annoncé.
        """
        async with self._verrou_ouverture:
            await self._ouvrir(acheteur=acheteur, saisie=saisie,
                               reward_id=reward_id, redemption_id=redemption_id,
                               acheteur_id=acheteur_id)

    async def _ouvrir(self, *, acheteur: str, saisie: str,
                      reward_id: str, redemption_id: str,
                      acheteur_id: str = "") -> None:
        if self.duel_en_cours is not None:
            # Un duel tourne déjà : le remboursement seul laissait le viewer
            # sans un mot d'explication (Task 7, faute de canal d'annonce).
            # Ne JAMAIS écraser le duel en cours au passage.
            await self._refuser(reward_id, redemption_id, "un duel est déjà en cours")
            return

        if _uid_valide(saisie) == self._azrael_uid:
            # Tranché sans le moindre appel réseau quand l'identifiant est
            # donné tel quel.
            await self._refuser(reward_id, redemption_id, MOTIF_SOI_MEME)
            return

        resolu, cause = await self._resoudre(saisie)
        if resolu is None:
            # Un compte non résolu : PAS de remboursement au premier essai, ni
            # pour un pseudo ni pour un identifiant. La recherche par pseudo de
            # l'API rate des comptes bien réels, et un identifiant peut être mal
            # recopié, venir d'une autre plateforme, ou tomber sur un hoquet de
            # l'API — refuser sèchement punirait le viewer pour un défaut qui
            # n'est pas le sien. Il a droit au mode d'emploi et à ses essais,
            # avec la VRAIE cause : le numérique s'entendait dire « aucun
            # tracker de kills n'est épinglé sur ce compte », affirmation
            # souvent fausse sur son propre compte, devant le stream.
            await self._demander_uid(acheteur, reward_id, redemption_id,
                                     acheteur_id=acheteur_id, cause=cause)
            return

        uid, profil = resolu
        if uid == self._azrael_uid:
            # Le viewer a donné le PSEUDO d'Azraël : la comparaison ne portait
            # que sur l'identifiant, et ce chemin-là passait au travers.
            await self._refuser(reward_id, redemption_id, MOTIF_SOI_MEME)
            return
        if not read_kill_trackers(profil):
            await self._refuser(
                reward_id, redemption_id,
                "aucun tracker de kills n'est épinglé sur ce compte")
            return

        self._reward_id = reward_id
        self.duel_en_cours = self._nouveau_duel(
            viewer_nom=acheteur, viewer_uid=uid, viewer_id=_id_twitch(acheteur_id),
            redemption_id=redemption_id, etat=Etat.ATTENTE_SQUAD)
        await self._ranger()
        await self._annoncer_sur(Evenement("duel_ouvert", {"viewer": acheteur}))

    async def _demander_uid(self, acheteur: str, reward_id: str,
                            redemption_id: str, *, acheteur_id: str = "",
                            cause: str = CAUSE_INTROUVABLE) -> None:
        """Explique comment trouver son uid, et garde le duel en attente.

        Pas de remboursement ici : c'est le point même de cette étape (§9 de
        la spec) — le viewer garde ses points dépensés pendant qu'on lui
        laisse une vraie chance de répondre correctement.

        `cause` voyage jusqu'à l'annonce : dire « compte introuvable » quand
        c'est l'API qui est tombée, ou « aucun tracker épinglé » quand le
        compte n'a même pas été trouvé, revient à affirmer devant le stream
        une chose fausse sur le compte de quelqu'un.
        """
        self._reward_id = reward_id
        self._tentatives = 0
        self.duel_en_cours = self._nouveau_duel(
            viewer_nom=acheteur, viewer_uid="", viewer_id=_id_twitch(acheteur_id),
            redemption_id=redemption_id, etat=Etat.RESOLUTION)
        await self._ranger()
        await self._annoncer_sur(Evenement("compte_introuvable", {
            "viewer": acheteur, "url": URL_APEX_STATUS, "etapes": ETAPES_UID,
            "cause": cause,
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

        # Un pseudo est accepté ici aussi : le viewer a pu se tromper de
        # plateforme ou d'orthographe au premier essai, pas forcément renoncer
        # à son pseudo. Le compte d'Azraël reste écarté, donné sous l'une ou
        # l'autre forme.
        resolu, cause = None, CAUSE_SOI_MEME
        if _uid_valide(texte) != self._azrael_uid:
            resolu, cause = await self._resoudre(texte)
        if self.duel_en_cours is not duel:
            # La sonde de fond (`tick()`) a pu faire expirer ce duel
            # PENDANT cet appel réseau d'~1 s (délai de résolution
            # écoulé) : remboursement et abandon déjà annoncés sur
            # l'objet `duel` capturé ci-dessus, qui est maintenant
            # orphelin. Reprendre dessus rouvrirait un duel fantôme
            # (« duel_ouvert » juste après « abandonné ») ou, plus bas,
            # rembourserait une seconde fois la même redemption. Le
            # message reste consommé : il ne doit pas repartir dans le
            # traitement normal du chat.
            return True
        if resolu is not None and resolu[0] == self._azrael_uid:
            # Le PSEUDO d'Azraël, cette fois : la comparaison d'entrée ne
            # portait que sur l'identifiant.
            cause = CAUSE_SOI_MEME
        elif resolu is not None:
            uid, profil = resolu
            if not read_kill_trackers(profil):
                # Le compte est là, il est juste illisible : le dire tel quel
                # laisse au duelliste la seule action qui débloque la situation
                # — épingler un tracker de kills en jeu, puis répondre.
                cause = CAUSE_SANS_TRACKER
            else:
                duel.viewer_uid = uid
                # Le délai d'attente du squad repart à neuf : il ne doit pas
                # hériter du temps passé à chercher son uid.
                duel.demarrer_attente_squad()
                await self._ranger()
                await self._annoncer_sur(Evenement("duel_ouvert", {"viewer": duel.viewer_nom}))
                return True

        self._tentatives += 1
        if self._tentatives >= TENTATIVES_RESOLUTION:
            # Rembourser D'ABORD, nettoyer et persister ENSUITE, annoncer
            # SEULEMENT après — même ordre que `_avancer()` : une annonce qui
            # lève ne doit jamais laisser un remboursement en suspens ni un
            # duel fantôme derrière elle.
            evt = Evenement("abandon", {
                "rembourser": True,
                "motif": "impossible de retrouver ce compte Apex"})
            if not await self._rembourser(self._reward_id, duel.redemption_id,
                                          quoi="compte Apex jamais résolu"):
                evt = _echec_de_remboursement(evt)
            self.duel_en_cours = None
            await self._ranger()
            await self._annoncer_sur(evt)
            # Après l'annonce, comme partout : la trace ne passe jamais devant
            # les points ni devant la parole. Ce duel n'a pas eu lieu, mais
            # l'achat, lui, a bien eu lieu.
            await self._memoriser(duel, evt)
            return True

        await self._annoncer_sur(Evenement("compte_introuvable", {
            "viewer": duel.viewer_nom, "url": URL_APEX_STATUS,
            "etapes": ETAPES_UID, "cause": cause}))
        return True

    # -- Sonde --------------------------------------------------------------
    async def _profil(self, uid: str) -> dict | None:
        """Le profil du compte d'identifiant `uid`, ou `None`.

        La cause de l'échec ne sert qu'à la résolution — la sonde d'un duel en
        cours, elle, ne fait que constater qu'un relevé manque.
        """
        profil, _ = await self._bridge({"uid": uid})
        return profil

    async def _profil_par_pseudo(self, pseudo: str) -> tuple[dict | None, str]:
        """Le profil du compte qui porte ce pseudo, et la cause si rien.

        L'API veut `platform` dans les deux cas — c'est déjà ce que fait le
        reste du paquet (`service.py`), qui bascule entre `uid` et `player`
        sans jamais lâcher la plateforme.

        Rate des comptes parfaitement réels, mesuré sur plusieurs comptes y
        compris avec la casse officielle : d'où le repli qui explique comment
        trouver l'UID, et qui ne disparaît pas avec cette voie-ci.
        """
        return await self._bridge({"player": pseudo})

    async def _bridge(self, cle: dict) -> tuple[dict | None, str]:
        """Le profil, ou `None` et la CAUSE si la sonde n'a rien d'exploitable.

        Trois formes d'échec à écarter, pas une seule : `client.get` peut
        rendre une CHAÎNE d'erreur (panne réseau, cf. `ApexClient.get`), un
        dict `{"Error": "Player not found."}` avec un 200 tout à fait normal
        — piège documenté du projet (`reader.py`, `service.py`) — ou un dict
        VIDE (ni erreur ni contenu). Un `_profil()` qui acceptait l'un de ces
        cas comme un relevé valide donnait `isInGame` absent → `False`, et
        deux relevés d'erreur consécutifs suffisaient à faire croire à un
        retour au lobby en pleine manche réelle. `realtime` est présent dans
        tous les profils authentiques — y compris ceux vérifiés à l'ouverture
        d'un duel — donc son absence signe un corps inexploitable.

        Ces trois formes ne disent pas la même chose au viewer, et c'est tout
        l'objet de la cause rendue ici : seul le corps « not found » prouve que
        le compte n'a pas été trouvé. Les deux autres sont des pannes, et les
        annoncer comme un compte inexistant était affirmer devant le stream une
        chose fausse sur le compte de quelqu'un.
        """
        p = await self._client.get(
            "bridge", {**cle, "platform": self._plateforme}, sans_cache=True)
        if not isinstance(p, dict):
            return None, CAUSE_API
        if "Error" in p:
            # « Player not found. » est la seule erreur qui parle du COMPTE ;
            # les autres (quota, maintenance, clé) parlent de l'API.
            introuvable = "not found" in str(p.get("Error") or "").lower()
            return None, (CAUSE_INTROUVABLE if introuvable else CAUSE_API)
        if "realtime" not in p:
            # Un 200 sans erreur ni contenu : on ne peut rien en conclure sur
            # le compte, donc on n'en conclut rien.
            return None, CAUSE_API
        return p, ""

    async def _resoudre(self, saisie: str) -> tuple[tuple[str, dict] | None, str]:
        """Le compte Apex derrière une saisie de viewer : `(uid, profil)`.

        Les DEUX formes prévues par la spec (§3) sont acceptées : un identifiant
        purement numérique, ou un pseudo. Exiger l'uid renvoyait tout le monde
        au mode d'emploi pour un achat qui coûte des points.

        Le second membre est la CAUSE de l'échec (`""` en cas de succès) :
        compte introuvable, ou API indisponible. L'appelant en fait un message
        — c'est la seule chose qui distingue « ton compte n'existe pas » d'un
        hoquet de l'API, et le viewer entend l'un ou l'autre en direct.
        """
        uid = _uid_valide(saisie)
        if uid is not None:
            profil, cause = await self._bridge({"uid": uid})
            return ((uid, profil), "") if profil is not None else (None, cause)

        pseudo = _pseudo_valide(saisie)
        if pseudo is None:
            # Ça ne ressemble à rien de sondable : ni un uid, ni un pseudo. Rien
            # ne part au réseau, et il n'y a pas de compte à ne pas avoir trouvé.
            return None, CAUSE_INTROUVABLE
        profil, cause = await self._profil_par_pseudo(pseudo)
        if profil is None:
            return None, cause
        uid = _uid_du_profil(profil)
        return ((uid, profil), "") if uid else (None, CAUSE_INTROUVABLE)

    async def _avancer(self, duel: Duel, releve: Releve) -> None:
        """Fait avancer la machine d'un relevé, et applique les effets."""
        await self._appliquer(duel, duel.avancer(releve))

    async def _appliquer(self, duel: Duel, evts: list[Evenement]) -> None:
        """Applique les effets d'une salve d'événements.

        Ordre STRICT : remboursement(s) → nettoyage de `duel_en_cours` →
        persistance → annonces. Si l'annonce d'un abandon levait AVANT le
        remboursement et le nettoyage, l'exception sortirait avec les points
        du viewer non rendus, `duel_en_cours` toujours peuplé (donc tous les
        viewers suivants refusés indéfiniment) et l'état persisté périmé — un
        rebuild ressusciterait ce duel fantôme via `charger()`.

        Partagé par `_avancer()` (relevé) et par l'abandon sur API muette :
        les deux doivent tenir cet ordre, et un seul endroit le garantit.
        """
        for evt in evts:
            if evt.type == "abandon":
                # `manches_jouees` n'existe que sur les abandons issus
                # d'ENTRE_MANCHES — jamais un accès direct.
                logger.info(
                    "Duel Apex : abandon — {m} (manches jouées : {n})",
                    m=evt.donnees.get("motif"), n=evt.donnees.get("manches_jouees", 0))
        tranche = _tranche_les_points(evts)
        if await self._solder(duel, tranche):
            # Le remboursement a été REFUSÉ par Twitch : l'événement qui
            # tranchait les points doit cesser de promettre qu'ils reviennent.
            # Marqué ici, avant les annonces et sans toucher à l'ordre :
            # l'annonceur ne sait rien de Twitch, et le duel est déjà soldé.
            evts = [_echec_de_remboursement(e) if e is tranche else e
                    for e in evts]
        # Terminal = VERDICT ou ABANDON : après un abandon survenu alors qu'au
        # moins une manche a été mesurée, l'état final est VERDICT et non
        # ABANDON (le duel tranche sur les manches jouées). Nettoyer sur « le
        # duel est terminal » et non sur un état précis évite de rater ce cas.
        if duel.etat in (Etat.VERDICT, Etat.ABANDON):
            self.duel_en_cours = None
        await self._ranger()
        for evt in evts:
            await self._annoncer_sur(evt)
        # EN DERNIER, après la chaîne intouchable remboursement → nettoyage →
        # persistance → annonce : la trace mémoire est un bonus, elle ne prend
        # jamais le pas sur les points du viewer ni sur ce qui se dit à l'écran.
        #
        # UNE trace par salve, et pas une par événement : le duelliste qui ne
        # revient pas après une manche comptée déclenche un abandon PUIS un
        # verdict — deux `memory.add()` en écriraient deux, dont l'une
        # contredirait l'autre.
        await self._memoriser(duel, _trace_de_fin(evts))

    async def _solder(self, duel: Duel, evt: Evenement | None) -> bool:
        """Le sort des points, appliqué UNE fois et jamais laissé en suspens.

        Rembourser quand l'événement le dit, honorer sinon. Le second n'est pas
        une formalité : une redemption laissée `UNFULFILLED` reste dans la file
        de validation du streamer et s'y empile duel après duel — c'est le
        « ni l'un ni l'autre » qu'on refuse ici.

        `None` = cette salve ne solde rien (début ou fin de manche) : on ne
        touche pas aux points, ils sont encore en jeu.

        Rend `True` quand un REMBOURSEMENT a été tenté et REFUSÉ : l'appelant
        doit alors corriger l'annonce, qui promettrait sinon des points qui ne
        reviendront pas.
        """
        if evt is None:
            return False
        if evt.donnees.get("rembourser"):
            return not await self._rembourser(
                self._reward_id, duel.redemption_id, quoi=evt.type)
        await self._api.honorer_redemption(self._reward_id, duel.redemption_id)
        return False

    async def _memoriser(self, duel: Duel, evt: Evenement | None) -> None:
        """Le duel laisse une trace : « tu m'avais mis 11–6 le mois dernier ».

        Écrit un fait lisible tel quel — par un humain comme par le journal
        quotidien, qui lit déjà la mémoire et n'a donc rien à brancher.

        La trace dit ce qui s'est RÉELLEMENT passé. Deux façons de mentir
        étaient ouvertes, et toutes deux fabriquaient de faux précédents pour
        la revanche :

          · le drapeau `abandon` du verdict était ignoré — un duelliste qui
            mène puis quitte se retrouvait mémorisé « vainqueur » d'un duel
            régulier, exactement ce que la règle du jeu refuse de récompenser ;
          · une fin SANS verdict (abandon remboursé, annulation par un
            modérateur, compte jamais résolu) ne laissait rien du tout, alors
            que c'est une soirée où quelqu'un a bel et bien dépensé ses points.

        Ne fait JAMAIS échouer un duel : le verdict est déjà annoncé et les
        points déjà arbitrés quand on arrive ici. Une mémoire absente,
        indisponible ou en erreur se journalise et s'oublie.
        """
        if self._memory is None or evt is None:
            return
        if not duel.viewer_id:
            # Pas de silence : sans id, il n'y a pas de fiche où ranger ça, et
            # deviner (par pseudo) fabriquerait un utilisateur fantôme.
            logger.warning(
                "Duel Apex : résultat non mémorisé, l'identifiant Twitch de {v} "
                "est inconnu", v=duel.viewer_nom or "?")
            return
        d = evt.donnees or {}
        nom = duel.viewer_nom or "le duelliste"
        # Seules les manches MESURÉES sont comptées : annoncer « sur 3 manches »
        # quand une seule a pu être lue serait un chiffre inventé de plus.
        scores = d.get("scores") or duel.scores
        comptees = sum(1 for s in scores if s.get("azrael") is not None)
        manches = f"{comptees} manche{'s' if comptees > 1 else ''} comptée" \
                  f"{'s' if comptees > 1 else ''}"
        if evt.type != "verdict":
            # Aucun verdict : personne n'a gagné, et la trace ne doit surtout
            # pas en inventer un. Elle dit qu'il y a eu un duel, et pourquoi il
            # s'est arrêté — c'est ça, le précédent d'une revanche.
            joue = f" {manches} avaient été jouées, mais" if comptees else ""
            fait = (f"{nom} a acheté un duel Apex contre Azraël avec ses points de "
                    f"chaîne, mais le duel n'est pas allé à son terme :{joue} "
                    f"{d.get('motif') or 'le duel a été interrompu'}. Pas de "
                    f"vainqueur.")
        else:
            gagnant = d.get("gagnant")
            issue = ("personne ne l'emporte, égalité" if gagnant is None
                     else ("Azraël l'emporte" if gagnant == "azrael"
                           else f"{nom} l'emporte"))
            if d.get("abandon"):
                # Le verdict porte sur les seules manches jouées : le dire
                # ainsi, sinon la revanche s'appuiera sur une victoire qui n'a
                # jamais eu lieu en entier.
                fait = (f"{nom} a joué un duel Apex contre Azraël, acheté avec ses "
                        f"points de chaîne, mais le duel a été INTERROMPU avant la "
                        f"fin : sur {manches}, Azraël {d.get('azrael')} — {nom} "
                        f"{d.get('viewer')}, {issue} sur ce qui a été joué.")
            else:
                fait = (f"{nom} a joué un duel Apex contre Azraël, acheté avec ses "
                        f"points de chaîne : Azraël {d.get('azrael')} — {nom} "
                        f"{d.get('viewer')} sur {manches}, {issue}.")
        try:
            # Id BRUT, jamais préfixé : `memory.add()` construit `twitch:<id>`
            # lui-même. La forme préfixée donnerait `twitch:twitch:<id>`.
            await self._memory.add("twitch", duel.viewer_id, fait,
                                   username=duel.viewer_nom or None,
                                   source="apex_duel",
                                   origin="Duel Apex (points de chaîne)")
        except Exception as exc:  # noqa: BLE001 — une trace ratée n'annule pas un duel
            logger.warning("Duel Apex : résultat non mémorisé : {e}", e=exc)

    async def _api_muette(self, duel: Duel, maintenant: float) -> bool:
        """Un duel que plus aucun relevé ne peut faire avancer.

        `tick()` sort sans rien faire quand un relevé manque en MANCHE, et
        c'est délibéré : injecter un relevé fictif « hors partie » clôturerait
        une manche réellement en cours sur un simple hoquet. Mais sans
        contrepartie, une panne prolongée — ou un profil devenu illisible —
        gèle le duel pour toujours. C'est cette contrepartie.

        Vaut AUSSI entre deux manches, et pas seulement pendant l'une d'elles.
        Là-bas le minuteur d'attente du squad continuait bien de tourner, mais
        il finissait sur « le duelliste n'est pas revenu dans le délai » : pas
        de remboursement, et un viewer accusé d'un abandon dont l'API seule
        était l'auteur. Le même silence doit rendre le même verdict — une
        panne, donc les points.

        Rend `True` quand le duel a été soldé : l'appelant s'arrête là.
        """
        ou = ("en pleine manche" if duel.etat is Etat.MANCHE
              else "entre deux manches")
        if self._muet_depuis is None:
            self._muet_depuis = maintenant
            # WARNING et non DEBUG : c'est le seul signe visible en production
            # qu'un duel est en train de s'enliser. Une seule ligne par série,
            # pas une par tour de sonde (2 s).
            logger.warning(
                "Duel Apex : plus aucun relevé lisible {o} ({m}/{s}) — abandon "
                "et remboursement si ça dure au-delà de {d:.0f} s",
                o=ou, m=duel.manche_courante, s=duel.manches,
                d=self._api_muette_max_s)
            return False
        silence = maintenant - self._muet_depuis
        if silence < self._api_muette_max_s:
            return False
        duree = f"{int(silence // 60)} min" if silence >= 60 else f"{int(silence)} s"
        logger.error(
            "Duel Apex : API muette depuis {d} {o} — abandon", d=duree, o=ou)
        self._muet_depuis = None
        await self._appliquer(duel, duel.abandonner(
            f"l'API Apex ne répond plus depuis {duree} {ou}, plus rien ne peut "
            "être compté — une panne, pas un abandon du duelliste"))
        return True

    async def _stream_coupe(self, duel: Duel, maintenant: float) -> bool:
        """Le live d'Azraël s'est éteint pendant le duel (§8 de la spec).

        Un duel sans stream n'a plus d'objet : Azraël ne joue plus, le viewer
        ne peut plus rien mesurer, et rien de tout ça n'est de son fait. La
        spec le range depuis toujours parmi les remboursements ; il n'était
        simplement branché nulle part, et le duel finissait par tomber sur le
        timeout d'attente, qui lui NE rembourse pas et annonce « il n'est pas
        allé au bout du duel ». Le viewer était puni et accusé pour une panne.

        Deux gardes, pour deux erreurs différentes :
          · `None` (le watcher n'a pas encore sondé) n'est PAS « hors ligne » —
            un rebuild en plein duel ne doit pas solder sur une valeur par
            défaut ;
          · un seul relevé « hors ligne » ne suffit pas : `/helix/streams` rend
            parfois une liste vide sur une chaîne allumée, et ça coûterait au
            duelliste une partie qu'il est en train de jouer.

        Rend `True` quand le duel a été soldé : l'appelant s'arrête là.
        """
        if self._stream_en_ligne is None:
            return False
        try:
            en_ligne = self._stream_en_ligne()
        except Exception as exc:  # noqa: BLE001 — un statut illisible n'abandonne rien
            logger.warning("Duel Apex : statut du live illisible : {e}", e=exc)
            return False
        if en_ligne is not False:
            self._offline_depuis = None
            return False
        if self._offline_depuis is None:
            self._offline_depuis = maintenant
            logger.warning(
                "Duel Apex : le stream est vu hors ligne — abandon et "
                "remboursement si ça se confirme au-delà de {d:.0f} s",
                d=self._stream_coupe_max_s)
            return False
        if maintenant - self._offline_depuis < self._stream_coupe_max_s:
            return False
        self._offline_depuis = None
        logger.error("Duel Apex : stream coupé en cours de duel — abandon et "
                     "remboursement")
        await self._appliquer(duel, duel.abandonner(
            "le stream d'Azraël s'est coupé en cours de duel — une panne, pas "
            "un abandon du duelliste"))
        return True

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
        if duel is None or duel.etat in (Etat.VERDICT, Etat.ABANDON):
            return
        # AVANT tout le reste : un duel sans stream n'a plus d'objet, quel que
        # soit l'état où il se trouve. Continuer à sonder ne ferait que le
        # mener au timeout d'attente, qui ne rembourse pas et accuse le viewer.
        if await self._stream_coupe(duel, maintenant):
            return
        if duel.etat is Etat.RESOLUTION:
            # Aucun compte à sonder tant que l'uid n'est pas donné : ce tour ne
            # coûte AUCUNE requête. Il ne sert qu'à faire avancer le délai de
            # résolution, sans quoi un duelliste qui se tait gèle le duel pour
            # toujours.
            await self._avancer(duel, Releve(
                t=maintenant, azrael_in_game=False, viewer_in_game=False,
                kills_azrael={}, kills_viewer={}))
            return
        # EN PARALLÈLE, et c'est la cadence même du duel qui en dépend : une
        # requête `/bridge` coûte ~1 s de latence, donc deux profils sondés
        # l'un après l'autre portaient le tour à ~2 s AVANT le sommeil de
        # `cadence_s`. La cadence réelle valait le double de celle annoncée (4 s
        # au lieu de 2), et le debounce à deux relevés reportait la détection
        # d'une transition à ~8 s — pour un plafond dur mesuré à 39 s entre un
        # retour au lobby et le lancement suivant. L'API accepte 5 req/s
        # (mesuré) et le limiteur du client espace de toute façon les deux
        # départs : deux requêtes simultanées ne coûtent rien.
        azrael, viewer = await asyncio.gather(
            self._profil(duel.azrael_uid), self._profil(duel.viewer_uid))
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
            if duel.etat is Etat.ENTRE_MANCHES:
                # Le même garde-fou qu'en MANCHE, et pour la même raison : le
                # minuteur qui tourne ici finit sur « le duelliste n'est pas
                # revenu », donc SANS remboursement, alors que c'est l'API qui
                # s'est tue. Il passe en premier — un silence prolongé est une
                # panne, jamais un abandon.
                if await self._api_muette(duel, maintenant):
                    return
            elif duel.etat is Etat.MANCHE:
                # En MANCHE il n'y a AUCUN autre minuteur : c'est ici, et nulle
                # part ailleurs, que la panne prolongée se voit et se solde.
                await self._api_muette(duel, maintenant)
                return
            # ATTENTE_SQUAD et ENTRE_MANCHES : le minuteur d'attente doit
            # continuer d'avancer malgré la panne — sinon elle gèlerait le duel
            # pour toujours (jamais de timeout, jamais de remboursement, et le
            # viewer suivant resterait refusé indéfiniment). On s'en abstient en
            # MANCHE : y injecter un relevé fictif "hors partie" risquerait de
            # clore une manche réellement en cours via le debounce de fin de
            # partie, sur un simple hoquet de l'API.
            logger.debug("Duel : relevé incomplet, tour sauté")
            await self._avancer(duel, Releve(
                t=maintenant, azrael_in_game=False, viewer_in_game=False,
                kills_azrael={}, kills_viewer={}))
            return
        self._muet_depuis = None

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
            camp_azrael=_camp(azrael),
            camp_viewer=_camp(viewer),
        )
        await self._avancer(duel, releve)

    # -- Contrôle (streamer et modérateurs) ---------------------------------
    async def annuler(self, motif: str) -> bool:
        """Annulation par le streamer ou un modérateur. Rend `False` si les
        points n'ont pas pu être rendus — l'outil du chat le répète alors au
        modèle plutôt que d'affirmer un remboursement qui n'a pas eu lieu."""
        duel = self.duel_en_cours
        if duel is None:
            return True
        evt = Evenement("abandon", {"motif": motif, "rembourser": True})
        rendu = await self._rembourser(self._reward_id, duel.redemption_id,
                                       quoi="annulation depuis le chat")
        if not rendu:
            evt = _echec_de_remboursement(evt)
        self.duel_en_cours = None
        await self._ranger()
        await self._annoncer_sur(evt)
        # Un duel annulé par un modérateur reste un duel qui a eu lieu pour
        # celui qui l'a payé : sans trace, la revanche n'aurait aucun
        # précédent — et surtout aucun vainqueur ne doit être inventé.
        await self._memoriser(duel, evt)
        return rendu

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

    Le rattrapage des achats manqués vient APRÈS les deux premiers, et pour
    deux raisons : il lui faut l'identifiant de la récompense, et il lui faut
    savoir quel duel a été repris — sa redemption est encore en attente, et la
    rembourser solderait un duel en cours d'arbitrage. Il ne peut PAS empêcher
    le démarrage : un bot qui tourne sans rattrapage vaut mieux qu'un bot qui
    refuse de démarrer.

    Rassemblé ici, et non déroulé dans `main.py`, pour que cet ordre soit
    JOUABLE en test — c'est le seul endroit où il se vérifie.
    """
    await runner.charger()
    reward_id = await runner.assurer_recompense(titre, cout, prompt)
    try:
        await runner.rattraper_les_achats_manques()
    except Exception as exc:  # noqa: BLE001 — jamais bloquant pour le boot
        logger.error("Duel Apex : rattrapage des achats manqués en erreur : {e}",
                     e=exc)
    runner.activate()
    return reward_id


async def boucle_sonde(source: Callable[[], "DuelRunner | None"], *,
                       sleep=asyncio.sleep) -> None:
    """Sonde le duel en cours, et RIEN quand il n'y en a pas.

    Hors duel, aucune requête ne part : l'`ApexWatcher` entretient déjà
    l'historique du streamer, et un duel coûte à lui seul 1 requête/seconde
    (deux comptes toutes les 2 s, soit 20 % du débit autorisé).

    `source` est relue à CHAQUE tour, et non capturée une fois : le runner est
    câblé pendant le démarrage, et la boucle ne doit pas dépendre de qui, du
    câblage ou du `gather`, part le premier. Absent, elle attend simplement.

    `time.time()` et jamais `time.monotonic()` pour l'instant transmis à
    `tick()` : il est persisté dans l'état du duel et doit rester comparable
    après un redémarrage — une horloge monotone y repart de zéro (piège déjà
    payé ici, `bug_monotonic_uptime`). La DURÉE du tour, elle, se mesure avec
    `time.monotonic()` (un intervalle, jamais une date) : le tour lui-même
    coûte du temps — deux requêtes réseau, désormais parallèles mais espacées
    par le limiteur du client — et dormir la cadence PLEINE après un tour qui
    en a déjà consommé une partie fait dériver la période réelle bien au-delà
    de celle configurée. On dort donc le RELIQUAT (`cadence − durée`), jamais
    moins que zéro : un tour plus long que la cadence repart aussitôt, sans
    accumuler de retard.

    Vit tant que le bot vit : elle attrape, journalise et repart. Une boucle de
    fond qui meurt en silence laisse le duel figé sans que rien ne le signale.
    """
    while True:
        try:
            runner = source()
            if runner is None or runner.duel_en_cours is None:
                await sleep(REPOS_SANS_DUEL_S)
                continue
            debut = time.monotonic()
            await runner.tick(time.time())
            # La cadence vient du runner : rapprochée pendant une manche,
            # relâchée tant qu'il n'y a rien à mesurer. Lue APRÈS le tick,
            # comme avant ce correctif : le tour peut avoir fait changer
            # l'état (donc la cadence qui convient) entre les deux.
            cadence = runner.cadence_courante
            duree = time.monotonic() - debut
            await sleep(max(0.0, cadence - duree))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — la sonde ne meurt jamais en silence
            logger.error("Boucle de duel en erreur : {e}", e=exc)
            await sleep(RECUL_ERREUR_S)
