"""Digest de réveil : détection du sommeil, scoring pondéré, injection au tick.

Aucun appel réseau : le LLM, la base et le fact store sont des doubles. Les logs
de conversation sont écrits en dur dans un tmp_path au format réel
(`logs/conversations/discord/{canal}/{jour}.jsonl`).
"""
import json
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from bot.intelligence.cognitive_loop import CognitiveLoop
from bot.intelligence.wake_digest import (
    AFFINITY_THRESHOLD,
    MIN_SLEEP_SECONDS,
    WEIGHT_AFFINITY,
    WEIGHT_COMMUNITY_EVENT,
    WEIGHT_INTEREST,
    WEIGHT_MENTION,
    WakeDigest,
    last_engagement_ts,
    read_messages,
    score_messages,
)

_PROMPTS = "bot/intelligence/persona/prompts"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_log(root, channel, ts_records, platform="discord"):
    """Écrit des events JSONL dans le fichier du jour correspondant au ts."""
    from bot.intelligence.wake_digest import _PARIS

    for rec in ts_records:
        day = datetime.fromtimestamp(rec["ts"], _PARIS).strftime("%Y-%m-%d")
        path = root / platform / channel / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _msg(ts, author="Azrael", content="salut", author_id="111", type="message_in"):
    return {
        "ts": ts, "type": type, "author": author, "author_id": author_id,
        "content": content,
    }


class _FakeLLM:
    def __init__(self, reply="Pendant que tu dormais, ça a beaucoup parlé."):
        self.reply = reply
        self.calls = []

    async def complete(self, system, messages, **kwargs):
        self.calls.append((system, messages))
        return self.reply


class _FakeFacts:
    def __init__(self, desires=(), goals=(), focus=None):
        self._desires = list(desires)
        self._goals = list(goals)
        self._focus = focus
        self.added = []

    async def search_by_category(self, category, status=None, limit=10):
        from bot.intelligence.memory.facts import FactCategory
        source = self._desires if category is FactCategory.DESIRE else self._goals
        return [SimpleNamespace(content=c) for c in source[:limit]]

    async def get_latest_by_source(self, user_id, source, category=None):
        return SimpleNamespace(content=self._focus) if self._focus else None

    async def add(self, fact):
        self.added.append(fact)
        return len(self.added)


class _FakeDB:
    def __init__(self, trust=None, love=None):
        self._trust = trust or {}
        self._love = love or {}

    async def get_trust_scores_batch(self, users):
        return {(p, u): self._trust.get(u, 0.0) for p, u in users}

    async def get_love_scores_batch(self, users, decay_lambda=0.1):
        return {(p, u): self._love.get(u, 0.0) for p, u in users}


# ── read_messages ────────────────────────────────────────────────────────────

def test_read_messages_filtre_fenetre_type_et_vide(tmp_path):
    now = time.time()
    _write_log(tmp_path, "guild_general", [
        _msg(now - 100, content="dans la fenêtre"),
        _msg(now - 10000, content="trop vieux"),
        _msg(now - 50, content="pas un message", type="message_out"),
        _msg(now - 40, content="   "),
    ])
    got = read_messages(tmp_path, now - 3600, now)
    assert [m["content"] for m in got] == ["dans la fenêtre"]
    assert got[0]["channel"] == "guild_general"
    assert got[0]["author_id"] == "111"


def test_read_messages_multi_canaux_trie_par_ts(tmp_path):
    now = time.time()
    _write_log(tmp_path, "chanA", [_msg(now - 200, content="A")])
    _write_log(tmp_path, "chanB", [_msg(now - 100, content="B")])
    got = read_messages(tmp_path, now - 3600, now)
    assert [m["content"] for m in got] == ["A", "B"]


def test_read_messages_ignore_lignes_corrompues(tmp_path):
    now = time.time()
    _write_log(tmp_path, "chanA", [_msg(now - 100, content="ok")])
    from bot.intelligence.wake_digest import _PARIS
    day = datetime.fromtimestamp(now - 100, _PARIS).strftime("%Y-%m-%d")
    path = tmp_path / "discord" / "chanA" / f"{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("pas du json\n")
    assert [m["content"] for m in read_messages(tmp_path, now - 3600, now)] == ["ok"]


