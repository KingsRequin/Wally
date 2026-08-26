# tests/test_emotion_analyse_locale.py
"""Le chemin d'analyse émotionnelle SANS LLM, et le parsing de sa sortie.

Trois fonctions centrales n'étaient nommées dans aucun test : la passe mutmut du
2026-08-26 les donnait à 0 % (`_load_learned_words`), 3 % (`_analyze_sync`) et
6 % (`_extract_json`) de mutants tués — autrement dit, on pouvait en changer
presque n'importe quelle ligne sans qu'une seule assertion bronche. Elles sont
pourtant sur le chemin chaud : `_analyze_sync` est ce qui note l'humeur de CHAQUE
message quand le LLM n'est pas sollicité.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import bot.core.emotion as em
from bot.core.emotion import EMOTIONS, MAX_DELTA_PER_MESSAGE, EmotionEngine, _extract_json


def make_engine():
    config = MagicMock()
    config.emotions = {
        e: MagicMock(decay_lambda=0.1, boredom_rise_per_hour=None) for e in EMOTIONS
    }
    config.bot.emotion_inertia_factor = 0.5
    return EmotionEngine(config)


# --- _extract_json ----------------------------------------------------------
# Ce que rend un LLM à qui on demande du JSON : parfois du JSON, souvent un bloc
# markdown, parfois une phrase autour.


def test_json_nu():
    assert _extract_json('{"anger": 0.2}') == {"anger": 0.2}


def test_json_entoure_d_espaces_et_de_sauts_de_ligne():
    assert _extract_json('\n\n  {"joy": 0.1}  \n') == {"joy": 0.1}


def test_json_dans_un_bloc_markdown_annonce():
    assert _extract_json('```json\n{"joy": 0.1}\n```') == {"joy": 0.1}


def test_json_dans_un_bloc_markdown_sans_langage():
    assert _extract_json('```\n{"joy": 0.1}\n```') == {"joy": 0.1}


def test_json_noye_dans_une_phrase():
    brut = 'Voici mon analyse : {"sadness": 0.3} — voilà.'
    assert _extract_json(brut) == {"sadness": 0.3}


def test_json_imbrique_pris_en_entier_et_pas_a_la_premiere_accolade_fermante():
    """`rfind("}")` et non `find`, sinon l'objet est tronqué au sous-objet."""
    brut = 'blabla {"a": {"b": 1}, "c": 2} fin'
    assert _extract_json(brut) == {"a": {"b": 1}, "c": 2}


def test_texte_sans_json_leve_plutot_que_de_rendre_un_dict_vide():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("Je n'ai pas compris la question.")


def test_accolade_ouvrante_seule_leve():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("il manque la fin : {")


# --- _load_learned_words ----------------------------------------------------
# ⚠️ `isolate_learned_emotion_words` (conftest, autouse) pointe déjà
# `_LEARNED_WORDS_PATH` sur un tmp_path : un moteur construit ici part vierge.


def test_sans_fichier_le_moteur_demarre_vierge_et_sans_broncher():
    engine = make_engine()
    assert all(engine._learned_words[e] == [] for e in EMOTIONS)


def test_les_mots_du_fichier_sont_relus(tmp_path, monkeypatch):
    chemin = tmp_path / "appris.json"
    chemin.write_text(json.dumps({"joy": [["bidule", 0.11]]}), encoding="utf-8")
    monkeypatch.setattr(em, "_LEARNED_WORDS_PATH", str(chemin))

    engine = make_engine()

    assert engine._learned_words["joy"] == [("bidule", 0.11)]


def test_un_poids_ecrit_en_texte_est_relu_comme_nombre(tmp_path, monkeypatch):
    """Le JSON écrit par une autre main peut porter `"0.11"` ; sans conversion,
    le delta part en concaténation de chaînes plus loin."""
    chemin = tmp_path / "appris.json"
    chemin.write_text(json.dumps({"joy": [["bidule", "0.11"]]}), encoding="utf-8")
    monkeypatch.setattr(em, "_LEARNED_WORDS_PATH", str(chemin))

    engine = make_engine()

    mot, poids = engine._learned_words["joy"][0]
    assert isinstance(poids, float) and poids == pytest.approx(0.11)


def test_une_emotion_absente_du_fichier_reste_vide(tmp_path, monkeypatch):
    chemin = tmp_path / "appris.json"
    chemin.write_text(json.dumps({"joy": [["bidule", 0.11]]}), encoding="utf-8")
    monkeypatch.setattr(em, "_LEARNED_WORDS_PATH", str(chemin))

    engine = make_engine()

    assert engine._learned_words["anger"] == []


def test_un_fichier_corrompu_ne_bloque_pas_le_demarrage(tmp_path, monkeypatch):
    """Le fichier est écrit par le bot en marche : une coupure au mauvais moment
    le laisse tronqué. Wally doit démarrer quand même, sans ses mots appris."""
    chemin = tmp_path / "appris.json"
    chemin.write_text('{"joy": [["bidule", 0.1', encoding="utf-8")
    monkeypatch.setattr(em, "_LEARNED_WORDS_PATH", str(chemin))

    engine = make_engine()

    assert all(engine._learned_words[e] == [] for e in EMOTIONS)


