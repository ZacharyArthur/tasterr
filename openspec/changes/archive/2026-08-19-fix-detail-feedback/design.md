## Context

See [proposal.md](proposal.md) for motivation. Detail routes currently retain
each active title in browser history, `inert` protects focus but not document
scrolling, and taste toggles initialize local optimistic state only once. The
frontend security checklist also requires external URLs to originate in the BFF.

## Goals / Non-Goals

**Goals:**

- Correct the shared route, overlay, and toggle boundaries with small local
  changes.
- Keep the detail response and generated frontend client typed end to end.
- Preserve direct detail deep links, browse focus restoration, and optimistic
  interaction behavior.

**Non-Goals:**

- A reusable modal manager or navigation abstraction.
- Client-side cache-wide optimistic updates for every detail field.
- Provider ID lookup for IMDb/TVDB or Plex playback integration.

## Decisions

### Replace a detail route when a card is opened from another detail

`MediaCard` will distinguish a title route from a browse route. From browse it
continues to push a modal route carrying the current location. From an active
detail it replaces that route and preserves the original background location;
a direct detail keeps no synthetic background. This makes Close retain its
existing back-or-Home behavior while collapsing arbitrary related-title chains.

Passing bespoke navigation callbacks through the More like this tree was
rejected because route history already owns this behavior and the shared card is
the point where every title navigation is formed.

### Lock the document for the overlay's lifetime

`DetailModal` will snapshot `document.body.style.overflow`, set it to `hidden`
while mounted, and restore the snapshot during effect cleanup. The overlay keeps
its existing `overflow-y-auto`, so long detail content remains scrollable.

A global modal/scroll-lock utility is unnecessary while the app has one overlay.

### Resynchronize optimistic toggle state from refreshed detail flags

`useTasteToggle` will update its local active value when its `initial` argument
changes. The keyed detail body still isolates different titles, while the sync
handles the same title rendering cached flags followed by a fresher response.

Writing partial `MediaDetail` values into TanStack Query's cache on every signal
was rejected as more coupling for no additional user-visible behavior.

### Construct the canonical TMDB URL in the backend detail model

The normalizer will add a required `external_url` using the fixed HTTPS TMDB
origin, validated media type, and numeric title ID. React will render only that
typed response field with `target="_blank"` and `rel="noopener noreferrer"`.
Regenerating the OpenAPI client keeps the field single-sourced.

Client-side construction was rejected by the frontend security checklist.
IMDb/TVDB links were rejected because current catalog data does not carry their
IDs and another upstream lookup is not justified for this request.

### Re-enter dialog focus when related content replaces the title

`DetailModal` will focus the dialog container only when the route's title
identity changes. This makes the newly labelled dialog the explicit focus target
after the focused related card unmounts, while leaving initial focus and final
restoration to the existing focus trap. The trap will treat focus outside its
enumerated controls, including the programmatically focused dialog container, as
a boundary: Tab moves to the first control and Shift+Tab wraps to the last.

Remounting the entire dialog was rejected because it would disrupt the overlay
lifecycle and its reference to the original opening control.

## Security considerations

- No endpoint, auth, session, database, or outbound HTTP behavior changes. The
  existing authenticated title endpoint and explicit `MediaDetail` response
  model remain in place.
- `external_url` is an allowlisted server-generated HTTPS URL whose origin and
  path kind are constants; no browser or upstream URL is forwarded and no secret
  is exposed.
- React renders catalog text normally; no HTML injection path is introduced.
  The external link prevents opener access, and project-wide response security
  headers remain unchanged.
- Browser tests use invented fixtures and make no live requests.
- No dependency is added, so neither lockfile changes.

## Risks / Trade-offs

- [A future second simultaneous overlay could restore scroll too early] → The app
  currently renders exactly one route-driven detail overlay; introduce a shared
  lock counter only if overlapping overlays are added.
- [Replacing related-title history removes Back traversal between details] → This
  is intentional and matches the reported expectation that detail browsing is a
  single overlay session.
- [The backend URL couples the response to TMDB's public route format] → The
  stable, fixed pattern is isolated to one normalizer expression and can be
  changed without touching the SPA.

## Migration Plan

Regenerate the OpenAPI client, ship backend and frontend together in the existing
single image, and require no data migration. Roll back by deploying the previous
image; persisted data is unaffected.