def test_read_messages_exclut_les_mp(tmp_path):
    """Les MP ne sont pas la vie de la communauté : hors périmètre du digest."""
    now = time.time()
    _write_log(tmp_path, "dm", [_msg(now - 100, content="secret en privé")])
    _write_log(tmp_path, "chanA", [_msg(now - 100, content="public")])
    assert [m["content"] for m in read_messages(tmp_path, now - 3600, now)] == ["public"]


def test_read_messages_racine_absente(tmp_path):
    assert read_messages(tmp_path / "nope", 0, time.time()) == []


# ── last_engagement_ts ───────────────────────────────────────────────────────

def test_last_engagement_prefere_message_out(tmp_path):
    now = time.time()
    _write_log(tmp_path, "chanA", [
        _msg(now - 500, type="message_out"),
        _msg(now - 100),  # message_in plus récent : ne compte pas
    ])
    assert last_engagement_ts(tmp_path) == pytest.approx(now - 500)


def test_last_engagement_fallback_dernier_event(tmp_path):
    now = time.time()
    _write_log(tmp_path, "chanA", [_msg(now - 100), _msg(now - 300)])
    assert last_engagement_ts(tmp_path) == pytest.approx(now - 100)


def test_last_engagement_sans_logs(tmp_path):
    assert last_engagement_ts(tmp_path) is None


def test_une_soiree_sur_twitch_compte_comme_une_veille(tmp_path):
    """Le 13/08 à 22:45, Wally s'annonçait « réveillé après 9,2 h sans
    sollicitation » — il venait d'envoyer 89 messages dans le chat de la chaîne.
    Seul `discord/` était lu."""
    now = time.time()
    _write_log(tmp_path, "azrael_ttv", [_msg(now - 600, type="message_out")],
               platform="twitch")

    assert last_engagement_ts(tmp_path) == pytest.approx(now - 600)


def test_le_dernier_mot_revient_a_la_plateforme_la_plus_recente(tmp_path):
    """Deux plateformes, un seul « dernier moment » : le plus récent des deux."""
    now = time.time()
    _write_log(tmp_path, "general", [_msg(now - 7200, type="message_out")])
    _write_log(tmp_path, "azrael_ttv", [_msg(now - 300, type="message_out")],
               platform="twitch")

    assert last_engagement_ts(tmp_path) == pytest.approx(now - 300)


def test_les_traces_internes_ne_font_pas_une_sollicitation(tmp_path):
    """`cognitive/` et `facts/` s'écrivent même quand personne ne lui parle : les
    compter ferait de « maintenant » l'éternelle dernière veille, et plus aucun
    réveil ne serait jamais détecté."""
    now = time.time()
    _write_log(tmp_path, "general", [_msg(now - 40000, type="message_out")])
    _write_log(tmp_path, "brain", [_msg(now - 10, type="think")], platform="cognitive")
    _write_log(tmp_path, "discord", [_msg(now - 5, type="fact_stored")], platform="facts")

    assert last_engagement_ts(tmp_path) == pytest.approx(now - 40000)


# ── Scoring ──────────────────────────────────────────────────────────────────

def _scored(messages, **kwargs):
    kwargs.setdefault("bot_aliases", {"wally", "@wally"})
    kwargs.setdefault("affinity_ids", set())
    kwargs.setdefault("interest_tokens", set())
    return score_messages(messages, **kwargs)


def test_score_mention_directe():
    msgs = [{"ts": 0, "channel": "c", "author": "A", "author_id": "1",
             "content": "@Wally tu dors ?"}]
    out = _scored(msgs)
    assert out[0]["score"] == WEIGHT_MENTION
    assert out[0]["tags"] == ["mention"]


def test_score_mention_insensible_aux_accents_et_casse():
    msgs = [{"ts": 0, "channel": "c", "author": "A", "author_id": "1",
             "content": "WALLY est où"}]
    assert _scored(msgs)[0]["score"] == WEIGHT_MENTION


