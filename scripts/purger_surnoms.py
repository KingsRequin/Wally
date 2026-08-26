#!/usr/bin/env python3
"""Efface de la mémoire ce qui apprend à Wally à nommer les gens autrement.

Décidé par l'owner le 2026-08-25 : des viewers apprenaient à Wally à désigner
les autres par des surnoms — « mks_zedd est surnommé Zeddo », « clakernojutsu
l'appelle controllerhater » — et jusque dans les portraits, qui sont réinjectés
à CHAQUE prompt et battent n'importe quelle consigne.

Le 2026-08-26, Wally appelle toujours KingsRequin « petit chevreuil » en plein
live. La première passe n'avait traité que deux gisements sur cinq : tout ce
qui est RELU vers le prompt doit être purgé, pas seulement les faits.

  · `atomic_facts` — ARCHIVÉS, pas supprimés. C'est la convention du projet
    (« suppression = archive ») : un fait archivé sort du contexte mais reste
    lisible si on doit comprendre ce qui s'est passé.
  · `user_profiles` · `topics` · `session_analyses` — RÉÉCRITS phrase à
    phrase. Les effacer entièrement coûterait un portrait complet à recalculer
    pour 27 personnes ; retirer les seules phrases fautives garde le reste.
  · `persistent_notes` — SUPPRIMÉES. Une note est un bloc titre + contenu
    rédigé comme une consigne, et rendu « **{titre}** : {contenu} » dans
    chaque prompt : en retirer une phrase laisserait un titre « Surnom
    KingsRequin » en gras, ce qui suffit à réapprendre l'étiquette. Le contenu
    intégral est imprimé avant l'effacement — c'est la trace.

Ne sont PAS touchés, et c'est délibéré :

  · `user_aliases` — ils servent à COMPRENDRE qui est désigné (« azra » →
    azraël), pas à nommer. Les purger rendrait Wally incapable de reconnaître
    les gens.
  · `daily_log` — la trace BRUTE de ce que les gens ont dit. Le garde-fou vise
    ce que Wally retient DES GENS, pas ce que le chat a tapé.
  · `cognitive_events` et les faits `wally:self` — sa vie mentale, exemptée au
    même titre que dans `bot.core.surnoms.SUJET_EXEMPT`.

`detecter()` reconnaît le MÉCANISME (« surnommé », « l'appelle X »), jamais un
surnom en particulier — c'est ce qui lui permet d'attraper le prochain. Mais un
surnom DÉJÀ installé se raconte sans marqueur : « Malef a lancé la blague du
petit chevreuil ». D'où `--expression`, qui vise un surnom nommé pour cette
passe-là. Le surnom vit dans la ligne de commande, jamais dans le code.

    python3 scripts/purger_surnoms.py                       # montre, ne touche à rien
    python3 scripts/purger_surnoms.py --expression "petit chevreuil"
    python3 scripts/purger_surnoms.py --appliquer
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.core.surnoms import SUJET_EXEMPT, detecter  # noqa: E402

BASE = Path(__file__).resolve().parent.parent / "data" / "wally.db"

# Une phrase se termine par un point, un point-virgule ou un retour à la ligne.
# Les portraits sont rédigés en prose : découper plus fin couperait au milieu
# d'une énumération et rendrait le texte incompréhensible.
_PHRASE = re.compile(r"[^.;\n]+[.;\n]?")

# Les gisements de PROSE relue vers le prompt : (table, clé, colonnes).
# `topics` part dans les deux handlers (`get_topics(limit=5)`),
# `session_analyses` remonte par le recall cross-session du consolidateur.
_PROSE = (
    ("user_profiles", "user_id", ("portrait",)),
    ("topics", "id", ("summary", "opinion")),
    ("session_analyses", "id", ("summary",)),
)


def _faiseur(expression: str):
    """Rend la fonction « ce texte est-il fautif ? » pour cette passe.

    Deux lectures qui se complètent : le mécanisme, toujours actif, et le
    surnom nommé du jour s'il y en a un.
    """
    motif = re.compile(re.escape(expression), re.I) if expression else None

    def fautif(texte: str, user_id: str | None = None) -> bool:
        if not texte or user_id == SUJET_EXEMPT:
            return False
        return bool(detecter(texte, user_id)) or bool(motif and motif.search(texte))

    return fautif


def _phrases_fautives(texte: str, fautif) -> list[str]:
    return [p for p in _PHRASE.findall(texte or "") if p.strip() and fautif(p)]


def _nettoyer(texte: str, fautives: list[str]) -> str:
    """Retire les phrases fautives et recolle ce qui reste."""
    neuf = texte
    for ph in fautives:
        neuf = neuf.replace(ph, " ")
    # Espaces et ponctuation orpheline laissés par le retrait.
    neuf = re.sub(r"\s{2,}", " ", neuf)
    return re.sub(r"\s+([,.;])", r"\1", neuf).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit vraiment (sans ce drapeau : simple aperçu)")
    ap.add_argument("--expression", default="",
                    help="un surnom NOMMÉ à purger en plus du mécanisme "
                         "(ex. --expression \"petit chevreuil\")")
    ap.add_argument("--sauf", default="",
                    help="lignes à ÉPARGNER, en « table:id » séparés par des "
                         "virgules (ex. persistent_notes:23,session_analyses:51)")
    ap.add_argument("--base", default=str(BASE))
    args = ap.parse_args()

    fautif = _faiseur(args.expression)

    # `detecter()` est réglé pour le point d'ÉCRITURE, où un faux positif ne
    # coûte rien : Wally répond « je n'enregistre pas de surnom » et la
    # conversation continue. Appliqué rétroactivement à une SUPPRESSION, le
    # même faux positif détruit une donnée juste — « Azraël a décidé que ça
    # s'appelle "le journal de Wally" » (une chose, pas une personne), ou
    # « on m'a affublé du surnom X » (Wally lui-même, déjà exempté à
    # l'écriture par `SUJET_EXEMPT`, mais écrit à la première personne dans la
    # prose). D'où ce garde-fou humain : on épargne nommément, on ne desserre
    # pas le détecteur.
    epargnes = {s.strip() for s in args.sauf.split(",") if s.strip()}

    c = sqlite3.connect(args.base)

    # ── 1. les faits ────────────────────────────────────────────────────
    # `superseded` AUSSI, et pas seulement `active` : `UserModeler._refresh_one`
    # nourrit le portrait des deux lots. Ne traiter que les faits actifs
    # laisserait un surnom remonter par la passe de 21 h, sans que rien ne le
    # signale — et le portrait est réinjecté à chaque prompt.
    faits = [
        (fid, uid, txt) for fid, uid, txt, st
        in c.execute("SELECT id, user_id, content, status FROM atomic_facts")
        if st in ("active", "superseded") and fautif(txt or "", uid)
        and f"atomic_facts:{fid}" not in epargnes
    ]
    print(f"FAITS à archiver : {len(faits)}  "
          f"({len({f[1] for f in faits})} personnes)")
    for fid, uid, txt in faits[:60]:
        print(f"  #{fid:<6} [{uid[:24]:24}] {txt[:96].splitlines()[0]}")
    if len(faits) > 60:
        print(f"  … et {len(faits) - 60} de plus")

    # ── 2. les notes persistantes ───────────────────────────────────────
    # Le gisement le plus fort du lot : injecté à TOUTES les conversations,
    # rédigé comme un ordre. C'est celui qui a tenu six jours de plus.
    notes = [
        (nid, titre, contenu)
        for nid, titre, contenu in c.execute(
            "SELECT id, title, content FROM persistent_notes")
        if (fautif(contenu or "") or fautif(titre or ""))
        and f"persistent_notes:{nid}" not in epargnes
    ]
    print(f"\nNOTES PERSISTANTES à supprimer : {len(notes)}")
    for nid, titre, contenu in notes:
        print(f"  #{nid:<4} « {titre} »")
        print(f"        {contenu.strip()[:220]}")

    # ── 3. la prose relue vers le prompt ────────────────────────────────
    proses: list[tuple[str, str, object, str, str, list[str]]] = []
    for table, cle, colonnes in _PROSE:
        for ligne in c.execute(
                f"SELECT {cle}, {', '.join(colonnes)} FROM {table}"):  # noqa: S608 — noms internes
            if f"{table}:{ligne[0]}" in epargnes:
                continue
            for colonne, valeur in zip(colonnes, ligne[1:]):
                fautives = _phrases_fautives(valeur, fautif)
                if fautives:
                    proses.append((table, cle, ligne[0], colonne, valeur, fautives))
    total_phrases = sum(len(p[5]) for p in proses)
    print(f"\nPROSE à nettoyer : {len(proses)} champ(s), "
          f"{total_phrases} phrase(s) retirée(s)")
    for table, _, ident, colonne, _, fautives in proses:
        for ph in fautives:
            print(f"  [{table}.{colonne} {str(ident)[:24]}] − {ph.strip()[:90]}")

    if not args.appliquer:
        print("\n(aperçu seul — relancer avec --appliquer pour écrire)")
        return 0

    # ── 4. l'écriture ───────────────────────────────────────────────────
    for fid, _, _ in faits:
        c.execute("UPDATE atomic_facts SET status='archived' WHERE id=?", (fid,))
    for nid, _, _ in notes:
        c.execute("DELETE FROM persistent_notes WHERE id=?", (nid,))
    nettoyes = 0
    for table, cle, ident, colonne, valeur, fautives in proses:
        neuf = _nettoyer(valeur, fautives)
        if neuf != valeur:
            c.execute(
                f"UPDATE {table} SET {colonne}=? WHERE {cle}=?",  # noqa: S608 — noms internes
                (neuf, ident))
            nettoyes += 1
    c.commit()
    print(f"\n✅ {len(faits)} fait(s) archivé(s), {len(notes)} note(s) supprimée(s), "
          f"{nettoyes} champ(s) de prose réécrit(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
