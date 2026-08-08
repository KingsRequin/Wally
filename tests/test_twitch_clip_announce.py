"""Un clip fraîchement créé n'a pas encore de vidéo : il faut la ré-attendre.

Vécu le 2026-08-08 : quand Wally repérait un clip tout seul, l'overlay n'affichait
que le titre ; le même clip demandé plus tard s'affichait bien en vidéo.

Twitch documente un délai entre la création d'un clip pendant un live et le
moment où son asset est disponible — « indéterminé, typiquement de plusieurs
minutes ». La veille interroge l'API toutes les deux minutes, elle tombait donc
systématiquement sur un clip pas encore transcodé : `get_clip_video_url`
renvoyait None et `show_clip` retombait sur la carte titre.
"""
import pytest

from bot.twitch.clip_announce import CLIP_VIDEO_RETRY_DELAYS, announce_clip


class _Narrator:
    def __init__(self, active=True):
        self.active = active
        self.calls = []

    def is_active(self):
        return self.active

    def show_clip(self, title, author, *, embed_url="", video_url="", duration=0.0):
        self.calls.append({"title": title, "author": author,
                           "embed_url": embed_url, "video_url": video_url,
                           "duration": duration})
        return True


class _Api:
    """Rend la vidéo disponible seulement à partir du n-ième appel."""

    def __init__(self, ready_at_call=1, url="https://x.cloudfront.net/c.mp4"):
        self.ready_at_call = ready_at_call
        self.url = url
        self.calls = 0

    async def get_clip_video_url(self, slug):
        self.calls += 1
        if self.ready_at_call and self.calls >= self.ready_at_call:
            return {"url": self.url, "duration": 12}
        return None


CLIP = {"id": "AbcSlug", "title": "un moment", "creator_name": "KingsRequin",
        "embed_url": "https://clips.twitch.tv/embed?clip=AbcSlug", "duration": 12}


@pytest.fixture
def slept():
    """Neutralise l'attente réelle tout en la gardant observable."""
    waited = []

    async def _sleep(seconds):
        waited.append(seconds)

    return waited, _sleep


@pytest.mark.asyncio
async def test_video_disponible_du_premier_coup(slept):
    waited, sleep = slept
    narrator, api = _Narrator(), _Api(ready_at_call=1)
    await announce_clip(narrator, api, CLIP, sleep=sleep)

    assert narrator.calls[0]["video_url"] == "https://x.cloudfront.net/c.mp4"
    assert waited == []  # rien à attendre : on n'ajoute pas de latence pour rien


@pytest.mark.asyncio
async def test_on_attend_que_twitch_ait_fini_de_transcoder(slept):
    waited, sleep = slept
    narrator, api = _Narrator(), _Api(ready_at_call=3)
    await announce_clip(narrator, api, CLIP, sleep=sleep)

    assert len(narrator.calls) == 1  # affiché UNE fois, pas à chaque tentative
    assert narrator.calls[0]["video_url"] == "https://x.cloudfront.net/c.mp4"
    assert waited == list(CLIP_VIDEO_RETRY_DELAYS[:2])


@pytest.mark.asyncio
async def test_on_annonce_quand_meme_si_la_video_ne_vient_jamais(slept):
    """Mieux vaut la carte que rien : le clippeur mérite qu'on le signale."""
    waited, sleep = slept
    narrator, api = _Narrator(), _Api(ready_at_call=0)
    await announce_clip(narrator, api, CLIP, sleep=sleep)

    assert len(narrator.calls) == 1
    assert narrator.calls[0]["video_url"] == ""
    assert narrator.calls[0]["embed_url"] == CLIP["embed_url"]
    assert len(waited) == len(CLIP_VIDEO_RETRY_DELAYS)


@pytest.mark.asyncio
async def test_rien_si_loverlay_setiend_pendant_lattente(slept):
    """L'attente peut dépasser la fin du live — inutile de pousser dans le vide."""
    waited, _sleep = slept
    narrator, api = _Narrator(), _Api(ready_at_call=0)

    async def _sleep_then_stop(seconds):
        waited.append(seconds)
        narrator.active = False

    await announce_clip(narrator, api, CLIP, sleep=_sleep_then_stop)
    assert narrator.calls == []


@pytest.mark.asyncio
async def test_une_api_qui_leve_ne_fait_pas_tomber_lannonce(slept):
    _waited, sleep = slept

    class _Boom:
        async def get_clip_video_url(self, slug):
            raise RuntimeError("GQL down")

    narrator = _Narrator()
    await announce_clip(narrator, _Boom(), CLIP, sleep=sleep)
    assert narrator.calls[0]["video_url"] == ""  # repli, pas de plantage


@pytest.mark.asyncio
async def test_la_duree_vient_de_la_video_quand_on_la_connait(slept):
    _waited, sleep = slept
    narrator, api = _Narrator(), _Api(ready_at_call=1)
    await announce_clip(narrator, api, {**CLIP, "duration": 99}, sleep=sleep)
    assert narrator.calls[0]["duration"] == 12
