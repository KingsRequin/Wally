import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.fixture
def instance_dir(tmp_path):
    return tmp_path / "instances"

@pytest.mark.asyncio
async def test_creates_directory_structure(instance_dir):
    from bot.core.provisioner import provision_instance
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", AsyncMock()):
        await provision_instance("cindy", 8081, data)
    slug_dir = instance_dir / "cindy"
    assert (slug_dir / ".env").exists()
    assert (slug_dir / "config.yaml").exists()
    assert (slug_dir / "docker-compose.yml").exists()
    assert (slug_dir / "data").is_dir()
    assert (slug_dir / "logs").is_dir()
    assert (slug_dir / "bot" / "persona").is_dir()

@pytest.mark.asyncio
async def test_env_contains_required_keys(instance_dir):
    from bot.core.provisioner import provision_instance
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", AsyncMock()):
        await provision_instance("cindy", 8081, data)
    env_text = (instance_dir / "cindy" / ".env").read_text()
    assert "DISCORD_TOKEN=mytoken" in env_text
    assert "OPENAI_API_KEY=sk-test" in env_text
    assert "JWT_SECRET=" in env_text
    assert "QDRANT_COLLECTION_NAME=wally_cindy" in env_text
    # JWT_SECRET must be non-empty
    for line in env_text.splitlines():
        if line.startswith("JWT_SECRET="):
            assert len(line.split("=", 1)[1]) > 10

@pytest.mark.asyncio
async def test_config_yaml_has_trigger_names(instance_dir):
    from bot.core.provisioner import provision_instance
    import yaml
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", AsyncMock()):
        await provision_instance("cindy", 8081, data)
    cfg = yaml.safe_load((instance_dir / "cindy" / "config.yaml").read_text())
    assert "cindy" in cfg["bot"]["trigger_names"]
    assert cfg["bot"]["language_default"] == "fr"

def test_provisioner_config_includes_theme_defaults(tmp_path):
    """Le config.yaml généré contient un bloc theme: avec les valeurs par défaut."""
    import yaml
    from bot.core.provisioner import _write_config_yaml

    data = {"bot_name": "TestBot", "language_default": "fr"}
    _write_config_yaml(tmp_path, "testslug", data)

    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert "theme" in cfg
    assert cfg["theme"]["accent_color"] == "#06b6d4"
    assert cfg["theme"]["layout_variant"] == "sidebar-left"
    assert cfg["theme"]["tab_style"] == "icons-only"

@pytest.mark.asyncio
async def test_persona_files_written(instance_dir):
    from bot.core.provisioner import provision_instance
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", AsyncMock()):
        await provision_instance("cindy", 8081, data)
    soul = (instance_dir / "cindy" / "bot" / "persona" / "SOUL.md").read_text()
    assert "Je suis Cindy" in soul

@pytest.mark.asyncio
async def test_docker_compose_launched(instance_dir):
    from bot.core.provisioner import provision_instance
    mock_docker = AsyncMock()
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", mock_docker):
        await provision_instance("cindy", 8081, data)
    mock_docker.assert_called_once()
    args = mock_docker.call_args[0]
    assert "cindy" in str(args[0])  # path contient le slug

@pytest.mark.asyncio
async def test_dry_run_skips_docker(instance_dir):
    from bot.core.provisioner import provision_instance
    mock_docker = AsyncMock()
    data = _make_data()
    with patch("bot.core.provisioner.INSTANCES_DIR", instance_dir), \
         patch("bot.core.provisioner._run_docker_compose", mock_docker):
        await provision_instance("cindy", 8081, data, dry_run=True)
    mock_docker.assert_not_called()

def _make_data():
    return {
        "discord_token": "mytoken",
        "discord_guild_id": "123456",
        "discord_client_id": "cid",
        "discord_client_secret": "csec",
        "openai_api_key": "sk-test",
        "anthropic_api_key": "",
        "tavily_api_key": "",
        "bot_name": "cindy",
        "language_default": "fr",
        "trigger_names": ["cindy"],
        "twitch_enabled": False,
        "persona_soul": "Je suis Cindy",
        "persona_identity": "Cindy identity",
        "persona_voice": "Cindy voice",
        "persona_emotions": "Cindy emotions",
        "web_base_url": "https://cindy.example.com",
    }
