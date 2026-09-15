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


def _bot(salon_ids=(LOGS,), guild_ids=(COMMU,), *, inclure_bots=False):
    salons = {sid: _salon_logs(sid) for sid in salon_ids}
    salons[5] = SimpleNamespace(id=5, name="discussions")
    cfg = SimpleNamespace(salon_ids=list(salon_ids), guild_ids=list(guild_ids), inclure_bots=inclure_bots)
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(journal_moderation=cfg)))
    bot.get_channel = lambda cid: salons.get(cid)
    logs = salons[salon_ids[0]] if salon_ids else _salon_logs(LOGS)
    return bot, logs


def _bot_multi(salon_ids, *, manquant=(), limite=LIMITE_TAILLE, guild_ids=(COMMU,), inclure_bots=False):
    salons = {sid: _salon_logs(sid, limite=limite) for sid in salon_ids if sid not in manquant}
    salons[5] = SimpleNamespace(id=5, name="discussions")
    cfg = SimpleNamespace(salon_ids=list(salon_ids), guild_ids=list(guild_ids), inclure_bots=inclure_bots)
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(journal_moderation=cfg)))
    bot.get_channel = lambda cid: salons.get(cid)
    return bot, salons


def _piece(id, nom, *, content_type="image/png", size=1000, echoue=None):
    if echoue is not None:
        to_file = AsyncMock(side_effect=echoue)
    else:
        to_file = AsyncMock(return_value=discord.File(io.BytesIO(b"x"), filename=nom))
    return SimpleNamespace(id=id, filename=nom, content_type=content_type, size=size, to_file=to_file)


def _message(contenu, *, bot_auteur=False, guild=COMMU, pieces=(), auteur_id=1, msg_id=1, channel_id=5,
             auteur_nom="alice"):
    auteur = SimpleNamespace(id=auteur_id, bot=bot_auteur, name=auteur_nom,
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
# Fix round 2 — pires cas CONSTRUITS (pas mesurés à la main) : chaque bloc au
# plafond EN MÊME TEMPS (texte multiligne max + liste de pièces non
# récupérées à son maximum), plutôt qu'un seul bloc isolé.


async def test_budget_4000_pire_cas_edition_texte_et_pieces_non_recuperees():
    """Avant ET après au plafond de citation, PLUS 15 pièces retirées (plus
    que `_MAX_PIECES`, mélange « plus disponible » / « au-delà de 10 »), avec
    des noms longs — le pire cas mesuré par le reviewer (~3654 caractères)."""
    bot, logs = _bot()
    avant, apres = "a\n" * 2000, "b\n" * 2000
    nom_long = "x" * 80 + ".png"
    pieces = [_piece(i, nom_long,
                     echoue=discord.NotFound(SimpleNamespace(status=404, reason="x"), "gone"))
              for i in range(15)]
    await jm.message_modifie(bot, _message(avant, pieces=pieces), _message(apres, pieces=[]))
    blocs = _textes(_vue(logs))
    total = sum(len(t) for t in blocs)
    assert total <= 4000
    # Preuve que les plafonds ont bien été ATTEINTS, pas simplement respectés
    # sur une entrée qui n'y touchait jamais : chaque bloc concurrent doit
    # porter la marque de sa troncature.
    bloc_avant = next(b for b in blocs if b.startswith("**Avant**"))
    bloc_apres = next(b for b in blocs if b.startswith("**Après**"))
    bloc_non_recup = next(b for b in blocs if "non récupérées" in b)
    assert bloc_avant.endswith("…")
    assert bloc_apres.endswith("…")
    assert bloc_non_recup.endswith("…")


async def test_budget_4000_pire_cas_suppression_texte_et_pieces_non_recuperees():
    """Contenu au plafond de citation PLUS 15 pièces non récupérables à noms
    longs — pire cas mesuré par le reviewer (~2115 caractères)."""
    bot, logs = _bot()
    contenu = "a\n" * 2000
    nom_long = "y" * 80 + ".png"
    pieces = [_piece(i, nom_long,
                     echoue=discord.NotFound(SimpleNamespace(status=404, reason="x"), "gone"))
              for i in range(15)]
    msg = _message(contenu, pieces=pieces)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload)
    blocs = _textes(_vue(logs))
    total = sum(len(t) for t in blocs)
    assert total <= 4000
    bloc_contenu = next(b for b in blocs if b.startswith("> "))
    bloc_non_recup = next(b for b in blocs if "non récupérées" in b)
    assert bloc_contenu.endswith("…")
    assert bloc_non_recup.endswith("…")


async def test_budget_4000_pire_cas_suppression_en_masse():
    """Beaucoup de messages en cache, auteurs et contenus longs — pire cas
    mesuré par le reviewer (~1558 caractères)."""
    bot, logs = _bot()
    msgs = [_message("x" * 500, auteur_id=i, msg_id=i, auteur_nom="a" * 40) for i in range(100)]
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5,
                              message_ids={m.id for m in msgs}, cached_messages=msgs)
    await jm.messages_supprimes_en_masse(bot, payload)
    blocs = _textes(_vue(logs))
    total = sum(len(t) for t in blocs)
    assert total <= 4000
    assert re.search(r"… et \d+ autres?", "\n".join(blocs))


def test_borner_ne_coupe_jamais_un_arobase_isole():
    """`_echapper` neutralise un `@` avec un zero-width space qui le SUIT :
    couper pile entre les deux ressusciterait une mention réelle."""
    texte = "x" * 10 + "@" + "\u200b" + "y" * 10
    resultat = jm._borner(texte, 12)   # la coupure tombe pile après le `@`
    assert not resultat.endswith("@…")
    assert not resultat[:-1].endswith("@")


