# Three Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement trust score 0.0 default, enriched Discord login page, and "Journal détaillé" dashboard tab.

**Architecture:** Three independent changes touching backend (database migration) and frontend (dashboard SPA). The trust score change requires updating 5 code locations + 1 test file. The login page and journal tab are pure frontend additions to app.js/index.html/style.css.

**Tech Stack:** Python/aiosqlite (backend), vanilla JS/CSS (frontend)

**Spec:** `docs/superpowers/specs/2026-03-20-three-improvements-design.md`

---

## File Map

| Action | File | What changes |
|--------|------|-------------|
| Modify | `bot/db/database.py:44` | Schema default 0.5→0.0 |
| Modify | `bot/db/database.py:397` | Fallback 0.5→0.0 |
| Modify | `bot/db/database.py:233+` | Add migration block |
| Modify | `bot/db/database.py:622` | COALESCE 0.5→0.0 |
| Modify | `bot/core/emotion.py:506` | Default param 0.5→0.0 |
| Modify | `bot/core/emotion.py:569` | Default param 0.5→0.0 |
| Modify | `bot/dashboard/routes/chat.py:259` | Default param 0.5→0.0 |
| Modify | `tests/test_dashboard_memory_db.py:66-86` | Update expected values |
| Modify | `bot/dashboard/static/app.js:2107-2118` | Replace login block |
| Modify | `bot/dashboard/static/index.html:64-68` | Insert journal tab in sidebar |
| Modify | `bot/dashboard/static/index.html:282` | Insert journal tab container |
| Modify | `bot/dashboard/static/app.js:131-132` | Add showTab case for journal |
| Modify | `bot/dashboard/static/app.js` (end) | Add renderJournalDetailTab() |
| Modify | `bot/dashboard/static/style.css` (end) | Add journal tab styles |

---

### Task 1: Trust score default 0.5→0.0 — database & backend

**Files:**
- Modify: `bot/db/database.py:44,397,622,233+`
- Modify: `bot/core/emotion.py:506,569`
- Modify: `bot/dashboard/routes/chat.py:259`

- [ ] **Step 1: Change schema default**

In `bot/db/database.py`, line 44, change:
```python
score REAL NOT NULL DEFAULT 0.5,
```
to:
```python
score REAL NOT NULL DEFAULT 0.0,
```

- [ ] **Step 2: Change Python fallback in get_trust_score()**

In `bot/db/database.py`, line 397, change:
```python
return float(row["score"]) if row else 0.5
```
to:
```python
return float(row["score"]) if row else 0.0
```

- [ ] **Step 3: Change COALESCE in list_memory_users()**

In `bot/db/database.py`, line 622, change:
```python
"COALESCE(t.score, 0.5) AS trust_score, 1 AS in_memory_users "
```
to:
```python
"COALESCE(t.score, 0.0) AS trust_score, 1 AS in_memory_users "
```

- [ ] **Step 4: Add migration for existing users**

In `bot/db/database.py`, inside the `create()` classmethod, add after the last migration block (around line 247, before the `logger.info` line):

```python
        # Migration: trust score baseline 0.5 → 0.0
        try:
            await conn.execute(
                "ALTER TABLE trust_scores ADD COLUMN trust_v2_migrated INTEGER DEFAULT 0"
            )
            await conn.commit()
            # Column just created → migration not yet run
            await conn.execute(
                "UPDATE trust_scores SET score = MAX(score - 0.5, 0.0)"
            )
            await conn.commit()
            logger.info("Trust score migration applied: all scores shifted by -0.5")
        except aiosqlite.OperationalError:
            pass  # Column already exists → migration already applied
```

- [ ] **Step 5: Change default params in emotion.py**

In `bot/core/emotion.py`, line 506, change:
```python
    async def analyze_message(
        self, text: str, trust_score: float = 0.5
    ) -> dict[str, float]:
```
to:
```python
    async def analyze_message(
        self, text: str, trust_score: float = 0.0
    ) -> dict[str, float]:
```

In `bot/core/emotion.py`, line 569, change:
```python
    async def process_message(
        self, text: str, trust_score: float = 0.5, context_messages: list[dict] | None = None,
```
to:
```python
    async def process_message(
        self, text: str, trust_score: float = 0.0, context_messages: list[dict] | None = None,
```

- [ ] **Step 6: Change default param in chat.py**

In `bot/dashboard/routes/chat.py`, line 259, change:
```python
async def _post_process(state: AppState, text: str, sender_id: str, trust: float = 0.5) -> None:
```
to:
```python
async def _post_process(state: AppState, text: str, sender_id: str, trust: float = 0.0) -> None:
```

- [ ] **Step 7: Update tests**

In `tests/test_dashboard_memory_db.py`:

Line 66-68 — change:
```python
    # Pas encore de trust score → défaut 0.5
    users = await db.list_memory_users()
    assert users[0]["trust_score"] == 0.5
```
to:
```python
    # Pas encore de trust score → défaut 0.0
    users = await db.list_memory_users()
    assert users[0]["trust_score"] == 0.0
```

Line 73 — change:
```python
    assert users[0]["trust_score"] == round(0.5 + 0.3, 2)
```
to:
```python
    assert users[0]["trust_score"] == round(0.0 + 0.3, 2)
```

