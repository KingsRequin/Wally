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

from bot.core.apex.reader import PlayerProfile

# Le point de départ du live, rangé en base : un rebuild d'image en pleine
# soirée remettait sinon la progression à zéro — et les rebuilds sont fréquents.
BASELINE_KEY = "apex:live_baseline"

# Le compte du streamer ne bouge pas plus vite que ça, et chaque passage coûte
# un appel : 90 s tient le rythme d'une partie sans marteler l'API.
POLL_INTERVAL_S = 90.0

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
        interval_s: float = POLL_INTERVAL_S,
        db=None,
        live_id: Callable[[], str] | None = None,
    ) -> None:
        self._service = service
        self._account = account
        self._is_live = is_live
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

    def activate(self) -> None:
        """S'enregistre comme source globale, lisible par `prompts.py`."""
        global _active
        _active = self

    async def tick(self) -> None:
        """Un passage : sonde le compte si un live tourne, sinon oublie tout."""
        if not self._account:
            return
        try:
            live = bool(self._is_live())
        except Exception as exc:  # noqa: BLE001 — sonde cassée = on se tait
            logger.debug("Apex watcher: état du live indisponible: {e}", e=exc)
            return
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
        try:
            profile = await self._service.fetch_profile(self._account[0], self._account[1])
        except Exception as exc:  # noqa: BLE001 — une panne d'API ne tue pas le suivi
            logger.debug("Apex watcher: profil indisponible: {e}", e=exc)
            return
        if profile is None:
            return
        self._profile = profile
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
            await asyncio.sleep(self._interval)

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
