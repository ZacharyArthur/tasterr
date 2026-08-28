## Why

Tasterr 1.1 completes the founding blueprint's v1.0 and v1.x product scope, but
its recommendations still infer viewing taste from Seerr requests and in-app
interactions rather than what each person actually watches. The remaining v2
milestone is the point at which the existing Plex login token becomes a
personalization input: watched titles should teach the profile, unfinished media
should be easy to resume, and a household should be able to find a title that
fits several people.

The current feed also optimizes almost entirely toward known taste. That is useful
but narrowing. A deliberately low-correlation, quality-gated rail keeps a small
amount of serendipity in the product without weakening the main recommendation
rail.

## What Changes

- Add a thin, typed Plex integration that uses the current Plex session token to
  discover accessible Plex Media Servers, validates their advertised HTTPS
  connections, and calls only bounded read endpoints. No Plex connection or
  access token reaches the browser or durable storage beyond the already-encrypted
  login token.
- Import a bounded window of the signed-in Plex user's watch history as
  idempotent, server-recorded `watched_plex` signals weighted at +2.5. Collapse TV
  episodes to their TMDB series, keep the newest watch time per title, and skip
  media without a canonical TMDB GUID rather than fuzzy-matching titles.
- Select from the three newest qualifying strong-positive sources using a stable
  per-user daily rotation for the related-title rail. Label a Plex-watch source
  **Because You Watched X** and every other source **More Like X**.
- Add an individually toggleable **Continue Watching** provider for Plex-backed
  sessions. Merge and de-duplicate results from a bounded number of accessible
  servers, resolve them to the existing TMDB catalog models, and show optional
  episode/progress context on otherwise standard media cards.
- Add an individually toggleable **Picks You Wouldn't Usually Watch** provider.
  It uses a broad existing catalog pool, excludes hidden/engaged titles, admits
  the lowest non-negative similarity quartile relative to that pool, then ranks
  by quality, current availability, and diversity instead of forcing inverse
  taste.
- Add an individually toggleable **Something for Everyone Tonight** household
  blend. The user selects two to six known Tasterr household members for the
  current screen only; the backend normalizes the mean of their profiles, applies
  every selected member's hidden/engaged exclusions, caps the combined candidate
  pool, and returns one bounded rail.
- Extend migrations, generated API types, unit/API/frontend/live-contract tests,
  operator and architecture documentation, and the applicable security
  regression suites.

## Capabilities

### New Capabilities

- `plex-personalization`: Plex account/server discovery, safe read access, watch
  history synchronization, canonical TMDB mapping, and Continue Watching.
- `household-recommendations`: Household member discovery, ephemeral audience
  selection, combined-profile scoring, privacy rules, and the blend rail.

### Modified Capabilities

- `taste-signals`: Adds the server-only, idempotent `watched_plex` signal and its
  fixed +2.5 weight.
- `taste-recommendations`: Uses Plex watches as strong positives, gives watched
  sources an honest rail label, and adds the low-correlation exploration policy.
- `media-browse`: Renders Continue Watching context, the exploration rail, and a
  non-blocking household audience picker using existing rail/card navigation.
- `app-settings`: Registers all three v2 rails as independent, default-enabled
  admin toggles.
- `app-database`: Stores only per-user Plex history attempt/success timestamps in
  addition to the canonical watched signals; raw Plex history is not retained.
- `user-auth`: Clarifies that the encrypted Plex token is also used for
  session-scoped Plex reads and remains absent for local-login sessions.

## Non-goals

- Updating `docs/PRD.md` or `docs/SPEC.md`; they remain frozen founding
  blueprints while these OpenSpec deltas become the living v2 contract.
- Starting, controlling, or recording playback; writing any state back to Plex;
  proxying Plex images/media; or replacing the existing experimental handoff.
- Fuzzy title/year matching when Plex metadata has no TMDB GUID.
- Importing raw episode events, play counts, device names, server names, server
  URLs, Plex rating keys, or a durable copy of Continue Watching.
- A scheduler, webhook receiver, Redis/queue, multi-process coordination, a Plex
  SDK, embeddings, collaborative filtering, or a new recommendation dependency.
- Persisted household groups, per-user household preferences, profile sharing,
  arbitrary profile weights, or an admin user-management surface.
- Random candidate scoring, per-request feed reshuffling, or intentionally
  anti-taste recommendations. The exploration rail remains deterministic,
  low-correlation, and quality-gated; only the approved related-source and genre
  presentation order rotate stably per user/day.
- Migrating the existing Plex PIN flow to Plex's newer JWT device flow unless the
  required live-contract spike proves the current token can no longer access the
  documented resources and PMS endpoints.
- Bumping/publishing v2.0.0. Release preparation remains a separate audited
  change after this product change is archived and merged.

## Impact

- Backend: the existing Plex client, a small Plex-to-catalog orchestration seam,
  recommendation signal/store/service/scorer code, rail registry/composer, auth
  scheduling, three session-gated API surfaces, and one additive/reversible
  SQLite migration.
- Frontend: generated types, optional progress/context on media cards, an inline
  household audience picker, and the existing dynamic settings list for new rail
  descriptors.
- External systems: additional read-only traffic to plex.tv and up to four Plex
  Media Servers advertised for the signed-in user. TMDB remains the source of
  browser-facing catalog metadata.
- Privacy/security: more household viewing behavior influences durable signals,
  but raw Plex payloads and credentials stay server-side. Cross-user profile data
  is used only inside a caller-inclusive blend and is never serialized.
- Milestone: completes the founding PRD's v2 Plex-aware personalization table and
  adds the requested serendipity rail.