Line 85-86 — change:
```python
    assert users["discord:bob"]["trust_score"] == round(0.5 + 0.2, 2)
    assert users["twitch:bob"]["trust_score"] == 0.5  # Twitch inchangé
```
to:
```python
    assert users["discord:bob"]["trust_score"] == round(0.0 + 0.2, 2)
    assert users["twitch:bob"]["trust_score"] == 0.0  # Twitch inchangé
```

- [ ] **Step 8: Run tests**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/test_dashboard_memory_db.py -v`
Expected: all tests PASS

- [ ] **Step 9: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v --timeout=30`
Expected: all tests PASS (no other test depends on the 0.5 default)

- [ ] **Step 10: Commit**

```bash
git add bot/db/database.py bot/core/emotion.py bot/dashboard/routes/chat.py tests/test_dashboard_memory_db.py
git commit -m "feat: trust score initial 0.5→0.0 with migration for existing users"
```

---

### Task 2: Discord login page enrichment

**Files:**
- Modify: `bot/dashboard/static/app.js:2107-2118`
- Modify: `bot/dashboard/static/style.css` (end of file)

- [ ] **Step 1: Replace the login block in renderChatTab()**

In `bot/dashboard/static/app.js`, replace the non-authenticated block (lines 2107-2118):

```javascript
  if (!authed) {
    el.innerHTML = `
      <div class="chat-login-prompt">
        <div style="font-size:1.2rem;font-weight:600;margin-bottom:8px">Chat avec Wally</div>
        <div style="color:var(--text-muted);max-width:400px">
          Connecte-toi avec Discord pour discuter avec Wally en temps réel.
        </div>
        <a href="/api/chat/auth/login" class="chat-login-btn">
          <svg width="20" height="15" viewBox="0 0 71 55" fill="white"><path d="M60.1 4.9A58.5 58.5 0 0 0 45.4.2a.2.2 0 0 0-.2.1 40.8 40.8 0 0 0-1.8 3.7 54 54 0 0 0-16.2 0A37.4 37.4 0 0 0 25.4.3a.2.2 0 0 0-.2-.1A58.4 58.4 0 0 0 10.5 4.9a.2.2 0 0 0-.1.1C1.5 18.7-.9 32.2.3 45.5v.2a58.9 58.9 0 0 0 17.8 9a.2.2 0 0 0 .3-.1 42.1 42.1 0 0 0 3.6-5.9.2.2 0 0 0-.1-.3 38.8 38.8 0 0 1-5.5-2.6.2.2 0 0 1 0-.4l1.1-.9a.2.2 0 0 1 .2 0 42 42 0 0 0 35.8 0 .2.2 0 0 1 .2 0l1.1.9a.2.2 0 0 1 0 .3 36.4 36.4 0 0 1-5.5 2.7.2.2 0 0 0-.1.3 47.3 47.3 0 0 0 3.6 5.8.2.2 0 0 0 .3.1A58.7 58.7 0 0 0 70.5 45.7v-.2c1.4-15-2.3-28.4-9.8-40.1a.2.2 0 0 0-.1-.1zM23.7 37.3c-3.5 0-6.3-3.2-6.3-7.1s2.8-7.1 6.3-7.1 6.4 3.2 6.3 7.1c0 3.9-2.8 7.1-6.3 7.1zm23.2 0c-3.5 0-6.3-3.2-6.3-7.1s2.8-7.1 6.3-7.1 6.4 3.2 6.3 7.1c0 3.9-2.8 7.1-6.3 7.1z"/></svg>
          Se connecter avec Discord
        </a>
      </div>`;
    return;
  }
```

Replace with:

```javascript
  if (!authed) {
    el.innerHTML = `
      <div class="chat-login-prompt">
        <div class="login-title">Avant de te connecter...</div>
        <div class="login-subtitle">Wally a besoin de savoir qui tu es pour se souvenir de toi.</div>

        <div class="login-why-block">
          <div class="login-why-icon">🔗</div>
          <div class="login-why-title">Pourquoi Discord ?</div>
          <div class="login-why-text">
            Wally utilise ton compte Discord comme identifiant pour rattacher tes souvenirs à ton profil.
            C'est ce qui lui permet de te reconnaître et de se souvenir de tes échanges passés,
            que ce soit ici ou sur le serveur Discord.
          </div>
        </div>

        <div class="login-cards">
          <div class="login-card" style="--card-accent: var(--c-curiosity)">
            <div class="login-card-icon" aria-hidden="true">🧠</div>
            <div class="login-card-title">Ta mémoire personnelle</div>
            <div class="login-card-text">Au fil de vos échanges, Wally retient tes goûts, ton humour, tes sujets favoris. Chaque conversation devient plus naturelle.</div>
          </div>
          <div class="login-card" style="--card-accent: var(--c-joy)">
            <div class="login-card-icon" aria-hidden="true">🔒</div>
            <div class="login-card-title">Données minimales</div>
            <div class="login-card-text">Seuls ton pseudo, ton ID et ton avatar Discord sont récupérés. Aucun accès à tes messages, serveurs ou liste d'amis.</div>
          </div>
          <div class="login-card" style="--card-accent: var(--c-sadness)">
            <div class="login-card-icon" aria-hidden="true">📦</div>
            <div class="login-card-title">Hébergement local</div>
            <div class="login-card-text">Tout est stocké sur le serveur de Wally. Rien ne transite par des services tiers. Tes données restent chez nous.</div>
          </div>
          <div class="login-card" style="--card-accent: var(--c-anger)">
            <div class="login-card-icon" aria-hidden="true">🗑️</div>
            <div class="login-card-title">Contrôle total</div>
            <div class="login-card-text">Tu peux consulter ou supprimer tous tes souvenirs à tout moment, directement depuis le chat.</div>
          </div>
        </div>

        <a href="/api/chat/auth/login" class="chat-login-btn">
          <svg width="20" height="15" viewBox="0 0 71 55" fill="white"><path d="M60.1 4.9A58.5 58.5 0 0 0 45.4.2a.2.2 0 0 0-.2.1 40.8 40.8 0 0 0-1.8 3.7 54 54 0 0 0-16.2 0A37.4 37.4 0 0 0 25.4.3a.2.2 0 0 0-.2-.1A58.4 58.4 0 0 0 10.5 4.9a.2.2 0 0 0-.1.1C1.5 18.7-.9 32.2.3 45.5v.2a58.9 58.9 0 0 0 17.8 9a.2.2 0 0 0 .3-.1 42.1 42.1 0 0 0 3.6-5.9.2.2 0 0 0-.1-.3 38.8 38.8 0 0 1-5.5-2.6.2.2 0 0 1 0-.4l1.1-.9a.2.2 0 0 1 .2 0 42 42 0 0 0 35.8 0 .2.2 0 0 1 .2 0l1.1.9a.2.2 0 0 1 0 .3 36.4 36.4 0 0 1-5.5 2.7.2.2 0 0 0-.1.3 47.3 47.3 0 0 0 3.6 5.8.2.2 0 0 0 .3.1A58.7 58.7 0 0 0 70.5 45.7v-.2c1.4-15-2.3-28.4-9.8-40.1a.2.2 0 0 0-.1-.1zM23.7 37.3c-3.5 0-6.3-3.2-6.3-7.1s2.8-7.1 6.3-7.1 6.4 3.2 6.3 7.1c0 3.9-2.8 7.1-6.3 7.1zm23.2 0c-3.5 0-6.3-3.2-6.3-7.1s2.8-7.1 6.3-7.1 6.4 3.2 6.3 7.1c0 3.9-2.8 7.1-6.3 7.1z"/></svg>
          Se connecter avec Discord
        </a>
      </div>`;
    return;
  }
```

- [ ] **Step 2: Add CSS for the login page**

Append to `bot/dashboard/static/style.css`:

```css
/* ── Login explanation page ─────────────────────────────────────────────── */
.login-title {
  font-size: 1.4rem;
  font-weight: 800;
  margin-bottom: 4px;
}
.login-subtitle {
  color: rgba(255,255,255,0.5);
  font-size: 0.9rem;
  margin-bottom: 24px;
}
.login-why-block {
  background: rgba(88,101,242,0.1);
  border: 2px solid rgba(88,101,242,0.4);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
  max-width: 480px;
  text-align: center;
}
.login-why-icon { font-size: 2rem; margin-bottom: 8px; }
.login-why-title { font-weight: 700; font-size: 1rem; margin-bottom: 6px; }
.login-why-text { font-size: 0.85rem; color: rgba(255,255,255,0.7); line-height: 1.5; }

.login-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  max-width: 520px;
  margin-bottom: 28px;
}
.login-card {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  padding: 16px;
  text-align: left;
}
.login-card-icon { font-size: 1.3rem; margin-bottom: 6px; }
.login-card-title {
  font-weight: 700;
  font-size: 0.85rem;
  margin-bottom: 4px;
  color: var(--card-accent, #fff);
}
.login-card-text { font-size: 0.75rem; color: rgba(255,255,255,0.5); line-height: 1.45; }

@media (max-width: 600px) {
  .login-cards { grid-template-columns: 1fr; }
}
```

- [ ] **Step 3: Verify visually**

Open the dashboard in a browser, ensure you're logged out of chat, navigate to the Chat tab. Verify:
- Title "Avant de te connecter..." is visible
- "Pourquoi Discord ?" block is prominent
- 4 cards display in 2×2 grid (or 1 column on mobile)
- Discord login button works and redirects to OAuth

- [ ] **Step 4: Commit**

```bash
git add bot/dashboard/static/app.js bot/dashboard/static/style.css
git commit -m "feat: enriched Discord login page with privacy explanation"
```

---

### Task 3: "Journal détaillé" dashboard tab

**Files:**
- Modify: `bot/dashboard/static/index.html:64-68,282`
- Modify: `bot/dashboard/static/app.js:131-132` (showTab) + end of file
- Modify: `bot/dashboard/static/style.css` (end of file)

- [ ] **Step 1: Add sidebar entry in index.html**

In `bot/dashboard/static/index.html`, after the Chat sidebar item (after line 67), insert:

```html
      <a class="sidebar-item" data-tab="journal-detail" onclick="showTab('journal-detail')" href="javascript:void(0)" aria-label="Journal détaillé">
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/></svg>
        <span>Journal</span>
      </a>
```

- [ ] **Step 2: Add tab container in index.html**

In `bot/dashboard/static/index.html`, before the CHAT TAB comment (before line 281), insert:

```html
    <!-- JOURNAL DETAIL TAB -->
    <div class="tab-content" id="tab-journal-detail"></div>
```