def test_borner_ne_coupe_jamais_un_backslash_isole():
    """Round 2 #B : `escape_markdown` protège un délimiteur avec un
    backslash qui le PRÉCÈDE — couper pile juste après ce backslash le
    laisserait seul devant l'ellipse, sans rien à échapper (même geste que
    ci-dessus, pour un backslash mort plutôt qu'une mention ressuscitée)."""
    texte = "x" * 10 + "\\" + "*" + "y" * 10
    resultat = jm._borner(texte, 12)   # la coupure tombe pile après le backslash
    assert not resultat.endswith("\\…")
    assert not resultat[:-1].endswith("\\")


def test_borner_lignes_singulier_pour_une_seule_ligne_restante():
    """« … et 1 autres » est un mauvais français : le singulier s'impose."""
    lignes = ["a" * 50, "b" * 50]
    resultat = jm._borner_lignes(lignes, 65)   # seule la 1re ligne tient
    assert resultat.endswith("… et 1 autre")
    assert "1 autres" not in resultat


def test_borner_lignes_pluriel_pour_plusieurs_lignes_restantes():
    lignes = ["a" * 50, "b" * 50, "c" * 50]
    resultat = jm._borner_lignes(lignes, 65)   # seule la 1re ligne tient, 2 restent
    assert resultat.endswith("… et 2 autres")


async def test_suppression_en_masse_liste_bornee_par_lignes_entieres():
    """`_borner` coupait au caractère près : une ligne `**auteur**` tronquée
    en plein milieu du marqueur mettait tout le RESTE du message en gras."""
    bot, logs = _bot()
    msgs = [_message("x" * 100, auteur_id=i, msg_id=i) for i in range(80)]
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5,
                              message_ids={m.id for m in msgs}, cached_messages=msgs)

    await jm.messages_supprimes_en_masse(bot, payload)

    texte = "\n".join(_textes(_vue(logs)))
    for ligne in texte.splitlines():
        if "…" not in ligne:
            assert ligne.count("**") % 2 == 0   # jamais un marqueur `**` coupé en deux
    assert "… et" in texte and "autres" in texte


async def test_nom_auteur_avec_underscores_echappe_dans_la_meta():
    bot, logs = _bot()
    msg = _message("texte", auteur_nom="a_b_c")
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    assert "a\\_b\\_c" in texte


async def test_nom_auteur_avec_underscores_echappe_en_masse():
    bot, logs = _bot()
    msg = _message("texte", auteur_nom="a_b_c")
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_ids={msg.id}, cached_messages=[msg])
    await jm.messages_supprimes_en_masse(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    assert "a\\_b\\_c" in texte


async def test_salon_introuvable_avertit_avec_son_id():
    bot, _salons = _bot_multi([999], manquant=[999])
    dits: list[str] = []
    jeton = jm.logger.add(lambda m: dits.append(str(m)), level="WARNING")
    try:
        payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=None)
        await jm.message_supprime(bot, payload)
    finally:
        jm.logger.remove(jeton)
    assert any("999" in d for d in dits)


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
    """Un seul mot change : le diff met en évidence CE mot, pas tout le
    message — `**Modification**` plutôt que deux blocs Avant/Après."""
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("ancien texte"), _message("nouveau texte"))
    texte = "\n".join(_textes(_vue(logs)))
    assert "**Modification**" in texte
    assert "~~ancien~~" in texte
    assert "**nouveau**" in texte
    assert "texte" in texte
    assert "**Avant**" not in texte
    assert "**Après**" not in texte


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
    blocs = _textes(_vue(logs))
    # Le texte n'a pas bougé : aucun bloc de contenu — ni diff ni Avant/Après,
    # ce serait un « changement » affiché sur du texte identique.
    assert not any("Modification" in b or "Avant" in b or "Après" in b for b in blocs)


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


# ---------------------------------------------------------------------------
# Revue finale — un événement né dans un salon de logs ne se journalise pas


async def test_suppression_dans_un_salon_de_logs_non_republiee():
    """Supprimer une fiche du journal la republiait aussitôt, à l'infini."""
    bot, salons = _bot_multi([LOGS, LOGS2])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=LOGS, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    salons[LOGS].send.assert_not_awaited()
    salons[LOGS2].send.assert_not_awaited()


async def test_purge_d_un_salon_de_logs_non_republiee():
    bot, salons = _bot_multi([LOGS, LOGS2])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=LOGS2, message_ids={1, 2}, cached_messages=[])
    await jm.messages_supprimes_en_masse(bot, payload)
    salons[LOGS].send.assert_not_awaited()
    salons[LOGS2].send.assert_not_awaited()


async def test_edition_dans_un_salon_de_logs_non_republiee():
    bot, salons = _bot_multi([LOGS, LOGS2])
    await jm.message_modifie(bot, _message("a", channel_id=LOGS), _message("b", channel_id=LOGS))
    salons[LOGS].send.assert_not_awaited()
    salons[LOGS2].send.assert_not_awaited()


# ---------------------------------------------------------------------------
# Revue finale — le salon d'origine est lisible depuis un autre serveur


async def test_nom_du_salon_a_cote_de_la_mention_suppression_et_masse():
    bot, logs = _bot()
    await jm.message_supprime(bot, SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1,
                                                   cached_message=None))
    await jm.messages_supprimes_en_masse(bot, SimpleNamespace(guild_id=COMMU, channel_id=5,
                                                              message_ids={1}, cached_messages=[]))
    assert "<#5> (#discussions)" in "\n".join(_textes(_vue(logs, 0)))
    assert "<#5> (#discussions)" in "\n".join(_textes(_vue(logs, 1)))


