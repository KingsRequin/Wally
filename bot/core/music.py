"""Ce que Wally sait de la musique d'Azraël, et ce qu'il peut en faire.

Azraël écoute sur YouTube dans un onglet de son navigateur. Une extension
Chrome, installée chez lui, envoie ici un **battement** régulier — ce qui passe —
et repart avec les **ordres en attente**. Un seul canal, dans les deux sens.

Pourquoi pas un flux SSE, qui aurait été le motif maison (`OverlayFeed`) : il
aurait fallu des tickets à usage unique (`EventSource` ne porte pas d'en-tête
`Authorization`), une route de flux, une politique CORS pour elle, et sa
reconnexion — le tout pour gagner une seconde de latence sur une action que
Wally met déjà plus longtemps à décider. La réponse au battement porte les
ordres : trois mécanismes en moins.

Ce module ne parle ni au réseau ni au LLM : il tient l'état et la file. C'est ce
qui le rend testable sur des dictionnaires nus, horloge comprise.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from collections.abc import Callable

from loguru import logger

# Ce qu'une action peut être. L'énuméré est ICI et non dans le prompt : l'action
# vient d'un modèle de langage, et un prompt n'est pas une barrière.
ACTIONS = frozenset({"play", "pause", "next", "prev", "play_query"})

# Le titre et l'artiste viennent d'une page web — entrée non fiable — et
# finissent dans le chat Twitch et sur l'overlay.
_MAX_TEXTE = 200


class MusicService:
    """L'état du lecteur d'Azraël, et la file d'ordres qui l'attend."""

    # Au-delà, on ne prétend plus savoir ce qui passe : c'est ce qui passait.
    # Large devant la période du battement (~2 s) pour tolérer un hoquet réseau
    # sans déclarer l'extension morte.
    PERIME_S = 45
    # Un ordre non pris passé ce délai est jeté. La musique est du temps réel :
    # « suivante » exécuté cinq minutes plus tard surprendrait tout le monde en
    # plein autre morceau.
    ORDRE_TTL_S = 10
    # Ce qu'on attend l'accusé avant de dire qu'on n'a pas pu. Arbitré avec
    # l'owner : deux secondes de silence sont déjà longues en direct.
    ACCUSE_TIMEOUT_S = 2.0
    # Un modo qui spamme « suivante » ne doit ni remplir la mémoire ni faire
    # défiler trente morceaux au retour de l'extension.
    MAX_ORDRES = 5

    def __init__(self, horloge: Callable[[], float] | None = None) -> None:
        self._maintenant = horloge or time.monotonic
        self._etat: dict | None = None
        self._vu_a: float = 0.0
        self._file: deque[dict] = deque(maxlen=self.MAX_ORDRES)
        # Les ordres partis, en attente de leur accusé.
        self._attentes: dict[str, asyncio.Future] = {}

    # ── côté extension ──────────────────────────────────────────────────────

    def battement(self, *, actif: bool, joue: bool, titre: str, artiste: str,
                  url: str, accuses: list[dict] | None = None) -> list[dict]:
        """Range l'état, referme les accusés, et rend les ordres en attente."""
        for accuse in accuses or []:
            self._accuser(accuse)

        if not actif:
            # L'extension voit TOUT ce qu'Azraël ouvre sur YouTube. Éteinte,
            # elle ne laisse rien ici : la confidentialité se joue à
            # l'écriture, pas à la lecture — un consommateur branché plus tard
            # trouverait sinon le titre d'une vidéo privée.
            self._etat = None
            self._vu_a = 0.0
            return self._servir()

        self._etat = {
            "titre": str(titre or "")[:_MAX_TEXTE],
            "artiste": str(artiste or "")[:_MAX_TEXTE],
            "url": str(url or "")[:500],
            "joue": bool(joue),
        }
        self._vu_a = self._maintenant()
        return self._servir()

    def _servir(self) -> list[dict]:
        """Les ordres encore valables, retirés de la file.

        Retirés, donc remis UNE fois : deux onglets qui battent, ou un battement
        rejoué, ne doivent pas faire sauter deux morceaux.
        """
        maintenant = self._maintenant()
        sortis: list[dict] = []
        while self._file:
            ordre = self._file.popleft()
            if maintenant - ordre["ne_a"] > self.ORDRE_TTL_S:
                self._resoudre(ordre["id"], {"ok": False,
                                             "raison": "ordre périmé, le lecteur n'a pas répondu à temps"})
                continue
            sortis.append({"id": ordre["id"], "action": ordre["action"],
                           "query": ordre["query"]})
        return sortis

    def _accuser(self, accuse: dict) -> None:
        if not isinstance(accuse, dict):
            return
        self._resoudre(str(accuse.get("id") or ""), {
            "ok": bool(accuse.get("ok")),
            "titre": str(accuse.get("titre") or "")[:_MAX_TEXTE],
            "raison": str(accuse.get("raison") or "")[:_MAX_TEXTE],
        })

    def _resoudre(self, ordre_id: str, resultat: dict) -> None:
        attente = self._attentes.pop(ordre_id, None)
        if attente is not None and not attente.done():
            attente.set_result(resultat)

    # ── côté bot ────────────────────────────────────────────────────────────

    def etat(self) -> dict | None:
        """Ce qui passe, ou `None` si on ne sait pas.

        `None` et non un dictionnaire vide : « je ne sais pas » et « rien ne
        joue » sont deux réponses opposées pour qui demande.
        """
        if self._etat is None:
            return None
        if self._maintenant() - self._vu_a > self.PERIME_S:
            return None
        return dict(self._etat)

    async def commander(self, action: str, query: str = "") -> dict:
        """Pose un ordre et ATTEND son accusé. Ne ment jamais sur le résultat.

        Sans accusé, c'est un échec — l'extension peut être éteinte, l'onglet
        fermé, le PC en veille. Annoncer « c'est fait » sans preuve est le
        travers qu'on corrige partout ailleurs dans ce bot.
        """
        action = str(action or "").strip()
        if action not in ACTIONS:
            return {"ok": False, "raison": f"action inconnue : {action or '(vide)'}"}
        query = str(query or "").strip()[:_MAX_TEXTE]
        if action == "play_query" and not query:
            return {"ok": False, "raison": "il manque le titre à lancer"}

        ordre_id = uuid.uuid4().hex[:12]
        attente: asyncio.Future = asyncio.get_running_loop().create_future()
        self._attentes[ordre_id] = attente
        # `deque(maxlen=…)` évince le plus ancien en silence : on le résout,
        # sinon son appelant attendrait deux secondes pour rien.
        if len(self._file) == self.MAX_ORDRES:
            evince = self._file[0]
            self._resoudre(evince["id"], {"ok": False,
                                          "raison": "trop d'ordres en attente"})
        self._file.append({"id": ordre_id, "action": action, "query": query,
                           "ne_a": self._maintenant()})

        try:
            return await asyncio.wait_for(attente, self.ACCUSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._attentes.pop(ordre_id, None)
            logger.info("Musique : ordre « {a} » sans accusé après {t} s",
                        a=action, t=self.ACCUSE_TIMEOUT_S)
            return {"ok": False,
                    "raison": "le lecteur d'Azraël n'a pas répondu"}
