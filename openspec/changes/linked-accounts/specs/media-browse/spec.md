# media-browse Specification (delta)

## MODIFIED Requirements

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
opens the "Connect Seerr" dialog (see `media-requests`) when the backend signals
`re_auth_required`, and offers a
server-provided "Request in Seerr" link on failure. Seerr/library text SHALL be
rendered as text, and any Seerr external link SHALL come only from the backend.
The detail modal SHALL additionally carry the **taste affordances**: opening a
detail posts a `detail_open` signal (fire-and-forget — a failed signal never
disturbs browsing), a watchlist toggle adds or retracts a `watchlist` signal, a
"Not interested" control adds or retracts a `not_interested` signal, and a
"Why am I seeing this?" element reveals the backend's explanation for the title.
The navbar user menu SHALL offer **Reset recommendations**, invoking the reset
endpoint only after an explicit confirmation.

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
- **THEN** the SPA opens the "Connect Seerr" dialog rather than showing a generic
  error or signing the user out

#### Scenario: Opening a detail records a signal quietly

- **WHEN** the user opens a title's detail modal
- **THEN** a `detail_open` signal is posted without blocking or disturbing the
  view, even if the post fails

#### Scenario: Watchlist toggles from the detail modal

- **WHEN** the user toggles the watchlist control on a title
- **THEN** the SPA posts the `watchlist` signal (or its retraction) and reflects
  the new state

#### Scenario: Not interested hides and can be undone

- **WHEN** the user marks a title "Not interested"
- **THEN** the SPA posts the `not_interested` signal and offers an undo that
  retracts it

#### Scenario: Explainer reveals the why

- **WHEN** the user asks "Why am I seeing this?" on a title
- **THEN** the SPA shows the reasons returned by the explain endpoint, rendered
  as text

#### Scenario: Reset requires confirmation

- **WHEN** the user picks Reset recommendations from the navbar menu
- **THEN** the reset endpoint is called only after the user explicitly confirms
