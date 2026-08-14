# tests/test_voice_transcript_context.py
"""Ce qui se dit en vocal remonte dans les réponses ÉCRITES de Wally.

Il était dans le salon vocal et incapable d'en dire un mot dans le chat Twitch.
Le tampon corrige ça — sans jamais laisser sortir un vocal privé : la garde est
posée à l'écriture, pas au rendu.
"""
import time

import pytest

import bot.core.voice_transcript as vt
from bot.core.voice_transcript import VoiceTranscriptFeed
from bot.intelligence.prompts import PromptBuilder

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}

SALON = 4242
AUTRE_SALON = 9999


@pytest.fixture(autouse=True)
def _reset_active():
    vt._active = None
    yield
    vt._active = None


@pytest.fixture(autouse=True)
def _live(monkeypatch):
    """Le live tourne : sans lui, rien n'est jamais retenu (c'est le but)."""
    monkeypatch.setattr(vt, "current_stream_status", lambda: {"live": True})


def _feed_en_direct(**kwargs) -> VoiceTranscriptFeed:
    feed = VoiceTranscriptFeed(**kwargs)
    feed.activate()
    feed.open_broadcast(SALON)
    return feed


# ── La garde à l'écriture ────────────────────────────────────────────────────

def test_rien_n_est_retenu_hors_live():
    feed = VoiceTranscriptFeed()
    feed.activate()
    assert feed.record(SALON, "Azraël", "on repart sur Storm Point") is False
    assert feed.render() == ""


def test_rien_n_est_retenu_d_un_autre_salon():
    feed = _feed_en_direct()
    assert feed.record(AUTRE_SALON, "Bob", "un secret entre nous") is False
    assert "secret" not in feed.render()


def test_rien_n_est_retenu_si_le_live_s_est_eteint(monkeypatch):
    """Deuxième verrou : la transition de fin de live peut être ratée."""
    feed = _feed_en_direct()
    monkeypatch.setattr(vt, "current_stream_status", lambda: {"live": False})
    assert feed.record(SALON, "Azraël", "bon, on arrête là") is False


def test_le_vocal_d_avant_le_live_ne_remonte_jamais():
    """Le trou que la garde au rendu laissait passer.

    Une demi-heure de vocal PRÉCÉDANT le lancement du stream n'a été entendue
    par aucun viewer : ouvrir la captation ne doit pas la rendre publique.
    """
    feed = VoiceTranscriptFeed()
    feed.activate()
    feed.record(SALON, "Azraël", "faut que je te raconte ma soirée d'hier")
    feed.open_broadcast(SALON)
    feed.record(SALON, "Azraël", "salut le chat")

    rendu = feed.render()
    assert "soirée d'hier" not in rendu
    assert "salut le chat" in rendu


def test_changer_de_salon_diffuse_oublie_le_precedent():
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "première partie")
    feed.open_broadcast(AUTRE_SALON)
    assert "première partie" not in feed.render()


def test_la_fin_du_live_purge_le_tampon():
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "gg les gars")
    feed.close_broadcast()
    assert feed.render() == ""
    # Et ce qui suit ne rentre plus.
    assert feed.record(SALON, "Azraël", "bon, entre nous") is False


def test_purge_explicite_au_depart_du_salon():
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "gg les gars")
    feed.clear("salon quitté")
    assert feed.render() == ""


# ── Le tampon ────────────────────────────────────────────────────────────────

def test_une_replique_vide_n_entre_pas():
    feed = _feed_en_direct()
    assert feed.record(SALON, "Azraël", "   ") is False
    assert feed.record(SALON, "", "du texte") is False


def test_le_tampon_est_borne():
    feed = _feed_en_direct(max_lines=3)
    for i in range(6):
        feed.record(SALON, "Azraël", f"réplique {i}")
    rendu = feed.render()
    assert "réplique 0" not in rendu
    assert "réplique 5" in rendu
    assert rendu.count("· [") == 3


