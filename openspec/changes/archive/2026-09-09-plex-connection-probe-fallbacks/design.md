## Context

See [proposal.md](proposal.md) for motivation. Plex discovery currently validates
and globally sorts advertised connection URLs, truncates the list to six, then
starts all selected identity probes concurrently and awaits their results in
priority order. A large local category can therefore exclude every fallback.
The same client is constructed independently for Home and background history.

## Goals / Non-Goals

**Goals:**

- Preserve a bounded probe set while ensuring every available connection category receives fallback coverage.
- Apply one validated setting consistently to Home and history discovery.
- Retain deterministic winner selection and every existing Plex trust boundary.

**Non-Goals:**

- Connection or credential caching, discovery retries, server allowlists, or changes to result-cache behavior.
- New services, abstractions, dependencies, or browser-visible configuration.

## Decisions

### Select categories locally in the Plex client

After existing URL validation and priority sorting, discovery reserves the first
candidate from each available local, remote-direct, and relay category. It fills
the remaining slots from the original sorted candidates not already selected,
then sorts the final selection with the existing priority key. Keeping this logic
inside server validation avoids a strategy abstraction and makes all callers use
the same selection.

Alternative: raise the fixed limit. Rejected because it only happens to cover the
observed resource and still lets one category crowd out all fallbacks.

### Keep concurrent probes and ordered awaits

The selected candidates are still started concurrently in deterministic priority
order and awaited in that order. Thus a faster lower-priority success does not
replace a slower preferred success. The existing `finally` cancellation and
gather remains responsible for awaiting unused probes.

Alternative: accept the first task to complete. Rejected because timing would
make winner selection nondeterministic and could prefer relay over local.

### Validate the configurable instance limit at both boundaries

`Settings` accepts `TASTERR_PLEX_MAX_CONNECTION_PROBES` with default 6 and range
3–12. `PlexMediaClient` takes a keyword-only value with the same default and
rejects values outside the same range, retaining the outbound bound for direct
callers. Both production constructors pass the setting explicitly. The minimum
of three leaves room for every available category; the maximum of twelve limits
operator-driven fan-out.

Alternative: mutate a module global. Rejected because client behavior would
depend on shared process state and tests/direct callers could bypass validation.

### Keep only the existing final-result cache

Continue Watching keeps its five-minute per-user positive/negative summary cache.
Discovery outputs remain call-local; history keeps its existing scheduling
throttle. A connection cache would retain sensitive, rotatable data without
removing the need for identity revalidation.

## Security considerations

- No API endpoint, authentication/session flow, database schema, or frontend code changes.
- Advertised values remain untrusted and are filtered before budgeting: HTTPS only; explicit-port `*.plex.direct`; no credentials, query, fragment, or non-root path.
- Standard TLS and hostname verification, five-second timeouts, disabled redirects, typed response parsing, exact machine identity matching, and the four-resource bound remain unchanged.
- Identity probes remain unauthenticated. Resource tokens are added only to later PMS reads through `X-Plex-Token`; browser headers are not forwarded.
- The configured 3–12 range fails closed and bounds extra unauthenticated probes. It is omitted from `PublicConfig` and OpenAPI browser contracts.
- No URL, machine identifier, token, rating key, title, account identity, or raw payload is added to logs, caches, durable rows, fixtures, or release evidence.
- No dependency is added, so dependency and lockfile review are unchanged.

## Risks / Trade-offs

- Higher configured values increase concurrent unauthenticated identity probes → enforce the hard maximum of twelve and document the cost.
- Reserving fallbacks reduces local candidates within a small budget → preserve local-first winner priority and fill every unreserved slot from the original ordering.
- Invalid deployment values prevent startup → document the accepted range; rollback is removing the variable to restore six.

## Migration Plan

Deploy with no configuration change to retain a six-probe limit. Operators may
set a value from 3 through 12 when their advertised topology needs a different
bound. Roll back code and remove the optional variable; no data migration or
cache invalidation is required.
