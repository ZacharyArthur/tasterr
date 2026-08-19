## Why

Real household use exposed friction in the title-detail experience: related-title
navigation builds a stack of modals, the feed can scroll behind the overlay, and a
recently changed My List state can briefly reopen stale and require an extra click.
The same feedback also asked for a direct catalog reference from the detail view.

This is post-v1 polish of the existing `media-browse` capability, originally
delivered by the M2 browse and M4 taste milestones.

## What Changes

- Replace the current detail route when opening a related title so one Close action
  returns to the original browse view.
- Lock document scrolling while the detail overlay is mounted, without preventing
  the overlay itself from scrolling.
- Resynchronize optimistic taste controls when refreshed detail data supplies newer
  watchlist or hidden state.
- Add a backend-supplied TMDB title URL to the typed detail response and expose it as
  an accessible external link in the detail view.
- Add focused regression coverage for route closing, scroll cleanup, refreshed
  toggle state, and the external link.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `media-browse`: Tighten detail-overlay navigation, scrolling, taste-state
  freshness, and external catalog-link behavior.

## Impact

- Backend catalog detail model/normalization and generated OpenAPI client types.
- Frontend detail routing, overlay lifecycle, taste-toggle state, and component
  tests.
- No database migration, new dependency, or new outbound request.

## Non-goals

- Plex deep links or forcing playback into a native Plex app.
- IMDb or TVDB links, which would require additional provider identifiers.
- Changes to recommendation scoring, Seerr requests, or watchlist persistence.
