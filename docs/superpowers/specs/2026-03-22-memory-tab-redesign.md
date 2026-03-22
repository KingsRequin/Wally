# Memory Tab Redesign — Design Spec

**Date:** 2026-03-22
**Status:** Draft
**Scope:** Dashboard memory tab UI/UX overhaul

---

## Problem Statement

The current memory tab uses a sidebar+detail layout that is impractical:
- Finding a specific user requires scrolling through a narrow 280px sidebar list
- No way to filter by platform or sort by meaningful criteria
- Memories are displayed as a flat, uncategorized list — hard to scan when a user has many entries
- No indication of memory source (auto-extracted vs manually added)
- No categorization/tagging of memories

## Design Overview

Replace the sidebar+detail layout with a **responsive card grid** for user browsing, and a **modal popup** for user detail with **categorized, collapsible memory groups**.

The 3 existing sub-tabs (Users / Global / Dashboard) are preserved as pill navigation.

---

## 1. Toolbar

Located above the grid in the Users sub-tab.

### Components (left to right)

| Component | Type | Behavior |
|---|---|---|
| Search | Text input | Fuzzy search by username, filters grid in real-time |
| Platform filter | Segmented pills | `Tous` / `Discord` / `Twitch` — filters grid |
| Sort | Dropdown | Options: by memory count (default), trust, love, alphabetical |
| Sans mémoire | Toggle switch | Show/hide users with 0 memories (default: hidden) |
| Sync | Button | Syncs users from Qdrant + resolves Discord/Twitch usernames |
| Analyser | Button | Triggers automatic link similarity analysis |

### Changes from current

- **Removed:** "Résoudre noms" button — merged into Sync (single action does both)
- **Removed:** "Lier deux users" button from toolbar — moved into user modal as contextual action
- **Added:** Platform filter pills, sort dropdown

---

## 2. User Card Grid

### Card content

- **Avatar**: Discord/Twitch profile picture via API. Fallback: first letter on a gradient background (Discord blue `#5865F2` or Twitch purple `#9146FF`)
- **Username**: 13px, semibold, white
- **Subtitle**: Platform name + memory count (e.g., "Discord · 28 mémoires")
- **Trust bar**: Horizontal progress bar, cyan `#06b6d4`, with numeric value below
- **Love bar**: Horizontal progress bar, pink `#ec4899`, with numeric value below
- **Link badge** (conditional): Small "🔗 lié" badge in top-right corner if account is linked

### Layout

- CSS Grid, responsive columns:
  - Desktop (>1200px): 4 columns
  - Tablet (>768px): 3 columns
  - Mobile (<768px): 2 columns
- Gap: 12px
- Cards sorted according to toolbar sort selection

### Styling (glassmorphism)

- Background: `rgba(255, 255, 255, 0.05)`
- Border: `1px solid rgba(255, 255, 255, 0.08)`
- Border-radius: `12px`
- Hover: border transitions to `rgba(6, 182, 212, 0.3)`, background to `rgba(255, 255, 255, 0.07)`
- Avatar ring: `box-shadow: 0 0 0 2px` with platform color at 30% opacity

### Users without memories

When "Sans mémoire" toggle is ON:
- Cards shown with reduced opacity (0.6)
- Dashed border instead of solid
- Subtitle: "Discord · sans mémoire" in italic

---

## 3. User Detail Modal

Opens on card click. Centered overlay with backdrop blur.

### Modal structure (top to bottom)

#### 3.1 Header

- Large avatar (56px) with platform gradient ring
- Username (17px, semibold)
- Platform + join date
- Stats in large type: Trust, Love, Memory count
- Close button (✕) top-right

#### 3.2 Action bar

- `+ Ajouter mémoire` — opens inline form to add a memory with category selector
- `🔗 Lier un compte` — triggers link mode (see section 4)
- `🗑 Supprimer tout` — right-aligned, red, requires confirmation

#### 3.3 Search

- Text input: "🔍 Rechercher dans les mémoires..."
- Filters visible memories across all categories in real-time

#### 3.4 Memory categories (collapsible sections)

Each category is a collapsible section with:
- **Header**: chevron (▼/▶) + category name (colored, uppercase) + count
- **Body**: list of memory entries, sorted by date descending (most recent first)

