# tests/test_voice_request_reply.py
"""La mise en forme de la réponse orale avant qu'elle parte dans le chat.

Vu en live le 2026-08-08 : « Yo Azra ! Alors moi c'est Wally, un petit bot qui
écoute ce qui se dit dans le micro d » — coupé net, en plein mot, à 380
caractères pile. La vraie cause était en amont (le prompt laissait Wally
raconter son raisonnement avant de répondre, ce qui mangeait le budget), mais
une coupe brutale reste une coupe brutale : ce filet doit tomber sur un mot
entier et le dire.
"""
from bot.discord.voice.request import _MAX_REPLY_CHARS, fit_for_chat


def test_une_reponse_courte_passe_intacte():
    assert fit_for_chat("Salut Azra !") == "Salut Azra !"


def test_les_espaces_sont_normalises():
    """Le texte vient d'un LLM : retours à la ligne et doubles espaces."""
    assert fit_for_chat("Salut\n\nAzra   !") == "Salut Azra !"


def test_rien_a_dire_rend_une_chaine_vide():
    assert fit_for_chat("") == ""
    assert fit_for_chat(None) == ""


def test_une_reponse_trop_longue_ne_coupe_pas_en_plein_mot():
    long = "Wally écoute le micro et répond dans le chat. " * 20
    out = fit_for_chat(long)

    assert len(out) <= _MAX_REPLY_CHARS
    # Le défaut d'origine : « ...dans le micro d ». Le dernier mot doit être entier.
    assert not out.rstrip("…").endswith(" ")
    dernier = out.rstrip("…").split()[-1]
    assert dernier in long.split(), f"mot tronqué : {dernier!r}"


def test_une_coupe_se_signale():
    """Sans marque, le lecteur croit que Wally s'est arrêté là volontairement."""
    out = fit_for_chat("mot " * 200)
    assert out.endswith("…")


def test_un_mot_unique_plus_long_que_la_limite_est_coupe_quand_meme():
    """Pas de `rsplit` possible : il ne faut pas rendre une chaîne vide."""
    out = fit_for_chat("a" * (_MAX_REPLY_CHARS + 50))
    assert 0 < len(out) <= _MAX_REPLY_CHARS


def test_une_reponse_pile_a_la_limite_n_est_pas_marquee():
    """Rien n'a été perdu : l'ellipse serait un mensonge."""
    texte = "b" * _MAX_REPLY_CHARS
    out = fit_for_chat(texte)
    assert out == texte
    assert not out.endswith("…")


# ── le prompt, cause première ────────────────────────────────────────────────


def test_le_prompt_interdit_de_penser_a_voix_haute():
    """Le prompt COMMANDE un travail d'interprétation (« suppose une erreur de
    transcription ») sans dire qu'il est interne : Wally l'a fait à voix haute,
    et le chat a lu son raisonnement à la place de sa réponse."""
    from bot.intelligence.prompts import load_prompt

    prompt = load_prompt("voice_request", render=False).lower()
    assert "interne" in prompt
    assert "préambule" in prompt
