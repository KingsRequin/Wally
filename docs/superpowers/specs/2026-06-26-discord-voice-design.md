# Wally Vocal (Discord) — Design

**Date :** 2026-06-26
**Branche :** `feat/site-redesign-arcade`
**Statut :** spec validée, en attente de plan d'implémentation

---

## 1. Objectif

Permettre à Wally de **discuter en vocal** dans les salons vocaux Discord : il écoute
les participants, comprend ce qui se dit, et répond à voix haute — en réutilisant
intégralement son cerveau existant (gate cognitif, reasoning, persona, émotions, mémoire).

**Usage attendu :** faible, ~2-3h/mois. Contrainte budgétaire : **< 5 €/mois**.
**Coût retenu : 0 €/mois** grâce au free tier Azure Speech (5h STT + 500k chars TTS / mois).

---

## 2. Principe directeur

Le cerveau ne change pas. On ajoute deux **transducteurs** autour du pipeline existant :

- une **oreille** : Speech-to-Text (Azure)
- une **bouche** : Text-to-Speech (Azure Neural)

La parole entrante est transcrite en *pseudo-message* qui entre dans le pipeline
cognitif déjà en place (`notify_activity → gate.decide() → reasoning`). La réponse
texte produite par le reasoning ressort et est synthétisée en voix.

C'est exactement le flux Discord écrit actuel (`bot/discord/handlers.py`), mais avec
l'audio comme entrée/sortie au lieu du texte.

---

## 3. Flux de données

```
Audio Discord (flux par locuteur, Opus)
  → décodage Opus → PCM
  → VAD (webrtcvad) : découpe en segments de parole, jette les silences   ⟵ protège le quota gratuit
  → Azure STT (streaming) → texte + identité du locuteur (mapping ssrc → user Discord)
  → [PIPELINE EXISTANT : notify_activity → gate.decide() → reasoning]
  → texte de réponse (persona + émotions + mémoire, identiques à l'écrit)
  → Azure Neural TTS → PCM
  → discord.VoiceClient.play() dans le salon
```

---

## 4. Déclenchement (entrée / sortie symétriques)

Trois portes pour **entrer**, trois portes pour **sortir** :

