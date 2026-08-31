"""La veille des clips : ce qu'elle annonce, et surtout ce qu'elle N'annonce PAS.

Extraite du `main()` de mille lignes le 2026-08-23. Elle y portait deux
arbitrages payés en production que rien ne vérifiait :

  · la mémoire des clips déjà vus est une `deque(maxlen=200)` et non un `set`
    vidé d'un coup. Avec le `clear()`, jusqu'à VINGT clips étaient réannoncés au
    tour suivant — la fenêtre demandée à Twitch fait cinq minutes, la période
    deux. C'est le test `test_un_clip_deja_vu_n_est_jamais_reannonce` ;
  · l'annonce part en tâche de fond, parce qu'elle attend que Twitch ait fini
    de préparer le clip. La faire en ligne bloquerait la veille, et les clips
    suivants passeraient à la trappe.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot.twitch.clip_announce import VeilleDesClips


def _veille(clips, *, actif=True):
    narrateur = MagicMock()
    narrateur.is_active = MagicMock(return_value=actif)
    discord_bot = MagicMock()
    discord_bot.overlay_narrator = narrateur

    twitch_bot = MagicMock()
    twitch_bot.twitch_api.get_recent_clips = AsyncMock(return_value=clips)
    return VeilleDesClips(discord_bot=discord_bot, twitch_bot=twitch_bot), twitch_bot


def _patcher_annonce(monkeypatch):
    """Remplace `announce_clip` et rend la liste des clips qui y sont passés."""
    vus: list[dict] = []

    async def _faux(narrateur, api, clip):
        vus.append(clip)

    monkeypatch.setattr("bot.twitch.clip_announce.announce_clip", _faux)
    return vus


async def test_un_clip_neuf_est_annonce(monkeypatch):
    vus = _patcher_annonce(monkeypatch)
    v, _ = _veille([{"id": "abc"}])
    await v.un_tour()
    await asyncio.gather(*list(v._taches))
    assert [c["id"] for c in vus] == ["abc"]


async def test_un_clip_deja_vu_n_est_JAMAIS_reannonce(monkeypatch):
    """Le défaut payé en prod. La fenêtre demandée à Twitch fait cinq minutes,
    la période deux : le même clip revient dans deux ou trois réponses de
    suite. Sans mémoire, l'écran le rejouerait autant de fois."""
    vus = _patcher_annonce(monkeypatch)
    v, _ = _veille([{"id": "abc"}])
    for _ in range(3):
        await v.un_tour()
        await asyncio.gather(*list(v._taches))
    assert [c["id"] for c in vus] == ["abc"]


async def test_la_memoire_est_BORNEE_et_sort_les_plus_vieux_un_par_un(monkeypatch):
    """`deque(maxlen)` et pas un `set` vidé d'un coup : le `clear()` oubliait
    TOUT, et jusqu'à vingt clips repartaient à l'écran au tour suivant."""
    _patcher_annonce(monkeypatch)
    v, twitch = _veille(None)
    n = VeilleDesClips.MEMOIRE
    twitch.twitch_api.get_recent_clips = AsyncMock(
        return_value=[{"id": str(i)} for i in range(n + 5)])
    await v.un_tour()
    await asyncio.gather(*list(v._taches))
    # L'invariant est « BORNÉE », pas « bornée à 200 » : lire la constante
    # ferait passer le test quelle que soit sa valeur, y compris un maxlen
    # assez grand pour ne jamais mordre — ce qui est le défaut d'origine.
    assert v._vus.maxlen is not None
    assert len(v._vus) == n
    assert "0" not in v._vus        # les cinq plus vieux sont sortis
    assert str(n + 4) in v._vus     # le plus récent est là


async def test_un_clip_sans_id_est_ignore(monkeypatch):
    vus = _patcher_annonce(monkeypatch)
    v, _ = _veille([{"id": ""}, {}, {"id": "bon"}])
    await v.un_tour()
    await asyncio.gather(*list(v._taches))
    assert [c["id"] for c in vus] == ["bon"]


async def test_sans_narrateur_actif_on_n_interroge_meme_pas_twitch(monkeypatch):
    """L'overlay est fermé : personne ne verrait le clip. Interroger l'API pour
    rien coûterait un appel toutes les deux minutes, toute la journée."""
    _patcher_annonce(monkeypatch)
    v, twitch = _veille([{"id": "abc"}], actif=False)
    await v.un_tour()
    twitch.twitch_api.get_recent_clips.assert_not_awaited()


async def test_l_annonce_part_en_TACHE_DE_FOND(monkeypatch):
    """Elle attend que Twitch ait fini de préparer le clip. En ligne, elle
    bloquerait la veille et les clips suivants passeraient à la trappe."""
    lent = asyncio.Event()

    async def _traine(narrateur, api, clip):
        await lent.wait()

    monkeypatch.setattr("bot.twitch.clip_announce.announce_clip", _traine)
    v, _ = _veille([{"id": "abc"}])
    # `wait_for` et pas un simple `await` : si l'annonce redevenait EN LIGNE,
    # `un_tour()` ne rendrait jamais la main et le test PENDRAIT au lieu
    # d'échouer. Un test qui pend bloque la suite entière et se fait tuer par
    # un timeout global, très loin de sa cause.
    await asyncio.wait_for(v.un_tour(), timeout=2.0)
    assert len(v._taches) == 1      # référence forte gardée
    lent.set()
    await asyncio.gather(*list(v._taches))
    assert not v._taches            # le callback l'a retirée


async def test_une_API_en_erreur_ne_tue_pas_la_veille(monkeypatch):
    """Elle tourne dans une boucle sans fin : une exception qui remonte
    l'arrêterait pour de bon, et plus aucun clip ne serait annoncé du live."""
    _patcher_annonce(monkeypatch)
    v, twitch = _veille(None)
    twitch.twitch_api.get_recent_clips = AsyncMock(side_effect=RuntimeError("Twitch fâché"))
    await v.un_tour()               # ne doit pas lever


async def test_une_reponse_VIDE_ne_casse_rien(monkeypatch):
    """`get_recent_clips` peut rendre `None` : `for clip in None` lèverait."""
    _patcher_annonce(monkeypatch)
    v, twitch = _veille(None)
    twitch.twitch_api.get_recent_clips = AsyncMock(return_value=None)
    await v.un_tour()
    assert not v._vus


async def test_la_fenetre_demandee_est_plus_LARGE_que_la_periode():
    """Sinon un clip créé pile entre deux tours ne serait jamais vu. C'est cet
    écart qui impose la mémoire des clips déjà annoncés."""
    assert VeilleDesClips.FENETRE_MIN * 60 > VeilleDesClips.PERIODE_S


async def test_le_clip_part_a_lecran_pendant_quon_en_parle_encore():
    """Le clip est REJOUÉ, pas archivé : sa valeur tient à sa fraîcheur.

    Deux bornes, et pas une ligne d'implémentation : le temps de DÉTECTION
    (période de veille) et le temps de LATENCE une fois la vidéo prête (le pas
    entre deux reprises). C'est la somme des deux que le public voit.
    """
    from bot.twitch.clip_announce import CLIP_VIDEO_RETRY_DELAYS

    assert VeilleDesClips.PERIODE_S <= 30
    assert max(CLIP_VIDEO_RETRY_DELAYS) <= 20
    # Sans plafond, une tâche par clip sonderait l'API GQL non officielle
    # jusqu'à la fin du live.
    assert 120 <= sum(CLIP_VIDEO_RETRY_DELAYS) <= 300
