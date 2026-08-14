# bot/twitch/duel_announce.py
"""Les annonces du duel Apex : une phrase dans le chat, le tableau à l'écran.

`DuelRunner` ne connaît qu'une chose de la sortie : une coroutine
`annoncer(evenement)`. Tout ce qui suit vit ici — le registre de ton
(`bot/persona/prompts/apex_duel.md`, une section par type d'événement ; le
dossier est bind-monté, donc un redémarrage suffit à changer le ton, sans
rebuild), la rédaction, l'envoi Twitch et le widget d'overlay.

Deux règles tiennent ce fichier :

  · **la parole part toujours.** Le viewer a dépensé ses points ; un appel LLM
    raté ne doit pas avaler l'étape. Sans habillage, c'est le texte FACTUEL qui
    est publié tel quel.
  · **les chiffres ne sont jamais laissés au modèle.** Ils sont calculés par la
    machine à états, écrits ici en toutes lettres, et le modèle ne fait que les
    habiller. L'adresse du site suit la même règle : elle est collée par le
    code, un modèle qui reformule une URL la casse.
"""
from __future__ import annotations

from loguru import logger

from bot.core.apex.duel import Evenement
from bot.core.llm import FALLBACK_RESPONSE
from bot.intelligence.prompts import load_prompt

# Plafond d'un message Twitch (500 caractères). Même marge que les événements
# sociaux : de quoi ajouter les points de suspension sans dépasser.
MAX_CHAT = 480

_SOCLE = (
    "Tu arbitres un duel Apex entre Azraël et un viewer qui a dépensé ses points "
    "de chaîne. Les chiffres te sont donnés : tu les habilles, tu ne les inventes "
    "pas et tu ne les recalcules pas. UNE phrase courte, adressée aux SPECTATEURS "
    "du live. Réponds uniquement par la phrase, sans guillemets."
)

# Le registre est lu une fois, au chargement du module — comme les autres
# prompts d'overlay. `/reload-persona` ne le relit donc pas : c'est le
# comportement de tout `load_prompt()` du projet.
_REGISTRE_BRUT = load_prompt("apex_duel", render=False)


def _sections(contenu: str) -> dict[str, str]:
    """Découpe un Markdown en {clé de section: directive}.

    Le `"\\n" + contenu` n'est pas cosmétique : sans lui, un fichier qui
    commence directement par `## clé` perd sa PREMIÈRE section — le bug
    `anger_low`, resté invisible des mois.
    """
    directives: dict[str, str] = {}
    for section in ("\n" + (contenu or "")).split("\n## ")[1:]:
        lignes = section.strip().split("\n", 1)
        if len(lignes) < 2:
            continue
        cle = lignes[0].strip()
        texte = " ".join(lignes[1].strip().split("\n")).strip()
        if cle and texte:
            directives[cle] = texte
    return directives


_REGISTRE = _sections(_REGISTRE_BRUT)


def registre_duel() -> dict[str, str]:
    """Le registre de ton par type d'événement, tel qu'il est chargé."""
    return _REGISTRE


# Les seuls événements où `donnees["viewer"]` est un NOM. Ailleurs
# (`manche_fin`, `verdict`) la même clé porte un nombre de kills : la lire comme
# un pseudo faisait annoncer « Azraël 4, 2 2 » et affichait « 2 » comme nom du
# duelliste sur l'overlay.
_TYPES_NOMMANT_LE_VIEWER = ("duel_ouvert", "compte_introuvable", "recommence")


def nom_du_viewer(evt: Evenement) -> str:
    """Le pseudo du duelliste porté par cet événement, `""` s'il n'en porte pas."""
    if evt.type not in _TYPES_NOMMANT_LE_VIEWER:
        return ""
    return str((evt.donnees or {}).get("viewer") or "")


