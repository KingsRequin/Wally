"""Rejouer un clip Twitch sur l'overlay.

Le widget `clip` n'affichait qu'une carte texte — « ✂ nouveau clip » + titre +
auteur. Aucune vidéo n'a jamais été jouée.

Deux exigences guident ces tests :
- l'URL d'embed part dans le `src` d'une iframe : elle doit venir de Twitch ;
- sans embed exploitable, on retombe sur la carte plutôt que sur du vide —
  Twitch refuse l'iframe quand le `parent` ne correspond pas au domaine hôte.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.discord.handlers import run_last_clip_tool
from bot.intelligence.overlay_narrator import LAST_CLIP_TOOL_SPEC, OverlayNarrator

EMBED = "https://clips.twitch.tv/embed?clip=GentilPoulet123"
VIDEO = "https://d1ndex63qxojbr.cloudfront.net/nauth/abc/landscape/avc/720p.mp4?sig=x&token=y"

CLIP = {
    "id": "GentilPoulet123",
    "title": "le 1v3 de la mort",
    "creator_name": "Azrael",
    "embed_url": EMBED,
    "duration": 28.5,
    "created_at": "2026-08-07T20:00:00Z",
}


def _n(clip=CLIP, live=True):
    feed = OverlayFeed()
    provider = AsyncMock(return_value=clip)
    return OverlayNarrator(feed, MagicMock(), lambda: live, last_clip=provider), feed


def _widgets(q):
    return [e for e in (q.get_nowait() for _ in range(q.qsize())) if e["type"] == "widget"]


# ── publication ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_fichier_video_est_joue_en_priorite():
    """C'est le SEUL mode qui démarre tout seul : le player Twitch en iframe
    refuse l'autoplay dans un overlay (« style visibility »)."""
    n, feed = _n({**CLIP, "video_url": VIDEO})
    q = feed.subscribe()
    out = await n.play_last_clip()
    assert out["played"] is True
    params = _widgets(q)[-1]["params"]
    assert params["video"] == VIDEO
    assert "embed" not in params, "la vidéo prime sur le player"


@pytest.mark.asyncio
async def test_sans_fichier_video_le_player_prend_le_relais():
    """Filet si l'API GraphQL non officielle change. Mais il attend un clic :
    `played` doit rester faux, sinon Wally annonce une lecture qui n'a pas lieu."""
    n, feed = _n()
    q = feed.subscribe()
    out = await n.play_last_clip()
    assert out["played"] is False
    params = _widgets(q)[-1]["params"]
    assert params["embed"] == EMBED
    assert params["title"] == "le 1v3 de la mort"


@pytest.mark.asyncio
async def test_l_affichage_dure_le_temps_du_clip():
    """Sans marge, le widget s'efface au moment où la vidéo se termine — voire
    avant qu'elle n'ait fini de charger."""
    n, feed = _n()
    q = feed.subscribe()
    await n.play_last_clip()
    assert _widgets(q)[-1]["params"]["duration"] == pytest.approx(28.5 + 3)


@pytest.mark.asyncio
async def test_une_duree_absurde_est_bornee():
    """Un clip Twitch fait 60 s au plus : une valeur folle figerait l'overlay."""
    n, feed = _n({**CLIP, "video_url": VIDEO, "duration": 99999})
    q = feed.subscribe()
    await n.play_last_clip()
    assert _widgets(q)[-1]["params"]["duration"] == pytest.approx(60 + 3)


@pytest.mark.asyncio
async def test_une_duree_illisible_ne_fait_pas_tomber_la_lecture():
    n, feed = _n({**CLIP, "video_url": VIDEO, "duration": "beaucoup"})
    q = feed.subscribe()
    assert (await n.play_last_clip())["played"] is True
    assert _widgets(q)[-1]["params"]["duration"] > 0


# ── la garde sur l'URL ────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "https://evil.example/embed?clip=x",
    "javascript:alert(1)",
    "http://clips.twitch.tv/embed?clip=x",        # pas https
    "https://clips.twitch.tv.evil.com/embed?c=1",
    "",
])
@pytest.mark.asyncio
async def test_une_url_qui_ne_vient_pas_de_twitch_ne_devient_pas_une_iframe(url):
    """Cette URL part dans le `src` d'une iframe : elle ne se discute pas."""
    n, feed = _n({**CLIP, "embed_url": url})
    q = feed.subscribe()
    out = await n.play_last_clip()
    params = _widgets(q)[-1]["params"]
    assert "embed" not in params, f"{url!r} a été acceptée comme embed"
    assert out["played"] is False
    assert params["title"] == "le 1v3 de la mort"   # la carte reste affichée


@pytest.mark.asyncio
async def test_sans_embed_la_carte_prend_le_relais():
    """Twitch refuse l'iframe si le `parent` ne colle pas au domaine hôte.
    Mieux vaut la carte que la vidéo noire."""
    n, feed = _n({**CLIP, "embed_url": ""})
    q = feed.subscribe()
    assert (await n.play_last_clip())["played"] is False
    assert _widgets(q)[-1]["params"]["duration"] == 10


