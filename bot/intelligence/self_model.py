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
    derived = _SECTION_TITLE + "\n" + "\n".join(lines)

    static = (static_text or "").rstrip()
    return f"{static}\n\n{derived}\n" if static else f"{derived}\n"