def test_une_replique_perimee_disparait():
    feed = _feed_en_direct(line_ttl=60.0)
    feed.record(SALON, "Azraël", "c'était il y a longtemps")
    # Vieillissement direct du tampon : l'horloge monotone n'est pas réglable.
    ts, speaker, text = feed._lines[0]
    feed._lines[0] = (ts - 3600.0, speaker, text)
    assert feed.render() == ""


def test_l_ancienneté_est_dite_quand_ca_s_est_calme():
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "on y va")
    ts, speaker, text = feed._lines[0]
    feed._lines[0] = (ts - 600.0, speaker, text)
    rendu = feed.render()
    assert "il y a 10 min" in rendu
    assert "on y va" in rendu


# ── Le rendu ─────────────────────────────────────────────────────────────────

def test_le_bloc_dit_qui_est_present():
    feed = _feed_en_direct()
    feed.set_presence_source(lambda: ["Azraël", "KingsRequin"])
    feed.record(SALON, "Azraël", "on repart ?")
    assert "Azraël, KingsRequin" in feed.render()


def test_un_fournisseur_de_presence_casse_ne_casse_pas_le_bloc():
    feed = _feed_en_direct()

    def _boum() -> list[str]:
        raise RuntimeError("salon introuvable")

    feed.set_presence_source(_boum)
    feed.record(SALON, "Azraël", "on repart ?")
    assert "on repart ?" in feed.render()


def test_le_bloc_previent_que_c_est_du_stt():
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "on repart ?")
    assert "transcription automatique" in feed.render()


def test_le_bloc_dit_que_ces_gens_ne_sont_pas_dans_le_chat():
    """Sans ça, Wally répond dans le chat Twitch à une question posée en vocal."""
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "wally t'en penses quoi ?")
    rendu = feed.render()
    assert "EN VOCAL" in rendu
    assert "Ne leur réponds pas ici" in rendu


# ── L'injection au prompt ────────────────────────────────────────────────────

def test_le_bloc_arrive_dans_le_prompt_systeme():
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "on repart sur Storm Point")
    out = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "Conversation vocale en cours" in out
    assert "Storm Point" in out


def test_aucun_bloc_sans_tampon_actif():
    out = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "Conversation vocale en cours" not in out


def test_le_bloc_est_absent_du_chemin_vocal():
    """Sur le chemin vocal, ces répliques sont déjà dans les `messages` :
    les réinjecter les montrerait deux fois, une fois datées une fois pas."""
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "on repart sur Storm Point")
    out = PromptBuilder().build_system_prompt(
        emotion_state=_EMOTIONS_FLAT, situation={"platform": "discord_vocal"}
    )
    assert "Conversation vocale en cours" not in out


def test_le_bloc_est_present_sur_le_chemin_twitch():
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "on repart sur Storm Point")
    out = PromptBuilder().build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        situation={"platform": "twitch", "stream_live": True},
    )
    assert "Conversation vocale en cours" in out


@pytest.mark.asyncio
async def test_la_cognition_percoit_toujours_le_vocal(monkeypatch):
    """Le vocal transitait par le flux du stream, que la cognition lit. L'en
    sortir ne doit pas rendre la boucle cognitive sourde."""
    import bot.core.system_info as si
    from bot.intelligence.attention_agent import AttentionAgent

    monkeypatch.setattr(si, "read_host_metrics", lambda: None, raising=False)

    async def _no_weather():
        return None

    monkeypatch.setattr(si, "fetch_weather_france", _no_weather, raising=False)

    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "on repart sur Storm Point")

    ctx = await AttentionAgent(_FactsMuets()).build_context({"boredom": 0.1}, [])
    assert ctx.stream_feed and "Storm Point" in ctx.stream_feed


class _FactsMuets:
    """Un magasin de faits qui ne répond rien : seul le bloc vocal nous intéresse."""

    async def search_by_category(self, *a, **k):
        return []

    async def get_latest_by_source(self, *a, **k):
        return None

    async def get_by_user(self, *a, **k):
        return []

    async def sample_random(self, *a, **k):
        return []


# ── Les logs ─────────────────────────────────────────────────────────────────

