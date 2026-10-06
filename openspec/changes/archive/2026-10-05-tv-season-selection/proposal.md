# Proposal: tv-season-selection

## Why

`media-requests` always asks Seerr for the whole series when a member requests
a TV title (`"seasons": "all"`). Members often want only part of a show:
seasons 4-5 because 1-3 are already on hand, or a single season to replace a
corrupt or lower-quality copy. Seerr's own request modal lists every season,
Specials included, as a toggle, and its request API already accepts an
explicit list of season numbers in place of `"all"`. Tasterr is a front end
over Seerr, so this exposes a capability Seerr already has rather than adding
new acquisition logic. Without it, anyone who needs a subset has to leave
Tasterr for Seerr's UI for that one action.

## What Changes

- **Seerr client** (`clients/seerr.py`): `create_request` gains an optional
  `seasons: list[int]`. When given for a TV title it is forwarded as Seerr's
  `seasons` array; omitted keeps `"all"` exactly as today.
- **Request endpoint** (`api/request.py`): `RequestBody` gains optional
  `seasons` — a non-empty list of unique season numbers, each 0-1000 (0 is
  Specials). It is rejected with `422` before any upstream read when sent for
  a movie, empty, out of range, or duplicated. The list is forwarded unchanged
  through the re-auth retry.
- **Catalog** (`catalog/normalize.py`): the title detail keeps TMDB's Specials
  (season 0) so the request flow can offer it. The detail page's own season
  list still hides it.
- **Season dialog** (`SeasonPicker.tsx`, `RequestButton.tsx`): for a TV title
  with more than one season entry, Request opens a dialog listing every season
  and Specials (when the show has them), each with a toggle, an "All seasons"
  toggle, **OK** and **Cancel**. Regular seasons start on and Specials off —
  the same set Seerr's `"all"` covers — so OK without changes sends today's
  exact body; only a different choice sends `seasons`. Movies and
  single-season shows keep the one-click request. The dialog reuses the detail
  modal's overlay, panel and button tokens.
- **Focus trap** (`lib/useFocusTrap.ts`): traps stack, so Escape and Tab go to
  the innermost dialog and the page behind stays inert until the last closes.

## Capabilities

### Modified Capabilities

- `media-requests`: the request requirement accepts an optional, validated
  season list for TV; a new requirement covers the season dialog. Attribution,
  re-auth ladder, fallback, permissions, variant and destination rules are
  unchanged.

## Impact

- **Backend**: one optional field and validator on `RequestBody`; one optional
  parameter threaded through `_request_with_reauth` and
  `SeerrClient.create_request`; Specials kept in the detail response. No new
  endpoint, dependency, or migration.
- **Frontend**: new `SeasonPicker` component; `RequestButton` gains a
  `seasons` prop; `DetailModal` passes the title's seasons and hides Specials
  from its own list; `useFocusTrap` supports nesting; `api.gen.ts`
  regenerated.
- **Tests**: client body shape for a subset; endpoint validation rejected
  before reads; subset preserved across the re-auth retry; Specials kept by
  normalization; Vitest for dialog defaults, default body, subset with
  Specials, empty-selection block, cancel reset, Escape closing only the
  dialog, and single-season direct request.

## Non-goals

- **Requesting more seasons of a partially available or already requested
  show.** Such titles are not requestable today (`409` / no Request button);
  per-season status and top-up requests are a separate change.
- **Validating season numbers against TMDB on the server.** Explicit arrays
  are bounded and unique but are not checked for existence. Seerr 3.5.0 removes
  disabled Specials and already requested or available seasons; it does not
  validate the remaining numbers against TMDB. A hand-crafted nonexistent
  season can consume the member's own quota. Server-side catalog validation
  remains outside this change.
