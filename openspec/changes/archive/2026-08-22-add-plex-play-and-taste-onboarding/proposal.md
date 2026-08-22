## Why

Tasterr can already tell when a title is in the household library, but it offers no direct path to play that title, and users whose Seerr request history is empty receive no useful cold-start personalization. These are the two deferred v1.x capabilities named in the founding blueprint and can now be added without Plex API access or a new recommendation signal vocabulary.

## What Changes

- Carry Seerr-provided Plex web and app deep links, including Overseerr/Jellyseerr aliases and 4K variants, through typed availability into title detail responses.
- Show explicit, experimental Plex Web and Plex App controls for fully or partially available titles. Plex Web opens separately to preserve Tasterr for a retry when Plex discards a destination during sign-in or household-user selection; Android keeps its tested `intent://` missing-app fallback.
- Make the existing Plex PIN approval flow use a real popup, close itself, and return focus to Tasterr on successful sign-in when the browser permits, without giving the Plex page access to the Tasterr tab or making popup success a login requirement.
- Add a non-blocking, dismissible taste picker for users whose completed cold-start seed left them with no signals.
- Record selected picker titles as the existing `watchlist` signal and persist dismissal/completion so the picker is not shown again.
- Extend unit, API, frontend, generated-type, migration, and live Seerr contract coverage.

## Capabilities

### New Capabilities

- `taste-onboarding`: Eligibility, presentation, dismissal, and signal recording for the one-time cold-start taste picker.

### Modified Capabilities

- `media-availability`: Fully or partially available-title normalization includes validated Seerr-provided Plex web/app links and their flavor aliases.
- `media-browse`: The title detail modal offers experimental, accessible Plex Web and Plex App controls when a fully or partially available library title has usable links.
- `taste-signals`: Browser-supplied title ids use the shared database-safe upper bound.
- `media-requests`: Request title ids use the same bound before any Seerr or taste side effect.
- `user-auth`: The SPA retains a protected, in-memory handle to its script-opened Plex approval window and closes it best-effort after the existing PIN poll succeeds.

## Non-goals

- Reading or exposing Plex tokens, calling the Plex API, ingesting Plex watch history, or starting playback directly.
- Adding a new signal kind or changing recommendation weights/profile math.
- Guaranteeing that Plex Web or a native Plex app preserves the requested destination through sign-in or household-user selection.
- Building a separate onboarding catalog, onboarding route, or mandatory first-run flow.

## Impact

- Backend: Seerr wire models, availability domain/API models, title detail response, onboarding state/API, one additive SQLite migration, and security/boundary tests.
- Frontend: generated OpenAPI types, detail Plex Web/App controls, a best-effort auto-closing Plex approval popup with focus return, and a home-feed taste picker using existing feed titles and signal semantics.
- Systems: read-only Seerr integration only; no direct Plex traffic and no new dependency.
- Milestone: advances the PRD's post-v1 Play-in-Plex and onboarding-picker scope.
