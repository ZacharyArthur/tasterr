## Why

Watched titles (imported watch history) are excluded only from Recommended for
You, Picks You Wouldn't Usually Watch, and household picks. Not interested is
honored only by personalized rails and My List. Because You Watched / More Like,
Trending, genre, decade, service, and popular rails ignore one or both, so titles
a member has already seen or explicitly dismissed keep coming back. GitHub issue
#55 asks for both exclusions on every discovery rail, the way library hiding
became universal in #33, with watched hiding as a household setting next to
"Hide library items".

This advances the existing `discovery-filtering` capability (one exclusion seam
for every discovery surface) and `app-settings` (household discovery
preferences).

## What Changes

- **Not interested** hides the title from every discovery surface for the member
  who dismissed it, always, with no setting.
- New household runtime setting `hide_watched_items`, **on by default**, beside
  `hide_library_items`, with an optional `TASTERR_HIDE_WATCHED_ITEMS` environment
  lock. While on, every title the member has any stored watched signal for (every
  `watched_*` kind, movies and series alike) is hidden from their discovery
  surfaces.
- Watched hiding uses retained rows regardless of the member's taste-source
  toggle (the toggle governs learning, not hiding); clearing a source's imported
  history brings its titles back.
- Coverage is the existing discovery-filtering coverage: Home and paginated
  rails (including Because You Watched / More Like), hero slides, household
  blend, and detail recommendations/similar. Search, My List, Continue Watching,
  and direct title detail stay unfiltered.
- These personal exclusions come from the member's own signals in SQLite, so
  they need no upstream verification and do not spend the shared verification
  budget. They make filtering "active" for that request, so the existing refill
  and filtered-empty-feed rules apply.
- Settings gains a labelled "Hide titles members have watched" control with lock
  display. `docs/CONFIGURATION.md`, `.env.example`, and `compose.example.yaml`
  document the variable.

## Non-goals

- A manual "Seen it" action for titles watched outside linked servers (it would
  need a new signal kind, migration, UI, and weight decision). Trakt history
  (`trakt-watch-history`) covers the main case; revisit as its own change.
- Per-member watched-hiding preference.
- Hiding only fully watched series. Watch history collapses episodes to their
  series, so any watched episode hides the series; Continue Watching still
  surfaces series in progress.
- Changing household blend's existing veto (it already excludes every
  participant's watched, requested, watchlisted, and dismissed titles).
- Filtering Search, My List, Continue Watching, or direct title detail.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `discovery-filtering`: new per-member exclusions (Not interested always,
  watched titles while the household setting is on) across all discovery
  surfaces; "active filtering" now includes them.
- `app-settings`: runtime document gains `hide_watched_items` with an
  environment lock; the Settings exclusion controls show it.

## Impact

- Backend: `runtime_settings.py`, `settings.py` (lock), `catalog/discovery.py`
  (personal hidden set), `catalog/service.py` (filter construction),
  `api/catalog.py` (`get_catalog` loads the caller's set), `recommend/service.py`
  (ranking boosts keep their path unless a household filter is on),
  `recommend/store.py` (one query for the caller's watched and dismissed keys).
- Frontend: Settings exclusion control, generated types.
- Docs: `docs/CONFIGURATION.md`, `.env.example`, `compose.example.yaml`.
- No migration, no new dependency, no new browser response field outside admin
  settings. Behavior change on upgrade: watched titles disappear from generic
  rails by default; admins can turn it off.
- Landing order: after `tmdb-metadata-language`, before `watch-history-window`.
  `trakt-watch-history` relies on "every `watched_*` kind" here to hide Trakt
  watches with no further change.
