"""Le sondage Discord : la carte, les boutons, la cadence et la clôture.

Le comptage vit dans `bot/core/sondage.py` et le dessin dans
`bot/core/sondage_image.py` ; ici on ne fait que parler à Discord. Ce module
porte AUSSI la définition de l'outil offert au LLM — comme `web_search` ou
`scrape`, un service qui expose le sien le garde collé à ce qu'il appelle
(`tests/test_tools_rangement.py` : seuls les modules qui ne sont QU'un outil
vont dans `bot/tools/`).

Le message est en **Components V2** : la question, l'image et les boutons de
vote tiennent dans un seul `Container`, au lieu d'un embed surmonté de
réactions. Ce que la bascule a SUPPRIMÉ : voter par réaction obligeait Wally à
retirer la précédente pour qu'une personne ne compte pas deux fois, ce qui exige
`Gérer les messages` — sans cette permission le second clic était ignoré, et le
pied de page devait s'en excuser. Un bouton n'a pas ce problème : le vote est
une interaction, pas un état posé sur le message.

⚠️ En Components V2, `content` est INTERDIT sur le message. Le `@everyone` d'un
sondage pingué voyage donc dans un `TextDisplay`, où il mentionne pour de vrai ;
`allowed_mentions` continue de décider si le ping part.

Trois choses appartiennent au SERVEUR, jamais au modèle ni au demandeur :

· **La cadence des redessins.** Discord limite les éditions d'un message ; une
  rafale de votes doit se fondre en une seule image, sinon l'affichage retarde
  de plusieurs secondes sur le vote — le contraire de ce qu'on cherche.
· **Le droit de ping.** Wally ne mentionne `@everyone` que si la personne qui
  demande a elle-même la permission dans le salon visé. Sans cette vérification,
  n'importe qui ferait sonner tout le serveur PAR PROCURATION.
· **L'unicité du vote.** `Sondage.votes` est un dict par personne : deux voix
  pour une même personne sont structurellement impossibles. Un clic sur son
  propre choix le RETIRE, un clic sur un autre le REMPLACE.
"""
from __future__ import annotations

import asyncio
import io
from typing import Any, Optional

import discord
from loguru import logger

from bot.core.etat_persistant import EtatPersistant
from bot.core.self_trace import note_act
from bot.core.sondage import (
    MAX_OPTIONS,
    MIN_OPTIONS,
    Sondage,
    Sondages,
    creer,
    emoji_pour,
)
from bot.core.sondage_image import rendre

NOM_IMAGE = "sondage.png"
_COULEUR_OUVERT = 0x9D7BFF        # --who-deep
_COULEUR_CLOS = 0x7DFFB0          # --win
_PIED = "-# Clique une option pour voter — reclique-la pour retirer ta voix."
# Le préfixe des `custom_id` de vote. FIXE, et sans identifiant de message :
# c'est ce qui permet à UN seul enregistrement persistant de router les clics de
# TOUS les sondages ouverts. Le message visé est lu sur l'interaction.
_PREFIXE_VOTE = "sondage:vote:"
_BOUTONS_PAR_RANG = 5             # plafond Discord d'une `ActionRow`


class BoutonVote(discord.ui.Button):
    """Une option du sondage.

    Le `custom_id` porte l'INDEX de l'option, jamais l'identifiant du message :
    c'est ce qui rend la vue persistante (cf. `vue_de_routage`). Le sondage
    concerné se déduit de `interaction.message.id`.
    """

    def __init__(self, index: int, option: str, *, clos: bool = False) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=option[:80],
            emoji=emoji_pour(index),
            custom_id=f"{_PREFIXE_VOTE}{index}",
            disabled=clos,
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        service = getattr(interaction.client, "sondages", None)
        if service is None:
            # Ne peut arriver qu'entre deux versions du bot ; sans ce mot, le
            # clic reste sans réponse et Discord affiche « échoué ».
            logger.warning("Sondage: clic reçu mais le service n'est pas branché")
            await interaction.response.send_message(
                "Le sondage n'est plus branché.", ephemeral=True)
            return
        await service.sur_clic(interaction, self.index)


