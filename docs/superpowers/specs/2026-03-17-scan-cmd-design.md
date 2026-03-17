# Commande `/wally scan` — Analyse manuelle de l'historique Discord

**Date:** 2026-03-17
**Status:** Approved
**Scope:** `bot/discord/commands/scan_cmd.py` (nouveau), `bot/core/sessions.py` (ajout méthode publique)

---

## Contexte

Quand le bot redémarre avant la fin d'une session (20 min d'inactivité), les messages en RAM sont perdus et aucune extraction de faits n'a lieu. La commande `/wally scan` permet à un admin de déclencher manuellement l'analyse de l'historique Discord du salon courant, comme si la session s'était terminée normalement.

---

## Interface utilisateur

Commande slash admin, Discord uniquement :

```
/wally scan messages:20       → analyse les 20 derniers messages du salon
/wally scan heures:1.5        → analyse les messages des 1h30 dernières
```

**Contraintes :**
- Un seul paramètre à la fois (`messages` OU `heures`, pas les deux — si les deux sont fournis, `heures` a priorité)
- `messages` : entier 2–500, défaut suggéré : 50
- `heures` : float 0.1–72.0
- Admin-only (`administrator=True`)
- Réponse éphémère uniquement (visible par l'admin seul)

**Flow de réponse :**
1. Réponse immédiate : `"⏳ Scan en cours…"` (defer éphémère)
2. Fetch + analyse (async)
3. Résultat : `"✅ X fait(s) extrait(s) pour Y utilisateur(s)."` ou message d'erreur explicite

---

## Modification `SessionManager`

Ajout d'une méthode publique :

```python
async def analyze_channel_messages(
    self,
    messages: list[discord.Message],
    platform: str,
    channel_id: str,
) -> int:
    """Analyse une liste de messages Discord et stocke les faits durables en mémoire.

    Retourne le nombre de participants pour lesquels des faits ont été stockés.
    Lève ValueError si moins de 2 messages humains non-vides sont présents.
    """
```

**Comportement interne :**
1. Filtre les messages : exclut les bots autres que le bot courant, exclut les messages vides/embeds-only
2. Construit un `_Session` avec les messages filtrés (ordre chronologique)
3. Identifie les `participants` : uniquement les auteurs humains (pas Wally)
4. Wally est inclus dans `session.messages` comme contexte mais absent de `session.participants`
5. Appelle `_analyze_session(session)` — même chemin de code que la session automatique
6. Retourne le nombre de participants pour lesquels des faits ont été stockés

---

## Filtrage des messages

| Message | Traitement |
|---------|------------|
| Auteur = bot autre que Wally | Exclu totalement |
| Auteur = Wally | Inclus comme contexte, exclu des participants |
| Auteur = humain | Inclus contexte + participant |
| Contenu vide ou embed-only | Exclu |

---

## Nouveau fichier `scan_cmd.py`

Structure parallèle à `journal_cmd.py` :

```python
# bot/discord/commands/scan_cmd.py

@app_commands.command(name="scan")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    messages="Nombre de messages à analyser (2–500)",
    heures="Durée en heures à couvrir (0.1–72)",
)
async def scan(
    interaction: discord.Interaction,
    messages: Optional[int] = None,
    heures: Optional[float] = None,
) -> None:
    ...
```

Enregistré dans `WallyDiscord` comme les autres cogs.

---

## Gestion des erreurs

| Situation | Réponse éphémère |
|-----------|-----------------|
| Ni `messages` ni `heures` fournis | `"❌ Précise un nombre de messages ou une durée."` |
| Moins de 2 messages humains trouvés | `"⚠️ Pas assez de messages humains pour analyser (minimum 2)."` |
| Permissions Discord insuffisantes (lecture historique) | `"❌ Je n'ai pas la permission de lire l'historique de ce salon."` |
| Échec de l'analyse LLM | `"❌ Erreur lors de l'analyse. Consulte les logs."` |

Toutes les erreurs sont loguées via `loguru`.

---

## Enregistrement dans le bot

Dans `bot/discord/bot.py`, ajouter `ScanCog` aux cogs chargés au démarrage, identique aux cogs existants.

---

## Tests

- `test_scan_cmd_messages` — scan N messages, vérifie appel `analyze_channel_messages`
- `test_scan_cmd_heures` — scan par durée, vérifie le filtre `after=`
- `test_scan_cmd_no_params` — erreur si aucun paramètre
- `test_scan_cmd_too_few_messages` — erreur si < 2 messages humains
- `test_analyze_channel_messages_filters` — vérifie exclusion bots, messages vides
- `test_analyze_channel_messages_wally_context` — Wally inclus contexte, exclu participants

---

## Non-goals

- Pas d'équivalent Twitch (pas d'API historique comparable)
- Pas de restauration de la fenêtre de contexte glissante
- Pas de stockage de l'historique en base SQLite
