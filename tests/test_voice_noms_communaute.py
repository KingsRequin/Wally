"""Le vocal entend les noms de la communauté, absents compris.

« Bien le bonsoir Kassandre », lancé à une viewer du chat Twitch, sortait
« Cassandra » : elle n'était pas dans le salon, et son pseudo
`kassandreyunikon` ne se prononce pas. La forme parlée vient des alias appris.
"""
import asyncio

from bot.discord.voice.noms import charger_noms_communaute, choisir_noms, forme_parlee


def test_le_surnom_parle_accompagne_le_pseudo():
    lignes = [("twitch:1", "kassandreyunikon", "kassandre", 1.0)]
    assert choisir_noms(lignes) == ["Kassandreyunikon", "Kassandre"]


def test_un_alias_peu_sur_n_entre_pas():
    lignes = [("twitch:1", "Malef__", "moulouf", 0.8)]
    assert choisir_noms(lignes) == ["Malef"]


def test_les_identifiants_et_les_intonations_ne_sont_pas_des_noms():
    assert forme_parlee("Malef__") == "Malef"
    assert forme_parlee("@xeforce_") == "Xeforce"
    assert forme_parlee("requiiiiiin") is None
    assert forme_parlee("OMG PLS JOUEZ AVK MWAA") is None
    assert forme_parlee("snorkiz7") == "Snorkiz"
    assert forme_parlee(":@") is None
    assert forme_parlee(None) is None


def test_la_casse_d_origine_est_gardee():
    assert forme_parlee("ClakerNoJutsu") == "ClakerNoJutsu"
    assert forme_parlee("iron d'aile") == "Iron d'aile"


def test_deux_formes_par_personne_au_plus_pour_ne_pas_evincer_les_autres():
    lignes = [("discord:1", "Azraël", a, 1.0) for a in ("azrael", "zazrael", "azra", "tonton az")]
    lignes.append(("discord:2", "Rina", None, None))
    assert choisir_noms(lignes) == ["Azraël", "Azrael", "Rina"]


def test_l_ordre_d_activite_est_conserve_et_les_doublons_retires():
    lignes = [("twitch:9", "oyoloyoo", "oyo", 1.0), ("discord:3", "Oyoloyoo", None, None)]
    assert choisir_noms(lignes) == ["Oyoloyoo", "Oyo"]


def test_une_base_qui_leve_ne_coute_pas_le_join():
    class _DB:
        async def lignes_noms_communaute(self, confiance_min):
            raise RuntimeError("database is locked")

    assert asyncio.run(charger_noms_communaute(_DB())) == []
    assert asyncio.run(charger_noms_communaute(None)) == []


def test_la_requete_rend_les_alias_surs_des_personnes_connues(tmp_path):
    from bot.db.database import Database

    async def _run():
        db = await Database.create(str(tmp_path / "t.db"))
        try:
            await db.upsert_memory_user("twitch:90774597", "twitch", "kassandreyunikon")
            await db.execute("UPDATE memory_users SET memory_count = 25")
            await db.execute(
                "INSERT INTO user_aliases(nickname, canonical_uid, display_name, source, confidence, created_at)"
                " VALUES ('kassandre', 'twitch:90774597', 'kassandre', 'llm', 1.0, 0),"
                "        ('licornekssandre', 'twitch:90774597', 'kassandre', 'llm', 0.8, 0)")
            return await charger_noms_communaute(db)
        finally:
            await db.close()

    assert asyncio.run(_run()) == ["Kassandreyunikon", "Kassandre"]


def test_le_service_passe_le_salon_avant_la_communaute():
    from bot.discord.voice.service import VoiceService

    class _M:
        def __init__(self, d, n):
            self.display_name, self.name, self.bot = d, n, False

    svc = VoiceService.__new__(VoiceService)
    svc._channel = type("C", (), {"members": [_M("Azraël", "._.azrael._.")]})()
    svc._noms_communaute = ["Kassandre"]
    assert svc.noms_a_entendre() == ["Azraël", "._.azrael._.", "Kassandre"]
