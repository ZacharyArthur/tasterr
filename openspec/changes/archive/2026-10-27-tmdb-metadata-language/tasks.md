## 1. Setting

- [x] 1.1 Add `language` (default `en-US`, `ll-CC` pattern) to `RuntimeSettings`. Verify with tests: defaults, round-trip, invalid values rejected atomically, a stored document without the field resolves to `en-US`, and an older model ignores the extra field.
- [x] 1.2 Add `metadata_language` to `PublicConfig`. Verify by extending the PublicConfig regression and config API tests.

## 2. TMDB client and catalog

- [x] 2.1 Thread an explicit `language` argument through the `TmdbClient` display methods, add `ENGINE_LANGUAGE`, and build `include_image_language` and `include_video_language` from one helper; add optional `iso_639_1` to `TmdbVideo`. Verify with client tests asserting the params per method and that cache keys differ by language.
- [x] 2.2 Pass `runtime.language` into `CatalogService` at all three construction sites; pin `title_facts()` and `genre_map()` to `ENGINE_LANGUAGE`. Verify with tests: with `en-US`, facts make no extra call after a detail read (existing test); with `es-ES`, facts use an `en-US` read and display uses `es-ES`; a Continue Watching rail cached in English stays English until its five-minute entry expires and then resolves in Spanish (advance the cache clock in the test).
- [x] 2.3 Prefer the configured language in `pick_logo` and `pick_trailer` (configured > `en` > neutral). Verify with normalize tests for each fallback step, including a Spanish teaser beating an English trailer.
- [x] 2.4 Switch genre rails in `rails/composer.py` to `genres()` so rail titles are localized. Verify with a composer test that the genre rail title uses the display name while the engine's genre map is unchanged.

## 3. Admin languages

- [x] 3.1 Add the primary-translations read to `clients/tmdb.py` and admin `GET /api/v1/languages` (validated, deduplicated, sorted). Verify with API tests: admin success, malformed codes dropped, 403 for members with no TMDB call, generic error when TMDB is unconfigured.
- [x] 3.2 Regenerate `api.gen.ts`, then add a language select beside the region in Settings (labels via `Intl.DisplayNames` plus the code; always includes the saved value). Verify with a Vitest case for labels, the saved-value fallback, and the save payload.

## 4. Accessibility

- [x] 4.1 Set `lang` from `metadata_language` on TMDB title, overview, and tagline elements in `MediaCard`, `Hero`, and `DetailModal` only; omit it while config is loading. Verify with Vitest assertions on those elements and on a neighbouring control that lacks it.

## 5. Documentation

- [x] 5.1 Document the language setting in `docs/CONFIGURATION.md` (runtime settings list; English engine vocabulary and engine-derived English genre labels; extra `en-US` reads for non-English households; Continue Watching may show the previous language for up to five minutes after a change; UI stays English). Verify the docs tests pass under `just check`.

## 6. Gate

- [x] 6.1 Before archiving, compare each MODIFIED block in `specs/` with the current `openspec/specs/` text and fold in anything a change archived since this one was written added. Verify with `openspec validate tmdb-metadata-language --strict`.
- [x] 6.2 Run `just check` inside the devcontainer and fix any failures until it passes.
