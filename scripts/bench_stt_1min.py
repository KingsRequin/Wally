#!/usr/bin/env python3
"""Compare le STT local et Qwen3-ASR-Flash (via 1min.ai) sur le MÊME audio.

Trois questions, dans l'ordre où elles décident :

1. **Qui comprend le mieux ?** Le moteur local est un `small` sur CPU ; il rend
   « je suis enceinte tellement rompiche » là où quelqu'un parlait de ranked.
   Qwen est deux ordres de grandeur plus gros. On compare mot à mot.

2. **Qui tient sous la charge ?** C'est la vraie question du live. Le local
   nominal est à ~450 ms, mais à trois locuteurs il monte à 6-8 s et finit par
   JETER des énoncés (mesuré le 2026-08-18). Une API n'a pas de file : elle
   encaisse les trois en parallèle. Un banc qui ne mesure qu'un énoncé à la
   fois passe à côté du seul chiffre qui compte.

3. **Qui résiste au bruit ?** Un salon vocal n'est pas un studio. Chaque
   échantillon est rejoué avec du bruit ajouté, à deux niveaux.

Le corpus est celui de `bench_stt.py` (voix de synthèse) : ces chiffres valent
en COMPARAISON entre moteurs, pas en absolu.

    docker exec wally-bot python scripts/bench_stt_1min.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from bot.discord.voice.request import address_match

_CACHE = Path("data/bench_stt")
_API = "https://api.1min.ai/api"
_NOMS = ["wally"]

# Ce que chaque échantillon dit vraiment, pour juger les transcriptions.
_ATTENDU = {
    "Wally, tu peux m'envoyer un mail ?": True,
    "Eh ben écoute, moi ça va, mon cher Wally, tout va bien.": True,
    "Envoie un mème, Wally.": True,
    "Alors, Wally écoute pas ce qu'il dit.": True,
    "Le modèle 3D de Wally qui tourne derrière.": True,
    "Wally, il y a toujours zéro kill ?": True,
    "Demande des trucs à Wally.": True,
    "Wally, t'en penses quoi de cette partie ?": True,
    "Gros, ça fait trois fois qu'on fait le wall jump dans ce coin du mur.": False,
    "Il faut que j'investisse dans un walk, le walk c'est la vie.": False,
    "J'arrive, I'm on my way, pour sauver Cassandra.": False,
    "Well, c'est bien chaud.": False,
    "Allez, on y va les gars.": False,
    "Elle est où la balle ?": False,
    "Salut tout le monde, ça va ?": False,
    "Je fais principalement du farm de kills.": False,
}


def _wav(pcm: bytes) -> bytes:
    import io
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return tampon.getvalue()


def _bruiter(pcm: bytes, rapport: float) -> bytes:
    """Ajoute du bruit à `rapport` fois l'amplitude du signal (0 = intact)."""
    if not rapport:
        return pcm
    import numpy as np
    sig = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    tirage = np.random.RandomState(7)
    bruit = tirage.randn(len(sig)) * (np.abs(sig).mean() * rapport)
    return np.clip(sig + bruit, -32768, 32767).astype("<i2").tobytes()


def _appel_1min(pcm: bytes, cle: str) -> tuple[str, float]:
    """(texte, secondes). Upload PUIS transcription — les deux comptent en latence.

    Compter l'upload est le seul honnête : en production, l'audio part du
    conteneur à chaque énoncé. Ne chronométrer que l'inférence donnerait un
    chiffre que le live ne verra jamais.
    """
    import httpx

    t0 = time.monotonic()
    with httpx.Client(timeout=180.0) as client:
        envoi = client.post(f"{_API}/assets", headers={"API-KEY": cle},
                            files={"asset": ("a.wav", _wav(pcm), "audio/wav")})
        try:
            chemin = envoi.json()["fileContent"]["path"]
        except Exception:
            return f"<upload illisible: {envoi.text[:120]!r}>", time.monotonic() - t0
        rep = client.post(f"{_API}/features",
                          headers={"API-KEY": cle, "Content-Type": "application/json"},
                          json={"type": "SPEECH_TO_TEXT", "model": "qwen3-asr-flash",
                                "promptObject": {"audioUrl": chemin,
                                                 "response_format": "text",
                                                 "language": "fr"}})
    dt = time.monotonic() - t0
    try:
        corps = rep.json()
        if "errorCode" in corps:
            return f"<refus: {corps.get('message', '')[:90]}>", dt
        res = corps["aiRecord"]["aiRecordDetail"]["resultObject"]
        return (res[0] if isinstance(res, list) else str(res)).strip(), dt
    except Exception:
        return f"<réponse illisible: {rep.text[:120]!r}>", dt


async def _local(pcm: bytes, stt) -> tuple[str, float]:
    t0 = time.monotonic()
    texte = await stt.transcribe(pcm)
    return texte.strip(), time.monotonic() - t0


def _juge(dit: str, entendu: str) -> str:
    """Le nom est-il là où il doit être ? C'est la garde de prod qui tranche."""
    attendu = _ATTENDU[dit]
    vu = address_match(entendu, _NOMS).addressed
    if attendu and vu:
        return "ok"
    if attendu:
        return "RATÉ"
    return "FAUX" if vu else "ok"


async def principal() -> None:
    cle = os.environ.get("ONEMIN_API_KEY", "")
    if not cle:
        raise SystemExit("ONEMIN_API_KEY manquant dans .env")

    from bot.discord.voice.providers import FasterWhisperSTT

    textes = sorted(_ATTENDU)
    # Le cache de `bench_stt.py` porte le haché du texte.
    import hashlib
    echantillons = []
    for t in textes:
        f = _CACHE / f"{hashlib.sha1(t.encode()).hexdigest()[:16]}.pcm16k"
        if f.exists():
            echantillons.append((t, f.read_bytes()))
    print(f"{len(echantillons)}/{len(textes)} échantillons en cache\n")

    stt = FasterWhisperSTT(model_size="small", language="fr-FR",
                           device="cpu", compute_type="int8", phrases=["Wally"])
    await stt.warmup()

    for libelle, bruit in (("audio propre", 0.0), ("bruit modéré", 0.3), ("bruit fort", 0.8)):
        print(f"\n{'=' * 78}\n{libelle}\n{'=' * 78}")
        scores = {"local": [0, 0, 0.0], "qwen": [0, 0, 0.0]}  # ok, faux/ratés, secondes
        for dit, pcm_net in echantillons:
            pcm = _bruiter(pcm_net, bruit)
            t_loc, dt_loc = await _local(pcm, stt)
            t_qwen, dt_qwen = await asyncio.to_thread(_appel_1min, pcm, cle)
            for cle_m, texte, dt in (("local", t_loc, dt_loc), ("qwen", t_qwen, dt_qwen)):
                verdict = _juge(dit, texte)
                scores[cle_m][0 if verdict == "ok" else 1] += 1
                scores[cle_m][2] += dt
            marque = f"{_juge(dit, t_loc):4s}/{_juge(dit, t_qwen):4s}"
            print(f"  [{marque}] {dit}")
            print(f"      local ({dt_loc:4.1f}s) : {t_loc}")
            print(f"      qwen  ({dt_qwen:4.1f}s) : {t_qwen}")
        for cle_m in ("local", "qwen"):
            ok, ko, secs = scores[cle_m]
            print(f"  → {cle_m:6s} : {ok}/{ok + ko} justes · {secs:.0f} s au total")


if __name__ == "__main__":
    asyncio.run(principal())