| Action | Slash-command | Demande texte (outil LLM) | Demande orale (en vocal) |
|---|---|---|---|
| **Rejoindre** | `/wally join` (rejoint le salon de l'appelant) | « Wally viens en vocal » → outil `join_voice` | — |
| **Quitter** | `/wally leave` | « Wally quitte le vocal » → outil `leave_voice` | « Wally, dégage / tu peux partir » → `leave_voice` |

- La **demande orale de partir** fonctionne sans mécanique spéciale : la parole devient
  un pseudo-message qui traverse le cerveau avec accès aux outils ; l'outil `leave_voice`
  est exposé pendant les sessions vocales, donc le reasoning peut l'appeler.
- **Garde-fou :** seul un participant **présent dans le salon vocal** peut le faire partir
  oralement (on ignore toute demande de départ venant d'ailleurs ou d'une transcription parasite).
- Avant de couper, Wally **confirme brièvement à voix haute** (« ok, je vous laisse »).
- **Auto-leave** : après 2 minutes sans parole détectée, ou si le salon devient vide.
  Évite de rester connecté à transcrire dans le vide (protège le quota).

---

## 5. Composants (nouveau module `bot/discord/voice/`)

### 5.1 `VoiceService` (orchestrateur)
- Gère le cycle de vie : connexion au salon, attache le sink d'écoute, démarre/arrête.
- Un seul salon vocal actif à la fois (v1).
- Tient l'état : salon courant, mapping `ssrc → user`, flag « Wally parle ».

### 5.2 Écoute
- `discord-ext-voice-recv` (discord.py **ne reçoit pas** l'audio nativement) + `PyNaCl` + FFmpeg/libopus.
- Sink personnalisé : PCM par utilisateur → buffer → **VAD** (`webrtcvad`) pour isoler les
  segments de parole.
- Mapping `ssrc → membre Discord` pour étiqueter chaque transcription (`_author_label` réutilisé).

### 5.3 STT — `AzureSTT`
- Azure Speech SDK, reconnaissance en français (langue configurable).
- Entrée : segment PCM ; sortie : texte + locuteur.

### 5.4 Cerveau (réutilisé tel quel)
- Le texte transcrit est injecté dans le pipeline cognitif comme un message :
  `notify_activity` puis `gate.decide()`.
- Si décision `RESPOND` → reasoning génère la réponse (persona, émotions, mémoire — inchangés).
- Le `cognitive_feed` émet ATTN/THINK/DECIDE/SPEAK comme à l'écrit → **visible en live sur le site arcade**.
- `notify_reply` appelé après la prise de parole (cohérence anti-rumination).

### 5.5 TTS — `AzureTTS`
- Azure Neural (voix FR). Entrée : texte ; sortie : PCM jouable par `VoiceClient`.

### 5.6 Voix / playback
- `discord.VoiceClient.play()` (envoi audio = **natif** discord.py, contrairement à l'écoute).
- **Tour de parole** : Wally attend un silence avant de parler ; l'écoute est **coupée
  pendant le playback** (anti-larsen, sinon il transcrit sa propre voix).

---

## 6. Abstraction provider

STT et TTS derrière une interface minimale (sur le modèle de la couche LLM multi-provider
`bot/core/llm/`). Brancher ElevenLabs / Deepgram / OpenAI plus tard = implémenter
l'interface, sans toucher au reste. La sélection se fait par config.

```
SpeechToText.transcribe(pcm: bytes, lang: str) -> str
TextToSpeech.synthesize(text: str, voice: str) -> bytes  # PCM
```

---

## 7. Configuration

Section `voice:` dans `config.yaml` :

```yaml
voice:
  enabled: true
  stt_provider: azure
  tts_provider: azure
  language: fr-FR
  azure_voice: fr-FR-DeniseNeural   # voix Neural FR (à choisir)
  auto_leave_minutes: 2             # auto-leave après 2 min sans parole
  vad_aggressiveness: 2             # webrtcvad 0..3
```

Secrets dans `.env` (jamais commités) :

```
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=...
```

---

## 8. Gestion d'erreurs

- **Azure indisponible / quota dépassé** → log WARNING, Wally reste **muet en vocal**,
  jamais de crash. Le reste du bot continue normalement.
- **Pas de droits voix / salon plein / appelant hors vocal** → message clair à l'appelant
  (réponse de la slash-command ou réponse texte de l'outil).
- **Échec `discord-ext-voice-recv`** → encapsulé ; en cas d'échec, le vocal se désactive
  proprement sans impacter le texte.
- **Tous les handlers vocaux** : try/except, log, continue (convention projet).

---

## 9. Dépendances & setup

### Python (`requirements.txt`)
- `discord-ext-voice-recv` (réception audio)
- `PyNaCl` (chiffrement voix Discord)
- `azure-cognitiveservices-speech` (STT + TTS)
- `webrtcvad` (détection d'activité vocale)

### Système (Dockerfile)
- `ffmpeg` + `libopus` (encodage/décodage Opus, playback)

### Côté propriétaire (une fois, ~15-20 min)
- Créer une ressource **Azure Speech** (tier gratuit F0), récupérer clé + région.
- Renseigner `AZURE_SPEECH_KEY` et `AZURE_SPEECH_REGION` dans `.env`.

---

## 10. Contrainte machine (CT100)

2 cores, 3.5 Go RAM, **pas de GPU**. Acceptable : Azure fait le lourd (STT/TTS) **en cloud**.
Localement = décodage Opus + VAD léger + playback, pour **un seul salon à la fois**.
Charge CPU modérée.

---

## 11. Tests

- **Mock Azure SDK** : `transcribe()` renvoie un texte fixe ; `synthesize()` renvoie des bytes.
- **Mock `discord-ext-voice-recv`** : sink simulé alimenté en PCM de test.
- Scénarios :
  - Déclenchement `join`/`leave` via les 3 portes (commande, outil texte, outil oral).
  - Garde-fou : demande orale de départ par un non-participant → ignorée.
  - Segmentation VAD (parole vs silence).
  - Mapping locuteur → user.
  - Branchement gate : `RESPOND` → TTS appelé ; `IGNORE`/`DEFER` → pas de TTS.
  - Anti-larsen : écoute coupée pendant le playback.
  - Auto-leave (inactivité, salon vide).
- **Aucun appel réseau réel** en test.

---

## 12. Limites assumées (YAGNI v1)

- Un seul salon vocal à la fois (pas de multi-guild simultané).
- Pas de wake-word, pas de speech-to-speech end-to-end, pas de clonage de voix.
- Identité locuteur = mapping Discord (`ssrc`), pas de biométrie vocale.
- Voix FR Azure stock (pas de voix custom en v1).

---

## 13. Découpage en phases (rappel CLAUDE.md : ≤ 5 fichiers / phase, vérif entre chaque)

1. **Socle écoute** : deps, Dockerfile, `VoiceService` + sink + VAD, `/wally join`/`/wally leave`
   (sans STT/TTS — vérifier connexion vocale + capture audio).
2. **STT + TTS** : `AzureSTT`, `AzureTTS`, abstraction provider, config, secrets.
3. **Branchement cerveau** : pseudo-message → gate → reasoning → TTS ; anti-larsen ; tour de parole.
4. **Outils LLM** `join_voice`/`leave_voice` + garde-fous + confirmation orale + auto-leave.
5. **Tests** + vérification finale.

---

## 14. Critères de succès

- Wally rejoint un salon vocal via les 3 portes et le quitte via les 3 portes.
- Il transcrit la parole, décide via son gate, et répond à voix haute en français.
- Il ne se coupe pas la parole / ne s'entend pas lui-même.
- Aucun crash si Azure est indisponible.
- Coût mensuel réel = 0 € sur l'usage cible (~3h/mois).
- Suite de tests verte, sans appel réseau.

---

## Checklist de vérification manuelle (post-déploiement)

À exécuter après rebuild image + déploiement, une fois `voice.enabled: true` et les clés Azure renseignées :

- [ ] `/wally join` depuis un salon vocal → Wally rejoint le salon.
- [ ] Parler « Wally tu es là ? » → il répond à voix haute en français.
- [ ] Dire quelque chose hors-sujet → le gate peut le faire rester silencieux (selon contexte/émotions).
- [ ] Wally ne réagit pas à sa propre voix (pas d'écho larsen).
- [ ] « Wally tu peux partir » à l'oral → il confirme brièvement et quitte le salon.
- [ ] `/wally leave` → il quitte le salon.
- [ ] En texte « Wally viens en vocal » (depuis un salon vocal) → il rejoint via l'outil LLM.
- [ ] Laisser le salon silencieux 2 minutes → auto-leave automatique.
- [ ] Couper la clé Azure (ou la rendre invalide) → aucun crash, Wally reste muet en vocal, le bot texte continue.
