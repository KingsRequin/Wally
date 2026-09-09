"""Le temps de réponse se mesure sur les TROIS chemins, pas sur un seul.

Défaut relevé par l'owner le 2026-09-09 : la tuile « temps de réponse » de
l'accueil du site affichait « — » en permanence. Elle n'était pas cassée —
elle n'avait jamais rien reçu.

`AppState.record_response_time()` n'avait qu'UN appelant dans tout le dépôt,
`dashboard/routes/chat.py`, soit le chat WEB. Or il ne sert quasiment jamais :
mesuré sur un boot du 2026-09-09, `messages_web: 0` contre 2 sur Discord et 40
sur Twitch. Le tampon restait donc vide, `avg_response_ms` rendait `None`, et
le site affichait un tiret — sans que rien ne dise que le compteur n'avait
jamais été branché sur les deux voies qui portent le trafic.

Signature déjà payée ailleurs (cf. `test_parite_cablage.py`) : une capacité
posée d'un seul côté ne casse rien, ne journalise rien et ne fait échouer aucun
test. Elle se contente de ne pas exister.

Sur l'AST et non par `grep` : une ligne commentée ou une docstring qui parle de
la mesure ne doit pas compter comme un branchement. Et on regarde la PRÉSENCE
de l'appel, jamais sa forme — asserter une ligne d'implémentation figerait le
défaut le jour où on voudra la déplacer.
"""
import ast
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]

# Les trois chemins par lesquels Wally répond à quelqu'un. Chacun doit verser
# sa mesure au dashboard, sinon la moyenne ne décrit qu'une partie du trafic.
_CHEMINS = {
    "chat web": Path("bot/dashboard/routes/chat.py"),
    "Discord": Path("bot/discord/handlers.py"),
    "Twitch": Path("bot/twitch/handlers.py"),
}


def _mesure_la_latence(chemin: Path) -> bool:
    """Vrai si le fichier APPELLE `record_response_time` quelque part."""
    arbre = ast.parse((_RACINE / chemin).read_text(encoding="utf-8"))
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "record_response_time"
        for n in ast.walk(arbre)
    )


def test_les_trois_chemins_de_reponse_versent_leur_latence():
    manquants = [nom for nom, f in _CHEMINS.items() if not _mesure_la_latence(f)]
    assert not manquants, (
        "temps de réponse jamais mesuré sur : " + ", ".join(manquants)
        + " — la tuile du site affichera « — » pour tout le trafic de ces "
          "chemins, sans que rien ne le signale."
    )


def test_la_moyenne_est_vide_tant_que_personne_ne_mesure():
    """Le repli est `None`, et c'est LUI qui s'affichait en « — » pendant des
    semaines. Le garder explicite : un 0 mentirait en annonçant une réponse
    instantanée là où il n'y a simplement aucune mesure."""
    from bot.dashboard.state import AppState

    etat = AppState.__new__(AppState)
    etat._init_latency()
    assert etat.avg_response_ms is None
    etat.record_response_time(1500.0)
    assert etat.avg_response_ms == 1500.0
