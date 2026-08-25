"""Wally appelle les gens par leur pseudo, et rien d'autre.

Le 2026-08-25, l'owner constate que des viewers apprennent à Wally à désigner
les autres par des surnoms. La base en portait 50 actifs : « mks_zedd est
surnommé Zeddo », « clakernojutsu l'appelle controllerhater », « surnomme
KingsRequin petit chevreuil » — et 27 portraits, qui sont réinjectés à CHAQUE
prompt et battent n'importe quelle consigne.

Un surnom collé par un tiers n'est pas un fait sur la personne : c'est une
étiquette qu'elle n'a pas choisie, et Wally la portait devant tout un live.

Les phrases de ces tests sont des VRAIES lignes de la base de production.
"""
import pytest

from bot.core.surnoms import REFUS, detecter


# ── ce qui doit être REFUSÉ (lignes réelles de la base) ────────────────
@pytest.mark.parametrize("texte", [
    "mks_zedd est surnommé Zeddo",
    "dovaest est lié à malef__ : amical, surnomme Malouf",
    "clakernojutsu est lié à taki_gano : le charrie, l'appelle controllerhater",
    "clakernojutsu est lié à taki_gano : le surnomme best aim assist player",
    "skcordam est lié à Azrael : aime l'appeler Jean-Robert",
    "kingsrequin est lié à kassandreyunikon : appelle 'princesse'",
    "temcox_fps est surnommé Tempo",
    "rrina_t aime aussi se faire appeler « prédatrice »",
    "Aime taquiner Wally avec des surnoms affectueux, notamment 'la fourmis'",
    "salah1005 aime surnommer Wally affectueusement (chaton)",
])
def test_un_surnom_ne_rentre_pas(texte):
    assert detecter(texte, "discord:1") is not None, (
        f"« {texte} » a passé le garde — Wally réapprendra le surnom en base"
    )


def test_l_apostrophe_TYPOGRAPHIQUE_ne_passe_pas_a_travers():
    """Le LLM écrit « l’appelle » (U+2019) au moins aussi souvent que « l'appelle ».

    Sans normalisation, la moitié des cas franchissaient le garde en silence :
    un garde-fou qui rate un cas sur deux vaut à peine mieux que rien.
    """
    droite = "clakernojutsu l'appelle controllerhater"
    typo = "clakernojutsu l’appelle controllerhater"
    assert detecter(droite, "discord:1") is not None
    assert detecter(typo, "discord:1") is not None


# ── ce qui doit PASSER ─────────────────────────────────────────────────
@pytest.mark.parametrize("texte", [
    # L'exception qui compte : réclamer son vrai pseudo, c'est REFUSER une
    # étiquette. Effacer ce fait ferait redécouvrir la question à chaque fois.
    "temcox_fps préfère qu'on l'appelle par son vrai pseudo « temcox_fps » "
    "plutôt que par le surnom « Tempo »",
    "préfère être appelé par son vrai pseudo plutôt que par un surnom",
    "Semble sensible aux surnoms potentiellement péjoratifs",
    # « appeler » au sens de SOLLICITER n'a rien à voir avec nommer.
    "ha0r veut être appelé pour jouer à Warhammer",
    "Appelle-moi quand le live commence",
    # Et le tout-venant, qui ne doit surtout pas être happé.
    "Azraël joue à Apex tous les soirs et vise le Prédateur",
    "kassandreyunikon adore les chats noirs",
])
def test_ce_qui_n_est_pas_un_surnom_passe(texte):
    assert detecter(texte, "discord:1") is None, (
        f"« {texte} » a été refusé à tort — un fait légitime est perdu"
    )


def test_les_pensees_de_wally_ne_sont_PAS_filtrees():
    """Le garde vise ce que Wally retient DES GENS.

    Lui interdire d'y penser lui interdirait aussi de penser « je n'utilise pas
    de surnoms » — et 286 de ses pensées en base parlent déjà de la question.
    """
    pensee = "On me montre une amorce à partir du souvenir « KingsRequin appelle Wally 'mon Wally' »"
    assert detecter(pensee, "wally:self") is None
    assert detecter(pensee, "discord:610550333042589752") is not None


def test_le_refus_ORIENTE_au_lieu_de_claquer_la_porte():
    """Quelqu'un qui propose « appelle-moi Tempo » ne tente rien de louche.

    Même règle que le refus de pilotage de la musique : le message dit à Wally
    quoi en faire, sinon il répond par un « non » plat.
    """
    assert "pseudo" in REFUS
    assert "drame" in REFUS or "simplement" in REFUS


# ── le refus mord-il au POINT D'ÉCRITURE ? ─────────────────────────────
@pytest.mark.asyncio
async def test_un_surnom_n_atteint_JAMAIS_la_base(tmp_path):
    """Le garde est posé sur `SQLiteFactStore.add` — le point d'écriture unique.

    Tout ce qui écrit un fait y passe : `memory.add()`, l'outil du chat, la
    réconciliation du `fact_extractor`. Le poser plus haut laisserait un chemin
    ouvert, et c'est exactement comme ça que 50 surnoms sont entrés.
    """
    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.memory.facts import (
        AtomicFact, FactCategory, SQLiteFactStore,
    )

    chemin = str(tmp_path / "s.db")
    await create_v2_tables(chemin)
    store = SQLiteFactStore(chemin)

    async def ajouter(texte, uid="discord:1"):
        return await store.add(
            AtomicFact(user_id=uid, content=texte, category=FactCategory.PREF)
        )

    # 0 : aucun id valide, l'AUTOINCREMENT part à 1.
    assert await ajouter("mks_zedd est surnommé Zeddo") == 0
    assert await ajouter("clakernojutsu l'appelle controllerhater") == 0
    # Ce qui n'est pas un surnom entre normalement.
    assert await ajouter("Azraël joue à Apex tous les soirs") > 0
    # La vie mentale de Wally n'est pas concernée.
    assert await ajouter("je repense au surnom qu'on m'a donné", "wally:self") > 0

    restants = await store.get_by_user("discord:1")
    assert all("Zeddo" not in f.content for f in restants)


@pytest.mark.asyncio
async def test_un_remplacement_refuse_ne_CASSE_pas_la_chaine(tmp_path):
    """`_supersede` gardait l'id rendu par `add`.

    Un `supersede(ancien, 0)` marquerait l'ancien comme remplacé par un fait
    inexistant : le souvenir disparaîtrait des deux côtés.
    """
    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.memory.facts import (
        AtomicFact, FactCategory, SQLiteFactStore,
    )

    chemin = str(tmp_path / "r.db")
    await create_v2_tables(chemin)
    store = SQLiteFactStore(chemin)
    ancien = await store.add(AtomicFact(
        user_id="discord:1", content="Azraël stream le matin",
        category=FactCategory.PREF))
    assert ancien > 0

    from bot.intelligence.memory.ingest import MemoryIngest
    ingest = MemoryIngest.__new__(MemoryIngest)
    ingest._store = store
    ingest._make_fact = lambda cand, uid, st: AtomicFact(
        user_id=uid, content="Azraël est surnommé Azra", category=FactCategory.PREF)

    vieux = (await store.get_by_user("discord:1"))[0]
    rendu = await ingest._supersede(vieux, object(), "discord:1")

    # L'ancien survit, et n'a pas été marqué remplacé par un fantôme.
    encore = await store.get_by_user("discord:1")
    assert [f.content for f in encore] == ["Azraël stream le matin"]
    assert rendu.content == "Azraël stream le matin"
