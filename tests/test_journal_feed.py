"""Ce que le journal LIT de Discord, et ce qu'il y publie.

Deux closures de plus du `main()` de mille lignes, sorties le 2026-08-23. Elles
portent trois choses qu'aucun test ne regardait, et dont deux ont déjà coûté
quelque chose ailleurs dans ce projet :

  · la journée commence à minuit HEURE DE PARIS. L'hôte (CT100) est en UTC :
    lire `datetime.now()` naïvement décalerait la journée de deux heures et
    couperait la soirée en deux — le moment où il se passe quelque chose ;
  · un salon illisible ne doit pas coûter la lecture des autres ;
  · un salon de publication introuvable doit se DIRE. Muet, le journal du soir
    disparaissait sans que personne s'en aperçoive.
"""
import io
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from bot.discord.journal_feed import JournalDiscord

PARIS = ZoneInfo("Europe/Paris")


def _msg(auteur: str, contenu: str, quand: datetime):
    m = MagicMock()
    m.author = auteur
    m.content = contenu
    m.created_at = quand
    return m


def _salon(ident: int, messages: list, *, casse=False):
    s = MagicMock()
    s.id = ident

    async def _hist(after=None, limit=None):
        if casse:
            raise PermissionError("pas le droit de lire")
        for m in messages:
            if after is None or m.created_at >= after:
                yield m

    s.history = _hist
    return s


def _feed(salons, *, autorises=None, journal_channel_id=77):
    guild = MagicMock()
    guild.text_channels = salons
    bot = MagicMock()
    bot.guilds = [guild]
    config = MagicMock()
    config.bot.journal_channel_id = journal_channel_id

    feed = JournalDiscord(discord_bot=bot, config=config)
    return feed, bot, config


@pytest.fixture(autouse=True)
def _libelle_et_filtre(monkeypatch):
    """`_author_label` et `_is_channel_allowed` sont importés DANS la méthode :
    on remplace leur définition, pas un chemin d'import."""
    import bot.discord.handlers as h
    monkeypatch.setattr(h, "_author_label", lambda a: str(a))
    monkeypatch.setattr(h, "_is_channel_allowed", lambda cfg, cid: cid != 999)


# ── la lecture ──────────────────────────────────────────────────────────────

async def test_les_messages_du_jour_reviennent_tries_dans_l_ordre():
    maintenant = datetime.now(PARIS)
    s = _salon(1, [_msg("Bob", "deux", maintenant),
                   _msg("Alice", "un", maintenant - timedelta(hours=1))])
    feed, _, _ = _feed([s])
    out = await feed.lire_la_journee()
    assert [m["content"] for m in out] == ["un", "deux"]
    assert out[0]["author"] == "Alice"


async def test_la_journee_commence_a_minuit_HEURE_DE_PARIS():
    """L'hôte est en UTC. En été il y a deux heures d'écart : un message posté
    à 01 h 00 à Paris est encore « hier » en UTC, et disparaîtrait du journal.
    Le test le vérifie sur la borne réellement passée à `history()`."""
    vue = {}
    s = MagicMock()
    s.id = 1

    async def _hist(after=None, limit=None):
        vue["after"] = after
        return
        yield        # noqa: unreachable — fait de `_hist` un générateur

    s.history = _hist
    feed, _, _ = _feed([s])
    await feed.lire_la_journee()

    attendu = datetime.now(PARIS).replace(hour=0, minute=0, second=0, microsecond=0)
    assert vue["after"] == attendu
    assert vue["after"].tzinfo is not None       # jamais un datetime naïf


async def test_un_salon_NON_AUTORISE_n_est_pas_lu():
    interdit = _salon(999, [_msg("X", "privé", datetime.now(PARIS))])
    ok = _salon(1, [_msg("Y", "public", datetime.now(PARIS))])
    feed, _, _ = _feed([interdit, ok])
    assert [m["content"] for m in await feed.lire_la_journee()] == ["public"]


