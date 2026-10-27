## MODIFIED Requirements

### Requirement: Title facts feed the recommendation engine

The catalog SHALL expose an internal **title facts** surface per title — genres,
keywords, top-billed cast, director/creator, original language, release year,
runtime, vote statistics, active watch region, and that region's flatrate
provider ids — for the recommendation engine's feature builder. The TMDB detail
fetch SHALL include keywords and watch providers via the detail append. Title
facts SHALL always be read in `en-US`, whatever the configured metadata language,
so the engine's feature vocabulary never changes with that setting. When the
metadata language is `en-US`, facts SHALL derive from the same cached detail
payload as normalized detail, and repeated facts reads within the cache TTL make
no additional TMDB call. The genre name-to-id map the engine uses SHALL likewise
be read in `en-US`. Title facts are internal domain data: they SHALL NOT appear in
any API response model and SHALL NOT import application deployment settings.

#### Scenario: Facts include keywords
- **WHEN** title facts are built for a title whose TMDB detail carries keywords
- **THEN** the facts include those keywords alongside genres, cast, creator,
  language, year, runtime, and vote statistics

#### Scenario: Facts include active-region services
- **WHEN** title facts are built for a title with flatrate providers in the active
  region
- **THEN** the facts include that region and the provider ids from the same detail
  payload

#### Scenario: Facts reuse the cached detail fetch
- **WHEN** the metadata language is `en-US` and title facts are requested for a
  title whose detail payload is cached and fresh
- **THEN** no additional TMDB request is made

#### Scenario: Facts stay English under another language
- **WHEN** the metadata language is `es-ES` and title facts are built
- **THEN** the facts come from an `en-US` detail read, and their genre names match
  the names in previously stored features

#### Scenario: Facts stay out of API responses
- **WHEN** any `/api/v1` response model is serialized
- **THEN** it contains no title-facts payload

## ADDED Requirements

### Requirement: Display reads follow the household metadata language

Every display-facing TMDB read (discover, trending, search, detail, genre lists
used for rail titles, watch-provider regions, and providers) SHALL send the
resolved household metadata language. Detail reads SHALL request images in the
configured language, then English, then language-neutral, and videos in the
configured language, then English, then language-neutral. Logo selection SHALL
prefer the configured language, then English, then language-neutral, and trailer
selection SHALL prefer the configured language, then English, before its
existing type and official ranking. Cached TMDB entries SHALL be keyed by
language, so changing the language never serves another language's cached TMDB
text as fresh. The one accepted exception is Continue Watching, whose resolved
per-user rail is cached for five minutes: after a language change it MAY show
the previous language until that entry expires, and SHALL show the new language
once it has.

#### Scenario: Spanish metadata
- **WHEN** the household language is `es-ES` and a member opens Home and a title
  detail
- **THEN** titles, overviews, and genre rail names come from TMDB's Spanish
  translation where one exists, and from the original text otherwise

#### Scenario: Missing localized logo falls back
- **WHEN** a title has English and language-neutral logos but none in the
  configured language
- **THEN** the English logo is shown

#### Scenario: Localized trailer preferred
- **WHEN** a title has official YouTube trailers in Spanish and in English and the
  language is `es-ES`
- **THEN** the Spanish trailer is selected

#### Scenario: Language change does not reuse old text
- **WHEN** an admin changes the language from `en-US` to `es-ES`
- **THEN** the next display reads request Spanish text rather than serving the
  cached English entries

#### Scenario: Continue Watching catches up after its cache expires
- **WHEN** a member's Continue Watching rail is cached in English and an admin
  changes the language to `es-ES`
- **THEN** the rail may stay English for up to five minutes, and the first read
  after the entry expires shows Spanish titles and overviews
