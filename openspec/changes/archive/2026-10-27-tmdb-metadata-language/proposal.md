## Why

Every title, overview, genre, poster, and logo Tasterr shows is English, because
the TMDB language is hard-coded to `en-US` and images prefer English. Households
that don't speak English can't use it comfortably. GitHub issue #51 asks for a
configurable TMDB metadata language (for example `es-ES`) and explicitly not UI
translation. Region is already an admin setting; language is the missing
companion.

This advances the existing `media-catalog` and `app-settings` capabilities.

## What Changes

- New household runtime setting `language` (default `en-US`), chosen by admins
  in Settings next to the region, from TMDB's list of primary translations.
- All display-facing TMDB reads (discover, trending, search, detail, genre
  names, regions, providers) use that language. TMDB falls back to original
  text where a translation is missing.
- Images and trailers prefer the configured language, then English, then
  language-neutral, so posters, logos, and trailers never disappear just
  because no localized version exists.
- The recommendation engine's vocabulary stays English. Title facts and the
  genre name→id map used by the engine are always read in `en-US`, so stored
  taste features and profiles stay consistent when the language changes.
- `PublicConfig` exposes the metadata language, so the SPA marks TMDB text with a
  matching `lang` attribute and screen readers pronounce it correctly.
- `docs/CONFIGURATION.md` documents the setting and its limits.

## Non-goals

- UI translation (buttons, labels, rail names Tasterr writes itself).
- Per-member language: one household setting, as region is.
- An environment-variable override. Region has none either; add one later only
  if someone needs to lock it.
- Localizing recommendation explanations ("Because you liked…" genre labels come
  from the engine's English vocabulary).
- Re-keying stored taste features to genre ids.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `media-catalog`: display reads follow the configured language with image and
  trailer fallbacks; title facts and the engine genre map stay `en-US`.
- `app-settings`: runtime settings gain `language`; a new admin language-choices
  endpoint; `PublicConfig` gains the metadata language.
- `media-browse`: TMDB text carries a `lang` attribute.

## Impact

- Backend: `runtime_settings.py`, `clients/tmdb.py` (language parameter,
  `include_image_language`, `include_video_language`, primary-translations
  read), `catalog/service.py`, `catalog/normalize.py` (logo/trailer preference),
  `rails/composer.py` (genre rails use display genres), `api/admin.py`,
  `api/catalog.py`, `api/taste.py`, `settings.py` (`PublicConfig`).
- Frontend: Settings language picker (labels via the browser's
  `Intl.DisplayNames`, no dependency), `lang` attributes in `MediaCard`, `Hero`,
  and `DetailModal`, plus generated types.
- No migration: the runtime document gains a defaulted field. Cache keys already
  include request params, so each language gets its own entries.
- Landing order: seerr-login-mode-label → tmdb-metadata-language →
  discovery-exclusions-everywhere → watch-history-window →
  jellyfin-continue-watching → sign-in-method-allowlist →
  seerr-media-server-awareness → trakt-watch-history.
