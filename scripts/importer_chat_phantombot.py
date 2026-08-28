#!/usr/bin/env python3
"""Verse dans la mémoire de Wally les mois de chat que seul PhantomBot a vus.

PhantomBot journalise le chat Twitch depuis le **9 février 2026** ; Wally, lui,
seulement depuis le **14 juillet** (ses JSONL). Entre les deux : 103 jours et
~29 700 lignes utiles, 373 personnes, que Wally n'a jamais lues. C'est de la
matière à faits — `fact_extractor` tourne déjà sur exactement cette entrée : un
auteur, un texte.

⚠️ **Ces faits ne doivent JAMAIS passer pour du frais.** Chaque fait entre daté
du jour où la chose a été DITE (`quand`), pas du jour de l'import. Sans ça :

- la réconciliation tranche les contradictions à l'ancienneté, et un fait de
  février daté d'août écraserait une vérité plus récente ;
- `get_users_with_recent_facts` régénère le portrait des gens dont un fait a
  bougé « récemment » — 373 portraits refaits d'un coup, sur du vieux ;
- le journal du soir lit les messages Discord depuis minuit, pas les faits, mais
  son repli `_build_memory_fallback_context()` verse TOUS les souvenirs connus
  les soirs sans conversation.

Résolution des identités : l'ID identifie, le pseudo s'adresse. Les pseudos sont
convertis en identifiants Twitch via `phantombot_logintoid`, lu dans le dump du
jour — 360 des 373 auteurs, soit 96 % des lignes. Les 13 restants sont ignorés
plutôt qu'écrits sous un pseudo : un fait rangé sous `twitch:<pseudo>` ne
rejoindrait jamais la personne.

Usage :
    PYTHONPATH=. python3 scripts/importer_chat_phantombot.py --jour 2026-02-20
    PYTHONPATH=. python3 scripts/importer_chat_phantombot.py --jour 2026-02-20 --apply
    PYTHONPATH=. python3 scripts/importer_chat_phantombot.py --apply   # les 103 jours
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import gzip
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger  # noqa: E402

from bot.config import Config  # noqa: E402
from bot.core.llm.factory import create_llm_client  # noqa: E402
from bot.db.database import Database  # noqa: E402
from bot.db.schema_v2 import create_v2_tables  # noqa: E402
from bot.intelligence.fact_extractor import FactExtractor  # noqa: E402
from bot.intelligence.memory.ingest import MemoryIngest  # noqa: E402
from bot.intelligence.memory.service import MemoryService  # noqa: E402

_PB = "/opt/stacks/phanthombotwally/data"

# Le jour où les JSONL de Wally commencent : au-delà, il a déjà tout vu.
_DEBUT_WALLY = "2026-07-14"

# `[02-09-2026 @ 11:43:17.036 GMT] pseudo: message` — 2 lignes sur 51 254 y échappent.
_LIGNE = re.compile(r"^\[(\d\d)-(\d\d)-(\d{4}) @ [\d:.]+ GMT\] ([^:]+): (.*)$")

# `wallytebully` est le compte PARTAGÉ par Wally et PhantomBot : ses lignes sont
# les réponses des deux bots. Les mémoriser ferait apprendre à Wally ses propres
# répliques comme des faits sur les gens.
_BOTS = {
    "wallytebully", "streamelements", "nightbot", "moobot", "fossabot",
    "streamlabs", "sery_bot", "kofistreambot", "own3d", "botrixoficial",
    "tangiabot", "creatisbot", "wizebot", "commanderroot", "anotherttvviewer",
}

# Combien de lignes par appel au LLM. La fenêtre de contexte du fact_extractor
# tourne autour de 20 messages en production ; on reste dans le même ordre pour
# que l'extraction voie des échanges, pas des phrases isolées.
_LOT = 25


def _dump_du_jour() -> str:
    """Le dump SQL le plus récent de PhantomBot (il en écrit un par jour)."""
    dumps = sorted(glob.glob(f"{_PB}/dbbackup/*.h2.sql.gz"))
    if not dumps:
        raise SystemExit(f"Aucun dump dans {_PB}/dbbackup/")
    return dumps[-1]


def _table(chemin: str, table: str) -> list[tuple[str, str]]:
    """Les (variable, value) d'une table du dump, validés contre le compteur H2.

    H2 écrit `-- N +/- SELECT COUNT(*) FROM PUBLIC.<table>;` juste avant chaque
    bloc. Un parseur naïf déborde d'un `INSERT` sur la table suivante et rend des
    chiffres crédibles mais faux — vécu : 161 « anciens pseudos » qui n'ont
    jamais existé. On compare, et on refuse de continuer en cas d'écart.
    """
    tup = re.compile(r"\('((?:[^']|'')*)', '((?:[^']|'')*)', '((?:[^']|'')*)'\)")
    ins = re.compile(r'INSERT INTO "PUBLIC"\."([A-Za-z0-9_]+)" VALUES(.*)$')
    cnt = re.compile(r"^-- (\d+) \+/- SELECT COUNT\(\*\) FROM PUBLIC\.([A-Za-z0-9_]+);")
    lignes: list[tuple[str, str]] = []
    attendu: int | None = None
    courante: str | None = None

    def _tuples(texte: str) -> None:
        for t in tup.finditer(texte):
            if courante == table:
                lignes.append((t.group(2).replace("''", "'"),
                               t.group(3).replace("''", "'")))

    with gzip.open(chemin, "rt", encoding="utf-8", errors="replace") as f:
        for ligne in f:
            c = cnt.match(ligne)
            if c and c.group(2) == table:
                attendu = int(c.group(1))
                continue
            m = ins.match(ligne.rstrip("\n"))
            if m:
                courante = m.group(1)
                _tuples(m.group(2))
                continue
            if courante is None:
                continue
            if ligne.lstrip().startswith("("):
                _tuples(ligne)
            else:
                courante = None

    if attendu is not None and len(lignes) != attendu:
        raise SystemExit(
            f"Parsage de {table} incohérent : {len(lignes)} lues, "
            f"{attendu} annoncées par H2. Ne pas importer sur cette base."
        )
    return lignes


def _lire_les_logs(jour: str | None) -> dict[str, list[tuple[str, str]]]:
    """{jour: [(pseudo, texte), …]} — bots, commandes et période Wally écartés."""
    par_jour: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for fichier in sorted(glob.glob(f"{_PB}/logs/chat/*.txt")):
        with open(fichier, encoding="utf-8", errors="replace") as f:
            for ligne in f:
                m = _LIGNE.match(ligne.rstrip("\n"))
                if not m:
                    continue
                mois, j, an, qui, texte = m.groups()
                date = f"{an}-{mois}-{j}"
                if jour is not None and date != jour:
                    continue
                if jour is None and date >= _DEBUT_WALLY:
                    continue
                qui = qui.lower()
                # Les `!commande` sont de la mécanique de bot, pas de la parole.
                if qui in _BOTS or texte.startswith("!") or not texte.strip():
                    continue
                par_jour[date].append((qui, texte))
    return dict(par_jour)


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    p.add_argument("--jour", help="une seule journée, AAAA-MM-JJ (essai avant la masse)")
    p.add_argument("--apply", action="store_true", help="écrit (sinon dry-run)")
    args = p.parse_args()

    par_jour = _lire_les_logs(args.jour)
    if not par_jour:
        print("Rien à importer.")
        return 0

    l2i = {pseudo.lower(): uid for pseudo, uid in _table(_dump_du_jour(),
                                                         "phantombot_logintoid")}
    total = sum(len(v) for v in par_jour.values())
    connus = sum(1 for lignes in par_jour.values() for qui, _ in lignes if qui in l2i)
    orphelins = sorted({qui for lignes in par_jour.values()
                        for qui, _ in lignes if qui not in l2i})

    print(f"{len(par_jour)} jour(s), {total} ligne(s) utiles.")
    print(f"  résolues en ID Twitch : {connus}  ({total - connus} écartées, "
          f"{len(orphelins)} pseudo(s) sans ID)")
    if orphelins:
        print(f"  sans ID, donc ignorés : {', '.join(orphelins[:12])}"
              + (" …" if len(orphelins) > 12 else ""))
    print(f"  ~{(connus + _LOT - 1) // _LOT} appel(s) LLM à {_LOT} lignes")

    if not args.apply:
        print("\ndry-run — relancer avec --apply")
        for date in sorted(par_jour)[:1]:
            print(f"\nAperçu du {date} :")
            for qui, texte in par_jour[date][:8]:
                marque = l2i.get(qui, "SANS ID")
                print(f"  [{qui} → {marque}] {texte[:90]}")
        return 0

    db = await Database.create(args.db)
    try:
        config = Config.load()
        await create_v2_tables(args.db)
        secondary = create_llm_client(config.llm.secondary, db)
        memory = MemoryService(config)
        memory.set_embedding_backend(db_path=args.db)
        memory.set_openai_client(secondary)
        memory.set_db(db)
        await memory.load_aliases(db)
        if memory.fact_store is None:
            print("fact_store indisponible — on n'importe pas à l'aveugle.")
            return 1
        extracteur = FactExtractor(
            config, memory, secondary, db=db,
            ingest=MemoryIngest(memory.fact_store, secondary),
        )

        ecrits = 0
        for date in sorted(par_jour):
            # Minuit heure de Paris ce jour-là, ramené en UTC naïf comme le
            # reste des colonnes de dates (cf. `MemoryService.add`). L'heure
            # exacte n'a pas d'importance : c'est le JOUR qui situe le fait.
            quand = datetime.strptime(date, "%Y-%m-%d")
            messages = [
                {"user_id": l2i[qui], "display_name": qui, "content": texte}
                for qui, texte in par_jour[date] if qui in l2i
            ]
            for i in range(0, len(messages), _LOT):
                lot = messages[i:i + _LOT]
                ecrits += await extracteur._extract_facts(
                    lot, "twitch", f"phantombot:{date}",
                    origin=f"phantombot_chat:{date}", quand=quand,
                )
            logger.info("Import {d} : {n} ligne(s) → {e} fait(s) au total",
                        d=date, n=len(messages), e=ecrits)

        print(f"\n{ecrits} fait(s) écrit(s), datés de leur jour d'origine.")
        print("Les portraits ne se régénéreront PAS tout seuls (les faits ne "
              "sont pas 'récents') — lancer scripts/regenerer_portraits.py "
              "--apply si on veut qu'ils intègrent cette matière.")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
