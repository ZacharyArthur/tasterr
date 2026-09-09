## Why

Plex Continue Watching and history can disappear when numerous unreachable local connections consume the fixed discovery probe budget before a usable remote-direct or relay fallback is attempted. This change advances the existing v2 Plex-aware personalization capability by preserving bounded fallback coverage and making the bound configurable.

## What Changes

- Select Plex connection probes by category so available remote-direct and relay fallbacks receive a slot before remaining capacity is filled by priority.
- Add a server-side probe-limit setting with a default of 6 and a validated range of 3–12.
- Pass the configured limit to both request-time Continue Watching and background history discovery.
- Document the operational and security effect without exposing the setting through browser contracts.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `plex-personalization`: Define configurable, category-aware, deterministic, bounded Plex server connection discovery.

## Non-goals

- Caching Plex connection URLs, machine identifiers, or resource tokens.
- Changing the five-minute Continue Watching result cache or any existing Plex URL, TLS, identity, redirect, token, or resource-count protection.

## Impact

Plex client discovery, backend settings, the Home and history-sync construction paths, focused tests, the Plex personalization specification, and operator configuration/security documentation. No new dependency or browser-facing API is introduced.
