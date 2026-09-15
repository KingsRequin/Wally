from __future__ import annotations

import asyncio
import io
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from bot.discord import journal_moderation as jm

LOGS, LOGS2, COMMU = 70, 71, 9
LIMITE_TAILLE = 8 * 1024 * 1024  # 8 Mio, plafond d'upload typique d'un serveur non boosté


def _salon_logs(sid, *, limite=LIMITE_TAILLE):
    return SimpleNamespace(id=sid, guild=SimpleNamespace(filesize_limit=limite), send=AsyncMock())


def _bot(salon_ids=(LOGS,), guild_ids=(COMMU,)):
    salons = {sid: _salon_logs(sid) for sid in salon_ids}
    salons[5] = SimpleNamespace(id=5, name="discussions")
    cfg = SimpleNamespace(salon_ids=list(salon_ids), guild_ids=list(guild_ids))
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(journal_moderation=cfg)))
    bot.get_channel = lambda cid: salons.get(cid)
    logs = salons[salon_ids[0]] if salon_ids else _salon_logs(LOGS)
    return bot, logs


def _bot_multi(salon_ids, *, manquant=(), limite=LIMITE_TAILLE, guild_ids=(COMMU,)):
    salons = {sid: _salon_logs(sid, limite=limite) for sid in salon_ids if sid not in manquant}
    salons[5] = SimpleNamespace(id=5, name="discussions")
    cfg = SimpleNamespace(salon_ids=list(salon_ids), guild_ids=list(guild_ids))
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(journal_moderation=cfg)))
    bot.get_channel = lambda cid: salons.get(cid)
    return bot, salons


def _piece(id, nom, *, content_type="image/png", size=1000, echoue=None):
    if echoue is not None:
        to_file = AsyncMock(side_effect=echoue)
    else:
        to_file = AsyncMock(return_value=discord.File(io.BytesIO(b"x"), filename=nom))
    return SimpleNamespace(id=id, filename=nom, content_type=content_type, size=size, to_file=to_file)


def _message(contenu, *, bot_auteur=False, guild=COMMU, pieces=(), auteur_id=1, msg_id=1, channel_id=5):
    auteur = SimpleNamespace(id=auteur_id, bot=bot_auteur, name="alice",
                             display_avatar=SimpleNamespace(url="https://cdn/avatar.png"))
    return SimpleNamespace(
        id=msg_id, content=contenu, guild=SimpleNamespace(id=guild),
        channel=SimpleNamespace(id=channel_id, name="discussions"),
        author=auteur, attachments=list(pieces),
        jump_url=f"https://discord.com/channels/{guild}/{channel_id}/{msg_id}",
    )


def _vue(logs, appel=0):
    return logs.send.await_args_list[appel].kwargs["view"]


def _textes(vue) -> list[str]:
    return [c.content for c in vue.walk_children() if isinstance(c, discord.ui.TextDisplay)]


def _medias(vue) -> list[str]:
    noms = []
    for c in vue.walk_children():
        if isinstance(c, discord.ui.MediaGallery):
            noms.extend(item.media.url.removeprefix("attachment://") for item in c.items)
    return noms


def _fichiers_composants(vue) -> list[str]:
    return [c.url.removeprefix("attachment://") for c in vue.walk_children()
            if isinstance(c, discord.ui.File)]


# ---------------------------------------------------------------------------
# Suppression — cas de base


async def test_suppression_en_cache_image_et_video_journalisee_sans_mention():
    bot, logs = _bot()
    image = _piece(1, "photo.png", content_type="image/png")
    video = _piece(2, "clip.mp4", content_type="video/mp4")
    msg = _message("salut @everyone", pieces=[image, video])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    kwargs = logs.send.await_args.kwargs
    assert kwargs["allowed_mentions"].everyone is False
    vue = kwargs["view"]
    texte = "\n".join(_textes(vue))
    assert "@\u200beveryone" in texte
    assert _medias(vue) == ["photo.png"]
    assert _fichiers_composants(vue) == ["clip.mp4"]
    noms_envoyes = {f.filename for f in kwargs["files"]}
    assert noms_envoyes == {"photo.png", "clip.mp4"}


async def test_piece_indisponible_listee_message_quand_meme_publie():
    bot, logs = _bot()
    piece = _piece(1, "photo.png", echoue=discord.NotFound(SimpleNamespace(status=404, reason="x"), "gone"))
    msg = _message("texte", pieces=[piece])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    logs.send.assert_awaited_once()
    texte = "\n".join(_textes(_vue(logs)))
    assert "photo.png" in texte
    assert "plus disponible" in texte


async def test_piece_trop_lourde_pas_de_telechargement_tente():
    bot, logs = _bot()
    piece = _piece(1, "gros.mp4", content_type="video/mp4", size=LIMITE_TAILLE + 1)
    msg = _message("texte", pieces=[piece])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    piece.to_file.assert_not_awaited()
    texte = "\n".join(_textes(_vue(logs)))
    assert "gros.mp4" in texte
    assert "trop lourde" in texte


