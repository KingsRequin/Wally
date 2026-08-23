"""Un état « en cours » qui survit au redémarrage du process.

Les rebuilds sont FRÉQUENTS ici — cinq le 19/08 entre 20 h et 23 h, en plein
live. Tout ce qui vit en RAM meurt donc plusieurs fois par soirée : un bingo,
une partie de pendu, un cumul de kills, un pari ouvert. Le symptôme n'est jamais
« ça a planté », c'est « ça n'a pas marché » — le plus cher à diagnostiquer.

Trois modules avaient déjà écrit ce patron chacun de leur côté (l'overlay pour
le bingo/pendu/objectif, `DuelRunner`, le point de départ de progression Apex),
avec à chaque fois les mêmes pièges à repayer :

  · **Borner à la session.** Deux lives se suivent ; le cumul du précédent n'a
    rien à faire dans le suivant.
  · **Tolérer une session INCONNUE.** Au démarrage, le statut Twitch n'est pas
    encore revenu de son poll (60 s) : l'identité du live est vide des deux
    côtés. Sans repli sur l'âge, la reprise échouait précisément dans le cas
    qu'elle vise — le rebuild.
  · **Référence forte sur la tâche d'écriture.** La boucle asyncio n'en garde
    qu'une faible, et une tâche collectée en vol perd exactement l'écriture qui
    devait survivre au process.
  · **Ne jamais lever.** Un état non rangé dégrade ; une exception qui remonte
    dans une sonde ou un handler casse la fonctionnalité entière.

Le rangement va dans `bot_state` (SQLite), pas dans un fichier JSON à côté : la
base est déjà là, déjà montée en volume, déjà transactionnelle, et un fichier de
plus serait un fichier de plus à sauvegarder, à verrouiller et à réparer.

⚠️ **Ne JAMAIS y ranger un `time.monotonic()`.** Il repart de zéro à chaque
process : relu tel quel, il donne une durée écoulée absurde. Les délais se
rangent en temps MURAL (`time.time()`) et se reconvertissent à la reprise —
piège déjà payé sur l'uptime du bot.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from loguru import logger

# Au-delà, ce n'est plus un redémarrage mais un autre jour. Utilisé UNIQUEMENT
# quand la session n'est identifiable d'aucun côté : un rebuild se compte en
# secondes, un live précédent en heures.
AGE_MAX_DEFAUT_S = 6 * 3600


class EtatPersistant:
    """Une clé de `bot_state` qui porte un instantané JSON borné à une session.

    `session` rend ce qui identifie le contexte courant (le `started_at` du
    live, en pratique) ou `""` quand on ne le sait pas encore. `age_max_s` ne
    sert QUE dans ce dernier cas.
    """

    def __init__(self, db, cle: str, *, session: Callable[[], str],
                 horloge: Callable[[], float] = time.time,
                 age_max_s: float = AGE_MAX_DEFAUT_S) -> None:
        self._db = db
        self._cle = cle
        self._session = session
        self._horloge = horloge
        self._age_max = age_max_s
        self._taches: set[asyncio.Task] = set()

    # ── lecture ──────────────────────────────────────────────────────────

    def _session_courante(self) -> str:
        try:
            return str(self._session() or "")
        except Exception as exc:  # noqa: BLE001 — une sonde cassée ne ressuscite rien
            logger.debug("{c} : session indisponible : {e!r}", c=self._cle, e=exc)
            return ""

    def _meme_session(self, enveloppe: dict) -> bool:
        rangee = str(enveloppe.get("session") or "")
        courante = self._session_courante()
        if rangee and courante:
            return rangee == courante
        try:
            age = self._horloge() - float(enveloppe.get("range_a") or 0)
        except (TypeError, ValueError):
            return False
        return 0 <= age <= self._age_max

    async def charger(self) -> dict:
        """L'instantané rangé s'il appartient au contexte courant, `{}` sinon.

        Toujours un dict : l'appelant n'a jamais à distinguer « rien rangé » de
        « rangé mais périmé » — dans les deux cas il n'y a rien à reprendre.
        """
        if self._db is None:
            return {}
        try:
            brut = await self._db.get_state(self._cle)
        except Exception as exc:  # noqa: BLE001 — une base muette n'efface rien
            logger.warning("{c} : lecture impossible ({e!r})", c=self._cle, e=exc)
            return {}
        if not brut:
            return {}
        try:
            enveloppe = json.loads(brut)
        except (ValueError, TypeError) as exc:
            # Une écriture interrompue laisse du JSON tronqué. On le DIT : un
            # état perdu en silence se découvre des semaines plus tard.
            logger.warning("{c} : JSON illisible, état ignoré ({e!r})", c=self._cle, e=exc)
            return {}
        if not isinstance(enveloppe, dict) or not self._meme_session(enveloppe):
            return {}
        donnees = enveloppe.get("donnees")
        return donnees if isinstance(donnees, dict) else {}

    # ── écriture ─────────────────────────────────────────────────────────

    async def ranger(self, donnees: dict[str, Any]) -> None:
        """Range l'instantané. Ne lève jamais."""
        if self._db is None:
            return
        try:
            await self._db.set_state(self._cle, json.dumps(
                {"session": self._session_courante(),
                 "range_a": self._horloge(),
                 "donnees": donnees},
                ensure_ascii=False,
            ))
        except Exception as exc:  # noqa: BLE001 — un état non rangé n'est pas fatal
            logger.warning("{c} : écriture impossible ({e!r})", c=self._cle, e=exc)

    def ranger_bientot(self, donnees: dict[str, Any]) -> None:
        """Range sans attendre, depuis un chemin synchrone.

        La tâche est TENUE dans `self._taches` : la boucle asyncio ne garde
        qu'une référence faible, et une tâche ramassée en vol perdrait
        exactement l'écriture qui doit survivre au process.
        """
        if self._db is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return          # hors boucle (appel synchrone en test) : rien à ranger
        tache = loop.create_task(self.ranger(donnees))
        self._taches.add(tache)
        tache.add_done_callback(self._taches.discard)

    async def oublier(self) -> None:
        """Efface la clé. Ne lève jamais.

        `set_state(cle, None)` ne ferait PAS l'affaire : il range la chaîne
        « None », qui se relit comme une valeur.
        """
        if self._db is None:
            return
        try:
            await self._db.delete_state(self._cle)
        except Exception as exc:  # noqa: BLE001 — un oubli raté n'est pas fatal
            logger.warning("{c} : effacement impossible ({e!r})", c=self._cle, e=exc)
