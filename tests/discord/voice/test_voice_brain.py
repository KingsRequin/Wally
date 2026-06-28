"""Tests des quick wins vocaux : heuristique de prise de parole + file d'attente anti-drop."""
import asyncio
from collections import OrderedDict
from types import SimpleNamespace

from bot.discord.voice import brain


# ----------------------------------------------------------------------
# _should_respond_voice : heuristique locale rapide (remplace le gate LLM)
# ----------------------------------------------------------------------

def test_repond_si_nomme():
    assert brain._should_respond_voice("salut wally ça va", history=[], named=True) is True


def test_repond_si_question_avec_point_interrogation():
    h = [{"role": "user", "content": "Alex: tu fais quoi ce soir ?"}]
    assert brain._should_respond_voice("tu fais quoi ce soir ?", history=h, named=False) is True


def test_repond_si_question_mot_interrogatif_en_debut():
    h = [{"role": "user", "content": "Alex: pourquoi le ciel est bleu"}]
    assert brain._should_respond_voice("pourquoi le ciel est bleu", history=h, named=False) is True


def test_repond_si_echange_en_cours_apres_que_wally_a_parle():
    # Wally vient de parler, quelqu'un enchaîne → réponse directe attendue.
    h = [
        {"role": "assistant", "content": "moi aussi j'adore ce jeu"},
        {"role": "user", "content": "Alex: ouais c'est clair"},
    ]
    assert brain._should_respond_voice("ouais c'est clair", history=h, named=False) is True


def test_se_tait_si_les_gens_se_parlent_entre_eux():
    # Pas nommé, pas une question, Wally n'est pas intervenu récemment → il écoute.
    h = [
        {"role": "user", "content": "Alex: t'as vu le match hier"},
        {"role": "user", "content": "Bob: ouais c'était fou"},
    ]
    assert brain._should_respond_voice("ouais c'était fou", history=h, named=False) is False


# ----------------------------------------------------------------------
# File d'attente multi-locuteurs : FIFO par personne, coalescing, TTL, plafond
# ----------------------------------------------------------------------

def _svc():
    return SimpleNamespace(is_responding=False, _pending_queue=OrderedDict())


async def _run_blocked_first(monkeypatch, enqueue_actions):
    """Lance une 1re réponse qui bloque, exécute `enqueue_actions` pendant, puis débloque.

    Retourne (calls, service) — calls = [(speaker_id, transcript), ...] dans l'ordre traité.
    """
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[tuple[str, str]] = []

    async def fake_respond_once(bot, service, sid, label, text):
        calls.append((sid, text))
        if text == "premier":
            started.set()
            await release.wait()

    monkeypatch.setattr(brain, "_respond_once", fake_respond_once)
    service = _svc()
    task = asyncio.create_task(brain._maybe_respond(None, service, "u1", "A", "premier"))
    await started.wait()
    await enqueue_actions(service)
    release.set()
    await task
    return calls, service


async def test_chaque_locuteur_different_est_traite(monkeypatch):
    # 3 personnes parlent pendant que Wally répond → les 3 sont traitées, dans l'ordre.
    async def actions(service):
        await brain._maybe_respond(None, service, "u2", "B", "deux")
        await brain._maybe_respond(None, service, "u3", "C", "trois")

    calls, service = await _run_blocked_first(monkeypatch, actions)
    assert calls == [("u1", "premier"), ("u2", "deux"), ("u3", "trois")]
    assert len(service._pending_queue) == 0
    assert service.is_responding is False


async def test_meme_locuteur_coalesce_garde_le_plus_recent(monkeypatch):
    # Le même locuteur répète → une seule réponse, à sa parole la plus récente.
    async def actions(service):
        await brain._maybe_respond(None, service, "u2", "B", "vieux")
        await brain._maybe_respond(None, service, "u2", "B", "recent")

    calls, _ = await _run_blocked_first(monkeypatch, actions)
    assert calls == [("u1", "premier"), ("u2", "recent")]


async def test_parole_en_attente_perimee_est_ignoree(monkeypatch):
    # Une parole en attente depuis plus que le TTL est abandonnée (anti-lag accumulé).
    clock = {"t": 1000.0}
    monkeypatch.setattr(brain, "_now", lambda: clock["t"])

    async def actions(service):
        await brain._maybe_respond(None, service, "u2", "B", "perimee")
        clock["t"] += brain._PENDING_TTL_S + 1  # le temps passe au-delà du TTL

    calls, service = await _run_blocked_first(monkeypatch, actions)
    assert calls == [("u1", "premier")]  # "perimee" jetée car trop vieille
    assert len(service._pending_queue) == 0


async def test_file_plafonnee_evince_les_plus_anciens(monkeypatch):
    # Plus de _PENDING_MAX locuteurs en attente → les plus anciens sont évincés.
    async def actions(service):
        for i in range(brain._PENDING_MAX + 2):
            await brain._maybe_respond(None, service, f"u{i}", f"S{i}", f"m{i}")

    calls, _ = await _run_blocked_first(monkeypatch, actions)
    answered = [t for _, t in calls if t != "premier"]
    assert len(answered) == brain._PENDING_MAX           # plafonné
    assert "m0" not in answered                          # le plus ancien évincé
    assert f"m{brain._PENDING_MAX + 1}" in answered      # le plus récent gardé