async def test_nom_du_salon_a_cote_de_la_mention_edition_echappe():
    bot, logs = _bot()
    avant, apres = _message("a"), _message("b")
    apres.channel = SimpleNamespace(id=5, name="le_salon")
    await jm.message_modifie(bot, avant, apres)
    assert "<#5> (#le\\_salon)" in "\n".join(_textes(_vue(logs)))


async def test_salon_inconnu_mention_suivie_de_l_id():
    bot, logs = _bot()
    await jm.message_supprime(bot, SimpleNamespace(guild_id=COMMU, channel_id=404, message_id=1,
                                                   cached_message=None))
    assert "<#404> (404)" in "\n".join(_textes(_vue(logs)))


# ---------------------------------------------------------------------------
# Revue finale — NSFW jamais republié, spoiler republié sous spoiler


async def test_pieces_d_un_salon_nsfw_listees_jamais_republiees():
    bot, logs = _bot()
    piece = _piece(1, "photo.png")
    msg = _message("texte", pieces=[piece])
    msg.channel = SimpleNamespace(id=6, name="nsfw", is_nsfw=lambda: True)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=6, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    piece.to_file.assert_not_awaited()
    kwargs = logs.send.await_args.kwargs
    assert kwargs["files"] == []
    assert _medias(kwargs["view"]) == []
    texte = "\n".join(_textes(kwargs["view"]))
    assert "photo.png (salon NSFW)" in texte


async def test_pieces_retirees_d_une_edition_en_salon_nsfw_non_republiees():
    bot, logs = _bot()
    photo = _piece(1, "photo.png")
    avant, apres = _message("lien", pieces=[photo]), _message("lien", pieces=[])
    apres.channel = SimpleNamespace(id=6, name="nsfw", is_nsfw=lambda: True)
    await jm.message_modifie(bot, avant, apres)
    photo.to_file.assert_not_awaited()
    assert "salon NSFW" in "\n".join(_textes(_vue(logs)))


async def test_piece_sous_spoiler_republiee_sous_spoiler():
    bot, logs = _bot()
    image = _piece(1, "SPOILER_photo.png")
    msg = _message("texte", pieces=[image])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    assert image.to_file.await_args.kwargs["spoiler"] is True
    kwargs = logs.send.await_args.kwargs
    fichier = kwargs["files"][0]
    assert fichier.spoiler is True
    galerie = next(c for c in kwargs["view"].walk_children() if isinstance(c, discord.ui.MediaGallery))
    assert galerie.items[0].spoiler is True
    assert galerie.items[0].media.url == f"attachment://{fichier.filename}"


async def test_fichier_sous_spoiler_composant_file_marque():
    bot, logs = _bot()
    video = _piece(1, "clip.mp4", content_type="video/mp4")
    video.is_spoiler = lambda: True      # drapeau Discord, sans préfixe dans le nom
    msg = _message("texte", pieces=[video])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    await jm.message_supprime(bot, payload)

    kwargs = logs.send.await_args.kwargs
    composant = next(c for c in kwargs["view"].walk_children() if isinstance(c, discord.ui.File))
    assert composant.spoiler is True
    assert composant.url == f"attachment://{kwargs['files'][0].filename}"
    assert kwargs["files"][0].spoiler is True


# ---------------------------------------------------------------------------
# Revue finale — fichiers refusés : fiche renvoyée en texte seul


async def test_fichiers_refuses_fiche_renvoyee_sans_pieces():
    bot, logs = _bot()
    refus = discord.Forbidden(SimpleNamespace(status=403, reason="x"), "Missing Permissions")
    logs.send.side_effect = [refus, None]
    piece = _piece(1, "photo.png")
    msg = _message("texte", pieces=[piece])
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)

    dits: list[str] = []
    jeton = jm.logger.add(lambda m: dits.append(str(m)), level="WARNING")
    try:
        await jm.message_supprime(bot, payload)
    finally:
        jm.logger.remove(jeton)

    assert logs.send.await_count == 2
    reprise = logs.send.await_args_list[1].kwargs
    assert "files" not in reprise or not reprise["files"]
    assert _medias(reprise["view"]) == []
    assert "photo.png (envoi des fichiers refusé)" in "\n".join(_textes(reprise["view"]))
    assert any("Joindre des fichiers" in d for d in dits)


# ---------------------------------------------------------------------------
# Suivi — un fil ouvert sous un salon de logs compte pour ce salon


async def test_suppression_dans_un_fil_d_un_salon_de_logs_non_republiee():
    bot, salons = _bot_multi([LOGS, LOGS2])
    fil = SimpleNamespace(id=800, name="discussion-fiche", parent_id=LOGS)
    obtenir = bot.get_channel
    bot.get_channel = lambda cid: fil if cid == 800 else obtenir(cid)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=800, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    salons[LOGS].send.assert_not_awaited()
    salons[LOGS2].send.assert_not_awaited()


async def test_edition_dans_un_fil_d_un_salon_de_logs_non_republiee():
    bot, salons = _bot_multi([LOGS, LOGS2])
    avant, apres = _message("a", channel_id=800), _message("b", channel_id=800)
    apres.channel = SimpleNamespace(id=800, name="discussion-fiche", parent_id=LOGS2)
    await jm.message_modifie(bot, avant, apres)
    salons[LOGS].send.assert_not_awaited()
    salons[LOGS2].send.assert_not_awaited()


