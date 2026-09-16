"""Créer et tenir à jour une récompense de points de chaîne.

Extrait de `DuelRunner.assurer_recompense()`, qui en détenait la seule copie.
L'avalanche de memes en a besoin des mêmes garanties, et elles ne sont pas
évidentes — les recopier aurait été le plus sûr moyen de n'en corriger qu'une
moitié le jour où l'une bouge :

  · Twitch réserve le remboursement d'une redemption à l'application qui a CRÉÉ
    la récompense. Une récompense posée à la main dans la console est donc
    IRREMBOURSABLE par nous (403). C'est pourquoi Wally les crée lui-même, et
    pourquoi leur identifiant est découvert à l'exécution — jamais écrit en
    configuration.
  · On ne recrée JAMAIS sur un doute. Si la liste des récompenses gérables est
    indisponible (panne Twitch), on garde l'identifiant connu : le perdre
    rendrait irremboursable toute redemption en vol.
  · Une récompense retrouvée est mise à JOUR (titre, coût, invite), jamais
    recréée : une récompense recréée perd son historique.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger


async def assurer_recompense(
    api: Any, db: Any, *, cle_etat: str, titre: str, cout: int, prompt: str,
    libelle: str = "récompense", saisie_requise: bool = True,
    cooldown_s: int = 0,
) -> str:
    """L'identifiant de notre récompense, créée si besoin. `""` si impossible.

    `cle_etat` est la clé de `bot_state` où vit l'identifiant : c'est le seul
    paramètre qui distingue deux récompenses, et il n'a pas de défaut — s'en
    passer ferait silencieusement partager la même à deux fonctionnalités.

    `cooldown_s` voyage jusqu'à Twitch, à la création COMME à la mise à jour :
    les récompenses en service ont toutes été créées avant que ce réglage
    existe, et ne le poser qu'à la création ne l'aurait jamais appliqué à
    aucune d'elles.
    """
    connu = await db.get_state(cle_etat)
    if connu:
        gerables = await api.recompenses_gerables()
        if gerables is None:
            logger.warning(
                "Liste des récompenses gérables indisponible — on garde l'ID connu "
                "pour {l} ({i})", l=libelle, i=connu)
            return str(connu)
        actuelle = next((r for r in gerables if r.get("id") == connu), None)
        if actuelle is not None:
            # Une mise à jour ratée ne coûte que le libellé : la récompense
            # reste achetable et remboursable.
            await api.maj_recompense(connu, titre, cout, prompt, actuelle=actuelle,
                                     saisie_requise=saisie_requise,
                                     cooldown_s=cooldown_s)
            return str(connu)
        logger.warning("Récompense {l} {i} introuvable côté Twitch — on recrée",
                       l=libelle, i=connu)
    nouvel_id = await api.creer_recompense(titre, cout, prompt,
                                           saisie_requise=saisie_requise,
                                           cooldown_s=cooldown_s)
    if not nouvel_id:
        logger.error("Récompense {l} impossible à créer — fonction indisponible",
                     l=libelle)
        return ""
    await db.set_state(cle_etat, nouvel_id)
    logger.info("Récompense {l} prête ({i}, {c} points)", l=libelle, i=nouvel_id, c=cout)
    return str(nouvel_id)


# ── Le registre : ce que chaque récompense EST, côté code ────────────────────


@dataclass(frozen=True)
class Definition:
    """Ce qui ne se règle pas depuis le panneau : c'est le code qui en dépend.

    `cle_etat` est la clé `bot_state` de l'identifiant Twitch — c'est elle que
    lit le gestionnaire d'achat (`events/redemptions.py`). `saisie_requise`
    dit si le gestionnaire LIT un texte : l'ôter à une récompense qui en attend
    un la ferait rembourser à chaque achat.
    """

    cle_etat: str
    libelle: str
    saisie_requise: bool


def _definitions() -> dict[str, Definition]:
    # Les clés d'état sont IMPORTÉES de leurs modules, jamais recopiées : c'est
    # la même chaîne qui écrit l'identifiant ici et qui le relit à l'achat.
    from bot.core.apex.duel_runner import CLE_RECOMPENSE as CLE_DUEL
    from bot.twitch.events.humeur import CLE_50, CLE_100
    from bot.twitch.events.tts_viewer import CLE_RECOMPENSE as CLE_TTS
    from bot.twitch.events.virus_popups import CLE_RECOMPENSE as CLE_VIRUS

    return {
        "tts_viewer": Definition(CLE_TTS, "TTS viewer", True),
        "humeur_50": Definition(CLE_50, "Humeur 50 %", True),
        "humeur_100": Definition(CLE_100, "Humeur 100 %", True),
        "attaque_meme": Definition(CLE_VIRUS, "Attaque de meme", False),
        "duel_apex": Definition(CLE_DUEL, "Duel Apex", True),
    }


DEFINITIONS: dict[str, Definition] = _definitions()

# L'arrondi du prix dynamique : un prix à 537 points se lit comme un bug.
PAS_DE_PRIX = 10


class PrixDynamique:
    """La « chauffe » du TTS : +1 par achat entendu, fond de moitié par demi-vie.

    Persistée (`bot_state`) avec son instant, pour qu'un rebuild en plein rush
    ne remette pas le prix à la base. `time.time()` et non `monotonic()` : une
    horloge monotone repart de zéro au redémarrage.
    """

    CLE_ETAT = "voice:tts_viewer_chauffe"

    def __init__(self, db: Any, config: Any, *, horloge=time.time) -> None:
        self._db = db
        self._config = config
        self._horloge = horloge
        self._chauffe = 0.0
        self._instant = horloge()

    async def charger(self) -> None:
        brut = await self._db.get_state(self.CLE_ETAT)
        if not brut:
            return
        try:
            donnees = json.loads(brut)
            self._chauffe = float(donnees["chauffe"])
            self._instant = float(donnees["instant"])
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Prix dynamique du TTS : chauffe illisible, repart de "
                           "zéro : {e!r}", e=exc)

    def chauffe(self) -> float:
        demi_vie_s = max(float(self._config.twitch.prix_dynamique_tts.demi_vie_minutes),
                         0.01) * 60
        ecoule = max(0.0, self._horloge() - self._instant)
        return self._chauffe * 0.5 ** (ecoule / demi_vie_s)

    def prix(self) -> int | None:
        """Le prix courant, `None` si le TTS n'a pas de configuration."""
        rc = self._config.twitch.recompenses.get("tts_viewer")
        if rc is None:
            return None
        base = max(1, int(rc.cout))
        hausse = float(self._config.twitch.prix_dynamique_tts.hausse_pct) / 100
        extra = round(base * hausse * self.chauffe() / PAS_DE_PRIX) * PAS_DE_PRIX
        return base + max(0, int(extra))

    async def ajouter_achat(self) -> None:
        maintenant = self._horloge()
        self._chauffe = self.chauffe() + 1
        self._instant = maintenant
        await self._db.set_state(self.CLE_ETAT, json.dumps(
            {"chauffe": self._chauffe, "instant": self._instant}))


