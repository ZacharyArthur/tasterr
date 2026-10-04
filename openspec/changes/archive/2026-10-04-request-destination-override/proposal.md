# Proposal: request-destination-override

## Why

`media-requests` (M3) always requests a title at Seerr's single configured
default server/profile/root folder — `POST /api/v1/request` only ever sends
`media_type` and `tmdb_id`. Households that register more than one destination
in Seerr for the same media type (e.g. separate root folders such as
`/movies`, `/new releases`, `/comedy specials`, each its own Seerr server entry
with its own default profile/root folder) have no way to choose a non-default
destination from Tasterr. Seerr's own "Advanced" request panel already supports
this per-request choice; Tasterr's simplified request flow currently has no
equivalent, which pushes anyone who needs a specific destination out of Tasterr
and into Seerr's native UI for that one action — undermining Tasterr's purpose
as the primary request surface. This advances `media-requests` (M3).

## What Changes

- **Destination discovery** (`clients/seerr.py`): new read methods against
  Seerr's existing service-discovery endpoints — `GET
  {SEERR}/api/v1/service/{radarr|sonarr}` (list of configured servers) and `GET
  {SEERR}/api/v1/service/{radarr|sonarr}/{id}` (that server's available quality
  profiles + root folders), authenticated by the **global** Seerr API key (this
  is configuration metadata, not a per-user action). Movie requests use
  `radarr`, TV requests use `sonarr`.
- **Destinations endpoint** (`api/request.py` or a new `api/destinations.py`):
  session-gated `GET /api/v1/{type}/{id}/destinations` returning the available
  `{server_id, server_name, quality_profiles: [{id, name}], root_folders: [{id,
  path}]}` options for that media type, each server's own default
  profile/root-folder flagged so the UI can preselect it. Seerr unconfigured or
  unreachable degrades to an empty list (no destinations to offer), same
  degradation posture as the rest of `media-requests` — never a hard failure
  that blocks requesting at the default.
- **Request override** (`clients/seerr.py` + `api/request.py`): `POST
  /api/v1/request` gains optional `server_id`, `profile_id`, `root_folder`
  fields, validated against that title's actual destination options (an
  override that doesn't match a real option from the destinations endpoint is
  rejected, not silently ignored or passed through unchecked) and forwarded to
  Seerr's existing `serverId`/`profileId`/`rootFolder` request fields. Omitting
  all three keeps today's behavior exactly as-is — this is additive.
- **Destination picker UI** (`RequestButton.tsx` / a new sibling component):
  when a title's destinations response reports more than one option, the first
  click on Request reveals Server / Quality Profile / Root Folder selectors
  (mirroring Seerr's own Advanced panel), preselected to the relevant default,
  instead of submitting immediately; a second click (labeled "Confirm request")
  sends it. Titles with a single (or no) configured destination see no UI
  change at all — Request still submits immediately.

## Capabilities

### Modified Capabilities

- `media-requests`: adds the destination-discovery read path and extends the
  request-creation requirement with optional, validated destination overrides.
  All existing requirements (attribution via per-user session cookie, re-auth
  ladder, redirect fallback, hardening/degradation, the live contract test)
  are unchanged — this only adds new, optional inputs to the existing flow.

## Impact

- **Backend**: `clients/seerr.py` gains two read methods (server list, server
  detail) reusing the existing global-key-authenticated pattern already used
  for availability reads; `create_request` gains three optional parameters.
  New endpoint wired into the router. No new dependencies, no migration.
- **Frontend**: new destinations query/hook in `lib/`; `RequestButton.tsx`
  (or a new component it composes) gains the conditional destination picker,
  surfaced on first click of Request rather than a separate toggle;
  `api.gen.ts` regenerated for the new/changed endpoints.
- **Tests**: destination-list mapping (pure), the request endpoint's override
  validation (rejects an option not present in that title's real destinations,
  accepts a valid one, omitted-override behavior unchanged), Seerr client
  contract tests for the two new read methods on `httpx.MockTransport`, and a
  live-marked contract test confirming a real override actually lands on the
  requested server/profile/folder in Seerr. Vitest for the picker's
  conditional visibility and selection state.

## Non-goals

- **Per-season destination overrides for TV** — a TV request still requests
  the whole series at one chosen destination; season-level granularity is out
  of scope here, same as it already is for quality in the base requirement.
- **Caching the destinations list** — this is small, infrequently-changing
  configuration data fetched on demand when the request UI opens; no new cache
  layer is justified for it.
- **Letting a destination override bypass or change request attribution,
  the re-auth ladder, or the redirect fallback** — those requirements are
  untouched; the override only changes *where* an otherwise-identical request
  lands.
- **Exposing Seerr's internal server list/structure beyond the options needed
  to render the picker** — the destinations endpoint returns only what the UI
  needs (names, ids, paths), not Seerr's full service configuration.