async def test_un_salon_ILLISIBLE_ne_coute_pas_les_autres():
    """Permissions retirées, salon supprimé : un seul salon fâché ferait perdre
    la journée entière si l'exception remontait."""
    casse = _salon(1, [], casse=True)
    bon = _salon(2, [_msg("Y", "sauvé", datetime.now(PARIS))])
    feed, _, _ = _feed([casse, bon])
    assert [m["content"] for m in await feed.lire_la_journee()] == ["sauvé"]


async def test_les_messages_VIDES_sont_ecartes():
    """Une image seule, un sticker : rien à raconter dans le journal."""
    s = _salon(1, [_msg("A", "   ", datetime.now(PARIS)),
                   _msg("B", "du texte", datetime.now(PARIS))])
    feed, _, _ = _feed([s])
    assert len(await feed.lire_la_journee()) == 1


async def test_sans_serveur_connu_on_le_DIT_et_on_rend_une_liste_vide():
    """Discord pas encore prêt : rendre `[]` en silence ferait croire à une
    journée sans un mot, et le journal du soir raconterait le vide."""
    feed, bot, _ = _feed([])
    bot.guilds = []
    assert await feed.lire_la_journee() == []


# ── la publication ──────────────────────────────────────────────────────────

async def test_le_texte_seul_part_dans_le_salon_du_journal():
    feed, bot, _ = _feed([])
    salon = MagicMock(); salon.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=salon)
    await feed.publier("le journal du soir")
    salon.send.assert_awaited_once_with("le journal du soir")


async def test_le_graphe_part_AVEC_son_texte():
    feed, bot, _ = _feed([])
    salon = MagicMock(); salon.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=salon)
    await feed.publier("le journal", file=io.BytesIO(b"PNG"))
    assert salon.send.await_args.args == ("le journal",)
    assert "file" in salon.send.await_args.kwargs


async def test_un_graphe_SANS_texte_part_quand_meme():
    feed, bot, _ = _feed([])
    salon = MagicMock(); salon.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=salon)
    await feed.publier("", file=io.BytesIO(b"PNG"))
    assert not salon.send.await_args.args
    assert "file" in salon.send.await_args.kwargs


async def test_un_salon_de_journal_INTROUVABLE_se_dit():
    """Le défaut de forme d'origine : trois `if` imbriqués sans `else`. Salon
    supprimé ou cache froid, et le journal du soir disparaissait sans un mot."""
    from loguru import logger

    feed, bot, _ = _feed([])
    bot.get_channel = MagicMock(return_value=None)
    vues: list[str] = []
    sink = logger.add(lambda m: vues.append(m.record["message"]), level="WARNING")
    try:
        await feed.publier("le journal")
    finally:
        logger.remove(sink)
    assert any("introuvable" in v for v in vues)


async def test_sans_salon_configure_on_ne_cherche_meme_pas():
    feed, bot, _ = _feed([], journal_channel_id=None)
    await feed.publier("le journal")
    bot.get_channel.assert_not_called()


# ── le branchement ──────────────────────────────────────────────────────────

def test_brancher_pose_les_DEUX_callbacks():
    """Un seul des deux posé, et le journal partirait sans historique — ou le
    lirait sans jamais le publier. Le câblage est ce que rien ne testait."""
    feed, _, _ = _feed([])
    journal = MagicMock()
    feed.brancher(journal)
    journal.set_send_callback.assert_called_once_with(feed.publier)
    journal.set_history_callback.assert_called_once_with(feed.lire_la_journee)


def test_le_branchement_se_VOIT_au_boot():
    """Le journal ne tourne qu'à 21 h : un branchement raté ne se découvrirait
    que le soir, sur un journal absent, sans rien pour dire si c'est le tuyau
    ou le contenu qui a manqué."""
    from loguru import logger

    feed, _, _ = _feed([])
    vues: list[str] = []
    sink = logger.add(lambda m: vues.append(m.record["message"]), level="INFO")
    try:
        feed.brancher(MagicMock())
    finally:
        logger.remove(sink)
    assert any("tuyaux Discord branchés" in v for v in vues)
