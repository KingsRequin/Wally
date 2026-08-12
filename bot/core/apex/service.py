# bot/core/apex/service.py
"""Les actions Apex offertes au LLM, rendues en texte lisible.

Le service ne décide de rien : il va chercher, met en forme, et dit clairement
quand il n'a pas. Ce qu'il ne sait pas faire est annoncé dans la description de
l'outil, pour que le modèle n'aille pas le chercher ailleurs.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from datetime import datetime
from io import BytesIO
from typing import Any

from loguru import logger

from bot.core.apex.client import ApexClient
from bot.core.apex.reader import PlayerProfile, read_profile
from bot.core.apex.widgets import (
    APEX_PANELS,
    craft_panel,
    map_panel,
    predator_panel,
    progress_panel,
    rank_panel,
    servers_panel,
    stats_panel,
    status_panel,
)


def _fr(n: int) -> str:
    """12345 → « 12 345 », lisible dans un chat."""
    return f"{n:,}".replace(",", " ")


def _depuis(quand: datetime) -> str:
    """« il y a 3 jours », « hier », « tout à l'heure » — daté, jamais vague."""
    from bot.core.apex.history import PARIS

    ecart = datetime.now(PARIS) - quand
    heures = ecart.total_seconds() / 3600
    if heures < 2:
        return "tout à l'heure"
    if heures < 24:
        return f"il y a {int(heures)} h"
    jours = int(heures // 24)
    return "hier" if jours == 1 else f"il y a {jours} jours"


def _classements(stat) -> str:
    """« (3ᵉ mondial, 2ᵉ sur PC) » — ou rien si l'API n'a pas encore calculé.

    Le rang plateforme arrivait à chaque appel et n'était jamais montré. C'est
    pourtant souvent le plus parlant : Azraël est 10ᵉ mondial aux wins avec Fuse,
    mais 3ᵉ sur PC. Ce n'est PAS un rang par pays — celui-là vit dans
    `/leaderboard`, fermé à notre clé.
    """
    morceaux = []
    if stat.world_pos is not None:
        mondial = f"{_rang(stat.world_pos)} mondial"
        # Le top % reste : « top 0.01 % » dit quelque chose que « 3ᵉ » ne dit
        # pas, et l'inverse est vrai aussi. Un test existant a résisté quand je
        # l'ai laissé tomber — il avait raison.
        if stat.top_percent is not None:
            mondial += f", top {stat.top_percent} %"
        morceaux.append(mondial)
    elif stat.top_percent is not None:
        morceaux.append(f"top {stat.top_percent} % mondial")
    if stat.platform_pos is not None:
        morceaux.append(f"{_rang(stat.platform_pos)} sur sa plateforme")
    return f" ({' — '.join(morceaux)})" if morceaux else ""


def _uid_valide(uid: str) -> str:
    """Un uid Apex est une suite de chiffres. Tout le reste est écarté ici,
    plutôt que d'être envoyé tel quel à l'API — le modèle confond volontiers
    « uid » et « pseudo »."""
    nettoye = str(uid or "").strip()
    return nettoye if nettoye.isdigit() else ""


def _rang(n: int) -> str:
    """1 → « 1ᵉʳ », 3 → « 3ᵉ ». Le premier ne se dit pas « 1ᵉ ».

    Azraël est 1ᵉʳ mondial aux dégâts avec Fuse : c'est le cas qui se voit."""
    return f"{_fr(n)}ᵉʳ" if n == 1 else f"{_fr(n)}ᵉ"


class ApexLegendsService:
    # Les libellés des modes, dans l'ordre d'intérêt. `wildcard` manquait :
    # c'est un mode qui tourne, et son absence donnait une rotation incomplète.
    _MODES = (
        ("battle_royale", "Battle Royale"),
        ("ranked", "Ranked"),
        ("ltm", "Mode temporaire"),
        ("wildcard", "Wildcard"),
    )

    def __init__(self, client: ApexClient | None = None, db: Any = None) -> None:
        self._client = client or ApexClient(os.environ.get("APEX_API_KEY", ""))
        self._db = db
        # Historique des compteurs (`ApexHistory`), branché après coup par
        # `main.py` — il a besoin de la base, que ce service ne construit pas.
        # Absent, tout marche comme avant : rien n'est consigné.
        self.history: Any = None
        # Quand le live en cours a commencé (`started_at` Twitch), branché par
        # `main.py`. Absent ou hors live, « ce stream » retombe sur le dernier
        # bloc de jeu lu dans les relevés.
        self.debut_du_live: Any = None
        # Points de la dernière progression calculée, PAR DEMANDEUR : le
        # handler vient y chercher de quoi tracer la courbe juste après l'appel
        # d'outil. Clé par demandeur et non globale, sinon deux questions
        # simultanées (Discord et Twitch) se voleraient leur graphe.
        # Borné : sans plafond, ce dict grossirait indéfiniment — c'est
        # exactement ce qui est arrivé au cache de `client.py`.
        # (points, notion, titre, relevés de RP)
        self._progressions: OrderedDict[str, tuple[list, str, str, list]] = OrderedDict()

    @property
    def available(self) -> bool:
        return bool(self._client.available)

    def get_tool_definition(self) -> dict:
        from bot.core.apex.tool import APEX_LEGENDS_TOOL
        return APEX_LEGENDS_TOOL

    async def execute(
        self,
        action: str,
        player_name: str = "",
        platform: str = "PC",
        *,
        remember: bool = False,
        requester: str | None = None,
        requester_name: str = "",
        legend: str = "",
        uid: str = "",
        period: str = "live",
        notion: str = "kills",
        peut_joindre_image: bool = False,
        ecran_disponible: bool = False,
    ) -> str:
        """Exécute une action. `requester` vient du HANDLER, jamais du modèle :
        c'est ce qui empêche quiconque de déclarer le compte d'un autre.

        `peut_joindre_image` dit si le canal sait porter une pièce jointe —
        vrai sur Discord, faux dans un chat Twitch. Le modèle doit le savoir :
        sans ça, il fabrique une URL vers une image imaginaire.

        `ecran_disponible` dit qu'un live tourne et que l'overlay écoute : dans
        un chat sans pièce jointe, c'est la SEULE sortie visuelle qui reste, et
        le modèle ne la trouve pas tout seul — il s'excuse de ne pas pouvoir
        envoyer d'image et en reste là.
        """
        if action == "player_stats":
            return await self._player_stats(
                player_name, platform,
                remember=remember, requester=requester, requester_name=requester_name,
                legend=legend, uid=uid,
            )
        if action == "progression":
            return await self._progression(
                player_name, platform, period=period, notion=notion or "kills",
                requester=requester, uid=uid, peut_joindre_image=peut_joindre_image,
                ecran_disponible=ecran_disponible,
            )
        if action == "map_rotation":
            return await self._map_rotation()
        if action == "crafting":
            return await self._crafting()
        if action == "predator":
            return await self._predator()
        if action == "server_status":
            return await self._server_status()
        return f"Action inconnue : {action}"

    # ── Le profil d'un joueur ─────────────────────────────────────────────────

    async def _player_stats(
        self,
        player_name: str,
        platform: str,
        *,
        remember: bool = False,
        requester: str | None = None,
        requester_name: str = "",
        legend: str = "",
        uid: str = "",
    ) -> str:
        cherche, platform = await self._resolve(player_name, platform, requester)
        # Un uid DONNÉ l'emporte sur celui qu'on avait mémorisé : c'est le seul
        # recours quand la recherche par pseudo échoue (cf. `_introuvable`).
        uid = _uid_valide(uid) or (await self._resolve_uid(requester, player_name) or "")
        if not cherche and not uid:
            return "Il me faut un pseudo Apex pour chercher."
        data = await self._client.get(
            "bridge", {**({"uid": uid} if uid else {"player": cherche}),
                       "platform": platform or "PC"}
        )
        if isinstance(data, str):
            return data
        profil = read_profile(data)
        if profil is None:
            erreur = str(data.get("Error") or "") if isinstance(data, dict) else ""
            return self._introuvable(cherche, erreur, cherche_par_uid=bool(uid))
        if remember and requester:
            await self._remember(profil, cherche, platform, requester, requester_name)
        rendu = self._render_profile(profil, legend=legend)
        # Les comptes qu'on ne sonde pas n'ont pour historique que leurs
        # consultations : c'est ici, et nulle part ailleurs, qu'ils en gagnent un.
        if rappel := await self._comparer_a_la_derniere_fois(profil):
            rendu = f"{rendu}\n{rappel}"
        return rendu

    async def _comparer_a_la_derniere_fois(self, profil: PlayerProfile) -> str:
        """« +124 kills depuis la dernière fois qu'on a regardé », ou "".

        L'ordre compte : on consigne le relevé courant AVANT de chercher le
        précédent, sinon la comparaison porterait sur des chiffres périmés.
        """
        # `getattr` et non `self.history` : le service est parfois construit
        # sans passer par `__init__` (doublures de test, `__new__`), et un
        # profil affiché ne doit pas dépendre de la présence de l'historique.
        historique = getattr(self, "history", None)
        if historique is None or not profil.uid:
            return ""
        stats = {k: s.value for k, s in profil.stats.items()}
        if not stats:
            return ""
        ts = time.time()
        try:
            await historique.enregistrer(profil.uid, stats, maintenant=ts)
            progression = await historique.depuis_derniere_consultation(
                profil.uid, "kills", avant=ts
            )
        except Exception as exc:  # noqa: BLE001 — l'historique est un bonus
            logger.warning("Apex: historique indisponible: {e}", e=exc)
            return ""
        if progression is None or progression.gain <= 0:
            return ""
        return (
            f"Depuis la dernière fois qu'on a regardé son compte "
            f"({_depuis(progression.depuis)}) : +{progression.gain} kills."
        )

    # ── La progression dans le temps ─────────────────────────────────────────

    async def _progression(
        self,
        player_name: str,
        platform: str,
        *,
        period: str,
        notion: str,
        requester: str | None,
        uid: str,
        peut_joindre_image: bool = False,
        ecran_disponible: bool = False,
    ) -> str:
        """Ce qu'un compteur a gagné sur une période, d'après nos relevés.

        L'API ne donne que des totaux à vie : ce chiffre-là n'existe que parce
        qu'on relève les compteurs au fil du temps. Il ne peut donc pas remonter
        avant le premier relevé, et on le dit quand c'est le cas.
        """
        historique = getattr(self, "history", None)
        if historique is None:
            return ("Je ne garde pas encore d'historique des compteurs, "
                    "je ne peux pas calculer de progression.")

        # Le compte visé et son NOM, lus d'un seul coup : le refus doit pouvoir
        # dire de qui il parle (cf. plus bas).
        lien = await self._lien(player_name, requester)
        cible = _uid_valide(uid) or ((lien["uid"] or "") if lien else "")
        nom_cible = (lien["apex_name"] if lien else "") or player_name.strip()
        if not cible:
            profil = await self.fetch_profile(
                *(await self._resolve(player_name, platform, requester))
            )
            cible = profil.uid if profil else ""
            nom_cible = (profil.name if profil else "") or nom_cible
        if not cible:
            return ("Il me faut savoir de quel compte Apex on parle pour suivre "
                    "sa progression.")

        try:
            fenetre = await self._fenetre(period, cible)
        except ValueError as refus:
            return str(refus)
        libelle_periode = fenetre.libelle

        progression = await historique.progression(cible, notion, fenetre.depuis)
        if progression is None:
            # Le refus NOMME le compte. Sans ça, « aucun relevé de ce compte »
            # se lit comme « aucun relevé d'Azraël » alors qu'on vient
            # d'interroger, faute de pseudo, celui de la personne qui parle —
            # et Wally annonce au chat une absence de données qui est fausse.
            qui = f"du compte {nom_cible}" if nom_cible else "de ce compte"
            texte = (f"Je n'ai aucun relevé {qui} sur cette période — "
                     f"je ne peux pas inventer sa progression.")
            if not player_name.strip() and not _uid_valide(uid):
                texte += (" C'est le compte de la personne à qui tu réponds, "
                          "faute de pseudo précisé : si la question portait sur "
                          "quelqu'un d'autre, rappelle-moi avec player_name.")
            return texte

        from bot.core.apex.chart import libelle as libelle_notion

        # Retenue SEULEMENT si le canal sait la porter : une courbe rangée pour
        # un chat Twitch ne serait jamais consommée, et attendrait là que la
        # même personne pose une question sur Discord.
        if peut_joindre_image:
            # Les relevés de RP partent avec les points : sans eux l'image
            # Discord serait monochrome là où l'overlay, sur la MÊME fenêtre,
            # colorerait les parties classées. Deux vérités pour les mêmes
            # parties, c'est exactement ce que la garde côté serveur cherchait
            # déjà à éviter pour le panneau.
            self._retenir_courbe(
                requester, progression.points, notion,
                f"{libelle_notion(notion).capitalize()} — {libelle_periode}",
                rp=await historique.rp_de_la_fenetre(cible, fenetre.depuis),
            )
        texte = (f"{libelle_periode.capitalize()} : "
                 f"+{_fr(progression.gain)} {libelle_notion(notion)}")
        # Un total qui ne couvre pas la période demandée doit le dire : « ce
        # mois-ci » alors qu'on ne mesure que depuis le 12 serait un chiffre
        # faux présenté comme complet.
        if progression.couverture_partielle:
            texte += (f" — mais je ne mesure ce compte que depuis le "
                      f"{progression.depuis.strftime('%d/%m à %Hh%M')}, "
                      f"donc c'est un minimum, pas le total de la période")
        texte += "."
        # Sans cette phrase, le modèle FABRIQUE une URL vers une image
        # imaginaire (« ![Courbe](https://…/progression-chart/…) ») : il a par
        # ailleurs consigne de citer ses sources en lien Markdown, et rien ne
        # lui disait que le graphe voyage déjà avec sa réponse.
        if peut_joindre_image:
            texte += (
                " [La courbe part AVEC ta réponse, en pièce jointe. N'écris "
                "aucun lien, aucune URL, aucune image Markdown : elle est déjà "
                "là. Contente-toi de commenter ce qu'elle montre.]"
            )
        elif ecran_disponible:
            # Sans cette phrase, « affiche la courbe » sur Twitch se terminait
            # par des excuses : le modèle constatait qu'il ne pouvait pas
            # envoyer d'image et n'allait pas chercher la seule sortie visuelle
            # qui lui restait — l'écran du stream, que les spectateurs voient.
            qui = f" player={nom_cible}" if nom_cible else ""
            texte += (
                " [Ce chat ne porte pas d'image, mais le live tourne : mets la "
                f"courbe SUR L'ÉCRAN maintenant avec `show_apex` panel=progress"
                f"{qui}, puis commente-la. N'invente aucun lien et ne t'excuse "
                "pas de ne pas pouvoir montrer d'image — tu peux.]"
            )
        else:
            texte += (
                " [Tu ne peux pas envoyer d'image ici : donne les chiffres, et "
                "n'invente surtout pas de lien vers un graphique.]"
            )
        return texte

    _MAX_COURBES = 20

    def _retenir_courbe(
        self, requester: str | None, points: list, notion: str, titre: str,
        *, rp: list | None = None,
    ) -> None:
        self._progressions[requester or ""] = (points, notion, titre, rp or [])
        while len(self._progressions) > self._MAX_COURBES:
            self._progressions.popitem(last=False)

    async def derniere_courbe(self, requester: str | None) -> BytesIO | None:
        """Le PNG de la dernière progression demandée par `requester`, ou None.

        Consommée : une courbe ne s'attache qu'une fois, sinon la question
        suivante de la même personne repartirait avec le graphe de la
        précédente.

        Le rendu part dans un thread — l'import de matplotlib et le tracé
        coûtent près d'une seconde, que la boucle asyncio ne doit pas passer
        à attendre.
        """
        retenu = self._progressions.pop(requester or "", None)
        if retenu is None:
            return None
        points, notion, titre, rp = retenu
        from bot.core.apex import chart

        try:
            return await asyncio.to_thread(chart.render, points, notion, titre, rp=rp)
        except Exception as exc:  # noqa: BLE001 — pas de graphe ≠ pas de réponse
            logger.warning("Apex: courbe non rendue: {e}", e=exc)
            return None

    def _introuvable(self, cherche: str, erreur: str, *, cherche_par_uid: bool) -> str:
        """Ce qu'on répond quand l'API ne trouve pas — en disant quoi faire.

        Beaucoup de comptes bien réels sont absents de la recherche par PSEUDO :
        l'API délègue à un « low priority search service » qui ne les indexe pas.
        `IBrainroTI67` en est un — introuvable par nom sur les trois plateformes,
        y compris depuis leur propre site, mais parfaitement lisible par uid.

        Sans cette explication, « pas trouvé » se lit comme « ce joueur n'existe
        pas », et personne ne pense à donner son uid.
        """
        if cherche_par_uid:
            return (
                f"Aucun compte Apex derrière cet uid ({erreur or 'inconnu'}). "
                "Vérifie le numéro."
            )
        return (
            f"{cherche} : introuvable par pseudo ({erreur or 'compte inconnu'}). "
            "La recherche par nom de l'API rate des comptes pourtant bien réels — "
            "ce n'est pas forcément une faute de frappe. Demande son uid Apex "
            "(le nombre à la fin de l'URL de sa page sur apexlegendsstatus.com) "
            "et rappelle-moi avec le paramètre `uid`."
        )

    async def fetch_profile(
        self, player: str, platform: str = "PC", uid: str | None = None
    ) -> PlayerProfile | None:
        """Le profil d'un joueur, ou None. Brique commune au texte, aux panneaux
        et au suivi passif — un seul endroit qui sait interroger `/bridge`.

        `uid` l'emporte sur le pseudo quand on l'a : un pseudo se change, un uid
        non — et l'API accepte les deux.
        """
        if not player and not uid:
            return None
        params = {"uid": uid} if uid else {"player": player}
        data = await self._client.get("bridge", {**params, "platform": platform or "PC"})
        if isinstance(data, str):
            return None
        return read_profile(data)

    async def _resolve(
        self, player_name: str, platform: str, requester: str | None
    ) -> tuple[str, str]:
        """Le pseudo Apex à interroger, et sur quelle plateforme.

        Un pseudo de plateforme (« xeforce_ ») est traduit en compte Apex si la
        personne l'a déclaré ; sans pseudo du tout, on prend celui du demandeur.
        Faute de liaison, on interroge tel quel — l'API tranchera.
        """
        lien = await self._lien(player_name, requester)
        if lien is None:
            return player_name, platform
        return lien["apex_name"], lien["apex_platform"] or platform

    async def _lien(self, player_name: str, requester: str | None):
        """La ligne de liaison, lue UNE fois.

        `_resolve` et `_resolve_uid` exécutaient exactement la même requête et
        n'en extrayaient chacune qu'une colonne : deux allers-retours SQLite
        pour une seule ligne, sur le chemin chaud `player_stats` comme sur
        `build_panel`. Et surtout deux résultats potentiellement DIFFÉRENTS si
        la liaison changeait entre les deux appels — le pseudo venait alors
        d'une ligne et l'uid d'une autre.
        """
        if self._db is None:
            return None
        try:
            return (
                await self._db.apex_find_by_display_name(player_name)
                if player_name
                else (await self._db.apex_get_account(requester) if requester else None)
            )
        except Exception as e:                       # une base grippée ne casse pas la recherche
            logger.warning("Apex: lecture des comptes liés impossible: {e}", e=e)
            return None

    async def _resolve_uid(self, requester: str | None, player_name: str) -> str | None:
        """L'uid mémorisé du joueur visé, s'il y en a un."""
        lien = await self._lien(player_name, requester)
        return (lien["uid"] or None) if lien else None

    async def _remember(
        self, profil, cherche: str, platform: str, requester: str, requester_name: str
    ) -> None:
        """Écrit la liaison — pour le DEMANDEUR, et seulement si le compte existe."""
        if self._db is None:
            return
        try:
            # Le nom OFFICIEL rendu par l'API, pas celui qui a été tapé : la
            # casse diffère (`Azrael_ttv` → `Azrael_TTV`), et surtout une
            # recherche par uid n'a pas de pseudo à mémoriser.
            nom = profil.name or cherche
            await self._db.apex_link_account(
                identity=requester,
                display_name=requester_name or requester,
                apex_name=nom,
                apex_platform=platform or "PC",
                uid=profil.uid or None,
            )
            logger.info(
                "Apex: compte {name} lié à {who}", name=nom, who=requester_name or requester
            )
        except Exception as e:
            logger.warning("Apex: impossible de mémoriser le compte: {e}", e=e)

    def _render_profile(self, p: PlayerProfile, legend: str = "") -> str:
        lignes = [f"{p.name} — niveau {_fr(p.level)} ({p.platform})"]
        if p.rank:
            rang = f"Rang BR : {p.rank.name}"
            if p.rank.div:
                rang += f" {p.rank.div}"
            rang += f" ({_fr(p.rank.score)} RP)"
            if p.rank.top_percent is not None:
                rang += f" — top {p.rank.top_percent} % du ladder"
            lignes.append(rang)
        etat = p.state or "état inconnu"
        if p.legend:
            etat += f", sur {p.legend}"
        lignes.append(f"État : {etat}")
        if p.banned:
            lignes.append(f"⚠️ Banni ({p.ban_reason or 'raison inconnue'})")
        for stat in p.stats.values():
            lignes.append(f"{stat.label} : {_fr(stat.value)}{_classements(stat)}")
        lignes += self._render_legends(p, legend)
        return "\n".join(lignes)

    def _render_legends(self, p: PlayerProfile, legende: str = "") -> list[str]:
        """Les chiffres par légende, ou l'explication de leur absence.

        Sans `legende`, un résumé trié par kills — c'est ce qui permet de
        répondre « avec quelle légende il tape le plus ». Avec, le détail de
        celle-là seulement.

        Un joueur ne publie que ce qu'il a ÉPINGLÉ en jeu : Azraël suit 17
        légendes, KingsRequin 4. Une légende absente n'a pas zéro kill, elle n'a
        pas de compteur — et le dire évite d'inventer un chiffre rassurant.
        """
        if not p.legend_stats:
            return ["(aucun compteur par légende épinglé sur ce compte)"]

        if legende:
            cherchee = legende.strip().lower()
            trouvee = next(
                (nom for nom in p.legend_stats if nom.lower() == cherchee), None
            )
            if trouvee is None:
                suivies = ", ".join(sorted(p.legend_stats))
                return [
                    f"Pas de compteur pour {legende} chez {p.name} — il ne l'a pas "
                    f"épinglé en jeu, ce n'est pas un zéro. Légendes suivies : {suivies}."
                ]
            detail = []
            for stat in p.legend_stats[trouvee].values():
                detail.append(f"  {stat.label} : {_fr(stat.value)}{_classements(stat)}")
            return [f"Avec {trouvee} :", *detail]

        # Résumé BORNÉ : Azraël suit 17 légendes, et déballer les trois notions
        # de chacune à chaque `player_stats` noierait le rang et l'état sous
        # cinquante lignes. Le podium répond à « avec quoi il tape le plus » ;
        # les autres noms suffisent pour savoir quoi redemander en détail.
        classees = sorted(
            p.legend_stats.items(),
            key=lambda kv: kv[1]["kills"].value if "kills" in kv[1] else -1,
            reverse=True,
        )
        lignes = ["Par légende (seulement celles qu'il suit en jeu) :"]
        for nom, notions in classees[:3]:
            morceaux = [f"{s.label.lower()} {_fr(s.value)}" for s in notions.values()]
            lignes.append(f"  {nom} : " + ", ".join(morceaux))
        reste = [nom for nom, _ in classees[3:]]
        if reste:
            lignes.append(
                "  aussi suivies (redemande avec `legend` pour le détail) : "
                + ", ".join(sorted(reste))
            )
        return lignes

    # ── Les panneaux de l'overlay ─────────────────────────────────────────────

    async def build_panel(
        self,
        panel: str,
        player: str = "",
        platform: str = "PC",
        *,
        requester: str | None = None,
        period: str = "live",
        notion: str = "kills",
    ) -> dict | None:
        """Le contenu d'un panneau d'overlay, prêt à publier — ou None.

        Le modèle ne fournit aucun chiffre : il nomme un panneau, on va chercher
        la donnée. None quand elle manque, pour ne jamais afficher de carte vide.
        """
        if panel not in APEX_PANELS:
            return None
        if panel in ("rank", "status", "stats", "progress"):
            cherche, platform = await self._resolve(player, platform, requester)
            uid = await self._resolve_uid(requester, player)
            if not cherche and not uid:
                return None
            data = await self._client.get(
                "bridge", {**({"uid": uid} if uid else {"player": cherche}),
                           "platform": platform or "PC"}
            )
            if isinstance(data, str):
                return None
            profil = read_profile(data)
            if panel == "progress":
                try:
                    fenetre = await self._fenetre(
                        period, profil.uid if profil else ""
                    )
                except ValueError as refus:
                    # Rien à l'écran plutôt qu'une carte sur une fenêtre
                    # inventée : le modèle apprend le refus par `apex_legends`,
                    # qui rend le texte de l'erreur.
                    logger.info("Apex: panneau de courbe refusé — {r}", r=refus)
                    return None
                if not await self._a_de_quoi_tracer(profil, fenetre, notion):
                    return None
                built = progress_panel(profil, fenetre=fenetre, notion=notion)
            else:
                built = {"rank": rank_panel, "status": status_panel,
                         "stats": stats_panel}[panel](profil)
        else:
            endpoint, params, builder = {
                "map": ("maprotation", {"version": "2"}, map_panel),
                "craft": ("crafting", None, craft_panel),
                "predator": ("predator", None, predator_panel),
                "servers": ("servers", None, servers_panel),
            }[panel]
            data = await self._client.get(endpoint, params)
            if isinstance(data, str):
                return None
            built = builder(data)
        return {"kind": f"apex_{panel}", **built} if built else None

    async def _fenetre(self, period: str, uid: str):
        """La fenêtre demandée, « ce stream » résolu. Lève `ValueError`.

        Le parseur ne connaît ni Twitch ni la base : c'est ici qu'on lui dit
        quand le stream a commencé.
        """
        from bot.core.apex.periode import parse_periode

        return parse_periode(period, debut_stream=await self._debut_du_stream(uid))

    async def _debut_du_stream(self, uid: str) -> float | None:
        """Le début du live en cours ou, à défaut, du dernier bloc de jeu.

        Le repli est ce qui fait marcher « la courbe du stream » une fois le
        stream fini — et aussi quand le bot a redémarré en pleine soirée et ne
        connaît plus le `started_at` du live qu'il traverse.
        """
        rappel = getattr(self, "debut_du_live", None)
        if callable(rappel):
            try:
                debut = rappel()
            except Exception as exc:  # noqa: BLE001 — une sonde cassée n'est pas fatale
                logger.debug("Apex: début du live indisponible: {e}", e=exc)
                debut = None
            if debut:
                return float(debut)
        historique = getattr(self, "history", None)
        # `getattr` sur la MÉTHODE, pas un try/except large : une doublure sans
        # cette méthode doit se voir, pas être avalée avec les pannes de base.
        derniere = getattr(historique, "debut_derniere_session", None)
        if derniere is None or not uid:
            return None
        try:
            return await derniere(uid)
        except Exception as exc:  # noqa: BLE001 — pas de session ≠ pas de réponse
            logger.warning("Apex: dernière session illisible: {e}", e=exc)
            return None

    async def _a_de_quoi_tracer(self, profil, fenetre, notion: str) -> bool:
        """Y a-t-il assez de relevés pour que l'image existe vraiment ?

        Le panneau ne porte qu'une URL : sans cette garde, la carte part à
        l'écran au nom du joueur, l'image répond 404, et le navigateur ne peut
        plus que retirer ce qu'il a déjà montré. Wally, lui, a déjà annoncé au
        chat qu'elle était affichée. Le 2026-08-12, une demande de courbe sans
        pseudo est ainsi partie sur le compte du DEMANDEUR, qui n'est pas
        sondé : les spectateurs ont vu un nom et rien d'autre.

        Sans historique branché (il l'est par `main.py`, après coup), on ne sait
        pas : on publie comme avant plutôt que de faire disparaître un panneau.
        """
        from bot.core.apex.chart import MIN_POINTS

        historique = getattr(self, "history", None)
        if historique is None:
            return True
        if profil is None or not profil.uid:
            return False
        try:
            progression = await historique.progression(
                profil.uid, notion, fenetre.depuis
            )
        except Exception as exc:  # noqa: BLE001 — l'overlay ne casse pas pour ça
            logger.warning("Apex: relevés illisibles pour le panneau: {e}", e=exc)
            return False
        if progression is None or len(progression.points) < MIN_POINTS:
            logger.info(
                "Apex: panneau de courbe refusé — pas assez de relevés pour "
                "{uid} ({notion}, {periode})",
                uid=profil.uid, notion=notion, periode=fenetre.libelle,
            )
            return False
        return True

    # ── L'état du jeu ─────────────────────────────────────────────────────────

    async def _map_rotation(self) -> str:
        data = await self._client.get("maprotation", {"version": "2"})
        if isinstance(data, str):
            return data
        lignes = []
        for cle, nom in self._MODES:
            mode = data.get(cle)
            if not isinstance(mode, dict):
                continue
            courant = mode.get("current") or {}
            suivant = mode.get("next") or {}
            ligne = f"{nom} : {courant.get('map', '?')}"
            if courant.get("remainingTimer"):
                ligne += f" (encore {courant['remainingTimer']})"
            if suivant.get("map"):
                ligne += f" → puis {suivant['map']}"
            lignes.append(ligne)
        return "\n".join(lignes) or "Pas de rotation disponible."

    async def _crafting(self) -> str:
        data = await self._client.get("crafting")
        if isinstance(data, str):
            return data
        if not isinstance(data, list):
            return "Pas de données de craft."
        lignes = []
        for lot in data:
            if not isinstance(lot, dict):
                continue
            objets = [
                (o.get("itemType") or {}).get("name", "?")
                for o in lot.get("bundleContent") or []
            ]
            if objets:
                lignes.append(f"{lot.get('bundleType', '?')} : {', '.join(objets)}")
        return "\n".join(lignes) or "Pas de données de craft."

    async def _predator(self) -> str:
        """Seuil Predator. L'API ne publie plus que `RP` : les arènes ont disparu."""
        data = await self._client.get("predator")
        if isinstance(data, str):
            return data
        rp = (data or {}).get("RP") or {}
        lignes = []
        for cle, nom in (("PC", "PC"), ("PS4", "PS4"), ("X1", "Xbox")):
            info = rp.get(cle)
            if not isinstance(info, dict):
                continue
            ligne = f"{nom} : {info.get('val', '?')} RP pour être Predator"
            if info.get("totalMastersAndPreds") is not None:
                ligne += f" ({info['totalMastersAndPreds']} Masters+Preds)"
            lignes.append(ligne)
        return "\n".join(lignes) or "Pas de données Predator."

    async def _server_status(self) -> str:
        data = await self._client.get("servers")
        if isinstance(data, str):
            return data
        lignes = []
        for groupe in (data or {}).values():
            if not isinstance(groupe, dict):
                continue
            for nom, info in groupe.items():
                if isinstance(info, dict) and info.get("Status"):
                    marque = "✅" if info["Status"] == "UP" else "❌"
                    lignes.append(f"{marque} {nom} : {info['Status']}")
        return "\n".join(lignes[:10]) or "Pas de données serveurs."