- [ ] **Step 3: Add showTab routing in app.js**

In `bot/dashboard/static/app.js`, inside `showTab()`, after the line `if (tabId === 'roadmap') loadRoadmap();` (line 131), add:

```javascript
  if (tabId === 'journal-detail') renderJournalDetailTab();
```

- [ ] **Step 4: Add renderJournalDetailTab() function in app.js**

Append this function at the end of `bot/dashboard/static/app.js` (before the closing of the file). This is the core content — 6 sections with vulgarization + expandable technical details:

```javascript
// ── Journal détaillé ────────────────────────────────────────────────────────

function renderJournalDetailTab() {
  const el = document.getElementById('tab-journal-detail');
  if (!el || el.querySelector('.jd-container')) return;

  el.innerHTML = `
    <div class="jd-container">
      <div class="jd-header">
        <h2 class="jd-title">Comment fonctionne Wally ?</h2>
        <p class="jd-subtitle">Découvre ce qui se passe dans la tête de Wally, étape par étape. Clique sur « Aller plus loin » pour voir le code source et les détails techniques.</p>
      </div>

      <!-- Section 1: Cycle de vie d'un message -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-curiosity)">1</span>
          <h3>Cycle de vie d'un message</h3>
        </div>
        <div class="jd-body">
          <p>Quand quelqu'un envoie un message sur Discord ou Twitch, Wally le reçoit et lance une série d'étapes en quelques secondes :</p>
          <p>D'abord, il <strong>détecte la langue</strong> du message (français, anglais…) pour répondre dans la bonne langue. Ensuite, il <strong>analyse le ton émotionnel</strong> grâce à NRCLex, un dictionnaire qui associe chaque mot à des émotions (joie, colère, tristesse…). En parallèle, il <strong>consulte sa mémoire</strong> : que sait-il sur l'auteur du message ? Quels sont ses goûts, ses sujets favoris ?</p>
          <p>Avec toutes ces informations, il <strong>construit un prompt personnalisé</strong> : sa personnalité (qui il est, comment il parle), son humeur actuelle, les souvenirs pertinents, et les derniers messages de la conversation. Ce prompt est envoyé à <strong>OpenAI</strong>, qui génère la réponse.</p>
          <p>En arrière-plan, Wally met à jour le <strong>score de confiance</strong> de l'utilisateur et enregistre le <strong>coût de l'appel API</strong>.</p>

          <div class="jd-pipeline">
            <span class="jd-pipe-step" style="background: #5865F2">📨 Message</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">🌍 Langue</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">🧠 Émotion</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">💾 Mémoire</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">✍️ Prompt</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step">🤖 OpenAI</span>
            <span class="jd-pipe-arrow">→</span>
            <span class="jd-pipe-step" style="background: var(--c-curiosity)">💬 Réponse</span>
          </div>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — le pipeline en code</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/discord/handlers.py — handle_message()</div>
              <pre><code>async def handle_message(self, message):
    # 1. Détection de la langue (asyncio.to_thread pour ne pas bloquer)
    lang = await asyncio.to_thread(detect_language, message.content)

    # 2. Analyse émotionnelle via NRCLex (aussi en thread séparé)
    trust = await self.db.get_trust_score(platform, user_id)
    emotion_result = await self.emotion.process_message(
        text, trust_score=trust, context_messages=context
    )

    # 3. Recherche en mémoire (Qdrant — similarité vectorielle)
    memories = await self.memory.search(user_id, message.content)

    # 4. Construction du prompt (persona + émotion + mémoire + contexte)
    prompt = self.prompt_builder.build(
        emotion_state=self.emotion.get_state(),
        memories=memories,
        context=recent_messages
    )

    # 5. Appel OpenAI → réponse
    response = await self.openai.complete(prompt)

    # 6. Post-traitement : trust score, coût, extraction de faits
    await self._post_process(message, response)</code></pre>
              <p class="jd-tech-note">Le pipeline est entièrement <strong>asynchrone</strong>. Les opérations CPU-bound (NRCLex, détection de langue) tournent dans <code>asyncio.to_thread()</code> pour ne pas bloquer la boucle événementielle — ce qui permet à Wally de continuer à écouter les autres messages pendant qu'il traite celui-ci.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 2: Système émotionnel -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-joy); color: #000">2</span>
          <h3>Système émotionnel</h3>
        </div>
        <div class="jd-body">
          <p>Wally ressent <strong>5 émotions en permanence</strong>, chacune mesurée entre 0.0 (absente) et 1.0 (maximale) :</p>

          <div class="jd-gauges">
            <div class="jd-gauge"><span class="jd-gauge-label">Colère</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:15%;background:var(--c-anger)"></div></div></div>
            <div class="jd-gauge"><span class="jd-gauge-label">Joie</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:65%;background:var(--c-joy)"></div></div></div>
            <div class="jd-gauge"><span class="jd-gauge-label">Tristesse</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:10%;background:var(--c-sadness)"></div></div></div>
            <div class="jd-gauge"><span class="jd-gauge-label">Curiosité</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:45%;background:var(--c-curiosity)"></div></div></div>
            <div class="jd-gauge"><span class="jd-gauge-label">Ennui</span><div class="jd-gauge-track"><div class="jd-gauge-fill" style="width:30%;background:var(--c-boredom)"></div></div></div>
          </div>

          <p>Chaque message fait bouger ces émotions. Un compliment booste la <strong>joie</strong>, une insulte monte la <strong>colère</strong>, une question intéressante pique la <strong>curiosité</strong>. L'impact dépend aussi du <strong>score de confiance</strong> de l'auteur : un inconnu (trust bas) provoque des réactions plus vives qu'un habitué.</p>
          <p>Avec le temps, chaque émotion <strong>retombe naturellement vers zéro</strong>, comme un humain qui se calme. La vitesse de retombée est différente pour chaque émotion — la colère s'apaise vite, la tristesse persiste plus longtemps.</p>
          <p>Si un utilisateur déclenche la colère au-delà d'un seuil trop souvent, Wally le <strong>mute temporairement</strong> : il ne répond plus avec du texte, seulement avec des réactions emoji (💩 ⛔ 😤).</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — décroissance exponentielle et formules</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/core/emotion.py — _apply_decay()</div>
              <pre><code># Formule de décroissance : E(t) = E₀ × e^(−λ × Δt)
