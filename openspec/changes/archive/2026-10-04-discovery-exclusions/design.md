## Context

See proposal.md. The rail composer handles most discovery; taste candidates and related-title lists have separate seams. Seerr status is cached for 60 seconds with no stale fallback. Recommendation feature records retain provider IDs for 30 days; current TMDB detail data has a six-hour TTL and existing stale-on-error behavior.

## Goals / Non-Goals

Share one eligibility policy and verification budget within each request. Keep taste sources intact and filtering independent of ranking math. No new dependency, library scan, database schema, or generalized rules engine.

## Decisions

- Add a small settings-free catalog discovery filter with primitive preferences, catalog and availability dependencies. Store completed checks per request and serialize overlapping same-title checks before acquiring a verification slot, including request-local Unknown outcomes. Use one five-second deadline from the first verification, concurrency eight, cancelling unfinished verification at expiry. Unknown titles remain eligible. Reuse bounded library reads for recommendation boosts rather than starting another unbounded batch. Do not change Seerr's global failure-cache policy.
- Check both regular and 4K statuses for available/partial. Use current cached TMDB title facts for region-scoped flatrate provider membership rather than persisted feature records. Raise the shared catalog cache from 1,024 to 4,096 entries for household verification working sets; keep the Seerr capacity and existing freshness/stale contracts unchanged. No separate provider cache or new configuration knob. The larger entry bound costs memory and does not guarantee warmth; no live household working-set measurement was performed.
- Filter candidates before ranking and generic discovery before rail minimum/deduplication. Explicitly exempt My List and Continue Watching. With filtering active, prefer Trending then the first surviving discovery rail for the hero; exclude intentional lists from this pool and still independently check eligibility. Keep the existing first-rail fallback when filtering is inactive. Filter related-title child lists only; direct details and search remain accessible. Drain the parallel title availability task on every exit, including suggestion errors and request cancellation.
- With active filters, discover sources fetch at most three pages to seek 20 eligible items, stopping at source exhaustion or verification-budget expiry. Additional page fetches use the remaining deadline and retain earlier results on timeout. Preserve initial source requests and default one-page behavior when inactive. Skip excluded service rails before fetching. Keep selected-service inclusion narrowing even when every selected service is excluded. Successfully empty catalog sources and filtered-empty home are successful results; total catalog failures remain failures even when an exempt rail is underfilled. Exempt list contents do not establish catalog success.
- Add `hide_library_items` and `excluded_service_ids` to runtime preferences (at most eight unique positive provider IDs). Optional `TASTERR_HIDE_LIBRARY_ITEMS` and JSON-array `TASTERR_EXCLUDED_SERVICE_IDS` override persisted preferences only when explicitly set, including false/empty. Keep stored values separate from effective values; admin API returns effective settings and an allowlisted list of locked fields. PUT preserves stored values of locked fields, updates other preferences, and returns effective settings.
- Region changes in the admin screen clear editable exclusions, retain overridden IDs, and explain overlap with selected services. Missing regional provider options remain removable using ID-labelled controls, including during metadata errors; pending labels distinguish loading from missing options and the shared eight-service UI bound shows a reached message. Confirmed saves cancel pending config/home/rails/title reads before invalidating them, preventing initial pending reads from restoring old discovery. Session guards run before cancellation and again after awaiting it. Saves also increment a client-local query-cache revision and remount household results independently of navigation/member refetches. This discards old mutation observers, including blends started after leaving Settings while the save was pending. Ordinary member refetches preserve completed and pending blends. Existing inclusion preferences and taste signals remain intact.
- Home records explicit success from personalized candidate source detail/discover/trending reads, including cache hits and empty lists. My List, profile/vector construction, genre metadata and eligibility verification do not establish source success. With filtering active, a successfully read personalized source permits empty Home even with ordinary catalog rails disabled. No signals or all enabled sources failing retain the existing error when no rail survives. Remove the former removal flag entirely. CatalogService owns and creates the active filter; rail/taste callers read that one handle. A TaskGroup drains sibling verification on unexpected errors as well as expiry, without swallowing programming errors.

## Security considerations

API: reuse session/admin dependencies, CSRF and admin mutation limits; only typed preferences and lock names are exposed. PublicConfig stays unchanged. No new mutation route, secret, cookie, credential, or browser-built URL. Validate IDs, uniqueness and limits in environment and API input; malformed env values fail startup validation rather than silently weakening filtering.

Outbound: only existing clients issue HTTP against existing validated base URLs. Fixed concurrency/deadline/page bounds, typed upstream data, no browser headers/raw payloads forwarded. Cancellation drains tasks; no detached verification work or duplicate unbounded availability batch.

Frontend: native labelled controls, text rendering, visible locks/error states; no storage of secrets or raw HTML. Database: existing JSON persistence and SQLAlchemy operations; locked overrides are never written into stored preferences. No migration or token changes. Logging stays generic without household title/identity/environment data. Dependencies: none.

## Risks / Trade-offs

- Cold caches or outages can leave unverified titles visible -> explicit best-effort wording, shared deadline and regression checks.
- Subscription metadata can be stale or incomplete -> retain existing documented TMDB cache policy and active region, avoid 30-day vectors as truth.
- Aggressive exclusions can empty discovery -> bounded refill, existing rail floors and a valid empty state; intentional lists remain accessible.
- Selected/excluded overlap narrows existing inclusion results -> exclusions win, skip conflicting service rails, explain in Settings.
- Confirmed settings saves keep existing cached discovery visible during refresh; pending pre-save responses cannot become the refreshed feed. This preserves ordinary background-refresh behavior rather than replacing cached content with a loading screen.
- An empty source's first filter call starts the shared clock so a following refill cannot run without a deadline. Moving clock initialization after the empty-check guard would break this existing bounded-refill contract.

## Migration Plan

Deploy backend and generated frontend together. Existing JSON rows gain defaults without migration. Rollback code together; extra JSON fields remain harmless to the prior model. Keep the change active for review, then archive on the branch before the eventual commit/PR workflow.
