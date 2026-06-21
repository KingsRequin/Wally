from bot.intelligence.emotional_drive import emotional_drive, _DRIVES


def test_empty_state_returns_none():
    assert emotional_drive({}) is None


def test_dominant_below_threshold_returns_none():
    state = {"anger": 0.3, "joy": 0.2, "sadness": 0.1, "curiosity": 0.4, "boredom": 0.39}
    assert emotional_drive(state) is None


def test_dominant_exactly_at_threshold_fires():
    state = {"anger": 0.0, "joy": 0.45, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    assert emotional_drive(state) == _DRIVES["joy"]


def test_each_emotion_dominant_returns_its_directive():
    for emo in ("anger", "joy", "sadness", "curiosity", "boredom"):
        state = {e: 0.0 for e in ("anger", "joy", "sadness", "curiosity", "boredom")}
        state[emo] = 0.8
        assert emotional_drive(state) == _DRIVES[emo]


def test_boredom_directive_content():
    state = {"boredom": 0.9, "anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0}
    drive = emotional_drive(state)
    assert "stimulation" in drive.lower()


def test_custom_threshold():
    state = {"curiosity": 0.6, "anger": 0.0, "joy": 0.0, "sadness": 0.0, "boredom": 0.0}
    assert emotional_drive(state, threshold=0.7) is None
    assert emotional_drive(state, threshold=0.5) == _DRIVES["curiosity"]


def test_tie_picks_one_drive():
    # Égalité entre deux émotions au-dessus du seuil : une directive valide sort.
    state = {"joy": 0.6, "curiosity": 0.6, "anger": 0.0, "sadness": 0.0, "boredom": 0.0}
    drive = emotional_drive(state)
    assert drive in (_DRIVES["joy"], _DRIVES["curiosity"])


def test_unknown_dominant_key_returns_none():
    # Robustesse : une clé inattendue dominante n'a pas de directive → None.
    assert emotional_drive({"mystery": 0.9}) is None
