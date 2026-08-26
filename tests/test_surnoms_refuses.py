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
import json

import pytest

from bot.core.surnoms import REFUS, detecter, expurger


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


# ── la note persistante, l'autre porte d'entrée ────────────────────────
class _FauxDB:
    """Ne retient que ce qu'on a VRAIMENT écrit — c'est tout l'enjeu."""

    def __init__(self):
        self.ecrites = []

    async def upsert_persistent_note(self, titre, contenu):
        self.ecrites.append((titre, contenu))


@pytest.mark.asyncio
async def test_une_note_persistante_n_enseigne_pas_de_surnom():
    """Le trou par lequel « petit chevreuil » a tenu six jours de plus.

    Le garde du 2026-08-25 couvrait `save_user_memory` et l'écriture des
    faits. `save_persistent_note` n'était gardé NULLE PART, sur aucune des
    trois plateformes — et son contenu part dans TOUTES les conversations.
    La note ci-dessous est la vraie ligne de production (`persistent_notes`
    n° 30, écrite le 2026-08-20) : elle donnait un ORDRE, réinjecté à chaque
    appel, et il battait la consigne du prompt.
    """
    from bot.core.notes_tool import run_save_note_tool

    db = _FauxDB()
    rendu = json.loads(await run_save_note_tool(db, {
        "title": "Surnom KingsRequin",
        "content": (
            "KingsRequin tient à être appelé « petit chevreuil » — surnom demandé "
            "par la communauté (malef__ a demandé à Wally de l'utiliser). "
            "À employer pour désigner KingsRequin."
        ),
    }))

    assert rendu["status"] == "denied"
    assert rendu["message"] == REFUS
    assert db.ecrites == []


@pytest.mark.asyncio
async def test_le_TITRE_de_la_note_est_garde_lui_aussi():
    """Le prompt rend « **{titre}** : {contenu} » — le titre part avec.

    Ne filtrer que le contenu laisserait « Surnom de KingsRequin » s'afficher
    en gras dans chaque prompt, ce qui suffit à réapprendre l'étiquette.
    """
    from bot.core.notes_tool import run_save_note_tool

    db = _FauxDB()
    rendu = json.loads(await run_save_note_tool(db, {
        "title": "Le surnom de KingsRequin",
        "content": "Il aime bien les animaux de la forêt.",
    }))

    assert rendu["status"] == "denied"
    assert db.ecrites == []


@pytest.mark.asyncio
async def test_une_note_ordinaire_passe():
    """Le garde ne doit pas fermer l'outil : la plupart des notes sont légitimes."""
    from bot.core.notes_tool import run_save_note_tool

    db = _FauxDB()
    rendu = json.loads(await run_save_note_tool(db, {
        "title": "Horaire du stream",
        "content": "Azraël lance son live vers 9 h en semaine.",
    }))

    assert rendu["status"] == "ok"
    assert db.ecrites == [("Horaire du stream", "Azraël lance son live vers 9 h en semaine.")]


@pytest.mark.asyncio
async def test_un_champ_manquant_rend_une_erreur_DITE():
    """Comportement déjà acquis, préservé par l'extraction.

    `required` au schéma ne garantit rien : un champ omis levait un KeyError
    au milieu de `complete_with_tools`, et Wally annonçait « c'est noté » sans
    rien avoir noté.
    """
    from bot.core.notes_tool import run_save_note_tool

    db = _FauxDB()
    rendu = json.loads(await run_save_note_tool(db, {"title": "Sans contenu"}))

    assert rendu["status"] == "error"
    assert db.ecrites == []


# ── la PROSE relue vers le prompt ──────────────────────────────────────
def test_expurger_retire_la_phrase_fautive_et_garde_le_reste():
    """Phrase à phrase, jamais tout ou rien.

    Un résumé de journée qui mentionne un surnom au milieu de dix autres
    choses ne doit pas disparaître en entier : on perdrait la mémoire de la
    journée pour une incise.
    """
    texte = (
        "clakernojutsu a salué le retour de Wally après son absence. "
        "Le surnom 'petit chevreuil' a provoqué une réaction de KingsRequin. "
        "L'ambiance est restée bon enfant."
    )
    neuf = expurger(texte)

    assert "chevreuil" not in neuf
    assert "clakernojutsu a salué le retour" in neuf
    assert "L'ambiance est restée bon enfant" in neuf


def test_expurger_ne_touche_pas_un_texte_sain():
    """L'identité stricte : rien à réécrire, rien de réécrit."""
    texte = "Azraël stream le matin. Il joue Fuse et Seer."
    assert expurger(texte) == texte


def test_expurger_encaisse_le_vide():
    assert expurger("") == ""
    assert expurger(None) == ""


@pytest.mark.asyncio
async def test_la_passe_de_21h_ne_peut_pas_REINTRODUIRE_un_surnom(tmp_path):
    """Le chat BRUT (`daily_log`) garde le surnom — c'est ce que les gens ont dit.

    `_form_topics` et le résumé de session le relisent chaque soir. Sans garde
    au point d'écriture, la passe de 21 h réécrirait le soir même ce que la
    purge venait d'effacer, et personne ne le verrait avant le live suivant.
    """
    from bot.db.database import Database
    from bot.db.schema_v2 import create_v2_tables

    chemin = str(tmp_path / "p.db")
    await create_v2_tables(chemin)
    db = await Database.create(chemin)
    try:
        sale = ("Grosse ambiance ce soir. "
                "Wally confirme que le surnom de KingsRequin est 'petit chevreuil'. "
                "On a fini sur un sondage.")

        await db.upsert_topic("soirée", sale, [], "Bonne soirée.")
        await db.insert_session_analysis("s1", "twitch", "c1", sale)
        await db.upsert_user_profile("twitch:1", sale)

        # Deux fois : la seconde passe par la branche UPDATE d'`upsert_topic`,
        # qui est un point d'écriture À PART — le test l'a attrapée à vide.
        await db.upsert_topic("soirée", sale, [], "Bonne soirée.")

        topics = await db.get_topics(limit=5)
        assert "chevreuil" not in topics[0]["summary"]
        assert "Grosse ambiance ce soir" in topics[0]["summary"]

        resumes = await db.get_recent_session_summaries("twitch", "c1")
        assert "chevreuil" not in resumes[0]["summary"]

        portrait = await db.get_user_profile("twitch:1")
        assert "chevreuil" not in portrait
        assert "On a fini sur un sondage" in portrait
    finally:
        await db.close()