def _points_rendus(d: dict, viewer: str = "") -> str:
    """Ce qu'il faut dire des points quand ils devaient revenir.

    `refund_redemption()` vérifie le corps de la réponse Helix, et le runner
    fait remonter son verdict jusqu'ici (`remboursement_echoue`). Un
    remboursement refusé — 403, scope perdu, redemption déjà soldée — ne
    s'annonce pas comme un remboursement réussi : le viewer l'entendrait
    devant le stream et attendrait des points qui ne reviendront jamais.

    On dit alors la vérité ET à qui s'adresser : seul le streamer peut les
    rendre à la main depuis sa console.
    """
    a_qui = f" de {viewer}" if viewer else ""
    if d.get("remboursement_echoue"):
        return (f"Attention : le remboursement a ÉCHOUÉ, les points{a_qui} "
                "n'ont pas été rendus. Il faut prévenir le streamer, il n'y a "
                "que lui qui puisse les rendre à la main.")
    return f"Les points{a_qui} ont été rendus."


def _fait(evt: Evenement, viewer_connu: str = "") -> str:
    """L'événement en français, chiffres compris. C'est le SOCLE de l'annonce :
    ce texte part tel quel si la rédaction échoue, il doit donc se suffire.

    `viewer_connu` comble les événements qui ne portent pas le nom du duelliste
    (fin de manche, verdict) : sans lui, l'annonce nue parlerait d'un anonyme.
    """
    d = evt.donnees or {}
    viewer = nom_du_viewer(evt) or viewer_connu or "le duelliste"

    if evt.type == "duel_ouvert":
        return (f"{viewer} lance un duel Apex contre Azraël. Il doit maintenant "
                "être invité dans le squad d'Azraël, et la partie doit se jouer "
                "en Battle Royale ou en Joker — la Mixtape ne compte aucun kill.")
    if evt.type == "compte_introuvable":
        return (f"Le compte Apex de {viewer} n'a pas été retrouvé. Ce qu'il doit "
                f"faire : {d.get('etapes') or ''}".strip())
    if evt.type == "manche_debut":
        return f"La manche {d.get('manche')} sur {d.get('sur')} commence."
    if evt.type == "manche_fin":
        if not d.get("mesurable"):
            return (f"La manche {d.get('manche')} sur {d.get('sur')} est finie, "
                    "mais aucun kill n'a pu être compté des deux côtés : elle ne "
                    "compte pour personne, et ce n'est pas un zéro à zéro.")
        return (f"Manche {d.get('manche')} sur {d.get('sur')} finie : "
                f"Azraël {d.get('azrael')} kills, {viewer} {d.get('viewer')}. "
                f"Total du duel : Azraël {d.get('total_azrael')}, "
                f"{viewer} {d.get('total_viewer')}.")
    if evt.type == "verdict":
        gagnant = d.get("gagnant")
        issue = ("personne ne l'emporte, c'est une égalité" if gagnant is None
                 else ("Azraël l'emporte" if gagnant == "azrael"
                       else f"{viewer} l'emporte"))
        if d.get("abandon"):
            # Le duel s'est arrêté en route. Les DEUX faits doivent être dits,
            # sans quoi l'annonce ment par omission : le verdict tient sur les
            # manches jouées, mais les points restent dépensés même pour qui
            # mène — sinon quitter en tête serait la meilleure stratégie.
            return (f"Duel interrompu. Sur les manches jouées : Azraël "
                    f"{d.get('azrael')}, {viewer} {d.get('viewer')} — {issue}. "
                    f"Les points de {viewer} restent dépensés : il n'est pas "
                    "allé au bout du duel.")
        # Le sort des points fait partie du résultat, pas d'un post-scriptum :
        # c'est la règle du duel (gagner rend les points, perdre les consomme)
        # et le duelliste doit l'entendre en même temps que le score. Le fait
        # vient de la machine à états, jamais d'une déduction locale.
        points = (_points_rendus(d, viewer) if d.get("rembourser")
                  else f"Les points de {viewer} sont consommés.")
        return (f"Duel terminé : Azraël {d.get('azrael')}, {viewer} "
                f"{d.get('viewer')} — {issue}. {points}")
    if evt.type == "refus":
        return (f"Le duel ne peut pas commencer : {d.get('motif')}. "
                f"{_points_rendus(d)}")
    if evt.type == "abandon":
        # `rembourser` tranche : annoncer un remboursement qui n'a pas eu lieu
        # serait un mensonge, et l'inverse une inquiétude pour rien.
        #
        # Quand il vaut False, au moins une manche a été comptée : un verdict
        # suit, qui tranche le classement — mais pas les points. Quitter en
        # cours ne les rend jamais, même à qui mène.
        rendu = (_points_rendus(d) if d.get("rembourser")
                 else "Les points ne sont PAS rendus : le duel n'a pas été joué "
                      "jusqu'au bout, même si le verdict tranche sur les manches "
                      "déjà comptées.")
        return f"Le duel s'arrête : {d.get('motif')}. {rendu}"
    if evt.type == "recommence":
        return (f"Les compteurs du duel repartent de zéro. {viewer} garde sa "
                "place, il ne repaie rien.")
    return ""


