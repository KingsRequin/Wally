# bot/twitch/events/redemptions.py
"""Achat d'une récompense de points de chaîne → ouverture d'un duel Apex.

Perception passive comme tout événement de stream ici : on alimente le flux
(`stream_feed`), on ne réveille aucune cadence de parole (`notify_*` absent
volontairement — le `feed.record()` en dessous n'en fait pas partie, il ne
touche que l'observateur de l'overlay).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


def _feed(bot, description: str) -> None:
    """Inscrit l'achat dans le flux passif (best-effort).

    Import inline plutôt que `from bot.twitch.events.social import _feed` :
    `social.py` importe déjà ce module (pour enregistrer le handler
    EventSub) — importer dans l'autre sens créerait un cycle. `getattr`
    reste donc la façon la plus simple de rester indépendant de social.py.
    """
    feed = getattr(bot, "stream_feed", None)
    if feed is None:
        return
    try:
        feed.record(description, kind="duel_redemption")
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("StreamFeed: enregistrement échoué : {e}", e=exc)


async def _dire(bot, acheteur: str, texte: str) -> None:
    """Un mot dans le chat à celui qui a payé, en direct et SANS le modèle.

    Ces deux chemins existent justement quand la machinerie du duel n'est pas
    disponible : le canal d'annonce du runner (`DuelAnnonceur`, avec sa
    rédaction LLM) n'est pas joignable ici, et un appel au modèle serait de
    toute façon la dernière chose à tenter dans un état dégradé. Le bot Twitch,
    lui, sait toujours envoyer un message — c'est ce que font les handlers
    d'événements sociaux.

    Sans ça, le viewer voyait ses points revenir sans un mot d'explication.
    Et la récompense reste achetable en permanence : rien ne la désactive, et
    elle est toujours reconnue via l'identifiant persisté.
    """
    # `acheteur` vaut « ? » quand l'événement ne porte pas de pseudo : mieux
    # vaut un message sans mention qu'un « @? » adressé à personne.
    mention = f"@{acheteur} " if acheteur and acheteur != "?" else ""
    try:
        await bot.twitch_api.send_message(text=f"{mention}{texte}")
    except Exception as exc:  # noqa: BLE001 — le remboursement est déjà fait
        logger.error("Duel : refus non annoncé dans le chat : {e}", e=exc)


def _rendus_ou_pas(rendu: bool, redemption_id: str, motif: str) -> str:
    """Le message du viewer, selon que Twitch a VRAIMENT rendu les points.

    `refund_redemption()` lit le corps de la réponse Helix et rend un booléen ;
    ces deux chemins l'ignoraient et affirmaient « tes points t'ont été rendus »
    quoi qu'il arrive. Un 403 (récompense créée hors de notre application),
    un scope perdu ou une redemption déjà soldée produisaient donc un mensonge
    en direct, avec pour seule trace une ligne de log.
    """
    if rendu:
        return f"{motif} — tes points t'ont été rendus."
    logger.error(
        "Duel Apex : REMBOURSEMENT REFUSÉ par Twitch (redemption {i}) — les "
        "points du viewer ne sont pas revenus, il faut les rendre à la main",
        i=redemption_id or "?")
    return (f"{motif}, et je n'ai pas réussi à te rendre tes points — préviens "
            "le streamer, il n'y a que lui qui puisse te les rendre à la main.")


async def _est_notre_recompense(bot, reward_id: str) -> bool:
    """La récompense créée par Wally lui-même, identifiée par son ID.

    Jamais par son titre : un titre se renomme d'un clic dans la console Twitch
    et le duel cesserait de répondre sans un mot dans les logs.

    Jamais par la config non plus : Twitch réserve le remboursement d'une
    redemption à l'application qui a CRÉÉ la récompense, donc c'est Wally qui
    la crée au démarrage — son ID est découvert à l'exécution et vit sur
    `bot.duel_runner._reward_id`, jamais dans `config.yaml`.

    `bot.duel_runner` peut être absent (Apex indisponible au boot, ou pas
    encore câblé) : on retombe alors sur l'ID persisté dans `bot_state`
    (`apex:duel_reward_id`, écrit par `DuelRunner.assurer_recompense`). SANS ce
    repli, un achat pendant que le runner est down ne serait jamais reconnu
    comme « notre » récompense — cette fonction rendrait `False` avant même que
    `handle_redemption` puisse atteindre sa branche « runner absent » et
    rembourser. Le viewer paierait pour rien.

    Un `reward_id` vide (aucune des deux sources connue) DÉSACTIVE le duel —
    sans ce garde, la moindre récompense de la chaîne en lancerait un.
    """
    runner = getattr(bot, "duel_runner", None)
    attendu = str(getattr(runner, "_reward_id", "") or "")
    if not attendu:
        db = getattr(bot, "db", None)
        if db is not None:
            try:
                attendu = str(await db.get_state("apex:duel_reward_id") or "")
            except Exception as exc:  # noqa: BLE001 — un repli ne casse jamais le filtrage
                logger.debug("Repli reward_id persistée indisponible : {e}", e=exc)
    return bool(attendu) and str(reward_id) == attendu


async def _est_le_spam_virus(bot, reward_id: str) -> bool:
    """La récompense « Attaque de virus », reconnue par son ID persisté.

    Même principe que pour le duel, et pour la même raison : Twitch ne laisse
    rembourser qu'à l'application qui a CRÉÉ la récompense, donc son ID est
    découvert à l'exécution. Un ID vide DÉSACTIVE le spam — sans ce garde,
    n'importe quelle récompense de la chaîne le déclencherait.
    """
    from bot.twitch.events.virus_popups import CLE_RECOMPENSE

    db = getattr(bot, "db", None)
    if db is None:
        return False
    try:
        attendu = str(await db.get_state(CLE_RECOMPENSE) or "")
    except Exception as exc:  # noqa: BLE001 — un filtrage ne casse jamais l'événement
        logger.debug("Spam de virus : ID persisté illisible : {e}", e=exc)
        return False
    return bool(attendu) and str(reward_id) == attendu


async def _est_une_humeur(bot, reward_id: str) -> float | None:
    """L'intensité voulue si c'est une de NOS deux récompenses d'humeur.

    `None` sinon — et un ID vide DÉSACTIVE, comme partout ailleurs : sans ce
    garde, n'importe quelle récompense de la chaîne forcerait une humeur.
    """
    from bot.twitch.events.humeur import CLE_100, CLE_50

    db = getattr(bot, "db", None)
    if db is None or not reward_id:
        return None
    for cle, intensite in ((CLE_50, 0.5), (CLE_100, 1.0)):
        try:
            attendu = str(await db.get_state(cle) or "")
        except Exception as exc:  # noqa: BLE001 — un filtrage ne casse pas l'événement
            logger.debug("Humeur : ID persisté illisible : {e}", e=exc)
            continue
        if attendu and str(reward_id) == attendu:
            return intensite
    return None


async def handle_redemption(bot: "WallyTwitch", event) -> None:
    """Point d'entrée EventSub. N'échoue jamais vers l'appelant."""
    reward_id = ""
    redemption_id = ""
    acheteur = ""
    try:
        reward_id = str(getattr(getattr(event, "reward", None), "id", ""))
        # Le spam AVANT le duel : deux récompenses distinctes arrivent par
        # le même événement, et chacune doit reconnaître la sienne.
        intensite = await _est_une_humeur(bot, reward_id)
        if intensite is not None:
            from bot.twitch.events.humeur import forcer_humeur

            await forcer_humeur(
                bot,
                acheteur=str(getattr(getattr(event, "user", None), "name", "") or "?"),
                # Le texte saisi par le viewer : c'est lui qui dit l'émotion.
                # `input`, comme le duel plus bas — c'est le nom de l'ATTRIBUT
                # chez twitchio. `user_input` est celui du champ dans le JSON
                # de Twitch, et il ne survit pas au modèle : le lire rendait
                # toujours "", donc « n'est pas une humeur que je connais »
                # devant un champ rempli, et les points rendus pour rien.
                texte=str(getattr(event, "input", "") or ""),
                intensite=intensite,
                reward_id=reward_id,
                redemption_id=str(getattr(event, "id", "")),
            )
            return
        if await _est_le_spam_virus(bot, reward_id):
            from bot.twitch.events.virus_popups import lancer_spam_virus

            await lancer_spam_virus(
                bot,
                acheteur=str(getattr(getattr(event, "user", None), "name", "") or "?"),
                reward_id=reward_id,
                redemption_id=str(getattr(event, "id", "")),
            )
            return
        if not await _est_notre_recompense(bot, reward_id):
            return

        redemption_id = str(getattr(event, "id", ""))
        acheteur = str(getattr(getattr(event, "user", None), "name", "") or "?")
        # L'identifiant Twitch du duelliste, porté par la redemption. Il ne
        # sert qu'à la trace mémoire de fin de duel : un pseudo se change, un
        # id non. `DuelRunner` le filtre (numérique) avant de s'en servir.
        acheteur_id = str(getattr(getattr(event, "user", None), "id", "") or "")
        saisie = str(getattr(event, "input", "") or "")

        logger.info("Duel Apex demandé par {u} (saisie : {s!r})", u=acheteur, s=saisie[:60])
        _feed(bot, f"{acheteur} a acheté un duel Apex contre Azraël (points de chaîne)")

        runner = getattr(bot, "duel_runner", None)
        if runner is None:
            logger.error("Duel demandé mais aucun runner câblé — remboursement")
            # Rembourser D'ABORD, annoncer ENSUITE : si l'envoi Twitch lève,
            # le viewer a déjà récupéré ses points. Même ordre que
            # `DuelRunner._refuser()`.
            rendu = await bot.twitch_api.refund_redemption(reward_id, redemption_id)
            await _dire(bot, acheteur, _rendus_ou_pas(
                rendu, redemption_id,
                "le duel Apex n'est pas disponible en ce moment (je n'ai pas "
                "la main dessus)"))
            return

        # Le cas « duel déjà en cours » n'est PLUS court-circuité ici : seul
        # `ouvrir()` détient à la fois le remboursement ET le canal d'annonce
        # (Task 8) — un refus muet, remboursé en direct depuis ce handler,
        # laissait le viewer sans un mot d'explication.
        await runner.ouvrir(
            acheteur=acheteur, acheteur_id=acheteur_id, saisie=saisie,
            reward_id=reward_id, redemption_id=redemption_id,
        )
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("Redemption en erreur : {e}", e=exc)
        # Best-effort : une exception ici (p. ex. un timeout réseau au milieu
        # d'`ouvrir()`) ne doit pas coûter ses points au viewer. `reward_id` et
        # `redemption_id` ne sont posés qu'après le filtrage — vides, il n'y a
        # rien à rembourser. Un remboursement en double sur une redemption déjà
        # traitée est refusé proprement côté Twitch, donc sans risque.
        if reward_id and redemption_id:
            rendu = False
            try:
                rendu = await bot.twitch_api.refund_redemption(reward_id, redemption_id)
            except Exception as exc2:  # noqa: BLE001 — le repli ne relève jamais non plus
                logger.error("Remboursement de secours en erreur : {e}", e=exc2)
            # Annoncé même si le remboursement a levé ou a été refusé : le
            # viewer doit savoir que sa demande a échoué, ET si ses points sont
            # revenus. Un silence lui laisse croire que le duel va démarrer ;
            # une promesse de remboursement qui n'a pas eu lieu est pire.
            await _dire(bot, acheteur, _rendus_ou_pas(
                rendu, redemption_id,
                "ton duel Apex n'a pas pu être lancé (pépin technique de mon "
                "côté)"))
