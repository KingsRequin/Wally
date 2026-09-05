"""Forcer l'humeur de Wally aux points de chaîne (§14).

Deux récompenses : 1 000 points montent l'émotion demandée à 50 %, 2 000 à
100 %. Le viewer écrit l'émotion voulue dans le champ de texte.

CE QUI DÉCIDE DE TOUT ICI, C'EST LE REMBOURSEMENT. Le viewer tape à la main : il
écrira « colere » sans accent, « JOIE » en majuscules, « énervé » plutôt que
« colère », ou carrément « pizza ». Chaque chemin où l'humeur ne change PAS rend
les points et le dit — sinon on prend 1 000 points pour rien, en direct.

D'où la règle : **large sur ce qu'on accepte, strict sur ce qu'on promet.**

Perception passive comme les autres événements de stream : on alimente le flux,
on ne réveille aucune cadence de parole.
"""
from __future__ import annotations

import unicodedata

from loguru import logger

from bot.core.emotion import EMOTIONS

# Deux récompenses, deux clés. Partagées, l'une deviendrait irremboursable et
# l'autre appliquerait la mauvaise intensité — piège déjà nommé pour le duel et
# l'attaque de virus.
CLE_50 = "humeur:reward_50_id"
CLE_100 = "humeur:reward_100_id"

COUT_50 = 1000
COUT_100 = 2000

TITRE_50 = "Forcer une humeur de wally a 50 %"
TITRE_100 = "Forcer une humeur de wally a 100 %"

# Le libellé DOIT proposer les mots : le viewer paie avant d'écrire, il ne peut
# pas deviner ce qu'on accepte. Un test vérifie que les cinq émotions du moteur
# y figurent — ajouter une émotion sans l'annoncer la rendrait indemandable.
PROMPT = ("Écris l'humeur voulue : colère, joie, tristesse, curiosité ou "
          "ennui. Un mot hors de cette liste et tes points te sont rendus")

# Ce qu'on accepte pour chaque émotion. Les accents et la casse sont retirés
# AVANT la comparaison (`_nu`), donc inutile de lister « colere » à côté de
# « colère » — mais les vrais synonymes, si : « énervé » et « rage » sont ce que
# les gens tapent réellement.
MOTS: dict[str, str] = {
    "colere": "anger", "enerve": "anger", "enervee": "anger", "rage": "anger",
    "fache": "anger", "furieux": "anger", "anger": "anger",
    "joie": "joy", "joyeux": "joy", "heureux": "joy", "content": "joy",
    "bonheur": "joy", "joy": "joy",
    "tristesse": "sadness", "triste": "sadness", "deprime": "sadness",
    "chagrin": "sadness", "sadness": "sadness",
    "curiosite": "curiosity", "curieux": "curiosity", "interesse": "curiosity",
    "curiosity": "curiosity",
    "ennui": "boredom", "blase": "boredom", "ennuye": "boredom",
    "lassitude": "boredom", "boredom": "boredom",
}


# Ce qu'on répond à qui s'est trompé de mot. Écrit une fois, pour que le refus
# et le libellé de la récompense ne divergent jamais.
LISTE_LISIBLE = "colère, joie, tristesse, curiosité, ennui"


def _nu(texte: str) -> str:
    """Minuscules, sans accent, sans espaces autour.

    Refuser « colere » pour un accent manquant serait prendre les points de
    quelqu'un sur une faute de frappe.
    """
    sans_accent = unicodedata.normalize("NFD", str(texte or ""))
    sans_accent = "".join(c for c in sans_accent if unicodedata.category(c) != "Mn")
    return sans_accent.strip().lower()


def reconnaitre_emotion(texte) -> str | None:
    """L'émotion demandée, ou `None` si le mot n'en désigne aucune."""
    nu = _nu(texte)
    if not nu:
        return None
    if nu in MOTS:
        return MOTS[nu]
    # Un mot noyé dans une phrase (« mets toi en colère stp ») : on cherche le
    # premier terme reconnu. Sur les mots seuls, la table ci-dessus a déjà
    # répondu.
    for mot in nu.replace("'", " ").split():
        if mot in MOTS:
            return MOTS[mot]
    return None


