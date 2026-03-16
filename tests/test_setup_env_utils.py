# tests/test_setup_env_utils.py
import pytest
from pathlib import Path


def test_read_env_values_parses_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=bar\nBAZ=qux\n")
    from bot.discord.commands.setup import read_env_values
    assert read_env_values(str(env)) == {"FOO": "bar", "BAZ": "qux"}


def test_read_env_values_skips_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# commentaire\nFOO=bar\n# autre\n")
    from bot.discord.commands.setup import read_env_values
    assert read_env_values(str(env)) == {"FOO": "bar"}


def test_read_env_values_empty_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    from bot.discord.commands.setup import read_env_values
    assert read_env_values(str(env)) == {}


def test_read_env_values_missing_file():
    from bot.discord.commands.setup import read_env_values
    assert read_env_values("/nonexistent/.env") == {}


def test_read_env_values_ignores_malformed_lines(tmp_path):
    """Une ligne sans '=' est ignorée (pas de crash)."""
    env = tmp_path / ".env"
    env.write_text("export FOO\nBAR=baz\n")
    from bot.discord.commands.setup import read_env_values
    assert read_env_values(str(env)) == {"BAR": "baz"}


def test_update_env_file_updates_existing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=old\nBAR=keep\n")
    from bot.discord.commands.setup import update_env_file
    update_env_file(str(env), {"FOO": "new"})
    content = env.read_text()
    assert "FOO=new" in content
    assert "BAR=keep" in content
    assert "FOO=old" not in content


def test_update_env_file_appends_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=bar\n")
    from bot.discord.commands.setup import update_env_file
    update_env_file(str(env), {"NEW_KEY": "value"})
    assert "NEW_KEY=value" in env.read_text()


def test_update_env_file_empty_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    from bot.discord.commands.setup import update_env_file
    update_env_file(str(env), {"KEY": "val"})
    assert "KEY=val" in env.read_text()


def test_update_env_file_preserves_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# OpenAI\nOPENAI_API_KEY=old\n")
    from bot.discord.commands.setup import update_env_file
    update_env_file(str(env), {"OPENAI_API_KEY": "new"})
    content = env.read_text()
    assert "# OpenAI" in content
    assert "OPENAI_API_KEY=new" in content


def test_is_env_complete_all_present(tmp_path):
    from bot.discord.commands.setup import is_env_complete, EDITABLE_ENV_KEYS
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}=value" for k in EDITABLE_ENV_KEYS))
    assert is_env_complete(str(env)) == []


def test_is_env_complete_missing_key(tmp_path):
    from bot.discord.commands.setup import is_env_complete
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-xxx\n")
    missing = is_env_complete(str(env))
    assert "DISCORD_TOKEN" in missing
    assert "OPENAI_API_KEY" not in missing


def test_is_env_complete_empty_value(tmp_path):
    from bot.discord.commands.setup import is_env_complete
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=\n")
    assert "OPENAI_API_KEY" in is_env_complete(str(env))


def test_is_env_complete_file_absent():
    from bot.discord.commands.setup import is_env_complete, EDITABLE_ENV_KEYS
    missing = is_env_complete("/nonexistent/.env")
    assert set(missing) == set(EDITABLE_ENV_KEYS)


def test_is_env_complete_ignores_infrastructure_keys(tmp_path):
    """QDRANT_URL et DB_PATH ne doivent pas être vérifiés."""
    from bot.discord.commands.setup import is_env_complete, EDITABLE_ENV_KEYS
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}=value" for k in EDITABLE_ENV_KEYS))
    # Même sans QDRANT_URL et DB_PATH, doit retourner []
    assert is_env_complete(str(env)) == []
