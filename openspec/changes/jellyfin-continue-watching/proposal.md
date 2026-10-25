## Why

Continue Watching works only for members with a Plex link. Jellyfin members get
history-based taste but no resume rail, and households running both servers
see only half their in-progress titles. The `jellyfin-integration` change put
this rail on the backlog because Jellyfin "Play" links need a browser-facing
Jellyfin URL. The rail doesn't depend on those links: its cards open Tasterr's
title detail, the same as Plex cards do. Jellyfin already exposes resumable and
next-up items scoped to a user id, which the existing API-key model supports.

This advances the existing `jellyfin-personalization` capability toward parity
with `plex-personalization`.

## What Changes

- A member with a Jellyfin link (Jellyfin configured, rail type enabled) gets
  Continue Watching from Jellyfin's resumable movies and episodes plus next-up
  episodes, read live with the API key scoped to the member's Jellyfin user id.
- A member with both Plex and Jellyfin links gets **one** Continue Watching
  rail: candidates from both sources are canonically mapped to TMDB, merged per
  title (newest activity wins), and capped at 20 before TMDB resolution.
- One per-user five-minute cache entry covers the merged rail. A failure in one
  source drops only that source's contribution. A failure in every contributing
  source caches the empty negative entry, as Plex-only members get today.
- Progress, episode context, and next-up rules match Plex: progress 1–99 %,
  `S{n} E{n}` context, and next-up episodes allowed with null progress.
- Unlinking Jellyfin clears the cached Continue Watching entry, as unlinking
  Plex does. The admin `continue-watching` toggle gates Jellyfin work too.
- Docs and README drop "Continue Watching is not supported" for Jellyfin.

## Non-goals

- Jellyfin "Play" or deep links (still need a browser-facing Jellyfin URL).
- Marking items watched or any other write to Jellyfin.
- Persisting any Jellyfin resume data, item ids, or progress.
- Emby.
- A per-source Continue Watching toggle for members (the rail is presentation,
  not a taste source, and stays independent of taste toggles).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `jellyfin-personalization`: the API key's allowed scoped reads add resume and
  next-up; new requirement for Jellyfin Continue Watching and cross-source merge.
- `plex-personalization`: the Continue Watching requirement now shares its rail,
  cap, and cache with Jellyfin and describes per-source failure.
- `account-linking`: unlinking Jellyfin clears the cached Continue Watching
  entry.
- `app-settings`: disabling `continue-watching` also prevents Jellyfin work.

## Impact

- Backend: `clients/jellyfin.py` (resume and next-up reads, episode fields), a
  Jellyfin resume mapper in `catalog/`, a shared candidate/merge/resolve step
  extracted from `catalog/plex.py`, `rails/registry.py` (provider gating), and
  `api/home.py` and `api/account.py` wiring and cache invalidation.
- Tests: client, mapper, merge, rail gating, unlink, live Jellyfin contract.
- Docs: `docs/CONFIGURATION.md`, `README.md`.
- No migration, no new dependency, no new environment variable, no new browser
  field (cards reuse `progress_percent` and `context`).
- Landing order: seerr-login-mode-label → tmdb-metadata-language →
  discovery-exclusions-everywhere → watch-history-window →
  jellyfin-continue-watching → sign-in-method-allowlist →
  seerr-media-server-awareness → trakt-watch-history. `trakt-watch-history`
  builds on this change's "Members can unlink accounts" text.
