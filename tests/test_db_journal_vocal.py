"""Le registre des cartes du journal vocal (`bot/db/mixins/journal_vocal.py`)."""
from bot.db.database import Database

LOGS1, LOGS2 = 70, 71


async def test_aucune_carte_par_defaut(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        assert await db.cartes_vocales(777) == []
    finally:
        await db.close()


async def test_carte_vocale_ajouter_et_lecture(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        await db.carte_vocale_ajouter(777, LOGS1, 999, 42, [42])
        cartes = await db.cartes_vocales(777)
        assert len(cartes) == 1
        carte = cartes[0]
        assert carte["log_salon_id"] == LOGS1
        assert carte["message_id"] == 999
        assert carte["createur_id"] == 42
        assert carte["participants"] == [42]
        assert isinstance(carte["cree_a"], float) and carte["cree_a"] > 0
    finally:
        await db.close()


async def test_une_carte_par_salon_de_logs(tmp_path):
    """Autant de lignes que de salons de logs configurés : chacun a SA carte."""
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        await db.carte_vocale_ajouter(777, LOGS1, 100, 42, [42])
        await db.carte_vocale_ajouter(777, LOGS2, 200, 42, [42])
        cartes = await db.cartes_vocales(777)
        assert {c["log_salon_id"] for c in cartes} == {LOGS1, LOGS2}
    finally:
        await db.close()


async def test_participant_ajoute_a_toutes_les_cartes_du_salon(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        await db.carte_vocale_ajouter(777, LOGS1, 100, 42, [42])
        await db.carte_vocale_ajouter(777, LOGS2, 200, 42, [42])
        await db.carte_vocale_participant_ajouter(777, 1)
        cartes = await db.cartes_vocales(777)
        assert all(set(c["participants"]) == {42, 1} for c in cartes)
    finally:
        await db.close()


async def test_participant_ajoute_idempotent(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        await db.carte_vocale_ajouter(777, LOGS1, 100, 42, [42])
        await db.carte_vocale_participant_ajouter(777, 1)
        await db.carte_vocale_participant_ajouter(777, 1)
        carte = (await db.cartes_vocales(777))[0]
        assert carte["participants"] == [42, 1]
    finally:
        await db.close()


async def test_participant_sans_carte_ne_fait_rien(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        await db.carte_vocale_participant_ajouter(777, 1)   # aucune ligne : silencieux
        assert await db.cartes_vocales(777) == []
    finally:
        await db.close()


async def test_cartes_vocales_supprimer(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        await db.carte_vocale_ajouter(777, LOGS1, 100, 42, [42])
        await db.carte_vocale_ajouter(888, LOGS1, 300, 1, [1])
        await db.cartes_vocales_supprimer(777)
        assert await db.cartes_vocales(777) == []
        assert len(await db.cartes_vocales(888)) == 1   # l'autre salon n'est pas touché
    finally:
        await db.close()


async def test_carte_vocale_ajouter_remplace_la_meme_carte(tmp_path):
    """`INSERT OR REPLACE` : rejouer la création (retry) ne duplique pas la ligne."""
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        await db.carte_vocale_ajouter(777, LOGS1, 100, 42, [42])
        await db.carte_vocale_ajouter(777, LOGS1, 101, 42, [42])
        cartes = await db.cartes_vocales(777)
        assert len(cartes) == 1
        assert cartes[0]["message_id"] == 101
    finally:
        await db.close()


async def test_salons_temp_avec_carte(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        assert await db.salons_temp_avec_carte() == set()
        await db.carte_vocale_ajouter(777, LOGS1, 100, 42, [42])
        await db.carte_vocale_ajouter(777, LOGS2, 200, 42, [42])   # même salon, autre log
        await db.carte_vocale_ajouter(888, LOGS1, 300, 1, [1])
        assert await db.salons_temp_avec_carte() == {777, 888}
        await db.cartes_vocales_supprimer(777)
        assert await db.salons_temp_avec_carte() == {888}
    finally:
        await db.close()


async def test_participants_stockes_plafonnes(tmp_path):
    """Au-delà de 500, les nouveaux arrivants ne sont plus ajoutés à la
    colonne — les premiers sont gardés, la ligne ne grossit pas pour toujours."""
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        deja_500 = list(range(500))
        await db.carte_vocale_ajouter(777, LOGS1, 100, 42, deja_500)
        carte = (await db.cartes_vocales(777))[0]
        assert len(carte["participants"]) == 500
        assert carte["participants"] == deja_500

        await db.carte_vocale_participant_ajouter(777, 999999)   # le 501e : refusé

        carte = (await db.cartes_vocales(777))[0]
        assert len(carte["participants"]) == 500
        assert 999999 not in carte["participants"]
    finally:
        await db.close()


async def test_carte_vocale_ajouter_plafonne_la_liste_initiale(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        trop = list(range(600))
        await db.carte_vocale_ajouter(777, LOGS1, 100, 42, trop)
        carte = (await db.cartes_vocales(777))[0]
        assert len(carte["participants"]) == 500
        assert carte["participants"] == trop[:500]
    finally:
        await db.close()
