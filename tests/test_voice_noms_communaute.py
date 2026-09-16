"""Le vocal entend les noms de la communauté, absents compris.

« Bien le bonsoir Kassandre », lancé à une viewer du chat Twitch, sortait
« Cassandra » : elle n'était pas dans le salon, et son pseudo
`kassandreyunikon` ne se prononce pas. La forme parlée vient des alias appris.
"""
import asyncio
from unittest.mock import patch

from bot.discord.voice.noms import (
    charger_noms_communaute,
    choisir_noms,
    forme_parlee,
    termes_de_biais,
)


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
    with patch("bot.discord.voice.service.noms_communaute", return_value=["Kassandre"]):
        assert svc.noms_a_entendre() == ["Azraël", "._.azrael._.", "Kassandre"]


def test_la_composition_est_la_meme_pour_tous_les_moteurs():
    assert termes_de_biais(["Wally", "wally"], lambda: ["Kassandre", "WALLY", ""]) == [
        "Wally", "Kassandre"]


def test_une_source_qui_leve_garde_le_nom_du_bot():
    def _cassee():
        raise RuntimeError("plus de salon")

    assert termes_de_biais(["Wally"], _cassee) == ["Wally"]


def test_le_moteur_local_recoit_les_noms_apres_celui_du_bot():
    """faster-whisper coupe les hotwords en gardant le DÉBUT : le nom de Wally
    doit rester en tête quelle que soit la longueur de la liste."""
    from bot.discord.voice.providers import FasterWhisperSTT

    stt = FasterWhisperSTT(phrases=["Wally"], extra_terms=lambda: ["Kassandre", "Malef"])
    assert stt._hotwords() == "Wally, Kassandre, Malef"


def test_l_instantane_n_est_relu_qu_une_fois_par_heure():
    from bot.discord.voice import noms

    appels = []

    class _DB:
        async def lignes_noms_communaute(self, confiance_min):
            appels.append(1)
            return [{"user_id": "twitch:1", "username": "kassandreyunikon",
                     "nickname": "kassandre", "confidence": 1.0}]

    with patch.object(noms, "_lu_a", None), patch.object(noms, "_instantane", []):
        asyncio.run(noms.rafraichir_noms_communaute(_DB()))
        asyncio.run(noms.rafraichir_noms_communaute(_DB()))
        assert noms.noms_communaute() == ["Kassandreyunikon", "Kassandre"]
    assert len(appels) == 1


class _Jetons:
    """Un jeton par caractère non séparateur : assez pour tester le budget."""

    class _Enc:
        def __init__(self, n):
            self.ids = [0] * n

    def encode(self, texte, add_special_tokens=False):
        return self._Enc(len(texte.replace(", ", "")))


class _Modele:
    max_length = 40  # budget = 19 jetons
    hf_tokenizer = _Jetons()


def test_wally_encadre_les_noms_qui_tiennent_dans_le_budget():
    """Mesuré : Wally + liste coupée par la bibliothèque = 7/8 appels entendus ;
    Wally + ce qui tient + Wally = 8/8, avec les mêmes 6/6 noms."""
    from bot.discord.voice.providers import FasterWhisperSTT

    stt = FasterWhisperSTT(phrases=["Wally"],
                           extra_terms=lambda: ["Kassandre", "Malef", "Keychka"])
    # 19 − 2×5 (Wally) − 1 = 8 : « Kassandre » (9) ne tient pas, rien ne passe
    # devant lui — l'ordre d'activité n'est jamais sauté.
    assert stt._hotwords(_Modele()) == "Wally"
    stt = FasterWhisperSTT(phrases=["Wally"], extra_terms=lambda: ["Malef", "Keychka"])
    assert stt._hotwords(_Modele()) == "Wally, Malef, Wally"


def test_sans_noms_le_nom_seul_reste_tel_qu_il_a_ete_mesure():
    from bot.discord.voice.providers import FasterWhisperSTT

    assert FasterWhisperSTT(phrases=["Wally"])._hotwords(_Modele()) == "Wally"
