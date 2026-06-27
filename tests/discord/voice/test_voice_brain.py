"""Tests des quick wins vocaux : heuristique de prise de parole + file d'attente anti-drop."""
import asyncio
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
# File d'attente : ne plus jeter la parole entendue pendant que Wally parle
# ----------------------------------------------------------------------

async def test_parole_pendant_la_reponse_est_mise_en_attente(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def fake_respond_once(bot, service, sid, label, text):
        calls.append(text)
        if text == "premier":
            started.set()
            await release.wait()

    monkeypatch.setattr(brain, "_respond_once", fake_respond_once)
    service = SimpleNamespace(is_responding=False, _pending=None)

    task = asyncio.create_task(
        brain._maybe_respond(None, service, "u1", "A", "premier")
    )
    await started.wait()

    # Une nouvelle parole arrive PENDANT que Wally répond → mise en attente, pas jetée.
    await brain._maybe_respond(None, service, "u2", "B", "deuxieme")
    assert service._pending == ("u2", "B", "deuxieme")
    assert calls == ["premier"]  # pas encore traité

    release.set()
    await task
    # À la fin de la réponse, la parole en attente est traitée.
    assert calls == ["premier", "deuxieme"]
    assert service._pending is None
    assert service.is_responding is False


async def test_seule_la_derniere_parole_en_attente_est_gardee(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def fake_respond_once(bot, service, sid, label, text):
        calls.append(text)
        if text == "premier":
            started.set()
            await release.wait()

    monkeypatch.setattr(brain, "_respond_once", fake_respond_once)
    service = SimpleNamespace(is_responding=False, _pending=None)

    task = asyncio.create_task(
        brain._maybe_respond(None, service, "u1", "A", "premier")
    )
    await started.wait()
    await brain._maybe_respond(None, service, "u2", "B", "vieux")
    await brain._maybe_respond(None, service, "u3", "C", "recent")  # écrase "vieux"
    release.set()
    await task

    assert calls == ["premier", "recent"]  # "vieux" est écrasé, pas traité
