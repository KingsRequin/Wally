"""Wally en vocal pendant le live, et la vanne du tampon vocal.

Extrait de `bot/main.py`, où ces ~130 lignes vivaient en fonctions IMBRIQUÉES
dans un `main()` de 1071 lignes. Aucun test ne pouvait les atteindre : elles
n'existaient qu'à l'intérieur d'un appel à `main()`. Ce n'était pas un oubli,
c'était mécanique.

Ce que ça décidait, sans filet : **quand la captation vocale s'ouvre**. Le
tampon `VoiceTranscriptFeed` refuse tout ce qui n'est pas diffusé au live — la
confidentialité se joue à l'ÉCRITURE, et ce refus-là EST testé. Mais personne
ne testait le geste d'en face, `open_broadcast()` / `close_broadcast()`, alors
que c'est lui qui décide si une conversation vocale privée peut ressortir dans
le contexte écrit de Wally, sur Twitch.

Deux chemins mènent au même endroit, et c'est voulu :

  · `sur_transition()` — l'événement, quand le live bascule. Il ne se produit
    qu'UNE fois.
  · `veiller()` — le filet, toutes les 30 s. Après un redémarrage ou un crash
    en plein stream, aucune transition n'a lieu : sans lui, Wally resterait
    dehors tout le live, et la captation resterait fermée. Il compare l'état
    RÉEL du live à l'état RÉEL de la connexion, il ne suppose aucun événement.
    Il couvre donc aussi la déconnexion réseau et le kick.

`un_tour()` est séparé de `veiller()` exprès : une boucle `while True` avec un
`sleep(30)` dedans ne se teste pas, un tour se teste en une ligne.
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from bot.core.voice_transcript import VoiceTranscriptFeed

# Le rythme du filet. Assez court pour qu'un retour après crash ne coûte pas un
# quart de live, assez long pour ne pas marteler l'API Discord.
_PERIODE_S = 30.0

# En deçà, un retour en écoute s'explique par le redémarrage qui vient d'avoir
# lieu : aucune transition n'a été émise pendant que le bot était éteint, donc
# c'est au filet de le faire rentrer. C'est le fonctionnement NORMAL.
#
# Mesuré sur 7 jours : 27 des 31 retours suivaient un démarrage de moins de
# trois minutes — la plupart des rebuilds de l'owner. Les 4 autres sont le vrai
# signal, et ils étaient noyés dans les 27. Un log qui crie tout le temps ne dit
# plus rien.
_APRES_DEMARRAGE_S = 180.0


class PresenceDeStream:
    """Décide de la présence vocale de Wally pendant le live, et de la captation.

    Les dépendances sont explicites et non capturées : c'est tout l'objet de
    l'extraction. `stream_watcher` est posé APRÈS coup (`brancher_watcher`)
    parce qu'il se construit en prenant cette instance en paramètre — l'un des
    deux doit bien naître en premier.
    """

    def __init__(
        self,
        *,
        discord_bot: Any,
        db: Any,
        config: Any,
        voice_transcript: VoiceTranscriptFeed,
    ) -> None:
        self._bot = discord_bot
        self._db = db
        self._config = config
        self._transcript = voice_transcript
        self._watcher: Any = None
        # Référence forte : une tâche détachée peut être ramassée par le GC
        # avant la fin du join.
        self._taches: set[asyncio.Task] = set()
        self._premier_tour = True
        # L'instant de naissance de cet objet vaut celui du démarrage : il est
        # construit au boot, dans `main()`.
        self._ne_le = time.monotonic()

    def brancher_watcher(self, stream_watcher: Any) -> None:
        self._watcher = stream_watcher

    # ── le service vocal, résolu à chaque fois ───────────────────────────────
    #
    # Jamais gardé : il naît dans le `setup_hook` de Discord, donc APRÈS cet
    # objet, et il est remplacé à chaque reconnexion.
    def _service(self) -> Any:
        return getattr(self._bot, "voice_service", None)

    async def _salon(self) -> Any:
        """Le salon vocal du stream, VÉRIFIÉ présent.

        Celui retenu la veille peut avoir été supprimé (salon éphémère) : on
        retombe alors sur celui de la config. Un souvenir mort vaut absence.
        """
        from bot.discord.voice.channel_memory import resolve_voice_channel

        return await resolve_voice_channel(
            self._bot, self._db, self._config.bot.stream_voice_channel_id
        )

    # ── chemin 1 : la transition ─────────────────────────────────────────────

    def on_transition(self, old: dict, new: dict) -> None:
        """Point d'entrée synchrone du `StreamWatcher`. Lance le travail de fond.

        Séparé de `_on_stream_transition` (resté dans `main.py`) : celui-ci ne
        fait rien sans salon « chambre » configuré, et l'écoute n'a pas à en
        dépendre.
        """
        if self._service() is None:
            return
        monte = bool(new.get("live")) and not bool(old.get("live"))
        descend = bool(old.get("live")) and not bool(new.get("live"))
        if not (monte or descend):
            return
        t = asyncio.create_task(self.sur_transition(old, new))
        self._taches.add(t)
        t.add_done_callback(self._taches.discard)

    async def sur_transition(self, old: dict, new: dict) -> None:
        """Auto-join en écoute seule au début du live, retrait à la fin."""
        vs = self._service()
        if vs is None:
            return
        monte = bool(new.get("live")) and not bool(old.get("live"))
        descend = bool(old.get("live")) and not bool(new.get("live"))
        try:
            if monte:
                salon = await self._salon()
                # Le vocal de CE salon part désormais dans le live : il cesse
                # d'être privé, on peut le remettre au prompt. Ouvert AVANT le
                # retour anticipé ci-dessous — Wally est souvent déjà dans le
                # salon quand le live démarre, et l'ordre inverse laisserait la
                # captation fermée tout le live.
                self._transcript.open_broadcast(salon.id if salon else None)
                if vs.is_connected:
                    return          # déjà en vocal : on ne le déplace pas
                if salon is None:
                    logger.warning("voice: aucun salon de stream joignable")
                    return
                await vs.join(salon, listen_only=True, only_if_free=True)
            elif descend:
                # Le live s'arrête : le vocal redevient privé, et ce qui y a été
                # dit sort du contexte écrit.
                self._transcript.close_broadcast()
                if vs.is_connected and vs.listen_only:
                    # Seulement s'il est là POUR le stream : une conversation
                    # vocale en cours ne doit pas être coupée.
                    await vs.leave()
        except Exception as e:  # noqa: BLE001 — jamais bloquant
            logger.warning("voice: auto-join/leave du stream a échoué: {e!r}", e=e)

    # ── chemin 2 : le filet ──────────────────────────────────────────────────

    async def veiller(self, *, periode: float = _PERIODE_S) -> None:
        """Boucle sans fin. Toute la logique est dans `un_tour()`."""
        while True:
            await asyncio.sleep(periode)
            await self.un_tour()

    async def un_tour(self) -> None:
        """Un passage du filet. Ne lève jamais."""
        if self._premier_tour:
            self._premier_tour = False
            # UNE fois, en INFO. Hors live, ce filet ne laisse aucune trace :
            # `close_broadcast()` sur un tampon déjà fermé ne dit rien, et
            # `join()` n'est jamais appelé. On ne pouvait donc pas distinguer
            # « il tourne » de « la tâche est morte au premier tour » — et une
            # tâche asyncio qui lève meurt EN SILENCE. Une ligne au premier
            # passage suffit : au trentième redémarrage, elle est encore là.
            logger.info("voice: veilleur de stream armé (un tour toutes les {p:.0f} s)",
                        p=_PERIODE_S)
        try:
            vs = self._service()
            if vs is None:
                return
            statut = (getattr(self._watcher, "status", None) or {}) if self._watcher else {}
            if not bool(statut.get("live")):
                # Fin du live : il retrouve le droit de revenir au suivant.
                vs.listen_optout = False
                # Filet de la transition « fin de live » : elle ne se produit
                # qu'une fois, et un flux qui la rate laisserait la captation
                # ouverte sur un vocal redevenu privé.
                self._transcript.close_broadcast()
                return

            # Résolu AVANT le test de connexion : après un redémarrage en plein
            # stream, aucune transition n'a eu lieu, donc personne n'a ouvert la
            # captation — et Wally est peut-être déjà dans le salon, auquel cas
            # les deux tests suivants sortent d'ici.
            salon = await self._salon()
            self._transcript.open_broadcast(salon.id if salon else None)
            if vs.is_connected or vs.listen_optout:
                return
            if salon is None:
                return          # rien de joignable : déjà signalé par la résolution
            # DIRE POURQUOI. Après un redémarrage, c'est attendu — le filet
            # existe pour ça. Sans redémarrage, Wally est sorti d'un salon en
            # plein live sans que personne sache comment : ça mérite un
            # WARNING, et c'est ce qu'on veut pouvoir retrouver.
            depuis_demarrage = time.monotonic() - self._ne_le
            if depuis_demarrage <= _APRES_DEMARRAGE_S:
                logger.info("voice: retour en écoute après redémarrage "
                            "({d:.0f} s) — le filet a fait son travail",
                            d=depuis_demarrage)
            else:
                logger.warning("voice: Wally était SORTI du vocal en plein live, "
                               "sans redémarrage ({d:.0f} min de fonctionnement) "
                               "— retour en écoute",
                               d=depuis_demarrage / 60)
            await vs.join(salon, listen_only=True, only_if_free=True)
        except Exception as e:  # noqa: BLE001 — jamais bloquant
            logger.warning("voice: veilleur de stream en erreur: {e!r}", e=e)