def test_score_affinite():
    msgs = [{"ts": 0, "channel": "c", "author": "A", "author_id": "42",
             "content": "bonsoir tout le monde"}]
    out = _scored(msgs, affinity_ids={"42"})
    assert out[0]["score"] == WEIGHT_AFFINITY
    assert out[0]["tags"] == ["proche"]


def test_score_interet():
    msgs = [{"ts": 0, "channel": "c", "author": "A", "author_id": "1",
             "content": "on relance une partie d'Apex ce soir"}]
    out = _scored(msgs, interest_tokens={"apex"})
    assert out[0]["score"] == WEIGHT_INTEREST
    assert out[0]["tags"] == ["intérêt"]


def test_score_evenement_communautaire_par_rassemblement():
    """Trois personnes distinctes en moins de 5 min sur un canal = événement."""
    msgs = [
        {"ts": 0, "channel": "c", "author": "A", "author_id": "1", "content": "go"},
        {"ts": 60, "channel": "c", "author": "B", "author_id": "2", "content": "go"},
        {"ts": 120, "channel": "c", "author": "C", "author_id": "3", "content": "go"},
    ]
    out = _scored(msgs)
    assert all(m["score"] == WEIGHT_COMMUNITY_EVENT for m in out)


def test_score_pas_evenement_si_rassemblement_trop_etale():
    msgs = [
        {"ts": 0, "channel": "c", "author": "A", "author_id": "1", "content": "go"},
        {"ts": 4000, "channel": "c", "author": "B", "author_id": "2", "content": "go"},
        {"ts": 9000, "channel": "c", "author": "C", "author_id": "3", "content": "go"},
    ]
    assert all(m["score"] == 0.0 for m in _scored(msgs))


def test_score_pas_evenement_si_une_seule_personne_bavarde():
    msgs = [
        {"ts": i * 10, "channel": "c", "author": "A", "author_id": "1", "content": "seul"}
        for i in range(6)
    ]
    assert all(m["score"] == 0.0 for m in _scored(msgs))


def test_score_annonce_everyone():
    msgs = [{"ts": 0, "channel": "c", "author": "A", "author_id": "1",
             "content": "@everyone stream ce soir"}]
    out = _scored(msgs)
    assert out[0]["score"] == WEIGHT_COMMUNITY_EVENT
    assert out[0]["tags"] == ["événement"]


def test_score_cumule_les_poids():
    msgs = [{"ts": 0, "channel": "c", "author": "A", "author_id": "42",
             "content": "@everyone Wally vient jouer à Apex"}]
    out = _scored(msgs, affinity_ids={"42"}, interest_tokens={"apex"})
    assert out[0]["score"] == (
        WEIGHT_MENTION + WEIGHT_AFFINITY + WEIGHT_INTEREST + WEIGHT_COMMUNITY_EVENT
    )


# ── Détection du réveil ──────────────────────────────────────────────────────

def _digest(tmp_path, llm=None, db=None, facts=None):
    return WakeDigest(
        llm or _FakeLLM(), _PROMPTS, logs_root=tmp_path, db=db, fact_store=facts,
    )


def test_note_engagement_sans_sommeil_narme_rien(tmp_path):
    wd = _digest(tmp_path)
    now = time.time()
    wd.note_engagement(now)
    wd.note_engagement(now + 60)
    assert wd.pending is False


def test_note_engagement_apres_long_silence_arme_le_reveil(tmp_path):
    wd = _digest(tmp_path)
    now = time.time()
    wd.note_engagement(now)
    wd.note_engagement(now + MIN_SLEEP_SECONDS + 1)
    assert wd.pending is True


def test_premiere_sollicitation_sans_reference_narme_rien(tmp_path):
    """Sans référence temporelle (bootstrap pas encore passé), pas de réveil."""
    wd = _digest(tmp_path)
    wd.note_engagement(time.time())
    assert wd.pending is False


@pytest.mark.asyncio
async def test_bootstrap_arme_le_reveil_apres_une_longue_absence(tmp_path):
    now = time.time()
    _write_log(tmp_path, "chanA", [_msg(now - 6 * 3600, type="message_out")])
    wd = _digest(tmp_path)
    await wd.bootstrap(now)
    assert wd.pending is True


