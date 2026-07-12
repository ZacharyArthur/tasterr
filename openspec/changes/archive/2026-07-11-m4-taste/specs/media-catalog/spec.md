# media-catalog Specification (delta)

## ADDED Requirements

### Requirement: Title facts feed the recommendation engine

The catalog SHALL expose an internal **title facts** surface per title — genres,
keywords, top-billed cast, director/creator, original language, release year,
runtime, and vote statistics — for the recommendation engine's feature builder.
The TMDB detail fetch SHALL include keywords via the detail append, so facts
derive from the same cached detail payload as the normalized detail and repeated
facts reads within the cache TTL make no additional TMDB call. Title facts are
internal domain data: they SHALL NOT appear in any API response model and SHALL
NOT import application settings.

#### Scenario: Facts include keywords

- **WHEN** title facts are built for a title whose TMDB detail carries keywords
- **THEN** the facts include those keywords alongside genres, cast, creator,
  language, year, runtime, and vote statistics

#### Scenario: Facts reuse the cached detail fetch

- **WHEN** title facts are requested for a title whose detail payload is cached
  and fresh
- **THEN** no additional TMDB request is made

#### Scenario: Facts stay out of API responses

- **WHEN** any `/api/v1` response model is serialized
- **THEN** it contains no title-facts payload