# Chaque émotion a son propre λ (lambda) configurable dans config.yaml

def _apply_decay(self):
    now = time.time()
    dt = now - self._last_decay
    for emotion in EMOTIONS:
        lam = self._lambdas[emotion]
        self._state[emotion] *= math.exp(-lam * dt)
        if self._state[emotion] < DECAY_FLOOR:
            self._state[emotion] = 0.0
    self._last_decay = now</code></pre>
              <p class="jd-tech-note"><strong>Décroissance exponentielle</strong> : un λ élevé = retombée rapide. La colère a typiquement λ=0.003 (retombe en ~10min) tandis que la tristesse a λ=0.001 (persiste ~30min). Un task en arrière-plan applique cette décroissance toutes les 60 secondes.</p>
              <p class="jd-tech-note"><strong>Trust score et colère</strong> : quand le trust score est bas (<0.3), les deltas de colère sont amplifiés. Un nouvel utilisateur (trust=0.0) provoquera une réaction de colère plus forte qu'un habitué (trust=0.8). C'est un mécanisme de protection naturel.</p>
              <p class="jd-tech-note"><strong>Timeout</strong> : si la colère dépasse le seuil configuré N fois pour un même utilisateur, il est mute pendant X minutes (configurable). Pendant ce mute, Wally réagit uniquement avec des emoji.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 3: Mémoire -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-sadness)">3</span>
          <h3>Mémoire</h3>
        </div>
        <div class="jd-body">
          <p>Wally a <strong>deux types de mémoire</strong>, comme un humain :</p>
          <p><strong>La mémoire courte</strong> — les derniers messages de la conversation en cours. Wally garde en tête les N derniers échanges (configurable) pour garder le fil. Quand cette fenêtre devient trop grande, il la résume automatiquement via un modèle secondaire pour économiser des tokens.</p>
          <p><strong>La mémoire longue</strong> — des faits extraits automatiquement au fil du temps et stockés dans une base vectorielle (Qdrant). « Aime les crevettes », « fan d'Apex Legends », « déteste le lundi matin », « a un chat qui s'appelle Pixel ». Ces faits sont extraits par le <strong>FactExtractor</strong>, qui analyse les conversations par batch après une période d'inactivité.</p>
          <p>Quand Wally reçoit un message, il cherche dans sa mémoire longue les souvenirs les plus <strong>pertinents par similarité sémantique</strong> — pas juste par mots-clés, mais par sens. Si tu parles de « mon félin », il retrouvera le souvenir de Pixel même si le mot « chat » n'apparaît pas.</p>
          <p>Chaque plateforme a sa propre mémoire : les souvenirs Discord et Twitch sont <strong>strictement séparés</strong> par namespace (<code>discord:user_id</code> vs <code>twitch:username</code>).</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — mem0, Qdrant, trust score</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/core/memory.py — search() + FactExtractor</div>
              <pre><code># Recherche par similarité vectorielle dans Qdrant
async def search(self, user_id, query, limit=5):
    results = await self.client.search(
        collection="memories",
        query=query,           # Converti en embedding automatiquement
        filter={"user_id": user_id},
        limit=limit
    )
    return [r.payload for r in results]

