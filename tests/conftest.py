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
def isolate_journal_charts(tmp_path, monkeypatch):
    """Coupe les tests du dossier de graphes de production.

    `generate_and_send()` écrit `data/journal_charts/{date}.png` — un chemin
    RELATIF au cwd, donc le vrai dossier quand la suite tourne à la racine du
    dépôt. Les tests isolaient leur base dans `tmp_path` mais pas ce PNG : le
    graphe du jour publié dans le journal du soir était écrasé par celui des
    2 snapshots d'une fixture (joie 80 → 50, le reste à plat). 26 entrées entre
    le 2026-04-03 et le 2026-08-12 portaient ce faux graphe, octet pour octet
    identiques. Même famille que `isolate_learned_emotion_words` ci-dessus.
    """
    monkeypatch.setattr(
        "bot.intelligence.journal._JOURNAL_CHARTS_DIR",
        tmp_path / "journal_charts",
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
