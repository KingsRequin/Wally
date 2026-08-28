# Handoff de la refonte du panel admin

Ces deux fichiers sont des **références de design**, pas du code de production :
maquettes HTML statiques, données inventées, styles inline, aucune connexion aux
routes. Ils ne sont ni servis, ni chargés, ni testés — ils se lisent.

| Fichier | Contenu |
|---|---|
| `Panel Wally - Ecrans finaux.dc.html` | Les 13 écrans bureau + 3 écrans mobiles de la direction retenue, chacun précédé de sa note. **La référence principale** : pour toute question de couleur, d'espacement ou de hiérarchie, c'est lui qui tranche. |
| `Panel Wally - Navigation.dc.html` | L'historique des explorations : trois directions comparées, deux modèles mobiles. Utile pour comprendre POURQUOI la direction retenue l'a été. |

Chaque écran commence par un titre numéroté (`01` Cockpit … `14` Mobile) —
`grep -n '<h2'` donne la table des matières.

Source : projet Claude Design `a5f004f3-fe28-404b-ad1f-273434a9101a`, rapatrié
le 2026-08-28. Le README d'origine du handoff est distillé dans
`docs/plans/2026-08-28-refonte-panel-admin-plan.md`, qui porte les arbitrages —
dont celui de **ne pas** implémenter l'écran 13 (« Accès & rôles ») : le jeton
du panel donne accès à tout, modérateur et administrateur ont les mêmes droits.

`support.js` du projet d'origine n'a **pas** été rapatrié : c'est le runtime des
fichiers de maquette, sans rapport avec le panel, et il ne doit pas être porté.
