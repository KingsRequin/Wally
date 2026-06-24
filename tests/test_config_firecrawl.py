from bot.config import FirecrawlConfig, Config
import yaml


def test_firecrawl_config_defaults():
    cfg = FirecrawlConfig()
    assert cfg.enabled is True
    assert cfg.inline_max_tokens == 2000
    assert cfg.auto_scrape_links is True
    assert cfg.auto_scrape_cooldown_s == 30
    assert cfg.daily_limit == 200


def test_firecrawl_load_roundtrip(tmp_path):
    base = yaml.safe_load(open("config.yaml"))
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(base))
    cfg = Config.load(str(p))
    assert isinstance(cfg.firecrawl.inline_max_tokens, int)
    cfg.save()  # must not raise
