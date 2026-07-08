# media-browse Specification (delta)

## MODIFIED Requirements

### Requirement: Title detail

`GET /api/v1/title/{type}/{id}` SHALL return a normalized detail for a movie or TV
title: metadata (title, overview, genres, runtime, certification, year), backdrop,
poster, and logo imagery, a trailer when available, top cast and key crew, season
summaries for TV, where-to-watch provider info for the default region, and lists of
similar and recommended titles. `type` SHALL be constrained to `movie` or `tv` by
input validation, and an unknown title SHALL return a generic `404`. The detail
SHALL additionally include the title's **library availability**, resolved alongside
the TMDB detail; when Seerr is unavailable or unconfigured the availability SHALL
degrade to Unknown without failing or slowing the detail response.

#### Scenario: Movie detail

- **WHEN** an authenticated client requests detail for a known movie
- **THEN** it receives the metadata, imagery, trailer (if any), cast, where-to-watch
  providers, and similar/recommended lists

#### Scenario: TV detail includes seasons

- **WHEN** an authenticated client requests detail for a known TV title
- **THEN** the response includes its season summaries

#### Scenario: Detail includes availability

- **WHEN** an authenticated client requests detail for a title Seerr knows
- **THEN** the response includes the title's library availability

#### Scenario: Availability degrades without failing detail

- **WHEN** Seerr is unavailable or unconfigured while detail is fetched
- **THEN** the detail still returns with the availability set to Unknown

#### Scenario: Unknown title

- **WHEN** the request targets a valid `type` but an id TMDB does not know
- **THEN** the response is a generic `404` disclosing no upstream detail

#### Scenario: Type constrained to movie or tv

- **WHEN** the request uses a `type` other than `movie` or `tv`
- **THEN** it is rejected by input validation before any upstream call

### Requirement: Routed SPA browse experience

The SPA SHALL use a client router so the authenticated shell presents a Home view
(hero plus horizontally-scrolling rails with infinite scroll), a deep-linkable
title detail modal at `/title/:type/:id`, and a Search view — all fetched through
the OpenAPI-generated typed client via TanStack Query. Images SHALL be built
responsively from title image paths. TMDB-supplied text SHALL be rendered as text,
never as HTML, and non-essential animation SHALL be disabled under
`prefers-reduced-motion`. The SPA SHALL render an **availability badge** on cards,
the hero, search results, and detail — hydrated through a batch availability call
after the view renders, so browsing never waits on Seerr. The detail modal SHALL
present a **request affordance** in its where-and-how-to-watch section: a request
button that is disabled when Seerr is unconfigured (per `PublicConfig`) or the
title is already available/requested, shows an optimistic pending state on submit,
prompts re-login when the backend signals `re_auth_required`, and offers a
server-provided "Request in Seerr" link on failure. Seerr/library text SHALL be
rendered as text, and any Seerr external link SHALL come only from the backend.

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

#### Scenario: Badges hydrate after the view renders

- **WHEN** a Home or Search view has rendered its titles
- **THEN** availability badges populate from a batch availability call without
  having blocked the initial render

#### Scenario: Request button submits a request

- **WHEN** the user activates the request button for a requestable title
- **THEN** the SPA submits the request through the typed client and reflects the
  resulting pending/requested state

#### Scenario: Request affordance disabled when unavailable

- **WHEN** Seerr is unconfigured or the title is already available
- **THEN** the request button is disabled

#### Scenario: Re-login prompted on re-auth signal

- **WHEN** a request returns `re_auth_required`
- **THEN** the SPA prompts the user to re-login rather than showing a generic error
