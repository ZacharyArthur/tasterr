## Why

Households want discovery to focus on titles they cannot already watch in their library or on subscribed services (issue #33). This advances existing media-browse, taste-recommendations, household-recommendations, and M5 app-settings capabilities.

## What Changes

- Add optional household library hiding and region-scoped subscription-service exclusions, off by default.
- Apply exclusions to discovery rails, hero, household blend, and related-title suggestions; preserve Search, My List, Continue Watching, direct title access, and taste signals.
- Add admin controls and optional environment overrides with visible locks and preserved persisted preferences.
- Bound verification across each request, keep unverified titles visible, refill discover sources within fixed limits, and distinguish filtered-empty feeds from catalog failures.

## Capabilities

### New Capabilities

- `discovery-filtering`: Shared best-effort eligibility policy, deadlines, exemptions, and refill bounds.

### Modified Capabilities

- `app-settings`: Discovery preferences, environment precedence, lock metadata, and region-change behavior.

## Non-goals

Per-user controls, full Plex library scanning, hiding pending requests, rental/purchase exclusions, unlimited refilling, new dependencies, and release/publication work.

## Impact

Backend catalog/filtering, rails, recommendation candidate selection, API wiring and admin responses; frontend settings and stale household results; generated API types and configuration docs. No database migration or new dependency. Default behavior remains unchanged.
