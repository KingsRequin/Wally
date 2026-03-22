Mets à jour la documentation du projet en fonction des changements récents.

## Étapes

1. **Analyse les changements récents** : lis le `git log --oneline -20` et le `git diff HEAD~5 --stat` pour comprendre ce qui a changé depuis la dernière mise à jour de la doc.

2. **TODO.md** : lis le fichier, coche les tâches terminées, ajoute une ligne de rapport avec la date. Si rien n'a changé, ne touche pas au fichier.

3. **ROADMAP.md** : lis le fichier, déplace les features terminées de "Prévu" vers "Fait récemment" avec les sous-items cochés. Si rien n'a changé, ne touche pas au fichier.

4. **CLAUDE.md** : lis le fichier, mets à jour les sections impactées (directory structure, tables DB, sections de documentation des services). N'ajoute une nouvelle section que si un nouveau système majeur a été implémenté. Si rien n'a changé, ne touche pas au fichier.

5. **Dashboard Info** (`bot/dashboard/static/app.js`) : lis la fonction qui génère le panneau info (cherche les `<!-- Section N:` dans app.js). Si un nouveau système majeur a été ajouté, ajoute une section numérotée suivant le même format HTML (jd-section, jd-num, jd-body, details/summary). Mets aussi à jour le diagramme d'architecture si nécessaire. Si rien n'a changé, ne touche pas au fichier.

## Règles

- Ne modifie que ce qui a réellement changé. Si un fichier est déjà à jour, dis-le et passe au suivant.
- Garde le style et le format existant de chaque fichier.
- Commite tous les changements en un seul commit avec le message : `docs: update project documentation`
- Si aucun fichier n'a besoin de mise à jour, dis-le simplement sans créer de commit vide.