def _rangs_de_vote(options: list[str], *, clos: bool) -> list[discord.ui.ActionRow]:
    """Les boutons, cinq par rang — le plafond d'une `ActionRow`."""
    boutons = [BoutonVote(i, o, clos=clos) for i, o in enumerate(options)]
    return [discord.ui.ActionRow(*boutons[d:d + _BOUTONS_PAR_RANG])
            for d in range(0, len(boutons), _BOUTONS_PAR_RANG)]


class VueSondage(discord.ui.LayoutView):
    """La carte : la question en TEXTE, l'état en image, les options en boutons.

    Le `TextDisplay` de la question n'est pas un doublon de l'image : c'est lui
    qui part en notification et en aperçu mobile, là où un PNG ne dit rien.
    """

    def __init__(self, sondage: Sondage) -> None:
        super().__init__(timeout=None)
        if sondage.ping and not sondage.clos:
            # Hors du `Container` : une mention se lit mieux au-dessus de la
            # carte, et c'est `allowed_mentions` qui décide si elle sonne.
            self.add_item(discord.ui.TextDisplay("@everyone"))
        galerie: discord.ui.MediaGallery = discord.ui.MediaGallery()
        galerie.add_item(media=f"attachment://{NOM_IMAGE}")
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"## {sondage.question}"),
            galerie,
            *_rangs_de_vote(sondage.options, clos=sondage.clos),
            discord.ui.TextDisplay(sondage.ligne_resultat() if sondage.clos
                                   else _PIED),
            accent_colour=discord.Colour(_COULEUR_CLOS if sondage.clos
                                         else _COULEUR_OUVERT),
        ))


def vue_de_routage() -> discord.ui.LayoutView:
    """L'exemplaire enregistré au boot par `WallyDiscord.setup_hook` — JAMAIS envoyé.

    discord.py route un clic par `custom_id` : un seul enregistrement portant
    les `MAX_OPTIONS` boutons suffit donc à servir tous les sondages ouverts,
    quel que soit leur nombre d'options.

    Sans lui, un rebuild rendrait inertes les boutons déjà publiés et Discord
    répondrait « Cette interaction a échoué » — là où une réaction, elle,
    survivait toute seule.
    """
    vue = discord.ui.LayoutView(timeout=None)
    for rang in _rangs_de_vote([f"option {i + 1}" for i in range(MAX_OPTIONS)],
                               clos=False):
        vue.add_item(rang)
    return vue