async def test_fil_d_un_salon_ordinaire_toujours_journalise():
    bot, salons = _bot_multi([LOGS])
    avant, apres = _message("a", channel_id=800), _message("b", channel_id=800)
    apres.channel = SimpleNamespace(id=800, name="fil", parent_id=5)
    await jm.message_modifie(bot, avant, apres)
    salons[LOGS].send.assert_awaited_once()


# ---------------------------------------------------------------------------
# T1 #5 — horodatage Discord natif


def test_horodatage_absolu_et_relatif():
    from datetime import datetime, timezone
    dt = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    epoch = int(dt.timestamp())
    assert jm.horodatage(dt) == f"<t:{epoch}:f> (<t:{epoch}:R>)"


def test_horodatage_exige_un_datetime_conscient_du_fuseau():
    from datetime import datetime
    naif = datetime(2026, 9, 15, 12, 0, 0)
    try:
        jm.horodatage(naif)
    except ValueError:
        pass
    else:
        raise AssertionError("horodatage() aurait dû lever sur un datetime naïf")


async def test_horodatage_present_dans_toutes_les_cartes():
    """§2 de la spec : la fabrique d'horodatage sert TOUTES les cartes du
    tronc commun — suppression, édition, masse, vocal créé/supprimé."""
    bot, logs = _bot()
    msg = _message("texte")
    payload_suppr = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload_suppr)
    await jm.message_modifie(bot, _message("a"), _message("b"))
    payload_masse = SimpleNamespace(guild_id=COMMU, channel_id=5, message_ids={1}, cached_messages=[])
    await jm.messages_supprimes_en_masse(bot, payload_masse)
    salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
    await jm.vocal_cree(bot, SimpleNamespace(id=42, name="alice"), salon)
    await jm.vocal_supprime(bot, salon)

    assert logs.send.await_count == 5
    for appel in range(5):
        texte = "\n".join(_textes(_vue(logs, appel)))
        assert re.search(r"<t:\d+:f> \(<t:\d+:R>\)", texte), f"appel {appel} sans horodatage natif"


# ---------------------------------------------------------------------------
# T1 #7 — id de l'utilisateur en pied, copiable


async def test_pied_id_utilisateur_suppression():
    bot, logs = _bot()
    msg = _message("texte", auteur_id=123456789012345678)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    assert "-# ID `123456789012345678`" in texte


async def test_pied_id_utilisateur_absent_hors_cache():
    """Sans auteur connu (hors cache), pas d'id à mettre en pied."""
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    assert "ID `" not in texte


async def test_pied_id_utilisateur_edition():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("a", auteur_id=42), _message("b", auteur_id=42))
    texte = "\n".join(_textes(_vue(logs)))
    assert "-# ID `42`" in texte


async def test_pied_id_utilisateur_vocal_cree():
    bot, logs = _bot()
    salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
    await jm.vocal_cree(bot, SimpleNamespace(id=42, name="alice"), salon)
    texte = "\n".join(_textes(_vue(logs)))
    assert "-# ID `42`" in texte


def test_pied_utilisateur_format_copiable():
    utilisateur = SimpleNamespace(id=987654321)
    assert jm.pied_utilisateur(utilisateur) == "ID `987654321`"


# ---------------------------------------------------------------------------
# T1 #6 — diff d'édition : seuls les passages changés mis en évidence


async def test_edition_reecriture_totale_retombe_sur_avant_apres():
    """Plus de la moitié du texte change : le diff serait illisible, on
    retombe sur les blocs Avant/Après complets."""
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("un deux trois"), _message("quatre cinq six"))
    texte = "\n".join(_textes(_vue(logs)))
    assert "**Avant**" in texte
    assert "**Après**" in texte
    assert "> un deux trois" in texte
    assert "> quatre cinq six" in texte
    assert "**Modification**" not in texte


async def test_edition_diff_echappe_le_markdown_avant_les_marqueurs():
    """Un `*` posé par l'utilisateur ne doit pas se combiner avec nos propres
    marqueurs `~~`/`**` — le contenu source est markdown-échappé D'ABORD, et
    un espace de largeur nulle (round 1 #2) sépare le marqueur du délimiteur
    échappé qui le touche."""
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("salut *ami*"), _message("salut *pote*"))
    texte = "\n".join(_textes(_vue(logs)))
    zwsp = "\u200b"
    assert f"~~\\*ami\\*{zwsp}~~" in texte
    assert f"**\\*pote\\*{zwsp}**" in texte


def test_diff_mots_reste_inchange_hors_diff():
    assert jm._diff_mots("bonjour le monde", "bonjour le monde") == "bonjour le monde"


# ---------------------------------------------------------------------------
# Fix round 1 — #2 : délimiteur Markdown échappé au bord d'un mot marqué


def test_diff_mots_jamais_de_run_de_trois_etoiles_ou_tildes():
    """Un délimiteur Markdown échappé (`\\*`, `\\~`) sur le bord d'un mot
    marqué colle à notre propre marqueur et forme un run de 3+ caractères
    identiques que Discord peut relire comme un AUTRE marqueur — un espace
    de largeur nulle doit l'empêcher, des deux côtés selon le besoin, sans
    rien changer pour un mot ordinaire."""
    # Reproduction exacte round 1 : ajouter le token `**` (échappé en `\*\*`)
    # donnait `texte**\*\***`.
    ajout = jm._diff_mots("texte", "texte \\*\\*")
    assert not re.search(r"\*{3,}", ajout)
    # Reproduction exacte round 1 : un `~~` échappé (`\~\~`) qui change de mot
    # donnait `~~\~\~~~`.
    changement = jm._diff_mots("bonjour \\~\\~ monde", "bonjour change monde")
    assert not re.search(r"~{3,}", changement)
    # Un mot ordinaire, sans délimiteur sur son bord, n'est pas touché.
    assert jm._diff_mots("bonjour ancien monde", "bonjour nouveau monde") == \
        "bonjour ~~ancien~~ **nouveau** monde"


