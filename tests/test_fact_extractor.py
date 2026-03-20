from bot.core.fact_extractor import _is_memorable


class TestIsMemorableFilter:
    def test_short_message_rejected(self):
        assert _is_memorable("salut") is False
        assert _is_memorable("yo") is False
        assert _is_memorable("ok bro") is False  # < 15 chars

    def test_emoji_only_rejected(self):
        assert _is_memorable("😂😂😂") is False
        assert _is_memorable("🔥🔥") is False

    def test_single_interjection_rejected(self):
        assert _is_memorable("lol") is False
        assert _is_memorable("mdrrr") is False
        assert _is_memorable("ptdrrr") is False
        assert _is_memorable("xdddd") is False
        assert _is_memorable("hahaha") is False
        assert _is_memorable("okkk") is False
        assert _is_memorable("ggg") is False
        assert _is_memorable("ouiii") is False
        assert _is_memorable("nooon") is False
        assert _is_memorable("^^") is False
        assert _is_memorable("+1") is False
        assert _is_memorable("rip") is False
        assert _is_memorable("aaah") is False
        assert _is_memorable("ooooh") is False

    def test_all_interjections_rejected(self):
        assert _is_memorable("non non non non") is False
        assert _is_memorable("lol mdr ptdr xd") is False

    def test_interjection_with_content_passes(self):
        assert _is_memorable("mdr c'est trop vrai ce que tu dis") is True
        assert _is_memorable("oui je suis développeur Python") is True
        assert _is_memorable("lol j'habite à Marseille") is True

    def test_informative_message_passes(self):
        assert _is_memorable("je suis développeur Python depuis 3 ans") is True
        assert _is_memorable("j'habite à Lyon, je bosse dans une startup") is True
        assert _is_memorable("franchement j'adore le metal scandinave") is True

    def test_medium_message_passes(self):
        assert _is_memorable("c'est vraiment intéressant comme approche") is True

    def test_whitespace_handling(self):
        assert _is_memorable("  lol  ") is False
        assert _is_memorable("  mdr  ") is False
        assert _is_memorable("  je suis dev Python  ") is True  # > 15 chars after strip? Actually "je suis dev Python" is 18 chars