| Category | Color | Label |
|---|---|---|
| Faits | `#22c55e` (green) | FAIT |
| Préférences | `#3b82f6` (blue) | PREF |
| Langue | `#eab308` (yellow) | LANG |
| Relations | `#a855f7` (purple) | REL |
| Non classé | `#64748b` (gray) | — |

Each memory entry displays:
- Memory text (flex: 1)
- Source icon: 🤖 (auto-extracted) or ✍️ (manually added)
- Date (short format: "12 mar")
- Edit (✏️) and Delete (🗑) buttons — visible on hover only

Left border accent: 2px solid with category color at 30% opacity.

#### 3.5 Linked accounts section

- Shown at bottom, separated by a border-top
- Lists linked accounts as pills with platform icon, username, and unlink (✕) button

### Modal styling

- Backdrop: `rgba(0, 0, 0, 0.6)`
- Modal: `rgba(255, 255, 255, 0.05)`, `border: 1px solid rgba(255, 255, 255, 0.1)`, `border-radius: 14px`, `backdrop-filter: blur(10px)`
- Max-width: `650px`, centered
- Max-height: `80vh`, scrollable body

---

## 4. Account Linking Flow

1. User clicks "🔗 Lier un compte" in the modal
2. Modal closes
3. Grid enters **selection mode**:
   - Cyan banner appears above grid: `"{username} ↔ Cliquer sur un user..."` with Cancel button
   - Source user's card is grayed out (opacity 0.4)
   - All other cards get `cursor: crosshair`
   - Hovering a card shows cyan glow
4. User clicks a target card
5. Confirmation prompt: "Lier {source} avec {target} ?"
6. On confirm: link is created, grid exits selection mode
7. **Modal reopens automatically** on the source user, showing the newly linked account in "Comptes liés"

---

## 5. Memory Categorization

### Tagging mechanism

Categories are assigned by the LLM during fact extraction. The `fact_extraction_system.md` prompt will be updated to output structured facts with a `category` field.

Output format per fact:
```
[CATEGORY] fact text
```

Where CATEGORY is one of: `FAIT`, `PREF`, `LANG`, `REL`.

### Storage

The category is stored as metadata in mem0 alongside each memory entry. The mem0 `metadata` dict will include a `category` key.

### Migration

Existing memories without a category will appear in the "Non classé" (gray) section. An optional batch re-categorization could be run via LLM, but this is out of scope for the initial implementation.

---

## 6. Backend Changes

### New/modified endpoints

| Endpoint | Change |
|---|---|
| `GET /memory/users` | Add `sort_by` query param (memories, trust, love, name) |
| `GET /memory/users/{user_id}` | Return memories grouped by category |
| `POST /memory/users/{user_id}/memories` | Accept `category` field |
| `PUT /memory/users/{user_id}/memories/{memory_id}` | Accept `category` field |
| `POST /memory/sync` | Also trigger username resolution (merge current "resolve-usernames" logic) |

### Avatar URLs

Discord avatars: fetched via Discord API (`user.avatar.url`), cached in `memory_users` or trust_scores table as `avatar_url`.
Twitch avatars: fetched via Twitch API (`user.profile_image_url`), same caching.
Resolution happens during Sync or on first load. Stored as URL string in DB.

---

## 7. Sub-tabs (Global / Dashboard)

No changes to Global or Dashboard sub-tabs. They keep their current behavior:
- **Global**: CRUD list of global community memories
- **Dashboard**: Pending questions with priority + memory count bar chart per user

---

## 8. Files to modify

| File | Changes |
|---|---|
| `bot/dashboard/static/app.js` | Rewrite `renderMemoryTab()`, `loadMemoryUsers()`, `loadUserDetail()`, add modal/grid/link-mode logic |
| `bot/dashboard/static/style.css` | Replace `.mem-sidebar`/`.mem-detail`/`.mem-layout` with grid+modal styles |
| `bot/dashboard/routes/memory.py` | Add sort_by param, category support, merge resolve-usernames into sync |
| `bot/persona/prompts/fact_extraction_system.md` | Add category output format |
| `bot/core/fact_extractor.py` | Parse category from LLM output, store in mem0 metadata |
| `bot/core/memory.py` | Pass/return category metadata |
| `bot/db/database.py` | Add `avatar_url` column to relevant table if needed |

---

## 9. Out of scope

- Batch re-categorization of existing memories
- Drag-and-drop reordering of memories
- Bulk edit/delete operations
- Real-time avatar refresh (cached at sync time is sufficient)
