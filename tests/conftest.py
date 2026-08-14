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
def isolate_secret_guard():
    """Vide le registre des mots protégés entre deux tests.

    `bot.core.secret_guard._SECRETS` est un dict de MODULE : un test qui lance
    un pendu sur « fuse » sans jamais le lever le laisse protégé pour toute la
    suite, et le mot ressort en « […] » dans un test qui n'a rien à voir —
    exactement le sous-titre « Fuse · niv. 285 » d'un tableau de duel. Panne
    d'ordonnancement pure : chaque fichier passait seul.

    Un test le contournait déjà en appelant `clear_secrets()` lui-même
    (test_phase10_overlay.py) ; c'est le genre de garde qui a sa place ici, une
    fois, plutôt que dans chaque fichier qui y pense.
    """
    from bot.core.secret_guard import clear_secrets
    clear_secrets()
    yield
    clear_secrets()


@pytest.fixture(autouse=True)
def isolate_thread_sense():
    """Vide la mesure du fil entre deux tests.

    `bot.intelligence.thread_sense` garde ses compteurs dans des dicts de
    MODULE, comme `_relances` ou `secret_guard._SECRETS` : un test qui pousse
    quatre répliques finies par « 😄 » dans le canal « live » laisse le tic
    installé pour toute la suite, et le test suivant voit son propre message
    amputé de son emoji sans avoir rien demandé.
    """
    from bot.intelligence.thread_sense import oublier_tout
    oublier_tout()
    yield
    oublier_tout()


@pytest.fixture(autouse=True)
def isolate_pending_questions():
    """Vide le registre des questions sans réponse entre deux tests.

    Même famille que ci-dessus : un dict de MODULE. Une question laissée en
    attente par un test la rend « mûre » pour le suivant, qui verrait Wally
    ouvrir la bouche sans qu'on lui ait rien demandé.
    """
    from bot.intelligence.pending_question import oublier_tout
    oublier_tout()
    yield
    oublier_tout()


@pytest.fixture(autouse=True)
def isolate_self_trace():
    """Vide la trace de ses propres actes entre deux tests.

    Même famille que `isolate_secret_guard` : un singleton de MODULE
    (`bot.core.self_trace._TRACE`). Tout test qui publie une bulle d'overlay ou
    journalise un `message_out` y laisse une ligne, et le test suivant verrait
    un bloc « Ce que TU viens de faire » qu'il n'a pas produit — un faux positif
    dans un prompt, et un faux négatif quand la ligne attendue est déjà là.
    """
    from bot.core.self_trace import reset_self_trace
    reset_self_trace()
    yield
    reset_self_trace()


@pytest.fixture(autouse=True)
def isolate_emote_registry():
    """Vide le registre d'emotes Twitch entre deux tests.

    Même famille que `isolate_self_trace` : un singleton de MODULE
    (`bot.core.twitch_emotes._REGISTRE`). Un test qui déclare `LUL` utilisable
    et en compte trois laisserait le bloc « Les emotes de ce chat » dans le
    prompt du test suivant, qui n'a rien demandé.
    """
    from bot.core.twitch_emotes import reset_emotes
    reset_emotes()
    yield
    reset_emotes()


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