# FactExtractor : extraction de faits par batch
# Après 20min d'inactivité dans un canal, le FactExtractor
# analyse la conversation et extrait les faits durables :
# "### pseudo\\n- fait 1\\n- fait 2\\n..."
# Chaque fait est stocké via memory.add() dans Qdrant.</code></pre>
              <p class="jd-tech-note"><strong>mem0</strong> est la couche d'abstraction pour la mémoire longue. Elle gère l'embedding (conversion texte → vecteur), le stockage dans <strong>Qdrant</strong> (base vectorielle auto-hébergée), et la recherche par similarité.</p>
              <p class="jd-tech-note"><strong>Trust score</strong> : chaque utilisateur a un score de confiance (0.0 → 1.0) qui évolue avec le temps. +0.01 par interaction positive, -0.05 pour les comportements toxiques. Le score part à 0.0 — la confiance se mérite.</p>
              <p class="jd-tech-note"><strong>Sliding window</strong> : la mémoire courte garde les N derniers messages. Quand le nombre de tokens dépasse un seuil, les messages les plus anciens sont résumés par un modèle secondaire et remplacés par un bloc résumé.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 4: Personnalité -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-anger)">4</span>
          <h3>Personnalité</h3>
        </div>
        <div class="jd-body">
          <p>La personnalité de Wally est définie dans <strong>4 fichiers texte</strong> (Markdown), chacun avec un rôle précis :</p>
          <p><strong>SOUL.md</strong> — Son âme. Qui il est fondamentalement : un pote loyal, un peu cynique, avec un humour pince-sans-rire. Ce fichier définit les valeurs profondes qui ne changent jamais, peu importe l'humeur.</p>
          <p><strong>IDENTITY.md</strong> — Son histoire. D'où il vient, ce qu'il aime (la tech, les jeux, la musique), ses opinions, ses running jokes. C'est ce qui le rend unique et cohérent dans le temps.</p>
          <p><strong>VOICE.md</strong> — Comment il parle. Son registre de langue, ses tics verbaux, la longueur de ses réponses, quand il utilise des emoji et quand il n'en met pas. Le style, pas le fond.</p>
          <p><strong>EXEMPLES.md</strong> — Des exemples concrets de réponses « à la Wally » pour calibrer le ton. Le modèle s'en inspire sans les copier.</p>
          <p>À chaque message, ces 4 fichiers sont <strong>assemblés dans cet ordre</strong> et injectés dans le prompt système. L'émotion dominante du moment ajoute une <strong>directive comportementale</strong> tirée de <strong>EMOTIONS.md</strong> — si Wally est joyeux, il est plus bavard et taquin ; s'il est en colère, ses réponses sont courtes et impatientes.</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — PersonaService et prompt building</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/core/persona.py + bot/core/prompts.py</div>
              <pre><code># PersonaService charge les 4 fichiers persona au démarrage
# Ordre canonique : SOUL → IDENTITY → VOICE → EXEMPLES
persona_block = PersonaService.load()
# → Un seul bloc texte injecté dans le system prompt

# EMOTIONS.md est parsé séparément en {emotion: directive}
# Sections délimitées par "## emotion_name"
# Ex: "## anger" → "Tes réponses sont courtes et impatientes."

# PromptBuilder assemble le prompt final :
# [persona_block] + [emotion_directive] + [memories] + [context]
prompt = PromptBuilder.build(
    emotion_state=current_emotions,
    memories=relevant_memories,
    context=recent_messages
)</code></pre>
              <p class="jd-tech-note">Les fichiers persona sont chargés au démarrage et mis en cache. La commande <code>/wally reload-persona</code> permet de les recharger à chaud sans redémarrer le bot.</p>
              <p class="jd-tech-note"><strong>Directive émotionnelle</strong> : le prompt ne dit jamais « tu es en colère » — il dit « tes réponses sont courtes et impatientes ». C'est un choix de design : on décrit le comportement, pas l'état interne. Le LLM interprète mieux des instructions concrètes.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 5: Journal quotidien -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: var(--c-curiosity)">5</span>
          <h3>Journal quotidien</h3>
        </div>
        <div class="jd-body">
          <p>Chaque soir, Wally <strong>écrit son journal de la journée</strong>. C'est un texte rédigé avec ses propres mots, comme un vrai journal intime.</p>
          <p>Il commence par compiler <strong>toutes les conversations de la journée</strong> depuis sa base de données. Il identifie les <strong>moments forts</strong> : les pics d'émotion (quand il a ri, quand il s'est énervé, quand il était curieux) et qui les a déclenchés.</p>
          <p>Il note les <strong>statistiques</strong> : combien de messages, combien de participants uniques, les top 5 des plus actifs, les heures de pointe, la répartition Discord vs Twitch.</p>
          <p>Puis il rédige un <strong>résumé narratif</strong> de sa journée. Pour les grosses journées (beaucoup de messages), il utilise une technique de résumé multi-passes : il découpe en blocs de 30 messages, résume chaque bloc, puis synthétise les résumés en un texte final.</p>
          <p>Il génère aussi un <strong>graphe d'émotions</strong> (image PNG) montrant l'évolution de ses 5 émotions au cours de la journée, et <strong>forme des opinions</strong> sur les sujets récurrents qu'il a rencontrés (fire-and-forget, en arrière-plan).</p>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — DailyJournal et sources de données</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/core/journal.py — DailyJournal</div>
              <pre><code># Sources de données (ordre de priorité / fallback) :
# 1. daily_log (SQLite) — tous les messages du jour, survit aux redémarrages
# 2. Discord channel history — fallback API si daily_log vide
# 3. RAM context windows — buffers mémoire de la session en cours
# 4. mem0 memory banks — faits stockés en mémoire longue

# Taille dynamique du journal :
# < 50 messages → 150-250 mots
# 50-200 messages → 250-400 mots
# > 200 messages → 400-600 mots

# Multi-pass summarization pour les grosses journées :
# 1. Découper en chunks de 30 messages
# 2. Résumer chaque chunk via modèle secondaire
# 3. Synthétiser les résumés en texte final

