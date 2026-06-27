# API — Wally STT Server (transcription FR streaming, WebSocket)

Serveur de transcription vocale **française** en **streaming temps réel** sur GPU
(RealtimeSTT + faster-whisper). Ce document décrit **exactement** le protocole, pour
brancher un client sans accès à la machine serveur.

> **Réseau** : le serveur est destiné **uniquement au LAN**. Il écoute sur toutes les
> interfaces (`0.0.0.0`) mais le pare-feu Windows n'autorise le port 9090 que depuis le
> **sous-réseau local** (`LocalSubnet`). Rien n'est exposé sur Internet.

---

## 1. URL du WebSocket

```
ws://192.168.1.49:9090
```

- Protocole : **WebSocket non chiffré** (`ws://`, pas `wss://`) — réseau local de confiance.
- Hôte : `192.168.1.49` (IP LAN de la machine GPU). Depuis la machine elle-même : `ws://127.0.0.1:9090`.
- Port : `9090` (TCP).
- **Une connexion = un locuteur = un recorder dédié.** Le bot Discord ouvre **un flux WebSocket par locuteur**.

---

## 2. Messages ENTRANTS (client → serveur)

Deux types de trames :

### 2.1 Audio — trames **BINAIRES**

Chaque trame binaire est un **chunk audio PCM brut**, au format **IMPÉRATIF** suivant :

| Paramètre        | Valeur                                  |
|------------------|------------------------------------------|
| Encodage         | PCM linéaire **signé**                    |
| Profondeur       | **16 bits** (`int16`)                     |
| Boutisme         | **little-endian**                         |
| Canaux           | **1 (mono)**                              |
| Fréquence d'éch. | **16000 Hz**                             |
| Conteneur        | **aucun** (pas d'en-tête WAV, octets bruts) |

> ⚠️ Les octets binaires sont **supposés déjà en 16 kHz / mono / int16 LE** : le serveur
> ne les rééchantillonne pas. Si votre source est en 48 kHz (cas fréquent de Discord /
> Opus décodé), **rééchantillonnez côté client à 16 kHz et downmixez en mono** avant l'envoi.

**Taille de chunk recommandée** : **20 à 100 ms** d'audio, soit :

| Durée  | Octets (16 kHz × 2 o × mono) |
|--------|-------------------------------|
| 20 ms  | 640 octets                    |
| 30 ms  | 960 octets                    |
| 100 ms | 3200 octets                   |

100 ms est un bon défaut (utilisé pour les tests). Des chunks plus petits (20–30 ms)
réduisent un peu la latence des partiels. Envoyez l'audio **au fil de l'eau** (rythme
temps réel), comme il est capté.

### 2.2 Contrôle — trames **TEXTE** (JSON, optionnel)

Trames texte = JSON `{"type": "..."}`. Toutes sont **optionnelles** : le découpage des
énoncés est automatique (VAD, voir §4). Types reconnus :

| JSON                       | Effet |
|----------------------------|-------|
| `{"type": "flush"}`        | **Force la fin de l'énoncé courant immédiatement** (au lieu d'attendre le silence). Utile quand le client sait déjà que le locuteur s'est tu (ex. événement « stopped speaking » de Discord) → réduit la latence du `final`. |
| `{"type": "reset"}`        | Abandonne l'énoncé en cours et vide le buffer audio (repart à zéro, sans produire de `final`). |

Un type inconnu est ignoré (loggé côté serveur). Un JSON invalide est ignoré.

### 2.3 Fin de flux

Il n'existe **pas** de message « fin de session » obligatoire : **fermez simplement la
connexion WebSocket**. Le serveur libère alors proprement le recorder et la VRAM associée.

---

## 3. Messages SORTANTS (serveur → client)

Toujours des trames **TEXTE = JSON UTF-8**. Champ `type` toujours présent.

| `type`     | Champs            | Quand |
|------------|-------------------|-------|
| `ready`    | —                 | Une fois, après chargement des modèles : le serveur est prêt à recevoir l'audio. |
| `partial`  | `text` (string)   | À chaque mise à jour temps réel pendant que le locuteur parle (modèle `small`). Le texte **s'affine** au fil de l'énoncé. |
| `final`    | `text` (string)   | Quand un énoncé est terminé (fin détectée par le VAD ou via `flush`). Transcription **précise** (modèle `large-v3`). |
| `error`    | `message` (string)| Erreur (ex. serveur plein) ou exception de la connexion. |

**Conseil client** : attendez le message `ready` avant d'envoyer de l'audio (le 1er
chargement de `large-v3` prend ~20–30 s). Le texte fait autorité dans le message `final` ;
les `partial` sont indicatifs et peuvent être révisés.

### 3.1 Exemples RÉELS (capturés pendant les tests)

Séquence brute reçue pour la phrase _« Bonjour Wally, peux-tu transcrire cette phrase en
français correctement, s'il te plaît ? »_ :

```json
{"type": "ready"}
{"type": "partial", "text": "Bonjour."}
{"type": "partial", "text": "Bonjour Wally."}
{"type": "partial", "text": "Bonjour Wally, peux-tu transcrire cette phrase ?"}
{"type": "partial", "text": "Bonjour Wally, peux-tu transcrire cette phrase en français ?"}
{"type": "partial", "text": "Bonjour Wally, peux-tu transcrire cette phrase en français correctement, s'il te plaît ?"}
{"type": "final", "text": "Bonjour Wally, peux-tu transcrire cette phrase en français correctement, s'il te plaît ?"}
```

Exemple `error` (connexion refusée car limite atteinte) :