def test_le_verdict_ne_change_pas_a_chaque_replique():
    """Le verdict INFO n'est logué qu'aux transitions.

    Y glisser le nombre de répliques rendrait chaque rendu « nouveau » et le
    filtre anti-bruit ne filtrerait plus rien : une soirée en vocal noierait
    les logs sous une ligne par message reçu.
    """
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "une")
    feed.render()
    premier = feed._last_verdict
    feed.record(SALON, "Azraël", "deux")
    feed.render()
    assert feed._last_verdict == premier


def test_un_refus_repete_ne_se_relogue_pas():
    """Hors live, Wally entend une phrase toutes les deux secondes : sans le
    filtre par motif, une soirée écrirait une ligne de log par phrase."""
    feed = VoiceTranscriptFeed()
    feed.activate()
    feed.record(SALON, "Azraël", "une")
    motif = feed._last_refusal
    assert motif is not None
    feed.record(SALON, "Azraël", "deux")
    assert feed._last_refusal == motif


def test_un_refus_pour_un_autre_motif_est_bien_trace():
    feed = _feed_en_direct()
    feed.record(AUTRE_SALON, "Bob", "ailleurs")
    premier = feed._last_refusal
    feed.close_broadcast()
    feed.record(SALON, "Azraël", "et maintenant hors live")
    assert feed._last_refusal != premier


def test_une_replique_retenue_rearme_la_trace_de_refus():
    """Sinon le refus qui suit une période normale passerait sous silence."""
    feed = _feed_en_direct()
    feed.record(AUTRE_SALON, "Bob", "ailleurs")
    feed.record(SALON, "Azraël", "ici")
    assert feed._last_refusal is None


def test_le_verdict_change_quand_le_bloc_disparait():
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "une")
    feed.render()
    present = feed._last_verdict
    feed.close_broadcast()
    feed.render()
    assert feed._last_verdict != present


# ── Le vieillissement n'est pas simulé : garde-fou sur l'horloge ─────────────

def test_l_horloge_utilisee_est_monotone():
    """Le tampon date ses lignes avec `time.monotonic` : une horloge murale qui
    recule (NTP) ferait ressortir des répliques périmées."""
    feed = _feed_en_direct()
    avant = time.monotonic()
    feed.record(SALON, "Azraël", "maintenant")
    ts = feed._lines[0][0]
    assert avant <= ts <= time.monotonic()


# ── L'échange, pour qui a besoin des tours et pas du bloc rédigé ─────────────


def test_les_derniers_tours_sont_rendus_avec_qui_les_a_dits():
    """L'overlay condense un ÉCHANGE : sans le locuteur ni les tours d'avant,
    « et toi ? » ne veut rien dire et la bulle ne peut nommer personne."""
    feed = _feed_en_direct()
    feed.record(SALON, "Azraël", "j'ai encore raté le saut")
    feed.record(SALON, "Kassandre", "et toi ?")

    assert feed.recent_lines() == [
        ("Azraël", "j'ai encore raté le saut"),
        ("Kassandre", "et toi ?"),
    ]


def test_les_derniers_tours_sarretent_au_nombre_demande():
    feed = _feed_en_direct()
    for i in range(6):
        feed.record(SALON, "Azraël", f"réplique {i}")

    tours = feed.recent_lines(2)
    assert [t for _s, t in tours] == ["réplique 4", "réplique 5"]


def test_aucun_tour_hors_diffusion():
    """Même règle que le reste, et par le même chemin : ce qui n'a pas été
    retenu ne peut pas ressortir."""
    feed = VoiceTranscriptFeed()
    feed.activate()
    assert feed.record(SALON, "Azraël", "un secret entre nous") is False
    assert feed.recent_lines() == []


def test_un_tour_perime_ne_ressort_pas(monkeypatch):
    feed = _feed_en_direct(line_ttl=0.01)
    feed.record(SALON, "Azraël", "c'était il y a longtemps")
    monkeypatch.setattr(time, "monotonic", lambda: time.perf_counter() + 3600)

    assert feed.recent_lines() == []
