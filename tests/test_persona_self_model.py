from types import SimpleNamespace

from bot.intelligence.persona import PersonaService


def _persona_dir(tmp_path, caps_text="Je n'ai pas de corps."):
    (tmp_path / "SOUL.md").write_text("âme", encoding="utf-8")
    (tmp_path / "IDENTITY.md").write_text("Nom : Wally", encoding="utf-8")
    (tmp_path / "VOICE.md").write_text("Style : court.", encoding="utf-8")
    (tmp_path / "CAPABILITIES.md").write_text(caps_text, encoding="utf-8")
    return str(tmp_path)


def test_block_reflects_voice_enabled(tmp_path):
    cfg = SimpleNamespace(voice=SimpleNamespace(enabled=True))
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    block = ps.build_prompt_block()
    assert "parler en vocal" in block
    assert "Je n'ai pas de corps." in block  # narratif statique préservé


def test_block_reflects_voice_disabled(tmp_path):
    cfg = SimpleNamespace(voice=SimpleNamespace(enabled=False))
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    block = ps.build_prompt_block()
    assert "n'est pas activé" in block


def test_block_without_config_uses_static_only(tmp_path):
    ps = PersonaService(persona_dir=_persona_dir(tmp_path))  # config=None
    block = ps.build_prompt_block()
    assert "Je n'ai pas de corps." in block
    assert "Mes capacités techniques actuelles" not in block


def test_real_capabilities_md_has_no_fossilised_voice_line():
    # Le fichier réel ne doit plus affirmer que le vocal est désactivé/pas branché.
    with open("bot/persona/CAPABILITIES.md", encoding="utf-8") as f:
        content = f.read()
    assert "pas branché" not in content
    assert "elle est désactivée" not in content


def test_image_autonome_annoncee_avec_les_salons(tmp_path):
    """Les salons annoncés sont ceux que la politique ouvre vraiment."""
    cfg = SimpleNamespace(voice=SimpleNamespace(enabled=False))
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    ps.image_channels = ["#shitpost", "#memes"]
    block = ps.build_prompt_block()
    assert "#shitpost, #memes" in block
    assert "décider tout seul de fabriquer une image" in block


def test_image_autonome_eteinte_quand_aucun_salon(tmp_path):
    cfg = SimpleNamespace(voice=SimpleNamespace(enabled=False))
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    ps.image_channels = []
    assert "je ne peux pas pour l'instant" in ps.build_prompt_block()


def test_sans_noms_le_self_model_suit_la_config(tmp_path):
    """`image_channels` non renseigné ne doit pas faire dire l'inverse de la
    vérité : le chemin conversationnel affirmait « je ne peux pas » pendant que
    la cognition avait l'action."""
    from bot.config import ImageGenerationConfig

    cfg = SimpleNamespace(
        voice=SimpleNamespace(enabled=False),
        cognitive_loop={"enabled": True},
        image_generation=ImageGenerationConfig(
            autonomous_enabled=True, autonomous_channel_ids=["1"],
        ),
    )
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    assert ps.image_channels is None
    assert "décider tout seul de fabriquer une image" in ps.build_prompt_block()


def test_sans_cognition_pas_dimage_autonome(tmp_path):
    """La boucle cognitive est le seul chemin qui en décide : coupée, l'action
    n'existe nulle part, même si la section image reste configurée."""
    from bot.config import ImageGenerationConfig

    cfg = SimpleNamespace(
        voice=SimpleNamespace(enabled=False),
        cognitive_loop={"enabled": False},
        image_generation=ImageGenerationConfig(
            autonomous_enabled=True, autonomous_channel_ids=["1"],
        ),
    )
    ps = PersonaService(persona_dir=_persona_dir(tmp_path), config=cfg)
    assert "je ne peux pas pour l'instant" in ps.build_prompt_block()