# ── absence de clip ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aucun_clip_ne_publie_rien():
    n, feed = _n(clip=None)
    q = feed.subscribe()
    assert await n.play_last_clip() is None
    assert _widgets(q) == []


@pytest.mark.asyncio
async def test_hors_live_on_ne_va_meme_pas_chercher():
    """Un appel Helix pour rien à chaque demande hors live serait du gâchis."""
    feed = OverlayFeed()
    provider = AsyncMock(return_value=CLIP)
    n = OverlayNarrator(feed, MagicMock(), lambda: False, last_clip=provider)
    assert await n.play_last_clip() is None
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_api_en_erreur_ne_casse_rien():
    feed = OverlayFeed()
    provider = AsyncMock(side_effect=RuntimeError("Helix HS"))
    n = OverlayNarrator(feed, MagicMock(), lambda: True, last_clip=provider)
    assert await n.play_last_clip() is None


@pytest.mark.asyncio
async def test_sans_fournisseur_la_fonction_se_tait():
    """Twitch peut ne pas être configuré du tout."""
    n = OverlayNarrator(OverlayFeed(), MagicMock(), lambda: True)
    assert await n.play_last_clip() is None


# ── l'outil exposé au LLM ─────────────────────────────────────────────────


def _bot(result, active=True):
    narrator = MagicMock()
    narrator.play_last_clip = AsyncMock(return_value=result)
    narrator.is_active.return_value = active
    return SimpleNamespace(overlay_narrator=narrator)


@pytest.mark.asyncio
async def test_l_outil_annonce_le_clip_lance():
    out = json.loads(await run_last_clip_tool(
        _bot({"title": "le 1v3", "author": "Azrael", "played": True}), {}))
    assert out["status"] == "ok"
    assert "lancé" in out["message"] and "le 1v3" in out["message"]


@pytest.mark.asyncio
async def test_l_outil_distingue_la_carte_de_la_video():
    """Wally ne doit pas annoncer une vidéo quand seule la carte est passée."""
    out = json.loads(await run_last_clip_tool(
        _bot({"title": "le 1v3", "author": "Azrael", "played": False}), {}))
    assert "carte" in out["message"] and "lancé" not in out["message"]


@pytest.mark.asyncio
async def test_l_outil_interdit_d_inventer_le_contenu():
    """Wally ne voit pas la vidéo : sans garde, il raconte ce qu'il imagine."""
    out = json.loads(await run_last_clip_tool(
        _bot({"title": "le 1v3", "author": "Azrael", "played": True}), {}))
    assert "ne raconte pas" in out["message"]


@pytest.mark.asyncio
async def test_l_outil_avoue_qu_il_n_y_a_aucun_clip():
    out = json.loads(await run_last_clip_tool(_bot(None), {}))
    assert out["status"] == "nothing"
    assert "invente" in out["message"]


@pytest.mark.asyncio
async def test_l_outil_signale_l_absence_de_live():
    out = json.loads(await run_last_clip_tool(_bot(None, active=False), {}))
    assert out["status"] == "offline"


@pytest.mark.asyncio
async def test_sans_overlay_branche_l_outil_le_dit():
    out = json.loads(await run_last_clip_tool(SimpleNamespace(), {}))
    assert out["status"] == "unavailable"


def test_l_outil_ne_demande_aucun_parametre_obligatoire():
    """« affiche le dernier clip » ne porte aucune donnée : exiger un argument
    ferait hésiter le modèle, comme il hésitait sur le mot du pendu."""
    params = LAST_CLIP_TOOL_SPEC["function"]["parameters"]
    assert params.get("required", []) == []
    assert LAST_CLIP_TOOL_SPEC["function"]["name"] == "show_clip"


# ── le chemin vocal, de bout en bout ──────────────────────────────────────


@pytest.mark.asyncio
async def test_une_demande_vocale_joue_le_clip():
    """C'est par là que « Wally, mets le dernier clip » arrivera."""
    n, feed = _n()
    vus: dict = {}

    async def _fake(system_prompt, messages, tools, tool_executor, **kw):
        vus["outils"] = [t["function"]["name"] for t in tools]
        vus["retour"] = await tool_executor("show_clip", "{}")
        return "regardez-moi ça", []

    n._llm.complete_with_tools = _fake
    q = feed.subscribe()
    assert await n.on_voice_request("Azrael", "wally mets le dernier clip") \
        == "regardez-moi ça"
    assert "show_clip" in vus["outils"]
    assert json.loads(vus["retour"])["status"] == "ok"
    assert _widgets(q)[-1]["params"]["embed"] == EMBED


# ── la garde sur l'URL du fichier vidéo ───────────────────────────────────


