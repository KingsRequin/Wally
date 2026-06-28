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


def build_self_model(static_text: str, config) -> str:
    """Assemble le self-model : narratif statique + capacités dérivées de l'état réel.

    `static_text` = CAPABILITIES.md nettoyé (vérités de personnage stables).
    `config` = la config runtime ; chaque capacité à bascule est évaluée contre elle.

    Fonction pure : aucune I/O, aucune dépendance aux objets services montés
    (donc insensible à l'ordre de montage au boot). Un `config` malformé fait
    juste tomber la capacité en « inactive », jamais une exception.
    """
    lines = []
    for condition, on_text, off_text in _TOGGLE_CAPABILITIES:
        try:
            active = bool(condition(config))
        except Exception:
            active = False
        lines.append(f"- {on_text if active else off_text}")
    derived = _SECTION_TITLE + "\n" + "\n".join(lines)

    static = (static_text or "").rstrip()
    return f"{static}\n\n{derived}\n" if static else f"{derived}\n"
