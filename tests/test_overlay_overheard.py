"""Une phrase entendue en vocal n'est PAS un événement du live.

Vécu le 2026-08-08 : « du monde débarque, tenez-vous bien » s'affichait sur
l'overlay sans le moindre raid — 30 fois dans la journée. À chaque occurrence,
la bulle suivait d'une seconde une simple phrase de conversation entendue en
vocal.

Le vocal envoyait chaque phrase à `on_stream_event()`, dont le prompt AFFIRME au
modèle qu'il reçoit « un événement qui vient de se produire sur le live : un
raid, un abonnement, des bits, un changement de jeu ou de titre ». Sommé de
ranger « Euh... je ne sais pas si ce serait » dans ces catégories, le modèle
prenait la plus générique et recopiait l'exemple du raid. Il n'inventait pas :
on lui mentait sur la nature de ce qu'on lui donnait.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_voice_listen_only import _service


@pytest.mark.asyncio
async def test_le_vocal_ne_passe_plus_par_le_prompt_des_evenements():
    svc = _service()
    svc.listen_only = True
    svc._vc = MagicMock()
    narrator = MagicMock()
    narrator.count_spoken_vote.return_value = False
    narrator.on_stream_event = AsyncMock(return_value=None)
    narrator.on_overheard = AsyncMock(return_value=None)
    svc._bot.overlay_narrator = narrator

    with patch("bot.core.stream_feed.active_stream_feed", return_value=MagicMock()), \
         patch("bot.discord.voice.service.handle_transcript", new=AsyncMock()):
        user = SimpleNamespace(id=42, display_name="Azrael", name="azrael")
        await svc._dispatch_transcript(user, "euh je sais pas si ce serait", 120.0)
        await asyncio.sleep(0)

    narrator.on_overheard.assert_awaited()
    narrator.on_stream_event.assert_not_awaited()


@pytest.fixture(autouse=True)
def _vocal_diffuse(monkeypatch):
    """Le vocal de ces tests est diffusé au live.

    Sans ça, `on_overheard` refuse tout — et les tests qui vérifient une
    ABSENCE (trois-points, avatar) passeraient sans rien exercer.
    """
    import bot.intelligence.overlay_narrator as narrator_mod

    monkeypatch.setattr(narrator_mod, "_vocal_diffuse", lambda: True)


def _narrator():
    from bot.intelligence.overlay_narrator import OverlayNarrator

    n = OverlayNarrator.__new__(OverlayNarrator)
    n._feed = MagicMock()
    n._recent_bubbles = __import__("collections").deque(maxlen=8)
    n._may_react = lambda: True
    n._overheard_interval = 0.0
    n._mark_spoken = lambda: None
    n._is_repeat = lambda text: False
    n._remember_bubble = lambda text: None
    return n


@pytest.mark.asyncio
async def test_une_bribe_de_conversation_a_son_propre_cadrage():
    """Le prompt des événements décrit un raid/sub/bits : l'y faire passer
    poussait le modèle à inventer un événement qui n'existait pas."""
    from bot.intelligence.overlay_narrator import _EVENT_SYSTEM

    n = _narrator()
    seen = {}

    async def _condense(text, system=None, **_):
        seen["system"] = system
        return "il raconte n'importe quoi"

    n._condense = _condense
    await n.on_overheard("Azraël (vocal) : euh je sais pas")

    assert seen["system"] is not _EVENT_SYSTEM
    # Le cadrage doit NIER l'événement, pas l'énumérer comme une liste de choix.
    assert "pas un événement" in seen["system"].lower()


@pytest.mark.asyncio
async def test_les_vrais_evenements_gardent_leur_cadrage():
    """La régression à éviter : un vrai raid doit continuer d'être annoncé."""
    from bot.intelligence.overlay_narrator import _EVENT_SYSTEM

    n = _narrator()
    seen = {}

    async def _condense(text, system=None, **_):
        seen["system"] = system
        return "du monde débarque"

    n._condense = _condense
    await n.on_stream_event("Un raid de 42 personnes arrive de chez Untel")

    assert seen["system"] is _EVENT_SYSTEM
    n._feed.say.assert_called_once()


