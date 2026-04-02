# Wally — Public API Reference

Tous ces endpoints sont accessibles sans authentification.
Ils constituent le contrat stable entre le bot et tout frontend custom.

Base URL : `http(s)://votre-domaine`

---

## Status

### GET /api/public/status

Reponse JSON :
- uptime_seconds (number)
- discord_connected (bool)
- twitch_connected (bool)
- discord_guild (string|null)
- message_count (number)
- version (string)

---

## Emotions

### GET /api/public/emotions/history?since=<timestamp_ms>

Historique des snapshots (un toutes les 5 minutes).
Chaque objet : { anger, joy, sadness, curiosity, boredom, timestamp }

### GET /api/public/sse/emotions

Server-Sent Events temps reel.
Event : emotion_update
Data  : { anger, joy, sadness, curiosity, boredom }

---

## Twitch

### GET /api/public/twitch/stream

Reponse JSON :
- stream_live (bool)
- title (string)
- game_name (string)
- viewer_count (number)
- started_at (string ISO8601)

---

## Galerie

### GET /api/public/gallery?limit=N&sort=date|votes&page=N

Reponse : { images: [{ id, prompt, created_at, votes }], total, page }

### GET /api/public/gallery/{id}/image

Fichier image (PNG/JPG binaire).

### POST /api/public/gallery/{id}/vote

Ajouter un vote a une image.

---

## Graphe social

### GET /api/public/social-graph/data

Reponse : { nodes: [{ id, name, summary }], edges: [{ source, target, type, fact }] }

---

## Roadmap

### GET /api/public/roadmap

Reponse : { content: "..." }

---

## Chat web

### GET /api/chat/discord-login

Lance le flux OAuth2 Discord pour obtenir un JWT de chat.

### WS /api/chat/ws/{token}

WebSocket de chat authentifie par JWT Discord.

---

## Notes

- /api/public/* : aucun token requis.
- /api/public/gallery/{id}/image retourne du binaire, pas du JSON.
- Le SSE /api/public/sse/emotions diffuse en continu — prevoir un fallback polling.
- Panel admin : /admin (token Bearer requis pour les actions d'administration).