# ---------------------------------------------------------------------------
# Fix round 2 — #A : la JONCTURE entre deux fragments, pas seulement le bord
# interne d'un mot marqué (`_marque` de round 1 ne suffisait pas)


def test_diff_mots_repro_round2_equal_se_termine_par_delimiteur_echappe():
    """Repro EXACTE round 2 #A : un chunk `equal` qui finit par un
    délimiteur échappé (`\\*`), suivi d'un mot AJOUTÉ qui n'existe que côté
    `apres` — le tokenizer perd l'espace séparateur (rien à quoi l'aligner
    côté `avant`) juste après un chunk `equal` : sans séparation, ça donnait
    `'salut \\***nouveau**'` (run de 3 étoiles)."""
    avant = jm._echapper(discord.utils.escape_markdown("salut *"))
    apres = jm._echapper(discord.utils.escape_markdown("salut * nouveau"))
    resultat = jm._diff_mots(avant, apres)
    assert resultat is not None
    assert not re.search(r"\*{3,}", resultat)


def test_diff_mots_repro_round2_suppression_en_fin_de_message_tilde():
    """Même défaut avec des tildes, suppression en fin de message (§A)."""
    avant = jm._echapper(discord.utils.escape_markdown("salut ~~ mot"))
    apres = jm._echapper(discord.utils.escape_markdown("salut ~~"))
    resultat = jm._diff_mots(avant, apres)
    assert resultat is not None
    assert not re.search(r"~{3,}", resultat)


_ADVERSAIRES_DIFF_JONCTURE = [
    ("salut *", "salut * nouveau"),                          # insertion en FIN, avant finit par *
    ("bonjour ~~ monde", "bonjour change monde"),             # changement au MILIEU, mot = ~~
    ("* debut", "nouveau debut"),                             # changement au DÉBUT, avant commence par *
    ("mot_", "mot_ nouveau"),                                 # insertion en FIN, avant finit par _
    ("texte |", "texte | ajout"),                             # insertion en FIN, avant finit par |
    ("fin `", "fin ` ajout"),                                 # insertion en FIN, avant finit par `
    ("bonjour ~ monde ancien", "bonjour ~ monde nouveau"),    # changement en FIN
    ("* mot milieu fin", "changé mot milieu fin"),            # changement au DÉBUT
    ("debut milieu~ fin", "debut change fin"),                # changement au MILIEU, mot finit par ~
    ("a b c *", "a b c"),                                     # suppression pure en FIN, avant finit par *
]


def test_diff_mots_proprietes_adversariales_jamais_de_run_ni_de_marqueur_colle():
    """Propriété round 2 #A : sur un lot de paires adversariales (texte qui
    commence/finit par un délimiteur, changement au début/milieu/fin), le
    diff ne produit JAMAIS de run de 3+ `*`/`~`, ni un marqueur `**`/`~~`
    collé (sans ZWSP) à un délimiteur échappé venu d'un AUTRE fragment."""
    for avant_brut, apres_brut in _ADVERSAIRES_DIFF_JONCTURE:
        avant = jm._echapper(discord.utils.escape_markdown(avant_brut))
        apres = jm._echapper(discord.utils.escape_markdown(apres_brut))
        resultat = jm._diff_mots(avant, apres)
        assert resultat is not None, (avant_brut, apres_brut)
        assert not re.search(r"[*~]{3,}", resultat), (avant_brut, apres_brut, resultat)


# ---------------------------------------------------------------------------
# Fix round 3 — l'espace d'ORIGINE reste hors des marqueurs, jamais perdu


def test_diff_mots_insertion_au_debut_espace_hors_marqueur():
    """`.strip()` mangeait l'espace qui séparait le mot ajouté du voisin —
    `'nouveau mot'` devenait `'**nouveau**mot'` (collé), pas
    `'**nouveau** mot'`."""
    assert jm._diff_mots("mot", "nouveau mot") == "**nouveau** mot"


def test_diff_mots_insertion_a_la_fin_espace_hors_marqueur():
    assert jm._diff_mots("mot", "mot nouveau") == "mot **nouveau**"


def test_diff_mots_suppression_au_debut_espace_hors_marqueur():
    assert jm._diff_mots("ancien mot", "mot") == "~~ancien~~ mot"


def test_diff_mots_suppression_a_la_fin_espace_hors_marqueur():
    assert jm._diff_mots("mot ancien", "mot") == "mot ~~ancien~~"


def test_diff_mots_changement_au_milieu_espace_hors_marqueur():
    """Un remplacement simple, au milieu, n'a pas d'espace d'origine à
    récupérer des deux côtés : l'espace explicite entre les deux marqueurs
    reste la règle (déjà couvert ailleurs, réaffirmé ici pour le lot des 5
    scénarios round 3)."""
    assert jm._diff_mots("bonjour ancien monde", "bonjour nouveau monde") == \
        "bonjour ~~ancien~~ **nouveau** monde"


