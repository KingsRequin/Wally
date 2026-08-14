"""Ce que Wally perçoit de son propre fil.

Les trois travers relevés sur le live du 2026-08-13 (et la veille) :
profondeur d'un échange à sens unique, marqueur terminal collé à tous les
messages, vanne ressassée. Les cas rejouent des extraits RÉELS des journaux
`logs/conversations/twitch/azrael_ttv/`.
"""

import pytest

from bot.intelligence import thread_sense as ts


@pytest.fixture(autouse=True)
def _repartir_a_neuf():
    ts.oublier_tout()
    yield
    ts.oublier_tout()


# ── profondeur d'un fil ───────────────────────────────────────────────────

def test_premier_echange_ne_dit_rien_du_fil():
    ts.note_reponse("live", "kassandre", "La fête, oui, après le dernier carton.")
    assert ts.profondeur("live", "kassandre") == 1
    assert "d'affilée" not in ts.bloc_fil("live", "kassandre")


def test_le_fil_se_creuse_a_chaque_reponse_a_la_meme_personne():
    for i in range(10):
        ts.note_reponse("live", "kassandre", f"réplique numéro {i}")
    assert ts.profondeur("live", "kassandre") == 10


def test_repondre_a_quelqu_un_d_autre_referme_le_fil():
    for _ in range(5):
        ts.note_reponse("live", "kassandre", "encore une vanne pour toi")
    ts.note_reponse("live", "semydoo", "et une pour toi aussi")
    assert ts.profondeur("live", "kassandre") == 0
    assert ts.profondeur("live", "semydoo") == 1


def test_un_fil_perime_ne_compte_plus(monkeypatch):
    ts.note_reponse("live", "kassandre", "on fera la fête")
    depart = ts.time.monotonic()
    monkeypatch.setattr(ts.time, "monotonic", lambda: depart + ts._FIL_TTL_S + 1)
    assert ts.profondeur("live", "kassandre") == 0


def test_les_canaux_ne_se_melangent_pas():
    ts.note_reponse("live", "kassandre", "une vanne ici")
    ts.note_reponse("discussions", "kassandre", "une vanne là")
    assert ts.profondeur("live", "kassandre") == 1
    assert ts.profondeur("discussions", "kassandre") == 1


def test_le_bloc_nomme_la_personne_et_le_compte():
    for _ in range(4):
        ts.note_reponse("live", "k", "du texte quelconque")
    bloc = ts.bloc_fil("live", "k", nom_personne="kassandreyunikon")
    assert "4" in bloc and "kassandreyunikon" in bloc


def test_le_palier_atteint_vient_du_fichier_persona():
    paliers = {"3": "réponds plus court", "6": "laisse le dernier mot", "10": "lâche l'affaire"}
    for _ in range(7):
        ts.note_reponse("live", "k", "du texte quelconque")
    bloc = ts.bloc_fil("live", "k", paliers=paliers)
    assert "laisse le dernier mot" in bloc
    assert "lâche l'affaire" not in bloc
    assert "réponds plus court" not in bloc


def test_un_palier_illisible_n_empeche_pas_les_autres():
    paliers = {"trois": "n'importe quoi", "3": "réponds plus court"}
    for _ in range(4):
        ts.note_reponse("live", "k", "du texte")
    assert "réponds plus court" in ts.bloc_fil("live", "k", paliers=paliers)


# ── marqueur terminal ─────────────────────────────────────────────────────

@pytest.mark.parametrize("texte, attendu", [
    ("C'est parti, mème à l'écran ! 😄", "😄"),
    ("Bonne nuit temcox, dors bien :p", ":p"),
    ("t'es sérieux là ^^", "^^"),
    ("il a encore raté son saut.", ""),
    ("et toi, tu fais quoi ?", ""),
    ("Une prédatrice de 15 saisons qui traîne en silver", ""),
    ("", ""),
])
def test_ce_qui_compte_comme_marqueur_de_fin(texte, attendu):
    assert ts.marqueur_terminal(texte) == attendu


def test_un_marqueur_isole_n_est_pas_un_tic():
    ts.note_reponse("live", "k", "un premier message 😄")
    ts.note_reponse("live", "k", "un deuxième message 🔥")
    assert ts.tic_terminal("live") == ("", 0)


def test_le_marqueur_qui_revient_devient_un_tic():
    for i in range(4):
        ts.note_reponse("live", "k", f"message numéro {i} 😄")
    tic, compte = ts.tic_terminal("live")
    assert tic == "😄" and compte == 4


def test_le_tic_du_lendemain_est_vu_comme_celui_de_la_veille():
    """Le 12/08 c'était « :p », le 13/08 « 😄 » — aucune liste ne pouvait le prévoir."""
    for i in range(4):
        ts.note_reponse("veille", "k", f"message numéro {i} :p")
    assert ts.tic_terminal("veille")[0] == ":p"


def test_le_bloc_signale_le_tic_mesure():
    for i in range(4):
        ts.note_reponse("live", "k", f"message numéro {i} 😄")
    assert "😄" in ts.bloc_fil("live", "personne-neuve")


# ── retrait mécanique du tic ──────────────────────────────────────────────

def test_le_marqueur_passe_tant_qu_il_n_est_pas_un_tic():
    ts.note_reponse("live", "k", "premier message 😄")
    assert ts.retirer_tic("live", "encore un mot 😄") == "encore un mot 😄"


