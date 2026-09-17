# bot/dashboard/routes/config_discord.py
"""Réglages Discord du panel admin (Serveur communautaire, salons, anti-spam).

Le catalogue sert tous les sélecteurs de salon du panel (`formulaires.js`) :
ids en CHAÎNES, jamais en nombres — un snowflake dépasse 2^53 et `JSON.parse`
l'arrondit en silence. Les écritures les reconvertissent en `int` : rangés en
chaînes, ils ne seraient jamais égaux à `channel.id` et le réglage ne viserait
rien, sans le dire.

Chaque réglage exposé ici est relu À CHAQUE ÉVÉNEMENT par son lecteur
(`bot.config.discord.…`, le même objet que `request.app.state.wally.config`) :
aucune écriture de cette page ne demande de redémarrage, sauf le scan complet
des emotes (cf. `salons_speciaux`).

Validation d'abord, mutation ensuite : une requête refusée (422) ne laisse
rien derrière elle en mémoire, et `config.save()` n'est appelé qu'une fois
tout accepté.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

admin_router = APIRouter()

# Plafond Discord du nom d'un salon.
_NOM_SALON_MAX = 100
# Une phrase d'accueil vit dans une fiche V2 plafonnée à 4 000 caractères,
# avec la fact et sa traduction : on la garde courte.
_MESSAGE_BIENVENUE_MAX = 300
_URL_MAX = 2000


@admin_router.get("/discord/catalogue")
async def catalogue(request: Request) -> dict:
    """Serveurs, salons textuels et vocaux, catégories et rôles que Wally voit."""
    bot = request.app.state.wally.discord_bot
    if bot is None:
        return {"guilds": []}
    guilds = []
    for g in bot.guilds:
        guilds.append({
            "id": str(g.id),
            "name": g.name,
            "text_channels": [{"id": str(c.id), "name": c.name} for c in g.text_channels],
            "voice_channels": [{"id": str(c.id), "name": c.name} for c in g.voice_channels],
            "categories": [{"id": str(c.id), "name": c.name} for c in g.categories],
            "roles": [{"id": str(r.id), "name": r.name} for r in g.roles
                      if not r.is_default()],
        })
    return {"guilds": guilds}


# ── Validation ──────────────────────────────────────────────────────────────

def _refus(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _id(brut: object, libelle: str) -> int | None:
    """Un snowflake (chaîne ou entier) → `int` ; vide ou `null` → None."""
    if brut is None or brut == "":
        return None
    if isinstance(brut, bool) or not isinstance(brut, (str, int)):
        raise _refus(f"{libelle} : identifiant invalide.")
    texte = str(brut).strip()
    if not texte.isdigit():
        raise _refus(f"{libelle} : « {texte} » n'est pas un identifiant Discord.")
    return int(texte)


def _ids(brut: object, libelle: str) -> list[int]:
    if brut is None:
        return []
    if not isinstance(brut, list):
        raise _refus(f"{libelle} : une liste est attendue.")
    sortie: list[int] = []
    for x in brut:
        v = _id(x, libelle)
        if v is not None and v not in sortie:
            sortie.append(v)
    return sortie


def _bool(brut: object, libelle: str) -> bool:
    if not isinstance(brut, bool):
        raise _refus(f"{libelle} : vrai ou faux attendu.")
    return brut


def _entier(brut: object, libelle: str, mini: int, maxi: int) -> int:
    if isinstance(brut, bool) or not isinstance(brut, (int, float, str)):
        raise _refus(f"{libelle} : un nombre entier est attendu.")
    try:
        v = float(brut)
    except ValueError as e:
        raise _refus(f"{libelle} : un nombre entier est attendu.") from e
    if not v.is_integer():
        raise _refus(f"{libelle} : un nombre entier est attendu.")
    if not (mini <= v <= maxi):
        raise _refus(f"{libelle} : entre {mini} et {maxi}.")
    return int(v)


def _textes(brut: object, libelle: str, maxi: int) -> list[str]:
    """Liste de chaînes : blancs retirés, lignes vides écartées, longueur bornée."""
    if brut is None:
        return []
    if not isinstance(brut, list) or not all(isinstance(x, str) for x in brut):
        raise _refus(f"{libelle} : une liste de textes est attendue.")
    sortie = [x.strip() for x in brut if x.strip()]
    for x in sortie:
        if len(x) > maxi:
            raise _refus(f"{libelle} : « {x[:40]}… » dépasse {maxi} caractères.")
    return sortie


def _nom_salon(brut: object, libelle: str) -> str:
    if not isinstance(brut, str) or not brut.strip():
        raise _refus(f"{libelle} : obligatoire.")
    nom = brut.strip()
    if len(nom) > _NOM_SALON_MAX:
        raise _refus(f"{libelle} : {_NOM_SALON_MAX} caractères au plus.")
    return nom


def _texte_id(v: int | None) -> str | None:
    return None if v is None else str(v)


def _requis(corps: dict, *cles: str) -> None:
    manquants = [c for c in cles if c not in corps]
    if manquants:
        raise _refus("Champs manquants : " + ", ".join(manquants) + ".")


# ── Serveur communautaire ───────────────────────────────────────────────────

def _communaute(d: Any) -> dict:
    st, jm, ss, bv = d.salons_temporaires, d.journal_moderation, d.statut_stream, d.bienvenue
    return {
        "salons_temporaires": {
            "actif": st.salon_createur_id is not None,
            "salon_createur_id": _texte_id(st.salon_createur_id),
            "noms": list(st.noms),
        },
        "journal_moderation": {
            "actif": bool(jm.salon_ids),
            "salon_ids": [str(i) for i in jm.salon_ids],
            "guild_ids": [str(i) for i in jm.guild_ids],
            "inclure_bots": jm.inclure_bots,
        },
        "statut_stream": {
            "actif": ss.salon_id is not None,
            "salon_id": _texte_id(ss.salon_id),
            "nom_live": ss.nom_live,
            "nom_hors_live": ss.nom_hors_live,
        },
        "bienvenue": {
            "actif": bool(bv.guild_ids),
            "salon_id": _texte_id(bv.salon_id),
            "guild_ids": [str(i) for i in bv.guild_ids],
            "messages": list(bv.messages),
            "gifs": list(bv.gifs),
        },
    }


@admin_router.get("/discord/communaute")
async def lire_communaute(request: Request) -> dict:
    return _communaute(request.app.state.wally.config.discord)


@admin_router.patch("/discord/communaute/salons_temporaires")
async def ecrire_salons_temporaires(request: Request, c: dict) -> dict:
    """`{actif, salon_createur_id, noms}`. Désactivé = `salon_createur_id: null`."""
    _requis(c, "actif", "salon_createur_id", "noms")
    actif = _bool(c["actif"], "Activé")
    createur = _id(c["salon_createur_id"], "Salon créateur")
    noms = _textes(c["noms"], "Noms des salons", _NOM_SALON_MAX)
    if actif and createur is None:
        raise _refus("Choisis le salon vocal créateur pour activer le module.")
    cfg = request.app.state.wally.config
    section = cfg.discord.salons_temporaires
    section.salon_createur_id = createur if actif else None
    section.noms = noms
    cfg.save()
    return _communaute(cfg.discord)


@admin_router.patch("/discord/communaute/journal_moderation")
async def ecrire_journal_moderation(request: Request, c: dict) -> dict:
    """`{actif, salon_ids, guild_ids, inclure_bots}`. Désactivé = `salon_ids: []`."""
    _requis(c, "actif", "salon_ids", "guild_ids", "inclure_bots")
    actif = _bool(c["actif"], "Activé")
    salons = _ids(c["salon_ids"], "Salons du journal")
    guildes = _ids(c["guild_ids"], "Serveurs observés")
    inclure_bots = _bool(c["inclure_bots"], "Inclure les bots")
    if actif and not salons:
        raise _refus("Choisis au moins un salon où publier le journal.")
    if actif and not guildes:
        # Sans serveur observé, `salons_cibles` ne publie rien : l'écran
        # annoncerait un journal actif qui reste muet.
        raise _refus("Choisis au moins un serveur à observer.")
    cfg = request.app.state.wally.config
    section = cfg.discord.journal_moderation
    section.salon_ids = salons if actif else []
    section.guild_ids = guildes
    section.inclure_bots = inclure_bots
    cfg.save()
    return _communaute(cfg.discord)


@admin_router.patch("/discord/communaute/statut_stream")
async def ecrire_statut_stream(request: Request, c: dict) -> dict:
    """`{actif, salon_id, nom_live, nom_hors_live}`. Désactivé = `salon_id: null`."""
    _requis(c, "actif", "salon_id", "nom_live", "nom_hors_live")
    actif = _bool(c["actif"], "Activé")
    salon = _id(c["salon_id"], "Salon renommé")
    nom_live = _nom_salon(c["nom_live"], "Nom pendant le live")
    nom_hors_live = _nom_salon(c["nom_hors_live"], "Nom hors live")
    if actif and salon is None:
        raise _refus("Choisis le salon à renommer pour activer le module.")
    cfg = request.app.state.wally.config
    section = cfg.discord.statut_stream
    section.salon_id = salon if actif else None
    section.nom_live = nom_live
    section.nom_hors_live = nom_hors_live
    cfg.save()
    return _communaute(cfg.discord)


@admin_router.patch("/discord/communaute/bienvenue")
async def ecrire_bienvenue(request: Request, c: dict) -> dict:
    """`{actif, salon_id, guild_ids, messages, gifs}`. Désactivé = `guild_ids: []`.

    `salon_id: null` n'éteint rien : la fiche part dans le salon système du serveur.
    """
    _requis(c, "actif", "salon_id", "guild_ids", "messages", "gifs")
    actif = _bool(c["actif"], "Activé")
    salon = _id(c["salon_id"], "Salon d'accueil")
    guildes = _ids(c["guild_ids"], "Serveurs accueillis")
    messages = _textes(c["messages"], "Phrases d'accueil", _MESSAGE_BIENVENUE_MAX)
    gifs = _textes(c["gifs"], "GIF", _URL_MAX)
    for g in gifs:
        if not g.startswith(("https://", "http://")):
            raise _refus(f"GIF : « {g[:40]} » n'est pas une adresse web.")
    if actif and not guildes:
        raise _refus("Choisis au moins un serveur où accueillir les nouveaux membres.")
    cfg = request.app.state.wally.config
    section = cfg.discord.bienvenue
    section.salon_id = salon
    section.guild_ids = guildes if actif else []
    section.messages = messages
    section.gifs = gifs
    cfg.save()
    return _communaute(cfg.discord)


# ── Salons au rôle particulier ──────────────────────────────────────────────

_MODES_FILTRE = ("blacklist", "whitelist")


def _salons_speciaux(d: Any) -> dict:
    return {
        "always_trigger_channels": [str(i) for i in d.always_trigger_channels],
        "channel_filter_mode": d.channel_filter_mode,
        "channel_whitelist": [str(i) for i in d.channel_whitelist],
        "per_guild_channel_whitelist": {
            str(g): (None if v is None else [str(i) for i in v])
            for g, v in (d.per_guild_channel_whitelist or {}).items()
        },
        "clips_channel_id": _texte_id(d.clips_channel_id),
        "meme_channel_id": _texte_id(d.meme_channel_id),
        "emote_guild_id": _texte_id(d.emote_guild_id),
        "emoji_reaction_probability": d.emoji_reaction_probability,
    }


@admin_router.get("/discord/salons-speciaux")
async def lire_salons_speciaux(request: Request) -> dict:
    return _salons_speciaux(request.app.state.wally.config.discord)


@admin_router.patch("/discord/salons-speciaux")
async def ecrire_salons_speciaux(request: Request, c: dict) -> dict:
    """Écriture partielle : seuls les champs présents sont modifiés.

    `per_guild_channel_whitelist` : `{guild_id: null | [salon_id, …]}` —
    `null` = tous les salons de ce serveur ; un serveur absent suit la règle
    générale (`channel_filter_mode`). Remplacement intégral du dictionnaire.
    """
    nouveau: dict[str, Any] = {}
    if "always_trigger_channels" in c:
        nouveau["always_trigger_channels"] = _ids(c["always_trigger_channels"], "Salons où tout message s'adresse à Wally")
    if "channel_filter_mode" in c:
        mode = c["channel_filter_mode"]
        if mode not in _MODES_FILTRE:
            raise _refus("Mode de filtrage : « blacklist » ou « whitelist ».")
        nouveau["channel_filter_mode"] = mode
    if "channel_whitelist" in c:
        nouveau["channel_whitelist"] = _ids(c["channel_whitelist"], "Liste blanche")
    if "per_guild_channel_whitelist" in c:
        brut = c["per_guild_channel_whitelist"]
        if not isinstance(brut, dict):
            raise _refus("Règles par serveur : un objet est attendu.")
        par_serveur: dict[str, list[int] | None] = {}
        for g, v in brut.items():
            gid = _id(g, "Règles par serveur")
            if gid is None:
                raise _refus("Règles par serveur : serveur sans identifiant.")
            # Clé en CHAÎNE : `_is_channel_allowed` cherche `str(guild_id)`.
            par_serveur[str(gid)] = None if v is None else _ids(v, "Règles par serveur")
        nouveau["per_guild_channel_whitelist"] = par_serveur
    for cle, libelle in (("clips_channel_id", "Salon des clips"),
                         ("meme_channel_id", "Salon de dépôt des memes"),
                         ("emote_guild_id", "Serveur des emotes")):
        if cle in c:
            nouveau[cle] = _id(c[cle], libelle)
    if "emoji_reaction_probability" in c:
        p = c["emoji_reaction_probability"]
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not (0 <= p <= 1):
            raise _refus("Probabilité de réaction : un nombre entre 0 et 1.")
        nouveau["emoji_reaction_probability"] = float(p)
    cfg = request.app.state.wally.config
    for cle, valeur in nouveau.items():
        setattr(cfg.discord, cle, valeur)
    if nouveau:
        cfg.save()
    return _salons_speciaux(cfg.discord)


# ── Anti-spam : sourdine sur colère ─────────────────────────────────────────

def _colere(d: Any) -> dict:
    return {"anger_trigger_threshold": d.anger_trigger_threshold,
            "timeout_minutes": d.timeout_minutes}


@admin_router.get("/discord/colere")
async def lire_colere(request: Request) -> dict:
    return _colere(request.app.state.wally.config.discord)


@admin_router.patch("/discord/colere")
async def ecrire_colere(request: Request, c: dict) -> dict:
    """`{anger_trigger_threshold, timeout_minutes}` (partiel accepté)."""
    nouveau: dict[str, int] = {}
    if "anger_trigger_threshold" in c:
        nouveau["anger_trigger_threshold"] = _entier(
            c["anger_trigger_threshold"], "Seuil de déclenchements", 1, 50)
    if "timeout_minutes" in c:
        nouveau["timeout_minutes"] = _entier(c["timeout_minutes"], "Durée de la sourdine", 1, 1440)
    cfg = request.app.state.wally.config
    for cle, valeur in nouveau.items():
        setattr(cfg.discord, cle, valeur)
    if nouveau:
        cfg.save()
    return _colere(cfg.discord)