class SondageService:
    """Les sondages Discord vivants, leur affichage et leur clôture."""

    CLE_ETAT = "discord:sondages"
    # Un sondage sans durée reste ouvert ; au-delà d'un jour, c'est qu'on l'a
    # oublié, et le relancer au boot n'intéresse plus personne.
    AGE_MAX_S = 24 * 3600
    DELAI_MAJ_S = 1.5

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.sondages = Sondages()
        self._etat = EtatPersistant(getattr(bot, "db", None), self.CLE_ETAT,
                                    session=lambda: "", age_max_s=self.AGE_MAX_S)
        self._clotures: dict[int, asyncio.Task] = {}
        self._majs: dict[int, asyncio.Task] = {}
        # Référence FORTE sur les tâches : la boucle asyncio n'en garde qu'une
        # faible, et une tâche ramassée en vol emporte le redessin ou la clôture.
        self._taches: set[asyncio.Task] = set()

    # ── envoi ───────────────────────────────────────────────────────────────

    async def creer(self, *, salon: Any, question: str, options: list[str],
                    auteur: str = "", duree_s: Optional[float] = None,
                    ping: bool = False) -> Optional[Sondage]:
        """Publie la carte du sondage. None si la demande n'en est pas un."""
        sondage = creer(question, options, channel_id=salon.id, auteur=auteur,
                        duree_s=duree_s, ping=ping)
        if sondage is None:
            return None
        # Pas de `content=` : Components V2 l'interdit. Le `@everyone` est un
        # `TextDisplay` de la vue, et `allowed_mentions` décide s'il sonne.
        message = await salon.send(
            view=VueSondage(sondage),
            file=discord.File(io.BytesIO(await self._png(sondage)),
                              filename=NOM_IMAGE),
            allowed_mentions=discord.AllowedMentions(everyone=ping, users=False,
                                                     roles=False),
        )
        sondage.message_id = message.id
        self.sondages.ajouter(sondage)
        self._planifier_cloture(sondage)
        await self._ranger()
        logger.info("Sondage Discord ouvert par {a} : « {q} » ({n} options)",
                    a=auteur or "?", q=sondage.question, n=len(sondage.options))
        note_act(f"tu viens d'ouvrir un sondage Discord : « {sondage.question} »")
        return sondage

    # ── vote ────────────────────────────────────────────────────────────────

    async def sur_clic(self, interaction: Any, index: int) -> None:
        """Un clic sur une option : la voix, ou son retrait.

        Recliquer SON PROPRE choix le retire — c'est ce que faisait le décochage
        d'une réaction. Cliquer une autre option remplace la précédente sans que
        Wally ait à retirer quoi que ce soit, donc sans `Gérer les messages` :
        `Sondage.votes` est un dict par personne.

        Aucun accusé écrit : le retour, c'est l'image qui se redessine. Une
        confirmation éphémère par clic empilerait dix bulles chez un indécis.
        """
        message = getattr(interaction, "message", None)
        sondage = self.sondages.par_message(getattr(message, "id", 0))
        if sondage is None:
            await interaction.response.send_message(
                "Ce sondage n'existe plus.", ephemeral=True)
            return
        if sondage.clos:
            await interaction.response.send_message(
                f"Ce sondage est clos. {sondage.ligne_resultat()}", ephemeral=True)
            return
        if index >= len(sondage.options):
            # Un bouton de la vue de routage sur un sondage plus court : le
            # message ne peut pas le porter, mais un client retardataire si.
            await interaction.response.send_message(
                "Cette option n'existe pas.", ephemeral=True)
            return

        votant = str(interaction.user.id)
        change = (sondage.retirer(votant, index)
                  if sondage.votes.get(votant) == index
                  else sondage.voter(votant, index))
        await interaction.response.defer()
        if change:
            self._planifier_maj(sondage)

    # ── affichage ───────────────────────────────────────────────────────────

    def _planifier_maj(self, sondage: Sondage) -> None:
        """Groupe les redessins : un seul par `DELAI_MAJ_S`, votes fondus."""
        if sondage.message_id in self._majs:
            return              # le vote sera dans le redessin déjà programmé

        async def _bientot() -> None:
            try:
                await asyncio.sleep(self.DELAI_MAJ_S)
            finally:
                # Libéré AVANT le redessin : un vote qui tombe PENDANT l'édition
                # doit pouvoir en programmer une autre, sinon il n'apparaît qu'au
                # vote suivant — ou jamais, si c'était le dernier.
                self._majs.pop(sondage.message_id, None)
            await self._redessiner(sondage)

        self._majs[sondage.message_id] = self._lancer(_bientot())

    async def _redessiner(self, sondage: Sondage) -> None:
        message = self._message(sondage)
        if message is None:
            return
        try:
            await message.edit(
                view=VueSondage(sondage),
                attachments=[discord.File(io.BytesIO(await self._png(sondage)),
                                          filename=NOM_IMAGE)],
                # Un sondage pingué garde son `@everyone` dans la vue et se
                # redessine toutes les 1,5 s. Discord ne renotifie pas sur une
                # édition, mais on ne laisse pas ça à la parole de la doc.
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.NotFound as exc:
            # Message supprimé sous le sondage : il n'a plus de support, et le
            # garder ouvert bloquerait le salon pour tous les suivants.
            logger.warning("Sondage: message disparu, sondage oublié ({e!r})",
                           e=exc)
            sondage.clos = True
            self.sondages.oublier(sondage.message_id)
        except discord.HTTPException as exc:
            logger.warning("Sondage: édition refusée ({e!r})", e=exc)
        await self._ranger()

    async def _png(self, sondage: Sondage) -> bytes:
        # Pillow est CPU-bound : dans la boucle, il ferait bégayer le vocal.
        return await asyncio.to_thread(rendre, sondage)

    # ── clôture ─────────────────────────────────────────────────────────────

    def _planifier_cloture(self, sondage: Sondage) -> None:
        reste = sondage.restant()
        if reste is None:
            return              # sans durée : il reste ouvert jusqu'à la demande

        async def _a_l_heure() -> None:
            await asyncio.sleep(reste)
            await self.fermer(sondage)

        self._clotures[sondage.message_id] = self._lancer(_a_l_heure())

    async def fermer(self, sondage: Sondage) -> None:
        """Dépouille : boutons grisés, image figée, résultat annoncé."""
        if sondage.clos:
            return
        sondage.clos = True
        # `is not current_task()` : quand c'est le minuteur lui-même qui ferme,
        # s'annuler couperait la clôture avant l'annonce du résultat.
        tache = self._clotures.pop(sondage.message_id, None)
        if tache is not None and tache is not asyncio.current_task():
            tache.cancel()
        maj = self._majs.pop(sondage.message_id, None)
        if maj is not None:
            maj.cancel()
        # `_redessiner` republie la vue avec `clos=True` : boutons désactivés
        # et résultat en pied. Rien à nettoyer sur le message.
        await self._redessiner(sondage)
        self.sondages.oublier(sondage.message_id)
        await self._ranger()
        logger.info("Sondage Discord clos — {r}", r=sondage.ligne_resultat())
        note_act(sondage.ligne_resultat())

    # ── reprise ─────────────────────────────────────────────────────────────

    async def reprendre(self) -> None:
        """Reprend les sondages laissés ouverts par le process précédent.

        Les votes viennent de l'ÉTAT RANGÉ, seul à les porter : un bouton ne
        laisse aucune trace sur le message, contrairement à une réaction. Ce que
        la bascule coûte : un clic tombé pendant la coupure est perdu — mais pas
        EN SILENCE, Discord répond « Cette interaction a échoué » à qui l'a
        tenté. Le `fetch_message` ne sert plus qu'à vérifier que la carte existe
        encore.
        """
        self.sondages.from_dict(await self._etat.charger())
        for sondage in list(self.sondages.ouverts()):
            salon = self.bot.get_channel(sondage.channel_id)
            if salon is None:
                logger.warning("Sondage: salon {c} introuvable, sondage oublié",
                               c=sondage.channel_id)
                self.sondages.oublier(sondage.message_id)
                continue
            try:
                await salon.fetch_message(sondage.message_id)
            except discord.HTTPException as exc:
                logger.warning("Sondage: message {m} irrécupérable ({e!r})",
                               m=sondage.message_id, e=exc)
                self.sondages.oublier(sondage.message_id)
                continue
            if sondage.expire():
                await self.fermer(sondage)
                continue
            self._planifier_cloture(sondage)
            await self._redessiner(sondage)
            logger.info("Sondage repris : « {q} » ({n} votes)",
                        q=sondage.question, n=sondage.depouiller().total)
        await self._ranger()

    # ── plomberie ───────────────────────────────────────────────────────────

    def _message(self, sondage: Sondage) -> Any:
        salon = self.bot.get_channel(sondage.channel_id)
        if salon is None:
            return None
        return salon.get_partial_message(sondage.message_id)

    async def _ranger(self) -> None:
        await self._etat.ranger(self.sondages.to_dict())

    def _lancer(self, coro: Any) -> asyncio.Task:
        tache = asyncio.create_task(coro)
        self._taches.add(tache)

        def _fini(finie: asyncio.Task) -> None:
            self._taches.discard(finie)
            if not finie.cancelled() and finie.exception() is not None:
                logger.opt(exception=finie.exception()).error("Sondage: tâche échouée")

        tache.add_done_callback(_fini)
        return tache


# ── l'outil offert au LLM ───────────────────────────────────────────────────

# Bornes de durée. Une minute au moins (le temps de lire et de cliquer), un jour
# au plus : au-delà, plus personne ne revient voir le résultat.
_DUREE_MIN_MIN = 1.0
_DUREE_MAX_MIN = 24 * 60.0

SONDAGE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "sondage",
        "description": (
            "Lancer un sondage dans un salon Discord : tu publies une carte avec "
            "la question et les options, les gens votent en cliquant le bouton "
            "de leur choix, et l'image se met à jour à chaque vote. Un seul "
            "vote par personne — cliquer une autre option remplace le vote, "
            "recliquer la même le retire. "
            "Sers-t'en dès qu'on te demande un sondage, un vote, ou de faire "
            "choisir les gens entre plusieurs options. "
            "Dire « ok je lance le sondage » sans appeler l'outil ne lance RIEN. "
            "N'annonce jamais de résultat que l'outil ne t'a pas rendu : tant "
            "que le sondage est ouvert, tu ne sais pas qui gagne. "
            "Utilise `action: \"fermer\"` quand on te demande de clore le "
            "sondage ou d'en donner le résultat — c'est là que tu l'apprends. "
            "`ping_everyone` ne marche que si la personne qui te le demande a "
            "elle-même le droit de mentionner @everyone : sinon le sondage part "
            "quand même, sans le ping."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["creer", "fermer"],
                    "description": "Ouvrir un sondage, ou le dépouiller.",
                },
                "question": {
                    "type": "string",
                    "description": "La question posée, telle qu'elle s'affichera.",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        f"De {MIN_OPTIONS} à {MAX_OPTIONS} réponses possibles, "
                        "courtes."
                    ),
                },
                "duree_minutes": {
                    "type": "number",
                    "description": (
                        "Durée avant dépouillement automatique. Omets-la pour "
                        "laisser le sondage ouvert jusqu'à ce qu'on te demande "
                        "de le fermer."
                    ),
                },
                "salon": {
                    "type": "string",
                    "description": (
                        "Nom ou mention d'un AUTRE salon où publier. Par défaut, "
                        "le salon où on te parle."
                    ),
                },
                "ping_everyone": {
                    "type": "boolean",
                    "description": (
                        "Mentionner @everyone avec le sondage. Seulement si on "
                        "te le demande explicitement."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}


def _salon_demande(message: Any, demande: str) -> tuple[Any, Optional[str]]:
    """Résout « annonces », « #annonces » ou « <#43> » en salon du serveur."""
    guild = getattr(message, "guild", None)
    if guild is None:
        return None, "On n'est pas sur un serveur : je ne peux poster qu'ici."
    voulu = demande.strip().strip("<>#").strip()
    if voulu.isdigit():
        salon = guild.get_channel(int(voulu))
    else:
        cible = voulu.lower()
        salon = next((c for c in guild.text_channels
                      if c.name.lower() == cible), None)
    if salon is None:
        return None, f"Je ne trouve aucun salon « {demande} » sur ce serveur."
    return salon, None


def _peut(salon: Any, membre: Any, droit: str) -> bool:
    try:
        return bool(getattr(salon.permissions_for(membre), droit, False))
    except (AttributeError, TypeError) as exc:
        logger.debug("Sondage: permissions illisibles ({e!r})", e=exc)
        return False


async def run_sondage_tool(bot: Any, args: dict[str, Any], *,
                           message: Any) -> str:
    """Exécute l'outil. Rend à Wally ce qu'il doit savoir pour en parler."""
    service: Optional[SondageService] = getattr(bot, "sondages", None)
    if service is None:
        return "Le sondage n'est pas branché, je ne peux pas en ouvrir."

    salon: Any = getattr(message, "channel", None)
    if salon is None:
        return "Je ne vois pas de salon où poster ce sondage."
    demande = str(args.get("salon") or "").strip()
    if demande:
        salon, erreur = _salon_demande(message, demande)
        if salon is None:
            return erreur or f"Je ne trouve pas le salon « {demande} »."
        auteur = getattr(message, "author", None)
        # Poster ailleurs PAR PROCURATION : le droit se vérifie sur le
        # DEMANDEUR, pas seulement sur Wally. Sans ça, n'importe qui écrit dans
        # un salon fermé en passant par lui.
        if not _peut(salon, auteur, "send_messages"):
            return (f"{getattr(auteur, 'display_name', 'Cette personne')} n'a pas "
                    f"le droit d'écrire dans #{salon.name} : je n'y poste pas.")
        moi = getattr(getattr(message, "guild", None), "me", None)
        if moi is not None and not _peut(salon, moi, "send_messages"):
            return f"Je n'ai pas le droit d'écrire dans #{salon.name}."

    if str(args.get("action") or "creer").lower() == "fermer":
        sondage = service.sondages.ouvert_dans(salon.id)
        if sondage is None:
            return "Aucun sondage ouvert ici : il n'y a rien à dépouiller."
        await service.fermer(sondage)
        return (f"{sondage.ligne_resultat()} Annonce le résultat avec tes mots, "
                "sans réciter les chiffres un par un.")

    if service.sondages.ouvert_dans(salon.id) is not None:
        return ("Un sondage est déjà ouvert dans ce salon. Ferme-le d'abord "
                "(`action: \"fermer\"`) si tu veux en lancer un autre.")

    options = [str(o) for o in (args.get("options") or [])]
    duree_s = None
    if args.get("duree_minutes"):
        minutes = max(_DUREE_MIN_MIN,
                      min(_DUREE_MAX_MIN, float(args["duree_minutes"])))
        duree_s = minutes * 60.0

    # Le ping est un SUPPLÉMENT : sans le droit, on perd le ping, pas le
    # sondage. Wally dit pourquoi — sinon la personne croit qu'il l'a ignorée.
    ping = bool(args.get("ping_everyone"))
    refus_ping = ""
    if ping:
        auteur = getattr(message, "author", None)
        moi = getattr(getattr(message, "guild", None), "me", None)
        if not _peut(salon, auteur, "mention_everyone"):
            ping, refus_ping = False, (
                " Je n'ai pas mis le @everyone : la personne qui l'a demandé n'a "
                "pas le droit de mentionner tout le serveur. Dis-le-lui.")
        elif moi is not None and not _peut(salon, moi, "mention_everyone"):
            ping, refus_ping = False, (
                " Je n'ai pas mis le @everyone : je n'ai pas ce droit ici.")

    sondage = await service.creer(
        salon=salon, question=str(args.get("question") or ""), options=options,
        auteur=str(getattr(getattr(message, "author", None), "display_name", "")),
        duree_s=duree_s, ping=ping)
    if sondage is None:
        return (f"Il me faut une question et au moins deux options "
                f"(j'en ai reçu {len(options)}).")

    ou = "" if not demande else f" dans #{salon.name}"
    quand = (f" Il se dépouille tout seul dans {int((duree_s or 0) // 60)} minutes."
             if duree_s else " Il reste ouvert jusqu'à ce qu'on demande à le fermer.")
    return (f"Sondage publié{ou} : « {sondage.question} », "
            f"{len(sondage.options)} options, les gens votent en cliquant les "
            f"boutons.{quand}{refus_ping} Annonce-le avec tes mots ; ne "
            "recopie pas les options, elles sont déjà à l'écran.")
