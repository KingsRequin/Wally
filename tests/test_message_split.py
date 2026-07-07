import pytest

from bot.discord.message_split import (
    DISCORD_MAX_LEN,
    send_chunked,
    split_for_discord,
)


def test_short_text_single_chunk():
    assert split_for_discord("coucou") == ["coucou"]


def test_empty_text_no_chunk():
    assert split_for_discord("") == []
    assert split_for_discord("   \n  ") == []


def test_exact_limit_single_chunk():
    text = "a" * DISCORD_MAX_LEN
    assert split_for_discord(text) == [text]


def test_all_chunks_under_limit():
    text = ("Phrase de test assez longue pour remplir. " * 200).strip()
    chunks = split_for_discord(text)
    assert len(chunks) > 1
    assert all(len(c) <= DISCORD_MAX_LEN for c in chunks)


def test_reassembles_to_original_words():
    text = ("Wally observe le salon. " * 300).strip()
    chunks = split_for_discord(text)
    # Aucun mot perdu ni coupé : la concaténation des mots doit être identique.
    assert " ".join(chunks).split() == text.split()


def test_splits_on_sentence_boundary():
    a = "Ceci est la première phrase."
    b = "Voici la seconde."
    text = a + " " + b
    chunks = split_for_discord(text, limit=len(a) + 5)
    # La coupure tombe après le point de la première phrase, pas en plein milieu.
    assert chunks[0] == a
    assert chunks[1] == b


def test_prefers_newline_boundary():
    para1 = "x" * 40
    para2 = "y" * 40
    text = para1 + "\n\n" + para2
    chunks = split_for_discord(text, limit=50)
    assert chunks[0] == para1
    assert chunks[1] == para2


def test_never_splits_mid_word_when_avoidable():
    text = "motmotmot " * 100  # que des mots séparés par des espaces
    chunks = split_for_discord(text.strip(), limit=25)
    for c in chunks:
        assert not c.startswith(" ") and not c.endswith(" ")
        # chaque morceau ne contient que des mots entiers
        assert all(w == "motmotmot" for w in c.split())


def test_hard_cut_only_for_overlong_word():
    text = "z" * (DISCORD_MAX_LEN * 2 + 10)  # un seul « mot » gigantesque
    chunks = split_for_discord(text)
    assert all(len(c) <= DISCORD_MAX_LEN for c in chunks)
    assert "".join(chunks) == text  # rien perdu, coupe brute assumée


def test_punctuation_variants_are_boundaries():
    for punct in [".", "!", "?", "…"]:
        head = "a" * 30 + punct
        text = head + " " + "b" * 30
        chunks = split_for_discord(text, limit=len(head) + 3)
        assert chunks[0] == head


class _Sendable:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, part):
        self.sent.append(part)
        return type("Msg", (), {"id": len(self.sent), "channel": None})()


@pytest.mark.asyncio
async def test_send_chunked_sends_all_parts_in_order():
    dest = _Sendable()
    text = ("Une phrase de rapport. " * 300).strip()
    first = await send_chunked(dest, text)
    assert len(dest.sent) > 1
    assert all(len(p) <= DISCORD_MAX_LEN for p in dest.sent)
    assert dest.sent == split_for_discord(text)  # ordre préservé
    assert first.id == 1  # premier message retourné


@pytest.mark.asyncio
async def test_send_chunked_short_message_single_send():
    dest = _Sendable()
    first = await send_chunked(dest, "salut")
    assert dest.sent == ["salut"]
    assert first.id == 1


@pytest.mark.asyncio
async def test_send_chunked_empty_sends_nothing():
    dest = _Sendable()
    first = await send_chunked(dest, "   ")
    assert dest.sent == []
    assert first is None