@pytest.mark.asyncio
async def test_bootstrap_narme_rien_apres_un_redemarrage_court(tmp_path):
    now = time.time()
    _write_log(tmp_path, "chanA", [_msg(now - 120, type="message_out")])
    wd = _digest(tmp_path)
    await wd.bootstrap(now)
    assert wd.pending is False


@pytest.mark.asyncio
async def test_bootstrap_nefface_pas_un_engagement_deja_vu(tmp_path):
    now = time.time()
    _write_log(tmp_path, "chanA", [_msg(now - 6 * 3600, type="message_out")])
    wd = _digest(tmp_path)
    wd.note_engagement(now)  # une sollicitation est arrivée avant le bootstrap
    await wd.bootstrap(now)
    assert wd.pending is False


# ── Génération du digest ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consume_sans_reveil(tmp_path):
    assert await _digest(tmp_path).consume() is None


@pytest.mark.asyncio
async def test_consume_produit_le_digest_puis_se_desarme(tmp_path):
    now = time.time()
    for i in range(8):
        _write_log(tmp_path, "guild_general",
                   [_msg(now - 3000 + i * 60, content=f"message {i}")])
    llm, facts = _FakeLLM(), _FakeFacts()
    wd = _digest(tmp_path, llm=llm, facts=facts)
    wd.note_engagement(now - MIN_SLEEP_SECONDS - 10)
    wd.note_engagement(now)
    assert wd.pending is True

    digest = await wd.consume(now)
    assert digest == llm.reply
    assert wd.pending is False
    # Le digest est archivé en mémoire comme une pensée.
    assert len(facts.added) == 1
    assert facts.added[0].source == "wake_digest"
    # Un second appel ne régénère rien.
    assert await wd.consume(now) is None
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_consume_silencieux_si_trop_peu_de_messages(tmp_path):
    now = time.time()
    _write_log(tmp_path, "chanA", [_msg(now - 100, content="tout seul")])
    llm = _FakeLLM()
    wd = _digest(tmp_path, llm=llm)
    wd.note_engagement(now - MIN_SLEEP_SECONDS - 10)
    wd.note_engagement(now)
    assert await wd.consume(now) is None
    assert llm.calls == []


@pytest.mark.asyncio
async def test_consume_ne_leve_jamais(tmp_path):
    now = time.time()
    for i in range(8):
        _write_log(tmp_path, "chanA", [_msg(now - 3000 + i * 60, content=f"m{i}")])

    class _BoomLLM:
        async def complete(self, *a, **k):
            raise RuntimeError("LLM HS")

    wd = _digest(tmp_path, llm=_BoomLLM())
    wd.note_engagement(now - MIN_SLEEP_SECONDS - 10)
    wd.note_engagement(now)
    assert await wd.consume(now) is None


@pytest.mark.asyncio
async def test_transcript_annote_les_poids_et_le_sommeil(tmp_path):
    now = time.time()
    _write_log(tmp_path, "guild_general", [
        _msg(now - 3000 + i * 60, author=f"P{i}", author_id=str(i),
             content=f"on parle d'apex {i}")
        for i in range(6)
    ])
    llm = _FakeLLM()
    wd = _digest(
        tmp_path, llm=llm,
        db=_FakeDB(trust={"2": AFFINITY_THRESHOLD + 0.1}),
        facts=_FakeFacts(desires=["jouer à Apex avec eux"]),
    )
    wd.note_engagement(now - MIN_SLEEP_SECONDS - 10)
    wd.note_engagement(now)
    await wd.consume(now)

    prompt = llm.calls[0][1][0]["content"]
    header, transcript = prompt.split("\n\n", 1)
    assert "Tu as décroché pendant" in header
    assert "[#guild_general]" in transcript
    assert "intérêt" in transcript   # les désirs actifs alimentent les intérêts
    assert "proche" in transcript    # l'affinité DB est prise en compte
    assert "P2:" in transcript


