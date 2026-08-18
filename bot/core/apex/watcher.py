# bot/core/apex/watcher.py
"""Suivi passif du compte Apex du streamer, pendant le live seulement.

Même patron et même contrat que `stream_feed` : une voie SANS retour vers
l'action. Rien ici n'appelle `notify_activity` / `notify_event`. Wally SAIT
qu'Azraël est en partie sur Fuse ; il ne le commente que si on l'y amène.

La progression du live est notre réponse à `/games`, l'historique des matchs que
l'API nous refuse : on garde les compteurs du premier passage et on en fait la
différence. Elle se remet à zéro à chaque nouveau live — « depuis le début du
stream » n'a de sens que pour le stream en cours.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from loguru import logger

from bot.core.apex.kills_live import KillsDuLive
from bot.core.apex.reader import PlayerProfile

# Le point de départ du live, rangé en base : un rebuild d'image en pleine
# soirée remettait sinon la progression à zéro — et les rebuilds sont fréquents.
BASELINE_KEY = "apex:live_baseline"

# Deux cadences. Pendant le live, la courbe de progression est regardée en
# direct et mérite d'être fine ; hors live, on ne fait qu'entretenir
# l'historique des totaux, pour « combien de kills ce mois-ci ».
#
# L'API tolère 5 requêtes/seconde (doc officielle, vérifiée le 2026-08-11 ;
# la clé renvoie `x-current-rate` et aucun quota mensuel). À 30 s, on est à
# 0,03 req/s — deux ordres de grandeur sous la limite.
POLL_INTERVAL_LIVE_S = 30.0
POLL_INTERVAL_IDLE_S = 60.0
# Compat : d'anciens appels nommaient cet intervalle unique.
POLL_INTERVAL_S = POLL_INTERVAL_LIVE_S

_active: ApexWatcher | None = None


def current_apex_block() -> str | None:
    """Le bloc Apex prêt à injecter au prompt, ou None si rien à dire."""
    if _active is None:
        return None
    try:
        return _active.block()
    except Exception as exc:  # noqa: BLE001 — la perception ne casse jamais un prompt
        logger.debug("Apex watcher: bloc indisponible: {e}", e=exc)
        return None


class ApexWatcher:
    def __init__(
        self,
        service,
        account: tuple[str, str] | None,
        is_live: Callable[[], bool],
        interval_s: float = POLL_INTERVAL_LIVE_S,
        db=None,
        live_id: Callable[[], str] | None = None,
        history=None,
        idle_interval_s: float = POLL_INTERVAL_IDLE_S,
        on_partie: Callable[[dict], None] | None = None,
    ) -> None:
        self._service = service
        self._account = account
        self._is_live = is_live
        # Appelé à la fin de chaque partie, avec son bilan. Un rappel plutôt
        # qu'une référence au narrateur : le watcher naît AVANT lui, et
        # l'affichage n'a pas à faire partie de ce que sonde ce module.
        self._on_partie = on_partie
        self._kills: KillsDuLive | None = None
        self._kills_live_id = ""
        # Historique des totaux (`ApexHistory`), alimenté à CHAQUE passage —
        # y compris hors live : « ce mois-ci » compterait faux si les parties
        # jouées sans streamer manquaient à l'appel.
        self._history = history
        self._idle_interval = idle_interval_s
        # Dernier motif d'échec consigné, pour ne pas répéter la même ligne à
        # chaque passage. Une sonde qui tourne en continu et échoue en silence
        # laisse un historique vide qu'on découvre des semaines plus tard.
        self._dernier_echec: str | None = None
        # De QUEL live il s'agit — en pratique le `started_at` du stream. Le
        # point de départ rangé en base n'en portait aucune trace : un process
        # arrêté avant la fin du live A et redémarré pendant le live B rechargeait
        # le départ de A et le gardait. Wally annonçait alors aux spectateurs des
        # « +N kills depuis le début du live » cumulant deux sessions — de la
        # donnée fausse diffusée à l'écran, ce que ce paquet cherche à éviter.
        self._live_id = live_id
        self._interval = interval_s
        self._db = db
        self._profile: PlayerProfile | None = None
        self._baseline: dict[str, int] = {}
        self._baseline_loaded = False

    def _suivi_kills(self) -> KillsDuLive:
        """Le suivi partie par partie, créé à la demande.

        Rangé ici parce que c'est le watcher qui voit les transitions
        `in_game` — personne d'autre ne sonde le profil à la cadence du live.
        """
        if getattr(self, "_kills", None) is None:
            self._kills = KillsDuLive()
            self._kills_live_id = ""
        return self._kills

    def activate(self) -> None:
        """S'enregistre comme source globale, lisible par `prompts.py`."""
        global _active
        _active = self

    async def tick(self) -> None:
        """Un passage : relève les compteurs, et suit la progression si un live tourne.

        La sonde tourne désormais AUSSI hors live, pour tenir l'historique des
        totaux. La perception du live, elle, garde son contrat : hors live, pas
        de profil au prompt et pas de point de départ.
        """
        if not self._account:
            self._echec("aucun compte Apex configuré pour le streamer")
            return
        try:
            live = bool(self._is_live())
        except Exception as exc:  # noqa: BLE001 — sonde cassée = on suppose hors live
            self._echec(f"état du live indisponible ({exc})")
            live = False

        try:
            profile = await self._service.fetch_profile(self._account[0], self._account[1])
        except Exception as exc:  # noqa: BLE001 — une panne d'API ne tue pas le suivi
            self._echec(f"profil indisponible ({exc})")
            return
        if profile is None:
            self._echec("profil introuvable")
            return
        self._succes()
        await self._historiser(profile)

        if not live:
            # Le live est fini : la progression ne veut plus rien dire.
            self._profile = None
            self._baseline_loaded = False
            # Écrire seulement s'il y avait quelque chose à effacer : la branche
            # écrivait en base à CHAQUE tour hors live, soit ~960 commits par
            # jour sur le fichier SQLite partagé, pour rien.
            if self._baseline:
                self._baseline = {}
                await self._store_baseline({})
            return

        self._profile = profile

        # Les kills partie par partie. Le live courant sert de remise à zéro :
        # le cumul d'un soir ne doit pas traîner jusqu'au lendemain, ni un
        # redémarrage recoller deux sessions.
        suivi = self._suivi_kills()
        live_courant = self._live_courant()
        premier = getattr(self, "_kills_live_id", "") != live_courant
        if premier:
            suivi.nouveau_live()
            self._kills_live_id = live_courant
        bilan = suivi.relever(in_game=profile.in_game,
                              trackers=profile.kill_trackers, premier=premier)
        if bilan is not None and self._on_partie is not None:
            try:
                self._on_partie(bilan)
            except Exception as exc:  # noqa: BLE001 — l'affichage ne casse pas la sonde
                logger.warning("Apex watcher: bilan de partie non annoncé: {e}", e=exc)

        if not self._baseline and not self._baseline_loaded:
            # Un live peut avoir commencé avant ce process : on reprend le point
            # de départ rangé en base plutôt que d'en inventer un nouveau.
            self._baseline = await self._load_baseline()
            self._baseline_loaded = True
        if not self._baseline:
            # Premier passage du live : c'est le point de départ, pas un progrès.
            self._baseline = {k: s.value for k, s in profile.stats.items()}
            await self._store_baseline(self._baseline)

    async def run(self) -> None:
        """Boucle de fond. Ne s'arrête jamais d'elle-même."""
        while True:
            await self.tick()
            await asyncio.sleep(self._cadence())

    def _cadence(self) -> float:
        """30 s pendant le live, 60 s sinon. Hors live, seule l'historisation
        des totaux est en jeu : la finesse n'y sert à rien."""
        try:
            return self._interval if self._is_live() else self._idle_interval
        except Exception:  # noqa: BLE001 — sonde cassée : on prend le rythme lent
            return self._idle_interval

    async def _historiser(self, profile) -> None:
        """Range les compteurs du relevé. Jamais bloquant pour la perception."""
        if self._history is None:
            return
        compteurs = {k: s.value for k, s in profile.stats.items()}
        # Le RP part avec les autres. Le mode d'une partie n'existe NULLE PART
        # dans l'API — « BR Kills » inclut le classé, et `realtime` ne porte pas
        # la file de jeu — donc un RP qui bouge est le seul signal exploitable
        # qu'une partie était classée.
        #
        # Absent plutôt qu'à zéro quand le compte n'a pas de rang : un zéro se
        # lirait comme une chute de RP, donc comme une partie classée perdue.
        if profile.rank is not None:
            compteurs["rank_score"] = profile.rank.score
        try:
            await self._history.enregistrer(profile.uid, compteurs)
        except Exception as exc:  # noqa: BLE001 — l'historique est un bonus
            logger.warning("Apex watcher: relevé non historisé: {e}", e=exc)

    def _echec(self, motif: str) -> None:
        """Consigne un échec de sonde, au CHANGEMENT de motif seulement.

        En INFO et non en DEBUG : les journaux de production filtrent à INFO,
        et une sonde qui échoue en silence laisse un historique vide qu'on
        découvre des semaines plus tard. Filtré par motif parce qu'elle repasse
        toutes les 30 à 60 secondes.
        """
        if motif == self._dernier_echec:
            return
        self._dernier_echec = motif
        logger.info("Apex watcher: relevé impossible — {m}", m=motif)

    def _succes(self) -> None:
        if self._dernier_echec is not None:
            logger.info("Apex watcher: relevés repris")
            self._dernier_echec = None

    def _live_courant(self) -> str:
        """Identité du live en cours (son `started_at`), ou "" si inconnue."""
        if self._live_id is None:
            return ""
        try:
            return str(self._live_id() or "")
        except Exception as exc:  # noqa: BLE001 — une sonde cassée n'est pas fatale
            logger.debug("Apex watcher: identité du live indisponible: {e}", e=exc)
            return ""

    async def _load_baseline(self) -> dict[str, int]:
        """Le point de départ rangé, S'IL appartient bien au live en cours.

        Il était relu sans aucune vérification. Le format porte maintenant son
        live ; un enregistrement d'un autre live — ou de l'ancien format, plat et
        sans identité — est ignoré, et le premier passage repart de zéro.
        """
        if self._db is None:
            return {}
        try:
            raw = await self._db.get_state(BASELINE_KEY)
            data = json.loads(raw or "{}")
            if not isinstance(data, dict) or "stats" not in data:
                return {}      # ancien format plat : provenance inconnue, on jette
            attendu = self._live_courant()
            if str(data.get("live") or "") != attendu:
                logger.info("Apex watcher: point de départ d'un autre live, ignoré")
                return {}
            return {k: int(v) for k, v in (data.get("stats") or {}).items()}
        except Exception as exc:  # noqa: BLE001 — un départ illisible n'empêche pas de suivre
            logger.debug("Apex watcher: point de départ illisible: {e}", e=exc)
            return {}

    async def _store_baseline(self, baseline: dict[str, int]) -> None:
        if self._db is None:
            return
        try:
            await self._db.set_state(BASELINE_KEY, json.dumps(
                {"live": self._live_courant(), "stats": baseline}
            ))
        except Exception as exc:  # noqa: BLE001 — ne pas retenir n'est pas fatal
            logger.debug("Apex watcher: point de départ non rangé: {e}", e=exc)

    def progress(self) -> dict[str, int]:
        """Ce qui a bougé depuis le début du live. Vide tant qu'on n'a qu'un point."""
        if self._profile is None or not self._baseline:
            return {}
        gains = {}
        for notion, stat in self._profile.stats.items():
            depart = self._baseline.get(notion)
            if depart is not None and stat.value > depart:
                gains[notion] = stat.value - depart
        return gains

    def block(self) -> str | None:
        """Ce que Wally perçoit du jeu, en une ligne ou deux. None si rien."""
        p = self._profile
        if p is None:
            return None
        etat = "en partie" if p.in_game else (p.state or "hors ligne").lower()
        ligne = f"{p.name} est {etat}"
        if p.legend:
            ligne += f", sur {p.legend}"
        if p.rank:
            rang = p.rank.name + (f" {p.rank.div}" if p.rank.div else "")
            ligne += f" — {rang}, {p.rank.score} RP"
        lignes = ["--- Apex (perception passive) ---", ligne]
        gains = self.progress()
        if gains:
            libelles = {"kills": "kills", "wins": "victoires", "damage": "dégâts",
                        "revives": "réanimations", "headshots": "headshots",
                        "matches": "parties"}
            detail = ", ".join(
                f"+{v} {libelles.get(k, k)}" for k, v in gains.items()
            )
            lignes.append(f"Depuis le début du live : {detail}")
        return "\n".join(lignes)
