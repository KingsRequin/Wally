"""Sonde jetable : observer ce que l'API Apex dit d'un compte pendant qu'on joue.

Objectif — répondre à trois questions que la spec du duel laisse ouvertes :

  1. Que valent `isInGame` / `currentState` en lobby, en file d'attente, en partie ?
     Tout le découpage en manches en dépend, et on ne les a jamais observés qu'avec
     un compte hors ligne.
  2. QUELS compteurs de kills bougent après une partie — carrière, BR, par légende —
     et de combien. On saura alors lesquels sont indépendants et lesquels se
     recoupent, au lieu de le supposer.
  3. COMBIEN DE TEMPS après la fin d'une partie le tracker s'incrémente. C'est la
     valeur de `stabilite_s`.

Écrit dans `/tmp/duel_probe.jsonl` (une ligne par relevé et par compte) et n'affiche
que les CHANGEMENTS, pour rester lisible pendant une heure de jeu.

À jeter une fois la mesure faite. Lancement :
    python3 scripts/probe_duel.py
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx

# `platform` est OBLIGATOIRE même quand on interroge par uid : sans elle, l'API
# répond « Bad Request. Missing at least one of the following parameters ».
COMPTES = {"KingsRequin": ("1012242925358", "PC"), "Azrael": ("2274044345", "PC")}
CADENCE_S = 2.0
DUREE_MAX_S = 5400  # 90 min — un garde-fou, pas une cible
SORTIE = Path("/tmp/duel_probe.jsonl")


def _cle_api() -> str:
    for ligne in Path(".env").read_text(encoding="utf-8").splitlines():
        if ligne.startswith("APEX_API_KEY="):
            return ligne.split("=", 1)[1].strip()
    raise SystemExit("APEX_API_KEY absente de .env")


def _kills(bloc) -> dict:
    """Tous les trackers dont le libellé parle de kills, avec leur valeur.

    On ne présuppose AUCUNE clé : les trackers ne portent pas les mêmes d'un joueur
    à l'autre, et c'est précisément ce qu'on cherche à mesurer.

    Deux formes coexistent dans le même payload : `total` est un DICT indexé par clé,
    `legends.selected.data` est une LISTE de dicts portant leur propre `key`. Ne
    traiter que la première rendait les stats par légende vides en silence.
    """
    if isinstance(bloc, dict):
        entrees = [(cle, v) for cle, v in bloc.items() if isinstance(v, dict)]
    elif isinstance(bloc, list):
        entrees = [(str(v.get("key", "?")), v) for v in bloc if isinstance(v, dict)]
    else:
        return {}
    trouves = {}
    for cle, v in entrees:
        libelle = str(v.get("name", ""))
        if "kill" in libelle.lower() or "kill" in cle.lower():
            trouves[f"{cle} ({libelle})"] = v.get("value")
    return trouves


def _extrait(payload: dict) -> dict:
    rt = payload.get("realtime") or {}
    gl = payload.get("global") or {}
    legendes = payload.get("legends") or {}
    selected = legendes.get("selected") or {}
    return {
        "state": rt.get("currentState"),
        "state_txt": rt.get("currentStateAsText"),
        "since": rt.get("currentStateSinceTimestamp"),
        "online": rt.get("isOnline"),
        "in_game": rt.get("isInGame"),
        "party_full": rt.get("partyFull"),
        "legend": rt.get("selectedLegend"),
        "level": gl.get("level"),
        "level_pct": gl.get("toNextLevelPercent"),
        "kills_total": _kills(payload.get("total")),
        "legende_selected": selected.get("LegendName"),
        "kills_legende": _kills(selected.get("data")),
        "tous_trackers_legende": [t.get("name") for t in (selected.get("data") or []) if isinstance(t, dict)],
    }


async def _sonder(client: httpx.AsyncClient, cle: str, uid: str, plateforme: str) -> dict | None:
    try:
        r = await client.get("/bridge", headers={"Authorization": cle},
                             params={"uid": uid, "platform": plateforme}, timeout=15)
        if r.status_code != 200:
            return {"erreur": f"HTTP {r.status_code}", "corps": r.text[:120]}
        return _extrait(r.json())
    except Exception as exc:  # noqa: BLE001 — une sonde ne s'arrête pas sur un incident réseau
        return {"erreur": str(exc)[:120]}


def _diff(avant: dict | None, apres: dict) -> list[str]:
    if avant is None:
        return ["premier relevé"]
    lignes = []
    for k, v in apres.items():
        if avant.get(k) != v:
            lignes.append(f"{k}: {avant.get(k)!r} -> {v!r}")
    return lignes


async def main() -> None:
    cle = _cle_api()
    debut = time.monotonic()
    precedent: dict[str, dict] = {}
    print(f"Sonde lancée — {CADENCE_S} s, comptes : {', '.join(COMPTES)}")
    print(f"Journal : {SORTIE}\nSeuls les CHANGEMENTS s'affichent.\n")
    journal = SORTIE.open("a", encoding="utf-8")
    async with httpx.AsyncClient(base_url="https://api.mozambiquehe.re") as client:
      try:
        while time.monotonic() - debut < DUREE_MAX_S:
            for nom, (uid, plateforme) in COMPTES.items():
                releve = await _sonder(client, cle, uid, plateforme)
                if releve is None:
                    continue
                horodate = time.time()
                journal.write(json.dumps({"t": horodate, "compte": nom, **releve},
                                         ensure_ascii=False) + "\n")
                journal.flush()
                changements = _diff(precedent.get(nom), releve)
                if changements:
                    stamp = time.strftime("%H:%M:%S", time.localtime(horodate))
                    for ligne in changements:
                        print(f"[{stamp}] {nom:12s} {ligne}", flush=True)
                precedent[nom] = releve
            await asyncio.sleep(CADENCE_S)
      finally:
        journal.close()
    print("Durée maximale atteinte — sonde arrêtée.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