def test_diff_mots_espace_jamais_a_linterieur_dun_marqueur():
    """Un espace À L'INTÉRIEUR d'un marqueur (`** nouveau**`, `~~ancien ~~`)
    ne se rend pas en gras/barré sur Discord — sur les 5 scénarios round 3,
    le contenu capturé par chaque paire `**...**`/`~~...~~` ne commence ni
    ne finit par un espace."""
    cas = [
        ("mot", "nouveau mot"),
        ("mot", "mot nouveau"),
        ("ancien mot", "mot"),
        ("mot ancien", "mot"),
        ("bonjour ancien monde", "bonjour nouveau monde"),
    ]
    for avant, apres in cas:
        resultat = jm._diff_mots(avant, apres)
        assert resultat is not None, (avant, apres)
        marques = re.findall(r"\*\*(.+?)\*\*", resultat) + re.findall(r"~~(.+?)~~", resultat)
        assert marques, (avant, apres, resultat)
        for contenu in marques:
            assert contenu == contenu.strip(), (avant, apres, resultat)


# ---------------------------------------------------------------------------
# Fix round 4 — un changement d'espaces seuls ne colle plus deux mots


def _echappe(texte: str) -> str:
    """Le même échappement que `message_modifie` avant d'appeler le diff."""
    return jm._echapper(discord.utils.escape_markdown(texte))


def test_diff_mots_repro_round4_double_espace_reduit():
    assert jm._diff_mots(_echappe("hello  world"), _echappe("hello world")) == "hello world"


def test_diff_mots_repro_round4_triple_espace_reduit():
    assert jm._diff_mots(_echappe("mot1   mot2"), _echappe("mot1 mot2")) == "mot1 mot2"


def test_diff_mots_repro_round4_tabulation_devenue_espaces():
    assert jm._diff_mots(_echappe("mot1\tmot2"), _echappe("mot1  mot2")) == "mot1  mot2"


def test_diff_mots_repro_round4_saut_de_ligne_retire():
    assert jm._diff_mots(_echappe("un\n\ndeux"), _echappe("un\ndeux")) == "un\ndeux"


_ZWSP = "\u200b"

# Paires brutes, échappées comme par l'appelant. Espaces multiples, tabulations,
# sauts de ligne, bords du message, délimiteurs Markdown en bordure, mots
# répétés, côtés vides — et quelques paires qui prennent le repli (None).
_PAIRES_PROPRIETE_DIFF = [
    ("hello  world", "hello world"),
    ("mot1   mot2", "mot1 mot2"),
    ("mot1\tmot2", "mot1  mot2"),
    ("un\n\ndeux", "un\ndeux"),
    ("a b c", "a  b\tc"),
    ("a b c d", "a\nb\nc\nd"),
    ("  début milieu fin", "début milieu fin"),
    ("début milieu fin", "début milieu fin  "),
    ("\tun deux trois\n", "un deux trois quatre"),
    ("un deux trois", "  un deux trois quatre\n"),
    (" lead mid tail ", "\nlead  mid\ttail\n"),
    ("un deux trois quatre", "un trois quatre"),
    ("un deux trois quatre", "un deux\n\ntrois quatre cinq"),
    ("un  deux  trois quatre", "un deux trois  cinq  quatre"),
    ("un ancien\ndeux", "un nouveau\n deux"),
    ("ancien mot suite", "nouveau mot suite"),
    ("mot suite ancien", "mot suite nouveau"),
    ("a old b", "a  b"),
    ("*gras* et suite", "*gras* et la suite"),
    ("début ~~barré~~ fin", "début fin"),
    ("_a_ b c", "b c _a_"),
    ("* x y", "x y *"),
    ("mot ~", "~ mot"),
    ("a | b", "a | b |"),
    ("`code` ici", "`code` ici là"),
    ("salut *", "salut * nouveau"),
    ("salut ~~ mot", "salut ~~"),
    ("salut @tout le monde", "salut @tout  le monde !"),
    ("x x x x", "x x y x x"),
    ("le le le chat", "le le chat"),
    ("rep rep rep", "rep rep"),
    ("un\n", "un\n\ndeux trois"),
    ("**\n|\tb\n\nb", "\n~~| \nb\n\nb"),  # deux suppressions dès le début, un saut de ligne inchangé entre
    ("un deux", "un nouveau\nbloc deux"),               # insertion sur deux lignes
    ("un vieux\nbloc deux", "un deux"),                 # suppression sur deux lignes
    ("un a\n\nb deux", "un c\n\nd deux"),             # remplacement qui enjambe une ligne vide
    ("x a \n b y", "x y"),                               # espaces autour du saut, dans l'îlot
    ("x y", "x a\r\nb y"),                              # CRLF
    ("x \\ y", "x y"),                                   # backslash supprimé : `\\~~` reste un vrai marqueur
    ("x a\u2028b y z", "x y z"),                          # séparateur de ligne Unicode
    ("", ""),
    ("   ", "  "),
    ("", "mot"),                   # repli attendu : aucun mot commun
    ("mot", ""),                   # repli attendu
]


# Ce que `str.splitlines()` (donc la citation `> `) coupe comme fin de ligne.
_SAUT = r"[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]"
_ILOT = re.compile(r"~~.+?~~(?:(?=\s*" + _SAUT + r")\s+~~.+?~~)*")


def _retirer_suppressions(diff: str) -> str:
    """Retire chaque îlot `~~…~~` AVEC l'unique espace qui lui appartient.

    Un mot supprimé n'a aucune place dans le texte APRÈS : pour rester lisible,
    il apporte son propre séparateur — l'espace qui le précède, ou celui qui le
    suit quand il ouvre le message. Tout autre caractère vient de l'APRÈS.
    Une suppression sur plusieurs lignes est UN îlot de plusieurs segments
    `~~…~~`, séparés par des espaces qui contiennent un saut de ligne ; deux
    îlots distincts ne sont jamais séparés que par un espace simple.
    """
    morceaux, curseur = [], 0
    for m in _ILOT.finditer(diff):
        debut, fin = m.span()
        if debut == 0:
            if diff[fin:fin + 1] == " ":
                fin += 1
        else:
            assert diff[debut - 1] == " ", diff
            debut -= 1
        assert debut >= curseur, diff
        morceaux.append(diff[curseur:debut])
        curseur = fin
    morceaux.append(diff[curseur:])
    return "".join(morceaux)


