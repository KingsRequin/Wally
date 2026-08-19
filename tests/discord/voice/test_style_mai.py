"""Une voix MAI sait faire 18 tons — Wally n'en atteignait que cinq.

`fr-FR-Marc:MAI-Voice-2-Flash` accepte 18 `express-as`. Le prompt vocal, lui,
proposait huit mots-tags écrits en dur, et l'humeur ne pouvait colorer la voix
que par l'émotion DOMINANTE parmi cinq. Résultat : `determined`, `hopeful`,
`regretful`, `embarrassed`, `jealous`, `disgusted`, `confused`, `relieved` et
`happy` n'étaient joignables par AUCUN chemin.

Deux mécanismes ferment l'écart, sans rien écrire en dur côté prompt :

1. La liste des tons proposés est DÉRIVÉE de la voix réellement montée. Elle
   vaut 18 sur MAI, 4 sur une voix neurale standard, et zéro sur une voix qui
   n'a pas d'`express-as` du tout. Promettre à Wally un ton que sa voix ne
   rend pas, c'est lui faire écrire un tag sans effet ; le lui cacher quand il
   existe, c'est le mécanisme qui tourne à vide.
2. Ses émotions SECONDAIRES (fierté, nostalgie, mépris…) colorent la voix.
   Elles demandent deux émotions au-dessus du seuil, donc elles en disent plus
   que la dominante seule — même arbitrage que `COMPOSITES.md`, qui prime déjà
   sur les directives atomiques.
"""
from bot.discord.voice.style import (
    available_tags,
    resolve_style,
    secondary_to_style,
    supported_styles,
)

_MARC = "fr-FR-Marc:MAI-Voice-2-Flash"
_HENRI = "fr-FR-HenriNeural"
_MUETTE_DE_STYLE = ""  # ce que rend un TTS sans express-as

_CALME = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}


# ── les tons proposés suivent la voix ──

def test_les_dix_huit_styles_dune_voix_mai_sont_tous_atteignables():
    """Un style qu'aucun tag ne nomme est un style que Wally ne peut pas
    demander : le mécanisme existe, personne ne peut s'en servir."""
    from bot.discord.voice.style import _TAG_STYLE

    joignables = {_TAG_STYLE[tag] for tag in available_tags(_MARC)}
    manquants = supported_styles(_MARC) - joignables
    assert not manquants, f"styles MAI sans tag : {sorted(manquants)}"


def test_une_voix_standard_ne_propose_que_ce_quelle_rend():
    """Henri n'a que quatre styles. Lui en proposer dix-huit ferait écrire des
    tags qui retombent tous sur le même son — Wally croirait nuancer."""
    tags = available_tags(_HENRI)
    from bot.discord.voice.style import _TAG_STYLE, adapt_style

    rendus = [adapt_style(_TAG_STYLE[t], _HENRI) for t in tags]
    assert len(rendus) == len(set(rendus)), f"deux tags pour le même son : {tags}"
    assert len(tags) == len(supported_styles(_HENRI))


def test_une_voix_sans_style_ne_propose_aucun_ton():
    """Un moteur sans `express-as` ne rend aucun ton. En proposer un serait une
    promesse creuse :
    le tag partirait, ne changerait rien, et resterait invisible dans les logs."""
    assert available_tags(_MUETTE_DE_STYLE) == []
    assert available_tags(None) == []


def test_chaque_tag_propose_est_reconnu_a_la_lecture():
    """Le prompt et l'analyseur lisent la même table : un tag proposé mais non
    reconnu serait retiré du texte et perdu, sans une ligne de log."""
    from bot.discord.voice.style import parse_style_tag

    for tag in available_tags(_MARC):
        style, reste = parse_style_tag(f"[{tag}] dis donc")
        assert style is not None, f"tag proposé mais illisible : {tag}"
        assert reste == "dis donc"


# ── les émotions secondaires colorent la voix ──

def test_une_secondaire_active_colore_la_voix():
    assert secondary_to_style([("pride", 0.6)]) == "determined"
    assert secondary_to_style([("nostalgia", 0.5)]) == "regretful"
    assert secondary_to_style([("contempt", 0.5)]) == "disgusted"


def test_la_secondaire_la_plus_intense_gagne():
    """`get_secondary_emotions()` rend la liste triée par intensité ; on suit
    cet ordre plutôt que celui du dictionnaire."""
    assert secondary_to_style([("wonder", 0.8), ("anxiety", 0.4)]) == "surprised"


def test_aucune_secondaire_ne_laisse_la_voix_a_lhumeur():
    assert secondary_to_style([]) is None
    assert secondary_to_style(None) is None


def test_toutes_les_secondaires_configurees_ont_un_style():
    """Une secondaire sans style tomberait en silence sur l'humeur dominante —
    exactement le trou qu'on est en train de fermer."""
    import yaml

    from bot.discord.voice.style import _SECONDARY_STYLE

    cfg = yaml.safe_load(open("config.yaml"))
    configurees = set((cfg.get("emotions") or {}).get("secondaries") or {})
    assert configurees, "config.yaml sans secondaires : le test ne prouve rien"
    assert configurees <= set(_SECONDARY_STYLE), (
        f"sans style : {sorted(configurees - set(_SECONDARY_STYLE))}")


def test_toute_secondaire_reste_audible_sur_une_voix_mai():
    from bot.discord.voice.style import _SECONDARY_STYLE, adapt_style

    for nom, style in _SECONDARY_STYLE.items():
        assert adapt_style(style, _MARC) is not None, f"{nom} → {style} inaudible"


# ── priorités : tag > secondaire > humeur ──

def test_la_secondaire_prime_sur_lhumeur_dominante():
    """Fierté = joie ET curiosité au-dessus du seuil : elle dit davantage que
    « joie dominante ». Même arbitrage que les composites côté texte."""
    humeur = {**_CALME, "joy": 0.7, "curiosity": 0.5}
    style, _ = resolve_style("j'ai réussi", humeur, voice=_MARC,
                             secondaries=[("pride", 0.5)])
    assert style == "determined"


def test_le_tag_explicite_prime_sur_la_secondaire():
    humeur = {**_CALME, "joy": 0.7, "curiosity": 0.5}
    style, texte = resolve_style("[murmure] approche", humeur, voice=_MARC,
                                 secondaries=[("pride", 0.5)])
    assert style == "whispering"
    assert texte == "approche"


def test_sans_secondaire_lhumeur_dominante_reprend_la_main():
    humeur = {**_CALME, "anger": 0.8}
    assert resolve_style("bon", humeur, voice=_MARC, secondaries=[])[0] == "angry"


def test_une_secondaire_est_ramenee_aux_capacites_de_la_voix():
    """`determined` n'existe pas chez Henri : sans ce repli, la fierté rendrait
    la synthèse muette au lieu de la rendre plate."""
    style, _ = resolve_style("j'ai réussi", _CALME, voice=_HENRI,
                             secondaries=[("pride", 0.5)])
    assert style in supported_styles(_HENRI)


def test_une_voix_sans_style_ne_recoit_jamais_dexpress_as():
    """Le tag est quand même RETIRÉ du texte : non lu à voix haute, jamais
    envoyé comme style. C'est le cas d'un moteur sans styles, où il serait ignoré — mais un
    provider tiers pourrait, lui, échouer dessus."""
    style, texte = resolve_style("[murmure] approche", {**_CALME, "anger": 0.9},
                                 voice=_MUETTE_DE_STYLE, secondaries=[("pride", 0.9)])
    assert style is None
    assert texte == "approche"
