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
def isolate_processed_message_ids():
    """Vide le cache anti-rejeu des messages Discord entre deux tests.

    `bot.discord.handlers._processed_message_ids` est un dict de MODULE, et sa
    seule purge est un TTL de 120 secondes de temps RÉEL. Deux tests qui posent
    `message.id = 1` — le premier venu, personne ne se coordonne sur des ids
    factices — et le second voit son message sauté en silence
    (« Duplicate on_message event »), donc `append_message` jamais appelé.

    La suite ne passait que par chance de chronologie : `-n 4 --dist loadfile`
    répartit les fichiers sur quatre process, et en séquentiel les 145 s de la
    suite dépassent parfois le TTL. Vu rouge sous `-n 0`, que mutmut impose.
    """
    from bot.discord.handlers import _processed_message_ids
    _processed_message_ids.clear()
    yield
    _processed_message_ids.clear()


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


def _threads_aiosqlite_en_daemon() -> None:
    """Un test qui ÉCHOUE doit le DIRE, pas faire pendre la suite.

    Vécu le 2026-08-26 : tout test asyncio ouvrant une `Database` et échouant
    ne rendait jamais la main — pytest restait suspendu, sans afficher l'échec,
    et la suite paraissait « lente » au lieu de « rouge ». Reproduit en huit
    lignes : sur succès l'objet est collecté et sa connexion se ferme ; sur
    échec, pytest garde le frame du test vivant pour son traceback, donc la
    connexion aussi.

    La cause est chez `aiosqlite`, qui crée son thread de travail SANS
    `daemon=True` : l'interpréteur l'attend à la sortie, indéfiniment. On ne
    corrige pas la lib, on rend ses threads démontables — ici seulement, pour
    que l'échec sorte. Un test qui ferme proprement continue de fermer.
    """
    import aiosqlite.core

    if getattr(aiosqlite.core.Connection, "_wally_daemon", False):
        return
    original = aiosqlite.core.Connection.__await__

    def __await__(self):  # noqa: N807 — on remplace la méthode spéciale
        self._thread.daemon = True
        return original(self)

    aiosqlite.core.Connection.__await__ = __await__
    aiosqlite.core.Connection._wally_daemon = True


def pytest_configure(config):
    """Plafonne la mémoire de la suite — un test qui fuit ne doit pas tuer la machine.

    Vécu le 2026-08-19 : `test_azure_tts_returns_audio_bytes` remplaçait tout
    `speechsdk` par un MagicMock. La boucle `while True: n = stream.read_data(...)`
    de `AzureTTS._stream_sync` recevait alors un MagicMock — jamais `== 0`, donc
    jamais de sortie — et empilait un chunk par tour. Le process a pris 10 Go,
    saturé CT100 (14 Go) et son swap, et mis l`hôte Proxmox à 201 de load : DNS
    du réseau et bots compris. Pire, la session qui lançait la suite la relançait
    après chaque OOM-kill du noyau.

    La suite entière tient dans 509 Mo de RSS pour 1,18 Go d`espace d`adressage ;
    3 Go laissent 2,5× de marge. Au-delà, Python lève MemoryError et le test
    tombe — au lieu que le noyau tue la machine. `RLIMIT_AS` et pas `RLIMIT_DATA`
    parce que seul le premier couvre aussi les mmap.

    Réglable par WALLY_TESTS_MEM_MAX_MB ; 0 désactive le plafond.
    """
    import os
    import resource

    _threads_aiosqlite_en_daemon()

    plafond_mo = int(os.environ.get("WALLY_TESTS_MEM_MAX_MB", "3072"))
    if plafond_mo <= 0:
        return
    plafond = plafond_mo * 1024 * 1024
    souple, dur = resource.getrlimit(resource.RLIMIT_AS)
    # Ne jamais RELEVER un plafond déjà posé par l`appelant (cgroup, ulimit).
    if dur != resource.RLIM_INFINITY and dur < plafond:
        return
    resource.setrlimit(resource.RLIMIT_AS, (plafond, dur))
