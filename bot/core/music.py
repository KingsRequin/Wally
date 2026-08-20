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
import re
import time
import uuid
from collections import deque
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from loguru import logger

# Ce qu'une action peut être. L'énuméré est ICI et non dans le prompt : l'action
# vient d'un modèle de langage, et un prompt n'est pas une barrière.
ACTIONS = frozenset({"play", "pause", "next", "prev", "play_query"})

# Celles qui s'adressent à un lecteur À L'ARRÊT : elles peuvent donc partir vers
# un onglet qui ne joue pas, contrairement aux autres (cf. `_servir`).
_REVEILLENT = frozenset({"play", "play_query"})

# Le titre et l'artiste viennent d'une page web — entrée non fiable — et
# finissent dans le chat Twitch et sur l'overlay.
_MAX_TEXTE = 200

# L'identifiant d'une vidéo YouTube : onze caractères, et ce jeu-là exactement.
# La borne est stricte À DESSEIN — l'url vient d'une page web, donc d'une entrée
# non fiable, et ce qu'on en tire part dans un `<img src>` sur l'overlay. On ne
# renvoie JAMAIS l'url reçue : seulement une adresse RECONSTRUITE à partir d'un
# identifiant qui a passé cette grille.
_ID_YOUTUBE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Les hôtes d'où un identifiant est accepté. Une liste blanche, pas un `in` sur
# la chaîne : « youtube.com.pirate.fr » contient « youtube.com ».
_HOTES_YOUTUBE = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be", "www.youtu.be",
})


