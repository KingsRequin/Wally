#!/usr/bin/env python3
"""La phrase au présent qui dit à Wally ce qu'il sait faire.

Une demande d'amélioration livrée doit laisser une phrase à la PREMIÈRE PERSONNE
et au PRÉSENT dans `pending_upgrades.capability` — « Je vois le chat du live ».
Sans elle, le rendu retombe sur le texte de la DEMANDE, écrit du point de vue du
créateur (« Permettre à Wally de… ») : une phrase que Wally requalifie dès qu'un
désir la contredit, au lieu de l'intégrer. C'est le motif du 2026-08-09.

Le mécanisme existe (`SelfFix._ecrire_capacite`) mais ne couvre QUE le chemin
self-fix. Constaté le 2026-08-20 : les 15 demandes livrées entre le 2026-07-02
et le 2026-08-09 — toutes antérieures au mécanisme — avaient `capability` vide,
et `scripts/audit_memoire.py` montrait 3 désirs actifs réclamant des capacités
déjà livrées. Wally redemandait ce qu'il possédait.

Ce script couvre les deux trous :

  --apply            rattrape l'existant : toute livraison sans phrase en reçoit une
  --livrer <id>      marque une demande livrée À LA MAIN *et* pose sa phrase

Il n'implémente AUCUNE formulation : il appelle `formuler_capacite()`, le même
point que self-fix. Un seul endroit à corriger si la voix doit changer.

Rien n'est jamais écrasé : une demande qui a déjà sa phrase est laissée
tranquille (sauf `--refaire`).

Usage :
    python3 scripts/capacites_livrees.py                 # dry-run : montre les phrases
    python3 scripts/capacites_livrees.py --apply         # écrit
    python3 scripts/capacites_livrees.py --livrer 21 --apply
    python3 scripts/capacites_livrees.py --refaire --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from loguru import logger  # noqa: E402

# Hors Docker les clés API ne sont pas dans l'environnement (cf. bot/main.py).
load_dotenv()

from bot.config import Config  # noqa: E402
from bot.db.database import Database  # noqa: E402
from bot.intelligence.upgrade_registry import (  # noqa: E402
    DELIVERED,
    UpgradeRegistry,
    formuler_capacite,
)


async def _run(db_path: str, apply: bool, livrer: int | None, refaire: bool) -> int:
    config = Config.load()
    db = await Database.create(db_path)
    registre = UpgradeRegistry(db_path)

    from bot.core.llm.factory import create_llm_client

    llm = create_llm_client(config.llm.secondary, db)

    try:
        if livrer is not None:
            demande = await registre.get(livrer)
            if demande is None:
                logger.error("Demande #{i} introuvable", i=livrer)
                return 1
            if demande.status != DELIVERED:
                logger.info("#{i} : {s} → {d}", i=livrer, s=demande.status, d=DELIVERED)
                if apply:
                    await registre.set_status(livrer, DELIVERED)
            cibles = [demande]
        else:
            cibles = [u for u in await registre.recent(limit=None)
                      if u.status == DELIVERED]

        if not refaire:
            cibles = [u for u in cibles if not (u.capability or "").strip()]

        if not cibles:
            logger.info("Rien à faire : toute livraison porte déjà sa phrase.")
            return 0

        logger.info("{n} livraison(s) sans phrase au présent", n=len(cibles))
        ecrites = 0
        for u in cibles:
            phrase = await formuler_capacite(llm, u.proposal)
            if not phrase:
                # Journalisé, jamais avalé : une reformulation ratée laisse la
                # colonne NULL, et c'est exactement le trou qu'on comble ici.
                logger.warning("#{i} : reformulation vide — laissée sans phrase", i=u.id)
                continue
            print(f"\n  #{u.id}")
            print(f"    demande  : {(u.proposal or '')[:110]}")
            print(f"    capacité : {phrase}")
            if apply:
                await registre.set_capability(u.id, phrase)
                ecrites += 1

        if apply:
            logger.info("{n} phrase(s) écrite(s) en base", n=ecrites)
        else:
            logger.info("Dry-run — relancer avec --apply pour écrire")
        return 0
    finally:
        await db.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    p.add_argument("--apply", action="store_true", help="écrit en base (sinon dry-run)")
    p.add_argument("--livrer", type=int, metavar="ID",
                   help="marque cette demande livrée ET pose sa phrase")
    p.add_argument("--refaire", action="store_true",
                   help="reformule aussi les livraisons qui ont déjà une phrase")
    a = p.parse_args()
    return asyncio.run(_run(a.db, a.apply, a.livrer, a.refaire))


if __name__ == "__main__":
    raise SystemExit(main())
