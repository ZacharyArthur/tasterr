## 1. Shared resume step

- [ ] 1.1 Create `catalog/resume.py` with `ResumeCandidate`, `merge`, and `resolve` extracted from `catalog/plex.py`, with `source_rank` replacing `server_index`; switch Plex to emit candidates. Verify the existing Plex Continue Watching tests pass unchanged and add merge tests for cross-source ties (timestamp, then progress, then Plex before Jellyfin).
- [ ] 1.2 Move the per-user cache and `continue_watching_key` into a `continue_watching(...)` function in `catalog/resume.py` that gathers sources concurrently, gives each its own ten-second deadline, caches merged results under the existing five-minute TTL (`tmdb-metadata-language` relies on it to bound how long the rail can show the previous language), and caches an empty negative entry when no source succeeds; update `api/account.py` imports and move `tmdb-metadata-language`'s Continue Watching language-switch test onto the new function. Verify with tests: one load per cache lifetime, one source failing keeps the other, all failing caches empty, no stale serving, and the language-switch test passing.

## 2. Jellyfin reads and mapping

- [ ] 2.1 Add `resume_items(user_id)` and `next_up(user_id)` to `clients/jellyfin.py` and the optional item fields (`Type`, `RunTimeTicks`, `ParentIndexNumber`, `IndexNumber`, `PlaybackPositionTicks`). Verify with client tests: paths and params including `userId`, key only in `Authorization`, strict parsing, and typed errors on bad shapes.
- [ ] 2.2 Move the TMDB provider-id validator into `catalog/` and use it from `recommend/jellyfin_history.py`. Verify the existing Jellyfin history tests and the import-linter boundaries pass.
- [ ] 2.3 Add `catalog/jellyfin.py` to map resume and next-up items to `ResumeCandidate`s (progress 1–99, episode context, series collapse through one batched lookup, series last-played time or a position sentinel for next-up). Verify with unit tests for each inclusion/omission rule in the spec, including invalid progress, a missing TMDB id, an episode's own TMDB id ignored, and missing season/episode numbers.

## 3. Rail wiring

- [ ] 3.1 Add the Jellyfin client and linked user id to `RailContext`, set them in `api/home.py` only for a configured Jellyfin with a link, and make `continue_watching_provider` present when either source is available and the rail type is enabled. Verify with tests: Jellyfin-only member gets the rail; disabled rail type and dormant link do no Jellyfin read; a Plex-only member's behavior is unchanged.
- [ ] 3.2 Clear the Continue Watching cache on Jellyfin unlink. Verify with an account API test that the next Home load re-reads.
- [ ] 3.3 Add a Home API test with a fake Jellyfin transport asserting a Jellyfin-only member's Home response includes Continue Watching summaries with progress and episode context, and that afterwards no table holds a Jellyfin item id, position, or progress (the signals table gains no row). Verify with pytest.

## 4. Live contract and docs

- [ ] 4.1 Add live Jellyfin contract cases for `/UserItems/Resume` and `/Shows/NextUp` (shape, user scoping across two disposable users). Verify the cases are collected under `-m live` and record only generic outcomes.
- [ ] 4.2 Update `docs/CONFIGURATION.md` (Continue Watching for Plex and Jellyfin, merged rail, degraded modes) and `README.md` (remove "Continue Watching not supported" for Jellyfin; Play links remain unsupported). (The "Mixed setups" matrix lands later with `seerr-media-server-awareness`, which adds the Continue Watching row.) Verify the docs tests pass under `just check`.

## 5. Gate

- [ ] 5.1 Before archiving, compare each MODIFIED block in `specs/` with the current `openspec/specs/` text and fold in anything a change archived since this one was written added. Verify with `openspec validate jellyfin-continue-watching --strict`.
- [ ] 5.2 Run `just check` inside the devcontainer and fix any failures until it passes.
