from __future__ import annotations

# Registre déclaratif des capacités « à bascule » : (condition, phrase_active,
# phrase_inactive). Chaque condition lit l'état RÉEL depuis la config (source de
# vérité déclarative), jamais une valeur écrite à la main dans CAPABILITIES.md —
# c'est ce qui évite la fossilisation du self-model. Ajouter une capacité future =
# une entrée ici.
_TOGGLE_CAPABILITIES = [
    (
        lambda c: bool(getattr(getattr(c, "voice", None), "enabled", False)),
        "Je peux entendre et parler en vocal dans les salons audio.",
        "Le vocal existe dans mon code mais il n'est pas activé pour l'instant.",
    ),
]

_SECTION_TITLE = "## Mes capacités techniques actuelles"

# Ce que Wally peut montrer sur l'overlay, en langage de personne — pas la liste
# des identifiants techniques. La liste est DÉRIVÉE de `OverlayNarrator._WIDGETS`
# plutôt que recopiée : deux listes divergeraient, et il finirait par promettre
# un widget retiré ou ignorer un widget ajouté.
_WIDGET_WORDS = {
    "coinflip": "un pile ou face",
    "dice": "un ou plusieurs dés",
    "wheel": "une roue qui tranche entre plusieurs options",
    "poll": "un sondage où le chat vote en tapant un numéro",
    "countdown": "un compte à rebours",
    "gauge": "une jauge de progression",
    "counter": "un texte court",
    "pinned": "un message du chat mis en avant",
    "uptime": "depuis combien de temps ça stream",
    "stats": "les stats Apex d'un joueur",
    "versus": "la comparaison de deux joueurs",
    "bingo": "un bingo du stream que je coche au fur et à mesure",
    "prediction": "un pari sur l'issue d'une partie, avec mon score cumulé",
    "meme": "un meme de la communauté (je ne le vois pas, je connais sa description)",
    "rps": "un chifoumi où le chat vote contre moi",
    "hangman": "un pendu où le chat propose des lettres",
    "quote": "une réplique que j'ai entendue en vocal, ressortie plus tard",
    "goal": "un objectif de follows ou d'abonnements qui se remplit tout seul",
    "wave": "un signal quand le chat spamme le même emote",
    "talkers": "le classement des plus bavards du chat",
    "clip": "une alerte quand quelqu'un crée un clip",
    "planning": "le planning des streams de la semaine",
}


def _overlay_line() -> str:
    """Phrase récapitulant ce que Wally sait afficher, tirée du code réel."""
    try:
        from bot.intelligence.overlay_narrator import OverlayNarrator
        widgets = OverlayNarrator._WIDGETS
    except Exception:  # noqa: BLE001 — un self-model ne casse jamais un prompt
        return ""
    known = [_WIDGET_WORDS[w] for w in widgets if w in _WIDGET_WORDS]
    if not known:
        return ""
    return (
        "Pendant un live, je peux afficher des choses sur l'overlay que regardent "
        "les spectateurs (ils le voient, le streamer non) : " + ", ".join(known) + ". "
        "Je peux aussi tenir des compteurs qui durent d'un stream à l'autre "
        "(« combien de fois il dit qu'il a pas rechargé »), les arrêter et les "
        "lister. C'est moi qui décide d'afficher ou non — et hors live, rien ne "
        "s'affiche."
    )

_IMAGE_OFF = (
    "Fabriquer une image de ma propre initiative, je ne peux pas pour l'instant : "
    "il faut que quelqu'un déclenche `/image`."
)


_IMAGE_SANS_NOMS = (
    "Je peux décider tout seul de fabriquer une image et de la poster dans les "
    "salons prévus pour ça — personne n'a besoin de me la demander."
)


def _image_line(channels: list[str] | None, config) -> str:
    """Ce qu'il peut faire d'une image, dérivé des salons RÉELLEMENT ouverts.

    `channels` porte les NOMS des salons quand l'appelant les connaît (ils
    viennent de `CHANNELS.md`, que la config ne connaît pas). Une liste vide dit
    « éteint », et `None` dit « je ne sais pas les nommer » — dans ce dernier cas
    on retombe sur la config, jamais sur le contraire de la vérité : le chemin
    conversationnel affirmait sinon qu'il ne peut pas, pendant que le chemin
    cognitif lui donnait l'action.
    """
    if channels is None:
        cfg = getattr(config, "image_generation", None)
        # La boucle cognitive est le SEUL chemin qui décide d'une image tout
        # seul : capacité éteinte, l'action n'existe nulle part, quoi que dise
        # la section `image_generation`.
        cog = getattr(config, "cognitive_loop", None) or {}
        cog_on = cog.get("enabled", False) if isinstance(cog, dict) else getattr(cog, "enabled", False)
        ouvert = (
            bool(cog_on)
            and bool(getattr(cfg, "autonomous_enabled", False))
            and bool(getattr(cfg, "autonomous_channel_ids", None))
        )
        return _IMAGE_SANS_NOMS if ouvert else _IMAGE_OFF
    salons = [c for c in channels if c]
    if not salons:
        return _IMAGE_OFF
    return (
        "Je peux décider tout seul de fabriquer une image et de la poster dans "
        + ", ".join(salons)
        + " — personne n'a besoin de me la demander. Ça coûte de l'argent, donc "
        "je le fais quand l'image apporte vraiment quelque chose."
    )


_WEB_ON = (
    "Je peux chercher sur le web de moi-même quand une vraie curiosité me prend, "
    "même sans qu'on me le demande."
)
_WEB_OFF = (
    "Je pourrais chercher sur le web, mais c'est indisponible pour l'instant."
)


def build_self_model(static_text: str, config, *, web_available: bool = False,
                     image_channels: list[str] | None = None) -> str:
    """Assemble le self-model : narratif statique + capacités dérivées de l'état réel.

    `static_text` = CAPABILITIES.md nettoyé (vérités de personnage stables).
    `config` = la config runtime ; chaque capacité à bascule est évaluée contre elle.
    `web_available` = dispo RÉELLE de la recherche web (Tavily configuré). Dérivée
    d'un flag plutôt que de `config` car la clé vit dans l'environnement, pas la config.
    `image_channels` = les NOMS des salons où il peut poster une image de sa propre
    initiative (vide = capacité éteinte). Passés en argument et non recalculés ici :
    les noms viennent de `CHANNELS.md`, que la config ne connaît pas.

    Fonction pure : aucune I/O, insensible à l'ordre de montage. Un `config`
    malformé fait juste tomber une capacité en « inactive », jamais une exception.
    """
    lines = []
    for condition, on_text, off_text in _TOGGLE_CAPABILITIES:
        try:
            active = bool(condition(config))
        except Exception:
            active = False
        lines.append(f"- {on_text if active else off_text}")
    lines.append(f"- {_WEB_ON if web_available else _WEB_OFF}")
    lines.append(f"- {_image_line(image_channels, config)}")
    if overlay := _overlay_line():
        lines.append(f"- {overlay}")
    derived = _SECTION_TITLE + "\n" + "\n".join(lines)

    static = (static_text or "").rstrip()
    return f"{static}\n\n{derived}\n" if static else f"{derived}\n"
