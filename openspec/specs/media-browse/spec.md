# media-browse Specification

## Purpose
TBD - created by archiving change m2-browse. Update Purpose after archive.
## Requirements
### Requirement: Home feed of a hero and composed rails

`GET /api/v1/home` SHALL return a hero — a small set of featured titles with
backdrop, logo, and trailer metadata — and an ordered list of rails, each a titled
list of media summaries. Rails SHALL be composed from the enabled non-personalized
providers (trending, popular, recently-added, and genre). A provider failure
SHALL degrade the feed to fewer rails rather than fail the request, and rails with
fewer than a minimum number of items SHALL be omitted. Titles SHALL be de-duplicated
across the returned rails so a title does not repeat in a later rail.

#### Scenario: Authenticated home returns hero and rails
- **WHEN** an authenticated client requests `GET /api/v1/home`
- **THEN** it receives a hero and an ordered set of non-empty rails

#### Scenario: One failing provider still returns the rest
- **WHEN** a single rail provider errors while composing the home feed
- **THEN** the response still contains the hero and the remaining rails

#### Scenario: Under-filled rail omitted
- **WHEN** a provider yields fewer than the minimum number of items
- **THEN** that rail is omitted from the feed

#### Scenario: Titles de-duplicated across rails
- **WHEN** a title qualifies for more than one rail in a single response
- **THEN** it appears in only one of the returned rails

### Requirement: Infinite-scroll additional rails

`GET /api/v1/rails?cursor=` SHALL return a page of additional rails (top-rated,
by-decade, and further genres across movie and TV) together with a cursor for the
next page or a signal that the bounded catalogue is exhausted, so the SPA can
scroll continuously.

#### Scenario: First page returns rails and a next cursor
- **WHEN** a client requests `GET /api/v1/rails` with no cursor
- **THEN** it receives a page of rails and a cursor for the next page

#### Scenario: Exhausted catalogue signals completion
- **WHEN** a client pages past the last available rails
- **THEN** the response contains no further rails and signals that paging is done

### Requirement: Title detail

`GET /api/v1/title/{type}/{id}` SHALL return a normalized detail for a movie or TV
title: metadata (title, overview, genres, runtime, certification, year), backdrop,
poster, and logo imagery, a trailer when available, top cast and key crew, season
summaries for TV, where-to-watch provider info for the default region, and lists of
similar and recommended titles. `type` SHALL be constrained to `movie` or `tv` by
input validation, and an unknown title SHALL return a generic `404`. Availability
status and request actions are out of scope for this capability.

#### Scenario: Movie detail
- **WHEN** an authenticated client requests detail for a known movie
- **THEN** it receives the metadata, imagery, trailer (if any), cast, where-to-watch
  providers, and similar/recommended lists

#### Scenario: TV detail includes seasons
- **WHEN** an authenticated client requests detail for a known TV title
- **THEN** the response includes its season summaries

#### Scenario: Unknown title
- **WHEN** the request targets a valid `type` but an id TMDB does not know
- **THEN** the response is a generic `404` disclosing no upstream detail

#### Scenario: Type constrained to movie or tv
- **WHEN** the request uses a `type` other than `movie` or `tv`
- **THEN** it is rejected by input validation before any upstream call

### Requirement: Multi-search

`GET /api/v1/search?q=` SHALL return movie and TV summaries matching the query via
TMDB multi-search, dropping person results. The query SHALL be trimmed and
length-bounded; an empty or whitespace-only query SHALL return an empty result set
without calling TMDB.

#### Scenario: Query returns titles only
- **WHEN** an authenticated client searches a non-empty query
- **THEN** it receives matching movie and TV summaries and no person results

#### Scenario: Empty query short-circuits
- **WHEN** the query is empty or whitespace only
- **THEN** an empty result set is returned and no TMDB request is made

### Requirement: Browse endpoints are session-gated and degrade

All browse endpoints SHALL require a valid session using the shared default-deny
dependency. When TMDB is unconfigured they SHALL respond `503`; when TMDB errors
with no cached value available they SHALL respond with a generic `502` carrying no
upstream body or URL. Every endpoint SHALL declare an explicit, secret-free
response model.

#### Scenario: Unauthenticated browse request
- **WHEN** a client without a valid session requests any browse endpoint
- **THEN** the response is `401`

#### Scenario: Browse while TMDB is unconfigured
- **WHEN** an authenticated client requests a browse endpoint with TMDB unconfigured
- **THEN** the response is `503`

#### Scenario: Browse while TMDB is failing with no cache
- **WHEN** TMDB errors and no cached value is available for the request
- **THEN** the response is a generic `502` disclosing no upstream detail

### Requirement: Routed SPA browse experience

The SPA SHALL use a client router so the authenticated shell presents a Home view
(hero plus horizontally-scrolling rails with infinite scroll), a deep-linkable
title detail modal at `/title/:type/:id`, and a Search view — all fetched through
the OpenAPI-generated typed client via TanStack Query. Images SHALL be built
responsively from title image paths. TMDB-supplied text SHALL be rendered as text,
never as HTML, and non-essential animation SHALL be disabled under
`prefers-reduced-motion`.

#### Scenario: Home renders hero and rails
- **WHEN** an authenticated user opens the app
- **THEN** the Home view shows the hero and scrollable rails from `GET /api/v1/home`

#### Scenario: Deep-linkable detail modal
- **WHEN** the user navigates to `/title/:type/:id`
- **THEN** the title detail modal opens over the browse view for that title

#### Scenario: Search shows matching titles
- **WHEN** the user submits a search query
- **THEN** matching titles from `GET /api/v1/search` are displayed

#### Scenario: Reduced motion honored
- **WHEN** the user's system requests reduced motion
- **THEN** non-essential transitions and animations are disabled

