#!/usr/bin/env python3
"""Publie dans Discord des clips ANTÉRIEURS à la mise en service de la veille.

La veille (`bot/twitch/clip_announce.py`) ne connaît que les clips créés
pendant qu'elle tourne : les précédents n'ont jamais été postés. Ce script les
rattrape UNE fois, par la même carte Components V2 (`carte_de_clip`) et en
alimentant la même mémoire anti-doublon (`bot_state`).

⚠️ **Helix trie les clips par nombre de VUES, jamais par date.** « Les dix
derniers » se calcule donc ici, sur `created_at`. Et comme la réponse est
plafonnée à 100 entrées, une fenêtre qui en contient davantage rendrait les
100 plus VUS — un clip récent et peu vu passerait à la trappe. Le script le
DIT plutôt que de rendre un résultat faux en silence.

⚠️ **Redémarrer le bot après l'écriture.** Son instance de
`PublicationDesClips` a chargé la mémoire au boot et la réécrit ENTIÈRE à
chaque publication : sans restart, le premier clip du live suivant écraserait
les ids rattrapés, et ils repartiraient en doublon.

Usage :
    python3 scripts/rattraper_clips_discord.py                 # montre, n'envoie rien
    python3 scripts/rattraper_clips_discord.py --publier
    python3 scripts/rattraper_clips_discord.py --nombre 5 --jours 30 --publier
    docker compose restart wally     # OBLIGATOIRE après --publier
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RACINE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_RACINE / ".env")

import discord  # noqa: E402

from bot.config import Config  # noqa: E402
from bot.discord.clip_post import CLE_ETAT, carte_de_clip  # noqa: E402
from bot.twitch.api import TwitchAPI  # noqa: E402
from bot.twitch.token_manager import TwitchTokenManager  # noqa: E402

_BASE = _RACINE / "data" / "wally.db"
#: Assez pour que Discord ne compte pas la salve comme un flood, sans faire
#: durer le rattrapage : la limite est de 5 messages / 5 s par salon.
PAUSE_S = 1.5


async def _derniers_clips(nombre: int, jours: int) -> list[dict]:
    tm = TwitchTokenManager.load(_RACINE / ".env")
    api = TwitchAPI(
        token_manager=tm,
        client_id=os.getenv("TWITCH_CLIENT_ID", ""),
        bot_id=os.getenv("TWITCH_BOT_ID", "") or os.getenv("TWITCH_BROADCASTER_ID", ""),
        broadcaster_id=os.getenv("TWITCH_BROADCASTER_ID", ""),
    )
    depuis = datetime.now(timezone.utc) - timedelta(days=jours)
    clips = await api.get_recent_clips(depuis.strftime("%Y-%m-%dT%H:%M:%SZ"), first=100)
    if len(clips) >= 100:
        print(f"⚠️  100 clips rendus sur {jours} j — c'est le plafond Helix, et il "
              f"garde les plus VUS.\n    Un clip récent peu vu peut manquer : "
              f"relancer avec --jours plus petit.")
    clips.sort(key=lambda c: str(c.get("created_at") or ""), reverse=True)
    return clips[:nombre]


def _deja_publies() -> list[str]:
    if not _BASE.exists():
        return []
    with sqlite3.connect(_BASE) as conn:
        ligne = conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (CLE_ETAT,)
        ).fetchone()
    if not ligne or not ligne[0]:
        return []
    try:
        ids = json.loads(ligne[0])
    except (ValueError, TypeError):
        print("⚠️  mémoire des clips illisible, elle sera réécrite")
        return []
    return [str(i) for i in ids] if isinstance(ids, list) else []


def _ranger(ids: list[str]) -> None:
    import time
    with sqlite3.connect(_BASE) as conn:
        conn.execute(
            "INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (CLE_ETAT, json.dumps(ids), time.time()),
        )


async def _publier(clips: list[dict], salon_id: int) -> list[str]:
    """Poste du PLUS ANCIEN au plus récent : Discord empile, le dernier clip
    doit finir en bas."""
    envoyes: list[str] = []
    fini = asyncio.Event()

    class _Client(discord.Client):
        async def on_ready(self) -> None:
            try:
                salon = self.get_channel(salon_id) or await self.fetch_channel(salon_id)
                for clip in reversed(clips):
                    await salon.send(view=carte_de_clip(clip))
                    envoyes.append(str(clip.get("id") or ""))
                    print(f"   ✅ {clip.get('created_at')}  {clip.get('title')}")
                    await asyncio.sleep(PAUSE_S)
            except Exception as exc:  # noqa: BLE001 — on garde ce qui est parti
                print(f"   ❌ interrompu : {exc!r}")
            finally:
                fini.set()
                await self.close()

    client = _Client(intents=discord.Intents.default())
    await client.start(os.environ["DISCORD_TOKEN"])
    await fini.wait()
    return envoyes


async def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nombre", type=int, default=10)
    ap.add_argument("--jours", type=int, default=90)
    ap.add_argument("--publier", action="store_true",
                    help="envoie réellement (sans ce drapeau, montre seulement)")
    args = ap.parse_args()

    salon_id = Config.load(str(_RACINE / "config.yaml")).discord.clips_channel_id
    if not salon_id:
        print("❌ discord.clips_channel_id n'est pas renseigné dans config.yaml")
        return 1

    clips = await _derniers_clips(args.nombre, args.jours)
    if not clips:
        print(f"Aucun clip sur {args.jours} jours.")
        return 0

    deja = _deja_publies()
    neufs = [c for c in clips if str(c.get("id") or "") not in deja]
    print(f"{len(clips)} clip(s) retenu(s), {len(clips) - len(neufs)} déjà publié(s) :")
    for clip in neufs:
        print(f"   · {clip.get('created_at')}  {clip.get('title')} "
              f"— {clip.get('creator_name')}")
    if not neufs:
        return 0
    if not args.publier:
        print(f"\n(essai à blanc — relancer avec --publier pour envoyer dans {salon_id})")
        return 0

    print(f"\nEnvoi dans {salon_id}, du plus ancien au plus récent :")
    envoyes = await _publier(neufs, salon_id)
    if envoyes:
        _ranger(deja + envoyes)
        print(f"\n{len(envoyes)} clip(s) publié(s) et rangé(s) en base.")
        print("⚠️  `docker compose restart wally` MAINTENANT : sans ça, la mémoire "
              "en RAM du bot écrasera ces ids à la première publication du live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