@pytest.mark.asyncio
async def test_la_parole_entendue_nallume_pas_les_trois_points():
    """Le vocal passe ici à chaque phrase : des trois-points à chaque fois
    clignoteraient toute la soirée, la plupart sans bulle derrière."""
    n = _narrator()

    async def _condense(text, system=None, **_):
        return None  # le silence, cas normal sur du vocal

    n._condense = _condense
    await n.on_overheard("Azraël (vocal) : mouais bof")

    n._feed.thinking.assert_not_called()


@pytest.mark.asyncio
async def test_la_parole_entendue_nagite_pas_lavatar():
    """`react('stream_event')` fait s'emballer l'avatar : réservé aux vrais
    moments forts, pas à chaque phrase prononcée pendant une partie."""
    n = _narrator()

    async def _condense(text, system=None, **_):
        return "mouais"

    n._condense = _condense
    await n.on_overheard("Azraël (vocal) : un raid de fou dans ce jeu")

    assert not any(c.args and c.args[0] == "stream_event"
                   for c in n._feed.react.call_args_list)


# ── Une bulle doit APPORTER quelque chose ────────────────────────────────────
#
# Le 2026-08-13, sur 148 bulles d'un même live : 44 % ouvraient sur « Il / Elle
# / Ils / On dirait » et 50 % finissaient sur une virgule suivie d'un jugement
# creux. Le squelette dominant était la paraphrase à la 3e personne de la
# phrase qui venait d'être entendue — « je vise les murs » devenait « Il vise
# encore les murs ». Interdire des tournures ne servirait à rien : le modèle en
# invente d'autres. Ce qu'on peut exiger, c'est que la bulle contienne des mots
# que personne ne venait de prononcer.


class _tampon:
    """Un tampon de conversation vocale déjà rempli."""

    def __init__(self, tours):
        self._tours = tours

    def recent_lines(self, limit=8):
        return list(self._tours)[-limit:]


def _condensant(n, sortie):
    async def _condense(text, system=None, **_):
        _condense.vu = text
        return sortie

    _condense.vu = None
    n._condense = _condense
    return _condense


@pytest.mark.asyncio
async def test_une_bulle_qui_ne_fait_que_redire_lechange_nest_pas_publiee():
    n = _narrator()
    _condensant(n, "Il vise encore les murs")

    dit = await n.on_overheard("Azraël (vocal) : je vise les murs là encore")

    assert dit is None
    n._feed.say.assert_not_called()


@pytest.mark.asyncio
async def test_une_bulle_qui_apporte_un_angle_est_publiee():
    """Le garde-fou vise le vide, pas la brièveté : les bonnes bulles du même
    live rapprochent, décalent, précisent — et passent."""
    n = _narrator()
    _condensant(n, "Il compte ses heures comme des PV")

    dit = await n.on_overheard("Azraël (vocal) : ça fait trois heures qu'on joue")

    assert dit == "Il compte ses heures comme des PV"
    n._feed.say.assert_called_once()


@pytest.mark.asyncio
async def test_nommer_quelquun_ne_compte_pas_comme_une_redite(monkeypatch):
    """3 % des bulles nommaient quelqu'un. Le prénom vient forcément de ce qui
    a été entendu : s'il comptait comme un mot recopié, le filtre punirait
    exactement ce qu'on demande."""
    n = _narrator()
    _condensant(n, "Azraël justifie son plafond auprès de Kassandre")

    with patch("bot.core.voice_transcript.active_voice_transcript",
               return_value=_tampon([
                   ("Azraël", "je vise le plafond là"),
                   ("Kassandre", "mais pourquoi tu fais ça"),
               ])):
        dit = await n.on_overheard("Kassandre (vocal) : mais pourquoi tu fais ça")

    assert dit == "Azraël justifie son plafond auprès de Kassandre"


@pytest.mark.asyncio
async def test_le_modele_recoit_lechange_pas_la_phrase_seule():
    """« Et toi ? » ne veut rien dire sans le tour d'avant, et une vanne à
    quatre se comprend sur trois tours. Condenser une réplique isolée ne laisse
    rien à faire d'autre que la paraphraser."""
    n = _narrator()
    condense = _condensant(n, "Personne ne répond à Kassandre")

    with patch("bot.core.voice_transcript.active_voice_transcript",
               return_value=_tampon([
                   ("Azraël", "j'ai encore raté le saut"),
                   ("TaKi", "faut viser plus haut"),
                   ("Kassandre", "et toi ?"),
               ])):
        await n.on_overheard("Kassandre (vocal) : et toi ?")

    assert "raté le saut" in condense.vu       # les tours précédents
    assert "TaKi" in condense.vu               # et QUI a dit quoi
    assert "et toi ?" in condense.vu


