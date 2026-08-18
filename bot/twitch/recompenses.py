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

from typing import Any

from loguru import logger


async def assurer_recompense(
    api: Any, db: Any, *, cle_etat: str, titre: str, cout: int, prompt: str,
    libelle: str = "récompense", saisie_requise: bool = True,
) -> str:
    """L'identifiant de notre récompense, créée si besoin. `""` si impossible.

    `cle_etat` est la clé de `bot_state` où vit l'identifiant : c'est le seul
    paramètre qui distingue deux récompenses, et il n'a pas de défaut — s'en
    passer ferait silencieusement partager la même à deux fonctionnalités.
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
                                     saisie_requise=saisie_requise)
            return str(connu)
        logger.warning("Récompense {l} {i} introuvable côté Twitch — on recrée",
                       l=libelle, i=connu)
    nouvel_id = await api.creer_recompense(titre, cout, prompt,
                                           saisie_requise=saisie_requise)
    if not nouvel_id:
        logger.error("Récompense {l} impossible à créer — fonction indisponible",
                     l=libelle)
        return ""
    await db.set_state(cle_etat, nouvel_id)
    logger.info("Récompense {l} prête ({i}, {c} points)", l=libelle, i=nouvel_id, c=cout)
    return str(nouvel_id)