class GestionRecompenses:
    """Crée, met à jour et supprime les récompenses — au boot comme à chaud.

    Le panneau admin passe par ici : un prix modifié part chez Twitch dans la
    seconde, sans redémarrage. `duel_runner` est relu à chaque appel : le duel
    est câblé pendant le démarrage, et peut ne jamais l'être (Apex absent).
    """

    CADENCE_PRIX_S = 60

    def __init__(self, api: Any, db: Any, config: Any, *,
                 duel_runner: Callable[[], Any] = lambda: None) -> None:
        self._api = api
        self._db = db
        self._config = config
        self._duel_runner = duel_runner
        self.prix_tts = PrixDynamique(db, config)
        self._prix_pousse: int | None = None
        self._verrou_prix = asyncio.Lock()

    def _conf(self, cle: str) -> Any:
        return self._config.twitch.recompenses.get(cle)

    def cout_effectif(self, cle: str) -> int:
        if cle == "tts_viewer":
            prix = self.prix_tts.prix()
            if prix is not None:
                return prix
        return int(self._conf(cle).cout)

    async def appliquer(self, cle: str) -> str:
        """Crée ou aligne la récompense sur sa configuration. `""` si impossible."""
        rc, d = self._conf(cle), DEFINITIONS[cle]
        if rc is None or not rc.active:
            return ""
        cout = self.cout_effectif(cle)
        runner = self._duel_runner() if cle == "duel_apex" else None
        if runner is not None:
            # Par le runner : c'est lui qui tient l'identifiant lu à l'achat.
            reward_id = await runner.assurer_recompense(
                rc.titre, cout, rc.prompt, cooldown_s=int(rc.recharge_s))
        else:
            reward_id = await assurer_recompense(
                self._api, self._db, cle_etat=d.cle_etat, titre=rc.titre,
                cout=cout, prompt=rc.prompt, libelle=d.libelle,
                saisie_requise=d.saisie_requise, cooldown_s=int(rc.recharge_s))
        if cle == "tts_viewer" and reward_id:
            self._prix_pousse = cout
        return reward_id

    async def armer_au_boot(self) -> None:
        """Toutes sauf le duel, armé à part dans l'ordre de `armer_le_duel`."""
        await self.prix_tts.charger()
        for cle, d in DEFINITIONS.items():
            if cle == "duel_apex":
                continue
            rc = self._conf(cle)
            if rc is None:
                logger.error("Récompense {l} non armée : aucune entrée "
                             "twitch.recompenses.{c} dans config.yaml", l=d.libelle, c=cle)
                continue
            if not rc.active:
                logger.info("Récompense {l} non armée : supprimée depuis le panneau",
                            l=d.libelle)
                continue
            try:
                reward_id = await self.appliquer(cle)
                logger.info("Récompense {l} armée ({r})", l=d.libelle,
                            r=reward_id or "INDISPONIBLE")
            except Exception as exc:  # noqa: BLE001 — jamais bloquant pour le boot
                logger.error("Récompense {l} non armée : {e!r}", l=d.libelle, e=exc)

    async def supprimer(self, cle: str) -> bool:
        """Supprime de la chaîne ET empêche la recréation au prochain boot."""
        d = DEFINITIONS[cle]
        reward_id = str(await self._db.get_state(d.cle_etat) or "")
        if not await self._api.supprimer_recompense(reward_id):
            return False
        await self._db.set_state(d.cle_etat, "")
        rc = self._conf(cle)
        if rc is not None:
            rc.active = False
            self._config.save()
        if cle == "tts_viewer":
            self._prix_pousse = None
        return True

    async def lister(self) -> list[dict]:
        gerables = await self._api.recompenses_gerables()
        par_id = {r.get("id"): r for r in (gerables or [])}
        lignes = []
        for cle, d in DEFINITIONS.items():
            rc = self._conf(cle)
            reward_id = str(await self._db.get_state(d.cle_etat) or "")
            twitch = par_id.get(reward_id) if reward_id else None
            ligne = {
                "cle": cle, "libelle": d.libelle, "configuree": rc is not None,
                "active": bool(rc and rc.active),
                "titre": rc.titre if rc else "", "cout": int(rc.cout) if rc else 0,
                "prompt": rc.prompt if rc else "",
                "recharge_s": int(rc.recharge_s) if rc else 0,
                "saisie_requise": d.saisie_requise,
                "reward_id": reward_id,
                # `None` = liste Twitch illisible : on ne sait pas, ce n'est pas « absente ».
                "sur_twitch": None if gerables is None else twitch is not None,
                "cout_twitch": twitch.get("cost") if twitch else None,
            }
            if cle == "tts_viewer":
                ligne["prix_courant"] = self.prix_tts.prix()
                ligne["chauffe"] = round(self.prix_tts.chauffe(), 3)
            lignes.append(ligne)
        return lignes

    async def pousser_prix_tts(self) -> int | None:
        """Envoie le prix courant du TTS à Twitch s'il a bougé. Rend le prix en ligne."""
        async with self._verrou_prix:
            rc = self._conf("tts_viewer")
            if rc is None or not rc.active:
                return None
            reward_id = str(await self._db.get_state(DEFINITIONS["tts_viewer"].cle_etat)
                            or "")
            prix = self.prix_tts.prix()
            if not reward_id or prix is None:
                return None
            if prix == self._prix_pousse:
                return prix
            if await self._api.maj_recompense(
                    reward_id, rc.titre, prix, rc.prompt, saisie_requise=True,
                    cooldown_s=int(rc.recharge_s)):
                logger.info("Prix du TTS : {a} → {p} points", a=self._prix_pousse, p=prix)
                self._prix_pousse = prix
                return prix
            # Rien n'est retenu : le prochain tour retentera.
            return self._prix_pousse

    async def apres_achat_tts(self) -> tuple[int | None, int | None]:
        """(prix avant, prix après) — appelé quand un TTS a VRAIMENT été entendu."""
        avant = self._prix_pousse
        await self.prix_tts.ajouter_achat()
        return avant, await self.pousser_prix_tts()

    async def boucle_prix(self, *, sleep=asyncio.sleep) -> None:
        """Fait redescendre le prix du TTS à mesure que la chauffe fond."""
        while True:
            await sleep(self.CADENCE_PRIX_S)
            try:
                await self.pousser_prix_tts()
            except Exception as exc:  # noqa: BLE001 — la boucle ne meurt jamais
                logger.error("Prix dynamique du TTS en erreur : {e!r}", e=exc)
