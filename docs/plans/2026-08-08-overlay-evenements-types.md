# Un cadrage par événement pour l'overlay

**2026-08-08** — validé par l'owner.

## Le problème

`on_stream_event()` reçoit une phrase en français et rien d'autre : le type de
l'événement est perdu à la source (`feed.record("raid de X avec 12 spectateurs")`).
Son prompt compense en énumérant les types possibles — « un raid, un abonnement,
des bits, un changement de jeu » — ce qui somme le modèle d'en choisir un, même
quand aucun ne s'applique. C'est ce qui a fait annoncer 30 raids inexistants
(`44108b5`) à partir de phrases entendues en vocal.

Corollaire : les trois exemples littéraux du prompt sont recopiés mot pour mot.
Sur les logs d'une journée, « du monde débarque, tenez-vous bien » sort 30 fois,
« encore un qui va le regretter » 22 fois ; ce que le modèle invente vraiment
n'apparaît qu'une seule fois.

## La forme retenue

1. **Typer à la source.** `record(description, *, kind="")` transporte le type
   jusqu'à l'observateur, qui reçoit `(description, kind)`.

   | source | clés |
   |---|---|
   | `events/social.py` | `raid` `sub` `gift_sub` `bits` `follow_wave` |
   | `core/stream_watcher.py` | `live_start` `live_end` `game_change` `title_change` `audience` |

2. **`bot/persona/EVENTS.md`**, une section `## <clé>` par type, lue par
   `PersonaService._parse_sections()` — le parseur déjà en place, et déjà corrigé
   pour ne pas manger la première section. Même convention que `EMOTIONS.md` et
   `WEEKDAYS.md` : les règles communes ne vivent qu'à un seul endroit, et le ton
   d'un événement s'ajuste sans toucher aux autres. Rechargé par
   `/reload-persona`, dossier bind-monté : ni rebuild ni redémarrage.

3. **Des registres, pas des phrases.** Chaque section décrit ce qu'il faut viser,
   sans texte prêt à copier — un exemple littéral devient un gabarit.

4. **Le socle cesse d'énumérer les types.** `overlay_event.md` ne garde que les
   règles communes ; le type arrive désormais par la directive.

## Replis

Type inconnu, section absente ou `EVENTS.md` manquant → le socle seul. Jamais
pire que le comportement actuel.

## Bénéfice attaché

`_STRONG_EVENT_HINTS` cherche « raid » / « sub » en sous-chaîne **dans le texte**
pour agiter l'avatar : quelqu'un qui prononce le mot le déclenche. Avec un type
explicite, cela devient un ensemble de types forts.

## Exécution

- **Phase 1** — typage et transport (`stream_feed.py`, `social.py`,
  `stream_watcher.py`, `main.py`). Aucun changement de comportement : le type
  circule sans être encore utilisé.
- **Phase 2** — `EVENTS.md`, `persona.py`, `overlay_narrator.py`. Le ton change ici.

Validation de l'owner entre les deux phases.
