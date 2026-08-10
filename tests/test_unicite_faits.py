"""Deux fois le même souvenir, mot pour mot, ne doit pas pouvoir exister.

Relevé le 2026-08-10 en production : onze faits actifs portaient un contenu
strictement identique à un autre, chez la même personne et dans la même
catégorie. Deux copies mot pour mot de la même opinion, créées à treize minutes
d'écart, vivaient côte à côte depuis le 3 juillet.

Le ménage nocturne existait pourtant et tournait. Mais il fait trancher les
doublons par le LLM, par lots de 25 pris parmi les 150 plus anciens d'UNE
personne par nuit : deux copies tombées dans deux lots différents ne se croisent
jamais, et pour `wally:self` (2 039 souvenirs) la plupart des lots ne sont
jamais examinés. Or deux textes identiques n'ont besoin d'aucun arbitrage.

Deux mécanismes, deux rôles :
  · `merge_exact_duplicates()` replie ce qui existe déjà, sans LLM, sur tout le
    monde ;
  · `idx_facts_actif_unique` empêche d'en créer un nouveau, y compris quand deux
    ingests concurrents passent tous deux le test d'existence avant que l'un
    n'ait inséré — la course que le verrou applicatif ne couvre pas.
"""
import pytest

from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.memory.facts import (
    AtomicFact,
    FactCategory,
    FactStatus,
    SQLiteFactStore,
)


async def _store(tmp_path):
    chemin = str(tmp_path / "faits.db")
    await create_v2_tables(chemin)
    return SQLiteFactStore(chemin), chemin


def _fait(contenu="Taki est étudiant en master", user="discord:1", **kw):
    return AtomicFact(
        user_id=user, content=contenu, category=FactCategory.FAIT, **kw
    )


async def _actifs(store, user="discord:1"):
    return await store.get_by_user(user, min_confidence=0.0)


@pytest.mark.asyncio
async def test_deux_copies_identiques_sont_repliees_en_une(tmp_path):
    store, chemin = await _store(tmp_path)
    # On contourne `add()` pour fabriquer l'état RÉEL trouvé en production :
    # deux lignes actives identiques, nées avant que l'unicité existe.
    import sqlite3
    c = sqlite3.connect(chemin)
    c.execute("DROP INDEX IF EXISTS idx_facts_actif_unique")
    c.commit()
    c.close()

    a = await store.add(_fait())
    b = await store.add(_fait())
    assert a != b, "préparation : il faut bien deux lignes distinctes"

    replies = await store.merge_exact_duplicates()

    assert replies == 1
    restants = await _actifs(store)
    assert len(restants) == 1
    assert restants[0].id == a, "le plus ancien est gardé — il porte l'antériorité"


@pytest.mark.asyncio
async def test_le_repli_cumule_le_credit_des_copies(tmp_path):
    """Replier ne doit pas jeter ce que les copies avaient accumulé."""
    store, chemin = await _store(tmp_path)
    import sqlite3
    c = sqlite3.connect(chemin)
    c.execute("DROP INDEX IF EXISTS idx_facts_actif_unique")
    c.commit()
    c.close()

    a = await store.add(_fait(support_count=3, confidence=0.6))
    await store.add(_fait(support_count=4, confidence=0.9))

    await store.merge_exact_duplicates()

    garde = (await _actifs(store))[0]
    assert garde.id == a
    assert garde.support_count == 7, "les appuis des deux copies s'additionnent"
    assert garde.confidence == pytest.approx(0.9), "on garde la confiance la plus haute"


@pytest.mark.asyncio
async def test_le_repli_ne_touche_pas_deux_faits_differents(tmp_path):
    store, _ = await _store(tmp_path)
    await store.add(_fait("Taki est étudiant en master"))
    await store.add(_fait("Taki habite à Lyon"))

    assert await store.merge_exact_duplicates() == 0
    assert len(await _actifs(store)) == 2


@pytest.mark.asyncio
async def test_le_repli_ne_confond_pas_deux_personnes(tmp_path):
    """Le même texte chez deux personnes reste deux souvenirs."""
    store, _ = await _store(tmp_path)
    await store.add(_fait(user="discord:1"))
    await store.add(_fait(user="discord:2"))

    assert await store.merge_exact_duplicates() == 0
    assert len(await _actifs(store, "discord:1")) == 1
    assert len(await _actifs(store, "discord:2")) == 1