# Le journal inclut aussi :
# - Comparaison hebdo (émotions vs moyenne 7 jours)
# - Le journal de la veille (pour la continuité narrative)
# - Un graphe Matplotlib (PNG) des émotions du jour</code></pre>
              <p class="jd-tech-note">Le journal est déclenché par <strong>apscheduler</strong> (cron async) à une heure configurable. Il peut aussi être déclenché manuellement via <code>/wally journal</code>.</p>
              <p class="jd-tech-note">Le résultat est découpé en messages de max 1900 caractères (limite Discord = 2000) et posté dans le salon configuré. Le graphe PNG est envoyé en pièce jointe.</p>
              <p class="jd-tech-note"><strong>Formation d'opinions</strong> : en parallèle du journal, Wally analyse les sujets récurrents de la journée et forme des opinions nuancées qu'il stocke en mémoire. C'est un processus fire-and-forget qui enrichit sa personnalité au fil du temps.</p>
            </div>
          </details>
        </div>
      </section>

      <!-- Section 6: Architecture -->
      <section class="jd-section">
        <div class="jd-section-header">
          <span class="jd-num" style="background: #ff8800">6</span>
          <h3>Architecture</h3>
        </div>
        <div class="jd-body">
          <p>Wally est un <strong>programme Python unique</strong> (monolithe modulaire) qui gère Discord et Twitch en parallèle dans la même boucle asynchrone.</p>
          <p>Les deux plateformes partagent le <strong>même cerveau</strong> : le même moteur d'émotions, la même mémoire, la même personnalité, le même client OpenAI. C'est de l'<strong>injection de dépendances</strong> : les services sont créés une seule fois au démarrage, puis passés aux adaptateurs Discord et Twitch.</p>
          <p>Les souvenirs sont stockés dans <strong>Qdrant</strong>, une base de données spécialisée dans la recherche par similarité vectorielle. Les données opérationnelles (coûts, trust scores, timeouts, logs) sont dans <strong>SQLite</strong> via aiosqlite (async).</p>
          <p>Le tout tourne dans <strong>2 conteneurs Docker</strong> : un pour Wally (bot + dashboard web), un pour Qdrant. Qdrant a un healthcheck, et Wally attend qu'il soit prêt avant de démarrer.</p>

          <div class="jd-arch-diagram">
            <div class="jd-arch-row">
              <div class="jd-arch-box" style="border-color: #5865F2">
                <strong>Discord Bot</strong><br><span>discord.py 2.x</span>
              </div>
              <div class="jd-arch-box" style="border-color: #9146FF">
                <strong>Twitch Bot</strong><br><span>twitchio 2.x</span>
              </div>
              <div class="jd-arch-box" style="border-color: var(--accent)">
                <strong>Dashboard Web</strong><br><span>FastAPI + SSE</span>
              </div>
            </div>
            <div class="jd-arch-arrow">↓ injection de dépendances ↓</div>
            <div class="jd-arch-row">
              <div class="jd-arch-box jd-arch-core">
                <strong>Core Services</strong><br>
                <span>EmotionEngine · MemoryService · OpenAIClient · PersonaService · Config</span>
              </div>
            </div>
            <div class="jd-arch-arrow">↓ stockage ↓</div>
            <div class="jd-arch-row">
              <div class="jd-arch-box" style="border-color: var(--c-anger)">
                <strong>Qdrant</strong><br><span>Mémoire vectorielle</span>
              </div>
              <div class="jd-arch-box" style="border-color: var(--c-joy)">
                <strong>SQLite</strong><br><span>Coûts, trust, logs</span>
              </div>
              <div class="jd-arch-box" style="border-color: var(--c-curiosity)">
                <strong>OpenAI API</strong><br><span>GPT / o-series</span>
              </div>
            </div>
          </div>

          <details class="jd-details">
            <summary>🔍 Aller plus loin — main.py et asyncio.gather()</summary>
            <div class="jd-code-block">
              <div class="jd-file-path">bot/main.py — point d'entrée</div>
              <pre><code># Injection de dépendances : tout est créé une fois, partagé partout
config = Config.load()
db = await Database.create(config)
emotion = EmotionEngine(config)
memory = MemoryService(config)
openai_client = OpenAIClient(config, db)
persona = PersonaService(config)

# Les deux bots reçoivent les mêmes services
discord_bot = WallyDiscord(config, db, emotion, memory, openai_client, persona)
twitch_bot = WallyTwitch(config, db, emotion, memory, openai_client, persona)
dashboard = create_dashboard(config, db, emotion, memory, openai_client)

# Tout tourne en parallèle dans la même boucle événementielle
await asyncio.gather(
    discord_bot.start(token),
    twitch_bot.start(),
    dashboard.serve()
)</code></pre>
              <p class="jd-tech-note"><strong>asyncio.gather()</strong> lance les 3 services en parallèle dans la même boucle événementielle Python. Pas besoin de multi-threading ou de multi-processing — l'async/await suffit car tout le I/O est non-bloquant.</p>
              <p class="jd-tech-note"><strong>Docker</strong> : le <code>docker-compose.yml</code> définit 2 services. Wally dépend de Qdrant avec <code>condition: service_healthy</code> (healthcheck sur <code>/healthz</code>). La config et les données sont montées en volumes — pas besoin de rebuild pour changer la config.</p>
              <p class="jd-tech-note"><strong>Hot-reload</strong> : <code>config.save()</code> écrit la config en mémoire directement dans <code>config.yaml</code>. Les changements via le dashboard sont appliqués instantanément sans redémarrage.</p>
            </div>
          </details>
        </div>
      </section>
    </div>`;
}
```

- [ ] **Step 5: Add CSS for the journal tab**

Append to `bot/dashboard/static/style.css`:

```css
/* ── Journal détaillé ───────────────────────────────────────────────────── */
.jd-container { max-width: 780px; margin: 0 auto; padding: 8px 0; }
.jd-header { text-align: center; margin-bottom: 32px; }
.jd-title { font-size: 1.5rem; font-weight: 800; margin-bottom: 6px; }
.jd-subtitle { color: rgba(255,255,255,0.45); font-size: 0.85rem; max-width: 520px; margin: 0 auto; line-height: 1.5; }

.jd-section {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 24px;
  margin-bottom: 16px;
}
.jd-section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.jd-section-header h3 { font-size: 1.1rem; font-weight: 700; margin: 0; }
.jd-num {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-weight: 900; font-size: 0.85rem;
  color: #fff;
  flex-shrink: 0;
}
.jd-body p {
  font-size: 0.85rem;
  color: rgba(255,255,255,0.7);
  line-height: 1.6;
  margin: 0 0 10px;
}
.jd-body p strong { color: rgba(255,255,255,0.95); }

/* Pipeline diagram */
.jd-pipeline {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: center;
  padding: 14px;
  background: rgba(0,0,0,0.3);
  border-radius: 8px;
  margin: 16px 0;
}
.jd-pipe-step {
  background: rgba(255,255,255,0.08);
  padding: 6px 12px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
}
.jd-pipe-arrow { color: rgba(255,255,255,0.25); font-size: 0.8rem; }

/* Decorative gauges */
.jd-gauges { margin: 14px 0; }
.jd-gauge {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.jd-gauge-label {
  font-size: 0.72rem;
  color: rgba(255,255,255,0.5);
  width: 70px;
  text-align: right;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.jd-gauge-track {
  flex: 1;
  height: 8px;
  background: rgba(255,255,255,0.06);
  border-radius: 4px;
  overflow: hidden;
}
.jd-gauge-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

/* Architecture diagram */
.jd-arch-diagram {
  margin: 16px 0;
  padding: 20px;
  background: rgba(0,0,0,0.3);
  border-radius: 8px;
}
.jd-arch-row {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
}
.jd-arch-box {
  background: rgba(255,255,255,0.04);
  border: 2px solid rgba(255,255,255,0.15);
  border-radius: 8px;
  padding: 12px 18px;
  text-align: center;
  min-width: 140px;
}
.jd-arch-box strong { font-size: 0.85rem; }
.jd-arch-box span { font-size: 0.7rem; color: rgba(255,255,255,0.45); }
.jd-arch-core { flex: 1; max-width: 500px; }
.jd-arch-arrow {
  text-align: center;
  color: rgba(255,255,255,0.25);
  font-size: 0.8rem;
  padding: 8px 0;
}

/* Expandable details */
.jd-details {
  margin-top: 14px;
  border-top: 1px solid rgba(255,255,255,0.06);
  padding-top: 10px;
}
.jd-details summary {
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--accent);
  user-select: none;
}
.jd-details summary:hover { opacity: 0.8; }
.jd-code-block {
  margin-top: 12px;
  background: rgba(0,0,0,0.4);
  border-radius: 8px;
  padding: 14px;
}
.jd-file-path {
  font-size: 0.68rem;
  color: rgba(255,255,255,0.3);
  margin-bottom: 8px;
  font-family: monospace;
}
.jd-code-block pre {
  margin: 0;
  overflow-x: auto;
}
.jd-code-block code {
  font-size: 0.72rem;
  color: rgba(255,255,255,0.75);
  line-height: 1.5;
}
.jd-tech-note {
  font-size: 0.78rem;
  color: rgba(255,255,255,0.55);
  margin: 10px 0 0;
  line-height: 1.5;
}
.jd-tech-note strong { color: rgba(255,255,255,0.8); }
.jd-tech-note code {
  background: rgba(255,255,255,0.06);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.72rem;
}

@media (max-width: 600px) {
  .jd-section { padding: 16px; }
  .jd-pipeline { gap: 4px; }
  .jd-pipe-step { font-size: 0.65rem; padding: 4px 8px; }
  .jd-arch-box { min-width: 100px; padding: 8px 12px; }
}
```

- [ ] **Step 6: Verify visually**

Open the dashboard, click on the "Journal" tab in the sidebar. Verify:
- All 6 sections render with colored numbers
- Pipeline diagram in section 1 wraps properly
- Gauges in section 2 display with correct colors
- Architecture diagram in section 6 shows 3 rows
- All 6 "Aller plus loin" accordions expand/collapse
- Code blocks are readable with monospace font
- Mobile layout works (single column pipeline, narrower cards)

- [ ] **Step 7: Commit**

```bash
git add bot/dashboard/static/index.html bot/dashboard/static/app.js bot/dashboard/static/style.css
git commit -m "feat: add Journal détaillé dashboard tab with 6 sections"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run full test suite**

Run: `cd /opt/stacks/wally-ai && python -m pytest tests/ -v --timeout=30`
Expected: all tests PASS

- [ ] **Step 2: Visual check — all 3 improvements**

1. Trust score: check that `get_trust_score()` returns 0.0 for unknown users
2. Login page: navigate to Chat tab while logged out → enriched explanation page
3. Journal tab: navigate to Journal tab → 6 sections with expandable details

- [ ] **Step 3: Mark TODO items as done**

In `TODO.md`, check off the 3 completed items under AMELIORATION.
