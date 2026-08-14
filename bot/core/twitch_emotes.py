# bot/core/twitch_emotes.py
"""Les emotes que Wally peut RÉELLEMENT écrire dans le chat de la chaîne.

Un spectateur s'en est plaint en direct le 2026-08-13, et sa plainte disait
exactement le problème :

    20:14:29  Wally : « C'est parti, mème à l'écran ! 😄 »
    20:14:47  clakernojutsu : « Il m'agace avec ses "😄" LUL »

Il reproche un emoji Unicode **en écrivant `LUL`**. Ce n'est donc pas
l'expressivité qui gêne, c'est le REGISTRE : Wally écrit comme sur WhatsApp
dans un chat qui parle en emotes Twitch.

## Pourquoi une liste ne peut pas être écrite en dur

Deux raisons, et la seconde est la plus coûteuse :

1. Le vocabulaire d'une communauté bouge — une liste figée aujourd'hui sera
   fausse dans six mois.
2. **Une emote qu'on n'a pas le droit d'écrire s'affiche en toutes lettres.**
   Sur les 27 emotes de la chaîne, 26 sont réservées aux abonnés et une aux
   followers ; le compte du bot n'est pas abonné. Lui souffler `azrael74HYPE`
   le ferait écrire « azrael74HYPE » en clair dans le chat — pire que l'emoji.

Le registre se construit donc en croisant deux sources, et rien d'autre :

* **Ce qu'il a le DROIT d'écrire** — l'API Twitch. Les 304 emotes globales sont
  ouvertes à tout le monde ; les emotes de chaîne ne sont retenues que si
  `/helix/chat/emotes/user` confirme que le compte du bot y a droit (cf.
  `TwitchAPI.get_entitled_channel_emotes`). Le jour où Azraël offre un
  abonnement au bot, les `azrael74*` entrent toutes seules.
* **Ce qui VIT sur cette chaîne** — le chat lui-même. Un mot du chat compte
  comme emote quand il est EXACTEMENT dans la liste vérifiée, et pas autrement.
  Ce filtre fait tout le travail de sécurité : `azrael74DANCE` (40 occurrences)
  et `sharpy19Smilepepega` sont vus mais jamais proposés.

  On n'emploie PAS ici le tamis de forme des vagues d'emotes
  (`emote_wave._looks_like_emote`, qui exige une majuscule ailleurs qu'en tête) :
  il rejette 72 des 304 globales, dont `Kappa` — 128 emplois en sept jours, la
  plus utilisée du chat — ainsi que `Keepo`, `Kreygasm`, `Jebaited`, `:D` et
  `<3`. L'appartenance exacte à la liste vérifiée est à la fois plus stricte et
  plus complète : si un mot est écrit comme une emote existante, Twitch
  l'affiche comme cette emote — c'est la définition même de ce qu'on compte.

Le prompt ne reçoit qu'une poignée des plus employées — 304 emotes en contexte
seraient absurdes, et un modèle noyé sous un catalogue n'en retient aucune.

## Ce qu'on ne dit PAS au modèle

Le sens de chaque emote n'est écrit nulle part ici. Les globales Twitch (`LUL`,
`KonCha`, `HeyGuys`, `SeemsGood`, `NotLikeThis`) sont documentées et connues du
modèle ; écrire « LUL = rire » à la main serait exactement la valeur en dur que
ce module existe pour éviter, et ce serait faux le jour où l'usage local
détourne une emote. Le bloc lui demande donc simplement de ne pas employer
celles dont il ignore le sens.

## Panne d'API

`set_verified(None)` — l'API n'a pas répondu — **conserve** le registre
précédent au lieu de l'effacer : une coupure réseau ne doit pas faire retomber
Wally aux emojis. Registre vide = aucun bloc, zéro jeton, et surtout aucune
emote proposée : jamais d'invention.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from loguru import logger

# Combien d'emotes partent au prompt. Une poignée de celles qui servent, pas un
# catalogue : au-delà, la consigne devient une liste de courses (même raison que
# `_RESSASSAGE_MAX` dans `thread_sense`).
MAX_PROPOSEES = 8

# Fenêtre relue au démarrage dans les journaux de conversation. Le process est
# reconstruit presque tous les jours : sans amorçage, chaque redémarrage repartait
# d'un compteur vide et Wally n'avait aucune emote à proposer pendant la première
# demi-heure de live — soit exactement le moment où le chat en emploie le plus.
SEED_DAYS = 7


class EmoteRegistry:
    """Ce que Wally peut écrire, ordonné par ce que le chat emploie vraiment."""

    def __init__(self, max_proposees: int = MAX_PROPOSEES) -> None:
        self._max = max_proposees
        # Emotes dont on a la PREUVE qu'il peut les envoyer. Vide par défaut :
        # sans preuve, on ne propose rien.
        self._verified: set[str] = set()
        # Emotes vérifiées vues passer dans le chat → nombre d'occurrences.
        self._counts: Counter = Counter()

    # ------------------------------------------------------------------
    # Ce qu'il a le droit d'écrire
    # ------------------------------------------------------------------

    def set_verified(self, names: Optional[Iterable[str]]) -> None:
        """Remplace la liste des emotes autorisées. `None` = API muette, on garde.

        Les compteurs sont refiltrés : une emote qui sort du registre (fin
        d'abonnement) ne doit pas continuer d'être proposée par son historique.
        """
        if names is None:
            logger.warning(
                "Emotes : registre inchangé ({n} connue(s)) — l'API n'a pas répondu",
                n=len(self._verified),
            )
            return
        nouveau = {str(n).strip() for n in names if str(n).strip()}
        if nouveau == self._verified:
            return
        self._verified = nouveau
        self._counts = Counter({
            nom: compte for nom, compte in self._counts.items() if nom in nouveau
        })
        logger.info("Emotes : {n} utilisable(s) par le bot", n=len(nouveau))

    @property
    def verified(self) -> set[str]:
        return set(self._verified)

    def knows(self, name: str) -> bool:
        """Vrai si cette emote existe et que le bot a le droit de l'écrire.

        Sans copie du registre : appelé sur chaque mot de chaque ligne de chat
        par le détecteur de vagues.
        """
        return name in self._verified

    # ------------------------------------------------------------------
    # Ce qui vit dans le chat
    # ------------------------------------------------------------------

    def note_chat(self, text: str) -> None:
        """Compte les emotes VÉRIFIÉES d'une ligne de chat. Une par ligne et par nom.

        Comptée une seule fois par ligne : « LUL LUL LUL LUL » est UNE personne
        qui rit fort, pas quatre emplois. Sans ça, un seul spammeur décidait de
        tout le classement — c'est le même raisonnement que les vagues
        d'emotes, qui comptent des personnes et non des messages.
        """
        if not self._verified:
            return
        for token in set((text or "").split()):
            if token in self._verified:
                self._counts[token] += 1

    def top(self, limit: Optional[int] = None) -> list[str]:
        """Les emotes les plus employées ici, de la plus fréquente à la moins."""
        limite = self._max if limit is None else limit
        classe = sorted(self._counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [nom for nom, _ in classe[:max(0, limite)]]

    # ------------------------------------------------------------------
    # Amorçage depuis les journaux
    # ------------------------------------------------------------------

    def seed_from_logs(self, root, days: int = SEED_DAYS) -> int:
        """Relit les derniers jours de chat Twitch journalisé. Rend le nombre de lignes.

        Bloquant (lecture disque) : à appeler dans un `asyncio.to_thread`. Ne
        lève jamais — un amorçage raté laisse simplement le compteur à zéro.
        """
        if not self._verified:
            return 0
        base = Path(root) / "twitch"
        lignes = 0
        try:
            fichiers = sorted(base.glob("*/*.jsonl"))[-max(1, days) * 8:]
        except Exception as exc:  # noqa: BLE001 — un amorçage ne casse pas le boot
            logger.warning("Emotes : journaux illisibles ({e})", e=exc)
            return 0
        for chemin in fichiers:
            try:
                with open(chemin, encoding="utf-8") as f:
                    for ligne in f:
                        try:
                            event = json.loads(ligne)
                        except Exception:  # noqa: BLE001 — ligne tronquée
                            continue
                        if event.get("type") != "message_in":
                            continue
                        self.note_chat(str(event.get("content") or ""))
                        lignes += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("Emotes : {f} non relu ({e})", f=chemin, e=exc)
        logger.info(
            "Emotes : amorcées sur {n} ligne(s) de chat — {top}",
            n=lignes, top=", ".join(self.top()) or "aucune",
        )
        return lignes

    # ------------------------------------------------------------------
    # Rendu
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Le bloc de prompt, ou "" s'il n'a aucune emote sûre à proposer."""
        proposees = self.top()
        if not proposees:
            return ""
        return (
            "\n--- Les emotes de ce chat ---\n"
            "Tu écris dans un chat Twitch : ici on réagit avec des emotes, pas "
            "avec les emojis d'un clavier de téléphone.\n"
            "Celles-ci tournent vraiment dans ce chat ET ton compte a le droit "
            "de les écrire, exactement sous cette forme, majuscules comprises : "
            + ", ".join(proposees) + ".\n"
            "N'en écris JAMAIS une autre, même vue passer à l'instant : hors de "
            "ta portée, elle s'affiche en toutes lettres et te ridiculise. Si tu "
            "ne sais pas ce qu'une emote de cette liste exprime, ne l'emploie "
            "pas. Une emote s'écrit isolée, séparée du reste par une espace. "
            "Rien ne t'oblige à en mettre."
        )


# Instance de processus. Même choix que `self_trace` et `audit_log._RECEPTION` :
# le registre n'a pas de propriétaire naturel — le bot Twitch l'alimente, le
# constructeur de prompt le lit — et le faire descendre par injection
# demanderait de le câbler dans autant de constructeurs pour la même donnée.
_REGISTRE = EmoteRegistry()


def active_emote_registry() -> EmoteRegistry:
    """Le registre du processus."""
    return _REGISTRE


def reset_emotes() -> None:
    """Vide le registre (tests)."""
    _REGISTRE._verified = set()
    _REGISTRE._counts = Counter()


def note_chat_emotes(text: str) -> None:
    """Compte les emotes d'une ligne de chat. **Ne lève jamais.**"""
    try:
        _REGISTRE.note_chat(text)
    except Exception as exc:  # noqa: BLE001 — un compteur ne casse pas le chat
        logger.debug("Emotes : ligne non comptée ({e})", e=exc)


def current_emote_block() -> Optional[str]:
    """Bloc prêt à injecter dans un prompt TWITCH, ou None. Ne lève jamais.

    Réservé au chat Twitch : une emote Twitch écrite sur Discord, dans une bulle
    d'overlay ou à l'oral n'est qu'un mot bizarre.
    """
    try:
        return _REGISTRE.render() or None
    except Exception as exc:  # noqa: BLE001 — un bloc de contexte ne casse pas un prompt
        logger.debug("Emotes : bloc illisible ({e})", e=exc)
        return None


async def refresh_from_api(api) -> None:
    """Recharge le registre depuis l'API Twitch. **Ne lève jamais.**

    Les globales sont la base sûre ; les emotes de chaîne ne s'y ajoutent que si
    Twitch confirme que le compte du bot y a droit. Si les globales manquent, on
    ne touche à rien : mieux vaut un registre périmé qu'un registre vide.
    """
    try:
        globales = await api.get_global_emotes()
        if globales is None:
            _REGISTRE.set_verified(None)
            return
        chaine = await api.get_entitled_channel_emotes()
        if chaine:
            logger.info("Emotes : {n} emote(s) de chaîne ouverte(s) au bot", n=len(chaine))
        _REGISTRE.set_verified([*globales, *(chaine or [])])
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("Emotes : rafraîchissement impossible ({e})", e=exc)
