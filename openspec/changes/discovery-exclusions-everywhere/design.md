## Context

See proposal.md for motivation. Current state:

- `catalog/discovery.py:DiscoveryFilter` is the single exclusion seam. The
  composer runs every rail except My List and Continue Watching through
  `filter()`, the hero and detail suggestions use the same instance, and
  personalized candidates go through `eligible()` before ranking. It holds
  household policy only (`hide_library_items`, `excluded_service_ids`) and spends
  one five-second verification budget per request.
- `CatalogService` builds the filter only when a household filter is on. It has
  three construction sites:
  - `api/catalog.py:get_catalog`, a synchronous dependency with no DB session,
    which serves Home, `/rails`, and title detail (and their taste service);
  - `api/taste.py:build_taste`, synchronous with no user id, used by household
    blend, explain, and profile refresh;
  - `api/taste.py:schedule_seed`'s factory, a background Seerr-seed write path
    that builds no filter.
- `TasteService._in_library` (ranking boosts) uses `DiscoveryFilter.in_library`
  whenever a filter exists, under the five-second deadline and the `_playable`
  rule. Otherwise it uses `availability.batch`. `ctx.discovery_filter is not None` is what "active
  filtering" means to the composer (refill, hero fallback, filtered-empty feed).
- `recommend/scorer.py`: `hidden_titles` (Not interested) excludes from
  personalized rails and My List; `engaged_titles` (strong positives, including
  `watched_plex`/`watched_jellyfin`) excludes from Recommended for You,
  unexpected picks, and blend. More Like excludes only hidden titles.
- `runtime_settings.py` has `DiscoverySetting` and `settings.py` has the
  `TASTERR_HIDE_LIBRARY_ITEMS` lock (`locked_discovery_fields`,
  `resolve_runtime`).
- The SPA invalidates only `["home"]` after watchlist / Not interested
  toggles; extra rails (`["rails"]`) and detail suggestions (`["title", …]`)
  keep stale results until they refetch.

## Goals / Non-Goals

**Goals:**
- One seam: personal exclusions ride the existing `DiscoveryFilter`, so every
  discovery surface gets them without per-rail code.
- No upstream cost for personal exclusions.

**Non-Goals:**
- Changing taste learning, the profile, or `engaged_titles` semantics.

## Decisions

1. **Personal set on the filter.** `DiscoveryFilter` gains
   `personal: frozenset[TitleKey]`. `filter()` and `eligible()` drop personal
   keys before any verification, so they never consume the verification
   budget or concurrency slots, and they still apply once the deadline has
   expired (the check sits before `_run`'s early return). `filter()` and `eligible()` still start the
   shared deadline on first use, as `_run` does today. Discover refill
   (`catalog/service.py`) bounds pages 2–3 with that deadline, and an unset
   deadline would leave refill unbounded on what becomes the default path.
   `CatalogService` builds the filter when any of
   library hiding, service exclusions, or a non-empty personal set applies.
   Ranking boosts keep their current path unless a household filter is on: the
   filter exposes `household_active`, and `TasteService._in_library` delegates to
   `DiscoveryFilter.in_library` only when it is true, otherwise using
   `availability.batch` as today. So a member whose only filtering is personal
   keeps today's Recommended for You ranking, and boost lookups stay outside the
   verification budget for them. The `discovery-filtering` delta states this
   exception.
   Alternative: filter in each provider, rejected as N copies of one rule.

2. **One store query.** `store.discovery_exclusions(db, user_id, *, watched:
   bool)` returns keys of the caller's active `not_interested` rows plus, when
   `watched` is true, every `WATCHED_KINDS` row. It ignores switched-off
   sources on purpose: hiding is not taste. `WATCHED_KINDS` becomes one
   constant in `recommend/signals.py` and replaces the literal pair in
   `recommend/service.py` (the Because You Watched label) and `store.py`;
   `UNIQUE_PER_TITLE_KINDS` and `STRONG_POSITIVE_KINDS` are rewritten as unions
   that include it. A future `watched_*` kind is then added in one Python place
   (plus the SQL index predicate `SIGNAL_UNIQUE_INDEX_WHERE`, which must stay
   literal). Only `get_catalog` calls it and passes the set in, becoming async
   and taking the DB session dependency to do so. That one site covers every
   surface the spec names (Home, `/rails`, title detail, and their personalized
   candidates). `build_taste` and the seed factory stay unchanged: blend already
   vetoes every participant's watched and dismissed titles, explain and profile
   refresh show no discovery list, and the seed factory writes signals only.
   `catalog/` stays free of `recommend/` and DB imports, as it is today (the
   boundary tests enforce only its httpx, `api`, and `settings` bans).

3. **Setting mirrors library hiding.** `hide_watched_items: bool = True` in
   `RuntimeSettings`; `DiscoverySetting` gains it; `TASTERR_HIDE_WATCHED_ITEMS:
   bool | None` joins the lock list and `resolve_runtime`. Existing documents
   resolve to true without migration. Default true is a deliberate behavior
   change, called out in the docs and release notes.

4. **Blend unchanged.** Blend's catalog comes from `build_taste`, which gets no
   personal set; its existing all-participant veto (from all signals, including
   switched-off sources) already excludes every participant's watched and
   dismissed titles, which is a superset of the caller's personal exclusions.

5. **"Active filtering" includes personal exclusions.** Because the composer
   keys refill, hero fallback, and filtered-empty behavior off the filter's
   presence, a member with any personal exclusion gets those behaviors. Discover
   rails (genre, decade, service, popular) refill up to three pages. Fixed-list
   rails such as Trending keep their existing bounds and only shrink: a heavy
   watcher's Trending may fall below its minimum size and drop, and the hero then
   falls back to the first surviving discovery rail, as the living spec already
   allows.

## Risks / Trade-offs

- [Discover refill (≤3 pages) now runs for most members with history] → bounded
  by the existing page cap and TMDB caching; no new upstream type.
- [Trending shrinks or drops for heavy watchers, since fixed lists don't refill]
  → accepted; discover rails refill, the hero falls back, and the upgrade docs
  say so.
- [A sampled-then-dropped series disappears from generic rails] → documented;
  Continue Watching and Search still reach it, and clearing history restores it.
- [Upgrade changes generic rails silently] → default-on is called out in
  `docs/CONFIGURATION.md` and release notes; one checkbox or the environment
  variable restores old behavior.
- [Personal set size] → bounded by the member's own signal rows (import caps
  apply); one indexed query per request.

## Migration Plan

No schema migration. Existing runtime documents gain `hide_watched_items: true`
on read. Image-only rollback is safe: older images ignore the extra field.

## Security considerations

- **Endpoints:** none added. Admin settings GET/PUT gain one boolean and lock
  metadata under the existing admin dependency, same-origin check, and admin
  bucket; Pydantic validates the field.
- **Auth & sessions:** none. The personal set is read for the authenticated
  caller only and never serialized; responses only omit titles, so no other
  member's data can leak (blend keeps its existing aggregate veto).
- **Outbound HTTP:** none added; personal exclusions make no upstream call.
- **Database:** read-only use of existing `signals` rows; no schema change.
- **Configuration:** `TASTERR_HIDE_WATCHED_ITEMS` is non-secret, boot-validated
  like `TASTERR_HIDE_LIBRARY_ITEMS` (explicit null or empty fails boot).
- **Frontend, dependencies, PublicConfig:** one admin checkbox with fixed text;
  no new dependency; `PublicConfig` unchanged.