def _sous_titre(camp) -> str:
    """« Fuse · niv. 285 » sous un camp, à partir de ce qu'on sait de lui.

    Les deux valeurs viennent du profil sondé à chaque relevé, via l'événement.
    Ce qui manque est OMIS : sans légende on n'écrit que le niveau, sans niveau
    que la légende, et sans rien un sous-titre vide — que l'overlay n'affiche
    pas. Un « niv. 0 » serait une affirmation fausse de plus.
    """
    if not isinstance(camp, dict):
        return ""
    morceaux = []
    legende = str(camp.get("legende") or "").strip()
    if legende:
        morceaux.append(legende)
    try:
        niveau = int(camp.get("niveau") or 0)
    except (TypeError, ValueError):
        niveau = 0
    if niveau > 0:
        morceaux.append(f"niv. {niveau}")
    return " · ".join(morceaux)


class DuelAnnonceur:
    """La sortie du duel : le chat de la chaîne maison, et l'overlay.

    Construit avec le bot Twitch (pour l'API de chat, le LLM et la persona) et
    le nom de la chaîne maison. Le narrateur d'overlay est résolu à CHAQUE
    appel : il naît dans le `setup_hook` du bot Discord, donc après ce câblage.
    """

    def __init__(self, bot, *, channel: str) -> None:
        self._bot = bot
        self._channel = channel
        # Le nom du duelliste, retenu à l'ouverture : les événements de fin de
        # manche ne le portent pas, et à l'instant du verdict le duel a déjà
        # été effacé de `duel_en_cours` (le nettoyage précède les annonces).
        self._viewer = ""

    def _nom(self) -> str:
        """Le duelliste, même après un redémarrage en pleine manche.

        Le nom retenu en mémoire ne survit pas au rebuild ; le duel repris de
        la base, lui, le porte toujours. À l'inverse, au verdict le duel a déjà
        été effacé et seule la mémoire l'a encore : les deux sources se
        complètent, aucune ne suffit.
        """
        if self._viewer:
            return self._viewer
        from bot.core.apex.duel_runner import current_duel

        return str(getattr(current_duel(), "viewer_nom", "") or "")

    async def __call__(self, evt: Evenement) -> None:
        if nom := nom_du_viewer(evt):
            self._viewer = nom
        fait = _fait(evt, self._nom())
        if not fait:
            logger.warning("Duel : type d'événement sans annonce ({t})", t=evt.type)
            return

        # L'adresse est collée par le CODE, jamais laissée au modèle : une URL
        # reformulée rend le duel impossible à démarrer. Elle voyage comme un
        # suffixe pour que la troncature morde sur la réplique et jamais sur
        # elle — tronquer après l'avoir collée casserait ce qu'on protège.
        suffixe = (str((evt.donnees or {}).get("url") or "")
                   if evt.type == "compte_introuvable" else "")

        ligne = await self._rediger(evt.type, fait) or fait
        await self._publier(ligne, suffixe=suffixe)
        self._ecran(evt, ligne)

    # -- Rédaction ----------------------------------------------------------
    async def _rediger(self, type_evt: str, fait: str) -> str:
        """La phrase de Wally, ou `""` s'il n'a rien pu produire."""
        registre = _REGISTRE.get(type_evt, "")
        try:
            from bot.twitch.handlers import _build_situation

            system = self._bot.prompts.build_system_prompt(
                emotion_state=self._bot.emotion.get_state(),
                situation=_build_situation(self._bot, self._channel),
                persona_block=self._bot.persona.build_prompt_block(),
                emotion_directives=self._bot.persona.emotion_directives,
                weekday_directives=self._bot.persona.weekday_directives,
                composite_directives=self._bot.persona.composite_directives,
            )
            consignes = "\n\n".join(x for x in (_SOCLE, registre) if x)
            reponse = await self._bot.llm.complete(
                f"{system}\n\n{consignes}",
                [{"role": "user", "content": fait}],
                purpose="apex_duel",
            )
        except Exception as exc:  # noqa: BLE001 — sans habillage, le fait part nu
            logger.warning("Duel : annonce non rédigée ({t}) : {e}", t=type_evt, e=exc)
            return ""
        reponse = (reponse or "").strip()
        if not reponse or reponse == FALLBACK_RESPONSE.strip():
            # `complete()` ne lève pas : sur panne totale il rend une excuse
            # technique. La publier à la place du score serait perdre
            # l'information que le viewer attend.
            logger.warning("Duel : rédaction indisponible ({t}), fait publié nu",
                           t=type_evt)
            return ""
        return reponse

    # -- Sorties ------------------------------------------------------------
    async def _publier(self, texte: str, *, suffixe: str = "") -> None:
        plafond = MAX_CHAT - (len(suffixe) + 1 if suffixe else 0)
        if len(texte) > plafond:
            texte = texte[:plafond - 3] + "..."
        if suffixe:
            texte = f"{texte} {suffixe}"
        try:
            # Le retour est LU : sur Twitch, un 200 ne prouve pas la
            # publication — un refus d'AutoMod arrive dans le corps
            # (`is_sent: false`), et `send_message` le traduit en `False`. Une
            # étape de duel avalée en silence est indétectable autrement.
            if not await self._bot.twitch_api.send_message(text=texte):
                logger.warning("Duel : annonce refusée par Twitch — « {t} »",
                               t=texte[:80])
        except Exception as exc:  # noqa: BLE001 — l'overlay doit rester servi
            logger.error("Duel : annonce non publiée dans le chat : {e}", e=exc)

    def _ecran(self, evt: Evenement, commentaire: str) -> None:
        """Le tableau du duel, quand il y a un score à montrer.

        Jamais bloquant : un overlay absent ou en panne ne doit pas empêcher
        l'annonce, qui est déjà partie.
        """
        d = evt.donnees or {}
        if evt.type == "manche_debut":
            # Le tableau reparaît à CHAQUE début de manche (§11 de la spec) :
            # le widget n'est pas `sticky`, un duel dure une heure et le cycle
            # normal des widgets l'efface entre-temps.
            #
            # Avant la première manche, « 0 — 0 » ne prétend rien : rien n'a
            # encore été joué. Après une ou plusieurs manches dont AUCUNE n'a
            # pu être mesurée, les mêmes chiffres affirmeraient un score que
            # personne n'a compté — on se tait alors, comme à la fin d'une
            # manche non mesurable.
            if d.get("manches_jouees") and not d.get("total_mesurable"):
                return
            gauche, droite = d.get("total_azrael"), d.get("total_viewer")
            label = f"Duel — manche {d.get('manche')}/{d.get('sur')}"
        elif evt.type == "manche_fin":
            if not d.get("mesurable"):
                return          # rien de comparable : pas de tableau
            gauche, droite = d.get("total_azrael"), d.get("total_viewer")
            label = f"Duel — manche {d.get('manche')}/{d.get('sur')}"
        elif evt.type == "verdict":
            gauche, droite = d.get("azrael"), d.get("viewer")
            label = "Duel — score final"
        else:
            return

        from bot.discord.handlers import _overlay_narrator

        narrator = _overlay_narrator(self._bot)
        if narrator is None:
            return
        camps = d.get("camps") or {}
        try:
            narrator.show_widget(
                "versus", commentaire, label=label,
                left_name="Azraël", left_value=gauche,
                left_sub=_sous_titre(camps.get("azrael")),
                right_name=self._nom() or "le duelliste", right_value=droite,
                right_sub=_sous_titre(camps.get("viewer")),
            )
        except Exception as exc:  # noqa: BLE001 — l'écran n'est pas le canal principal
            logger.warning("Duel : tableau non affiché : {e}", e=exc)
