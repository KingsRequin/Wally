"""ACT `generate_image` : Wally fabrique une image et la poste de lui-même.

Avant, une image n'existait que si un humain tapait `/wally imagine`. Ces tests
tiennent les trois choses qui font qu'une capacité coûteuse reste tenable : le
salon, le motif du refus, et le fait que la dépense laisse une trace même quand
l'envoi Discord échoue.
"""
from pathlib import Path

import pytest

from bot.config import ImageGenerationConfig
from bot.core.image_initiative import ImageInitiative
from bot.intelligence.action_dispatcher import ActionDispatcher
from bot.intelligence.meta_agent import MetaDecision

SALON = "938504877464768603"
NOMS = {SALON: "#shitpost"}


class _Db:
    def __init__(self):
        self.images = []

    async def get_user_image_count_today(self, user_id):
        return 0

    async def get_last_image_ts(self, user_id):
        return None

    async def insert_gallery_image(self, **kw):
        self.images.append(kw)


class _Channel:
    id = int(SALON)
    name = "shitpost"
    guild = type("G", (), {"name": "serveur"})()

    def __init__(self, boom=False, message=None):
        self.envois = []
        self.boom = boom
        self._message = message

    async def send(self, content=None, file=None, allowed_mentions=None, reference=None):
        if self.boom:
            raise RuntimeError("permissions manquantes")
        self.envois.append({"content": content, "file": file, "reference": reference})

    async def fetch_message(self, mid):
        if self._message is None:
            raise RuntimeError("message introuvable")
        return self._message


class _ImageClient:
    def __init__(self, fichier: Path, erreur=None):
        self.fichier = fichier
        self.erreur = erreur
        self.appels = []

    async def generate_image(self, prompt, config, sender_id=None):
        self.appels.append((prompt, sender_id))
        if self.erreur:
            raise self.erreur
        return {
            "file_id": "abc", "file_name": "abc.png", "file_path": str(self.fichier),
            "cost_usd": 0.01, "revised_prompt": None, "model": "gpt-image-1.5",
            "quality": "low", "size": "1024x1024",
        }


class _Memory:
    def __init__(self):
        self.prelude = []

    def append_prelude(self, *a, **kw):
        self.prelude.append(a)

    def append_message(self, *a, **kw):
        pass


class _Bot:
    def __init__(self, channel, client, db):
        self._channel = channel
        self.image_client = client
        self.db = db
        self.memory = _Memory()
        self.conv_log = None
        self.config = type("C", (), {
            "image_generation": ImageGenerationConfig(
                autonomous_enabled=True, autonomous_channel_ids=[SALON],
                autonomous_daily_limit=3, autonomous_cooldown_minutes=90,
            ),
            "bot": type("B", (), {"name": "Wally", "owner_discord_id": "42"})(),
        })()

    def get_channel(self, cid):
        # Tous les salons existent SAUF "0" : le seul refus mesuré ici doit être
        # celui de la politique. Un faux bot qui ne connaît que le salon autorisé
        # ferait passer le test même sans allowlist (vérifié par mutation).
        return None if str(cid) == "0" else self._channel


class _Feed:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


@pytest.fixture
def fichier_image(tmp_path):
    p = tmp_path / "abc.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def _dispatcher(bot, db, feed=None):
    initiative = ImageInitiative(bot.config, db, channel_names=NOMS,
                                 auteur_id="discord:7")
    return ActionDispatcher(bot=bot, feed=feed, image_initiative=initiative)


@pytest.mark.asyncio
async def test_image_generee_et_postee(fichier_image):
    channel, db = _Channel(), _Db()
    bot = _Bot(channel, _ImageClient(fichier_image), db)
    feed = _Feed()
    d = _dispatcher(bot, db, feed)

    await d._act("generate_image", {"channel_id": SALON, "prompt": "un chat en armure",
                                    "comment": "voilà"})

    assert len(channel.envois) == 1
    assert channel.envois[0]["content"] == "voilà"
    assert channel.envois[0]["file"] is not None
    # Rangée en galerie sous SON id : c'est cette ligne qui porte son quota.
    assert db.images and db.images[0]["user_id"] == "discord:7"
    assert db.images[0]["prompt"] == "un chat en armure"
    assert any(e["type"] == "ACT" for e in feed.events)
    # Le chemin réactif doit savoir qu'il vient de poster une image.
    assert bot.memory.prelude


