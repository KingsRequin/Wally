# tests/test_persona_emotions.py
"""Non-régression : EMOTIONS.md sans préambule perdait sa première section.

Bug : `_parse_emotions()` faisait `content.split("\n## ")` alors que tous les
autres parseurs (`_parse_weekdays`, `_parse_composites`, `_parse_secondaries`,
`_parse_sections`) font `("\n" + content).split("\n## ")`. Sans le `"\n" +`
initial, quand le fichier commence directement par `## ` (pas de préambule),
la première section atterrit dans `sections[0]` (traité comme préambule) et
est donc jamais chargée.
"""

from bot.intelligence.persona import PersonaService

_EMOTIONS_NO_PREAMBLE = """## anger_low
Plus impatient, plus sec.

## anger_mid
Franchement irrité, réponses brèves et mordantes.

## joy_low
Un peu plus léger que d'habitude.
"""

_EMOTIONS_WITH_PREAMBLE = """# Directives par émotion

Préambule à ignorer.

## anger_low
Plus impatient, plus sec.

## anger_mid
Franchement irrité, réponses brèves et mordantes.

## joy_low
Un peu plus léger que d'habitude.
"""


def test_first_section_loaded_without_preamble(tmp_path):
    """Fichier commençant directement par '## ' → la 1ère section est quand même chargée."""
    (tmp_path / "EMOTIONS.md").write_text(_EMOTIONS_NO_PREAMBLE, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert "anger_low" in ps.emotion_directives
    assert ps.emotion_directives["anger_low"] == "Plus impatient, plus sec."
    # Les autres sections restent chargées aussi.
    assert set(ps.emotion_directives) == {"anger_low", "anger_mid", "joy_low"}


def test_preamble_still_ignored_all_sections_loaded(tmp_path):
    """Fichier avec préambule → préambule ignoré, toutes les sections chargées (inchangé)."""
    (tmp_path / "EMOTIONS.md").write_text(_EMOTIONS_WITH_PREAMBLE, encoding="utf-8")
    ps = PersonaService(persona_dir=str(tmp_path))
    assert set(ps.emotion_directives) == {"anger_low", "anger_mid", "joy_low"}
    assert "Préambule à ignorer" not in "".join(ps.emotion_directives.values())


def test_real_emotions_file_loads_15_directives_including_anger_low():
    """Preuve du fix sur le vrai fichier de prod : 15 directives, anger_low présent.

    L'assertion portait sur le TEXTE exact d'`anger_low` (« Plus impatient, plus
    sec. »). Or ce fichier est bind-monté et éditable depuis l'onglet Prompts : figer
    sa prose faisait rougir la suite à chaque retouche du personnage, alors que le
    bug surveillé ici est un bug de PARSEUR. On vérifie donc la présence et la
    substance, pas la formulation.
    """
    ps = PersonaService(persona_dir="bot/persona")
    assert len(ps.emotion_directives) == 15
    assert "anger_low" in ps.emotion_directives
    assert ps.emotion_directives["anger_low"].strip()


def test_les_paliers_hauts_sont_substantiels():
    """Une directive de deux mots ne dirige rien.

    `anger_high` valait « Furax. Insultes familières OK. » — cinq mots ; `joy_high`
    « Rare. Tu rayonnes malgré toi. » ; `sadness_high` « Silencieux, monosyllabique. »
    Là où les composites en font quatre lignes avec des formulations types. Un palier
    réduit à une étiquette laisse le LLM inventer son propre registre, et c'est
    exactement ce qui rendait ces états tièdes en prod.

    On mesure la substance et l'escalade, jamais la formulation : ce fichier est
    bind-monté et éditable depuis l'onglet Prompts.
    """
    ps = PersonaService(persona_dir="bot/persona")
    for emotion in ("anger", "joy", "sadness", "curiosity", "boredom"):
        haut = ps.emotion_directives.get(f"{emotion}_high", "")
        assert len(haut) > 300, (
            f"{emotion}_high ne fait que {len(haut)} caractères — un état extrême "
            "tient en plus de deux lignes, sinon le LLM comble le vide tout seul"
        )
        # L'escalade doit être lisible : plus on monte, plus la consigne est fournie.
        paliers = [len(ps.emotion_directives.get(f"{emotion}_{t}", "")) for t in ("low", "mid", "high")]
        assert paliers[0] < paliers[1] < paliers[2], (
            f"{emotion} : escalade cassée entre low/mid/high ({paliers})"
        )
