# Commande `/wally scan` — Analyse manuelle de l'historique Discord

**Date:** 2026-03-17
**Status:** Approved
**Scope:** `bot/discord/commands/scan_cmd.py` (nouveau), `bot/core/sessions.py` (ajout méthode publique + refactor `_analyze_session`)

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
- Si les deux paramètres sont fournis, `heures` a priorité et `messages` est ignoré (sans validation).
- `messages` : entier 2–500
- `heures` : float 0.1–72.0
- Admin-only (`@app_commands.default_permissions(administrator=True)`)
- Réponse éphémère uniquement (visible par l'admin seul)

**Flow de réponse :**
1. Validation des paramètres (avant defer) → erreur éphémère immédiate si invalide
2. `await interaction.response.defer(ephemeral=True)`
3. Fetch + analyse (async)
4. Résultat : `"✅ Faits extraits pour X utilisateur(s)."` ou message d'erreur éphémère

---

## Modification `SessionManager`

### Refactor `_analyze_session`

`_analyze_session` doit être refactorisé pour **retourner `int`** (le nombre de participants ayant reçu au moins une entrée mémoire) au lieu de `None`. Le log existant est conservé.

- **Chemin nominal :** retourner `stored` à la fin.
- **Chemin erreur :** le bloc `except Exception` existant logue l'erreur et **retourne `0`** (ne re-raise pas, comportement cohérent avec l'auto-session).

```python
async def _analyze_session(self, session: _Session) -> int:
    try:
        ...
        return stored
    except Exception as e:
        logger.error("Erreur lors de l'analyse de session: {e}", e=e)
        return 0
```

### Nouvelle méthode publique

```python
async def analyze_channel_messages(
    self,
    messages: list[discord.Message],
    platform: str,
    channel_id: str,
    bot_user_id: int,
) -> int:
    """Analyse une liste de messages Discord et stocke les faits durables en mémoire.

    Retourne le nombre de participants pour lesquels des faits ont été stockés.
    Lève ValueError si moins de 2 messages d'auteurs humains sont présents.
    """
```

**Comportement interne :**

1. **Identification de Wally :** `message.author.id == bot_user_id`. Ne jamais utiliser le display name.

2. **Filtrage :** pour chaque `discord.Message` :
   - Exclure si `message.author.bot and message.author.id != bot_user_id`
   - Exclure si `message.content.strip() == ""`
   - Sinon, conserver

3. **Lever `ValueError`** si le nombre de messages d'auteurs humains (non-bot, non-Wally) parmi les messages filtrés est inférieur à 2.

4. **Conversion en dict session** (format `_Session.messages`) :

   | `discord.Message` | Champ session |
   |---|---|
   | `message.author.display_name` | `author` |
   | `str(message.author.id)` | `user_id` |
   | `message.content` | `content` |
   | `message.created_at.timestamp()` | `timestamp` |

5. **Construction de `_Session` :**
   ```python
   session = _Session(
       channel_id=channel_id,
       platform=platform,
       messages=converted_messages,       # humains + Wally, ordre chronologique
       participants={...},                 # uniquement auteurs humains : user_id → display_name
       last_activity=converted_messages[-1]["timestamp"],
       timeout_task=None,
   )
   ```
   Ne jamais ajouter un auteur bot (y compris Wally) à `participants`.

6. Appeler `stored = await self._analyze_session(session)` et retourner `stored`.

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

**Validation (avant defer) :**
- Si ni `messages` ni `heures` → `interaction.response.send_message("❌ Précise un nombre de messages ou une durée.", ephemeral=True)` ; return
- Si `heures` fourni et hors [0.1, 72.0] → erreur éphémère ; return
- Si `heures` absent et `messages` fourni et hors [2, 500] → erreur éphémère ; return

**Fetch de l'historique (après defer) :**

```python
# Par nombre de messages
fetched_messages = [m async for m in channel.history(limit=N, oldest_first=True)]

# Par durée
after_dt = datetime.now(timezone.utc) - timedelta(hours=heures)
fetched_messages = [m async for m in channel.history(after=after_dt, oldest_first=True)]
```

**Appel :**
```python
stored = await session_manager.analyze_channel_messages(
    messages=fetched_messages,
    platform="discord",
    channel_id=str(interaction.channel_id),
    bot_user_id=interaction.client.user.id,
)
```

Enregistré dans `WallyDiscord` comme les autres cogs.

---

## Gestion des erreurs

| Situation | Réponse éphémère |
|-----------|-----------------|
| Ni `messages` ni `heures` | `"❌ Précise un nombre de messages ou une durée."` |
| `heures` hors [0.1, 72.0] | `"❌ La durée doit être entre 0.1 et 72 heures."` |
| `messages` hors [2, 500] | `"❌ Le nombre de messages doit être entre 2 et 500."` |
| `session_manager` non initialisé | `"❌ Service d'analyse non disponible."` |
| Moins de 2 messages humains | `"⚠️ Pas assez de messages humains pour analyser (minimum 2)."` |
| `discord.Forbidden` | `"❌ Je n'ai pas la permission de lire l'historique de ce salon."` |
| `discord.HTTPException` (autre) | `"❌ Erreur réseau lors du fetch. Consulte les logs."` |
| Échec de l'analyse LLM | `"❌ Erreur lors de l'analyse. Consulte les logs."` |

Toutes les erreurs sont loguées via `loguru`. Les exceptions levées par `interaction.response.defer()` lui-même sont hors scope.

**Ordre des `except` pour le fetch Discord** — `discord.Forbidden` est une sous-classe de `discord.HTTPException` ; il faut l'intercepter **en premier** :

```python
except discord.Forbidden:
    ...  # message permission
except discord.HTTPException:
    ...  # message réseau générique
```

---

## Tests

- `test_scan_cmd_messages` — scan N messages, vérifie appel `analyze_channel_messages` avec la bonne liste
- `test_scan_cmd_heures` — scan par durée, vérifie que `channel.history` est appelé avec `after` ≈ `datetime.now(utc) - timedelta(hours=N)` (tolérance ±5s)
- `test_scan_cmd_no_params` — erreur si aucun paramètre (avant defer)
- `test_scan_cmd_messages_out_of_range` — erreur si `messages=1` ou `messages=501`
- `test_scan_cmd_heures_out_of_range` — erreur si `heures=0.0` ou `heures=73.0`
- `test_scan_cmd_session_manager_none` — erreur si `session_manager` est `None`
- `test_scan_cmd_too_few_messages` — erreur si < 2 messages humains (ValueError)
- `test_scan_cmd_forbidden` — `discord.Forbidden` → message de permission
- `test_scan_cmd_http_exception` — `discord.HTTPException` (non-Forbidden) → message erreur réseau
- `test_analyze_channel_messages_filters` — vérifie exclusion bots tiers, messages vides, inclusion Wally comme contexte
- `test_analyze_channel_messages_wally_context` — Wally dans `messages`, absent de `participants`
- `test_analyze_channel_messages_too_few` — ValueError si < 2 messages humains
- `test_analyze_channel_messages_session_fields` — `timeout_task=None`, `last_activity` = timestamp du dernier message

---

## Non-goals

- Pas d'équivalent Twitch (pas d'API historique comparable)
- Pas de restauration de la fenêtre de contexte glissante
- Pas de stockage de l'historique en base SQLite
