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

_WEB_ON = (
    "Je peux chercher sur le web de moi-même quand une vraie curiosité me prend, "
    "même sans qu'on me le demande."
)
_WEB_OFF = (
    "Je pourrais chercher sur le web, mais c'est indisponible pour l'instant."
)


def build_self_model(static_text: str, config, *, web_available: bool = False) -> str:
    """Assemble le self-model : narratif statique + capacités dérivées de l'état réel.

    `static_text` = CAPABILITIES.md nettoyé (vérités de personnage stables).
    `config` = la config runtime ; chaque capacité à bascule est évaluée contre elle.
    `web_available` = dispo RÉELLE de la recherche web (Tavily configuré). Dérivée
    d'un flag plutôt que de `config` car la clé vit dans l'environnement, pas la config.

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
    if overlay := _overlay_line():
        lines.append(f"- {overlay}")
    derived = _SECTION_TITLE + "\n" + "\n".join(lines)

    static = (static_text or "").rstrip()
    return f"{static}\n\n{derived}\n" if static else f"{derived}\n"