@pytest.mark.parametrize("url", [
    "https://evil.example/clip.mp4",
    "http://d1ndex63qxojbr.cloudfront.net/x.mp4",       # pas https
    "https://cloudfront.net.evil.com/x.mp4",
    "javascript:alert(1)",
    "",
])
@pytest.mark.asyncio
async def test_une_video_qui_ne_vient_pas_de_twitch_est_refusee(url):
    """Cette URL part dans un `<video src>` : elle ne se discute pas."""
    n, feed = _n({**CLIP, "video_url": url})
    q = feed.subscribe()
    out = await n.play_last_clip()
    params = _widgets(q)[-1]["params"]
    assert "video" not in params, f"{url!r} a été acceptée"
    assert params["embed"] == EMBED, "on retombe sur le player"
    assert out["played"] is False


@pytest.mark.asyncio
async def test_la_duree_vient_du_clip_en_mode_video():
    n, feed = _n({**CLIP, "video_url": VIDEO, "duration": 25})
    q = feed.subscribe()
    await n.play_last_clip()
    assert _widgets(q)[-1]["params"]["duration"] == pytest.approx(25 + 3)


# ── filtrer par clippeur ──────────────────────────────────────────────────
#
# « affiche le dernier clip fait par azra » : le 2026-08-08, Wally a répondu
# « on n'est pas en live » SANS appeler l'outil (les logs de conversation le
# montrent : ni `tool_called` ni `tool_result`). Deux trous à la fois — l'outil
# ne savait pas filtrer, et sa description l'autorisait à conclure tout seul.


@pytest.mark.asyncio
async def test_le_clippeur_demande_est_transmis_au_fournisseur():
    """Seul le fournisseur peut filtrer : c'est lui qui parle à Helix."""
    feed = OverlayFeed()
    provider = AsyncMock(return_value=CLIP)
    n = OverlayNarrator(feed, MagicMock(), lambda: True, last_clip=provider)
    await n.play_last_clip("azra")
    provider.assert_awaited_once_with("azra", query=None, most_viewed=False)


@pytest.mark.asyncio
async def test_sans_clippeur_le_fournisseur_ne_filtre_rien():
    feed = OverlayFeed()
    provider = AsyncMock(return_value=CLIP)
    n = OverlayNarrator(feed, MagicMock(), lambda: True, last_clip=provider)
    await n.play_last_clip()
    provider.assert_awaited_once_with(None, query=None, most_viewed=False)


@pytest.mark.asyncio
async def test_l_outil_passe_l_auteur_au_narrateur():
    bot = _bot({"title": "le 1v3", "author": "Azrael", "played": True})
    await run_last_clip_tool(bot, {"author": "azra"})
    bot.overlay_narrator.play_last_clip.assert_awaited_once_with(
        "azra", query=None, most_viewed=False
    )


@pytest.mark.asyncio
async def test_l_outil_nomme_la_personne_quand_elle_n_a_rien_clippe():
    """« aucun clip récent » laisserait croire que la chaîne est vide, alors
    que seule cette personne n'a rien clippé."""
    out = json.loads(await run_last_clip_tool(_bot(None), {"author": "azra"}))
    assert out["status"] == "nothing"
    assert "azra" in out["message"].lower()


def test_l_outil_accepte_un_auteur_sans_l_exiger():
    props = LAST_CLIP_TOOL_SPEC["function"]["parameters"]["properties"]
    assert "author" in props
    assert LAST_CLIP_TOOL_SPEC["function"]["parameters"].get("required", []) == []


def test_la_description_n_autorise_pas_a_prejuger_du_live():
    """La mention « ne fonctionne que pendant un live » suffisait à faire
    refuser Wally de tête — sans jamais appeler l'outil, donc sans jamais
    apprendre que l'overlay répondait (mode test actif)."""
    desc = LAST_CLIP_TOOL_SPEC["function"]["description"].lower()
    assert "que pendant un live" not in desc
    assert "sans appeler" in desc


@pytest.mark.asyncio
async def test_le_chemin_vocal_transmet_aussi_le_clippeur():
    """Le chemin vocal a son propre exécuteur d'outils : il ignorait l'argument
    que le chemin texte transmet, et « mets le dernier clip d'azra » à voix
    haute serait retombé sur le clip de n'importe qui."""
    feed = OverlayFeed()
    provider = AsyncMock(return_value=CLIP)
    n = OverlayNarrator(feed, MagicMock(), lambda: True, last_clip=provider)

    async def _fake(system_prompt, messages, tools, tool_executor, **kw):
        await tool_executor("show_clip", json.dumps({"author": "azra"}))
        return "voilà", []

    n._llm.complete_with_tools = _fake
    await n.on_voice_request("KingsRequin", "wally mets le dernier clip d'azra")
    provider.assert_awaited_once_with("azra", query=None, most_viewed=False)