@pytest.mark.asyncio
async def test_un_doublon_insere_en_course_renforce_au_lieu_de_lever(tmp_path):
    """La course que le verrou applicatif ne couvre pas.

    Deux ingests concurrents peuvent passer `find_same_content()` avant que l'un
    n'ait inséré. L'index unique attrape le second — et `add()` doit traiter ce
    conflit pour ce qu'il est : « ce souvenir existe déjà », pas une panne.
    """
    store, _ = await _store(tmp_path)
    premier = await store.add(_fait())

    second = await store.add(_fait())          # ne doit PAS lever

    assert second == premier, "le doublon renvoie l'id du fait déjà présent"
    restants = await _actifs(store)
    assert len(restants) == 1
    assert restants[0].support_count == 2, "le fait existant a été renforcé"


@pytest.mark.asyncio
async def test_la_casse_et_les_espaces_ne_creent_pas_un_doublon(tmp_path):
    store, _ = await _store(tmp_path)
    premier = await store.add(_fait("Taki est étudiant en master"))

    second = await store.add(_fait("  taki est étudiant en master  "))

    assert second == premier
    assert len(await _actifs(store)) == 1


@pytest.mark.asyncio
async def test_une_apostrophe_nempeche_pas_de_reconnaitre_un_doublon(tmp_path):
    """Le pré-filtre par longueur ne doit pas rater ce que la normalisation raccourcit.

    `_normalize` retire la ponctuation : « Tenir un but jusqu'au bout » (26
    caractères) devient « tenir un but jusquau bout » (25). Le filtre SQL
    cherchait `length(content) = 25` et ne trouvait donc jamais la ligne de
    longueur 26 — c'est-à-dire la sienne. Toute phrase ponctuée échappait à la
    dédup live, soit la quasi-totalité d'entre elles.
    """
    store, _ = await _store(tmp_path)
    texte = "Tenir un but jusqu'au bout"
    premier = await store.add(_fait(texte))

    from bot.intelligence.memory.facts import _normalize
    assert len(_normalize(texte)) < len(texte), "préparation : la normalisation raccourcit"

    trouve = await store.find_same_content(
        "discord:1", FactCategory.FAIT, _normalize(texte)
    )
    assert trouve == premier, "le fait ne se reconnaît pas lui-même"


@pytest.mark.asyncio
async def test_reactiver_un_fait_en_conflit_ne_leve_pas(tmp_path):
    """Le panel admin et l'outil `doubt_memory` réactivent des faits archivés."""
    store, _ = await _store(tmp_path)
    a = await store.add(_fait())
    await store.set_status(a, FactStatus.ARCHIVED)
    b = await store.add(_fait())               # l'archivage libère la place
    assert b != a

    await store.set_status(a, FactStatus.ACTIVE)   # ne doit PAS lever

    actifs = await _actifs(store)
    assert len(actifs) == 1, "le jumeau reste archivé, il n'y a toujours qu'un actif"
    assert actifs[0].id == b


@pytest.mark.asyncio
async def test_corriger_un_contenu_vers_un_doublon_est_refuse_proprement(tmp_path):
    store, _ = await _store(tmp_path)
    await store.add(_fait("Taki est étudiant en master"))
    b = await store.add(_fait("Taki habite à Lyon"))

    ok = await store.update_content(b, "Taki est étudiant en master")

    assert ok is False, "l'appelant doit pouvoir afficher l'échec"
    contenus = {f.content for f in await _actifs(store)}
    assert contenus == {"Taki est étudiant en master", "Taki habite à Lyon"}


@pytest.mark.asyncio
async def test_le_menage_nocturne_replie_les_doublons_de_tout_le_monde(tmp_path):
    """Le tri LLM ne voit qu'une personne par nuit. Le repli exact, tout le monde."""
    import inspect

    from bot.intelligence.journal import DailyJournal

    src = inspect.getsource(DailyJournal.run_memory_cleanup)
    assert "merge_exact_duplicates()" in src
    # Sans argument : la portée est globale, pas la personne du soir.
    assert "merge_exact_duplicates(self" not in src
