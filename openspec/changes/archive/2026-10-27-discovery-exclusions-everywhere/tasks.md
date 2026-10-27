## 1. Setting and lock

- [x] 1.1 Add `hide_watched_items: bool = True` to `RuntimeSettings` and `DiscoverySetting`; add `TASTERR_HIDE_WATCHED_ITEMS` to `Settings`, the lock list, and `resolve_runtime`. Verify with tests: fresh and old documents resolve true, explicit `false` overrides and locks, a locked save preserves the stored value, explicit null, empty, or an invalid value such as `maybe` fails boot.

## 2. Personal exclusions

- [x] 2.1 Add `WATCHED_KINDS` to `recommend/signals.py`, define `UNIQUE_PER_TITLE_KINDS` and `STRONG_POSITIVE_KINDS` as unions that include it, and use it in place of the literal watched-kind pairs in `recommend/service.py` and `recommend/store.py`; add `store.discovery_exclusions(db, user_id, *, watched)` returning the caller's active `not_interested` keys plus watched keys when asked, ignoring switched-off sources. Verify with store tests: retracted Not interested is absent, cleared history rows are absent, watched rows of a switched-off source are present, another user's rows are absent.
- [x] 2.2 Give `DiscoveryFilter` a `personal` key set applied in `filter()` and `eligible()` before verification, and a `household_active` property. Build the filter in `CatalogService` when any household filter or a non-empty personal set applies, and make `TasteService._in_library` delegate to the filter only when `household_active`, otherwise using `availability.batch` as today. Verify with unit tests:
  - personal keys are dropped with no availability or facts call and no verification slot used, while `filter()` still starts the shared deadline;
  - personal keys are still dropped after the shared deadline has expired (the personal check runs before `_run`'s early return, not inside `_check`);
  - household-off plus a personal set still filters;
  - with only personal exclusions, ranking boosts use `availability.batch` and the same boost rule as today (a service test pins this);
  - with a household filter on, boosts still go through the filter as today.
- [x] 2.3 Load the caller's set in `get_catalog` only, using `hide_watched_items`. `get_catalog` in `api/catalog.py` is a synchronous dependency without a DB session today, so it becomes async and takes the DB session dependency, keeping its session-before-config 401/503 order. `build_taste` and the `schedule_seed` factory in `api/taste.py` stay unchanged. Verify with API tests (with fixtures covering a watched movie and a series with one watched episode): a watched title is absent from Trending while a second member who has not watched it still sees it there, a genre rail, an extra page, the hero, More Like / Because You Watched, and detail recommendations; a Not interested title is absent with watched hiding off; Search, My List, Continue Watching, and direct detail still return them; with the setting off and no dismissals, no filter is built (existing default-path tests unchanged); the caller's signal rows and profile vector are identical with watched hiding on and off; a household blend that includes the caller excludes their watched and Not interested titles.
- [x] 2.4 Verify refill and filtered-empty with personal exclusions: a discover rail emptied by watched titles refills within three pages; with only personal exclusions and TMDB stalling on page 2, the rail returns its page-1 survivors once the shared deadline expires; Trending (a fixed list) only shrinks and is dropped below its minimum, with the hero falling back to the first surviving discovery rail; and a Home whose fetched titles are all excluded returns a successful empty feed. Verify with composer tests.

## 3. Frontend

- [x] 3.1 Regenerate `api.gen.ts`; add a "Hide titles members have watched" checkbox beside library hiding in Settings with the existing lock display and best-effort note. Verify with Vitest: renders effective value, read-only when locked, included in the save payload, and shows the explanation text the `app-settings` delta requires (each member's own watched titles; Not interested always hides).
- [x] 3.2 Make Not interested refresh visible discovery: `lib/taste.ts` invalidates only `["home"]` today; also invalidate `["rails"]` (extra rails) and `["title"]` (detail suggestions). Verify with a Vitest case asserting all three invalidated query keys.

## 4. Documentation

- [x] 4.1 Document `hide_watched_items` and `TASTERR_HIDE_WATCHED_ITEMS` in `docs/CONFIGURATION.md` (default on, per-member effect, series collapse, exempt surfaces, upgrade behavior change including that discover rails refill while Trending can shrink or disappear for heavy watchers), `.env.example`, and `compose.example.yaml` (commented, like `TASTERR_HIDE_LIBRARY_ITEMS`); add the default-on behavior change to `docs/releases/unreleased.md`. Verify `test_docs.py` and `test_env_example.py` pass under `just check`.

## 5. Gate

- [x] 5.1 Before archiving, compare each MODIFIED block in `specs/` with the current `openspec/specs/` text and fold in anything a change archived since this one was written added. Verify with `openspec validate discovery-exclusions-everywhere --strict`.
- [x] 5.2 Run `just check` inside the devcontainer and fix any failures until it passes.