def _marqueurs_equilibres_par_ligne(texte: str) -> bool:
    """Chaque ligne porte un nombre PAIR de `**` et de `~~` actifs, et aucun
    `*`/`~` isolé. Les séquences échappées sont consommées d'abord : `\\~~`
    est un backslash échappé suivi d'un VRAI `~~`.
    """
    for ligne in texte.splitlines():
        jetons = [j for j in re.findall(r"\\.|\*\*|~~|[*~]", ligne) if j[0] != "\\"]
        if any(len(j) == 1 for j in jetons):
            return False
        if jetons.count("**") % 2 or jetons.count("~~") % 2:
            return False
    return True


def _sans_marqueurs(texte: str) -> str:
    texte = re.sub(r"\*\*(.+?)\*\*", r"\1", texte, flags=re.S)
    texte = re.sub(r"~~(.+?)~~", r"\1", texte, flags=re.S)
    return texte.replace(_ZWSP, "")


def test_diff_mots_propriete_aller_retour_espaces_jamais_perdus():
    """Sur chaque paire (repli exclu) :

    1. aucun run `[*~]{3,}` ;
    2. aucun contenu de marqueur qui commence ou finit par un espace ;
    3. suppressions retirées (îlot entier + son séparateur), marqueurs et ZWSP
       ôtés : on retrouve l'APRÈS EXACTEMENT, espaces compris ;
    4. ajouts retirés, marqueurs et ZWSP ôtés : on retrouve les MOTS de
       l'AVANT, dans l'ordre et jamais collés. Pas l'égalité exacte : les
       espaces visibles sont ceux de l'APRÈS (un changement d'espaces seuls
       n'a aucun marqueur, et le séparateur d'un ajout reste hors du gras),
       donc l'espacement de l'AVANT n'est pas reconstructible ;
    5. aucun marqueur n'enjambe une fin de ligne — ni dans le diff, ni une
       fois cité ligne par ligne (`> `) : Discord ne porte pas le gras ni le
       barré d'une ligne à l'autre, le marqueur s'afficherait en clair.

    Le ZWSP est ôté des DEUX côtés : `_echapper` en pose un après chaque `@`.
    """
    diffs = 0
    for avant_brut, apres_brut in _PAIRES_PROPRIETE_DIFF:
        avant, apres = _echappe(avant_brut), _echappe(apres_brut)
        resultat = jm._diff_mots(avant, apres)
        cas = (avant_brut, apres_brut, resultat)
        if resultat is None:
            continue
        diffs += 1
        assert not re.search(r"[*~]{3,}", resultat), cas
        contenus = (re.findall(r"\*\*(.+?)\*\*", resultat, flags=re.S)
                    + re.findall(r"~~(.+?)~~", resultat, flags=re.S))
        for contenu in contenus:
            nu = contenu.replace(_ZWSP, "")
            assert nu == nu.strip(), cas
            assert contenu.splitlines() == [contenu], cas
        assert _marqueurs_equilibres_par_ligne(resultat), cas
        assert _marqueurs_equilibres_par_ligne(jm._citer_deja_echappe(resultat)), cas
        assert _sans_marqueurs(_retirer_suppressions(resultat)) == apres.replace(_ZWSP, ""), cas
        sans_ajouts = re.sub(r"\*\*(.+?)\*\*", "", resultat, flags=re.S)
        assert _sans_marqueurs(sans_ajouts).split() == avant.replace(_ZWSP, "").split(), cas
    assert diffs >= 36


def test_diff_mots_insertion_sur_deux_lignes_marquee_ligne_par_ligne():
    assert jm._diff_mots("un deux", "un nouveau\nbloc deux") == "un **nouveau**\n**bloc** deux"


def test_diff_mots_suppression_sur_deux_lignes_marquee_ligne_par_ligne():
    assert jm._diff_mots("un vieux\nbloc deux", "un deux") == "un ~~vieux~~\n~~bloc~~ deux"


def test_diff_mots_remplacement_qui_enjambe_une_ligne_vide():
    """La ligne vide ne porte aucun marqueur, les espaces autour du saut
    restent dehors."""
    assert jm._diff_mots("un a \n\n b deux", "un c\n\nd deux") == \
        "un ~~a~~ \n\n ~~b~~ **c**\n\n**d** deux"


def test_citation_du_diff_tronque_ne_laisse_aucun_marqueur_ouvert():
    """Le budget coupe au caractère près : une coupure DANS un `**…**` ou un
    `~~…~~` laissait sur la dernière ligne un marqueur ouvert, affiché en
    clair. Toutes les positions de coupure sont essayées."""
    diff = jm._diff_mots("motoriginal000 motoriginal001 motoriginal002 ancien",
                         "motoriginal000 motoriginal001 motoriginal002 nouveau")
    assert diff is not None
    for limite in range(10, len(diff) + 3):
        cite = jm._citer_deja_echappe(diff, limite=limite)
        assert len(cite) <= limite, (limite, cite)
        assert _marqueurs_equilibres_par_ligne(cite), (limite, cite)


# ---------------------------------------------------------------------------
# Fix round 1 — #3 : pire cas budget sur le chemin DIFF (pas le repli)