@pytest.mark.asyncio
async def test_salon_interdit_ne_genere_rien(fichier_image):
    channel, db = _Channel(), _Db()
    client = _ImageClient(fichier_image)
    bot = _Bot(channel, client, db)
    d = _dispatcher(bot, db)

    await d._act("generate_image", {"channel_id": "111", "prompt": "un chat"})

    assert client.appels == []      # rien n'a été payé
    assert channel.envois == []


@pytest.mark.asyncio
async def test_le_motif_du_refus_est_journalise(fichier_image, monkeypatch):
    """« action silencieuse » ne dit pas quoi faire ; « salon interdit » si."""
    channel, db = _Channel(), _Db()
    bot = _Bot(channel, _ImageClient(fichier_image), db)
    d = _dispatcher(bot, db)
    motifs = []
    monkeypatch.setattr(d, "_journal_act_rejected",
                        lambda nom, args, motif: motifs.append(motif))

    await d._dispatch_act(MetaDecision(action="ACT", act_name="generate_image",
                                       act_args={"channel_id": "111", "prompt": "x"}))

    assert motifs and "interdit" in motifs[0]


@pytest.mark.asyncio
async def test_canal_introuvable(fichier_image):
    channel, db = _Channel(), _Db()
    client = _ImageClient(fichier_image)
    bot = _Bot(channel, client, db)
    d = _dispatcher(bot, db)
    d._image_initiative._config.image_generation.autonomous_channel_ids.append("0")

    await d._act("generate_image", {"channel_id": "0", "prompt": "un chat"})

    assert client.appels == []
    assert d._motif_refus == "canal 0 introuvable"


@pytest.mark.asyncio
async def test_prompt_manquant(fichier_image):
    channel, db = _Channel(), _Db()
    client = _ImageClient(fichier_image)
    bot = _Bot(channel, client, db)
    d = _dispatcher(bot, db)

    await d._act("generate_image", {"channel_id": SALON})

    assert client.appels == []


@pytest.mark.asyncio
async def test_refus_de_lapi_ne_casse_pas_le_tick(fichier_image):
    channel, db = _Channel(), _Db()
    client = _ImageClient(fichier_image, erreur=ValueError("prompt refusé"))
    bot = _Bot(channel, client, db)
    d = _dispatcher(bot, db)

    await d._act("generate_image", {"channel_id": SALON, "prompt": "x"})

    assert channel.envois == []
    assert db.images == []


@pytest.mark.asyncio
async def test_envoi_rate_laisse_quand_meme_la_depense_en_galerie(fichier_image):
    """L'image est payée : si elle disparaissait des compteurs, il réessaierait
    aussitôt et paierait deux fois."""
    channel, db = _Channel(boom=True), _Db()
    bot = _Bot(channel, _ImageClient(fichier_image), db)
    d = _dispatcher(bot, db)

    await d._act("generate_image", {"channel_id": SALON, "prompt": "x"})

    assert len(db.images) == 1
    assert d._motif_refus == "envoi Discord en échec"


@pytest.mark.asyncio
async def test_reponse_en_image_a_un_message(fichier_image):
    cible = object()
    channel, db = _Channel(message=cible), _Db()
    bot = _Bot(channel, _ImageClient(fichier_image), db)
    d = _dispatcher(bot, db)

    await d._act("generate_image", {"channel_id": SALON, "prompt": "x",
                                    "message_id": "555"})

    assert channel.envois[0]["reference"] is cible


@pytest.mark.asyncio
async def test_message_introuvable_ne_bloque_pas_lenvoi(fichier_image):
    channel, db = _Channel(message=None), _Db()
    bot = _Bot(channel, _ImageClient(fichier_image), db)
    d = _dispatcher(bot, db)

    await d._act("generate_image", {"channel_id": SALON, "prompt": "x",
                                    "message_id": "555"})

    assert len(channel.envois) == 1
    assert channel.envois[0]["reference"] is None


@pytest.mark.asyncio
async def test_sans_initiative_cablee_le_dispatcher_dit_pourquoi(fichier_image):
    channel, db = _Channel(), _Db()
    bot = _Bot(channel, _ImageClient(fichier_image), db)
    d = ActionDispatcher(bot=bot)
    assert d._service_manquant("generate_image") == "image_initiative"
