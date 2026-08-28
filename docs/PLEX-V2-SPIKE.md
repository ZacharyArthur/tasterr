# Plex v2 Live Contract Spike

Run date: 2026-08-25

Status: **passed**. Verified TLS/machine identity, exact per-row history
isolation, account-scoped Continue Watching, canonical movie/show TMDB mapping,
and viability of the current PIN-issued token format were demonstrated for the
available owner, managed, and shared roles.

## Safety scope

The probe used operator-supplied credentials locally and emitted only status
codes, field names, connection shapes, versions, and generic results. It did not
record tokens, connection URLs, server/account/household identifiers, rating
keys, titles, timestamps, or raw upstream bodies. Redirect following was
disabled and normal certificate and hostname verification remained enabled.

## Observed contract

| Area | Redacted observation | Result |
| --- | --- | --- |
| Account identity | `GET /api/v2/user` returned 200 for all three roles. The numeric cloud account field is `id`; observed identity fields include `uuid`, `username`, `title`, `email`, `restricted`, and `home`. A managed account returned an empty username, consistent with managed users not requiring one. | Pass |
| PMS account resolution | Owner-capable `GET /accounts` returned local `Account` rows with `id`, `key`, `name`, and preference fields; an unrelated non-user row used id `0` and was ignored. The owner cloud id did not match its positive local id, so one case-insensitive exact validated-username-to-`Account.name` match resolved it. A managed server token returned 403 for `/accounts`; its validated positive cloud id exactly matched every returned self-only history row. Other `/accounts` failures remain fatal. | Pass with explicit-403 non-admin fallback |
| Token format | All three PIN-issued account tokens used the traditional non-JWT format and successfully accessed account and resource endpoints. | Pass; no JWT migration needed |
| Resources | `GET /api/v2/resources` returned 200 for all roles. Server entries expose `accessToken`, `clientIdentifier`, `owned`, `provides`, and `connections`; owned-first ordering is observable. | Pass |
| Resource paging | Standard `X-Plex-Container-Start`/`Size` request headers produced no pagination response headers and offset requests did not produce distinct pages. | Treat as one bounded response |
| Connection policy | The accepted connection was HTTPS on a `*.plex.direct` hostname with an advertised non-default port. Other unavailable advertised connections failed as transport failures. | Pass with partial-failure degradation |
| TLS and identity | A connection completed with standard TLS verification and unauthenticated `/identity` returned the advertised `machineIdentifier`. PMS version `1.43.3.10896-cb3ebc72d` was observed. | Pass |
| Redirects | The client did not follow redirects; no redirected connection was accepted. | Pass |
| History shape | `GET /status/sessions/history/all` returned 200 for all roles after PMS-local account resolution. Rows used `accountID`, `viewedAt`, `type`, `ratingKey`, and `key`; episode rows also used `parentIndex` and `index`. Every observed row exactly matched the requested local account id with both caller-scoped and owner-capable resource tokens. | Pass |
| History paging/order | Response pagination headers and body offsets were observed; one-row pages were distinct and bounded rows were newest-first by `viewedAt`. | Pass |
| Continue Watching | `GET /hubs/continueWatching` returned 200 with items nested under `MediaContainer.Hub[].Metadata`. All roles returned pairwise-distinct results through distinct resource tokens, and each role's newly seeded resume item was absent from the other role results. Items expose `lastViewedAt`, `viewOffset`, and `duration`; episode items also expose `parentIndex`, `index`, and `grandparentRatingKey`. Valid 1–99 progress was observed for every role. | Pass |
| Canonical mapping | Bounded history/hub items omitted TMDB GUIDs. Metadata expansion with `includeGuids=1` exposed `Guid[].id`; movie lookup and episode `grandparentRatingKey` to show lookup both resolved positive `tmdb://` ids. | Pass |
| Multi-server behavior | The household did not expose multiple common servers. Connection-level partial failure was observed; server-level partial failure still requires invented fixtures. | Live case unavailable |

## Reconciliation checkpoint

- Account-scoped history first resolves a call-local PMS account id from
  `/accounts`. Prefer one exact numeric `id`/`key` match to `/api/v2/user.id`;
  when absent, require one case-insensitive exact `Account.name` match to the
  validated username. If and only if a non-admin server token explicitly receives
  403 from `/accounts`, use the validated positive cloud id as the filter; the
  [Plex history contract](https://developer.plex.tv/pms/) limits non-admin tokens
  to their own rows. Every
  returned row must still exactly match that id. Other endpoint failures and
  ambiguous, conflicting, missing, or malformed list resolution fail the server.
- Resource discovery is a single bounded response; production code must not add
  unsupported resource pagination.
- Connections are limited to advertised HTTPS `*.plex.direct` hosts with their
  explicit advertised ports, standard TLS verification, exact machine identity,
  and no redirects.
- Traditional PIN-issued tokens are viable for the required reads. JWT support
  remains out of scope unless a later supported token stops satisfying them.
- Movie and episode-to-show joins require metadata GUID expansion; title/year
  matching remains prohibited.
- History merge time is `viewedAt`; Continue Watching merge time is
  `lastViewedAt`.
- Server and connection failures degrade independently; bounded invented fixtures
  must cover multi-server partial success because the live household cannot.
- Continue Watching isolation is proved with distinct resource tokens,
  pairwise-distinct caller results, and an exclusive newly seeded resume item for
  every role.
- All hard-gate assumptions are reconciled. Production implementation may
  proceed with the PMS-local account-resolution rule above.

## Opt-in suite rerun

Run date: 2026-08-27

The five-test opt-in suite passed for the supplied owner, managed, and shared
tokens against PMS `1.43.3.10896-cb3ebc72d`. It exercised token validity,
unpaged bounded resource selection, standard TLS plus machine identity,
owner-list and explicit-403 non-admin account resolution, distinct one-row
history pages with exact `accountID` checks, caller-isolated Continue Watching,
`lastViewedAt` merge ordering, and movie plus episode-to-show TMDB GUID mapping.

## Cold-path timing follow-up

Run date: 2026-08-27

A redacted single-server timing check took 2.23 seconds for account identity and
22.94 seconds for serial resource discovery. The first five of six advertised
connections failed or timed out before the sixth verified in 0.26 seconds. Once
connected, the Continue Watching hub returned 20 bounded items in 0.07 seconds.
This evidence supports concurrent bounded identity probes and a ten-second
aggregate Continue Watching deadline; connection URLs and identifiers were not
retained.
The timing did not measure the metadata/GUID expansion required by the observed
hub rows. Production therefore orders eligible rows newest-first and caps that
expansion at 20 distinct per-server rating keys before canonical merge, rather
than allowing up to 200 metadata lookups inside the aggregate deadline.
No live case was available for multiple common servers; invented fixtures retain
that coverage.
