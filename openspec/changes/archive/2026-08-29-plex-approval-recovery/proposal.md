## Why

The Plex approval fallback now uses a durable protected link instead of tracking a replacement popup, but the living authentication contract still requires the removed reopen behavior. Aligning the contract now keeps the recovery path reviewable and prevents future work from restoring the more fragile popup coupling.

This advances the existing `user-auth` capability.

## What Changes

- Keep the initial script-created Plex approval popup as a best-effort convenience while polling remains authoritative.
- Make a protected approval link and copy action available for every pending Plex PIN, including blocked, closed, or browser-severed popup cases.
- Use neutral recovery guidance, focus-safe clipboard fallback, and repeatable accessible copy feedback.
- Replace the tracked replacement-popup requirement with the durable link-based recovery contract and add focused regression coverage.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `user-auth`: Replace tracked approval-popup reopening with a durable protected approval link and copy fallback while preserving polling, opener isolation, and cleanup.

## Impact

The change affects the SPA login screen, its frontend tests, and the `user-auth` living specification. It changes no backend API, session boundary, dependency, or secret exposure.

## Non-goals

- Changing Plex PIN creation, polling, expiry, or session establishment.
- Guaranteeing programmatic clipboard access when both browser clipboard mechanisms reject it.
- Automating Plex's external approval page in the hermetic end-to-end suite.