def test_le_marqueur_saute_une_fois_devenu_signature():
    for i in range(3):
        ts.note_reponse("live", "k", f"message numéro {i} 😄")
    assert ts.retirer_tic("live", "mème à l'écran ! 😄") == "mème à l'écran !"


def test_un_autre_marqueur_reste_permis():
    for i in range(3):
        ts.note_reponse("live", "k", f"message numéro {i} 😄")
    assert ts.retirer_tic("live", "bien joué 🔥") == "bien joué 🔥"


def test_une_replique_reduite_a_son_marqueur_survit_entiere():
    for i in range(3):
        ts.note_reponse("live", "k", f"message numéro {i} 😄")
    assert ts.retirer_tic("live", "😄") == "😄"


def test_le_retrait_ne_mange_pas_la_ponctuation_de_la_phrase():
    for i in range(3):
        ts.note_reponse("live", "k", f"message numéro {i} 😄")
    assert ts.retirer_tic("live", "tu crois vraiment ? 😄") == "tu crois vraiment ?"


# ── vanne ressassée ───────────────────────────────────────────────────────

def test_une_vanne_dite_une_fois_ne_remonte_pas():
    ts.note_reponse("live", "k", "Une prédatrice de 15 saisons qui traîne en silver.")
    ts.note_reponse("live", "k", "Le carton du déménagement attendra demain.")
    assert ts.mots_ressasses("live") == []


def test_la_vanne_ressortie_de_message_en_message_remonte():
    for _ in range(3):
        ts.note_reponse("live", "k", "encore la prédatrice qui traîne en silver")
    assert "predatrice" in ts.mots_ressasses("live")


def test_les_mots_outils_ne_passent_pas_pour_des_vannes():
    for _ in range(5):
        ts.note_reponse("live", "k", "voilà, toujours pareil, vraiment comme avant")
    assert ts.mots_ressasses("live") == []


def test_le_bloc_liste_les_mots_ressasses():
    for _ in range(3):
        ts.note_reponse("live", "k", "encore une couronne pour la prédatrice")
    bloc = ts.bloc_fil("live", "personne-neuve")
    assert "couronne" in bloc and "predatrice" in bloc


def test_une_vanne_enterree_cesse_d_etre_reprochee():
    for _ in range(3):
        ts.note_reponse("live", "k", "encore la prédatrice en silver")
    for i in range(ts._FENETRE_REPLIQUES):
        ts.note_reponse("live", "k", f"un sujet tout neuf numéro {i}")
    assert "predatrice" not in ts.mots_ressasses("live")


# ── le bloc dans son ensemble ─────────────────────────────────────────────

def test_un_canal_calme_ne_coute_rien():
    assert ts.bloc_fil("live", "k") == ""


def test_oublier_un_canal_laisse_les_autres_intacts():
    ts.note_reponse("live", "k", "une réplique ici")
    ts.note_reponse("discussions", "k", "une réplique là")
    ts.oublier_canal("live")
    assert ts.profondeur("live", "k") == 0
    assert ts.profondeur("discussions", "k") == 1


# ── branchement : le prompt et les deux adaptateurs ───────────────────────

def test_le_bloc_arrive_dans_le_prompt_systeme():
    from bot.intelligence.prompts import PromptBuilder

    prompt = PromptBuilder().build_system_prompt(
        emotion_state={"joy": 0.5},
        thread_context="\n--- Où tu en es dans ce fil ---\nsept fois d'affilée",
    )
    assert "sept fois d'affilée" in prompt


def test_sans_mesure_le_prompt_ne_porte_aucun_bloc_de_fil():
    from bot.intelligence.prompts import PromptBuilder

    prompt = PromptBuilder().build_system_prompt(emotion_state={"joy": 0.5})
    assert "Où tu en es dans ce fil" not in prompt


def test_fil_md_se_lit_comme_les_autres_blocs_persona(tmp_path):
    from bot.intelligence.persona import PersonaService

    (tmp_path / "FIL.md").write_text(
        "préambule ignoré\n\n## 3\nréponds plus court\n\n## 10\nlâche l'affaire\n",
        encoding="utf-8",
    )
    persona = PersonaService(persona_dir=str(tmp_path))
    assert persona.fil_directives == {"3": "réponds plus court", "10": "lâche l'affaire"}


def test_le_fil_md_livre_est_exploitable():
    """Le fichier réel, pas un gabarit de test : des seuils numériques et du texte."""
    from pathlib import Path

    from bot.intelligence.persona import PersonaService

    persona = PersonaService(
        persona_dir=str(Path(__file__).parent.parent / "bot" / "persona")
    )
    paliers = persona.fil_directives
    assert paliers, "FIL.md ne livre aucun palier"
    assert all(cle.isdigit() for cle in paliers), f"seuils non numériques : {list(paliers)}"
    # Le plus profond palier livré doit s'appliquer à un fil qui s'étire.
    assert ts._palier(max(int(c) for c in paliers), paliers)


@pytest.mark.parametrize("module", ["bot.discord.handlers", "bot.twitch.handlers"])
@pytest.mark.parametrize("point", ["bloc_fil", "note_reponse", "retirer_tic"])
def test_les_deux_adaptateurs_branchent_les_trois_points(module, point):
    """C'est le même Wally des deux côtés.

    Mesurer sur Twitch et pas sur Discord donnerait exactement le défaut qu'on
    corrige : une personne différente selon le canal. Le branchement se vérifie
    à la source — l'exécuter demanderait de monter un adaptateur entier.
    """
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module))
    assert f"thread_sense.{point}(" in source
