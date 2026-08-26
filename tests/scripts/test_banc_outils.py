"""Le banc d'outils doit rester un instrument HONNÊTE.

Sa conclusion ne vaut que si les deux variantes qu'il compare ne diffèrent QUE
par les distracteurs. Deux dérives silencieuses la ruineraient :

  • un outil du noyau renommé ou supprimé — le réduit perdrait un outil que les
    cas attendent, et le banc conclurait « le complet fait mieux » alors qu'il
    aurait simplement comparé deux catalogues différents. C'est arrivé pendant
    la construction : `show_last_clip` avait été renommé `show_clip` des mois
    plus tôt, et le noyau le réclamait encore ;
  • un cas qui attend un outil hors du noyau — l'outil serait absent du réduit,
    et le cas y échouerait par construction.

Ces tests ne lancent AUCUN appel LLM.
"""
import asyncio
import json

from scripts.banc_outils import CAS, NOYAU, Cas, Tour, _construire_outils, _verdict


def _catalogue() -> tuple[list[dict], list[dict]]:
    return asyncio.run(_construire_outils())


def test_le_noyau_existe_vraiment_dans_le_catalogue():
    complet, _ = _catalogue()
    noms = {t["function"]["name"] for t in complet}
    assert not (NOYAU - noms), (
        f"Outils du noyau absents du catalogue : {sorted(NOYAU - noms)}. "
        "Un renommage a eu lieu — corrige NOYAU, sinon le banc compare deux "
        "ensembles qui n'ont pas les mêmes outils attendus."
    )


def test_chaque_cas_attend_un_outil_present_dans_les_deux_variantes():
    _, reduit = _catalogue()
    dispo = {t["function"]["name"] for t in reduit}
    for cas in CAS:
        assert cas.attendu <= dispo, (
            f"« {cas.message} » attend {sorted(cas.attendu - dispo)}, absent du "
            "réduit : ce cas y échouerait par construction."
        )


def test_le_reduit_est_un_sous_ensemble_strict_du_complet():
    complet, reduit = _catalogue()
    noms_c = {t["function"]["name"] for t in complet}
    noms_r = {t["function"]["name"] for t in reduit}
    assert noms_r < noms_c
    assert len(noms_c) - len(noms_r) >= 10, (
        "Moins de dix distracteurs : le banc n'aurait plus grand-chose à mesurer."
    )


def test_les_specs_du_reduit_sont_les_memes_objets_que_dans_le_complet():
    """Aucune spec ne doit être reformulée entre les deux variantes.

    Si le réduit portait des descriptions allégées, on mesurerait deux facteurs
    à la fois — le nombre d'outils ET leur rédaction — et l'écart ne serait plus
    attribuable à rien.
    """
    complet, reduit = _catalogue()
    par_nom = {t["function"]["name"]: t for t in complet}
    for spec in reduit:
        nom = spec["function"]["name"]
        assert json.dumps(spec, sort_keys=True) == json.dumps(par_nom[nom],
                                                              sort_keys=True)


def test_le_jeu_de_cas_garde_des_negatifs():
    """Sans cas négatifs, le banc récompenserait le réflexe d'appeler un outil.

    C'est précisément le défaut que la surcharge produit en premier.
    """
    negatifs = [c for c in CAS if not c.attendu]
    assert len(negatifs) >= 8
    assert len(negatifs) >= len(CAS) // 4


def _tour(attendu: set[str], appeles: list[str]) -> Tour:
    return Tour(Cas("peu importe", attendu), "reduit", appeles, 0.0, "")


def test_verdict_distingue_les_quatre_issues():
    assert _verdict(_tour({"show_overlay"}, ["show_overlay"])) == "juste"
    assert _verdict(_tour({"show_overlay"}, ["apex_legends"])) == "mauvais_outil"
    assert _verdict(_tour({"show_overlay"}, [])) == "outil_manquant"
    assert _verdict(_tour(set(), [])) == "juste"
    assert _verdict(_tour(set(), ["show_overlay"])) == "faux_appel"


def test_un_outil_attendu_parmi_plusieurs_appels_compte_juste():
    """Wally enchaîne lecture puis affichage : le trouver dans la séquence suffit."""
    assert _verdict(_tour({"show_apex"}, ["apex_legends", "show_apex"])) == "juste"


def test_le_prelude_ne_pose_aucune_question():
    """Une question en suspens dans le prélude invalide TOUS les cas négatifs.

    Payé une fois : le premier prélude portait « il est cb de kill le chef ce
    matin ? ». Wally y répondait en appelant `apex_legends` — correctement — et
    le banc comptait onze « outil appelé à tort » sur des cas où le message
    testé était « LUL » ou « coucou ». Le verdict accusait Wally d'un réflexe
    qu'il n'a pas.
    """
    from scripts.banc_outils import PRELUDE

    fautives = [ligne for ligne in PRELUDE if "?" in ligne]
    assert not fautives, (
        f"Le prélude pose une question : {fautives}. Wally y répondra, et "
        "chaque cas négatif comptera un faux appel qui n'en est pas un."
    )
