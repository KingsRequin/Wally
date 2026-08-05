import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    import asyncio
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(autouse=True)
def isolate_learned_emotion_words(tmp_path, monkeypatch):
    """Coupe les tests du fichier d'apprentissage émotionnel de production.

    `EmotionEngine` lit `data/fr_emotion_words.json` à la construction et y écrit
    quand il apprend un mot. Sans isolation :
      - les assertions dépendent de ce que Wally a appris pour de vrai — « relou »
        a fini par être appris en prod, ce qui faisait tomber trois tests qui
        l'utilisaient comme mot d'exemple ;
      - un test qui apprend un mot inconnu ÉCRIT dans le fichier de production.
    """
    monkeypatch.setattr(
        "bot.core.emotion._LEARNED_WORDS_PATH",
        str(tmp_path / "fr_emotion_words.json"),
    )


@pytest.fixture(autouse=True)
def reset_identity_after_test():
    """Réinitialise l'identité du bot après chaque test.

    Évite que set_identity() appelé dans un test ne pollue les tests suivants.
    """
    yield
    from bot.intelligence import identity
    identity._NAME = "Wally"
    identity._CREATOR = "KingsRequin"
    identity._OWNER = ""
