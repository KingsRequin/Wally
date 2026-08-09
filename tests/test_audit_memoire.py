"""L'audit d'hygiène mémoire doit trouver le motif du 2026-08-09 — sans rien muter.

Deux propriétés comptent :
· il retrouve un désir qui recoupe une capacité déjà livrée (le cas #15265) ;
· il n'écrit RIEN. Un audit qui mute est un ménage déguisé, et sur cette base une
  réconciliation trop zélée a déjà effacé de la mémoire une fois (351aafc).
"""
import sqlite3

import pytest

from scripts.audit_memoire import (
    capacites_livrees,
    desirs_actifs,
    desirs_dates_sans_peremption,
    desirs_deja_livres,
    rapport,
)
from tests.test_selfupgrade_garde_verbosite import DEMANDE_19_LIVREE

# Le désir #15265 tel qu'il était en base le 2026-08-09 — c'est lui qui a relancé la
# demande alors que la capacité existait depuis le 05.
DESIR_15265 = (
    "Recevoir le flux du chat Twitch et les événements Twitch (follows, subs, bits, "
    "raids) en direct pendant les lives, sans le gameplay vidéo. Reformuler un "
    "code_fix propre qui distingue ça de la demande refusée en août ('voir le stream "
    "en direct'). — progression — · Formulé en code_fix propre : flux du chat Twitch "
    "et événements Twitch (sans vidéo), périmètre textuel uniquement, distinct de la "
    "demande refusée d'août."
)


@pytest.fixture()
def base(tmp_path):
    import asyncio

    from bot.db.schema_v2 import create_v2_tables

    chemin = str(tmp_path / "audit.db")
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        create_v2_tables(chemin)
    )
    db = sqlite3.connect(chemin)
    # Textes RÉELS (demande #19 livrée, désir #15265) : tronqués, ils ne pèsent plus
    # assez de vocabulaire commun pour que la mesure ait un sens — c'est la
    # verbosité elle-même qui est en jeu ici.
    db.execute(
        """INSERT INTO pending_upgrades (id, proposal, status, created_at, decided_at, capability)
           VALUES (19, ?, 'delivered', '2026-08-05T03:09', '2026-08-05T03:21', ?)""",
        (DEMANDE_19_LIVREE, "Je vois le chat du live d'Azraël et les événements de sa chaîne."),
    )
    db.execute(
        """INSERT INTO atomic_facts (user_id, content, category, confidence, decay_rate,
                                     status, source, created_at, last_seen_at, support_count)
           VALUES ('wally:self', ?, 'DESIRE', 0.8, 0.02, 'active', 'test',
                   '2026-08-08T08:26', '2026-08-08T08:26', 1)""",
        (DESIR_15265,),
    )
    db.execute(
        """INSERT INTO atomic_facts (user_id, content, category, confidence, decay_rate,
                                     status, source, created_at, last_seen_at, support_count)
           VALUES ('wally:self', 'Lire le blog post Hytale aujourd''hui à 16h', 'DESIRE',
                   0.8, 0.02, 'active', 'test', '2026-07-17T09:00', '2026-07-17T09:00', 1)"""
    )
    db.commit()
    db.close()
    return chemin


def test_il_retrouve_le_desir_qui_recoupe_une_capacite_livree(base):
    db = sqlite3.connect(base)
    db.row_factory = sqlite3.Row
    trouves = desirs_deja_livres(desirs_actifs(db), capacites_livrees(db))
    db.close()

    assert len(trouves) == 1, "le désir #15265 du 2026-08-09 passerait inaperçu"
    desir, demande, _score = trouves[0]
    assert demande["id"] == 19
    assert "chat Twitch" in desir["content"]
    # Sensibilité cadrée par le bas : le désir « blog Hytale » de la même base ne
    # doit PAS être rapproché de la capacité Twitch. Sans cette borne, abaisser le
    # seuil rendrait le rapport illisible et donc inutile.
    assert "Hytale" not in desir["content"]


def test_il_signale_un_desir_date_sans_peremption(base):
    db = sqlite3.connect(base)
    db.row_factory = sqlite3.Row
    signales = desirs_dates_sans_peremption(desirs_actifs(db))
    db.close()

    assert [d["content"] for d in signales] == ["Lire le blog post Hytale aujourd'hui à 16h"]


def test_laudit_nnecrit_rien(base):
    """Ouvert en `mode=ro` : toute tentative d'écriture lèverait."""
    avant = sqlite3.connect(base).execute(
        "SELECT count(*), sum(confidence) FROM atomic_facts"
    ).fetchone()

    texte = "\n".join(rapport(base, age_max=30))

    apres = sqlite3.connect(base).execute(
        "SELECT count(*), sum(confidence) FROM atomic_facts"
    ).fetchone()
    assert avant == apres
    assert "Audit mémoire" in texte