@pytest.mark.asyncio
async def test_le_prompt_du_vocal_nomme_le_bot_au_lieu_de_sa_sentinelle():
    """Ces prompts sont des constantes de module, chargées avant l'identité :
    le modèle recevait « la réaction de {{BOT_NAME}} » en toutes lettres."""
    from unittest.mock import AsyncMock as _AsyncMock

    n = _narrator()
    n._llm = MagicMock()
    n._llm.complete = _AsyncMock(return_value="RIEN")

    await n.on_overheard("Azraël (vocal) : bon on y retourne")

    envoye = n._llm.complete.await_args.args[0]
    assert "{{BOT_NAME}}" not in envoye


# ── Cadence : le vocal n'est pas un événement ────────────────────────────────


def _cadence_narrator():
    """Un narrateur avec ses vrais budgets, en live."""
    from bot.intelligence.overlay_narrator import OverlayNarrator

    return OverlayNarrator(MagicMock(), MagicMock(), lambda: True)


@pytest.mark.asyncio
async def test_le_bavardage_vocal_ne_fait_pas_taire_un_raid():
    """Une horloge unique laissait le vocal — qui arrive en continu — manger le
    créneau des événements, qui sont rares et attendus."""
    n = _cadence_narrator()
    vus = []
    n._condense = lambda text, system=None, **kw: _capture(vus, text)

    await n.on_overheard("Azraël (vocal) : bon ça se complique")
    await n.on_stream_event("raid de Kassandre avec 42 spectateurs", kind="raid")

    assert len(vus) == 2, "le raid a été avalé par le budget du vocal"


@pytest.mark.asyncio
async def test_un_raid_nouvre_pas_un_creneau_a_la_parole_entendue():
    """L'inverse est vrai aussi : un événement ne doit pas relancer le
    bavardage juste derrière."""
    n = _cadence_narrator()
    vus = []
    n._condense = lambda text, system=None, **kw: _capture(vus, text)

    await n.on_overheard("Azraël (vocal) : bon ça se complique")
    await n.on_stream_event("raid de Kassandre avec 42 spectateurs", kind="raid")
    await n.on_overheard("TaKi (vocal) : ils débarquent d'où ceux-là")

    assert len(vus) == 2, "la parole entendue a repris le créneau du raid"


@pytest.mark.asyncio
async def test_deux_phrases_daffilee_ne_font_pas_deux_appels():
    """148 bulles en 162 min, 357 appels au modèle : une bulle toutes les 46 à
    66 s pendant trois heures. Le vocal est un flux, pas un événement."""
    n = _cadence_narrator()
    vus = []
    n._condense = lambda text, system=None, **kw: _capture(vus, text)

    for phrase in ("bon ça se complique", "attends attends", "il est où lui"):
        await n.on_overheard(f"Azraël (vocal) : {phrase}")

    assert len(vus) == 1


async def _capture(vus, text):
    vus.append(text)
    return None


@pytest.mark.asyncio
async def test_une_observation_deja_faite_ne_revient_pas_une_heure_plus_tard():
    """« il rit tout seul » est ressorti cinq fois en trois jours, avec cinq
    jugements différents. La mémoire anti-répétition doit couvrir la soirée,
    pas les vingt dernières minutes."""
    remplissage = ("orage", "brique", "tunnel", "cactus", "radeau", "fusible",
                   "bocal", "tiroir", "falaise", "clavier", "vitrine", "poulie",
                   "serpent", "banquise", "poteau", "vernis", "hameau", "gousse",
                   "pinceau", "levier")
    observation = "il rigole tout seul devant son écran"
    tour = [0]

    async def _condense(text, system=None, **_):
        i = tour[0]
        tour[0] += 1
        return observation if i == 0 else remplissage[i - 1] + " en approche"

    n = _cadence_narrator()
    n._overheard_interval = 0.0
    n._condense = _condense

    dit = [await n.on_overheard("Azraël (vocal) : bon on continue")
           for _ in range(len(remplissage) + 1)]
    assert dit[0] == observation and all(dit), "le décor du test ne publie rien"

    tour[0] = 0                                  # la même observation revient
    assert await n.on_overheard("Azraël (vocal) : bon on continue") is None
