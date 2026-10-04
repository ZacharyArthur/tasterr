# Tasks: request-destination-override

## 1. Seerr client — destination-discovery reads

- [x] 1.1 `clients/seerr.py`: add `list_servers(media_type)` — `GET
      /api/v1/service/{radarr|sonarr}` with the global `X-Api-Key`, same bounded
      timeout/no-retry posture as the existing availability read, parsed into a
      typed server-list model (id, name, is_default, active_profile_id,
      active_directory). `httpx.MockTransport` tests: 200 parse, empty list,
      `5xx`/timeout → typed upstream error, global key attached.
- [x] 1.2 `clients/seerr.py`: add `server_destinations(media_type, server_id)` —
      `GET /api/v1/service/{radarr|sonarr}/{server_id}` parsed into a typed
      profiles + root-folders model. Tests: 200 parse, unknown server id → typed
      upstream-unavailable, `5xx`/timeout → typed upstream error.

## 2. Destinations API endpoint

- [x] 2.1 New `api/destinations.py` (or extend `api/request.py`): session-gated
      `GET /api/v1/{type}/{id}/destinations`, `{type}` reusing the existing
      media-type validator and `{id}` the existing bounded-integer tmdb-id
      validator (the id only decides radarr-vs-sonarr dispatch). Calls
      `list_servers` then `server_destinations` per server, returns an explicit
      secret-free response model (server id/name, profiles id/name, root
      folders id/path, each server's default profile/root-folder flagged).
      Seerr unconfigured or any upstream error degrades to an empty list, not a
      failure response. Register the router. Tests: `401` unauthenticated,
      single-server shape, multi-server shape, Seerr unconfigured → empty list
      with no call, Seerr down → empty list with no upstream body leaked.

## 3. Request endpoint — optional, validated override

- [x] 3.1 `api/request.py`: extend the request body with optional
      `server_id: int | None`, `profile_id: int | None`, `root_folder: str |
      None`. Before calling Seerr, when any override field is present, fetch
      that title's destinations (reusing task 2.1's logic) and reject (`422`)
      if the combination doesn't match a real server/profile/root-folder for
      it — no Seerr call on a rejected override. Tests: valid override is
      accepted and forwarded, an override not present in that title's real
      destinations is rejected before any Seerr request creation, all-omitted override
      behaves byte-for-byte as today (existing tests still pass unmodified).
- [x] 3.2 `clients/seerr.py`: extend `create_request` to accept the optional
      `server_id`/`profile_id`/`root_folder` and include Seerr's
      `serverId`/`profileId`/`rootFolder` fields in the request body only when
      provided. Tests: override fields present in the outgoing body when given,
      absent when omitted (byte-for-byte today's payload).

## 4. Frontend — destination picker

- [x] 4.1 Regenerate `api.gen.ts` from the updated backend OpenAPI schema for
      the new destinations endpoint and the extended request body.
- [x] 4.2 New `lib/` query hook for the destinations endpoint (TanStack Query,
      same caching/error conventions as the existing availability hooks).
- [x] 4.3 `RequestButton.tsx`: when the destinations query reports more than
      one option (multiple servers, or a single server with multiple root
      folders/profiles), the first click on Request reveals Server / Quality
      Profile / Root Folder selects preselected to the flagged default instead
      of submitting; a second click ("Confirm request") submits with the
      current selection. Zero or one destination → Request still submits
      immediately, no UI change from today. Vitest: picker hidden for a single
      destination with no other options, picker shown + selects populated when
      there's a choice, selection included in the submitted request, confirming
      an unchanged selection sends the default destination explicitly.

## 5. Spec, contract coverage, and gate

- [x] 5.1 Add a live-marked contract test (excluded from `just check`) that, when
      operator-run, verifies stored server/profile/root-folder fields and
      records the observed Seerr version. Execution remains opt-in.
- [x] 5.2 Run `just check` and fix any failures.


Review evidence correction: the initial live test did not assert destination
fields and was not run against a household instance. The supplemental
request-variants-and-review-fixes change replaces it with production-client
persistence assertions, version recording, and optional 4K coverage. Downstream
delivery remains operator-verified.
