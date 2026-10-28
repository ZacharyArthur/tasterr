## Why

A link's first Plex or Jellyfin history sync reads only the last 365 days
(`WATCH_HISTORY_INITIAL_WINDOW`, hard-coded). In issue #54 a member's Jellyfin
link imported zero titles because their newest play was just outside that
window, and titles watched earlier keep appearing in rails. The maintainer
noted on the issue that the window could be configurable. Both syncs already cap
work at 500 rows per type, so a longer window can't grow cost without bound.

This advances the existing `plex-personalization` and
`jellyfin-personalization` capabilities (bounded watch-history sync).

## What Changes

- Optional `TASTERR_WATCH_HISTORY_DAYS` environment variable: an integer from 1
  to 3650, default 365, sets how far back a link's **first** Plex or Jellyfin
  history sync reads. Later syncs keep the 24-hour overlap from the watermark.
- Invalid values (non-integer, out of range, explicit null or empty) fail boot.
- Existing links are not re-read automatically. `docs/CONFIGURATION.md` says
  that "Reset taste profile" (or switching a source off and on) re-imports using
  the new window.
- `.env.example` and `compose.example.yaml` document the variable.

## Non-goals

- An admin UI setting (it is a deployment tuning knob, not a household
  preference).
- Changing the 500-row caps, the six-hour throttle, or the 24-hour overlap.
- Automatically re-importing existing links when the value changes.
- Trakt, which imports all-time history under its own cap
  (`trakt-watch-history`).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `app-settings`: new optional, boot-validated `TASTERR_WATCH_HISTORY_DAYS`.
- `plex-personalization`: first sync uses the configured window.
- `jellyfin-personalization`: first sync uses the configured window.

## Impact

- Backend: `settings.py` (field and validation), `api/taste.py` (replace the
  constant with the setting at both import sites).
- Docs: `docs/CONFIGURATION.md`, `.env.example`, `compose.example.yaml`.
- No migration, no new dependency, no browser-facing change.
- Landing order: after `discovery-exclusions-everywhere`, before
  `jellyfin-continue-watching`.