async def test_budget_4000_pire_cas_diff_edition_alternee():
    """400 mots, la moitié changée un mot sur deux (ratio pile à 0.5, donc le
    chemin DIFF — pas le repli Avant/Après testé par les autres pire cas) :
    les marqueurs `~~`/`**` gonflent largement le texte au-delà du budget
    d'un bloc — la troncature doit quand même tenir le total sous 4000."""
    bot, logs = _bot()
    mots_avant = [f"motoriginal{i:03d}" for i in range(400)]
    mots_apres = [f"motoriginal{i:03d}" if i % 2 == 0 else f"motchange{i:03d}" for i in range(400)]
    avant, apres = " ".join(mots_avant), " ".join(mots_apres)
    await jm.message_modifie(bot, _message(avant), _message(apres))
    blocs = _textes(_vue(logs))
    total = sum(len(t) for t in blocs)
    assert total <= 4000
    bloc_diff = next(b for b in blocs if b.startswith("**Modification**"))
    assert bloc_diff.endswith("…")


# ---------------------------------------------------------------------------
# Fix round 1 — #4 : le repli Avant/Après échappe le markdown, comme le diff


async def test_edition_avant_apres_echappe_le_markdown():
    """Réécriture de plus de la moitié du texte (repli Avant/Après) : un
    `**gras**` brut posé par l'auteur doit ressortir échappé, exactement
    comme sur le chemin diff — jamais rendu tel quel (gras Discord), et
    jamais échappé DEUX fois (pas de double zero-width space après un `@`)."""
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("un deux trois **gras**"),
                             _message("quatre cinq six **gras**"))
    texte = "\n".join(_textes(_vue(logs)))
    assert "**Avant**" in texte and "**Après**" in texte   # bien le repli, pas le diff
    assert "\\*\\*gras\\*\\*" in texte
    assert "**gras**" not in texte


# ---------------------------------------------------------------------------
# T1 #4 — messages de bots exclus par défaut


async def test_suppression_message_de_bot_ignoree_par_defaut():
    bot, logs = _bot()
    msg = _message("texte", bot_auteur=True)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload)
    logs.send.assert_not_awaited()


async def test_suppression_message_de_bot_journalisee_si_inclure_bots():
    bot, logs = _bot(inclure_bots=True)
    msg = _message("texte", bot_auteur=True)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload)
    logs.send.assert_awaited_once()


async def test_edition_message_de_bot_journalisee_si_inclure_bots():
    bot, logs = _bot(inclure_bots=True)
    await jm.message_modifie(bot, _message("a", bot_auteur=True), _message("b", bot_auteur=True))
    logs.send.assert_awaited_once()


async def test_suppression_en_masse_lignes_de_bots_retirees_mais_total_intact():
    bot, logs = _bot()
    humain = _message("bonjour", auteur_id=1, msg_id=1, auteur_nom="alice", bot_auteur=False)
    bot_msg = _message("je suis un bot", auteur_id=2, msg_id=2, auteur_nom="wally", bot_auteur=True)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_ids={1, 2},
                              cached_messages=[humain, bot_msg])
    await jm.messages_supprimes_en_masse(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    assert "**Messages** 2" in texte    # le TOTAL compte le bot
    assert "alice" in texte
    assert "wally" not in texte         # sa ligne est retirée du détail


async def test_suppression_en_masse_lignes_de_bots_incluses_si_inclure_bots():
    bot, logs = _bot(inclure_bots=True)
    bot_msg = _message("je suis un bot", auteur_id=2, msg_id=2, auteur_nom="wally", bot_auteur=True)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_ids={2}, cached_messages=[bot_msg])
    await jm.messages_supprimes_en_masse(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    assert "wally" in texte


# ---------------------------------------------------------------------------
# Fix round 2 — #B : suppression/masse échappent le markdown du contenu,
# comme le fait déjà le chemin diff d'édition


_CONTENU_DANGEREUX = "```non fermé\n||secret|| # titre"


async def test_suppression_contenu_dangereux_echappe():
    """Une fence non fermée DÉFORME le reste de la fiche, un `||spoiler||`
    MASQUE le contenu au modérateur — les deux doivent ressortir échappés,
    comme le contenu Avant/Après d'une édition."""
    bot, logs = _bot()
    msg = _message(_CONTENU_DANGEREUX)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    attendu = discord.utils.escape_markdown(_CONTENU_DANGEREUX)
    for ligne in attendu.splitlines():
        assert ligne in texte
    assert "```non fermé" not in texte     # jamais la fence BRUTE
    assert "||secret||" not in texte       # jamais le spoiler BRUT


async def test_suppression_en_masse_contenu_dangereux_echappe():
    bot, logs = _bot()
    msg = _message(_CONTENU_DANGEREUX, auteur_id=1, msg_id=1)
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_ids={1}, cached_messages=[msg])
    await jm.messages_supprimes_en_masse(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    attendu = discord.utils.escape_markdown(_CONTENU_DANGEREUX)
    for ligne in attendu.splitlines():
        assert ligne in texte
    assert "```non fermé" not in texte
    assert "||secret||" not in texte


async def test_suppression_contenu_echappe_une_seule_fois():
    """`_citer` échappe déjà `@` — l'appelant qui échappe le markdown AVANT
    ne doit pas faire doubler le zero-width space posé après un `@`."""
    bot, logs = _bot()
    msg = _message("bonjour @tout le monde")
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=msg)
    await jm.message_supprime(bot, payload)
    texte = "\n".join(_textes(_vue(logs)))
    assert "@\u200btout" in texte
    assert "@\u200b\u200btout" not in texte