@pytest.mark.asyncio
async def test_affinite_sous_le_seuil_ignoree(tmp_path):
    now = time.time()
    _write_log(tmp_path, "chanA", [
        _msg(now - 3000 + i * 600, author=f"P{i}", author_id=str(i), content=f"m{i}")
        for i in range(6)
    ])
    llm = _FakeLLM()
    wd = _digest(tmp_path, llm=llm, db=_FakeDB(trust={"2": AFFINITY_THRESHOLD - 0.1}))
    wd.note_engagement(now - MIN_SLEEP_SECONDS - 10)
    wd.note_engagement(now)
    await wd.consume(now)
    transcript = llm.calls[0][1][0]["content"].split("\n\n", 1)[1]
    assert "proche" not in transcript


# ── Intégration boucle cognitive ─────────────────────────────────────────────

class _RecordingAttention:
    def __init__(self):
        self.kwargs = None

    async def build_context(self, *args, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace()


class _FakeReasoning:
    async def reason(self, context):
        return SimpleNamespace(thought_text="", decisions=[], thought_fact_id=None)


class _NullDispatcher:
    async def dispatch(self, decision):  # pragma: no cover — aucune décision ici
        pass


class _StubWake:
    def __init__(self, digest=None):
        self.digest = digest
        self.engagements = 0
        self.consumed = 0

    def note_engagement(self, now=None):
        self.engagements += 1

    async def consume(self, now=None):
        self.consumed += 1
        return self.digest


@pytest.mark.asyncio
async def test_tick_injecte_le_digest_dans_le_contexte():
    attention = _RecordingAttention()
    wake = _StubWake("Pendant que tu dormais, ça a chauffé dans #general.")
    loop = CognitiveLoop(
        attention, _FakeReasoning(), _NullDispatcher(), wake_digest=wake,
    )
    await loop._tick()
    assert attention.kwargs["wake_digest"] == wake.digest
    assert wake.consumed == 1


@pytest.mark.asyncio
async def test_tick_sans_reveil_passe_none():
    attention = _RecordingAttention()
    loop = CognitiveLoop(
        attention, _FakeReasoning(), _NullDispatcher(), wake_digest=_StubWake(None),
    )
    await loop._tick()
    assert attention.kwargs["wake_digest"] is None


@pytest.mark.asyncio
async def test_sollicitation_signale_lengagement():
    wake = _StubWake()
    loop = CognitiveLoop(
        _RecordingAttention(), _FakeReasoning(), _NullDispatcher(), wake_digest=wake,
    )
    loop.notify_activity(1, "Azrael", "salut", relevant=False)
    assert wake.engagements == 0          # perception passive : il dort encore
    loop.notify_activity(1, "Azrael", "wally ?", relevant=True)
    loop.notify_activity(2, "Azrael", "coucou", is_dm=True)
    assert wake.engagements == 2


@pytest.mark.asyncio
async def test_tick_survit_a_un_wake_digest_en_erreur():
    class _BoomWake(_StubWake):
        async def consume(self, now=None):
            raise RuntimeError("boum")

    attention = _RecordingAttention()
    loop = CognitiveLoop(
        attention, _FakeReasoning(), _NullDispatcher(), wake_digest=_BoomWake(),
    )
    await loop._tick()
    assert attention.kwargs["wake_digest"] is None


# ── Rendu dans le prompt de raisonnement ─────────────────────────────────────

def test_reasoning_rend_le_digest_en_tete():
    from bot.intelligence.reasoning_agent import ReasoningAgent

    agent = ReasoningAgent.__new__(ReasoningAgent)
    agent._channels_text = ""
    agent._capabilities_text = ""
    agent._channel_names = {}
    ctx = SimpleNamespace(
        wake_digest="Pendant que tu dormais, Azrael a organisé une soirée.",
        emotion_state={}, active_desires=[], active_goals=[], recent_thoughts=[],
        recent_interactions=[], time_of_day="morning",
    )
    rendered = agent._format_context(ctx)
    assert "plusieurs heures d'absence" in rendered
    assert "Azrael a organisé une soirée" in rendered
    assert rendered.index("Azrael a organisé") < rendered.index("**Heure :**")