async def test_deux_pieces_meme_nom_deux_references_distinctes():
    bot, logs = _bot()
    a, b = _piece(1, "photo.png"), _piece(2, "photo.png")
    msg = _message("texte", pieces=[a, b])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    noms = _medias(_vue(logs))
    assert len(noms) == 2
    assert len(set(noms)) == 2


async def test_suppression_hors_cache():
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=None)

    await jm.message_supprime(bot, payload)

    texte = "\n".join(_textes(_vue(logs)))
    assert "contenu non disponible" in texte
    assert "inconnu" in texte


async def test_guild_hors_liste_ignoree():
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=123, channel_id=5, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    logs.send.assert_not_awaited()


async def test_desactive():
    bot, logs = _bot(salon_ids=[])
    await jm.message_supprime(bot, SimpleNamespace(guild_id=COMMU, channel_id=5,
                                                   message_id=1, cached_message=None))
    logs.send.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fix round 1 — budget cité (borné APRÈS citation, pas avant)


async def test_budget_4000_respecte_avec_3000_plus_3000_caracteres():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("a" * 3000), _message("b" * 3000))
    total = sum(len(t) for t in _textes(_vue(logs)))
    assert total < 4000


async def test_budget_4000_respecte_texte_multiligne_edition():
    """De nombreuses lignes courtes : le préfixe `> ` peut presque doubler la
    taille — border AVANT la citation laissait passer un bloc deux fois trop
    gros (message Discord refusé, entrée perdue)."""
    bot, logs = _bot()
    avant, apres = "a\n" * 1500, "b\n" * 1500
    await jm.message_modifie(bot, _message(avant), _message(apres))
    total = sum(len(t) for t in _textes(_vue(logs)))
    assert total <= 4000


async def test_budget_4000_respecte_texte_multiligne_suppression():
    bot, logs = _bot()
    contenu = "a\n" * 1500
    msg = _message(contenu)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload)
    total = sum(len(t) for t in _textes(_vue(logs)))
    assert total <= 4000


# ---------------------------------------------------------------------------
# Fix round 1 — téléchargement : budget cumulé, collisions de renommage, noms sûrs


async def test_budget_telechargement_cumule_pour_tout_le_message():
    """Un plafond PAR fichier laissait passer 10× la limite en mémoire : le
    budget doit être un reste PARTAGÉ sur tout le message."""
    bot, logs = _bot()
    logs.guild.filesize_limit = 1000
    a, b = _piece(1, "a.png", size=600), _piece(2, "b.png", size=600)
    msg = _message("texte", pieces=[a, b])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    a.to_file.assert_awaited_once()
    b.to_file.assert_not_awaited()
    texte = "\n".join(_textes(_vue(logs)))
    assert "b.png" in texte
    assert "trop lourde" in texte


async def test_trois_pieces_collision_de_renommage_toutes_distinctes():
    """photo.png, photo.png, 1_photo.png : la 2e renommée en 1_photo.png
    collisionnait autrefois avec la 3e (nom brut identique, jamais vérifié)."""
    bot, logs = _bot()
    a, b, c = _piece(1, "photo.png"), _piece(2, "photo.png"), _piece(3, "1_photo.png")
    msg = _message("texte", pieces=[a, b, c])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    noms = _medias(_vue(logs))
    assert len(noms) == 3
    assert len(set(noms)) == 3


async def test_nom_non_ascii_assaini_pour_attachment_uri():
    bot, logs = _bot()
    piece = _piece(1, "été 2026 (1).png")
    msg = _message("texte", pieces=[piece])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    noms = _medias(_vue(logs))
    assert len(noms) == 1
    assert re.fullmatch(r"[A-Za-z0-9_.-]+", noms[0])
    assert noms[0].endswith(".png")


# ---------------------------------------------------------------------------
# Édition


async def test_edition_texte_change_avant_apres():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("ancien texte"), _message("nouveau texte"))
    texte = "\n".join(_textes(_vue(logs)))
    assert "> ancien texte" in texte
    assert "> nouveau texte" in texte


async def test_edition_sans_changement_de_texte_ni_piece_ignoree():
    bot, logs = _bot()
    photo = _piece(1, "photo.png")
    await jm.message_modifie(bot, _message("lien", pieces=[photo]), _message("lien", pieces=[photo]))
    logs.send.assert_not_awaited()


async def test_edition_meme_texte_mais_piece_retiree_publiee_avec_la_piece():
    bot, logs = _bot()
    photo = _piece(1, "photo.png")
    await jm.message_modifie(bot, _message("lien", pieces=[photo]), _message("lien", pieces=[]))
    logs.send.assert_awaited_once()
    assert _medias(_vue(logs)) == ["photo.png"]


async def test_edition_par_un_bot_ignoree():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("a", bot_auteur=True), _message("b", bot_auteur=True))
    logs.send.assert_not_awaited()


async def test_salon_de_logs_injoignable_ne_leve_pas():
    bot, logs = _bot()
    logs.send.side_effect = discord.HTTPException(SimpleNamespace(status=403, reason="x"), "Forbidden")
    await jm.message_modifie(bot, _message("a"), _message("b"))


