#!/usr/bin/env python3
"""Mesure ce que le STT local comprend — et ce qu'il invente.

Sert à trancher un réglage du moteur (hotwords, taille de modèle, beam) avec
des chiffres plutôt qu'avec une intuition. Deux questions, qui ne se répondent
jamais l'une l'autre :

1. **Est-ce qu'il entend son nom ?** Les phrases d'appel viennent des logs
   vocaux réels — celles où Wally a été appelé et n'a PAS répondu, parce que le
   modèle rendait « Wadi », « Wali », « Weli ». La réussite se juge avec la
   VRAIE garde de production (`address_match`), pas à l'œil : ce qui compte
   n'est pas que la transcription soit jolie, c'est que le bot réagisse.

2. **Est-ce qu'il l'invente ?** Les phrases de contrôle ne le nomment pas, et
   plusieurs contiennent les mots qui en sont proches (« wall jump », « on my
   way », « un walk »). Un réglage qui gagne sur (1) en perdant sur (2) est un
   mauvais réglage : chaque faux déclenchement coûte un appel au modèle ET un
   message publié dans le chat de la chaîne.

Le corpus est synthétisé par le TTS Azure de production, puis mis en cache dans
`data/bench_stt/` — une voix de synthèse n'est pas un micro de salon, donc les
chiffres valent en COMPARAISON entre réglages, pas en absolu.

    docker exec wally-bot python scripts/bench_stt.py
    docker exec wally-bot python scripts/bench_stt.py --modele small --modele medium
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from bot.discord.voice.audio import est_sous_le_plancher
from bot.discord.voice.request import address_match

_CACHE = Path("data/bench_stt")
_NOMS = ["wally"]

# Le vocabulaire à souffler au moteur. Le nom d'abord — c'est lui qui décide si
# Wally répond ; le reste est le jargon du salon, relevé dans les logs.
_HOTWORDS = "Wally, Azraël, Apex Legends, kills, ranked, Malef"


@dataclass(frozen=True)
class Cas:
    texte: str      # ce qui est prononcé
    appelle: bool   # Wally doit-il se sentir nommé ?


# Phrases d'appel : toutes RATÉES en live (cf. logs vocaux 2026-08-14→18), le
# nom étant rendu « Wadi », « Wali », « Weli », « Wallier ».
_APPELS = [
    "Wally, tu peux m'envoyer un mail ?",
    "Eh ben écoute, moi ça va, mon cher Wally, tout va bien.",
    "Envoie un mème, Wally.",
    "Alors, Wally écoute pas ce qu'il dit.",
    "Le modèle 3D de Wally qui tourne derrière.",
    "Wally, il y a toujours zéro kill ?",
    "Demande des trucs à Wally.",
    "Wally, t'en penses quoi de cette partie ?",
]

# Phrases de contrôle : il ne doit PAS se sentir nommé. Les quatre premières
# portent les mots qui l'ont fait parler dans le vide, ou qui en sont à une
# correction — c'est là qu'un réglage trop bavard se voit.
_CONTROLES = [
    "Gros, ça fait trois fois qu'on fait le wall jump dans ce coin du mur.",
    "Il faut que j'investisse dans un walk, le walk c'est la vie.",
    "J'arrive, I'm on my way, pour sauver Cassandra.",
    "Well, c'est bien chaud.",
    "Allez, on y va les gars.",
    "Elle est où la balle ?",
    "Salut tout le monde, ça va ?",
    "Je fais principalement du farm de kills.",
]

_CAS = [Cas(t, True) for t in _APPELS] + [Cas(t, False) for t in _CONTROLES]


async def _synthetiser(cas: Cas) -> bytes:
    """PCM 16 kHz mono du texte, via le TTS de production. Mis en cache sur disque.

    Le cache porte sur le HACHÉ du texte : changer une phrase régénère la
    sienne et laisse les autres tranquilles — un banc qu'on repaie en entier à
    chaque retouche finit par ne plus être lancé.
    """
    _CACHE.mkdir(parents=True, exist_ok=True)
    cle = hashlib.sha1(cas.texte.encode("utf-8")).hexdigest()[:16]
    fichier = _CACHE / f"{cle}.pcm16k"
    if fichier.exists():
        return fichier.read_bytes()

    import audioop

    from bot.config import Config
    from bot.discord.voice.providers import build_tts

    cfg = Config.load()
    tts = build_tts(cfg.voice)
    pcm48k = await tts.synthesize(cas.texte)
    if not pcm48k:
        raise RuntimeError(f"TTS muet sur : {cas.texte!r}")
    pcm16k, _ = audioop.ratecv(pcm48k, 2, 1, 48000, 16000, None)
    fichier.write_bytes(pcm16k)
    return pcm16k


def _construire(modele: str, hotwords: str | None):
    """Le STT local de production, dont on force l'indice de vocabulaire.

    On passe par le constructeur — donc par le chemin de transcription réel — et
    non par une copie du décodage : un banc qui reproduit le code au lieu de
    l'appeler finit par mesurer autre chose que ce qui tourne. `hotwords=None`
    donne bien l'absence d'indice, la config n'étant pas lue ici.
    """
    from bot.discord.voice.providers import FasterWhisperSTT

    return FasterWhisperSTT(model_size=modele, language="fr-FR",
                            device="cpu", compute_type="int8", hotwords=hotwords)


@dataclass
class Bilan:
    appels_vus: int = 0
    appels_total: int = 0
    faux: int = 0
    controles_total: int = 0
    secondes_audio: float = 0.0
    secondes_calcul: float = 0.0
    rates: list = None
    inventions: list = None

    def __post_init__(self):
        self.rates = self.rates or []
        self.inventions = self.inventions or []

    @property
    def debit(self) -> float:
        """Secondes d'audio traitées par seconde de calcul. Sous 1, il décroche."""
        return self.secondes_audio / self.secondes_calcul if self.secondes_calcul else 0.0


