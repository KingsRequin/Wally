"""Ce que Wally INVENTE pour un jeu, et qui ne doit jamais devenir un fait.

Le problème, mesuré avant d'écrire une ligne. Le `fact_extractor` — d'où
viennent l'écrasante majorité des faits en base — ne lit QUE les messages
entrants : ce que Wally écrit n'y entre jamais, il est hors de cause. Mais
`EmotionEngine.process_message()` reçoit `context_messages`, c'est-à-dire la
fenêtre glissante du canal, et `append_prelude(channel_id, self_name, reply)` y
dépose LES RÉPLIQUES DE WALLY. Le LLM d'analyse les voit donc, et peut les
rendre dans `user_facts` — qui part droit en `memory.add(source="post_process")`,
sur les deux plateformes.

Aucun jeu ne faisait jusqu'ici énoncer à Wally des affirmations sur les gens :
les 63 faits `post_process` en base au 2026-08-29 décrivent tous vraiment
quelqu'un. « Deux vérités, un mensonge » est le premier à le faire — d'où ce
module, écrit avec lui et pas avant.

## Pourquoi on ne compare pas les textes

Le geste évident serait de rapprocher un fait candidat des phrases inventées.
Il est mauvais : le LLM d'analyse REFORMULE, donc toute comparaison lexicale
laisse passer ce qu'elle ne reconnaît pas, et un faux négatif ici s'écrit en
base POUR TOUJOURS — la réconciliation lui donnerait même raison contre le vrai
fait, comme l'archive de février l'a montré à l'import PhantomBot.

Alors on ferme large : tant qu'une fiction est ouverte sur un canal, AUCUN
`user_facts` de ce canal n'est retenu. On perd quelques faits légitimes pendant
les deux minutes d'une partie. C'est le bon côté du marché : un fait manqué se
réapprend au message suivant, un faux fait ne se désapprend jamais.

## Pourquoi une échéance, et pas un simple drapeau

Une fiction qu'on oublie de fermer ne se voit pas : Wally continue de parler,
de répondre, de jouer — il cesse seulement d'APPRENDRE, en silence, sur ce
canal, indéfiniment. C'est la signature exacte des défauts que ce projet paie
le plus cher : quelque chose échoue, personne n'est prévenu.

L'échéance rend la panne impossible plutôt que rare. Elle vaut aussi contre le
cas où la tâche de révélation est annulée, perdue, ou meurt sur une exception.
Le registre vit en RAM : un redémarrage rouvre donc la mémoire, ce qui est le
bon sens de panne — on préfère mille fois manquer une garde qu'un mois de
faits.

## Portée

Par CANAL, parce que c'est la clé que `process_message` a sous la main et que
c'est là que le jeu se joue : une partie sur Twitch ne doit pas rendre Wally
amnésique dans un salon Discord au même moment.
"""
import time

from loguru import logger

# L'échéance de secours, quand l'appelant n'en donne pas. Large : une partie de
# deux minutes plus le temps de la révélation et des réactions.
_TTL_DEFAUT_S = 300.0

# Canal → instant (monotonic) où la fiction expire d'elle-même. Un dict et pas
# un ensemble : c'est l'échéance qui fait le travail, pas l'appartenance.
_ECHEANCES: dict[str, float] = {}


def ouvrir(canal_id: str, duree_s: float = _TTL_DEFAUT_S) -> None:
    """Déclare qu'à partir de maintenant, Wally invente sur ce canal.

    `duree_s` est un FILET, pas la durée du jeu : l'appelant ferme à la
    révélation. Elle borne ce qui arrive quand il ne le fait pas.
    """
    if not canal_id:
        return
    _ECHEANCES[str(canal_id)] = time.monotonic() + max(1.0, float(duree_s))
    logger.info("Fiction ouverte sur {c} pour {d:.0f}s — aucun fait ne sera "
                "retenu d'ici la révélation", c=canal_id, d=duree_s)


def fermer(canal_id: str) -> None:
    """La partie est finie : ce qui se dit redevient mémorisable."""
    if canal_id and _ECHEANCES.pop(str(canal_id), None) is not None:
        logger.info("Fiction fermée sur {c}", c=canal_id)


def en_cours(canal_id: str) -> bool:
    """Wally est-il en train d'inventer sur ce canal ?

    Purge l'échéance dépassée au passage : sans ça, un canal joué une fois
    resterait dans le dict pour la vie du process.
    """
    if not canal_id:
        return False
    fin = _ECHEANCES.get(str(canal_id))
    if fin is None:
        return False
    if time.monotonic() >= fin:
        del _ECHEANCES[str(canal_id)]
        logger.warning(
            "Fiction expirée d'elle-même sur {c} : personne ne l'a fermée. La "
            "révélation du jeu n'a pas eu lieu, ou sa tâche est morte.", c=canal_id,
        )
        return False
    return True
