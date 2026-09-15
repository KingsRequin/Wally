from bot.db.database import Database


async def test_registre_des_salons_temporaires(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    try:
        assert await db.salons_temporaires() == set()
        await db.salon_temporaire_ajouter(111, 9)
        await db.salon_temporaire_ajouter(111, 9)   # idempotent
        await db.salon_temporaire_ajouter(222, 9)
        assert await db.salons_temporaires() == {111, 222}
        await db.salon_temporaire_retirer(111)
        await db.salon_temporaire_retirer(333)      # absent : sans erreur
        assert await db.salons_temporaires() == {222}
    finally:
        await db.close()