async def _mesurer(modele: str, hotwords: str | None, echantillons: list) -> Bilan:
    stt = _construire(modele, hotwords)
    await stt.warmup()
    b = Bilan()
    for cas, pcm in echantillons:
        t0 = time.monotonic()
        texte = await stt.transcribe(pcm)
        b.secondes_calcul += time.monotonic() - t0
        b.secondes_audio += len(pcm) / 32000
        vu = address_match(texte, _NOMS).addressed
        if cas.appelle:
            b.appels_total += 1
            if vu:
                b.appels_vus += 1
            else:
                b.rates.append((cas.texte, texte))
        else:
            b.controles_total += 1
            if vu:
                b.faux += 1
                b.inventions.append((cas.texte, texte))
    return b


def _non_paroles() -> list[tuple[str, bytes]]:
    """Du son qui n'est PAS de la parole, et qui franchit le plancher.

    C'est le test qui décide, parce que c'est le défaut qui avait fait éteindre
    le biais du décodage : un ventilateur, et le modèle rendait « Wally wally ».
    Le silence pur ne prouve rien — le plancher l'écarte déjà. On prend donc du
    bruit assez fort pour lui passer devant.
    """
    import numpy as np

    tirage = np.random.RandomState(1234)
    sons = []
    for nom, ampli in (("souffle faible", 0.02), ("ventilateur", 0.06), ("bruit fort", 0.15)):
        for secondes in (1.0, 3.0):
            brut = tirage.randn(int(16000 * secondes)) * ampli
            # Souffle de ventilateur : du bruit, mais grave — un passe-bas
            # grossier suffit à s'éloigner du bruit blanc, que le VAD écarte
            # trop facilement pour être un test honnête.
            lisse = np.convolve(brut, np.ones(8) / 8, mode="same")
            pcm = (np.clip(lisse, -1, 1) * 32767).astype("<i2").tobytes()
            sous, _duree, niveau = est_sous_le_plancher(pcm)
            if sous:
                continue  # la prod l'écarterait : ce n'est pas au moteur de le juger
            sons.append((f"{nom} {secondes:.0f} s (rms {niveau})", pcm))
    return sons


async def _mesurer_inventions(modele: str, hotwords: str | None,
                              sons: list) -> tuple[int, list]:
    """Combien de ces non-paroles produisent du texte — et lequel."""
    stt = _construire(modele, hotwords)
    await stt.warmup()
    bavardages = []
    for libelle, pcm in sons:
        texte = (await stt.transcribe(pcm)).strip()
        if texte:
            nomme = address_match(texte, _NOMS).addressed
            bavardages.append((libelle, texte, nomme))
    return len(bavardages), bavardages


async def principal() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modele", action="append", default=None,
                    help="taille faster-whisper (répétable) ; défaut : small")
    args = ap.parse_args()
    modeles = args.modele or ["small"]

    print("Synthèse du corpus (TTS Azure, mis en cache)…")
    echantillons = []
    for cas in _CAS:
        pcm = await _synthetiser(cas)
        sous, duree, niveau = est_sous_le_plancher(pcm)
        if sous:  # ne mesurerait rien : la prod l'écarterait avant le moteur
            print(f"  ⚠ écarté par le plancher ({duree:.1f} s, rms {niveau}) : {cas.texte}")
            continue
        echantillons.append((cas, pcm))
    sons = _non_paroles()
    print(f"{len(echantillons)} échantillons · {len(sons)} non-paroles au-dessus du plancher\n")

    for modele in modeles:
        # Le nom seul est mesuré à part : c'est ce que la production enverra
        # (`voice.phrases` = nom du bot + déclencheurs). Déployer la liste large
        # après n'avoir mesuré qu'elle serait déployer autre chose que le banc.
        variantes = (("sans hotwords", None), ("le nom seul", "Wally"),
                     ("nom + jargon", _HOTWORDS))
        for libelle, hw in variantes:
            b = await _mesurer(modele, hw, echantillons)
            n_inventions, details = await _mesurer_inventions(modele, hw, sons)
            print(f"=== {modele} · {libelle} ===")
            print(f"  appels entendus : {b.appels_vus}/{b.appels_total}")
            print(f"  faux déclenchements : {b.faux}/{b.controles_total}")
            print(f"  bavardage sur du bruit : {n_inventions}/{len(sons)}")
            for lib, texte, nomme in details:
                marque = " ← SE CROIT NOMMÉ" if nomme else ""
                print(f"    {lib} → {texte!r}{marque}")
            print(f"  débit : {b.debit:.1f}× le temps réel "
                  f"({b.secondes_calcul:.1f} s de calcul pour {b.secondes_audio:.1f} s d'audio)")
            for dit, entendu in b.rates:
                print(f"    raté   : {dit!r} → {entendu!r}")
            for dit, entendu in b.inventions:
                print(f"    INVENTÉ: {dit!r} → {entendu!r}")
            print()


if __name__ == "__main__":
    asyncio.run(principal())
