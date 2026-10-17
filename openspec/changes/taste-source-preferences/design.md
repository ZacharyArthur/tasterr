# Design: taste-source-preferences

## Context

`compute_profile` builds a user's vector from all their signals; the profile row
is a pure cache. After the first three changes, Seerr, Plex, and Jellyfin
history each arrive through a per-link background sync, and `detail_open` comes
from `POST /signals`.

## Decisions

### 1. Filter at computation, never delete on switch-off

The profile is rebuilt with signals of switched-off kinds excluded. Switching
off invalidates the cached profile; switching back on invalidates it again. No
rows are touched, so the toggle is instant and lossless. Deletion is a separate,
explicit "Clear imported history" action.

### 2. One per-user JSON column

`users.taste_excluded_sources` holds the switched-off source names (empty by
default). Alternatives: a `use_for_taste` flag per linked account (but browsing
has no link, and Seerr history would split across two places), or a settings
table row per user (more machinery for four booleans). The source → kinds map is
a constant in `recommend/signals.py`, the existing home for signal vocabulary.

### 3. Off also means "stop collecting"

GitHub #47 asks for opt-in import, not just opt-out of influence. So the sync
triggers check the source state before scheduling; switching off cancels an
in-flight sync with the same cancel-and-await used by reset; and `detail_open`
posts become a no-op while browsing is off. The `POST /signals` response stays
success so the SPA needs no special case.

### 4. Clear keeps the watermark

Clearing removes what has been imported but doesn't rewind the sync. With the
source still on, later syncs start from the watermark's 24-hour overlap, so older
history stays cleared, but plays or requests inside that overlap can come back.
A source that never completed a sync has no watermark and re-imports fully.
Switching the source off and on again is the explicit way to re-import
everything. Reviewers accepted keeping the watermark; the overlap and
never-synced limits are stated in the spec rather than hidden.

### 4a. Watched titles stay excluded

Switching a source off removes it from the profile, but its watched titles still
keep out of recommended-for-you: that exclusion filters the member's own rail and
is not taste. "Clear imported history" removes the rows and therefore the
exclusion. Decided in review round 2.

### 5. Candidate sources skip switched-off signals

More-like, recommended-for-you, and household blends all seed candidates from a
user's newest strong signals (`_source_titles`). That selection filters by the same
excluded kinds, so a switched-off source neither anchors a "Because You Watched X"
rail nor decides which titles get scored. Household eligibility
(`has_taste_signals`) counts only signals that count, so a member whose remaining
signals are all switched off isn't offered for a blend that would then fail.

## Risks / Trade-offs

- **Turning a source off and on triggers a full re-import** (bounded, background).
  Acceptable; it is the user's explicit action.
- **Household blends change** when a member switches a source off. Intended:
  each member's contribution is their own profile.

## Security considerations

**Any new or changed API endpoint:**
- `POST /account/taste-sources` and `POST /account/taste-sources/{source}/clear`:
  session, same-origin check, mutation bucket; `source` is a `Literal` of the
  four switchable names (deliberate kinds are unrepresentable); explicit response
  models; caller-scoped only. Both are added to the mutation-inventory regression.
- `GET /account` adds only the caller's own on/off states.
- `POST /signals` keeps all validation; the browsing check runs after validation
  and rate limiting.

**Auth & session code:** no change.

**Outbound HTTP:** none added; switching off reduces outbound calls.

**Frontend:** toggles reflect server state; no data beyond the caller's own
settings.

**Database & migrations:** `0009` adds one non-secret column with a safe default;
copies no data. Household endpoints never expose another member's sources (the
profile is the only thing blended).

**Dependencies:** none added.