# ---------------------------------------------------------------------------
# Vocal


async def test_vocal_cree_et_supprime():
    bot, logs = _bot()
    salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
    membre = SimpleNamespace(id=42, name="alice")

    await jm.vocal_cree(bot, membre, salon)
    await jm.vocal_supprime(bot, salon)

    assert logs.send.await_count == 2
    texte_creation = "\n".join(_textes(_vue(logs, 0)))
    assert "<@42>" in texte_creation
    assert "Arène" in texte_creation
    texte_suppression = "\n".join(_textes(_vue(logs, 1)))
    assert "Arène" in texte_suppression


async def test_vocal_cree_sans_guild_ne_leve_pas():
    bot, _logs = _bot()
    salon = SimpleNamespace(id=777, name="Arène")  # pas de `.guild`
    await jm.vocal_cree(bot, SimpleNamespace(id=1, name="alice"), salon)


async def test_vocal_supprime_sans_guild_ne_leve_pas():
    bot, _logs = _bot()
    salon = SimpleNamespace(id=777, name="Arène")  # pas de `.guild`
    await jm.vocal_supprime(bot, salon)


# ---------------------------------------------------------------------------
# Suppression en masse (`on_raw_bulk_message_delete`)


async def test_suppression_en_masse_desactivee():
    bot, logs = _bot(salon_ids=[])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_ids={1, 2, 3}, cached_messages=[])
    await jm.messages_supprimes_en_masse(bot, payload)
    logs.send.assert_not_awaited()


async def test_suppression_en_masse_compte_affiche():
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_ids=set(range(20)), cached_messages=[])
    await jm.messages_supprimes_en_masse(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    assert "20" in texte


async def test_suppression_en_masse_liste_bornee():
    bot, logs = _bot()
    msgs = [_message("texte numéro " * 20, auteur_id=i, msg_id=i) for i in range(50)]
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5,
                              message_ids={m.id for m in msgs}, cached_messages=msgs)
    await jm.messages_supprimes_en_masse(bot, payload)
    total = sum(len(t) for t in _textes(_vue(logs)))
    assert total < 4000


# ---------------------------------------------------------------------------
# Plusieurs salons de logs


async def test_publication_sur_plusieurs_salons_fichiers_distincts():
    bot, salons = _bot_multi([LOGS, LOGS2])
    piece = _piece(1, "photo.png")
    msg = _message("texte", pieces=[piece])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    salons[LOGS].send.assert_awaited_once()
    salons[LOGS2].send.assert_awaited_once()
    f1 = salons[LOGS].send.await_args.kwargs["files"][0]
    f2 = salons[LOGS2].send.await_args.kwargs["files"][0]
    assert f1 is not f2
    assert f1.filename == f2.filename == "photo.png"


async def test_un_salon_manquant_n_empeche_pas_l_autre():
    bot, salons = _bot_multi([LOGS, LOGS2], manquant=[LOGS])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    salons[LOGS2].send.assert_awaited_once()


async def test_un_salon_en_echec_n_empeche_pas_l_autre():
    bot, salons = _bot_multi([LOGS, LOGS2])
    salons[LOGS].send.side_effect = discord.HTTPException(SimpleNamespace(status=403, reason="x"), "Forbidden")
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    salons[LOGS2].send.assert_awaited_once()


async def test_liste_salon_ids_vide_aucun_telechargement():
    bot, salons = _bot_multi([])
    piece = _piece(1, "photo.png")
    msg = _message("texte", pieces=[piece])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload)
    piece.to_file.assert_not_awaited()


async def test_budget_telechargement_prend_la_plus_petite_limite():
    bot, salons = _bot_multi([LOGS, LOGS2])
    salons[LOGS2].guild.filesize_limit = 500   # plus stricte que LOGS
    piece = _piece(1, "photo.png", size=600)
    msg = _message("texte", pieces=[piece])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    piece.to_file.assert_not_awaited()
    texte = "\n".join(_textes(salons[LOGS].send.await_args.kwargs["view"]))
    assert "trop lourde" in texte


# ---------------------------------------------------------------------------
# Enchaînement avec la perception (`edits.py`)


async def test_edits_journalise_meme_dans_une_guild_ignoree(monkeypatch):
    """L'appel est SCHEDULÉ (`_fire`), pas attendu, AVANT le filtre
    `ignored_guilds` de la perception — la perception ne doit pas attendre le
    détour par le journal (téléchargements + envois multi-salons)."""
    from bot.discord.events import edits

    appels = []

    async def faux(bot, before, after):
        appels.append(after.content)

    monkeypatch.setattr(jm, "message_modifie", faux)
    faux_bot = SimpleNamespace(user=SimpleNamespace(id=999),
                               config=SimpleNamespace(discord=SimpleNamespace(ignored_guilds={COMMU})))
    handlers = {}
    faux_bot.event = lambda f: handlers.setdefault(f.__name__, f)
    edits.register(faux_bot)
    await handlers["on_message_edit"](_message("a"), _message("b"))
    await asyncio.sleep(0)     # laisse la tâche schedulée par `_fire` s'exécuter
    assert appels == ["b"]
