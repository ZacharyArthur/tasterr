## Context

See proposal.md for motivation. Current state:

- `clients/tmdb.py` hard-codes `LANGUAGE = "en-US"` and
  `include_image_language="en,null"`. `_cached` builds the cache key from path
  plus params, so any param already partitions the cache.
- `CatalogService` takes `region` and `service_ids` from `RuntimeSettings` at its
  three construction sites (`api/catalog.py`, two in `api/taste.py`).
- `title_facts()` shares the display detail fetch. `recommend/features.py` turns
  genre **names** (and keyword, cast, and creator names) into persisted
  `title_features` dimensions such as `genre:action`. `TasteService` maps those
  names back to ids through `CatalogService.genre_map()` (name→id from
  `/genre/{media}/list`). `rails/composer.py` also uses `genre_map()` to title
  genre rails.
- `pick_logo` strongly prefers `en`; `pick_trailer` ignores language, and
  `TmdbVideo` has no language field.
- `PublicConfig` holds booleans and appearance; `RuntimeSettings` already
  validates region.

## Goals / Non-Goals

**Goals:**
- One household language for display text, with graceful image and trailer
  fallbacks.
- A stable engine vocabulary: no stored feature or profile changes meaning when
  the language changes.

**Non-Goals:**
- Migrating feature dimensions to ids, or localizing engine-derived labels.

## Decisions

1. **Language is a runtime setting, threaded like region.** `RuntimeSettings`
   gains `language: str = "en-US"`, validated against `^[a-z]{2}-[A-Z]{2}$`.
   `CatalogService` receives it alongside region and passes it to every
   `TmdbClient` display method as an explicit argument. The module constant
   becomes `ENGINE_LANGUAGE = "en-US"`. Because TMDB cache keys include params,
   no TMDB cache flush or invalidation is needed. Continue Watching is the
   exception: it caches each member's resolved rail (`MediaSummary` list) under a
   per-user key for five minutes, so after a language change it can show the old
   language until that entry expires. This is accepted (a rare admin action,
   self-healing within five minutes) rather than adding the language to that key
   or a prefix flush. Alternative: an environment variable
   (offered in the issue), rejected for parity with region and to avoid a second
   lock mechanism (see Non-goals).

2. **Engine reads pinned to `en-US`.** `title_facts()` and `genre_map()` always
   call TMDB with `ENGINE_LANGUAGE`. With the default language this is the same
   cache entry as display, so English households see no extra calls. Other
   languages pay one extra detail read per newly featurized title (features are
   persisted, so this is mostly a one-off per title) plus an extra genre-list
   read per six hours. Alternative: switch features to genre ids, rejected
   because it means a migration, a profile rebuild, and keyword/cast are names
   anyway; pinning avoids all of it.

3. **Genre rails use display genres.** `rails/composer.py` switches from
   `genre_map()` to `genres()` (id plus localized name), so rail titles are
   localized while the engine keeps its English map.

4. **Fallback chains, built once.** One helper derives the ISO 639-1 part
   (`es` from `es-ES`) and builds `"{lang},en,null"` (or `"en,null"` for
   English) for both `include_image_language` and `include_video_language`.
   `TmdbVideo` gains optional `iso_639_1`. `pick_logo` and `pick_trailer` take
   the language part and score configured > `en` > neutral. Trailer language
   ranks above type/official, so a Spanish teaser beats an English trailer.
   Alternative: language as only a tie-breaker, rejected because members
   watching in Spanish expect Spanish trailers first.

5. **Picker data from TMDB, labels from the browser.** `GET /languages` reads
   `/configuration/primary_translations` (a list of `ll-CC` strings) with the
   regions/providers cache options. The SPA labels codes with
   `Intl.DisplayNames(undefined, {type: "language"})`, a platform API, so no
   locale data is shipped or added as a dependency. The save path validates
   format only, so saving settings never depends on TMDB being up.

6. **`lang` from PublicConfig.** `PublicConfig.metadata_language` lets
   `MediaCard`, `Hero`, and `DetailModal` set `lang` on TMDB text elements only.
   It is a validated code, not a secret.

## Risks / Trade-offs

- [Genre labels from the engine (hero labels, "more like" reasons) stay English
  while titles are Spanish] → documented; localizing them would need the id
  migration this design avoids.
- [Non-English households make extra `en-US` detail reads] → bounded to new
  titles being featurized; detail TTL caching applies; documented.
- [TMDB lacks a translation] → TMDB returns the original-language text; image and
  video fallbacks keep visuals.
- [Changing language leaves the old language's entries in the in-process cache
  until eviction] → bounded by the existing entry cap; no correctness impact.
- [Continue Watching shows the previous language for up to five minutes after
  a change] → accepted and documented; its cached per-user rail expires on its
  existing TTL.

## Migration Plan

No schema migration. Existing runtime documents gain `en-US` on read. Image-only
rollback is safe: older images ignore the extra JSON field (the runtime model
ignores unknown fields; a task verifies this).

## Security considerations

- **Endpoints:** `GET /api/v1/languages` uses the admin dependency, has no input,
  and has an explicit response model of validated codes. The settings PUT keeps
  its CSRF and admin bucket; the new field is Pydantic-validated by pattern.
  `GET /config` gains one validated code.
- **Outbound HTTP:** TMDB only, through `clients/tmdb.py`. The language reaches
  TMDB only as a pattern-validated query parameter, never raw input. The new read
  uses existing timeouts and stale-on-error caching. Upstream codes are
  validated before use.
- **Secrets / PublicConfig:** the language code is non-secret; the PublicConfig
  regression test is extended to the new field.
- **Frontend:** `lang` values come from validated config. TMDB text keeps
  rendering as text. Language labels come from the browser, not upstream.
- **Database:** the non-secret runtime JSON gains one field; no migration and no
  secret material.
- **Auth, dependencies:** not applicable.