```json
{"type": "error", "message": "server full (2 connexions max)"}
```
(suivi d'une fermeture WebSocket avec le code `1013` = _try again later_.)

---

## 4. Délimitation des énoncés (logique VAD)

Le serveur s'appuie sur le **VAD de RealtimeSTT** (WebRTC + Silero) :

1. **Début d'énoncé** : détection automatique de parole dans le flux audio fourni.
2. Pendant la parole : le modèle **temps réel `small`** transcrit le buffer périodiquement
   → messages `partial` qui s'affinent.
3. **Fin d'énoncé** : déclenchée quand un **silence** est détecté pendant
   `post_speech_silence_duration` = **0,7 s** (valeur par défaut, configurable, voir §5).
   → le modèle **`large-v3`** produit la transcription définitive → message `final`.
4. Le cycle reprend automatiquement pour l'énoncé suivant sur la **même** connexion.

Conséquences pour le client :
- Pour qu'un `final` se déclenche « naturellement », il faut que le flux contienne le
  **silence** de fin (continuez d'envoyer l'audio, y compris les blancs). Si vous coupez
  l'audio net, envoyez `{"type":"flush"}` pour forcer le `final`.
- Le `flush` est le moyen recommandé pour minimiser la latence quand une source externe
  (Discord) signale déjà la fin de parole.

---

## 5. Paramètres configurables

Réglables par **variables d'environnement** (lues au démarrage du serveur) :

| Variable                  | Défaut       | Description |
|---------------------------|--------------|-------------|
| `WALLY_HOST`              | `0.0.0.0`    | Adresse d'écoute. |
| `WALLY_PORT`              | `9090`       | Port TCP. |
| `WALLY_FINAL_MODEL`       | `large-v3`   | Modèle de transcription finale (précis). |
| `WALLY_REALTIME_MODEL`    | `small`      | Modèle des partiels (rapide). `base`/`tiny` = plus rapide et moins de VRAM. |
| `WALLY_LANGUAGE`          | `fr`         | Code langue. |
| `WALLY_DEVICE`            | `cuda`       | `cuda` (GPU) ou `cpu`. |
| `WALLY_COMPUTE_TYPE`      | `float16`    | Précision GPU. `int8_float16` ≈ moitié de la VRAM pour `large-v3`. |
| `WALLY_MAX_CONNECTIONS`   | `2`          | Connexions simultanées max (voir limite VRAM ci-dessous). |
| `WALLY_POST_SILENCE`      | `0.7`        | Silence (s) avant de clore un énoncé (VAD). |

`--host` et `--port` peuvent aussi être passés en ligne de commande (prioritaires).

### Limite de connexions / VRAM (RTX 4070, 12 Go) — **MESURÉE**

- Coût mesuré : **~4,2 Go de VRAM par connexion** (`large-v3` float16 dans un process
  enfant dédié + `small` float16). Chaque recorder est **indépendant** (pas de partage).
- Pic mesuré à **2 connexions = ~11,8 Go / 12,3 Go** → **2 est la limite sûre** sur cette
  carte (avec le bureau Windows qui consomme déjà ~2–3 Go). **3 connexions → risque d'OOM.**
- Au-delà de `WALLY_MAX_CONNECTIONS`, les nouvelles connexions reçoivent
  `{"type":"error","message":"server full (...)"}` puis sont fermées (code `1013`).
- **Pour viser 3–4 connexions** : réduire la VRAM par connexion, p.ex.
  `WALLY_REALTIME_MODEL=base` (ou `tiny`) et/ou `WALLY_COMPUTE_TYPE=int8_float16`, puis
  augmenter `WALLY_MAX_CONNECTIONS` en conséquence.

---

## 6. Démarrer le serveur

Sur la machine GPU :

```bat
cd C:\Users\KingsRequin\wally-stt-server
start.bat
```

ou directement :

```bat
C:\Users\KingsRequin\wally-stt-server\venv\Scripts\python.exe C:\Users\KingsRequin\wally-stt-server\server.py
```

Exemple avec surcharge (port + modèle temps réel plus léger pour 3 connexions) :

```bat
set WALLY_REALTIME_MODEL=base
set WALLY_MAX_CONNECTIONS=3
start.bat
```

Au démarrage, le serveur logge le GPU détecté et l'URL d'écoute, p.ex. :

```
GPU detecte : NVIDIA GeForce RTX 4070 | CUDA 12.4 | cuDNN 90100
WebSocket en ecoute sur ws://0.0.0.0:9090
Modeles : final=large-v3 | realtime=small | langue=fr | device=cuda | compute=float16
```

---

## 7. Mini-client de référence (Python)

```python
import asyncio, json, numpy as np, soundfile as sf, websockets

async def main():
    data, sr = sf.read("audio_16k_mono.wav", dtype="int16")  # 16 kHz mono int16
    async with websockets.connect("ws://192.168.1.49:9090", max_size=None) as ws:
        # 1) attendre 'ready'
        while json.loads(await ws.recv()).get("type") != "ready":
            pass
        # 2) envoyer l'audio en chunks de 100 ms, au rythme temps réel
        chunk = 1600  # échantillons = 100 ms
        async def receive():
            async for msg in ws:
                obj = json.loads(msg)
                if obj["type"] == "partial":
                    print("partial:", obj["text"])
                elif obj["type"] == "final":
                    print("FINAL  :", obj["text"])
        rx = asyncio.create_task(receive())
        for i in range(0, len(data), chunk):
            await ws.send(data[i:i+chunk].tobytes())
            await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "flush"}))  # forcer le final
        await asyncio.sleep(3)
        rx.cancel()

asyncio.run(main())
```

Le projet fournit `client_test.py`, un client de test plus complet (lecture WAV ou capture
micro, mesure de latence). Voir `README.md`.
