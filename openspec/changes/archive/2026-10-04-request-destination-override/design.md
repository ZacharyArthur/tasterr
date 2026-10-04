# Design: request-destination-override

## Approach

**Destination discovery is a separate read, not folded into the detail/availability
response**, because it's only needed at the moment someone opens the request
control, it changes far less often than availability, and keeping it a distinct
endpoint keeps `GET /title/{type}/{id}` from growing a dependency on
Radarr/Sonarr-specific shapes it doesn't otherwise need.

`GET /api/v1/{type}/{id}/destinations` calls Seerr's existing
`service/{radarr|sonarr}` (list) and `service/{radarr|sonarr}/{id}` (profiles +
root folders) endpoints, authenticated with the **global** key — this is
household configuration metadata (what destinations exist), not a per-user
action, same reasoning the existing availability read already uses. The `{type}` path parameter decides Radarr versus Sonarr dispatch. The bounded
`{id}` preserves the validated title route shape and is otherwise unused.

**The override is validated server-side against that title's real destinations,
not merely type-checked.** `POST /api/v1/request` already validates `media_type`/
`tmdb_id` shape; the new optional `server_id`/`profile_id`/`root_folder` go
through an additional check — re-fetch (or reuse an in-request cache of) that
title's destinations and reject an override that doesn't match a real
server/profile/folder combination for it, rather than forwarding whatever the
client sent straight to Seerr. Seerr stores unknown server ids and can fail only during dispatch, so this
validation prevents silently failed requests. Shape errors are rejected before
reads; destination membership is checked before request creation. Failed reads
retain the generic request failure and configured redirect fallback.

**Omitting all three override fields is byte-for-byte today's request body** —
the existing `media-requests` behavior, tests, and the live contract test for
plain requests are unchanged. This is additive only.

## Security considerations

Per `docs/SECURITY.md`, the relevant checklists are **"Any new or changed API
endpoint"** and **"Outbound HTTP"**; auth/session, database, frontend-rendering,
and dependency checklists are unaffected (no new dependency, no new table, no
new client-rendered HTML).

**New endpoint — `GET /api/v1/{type}/{id}/destinations`:**
- Auth: session-gated, default-deny, same dependency as the rest of the
  authenticated API surface. It's a read, so no CSRF/mutation-rate-limit
  applies (consistent with how the existing availability read is treated).
- Input: `{type}` constrained to `movie`/`tv` (reusing the existing media-type
  validator), `{id}` the same bounded-integer TMDB id validation `/request`
  already applies.
- Output: an explicit, secret-free response model — server id/name,
  profile id/name, root-folder id/path, and which is the default. No raw Seerr
  JSON passthrough; unknown upstream fields are dropped by the typed model, not
  forwarded.
- Degradation: Seerr unconfigured or unreachable returns an empty destinations
  list (so Request submits immediately with no picker), not an error — matches
  the existing "Seerr down degrades, never blocks" posture. No upstream error
  body, status, or internal URL reaches the client.

**Modified endpoint — `POST /api/v1/request`:**
- The three new fields are optional, Pydantic-validated (`server_id`/
  `profile_id` bounded integers, `root_folder` a plain string compared against
  the title's real root-folder paths — never interpolated into a path or used
  for anything filesystem-adjacent on Tasterr's own side, it is only ever
  forwarded to Seerr as a JSON field).
- An override that doesn't match a real destination for that title is rejected
  (`422`) before any Seerr request creation. Shape validation occurs before
  reads; membership validation requires configuration reads.
- Everything else about the endpoint (auth, CSRF, rate limit, re-auth ladder,
  redirect fallback, error shape) is unchanged by this addition.

**Outbound HTTP (`clients/seerr.py`):**
- The two new read methods call `SEERR_INTERNAL_URL` from validated settings,
  same base-URL source every existing Seerr call uses — no user input ever
  reaches the outbound URL (SSRF-safe by construction, same as today).
- Same bounded timeout as the existing availability/request calls; no retry
  storm.
- Upstream JSON parsed into typed models (server, profile, root-folder shapes);
  unrecognized fields are dropped, not passed through.

**Logging:** no new credential, cookie, or PII-bearing field is introduced;
root-folder paths and profile names are household configuration, not secret,
and are not excluded from this change's test fixtures/evidence on that basis —
but no new log statement in this change includes upstream response bodies,
matching the existing generic-error convention.

## New dependencies

None — reuses `httpx` and the existing typed-client/response-model patterns
already in `clients/seerr.py` and `api/request.py`.


## Review revision

Superseded in this PR by `request-variants-and-review-fixes`: discovery is
permission-scoped, Standard/4K variants are explicit, and unchanged confirmation
uses Seerr defaults (including anime defaults). Upstream administrator rules remain
authoritative; stored request fields do not prove actual downstream delivery.