def vignette(url: str) -> str:
    """L'adresse de la pochette du morceau, ou `""` si on ne sait pas.

    La chaîne vide et non une image par défaut : l'overlay sait afficher un
    disque neutre, et une pochette FAUSSE sur un morceau serait pire que pas de
    pochette du tout — c'est le chat qui la verrait en premier.

    `mqdefault` et non `hqdefault`, MESURÉ et non supposé : la seconde est en
    480 × 360, soit du 4:3, et YouTube y ajoute donc des bandes noires en haut
    et en bas — un quart du disque, qui est rond et recadre au centre. La
    première est en 320 × 180, le format natif, sans bande. `maxresdefault`
    serait plus fine encore mais n'existe pas sur toutes les vidéos et rend un
    404 ; 320 px suffisent à un disque de 58 px comme à en tirer la couleur
    dominante, qui se lit sur une réduction en 48 × 48.
    """
    url = str(url or "").strip()
    if not url:
        return ""
    try:
        decoupe = urlparse(url)
    except ValueError:
        return ""            # url illisible : on ne devine pas
    if decoupe.hostname not in _HOTES_YOUTUBE:
        return ""
    if decoupe.hostname in ("youtu.be", "www.youtu.be"):
        brut = decoupe.path.lstrip("/")
    else:
        brut = (parse_qs(decoupe.query).get("v") or [""])[0]
    if not _ID_YOUTUBE.match(brut):
        # Une page d'accueil, une playlist, une recherche : pas de vidéo, donc
        # pas de pochette. Rien à signaler, c'est le cas courant.
        return ""
    return f"https://i.ytimg.com/vi/{brut}/mqdefault.jpg"


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

    def __init__(self, horloge: Callable[[], float] | None = None,
                 on_morceau: Callable[[dict], None] | None = None) -> None:
        self._maintenant = horloge or time.monotonic
        # Prévenu quand Azraël CHANGE de morceau, jamais à chaque battement.
        # Un rappel plutôt qu'un narrateur : ce module ne connaît ni l'écran ni
        # le réseau, et c'est ce qui le garde testable sur des dictionnaires
        # nus. `main.py` y branche l'overlay.
        self._on_morceau = on_morceau
        self._etat: dict | None = None
        self._vu_a: float = 0.0
        self._file: deque[dict] = deque(maxlen=self.MAX_ORDRES)
        # Les ordres partis, en attente de leur accusé.
        self._attentes: dict[str, asyncio.Future] = {}

    def ecouter_les_morceaux(self, rappel: Callable[[dict], None] | None) -> None:
        """Branche (ou débranche) le rappel des changements de morceau.

        Existe pour le câblage TARDIF : l'overlay naît avec la connexion
        Discord, longtemps après ce service, et le construire plus tard
        donnerait deux instances — la panne silencieuse que ce module évite
        depuis le début.
        """
        self._on_morceau = rappel

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
            if self._etat is not None:
                logger.info("Musique : partage coupé côté extension")
            self._etat = None
            self._vu_a = 0.0
            return self._servir()

        nouveau = {
            "titre": str(titre or "")[:_MAX_TEXTE],
            "artiste": str(artiste or "")[:_MAX_TEXTE],
            "url": str(url or "")[:500],
            "joue": bool(joue),
        }
        self._signaler(nouveau)
        self._etat = nouveau
        self._vu_a = self._maintenant()
        return self._servir(joue=bool(joue))

    def _signaler(self, nouveau: dict) -> None:
        """Ce qui CHANGE, et rien d'autre : les logs, puis l'écran.

        Un battement toutes les deux secondes ne peut pas entrer dans les logs.
        Mais sans aucune trace, rien ne dit si l'extension parle : la question
        s'est posée en direct le 2026-08-19 — « ça marche pas » — sans qu'aucun
        log ne puisse y répondre, ni côté serveur ni côté chat. On note donc les
        transitions qui informent : le contact pris (ou repris après un
        silence), et le morceau qui change.

        Le rappel suit la même règle, et c'est ce qui le rend supportable à
        l'écran : trente battements par minute, une seule annonce par morceau.
        """
        muet = self._etat is None or self._maintenant() - self._vu_a > self.PERIME_S
        avant = self._etat or {}
        change = muet or (avant.get("titre"), avant.get("artiste")) != (
            nouveau["titre"], nouveau["artiste"])
        if not change:
            return

        morceau = f"{nouveau['artiste']} — {nouveau['titre']}".strip(" —")
        logger.info("Musique : {q} — {m}",
                    q="l'extension parle" if muet else "morceau",
                    m=morceau or "aucun lecteur sur cette page")

        # Une page sans lecteur n'est pas un morceau, et une vidéo à l'arrêt n'a
        # rien à faire à l'écran DE SON PROPRE CHEF : mettre en pause n'est pas
        # un geste à annoncer. Demandée dans le chat, elle s'affiche quand même
        # — c'est l'autre chemin, et il garde ses propres règles.
        if not self._on_morceau or not nouveau["titre"] or not nouveau["joue"]:
            return
        try:
            self._on_morceau(dict(nouveau))
        except Exception as exc:  # noqa: BLE001 — l'écran ne doit rien casser
            logger.warning("Musique : annonce à l'écran impossible : {e}", e=exc)

    def _servir(self, *, joue: bool = True) -> list[dict]:
        """Les ordres encore valables, retirés de la file.

        Retirés, donc remis UNE fois : deux onglets qui battent ne doivent pas
        faire sauter deux morceaux.

        `joue` est ce qui décide QUEL onglet obéit. Azraël peut avoir trois
        onglets YouTube ouverts ; « suivante » ne veut rien dire pour ceux qui
        dorment. Le filtre est ICI et non dans l'extension : là-bas, l'onglet
        qui reçoit l'ordre l'a déjà retiré de la file, et l'ignorer le perdrait
        pour tout le monde. En file, il attend simplement le bon onglet.

        Les deux actions qui RÉVEILLENT (`play`, `play_query`) font exception :
        elles s'adressent justement à un lecteur à l'arrêt.
        """
        maintenant = self._maintenant()
        sortis: list[dict] = []
        gardes: list[dict] = []
        while self._file:
            ordre = self._file.popleft()
            if maintenant - ordre["ne_a"] > self.ORDRE_TTL_S:
                self._resoudre(ordre["id"], {"ok": False,
                                             "raison": "ordre périmé, le lecteur n'a pas répondu à temps"})
                continue
            if not joue and ordre["action"] not in _REVEILLENT:
                gardes.append(ordre)
                continue
            sortis.append({"id": ordre["id"], "action": ordre["action"],
                           "query": ordre["query"]})
        self._file.extend(gardes)
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
        if not self._etat.get("titre"):
            # L'extension bat aussi sur une page SANS lecteur — accueil,
            # recherche, liste de lecture — pour se dire vivante. Un état sans
            # titre ne dit donc rien de ce qui passe : c'est « je ne sais pas »,
            # pas « en pause sur «  » ».
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