async def _rendre(bot, acheteur: str, reward_id: str, redemption_id: str,
                  motif: str) -> None:
    """Rembourse et le dit. Dans cet ordre : si l'envoi lève, le viewer a déjà
    récupéré ses points.

    Le message dit AUSSI si le remboursement a abouti — promettre des points qui
    ne reviendront pas est pire que de ne rien promettre.
    """
    rendu = False
    try:
        rendu = await bot.twitch_api.refund_redemption(reward_id, redemption_id)
    except Exception as exc:  # noqa: BLE001 — on annonce quand même
        logger.error("Humeur : remboursement en erreur : {e!r}", e=exc)
    mention = f"@{acheteur} " if acheteur and acheteur != "?" else ""
    if rendu:
        texte = f"{mention}{motif}, tes points t'ont été rendus."
    else:
        texte = (f"{mention}{motif}, et je n'ai PAS pu te rendre tes points "
                 f"automatiquement, il faudra le faire manuellement "
                 f"(redemption {redemption_id}).")
    try:
        # ORANGE : une récompense payée qui n'a pas pu être honorée. Le viewer
        # doit repérer la ligne qui le concerne dans un chat qui défile — c'est
        # la seule annonce où il a perdu quelque chose.
        await bot.twitch_api.send_automatic(
            texte, color=bot.twitch_api.COULEUR_ECHEC)
    except Exception as exc:  # noqa: BLE001 — le remboursement est déjà fait
        logger.error("Humeur : refus non annoncé dans le chat : {e!r}", e=exc)


def _feed(bot, description: str) -> None:
    feed = getattr(bot, "stream_feed", None)
    if feed is None:
        return
    try:
        feed.record(description, kind="humeur_redemption")
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("StreamFeed : humeur non consignée : {e!r}", e=exc)


async def forcer_humeur(bot, *, acheteur: str, texte: str, intensite: float,
                        reward_id: str, redemption_id: str) -> None:
    """Applique l'humeur demandée, ou rend les points. N'échoue jamais vers
    l'appelant."""
    try:
        emotion = reconnaitre_emotion(texte)
        if emotion is None:
            logger.info("Humeur : « {t} » ne désigne aucune émotion — remboursement",
                        t=str(texte)[:40])
            await _rendre(
                bot, acheteur, reward_id, redemption_id,
                f"« {str(texte)[:40]} » n'est pas une humeur que je connais "
                f"({LISTE_LISIBLE})")
            return

        moteur = getattr(bot, "emotion", None)
        if moteur is None:
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "mon moteur d'émotions n'est pas disponible")
            return
        try:
            moteur.set_emotion(emotion, float(intensite))
        except Exception as exc:  # noqa: BLE001 — on rembourse plutôt que de garder
            logger.error("Humeur : application impossible : {e!r}", e=exc)
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "je n'ai pas réussi à changer d'humeur (pépin technique)")
            return

        pourcent = round(float(intensite) * 100)
        logger.info("Humeur forcée par {u} : {e} à {p} %",
                    u=acheteur, e=emotion, p=pourcent)
        _feed(bot, f"{acheteur} a forcé l'humeur de Wally : {emotion} à {pourcent} %")
        mention = f"@{acheteur} " if acheteur and acheteur != "?" else ""
        try:
            # VERT : la récompense a été honorée. Le pendant exact du
            # remboursement orange quelques lignes plus haut — les deux issues
            # du même achat se distinguent sans qu'on ait à lire la phrase.
            await bot.twitch_api.send_automatic(
                f"{mention}c'est fait, me voilà {_en_francais(emotion)} "
                f"à {pourcent} %. Merci qui.",
                color=bot.twitch_api.COULEUR_REUSSITE)
        except Exception as exc:  # noqa: BLE001 — l'humeur est déjà changée
            logger.error("Humeur : changement non annoncé dans le chat : {e!r}", e=exc)
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("Humeur en erreur : {e!r}", e=exc)
        await _rendre(bot, acheteur, reward_id, redemption_id,
                      "l'humeur n'a pas pu être changée (pépin technique)")


def _en_francais(emotion: str) -> str:
    return {"anger": "en colère", "joy": "joyeux", "sadness": "triste",
            "curiosity": "curieux", "boredom": "blasé"}.get(emotion, emotion)


# Garde-fou de cohérence : une émotion du moteur sans mot ici serait
# indemandable, et le viewer se ferait rembourser sans comprendre pourquoi.
_SANS_MOT = [e for e in EMOTIONS if e not in set(MOTS.values())]
if _SANS_MOT:  # pragma: no cover — un test le vérifie aussi
    logger.warning("Humeur : émotions sans mot reconnu : {e}", e=_SANS_MOT)
