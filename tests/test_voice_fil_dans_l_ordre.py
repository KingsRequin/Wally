"""En vocal, le fil de conversation doit être dans l'ORDRE où ça s'est dit.

Symptôme de l'owner : « quand on parle à Wally en voc, on dirait qu'il n'a pas
l'historique de la conversation — si on demande un sondage, qu'il nous demande
une précision et qu'on lui répond, il n'a pas le contexte de la réponse. »

Le fil était pourtant bien alimenté des deux côtés. Le défaut est un ordre
d'écriture :

  · la parole ENTENDUE est consignée à l'instant où le STT la rend ;
  · la réplique de Wally, elle, ne l'était qu'APRÈS `speak()` — c'est-à-dire
    après la synthèse Azure ET la lecture audio complète, plusieurs secondes.

Répondre à Wally pendant qu'il parle est le cas NORMAL d'une conversation. Sa
question s'insérait alors APRÈS la réponse qu'elle avait provoquée :

    user      : fais un sondage
    user      : sur les kills          ← entendu pendant qu'il parle
    assistant : sur quoi, le sondage ?  ← écrit après la lecture

Wally recevait donc un fil où sa propre question tombe après la réponse. Il ne
pouvait pas relier les deux — exactement ce que décrit l'owner.
"""
import asyncio
from types import SimpleNamespace

import pytest

from bot.discord.voice.brain import _remember_line


class _Service:
    """Le strict nécessaire de VoiceService pour ce que ces tests observent."""

    def __init__(self):
        self.history: list[dict] = []
        self.channel_id = 1
        self.dit: list[str] = []

    async def speak(self, text, **_):
        # Une vraie synthèse + lecture : plusieurs secondes. C'est cette durée
        # qui laissait la réponse de l'interlocuteur se glisser avant.
        await asyncio.sleep(0.05)
        self.dit.append(text)


def _lignes(service):
    return [(m["role"], m["content"]) for m in service.history]


@pytest.mark.asyncio
async def test_la_replique_est_au_fil_avant_d_etre_prononcee():
    """Le correctif tient en une chose : consigner AVANT de parler.

    La réplique est décidée au moment où elle est générée — c'est ce moment-là
    qui la situe dans la conversation, pas la fin de sa lecture à voix haute.
    """
    from bot.discord.voice.brain import _consigner_reponse

    service = _Service()
    _remember_line(service, role="user", speaker="Azraël", text="fais un sondage")

    async def _interlocuteur_repond_pendant_qu_il_parle():
        await asyncio.sleep(0.01)      # il a commencé à parler
        _remember_line(service, role="user", speaker="Azraël", text="sur les kills")

    await asyncio.gather(
        _consigner_reponse(service, "sur quoi, le sondage ?"),
        _interlocuteur_repond_pendant_qu_il_parle(),
    )

    assert _lignes(service) == [
        ("user", "Azraël: fais un sondage"),
        ("assistant", "sur quoi, le sondage ?"),
        ("user", "Azraël: sur les kills"),
    ], "la question de Wally doit précéder la réponse qu'elle provoque"
    assert service.dit == ["sur quoi, le sondage ?"]


@pytest.mark.asyncio
async def test_la_replique_reste_au_fil_meme_si_la_voix_echoue():
    """Une panne de TTS ne troue pas le fil : la réplique a été DÉCIDÉE, elle
    compte dans la conversation. Sans ça, Wally ignorerait ce qu'il vient de
    dire chaque fois qu'Azure hoquette.

    L'exception, elle, continue de remonter comme avant — ce lot corrige un
    ORDRE d'écriture, pas la gestion d'erreur du vocal.
    """
    from bot.discord.voice.brain import _consigner_reponse

    service = _Service()

    async def _echoue(text, **_):
        raise RuntimeError("Azure indisponible")

    service.speak = _echoue
    with pytest.raises(RuntimeError):
        await _consigner_reponse(service, "je disais donc")

    assert _lignes(service) == [("assistant", "je disais donc")]


# ── Le chat, en plus du vocal ───────────────────────────────────────────────
#
# Deuxième moitié de la demande : « il lui faut le chat ET le voc ». Le chat du
# live arrive par le flux passif du stream, et ce test vérifie qu'il n'est pas
# écarté sur le chemin vocal — ce qui laisserait Wally sourd à ce qui se dit à
# l'écrit pendant qu'on lui parle à l'oreille.

def test_le_chat_du_live_est_dans_le_contexte_vocal(monkeypatch):
    from bot.intelligence import prompts as mod

    vus: dict = {}

    def _faux_bloc(include_chat=True):
        vus["include_chat"] = include_chat
        return "--- Flux du stream ---\n[chat] quelqu'un: gg" if include_chat else ""

    monkeypatch.setattr(mod, "current_stream_feed_block", _faux_bloc)
    constructeur = mod.PromptBuilder.__new__(mod.PromptBuilder)
    rendu = mod.PromptBuilder.build_voice_system(
        constructeur,
        emotion_state={"joy": 0.5},
        persona_block="persona",
    )

    assert vus.get("include_chat") is True, (
        "le chat du live doit accompagner le vocal : sans lui, Wally n'a que ce "
        "qu'il entend et rate ce qui s'écrit pendant qu'on lui parle")
    assert "Flux du stream" in rendu
