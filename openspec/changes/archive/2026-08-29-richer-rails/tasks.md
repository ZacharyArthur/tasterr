## 1. Mixed service rails

- [x] 1.1 Fetch recent flatrate movies and TV independently, interleave them to 20 with surplus fill, require 10 final items, and verify balanced, lopsided, query-parameter, cap, and one-leg-failure cases in `backend/tests/test_rails.py`

## 2. Plex next-up episodes

- [x] 2.1 Parse show/season last-viewed timestamps, retain only episodes whose progress is genuinely absent, preserve hub position as the final ordering fallback, allow null progress through summary mapping, and verify timestamp, position, invalid-progress, and progress-less-movie behavior in `backend/tests/test_catalog_plex.py`
- [x] 2.2 Update the redacted live Plex timestamp contract for next-up rows and run `just test-live`, reporting only generic timestamp-field/fallback findings

## 3. Validation

- [x] 3.1 Run `openspec validate richer-rails --strict` and fix all change-artifact errors
- [x] 3.2 Run `just check` and fix all failures

## 4. Review fixes

- [x] 4.1 Render next-up episode context without a progress bar and cover it in `MediaCard.test.tsx`
- [x] 4.2 Normalize malformed optional Plex ordering timestamps, prefer in-progress duplicates on timestamp ties, and cover timestamp priority, malformed inputs, explicit-null progress, and cross-server fallback order
- [x] 4.3 Cover the service-specific 10-item omission through the composer
- [x] 4.4 Re-run strict OpenSpec validation and `just check`
