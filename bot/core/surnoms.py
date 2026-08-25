"""Wally appelle les gens par leur pseudo, et rien d'autre.

Le 2026-08-25, l'owner constate que des viewers apprennent à Wally à désigner
les autres par des surnoms : « temcox_fps est surnommé Tempo », « skcordam aime
appeler Azrael Jean-Robert », et jusque dans les portraits réinjectés à chaque
prompt — « surnomme KingsRequin "petit chevreuil" ». Un surnom collé par un
tiers n'est pas un fait sur la personne : c'est une étiquette qu'elle n'a pas
choisie, et Wally la portait ensuite devant tout un live.

Une consigne de prompt ne suffit pas — c'est la leçon du mégenrage : le portrait
est réinjecté à CHAQUE appel et bat la consigne. Il faut TRANCHER avant l'appel,
donc refuser l'ÉCRITURE. `detecter()` est ce refus, posé au point d'écriture
unique des faits (`SQLiteFactStore.add`) et sur l'outil `save_user_memory`.

Ce qui reste autorisé, et c'est délibéré : dire qu'une personne préfère son VRAI
pseudo. Ce fait-là sert exactement le but, et l'effacer laisserait Wally
redécouvrir la question à chaque fois.
"""
import re

# Le marqueur le plus franc : le mot lui-même. « surnom », « surnommé »,
# « surnomme »… quelle que soit la personne qui le porte.
_SURNOM = re.compile(r"\bsurnom\w*", re.I)

# « appeler / appelle / appelé » AU SENS DE NOMMER. Le verbe est ambigu — « je
# t'appelle demain », « sans appeler Wally » (trace du gate, 16 000 lignes en
# base) n'ont rien à voir. On ne retient donc que les tournures où un nom SUIT :
# entre guillemets, ou en apposition après un pronom d'objet.
_APPELER_NOMME = re.compile(
    r"(?:appel(?:le|er|é|ée|ent|ait)s?)\s+"
    r"(?:\w+\s+){0,3}?"
    r"[«\"'“‘]",
    re.I,
)
_SE_FAIRE_APPELER = re.compile(
    r"(?:se faire appeler|qu'on l['ae]\s*appelle|qu'on l['ae]\s*surnomme|"
    r"aime l['ae]\s*appeler|préfère être appelée?|doit être appelée?|"
    r"veut être appelée?|l['ae]\s*appelle\s+\w)",
    re.I,
)

# « appelé POUR jouer », « appelle QUAND tu veux » : le verbe y veut dire
# solliciter, pas nommer. Sans cette sortie, « ha0r veut être appelé pour
# Warhammer » passait pour un surnom.
_APPELER_SOLLICITE = re.compile(
    r"appel(?:le|er|é|ée|ent|ait)s?\s+(?:pour|quand|si|dès|en cas|à l'aide)\b",
    re.I,
)

# L'exception qui compte : réclamer son VRAI pseudo n'est pas donner un surnom,
# c'est le refuser. Ce fait-là doit VIVRE — il est la trace que la personne a
# demandé qu'on la laisse tranquille avec les étiquettes.
_VRAI_PSEUDO = re.compile(
    r"(?:vrai|véritable|propre)\s+(?:pseudo|nom|blaze)|"
    r"par son pseudo|pseudo\s+(?:réel|exact|d'origine)|"
    r"plutôt que (?:par )?(?:le |un |son )?surnom|"
    r"pas de surnom|sans surnom|"
    r"sensible aux surnoms|n'aime pas les surnoms",
    re.I,
)


# La vie mentale de Wally n'est pas concernée. Le garde-fou vise ce qu'il
# retient DES GENS ; lui interdire de penser au sujet lui interdirait aussi de
# penser « je n'utilise pas de surnoms », et 286 de ses pensées en base parlent
# déjà de la question.
SUJET_EXEMPT = "wally:self"


def detecter(texte: str, user_id: str | None = None) -> str | None:
    """La raison du refus si `texte` enseigne un surnom, None sinon.

    Rend une PHRASE et pas un booléen : elle part telle quelle dans le journal
    et dans le refus rendu au modèle, qui doit savoir quoi en dire.
    """
    if not texte or user_id == SUJET_EXEMPT:
        return None
    # Les apostrophes TYPOGRAPHIQUES d'abord. Le LLM écrit « l’appelle » avec
    # U+2019 au moins aussi souvent que « l'appelle » : sans cette ligne, la
    # moitié des cas passaient à travers le garde sans que rien ne le signale.
    texte = texte.replace("\u2019", "'").replace("\u2018", "'").replace("\u201b", "'")
    # L'exception d'abord : « préfère son vrai pseudo plutôt que le surnom X »
    # contient les deux marqueurs, et c'est le second qui doit l'emporter.
    if _VRAI_PSEUDO.search(texte) or _APPELER_SOLLICITE.search(texte):
        return None
    if _SURNOM.search(texte):
        return "le texte enseigne ou commente un surnom"
    if _SE_FAIRE_APPELER.search(texte):
        return "le texte enseigne une façon d'appeler quelqu'un"
    if _APPELER_NOMME.search(texte):
        return "le texte attribue un nom entre guillemets à quelqu'un"
    return None


# Ce que Wally répond quand on lui DEMANDE d'adopter un surnom. Le refus
# ORIENTE au lieu de claquer la porte : la personne qui propose « appelle-moi
# Tempo » ne tente rien de louche, elle ignore juste la règle.
REFUS = (
    "Refusé : je n'enregistre pas de surnom, ni pour toi ni pour quelqu'un "
    "d'autre. J'appelle chacun par son pseudo — c'est le seul nom que la "
    "personne a choisi elle-même. Dis-le simplement, sans en faire un drame."
)
