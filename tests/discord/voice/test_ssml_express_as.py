"""Le style émotionnel doit atteindre Azure, pas seulement être écrit dans le SSML.

`mstts` est un identifiant d'espace de noms XML, pas une URL : Azure compare la
chaîne EXACTE. Écrit en `https://`, l'élément `express-as` appartient à un espace
de noms que le serveur ne connaît pas — il ne proteste pas, il l'IGNORE et rend
la phrase à plat. Le système d'émotion vocal tournait donc à vide, sans un mot
dans les logs.

Mesuré le 2026-08-18 contre l'API réelle, `fr-FR-Marc:MAI-Voice-2-Flash`, même
texte :

    https + style joyful → 31 200 octets  ← à l'octet près le rendu SANS style
    http  + style joyful → 29 280 octets
    http  + style softvoice → 59 040 octets

Ces tests lisent le SSML en XML plutôt qu'en texte : ce qui compte n'est pas la
façon dont le namespace est déclaré, mais l'espace de noms où l'élément atterrit.
"""
from xml.etree import ElementTree

from bot.discord.voice.providers import AzureTTS

# Ce que le serveur Azure reconnaît. Vérifié en réel, pas lu dans le code.
_NS_AZURE = "http://www.w3.org/2001/mstts"

_MARC = "fr-FR-Marc:MAI-Voice-2-Flash"


def _tts(voice: str = _MARC) -> AzureTTS:
    return AzureTTS(key="k", region="r", voice=voice)


def test_le_style_atterrit_dans_lespace_de_noms_quazure_reconnait():
    ssml = _tts()._build_ssml("Salut", "joyful")
    racine = ElementTree.fromstring(ssml)

    trouves = racine.iter(f"{{{_NS_AZURE}}}express-as")
    element = next(trouves, None)
    assert element is not None, (
        f"aucun express-as dans {_NS_AZURE} — Azure rendrait la phrase à plat.\n{ssml}"
    )
    assert element.get("style") == "joyful"


def test_aucun_element_ne_traine_hors_des_deux_espaces_de_noms_connus():
    """Un élément dans un troisième espace de noms serait ignoré en silence,
    exactement comme l'était `express-as` — le défaut se reproduirait ailleurs."""
    ssml = _tts()._build_ssml("Salut", "softvoice")
    connus = {"http://www.w3.org/2001/10/synthesis", _NS_AZURE}

    for element in ElementTree.fromstring(ssml).iter():
        ns = element.tag.split("}")[0].lstrip("{") if "}" in element.tag else ""
        assert ns in connus, f"élément {element.tag} hors des espaces de noms connus"


def test_sans_style_le_texte_est_dit_tel_quel():
    """Sans émotion dominante, pas d'`express-as` : la voix parle à son
    intonation par défaut, ce qui n'est pas le même son qu'un style neutre."""
    ssml = _tts()._build_ssml("Salut", None)
    racine = ElementTree.fromstring(ssml)

    assert next(racine.iter(f"{{{_NS_AZURE}}}express-as"), None) is None
    voix = next(racine.iter("{http://www.w3.org/2001/10/synthesis}voice"))
    assert voix.get("name") == _MARC
    assert (voix.text or "").strip() == "Salut"


def test_le_texte_de_wally_ne_peut_pas_casser_le_ssml():
    """Il parle de balises et de guillemets comme n'importe qui. Non échappé,
    le SSML deviendrait invalide et il serait muet sur cette réplique-là."""
    dit = 'un <break> et des "guillemets" & une esperluette'
    racine = ElementTree.fromstring(_tts()._build_ssml(dit, "angry"))

    element = next(racine.iter(f"{{{_NS_AZURE}}}express-as"))
    assert element.text == dit
