#!/usr/bin/env python3
"""Efface de la mémoire ce qui apprend à Wally à nommer les gens autrement.

Décidé par l'owner le 2026-08-25 : des viewers apprenaient à Wally à désigner
les autres par des surnoms — « mks_zedd est surnommé Zeddo », « clakernojutsu
l'appelle controllerhater » — et jusque dans les portraits, qui sont réinjectés
à CHAQUE prompt et battent n'importe quelle consigne.

Deux gisements, deux traitements :

  · `atomic_facts` — ARCHIVÉS, pas supprimés. C'est la convention du projet
    (« suppression = archive ») : un fait archivé sort du contexte mais reste
    lisible si on doit comprendre ce qui s'est passé.
  · `user_profiles` — les portraits sont RÉÉCRITS phrase à phrase. Les effacer
    entièrement coûterait un portrait complet à recalculer pour 27 personnes ;
    retirer les seules phrases fautives garde le reste intact.

`user_aliases` n'est PAS touché — décision d'arbitrage : ces alias servent à
COMPRENDRE qui est désigné (« azra » → azraël), pas à nommer. Les purger
rendrait Wally incapable de reconnaître les gens.

    python3 scripts/purger_surnoms.py            # montre, ne touche à rien
    python3 scripts/purger_surnoms.py --appliquer
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.core.surnoms import detecter  # noqa: E402

BASE = Path(__file__).resolve().parent.parent / "data" / "wally.db"

# Une phrase se termine par un point, un point-virgule ou un retour à la ligne.
# Les portraits sont rédigés en prose : découper plus fin couperait au milieu
# d'une énumération et rendrait le texte incompréhensible.
_PHRASE = re.compile(r"[^.;\n]+[.;\n]?")


def _phrases_fautives(portrait: str) -> list[str]:
    return [p for p in _PHRASE.findall(portrait or "")
            if p.strip() and detecter(p, None)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit vraiment (sans ce drapeau : simple aperçu)")
    ap.add_argument("--base", default=str(BASE))
    args = ap.parse_args()

    c = sqlite3.connect(args.base)

    # ── 1. les faits ────────────────────────────────────────────────────
    # `superseded` AUSSI, et pas seulement `active` : `UserModeler._refresh_one`
    # nourrit le portrait des deux lots. Ne traiter que les faits actifs
    # laisserait un surnom remonter par la passe de 21 h, sans que rien ne le
    # signale — et le portrait est réinjecté à chaque prompt.
    faits = [
        (fid, uid, txt) for fid, uid, txt, st
        in c.execute("SELECT id, user_id, content, status FROM atomic_facts")
        if st in ("active", "superseded") and detecter(txt or "", uid)
    ]
    print(f"FAITS à archiver : {len(faits)}  "
          f"({len({f[1] for f in faits})} personnes)")
    for fid, uid, txt in faits[:60]:
        print(f"  #{fid:<6} [{uid[:24]:24}] {txt[:96].splitlines()[0]}")
    if len(faits) > 60:
        print(f"  … et {len(faits) - 60} de plus")

    # ── 2. les portraits ────────────────────────────────────────────────
    portraits = []
    for uid, p in c.execute("SELECT user_id, portrait FROM user_profiles"):
        fautives = _phrases_fautives(p)
        if fautives:
            portraits.append((uid, p, fautives))
    total_phrases = sum(len(f) for _, _, f in portraits)
    print(f"\nPORTRAITS à nettoyer : {len(portraits)} "
          f"({total_phrases} phrase(s) retirée(s))")
    for uid, _, fautives in portraits[:20]:
        for ph in fautives:
            print(f"  [{uid[:24]:24}] − {ph.strip()[:96]}")

    if not args.appliquer:
        print("\n(aperçu seul — relancer avec --appliquer pour écrire)")
        return 0

    # ── 3. l'écriture ───────────────────────────────────────────────────
    for fid, _, _ in faits:
        c.execute("UPDATE atomic_facts SET status='archived' WHERE id=?", (fid,))
    nettoyes = 0
    for uid, portrait, fautives in portraits:
        neuf = portrait
        for ph in fautives:
            neuf = neuf.replace(ph, " ")
        # Espaces et ponctuation orpheline laissés par le retrait.
        neuf = re.sub(r"\s{2,}", " ", neuf)
        neuf = re.sub(r"\s+([,.;])", r"\1", neuf).strip()
        if neuf != portrait:
            c.execute("UPDATE user_profiles SET portrait=? WHERE user_id=?",
                      (neuf, uid))
            nettoyes += 1
    c.commit()
    print(f"\n✅ {len(faits)} fait(s) archivé(s), {nettoyes} portrait(s) réécrit(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