def test_un_mot_relu_du_disque_pese_vraiment_sur_l_analyse(tmp_path, monkeypatch):
    """Relire n'est utile que si la suite s'en sert : le va-et-vient complet."""
    chemin = tmp_path / "appris.json"
    chemin.write_text(json.dumps({"joy": [["schplouf", 0.12]]}), encoding="utf-8")
    monkeypatch.setattr(em, "_LEARNED_WORDS_PATH", str(chemin))

    engine = make_engine()

    assert engine._analyze_sync("un vrai schplouf", 1.0).get("joy") == pytest.approx(0.12)


# --- _analyze_sync ----------------------------------------------------------


def test_un_texte_neutre_ne_bouge_aucune_emotion():
    assert make_engine()._analyze_sync("bonjour la table est en bois", 1.0) == {}


def test_une_insulte_francaise_monte_la_colere():
    deltas = make_engine()._analyze_sync("quel connard", 1.0)
    assert deltas.get("anger", 0.0) > 0


def test_les_mots_francais_ne_se_declenchent_pas_en_sous_chaine():
    """« con » est dans la liste ; « concombre » ne doit rien déclencher."""
    assert make_engine()._analyze_sync("j'aime le concombre", 1.0) == {}


def test_un_empilement_d_insultes_reste_sous_le_plafond_par_message():
    deltas = make_engine()._analyze_sync("connard merde abruti rage putain débile", 1.0)
    assert deltas["anger"] == pytest.approx(MAX_DELTA_PER_MESSAGE)


def test_aucune_emotion_ne_depasse_jamais_le_plafond_par_message():
    texte = "connard merde triste horrible génial super pourquoi bof ennuyeux flemme"
    deltas = make_engine()._analyze_sync(texte, 1.0)
    assert deltas
    assert all(v <= MAX_DELTA_PER_MESSAGE for v in deltas.values())


def test_une_confiance_basse_amplifie_la_colere():
    """L'amplification ne joue que sur la portion anglaise (NRCLex) et seulement
    tant que le plafond n'est pas déjà atteint — d'où ce texte dilué."""
    texte = "hate happy good love joy trust wonderful excellent brilliant amazing"
    engine = make_engine()

    confiant = engine._analyze_sync(texte, 1.0)["anger"]
    mefiant = engine._analyze_sync(texte, 0.0)["anger"]

    assert mefiant > confiant


def test_une_confiance_haute_n_attenue_pas_en_dessous_du_brut():
    """Le multiplicateur est `1 + max(0, 1 - trust)` : au-delà de trust=1 il
    reste 1. Une confiance énorme ne doit pas éteindre la colère."""
    texte = "hate happy good love joy trust wonderful excellent brilliant amazing"
    engine = make_engine()

    assert engine._analyze_sync(texte, 5.0)["anger"] == pytest.approx(
        engine._analyze_sync(texte, 1.0)["anger"]
    )


def test_un_mot_anglais_de_joie_monte_la_joie():
    deltas = make_engine()._analyze_sync("this is wonderful and delightful", 1.0)
    assert deltas.get("joy", 0.0) > 0


def test_l_ennui_n_a_pas_de_source_anglaise_mais_bien_une_source_francaise():
    """`NRC_MAP["boredom"]` est vide exprès : seul le lexique français le porte."""
    engine = make_engine()
    assert "boredom" not in engine._analyze_sync("boring boring boring", 1.0)
    assert engine._analyze_sync("bof, c'est ennuyeux", 1.0).get("boredom", 0.0) > 0


def test_la_casse_du_texte_est_sans_effet():
    engine = make_engine()
    assert engine._analyze_sync("QUEL CONNARD", 1.0) == engine._analyze_sync("quel connard", 1.0)


def test_une_panne_du_lexique_anglais_ne_leve_pas():
    """Le pipeline d'un message appelle ceci en direct : une exception ici
    ferait tomber la réponse entière."""
    with patch.dict("sys.modules", {"nrclex": None}):
        make_engine()._analyze_sync("hello there", 1.0)


def test_une_panne_du_lexique_anglais_ne_coute_pas_la_detection_francaise():
    """`nrclex` porte l'ANGLAIS. Sa panne ne doit pas rendre Wally sourd au
    français : les deux moitiés étaient sous un `try` unique."""
    with patch.dict("sys.modules", {"nrclex": None}):
        deltas = make_engine()._analyze_sync("quel connard", 1.0)

    assert deltas.get("anger", 0.0) > 0


def test_des_mots_appris_corrompus_ne_coutent_pas_l_analyse_anglaise():
    """Symétrique : le fichier des mots appris est écrit par le bot en marche.
    Une entrée malformée ne doit pas emporter la moitié qui, elle, va bien."""
    engine = make_engine()
    engine._learned_words["joy"] = "pas une liste de paires"  # type: ignore[assignment]

    assert engine._analyze_sync("this is wonderful", 1.0).get("joy", 0.0) > 0
