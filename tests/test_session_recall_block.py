from bot.intelligence.prompts import build_session_recall_block


def test_empty_summaries_returns_empty():
    assert build_session_recall_block([]) == ""


def test_block_lists_summaries():
    block = build_session_recall_block(
        [{"summary": "On a parlé d'Apex."}, {"summary": "Bob était de mauvaise humeur."}]
    )
    assert "Sessions précédentes" in block
    assert "On a parlé d'Apex." in block
    assert "Bob était de mauvaise humeur." in block
