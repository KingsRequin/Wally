from bot.v2.core.channels import ChannelDirectory, ChannelInfo

_SAMPLE = """\
# commentaire en tête
# Format : <id> | <nom> | <type> | <utilité>

875421532351000627 | #discussions | text | discussion générale, le canal principal
875450811151450143 | #memes | text | memes en rapport avec la communauté
1106526870956146779 | #suggestions | forum | suggestions musique/vidéo — FORUM

ligne | malformee | trois
875438958836846653 | #recherche | text | chercher des gens
"""


def _write(tmp_path, content):
    p = tmp_path / "CHANNELS.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_parses_format(tmp_path):
    d = ChannelDirectory.load(_write(tmp_path, _SAMPLE))
    ids = d.speakable_ids()
    assert "875421532351000627" in ids
    assert "875450811151450143" in ids
    assert "875438958836846653" in ids


def test_load_ignores_comments_and_malformed(tmp_path):
    d = ChannelDirectory.load(_write(tmp_path, _SAMPLE))
    # 3 canaux text + 1 forum valides ; commentaires/vides/malformés ignorés.
    assert d.speakable_ids() == {
        "875421532351000627",
        "875450811151450143",
        "875438958836846653",
    }


def test_speakable_excludes_forum(tmp_path):
    d = ChannelDirectory.load(_write(tmp_path, _SAMPLE))
    assert not d.is_speakable("1106526870956146779")  # #suggestions = forum
    assert "1106526870956146779" not in d.speakable_ids()


def test_is_speakable(tmp_path):
    d = ChannelDirectory.load(_write(tmp_path, _SAMPLE))
    assert d.is_speakable("875421532351000627") is True
    assert d.is_speakable("000000000000000000") is False


def test_missing_file_is_empty(tmp_path):
    d = ChannelDirectory.load(tmp_path / "nope.md")
    assert d.speakable_ids() == set()
    assert d.render() == ""


def test_render_contains_text_channels_not_forum(tmp_path):
    d = ChannelDirectory.load(_write(tmp_path, _SAMPLE))
    out = d.render()
    assert "875421532351000627 #discussions" in out
    assert "#memes" in out
    # le forum n'est PAS une cible (pas listé comme canal où écrire), mais
    # mentionné comme avertissement.
    assert "1106526870956146779 #suggestions —" not in out
    assert "forum" in out and "#suggestions" in out


def test_render_empty_when_no_channels(tmp_path):
    d = ChannelDirectory([])
    assert d.render() == ""


def test_real_directory_eight_text_channels():
    """Le vrai fichier livré expose 8 canaux textuels (le forum exclu)."""
    import pathlib
    real = pathlib.Path(__file__).parents[3] / "bot" / "v2" / "persona" / "CHANNELS.md"
    d = ChannelDirectory.load(real)
    assert len(d.speakable_ids()) == 8
    assert "1106526870956146779" not in d.speakable_ids()  # #suggestions forum
    assert isinstance(d._channels[0], ChannelInfo)
