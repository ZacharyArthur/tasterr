# media-browse Specification

## Purpose
TBD - created by archiving change m2-browse. Update Purpose after archive.
## Requirements
### Requirement: Home feed of a hero and composed rails

`GET /api/v1/home` SHALL return the enabled hero section and an ordered list of
enabled rails, each a titled list of media summaries. The global runtime snapshot
SHALL gate registered provider types before they fetch. The provider set SHALL
include non-personalized trending, popular-in-region, recent-release, genre, and
bounded per-selected-service rails plus the authenticated user's
recommended-for-you, because-you-watched, and my-list providers. The generic
release rail SHALL be titled `Recent Releases`. Each per-selected-service rail
SHALL use current flatrate movie availability and movie release dates from the
preceding 365 days and SHALL be titled `Recent Releases on {service}`. Dynamic
genre and service instances share their registered type gate; absent disablement
means enabled, including for a newly registered type. A provider failure SHALL
degrade the feed to fewer rails rather than fail the request, and rails with
fewer than a minimum number of items SHALL be omitted. Titles SHALL be
de-duplicated across returned rails so a title does not repeat later. Disabling
every provider SHALL return a valid empty feed rather than override the admin's
choice.

#### Scenario: Authenticated home returns enabled hero and rails
- **WHEN** an authenticated client requests `GET /api/v1/home` with default
  settings
- **THEN** it receives a hero and an ordered set of non-empty rails

#### Scenario: Disabled type is neither fetched nor returned
- **WHEN** an admin has disabled a registered hero or rail type
- **THEN** that section/provider performs no catalog work and is absent from the
  feed

#### Scenario: New provider type defaults enabled
- **WHEN** a registered type has no entry in the disabled set
- **THEN** it participates in composition by default

#### Scenario: Generic release rail is labelled honestly
- **WHEN** the generic release provider yields enough movie titles
- **THEN** the home feed includes a `Recent Releases` rail

#### Scenario: Selected service produces a bounded service rail
- **WHEN** a selected service has provider metadata and enough flatrate movie
  titles released during the preceding 365 days
- **THEN** the home feed includes a `Recent Releases on {service}` rail for it,
  up to the documented service-rail cap

#### Scenario: Service metadata failure degrades independently
- **WHEN** provider metadata cannot be resolved and no stale value exists
- **THEN** service rails are omitted while other home providers still compose

#### Scenario: One failing provider still returns the rest
- **WHEN** a single rail provider errors while composing the home feed
- **THEN** the response still contains the enabled hero and remaining rails

#### Scenario: Under-filled rail omitted
- **WHEN** a provider yields fewer than the minimum number of items
- **THEN** that rail is omitted from the feed

#### Scenario: Titles de-duplicated across rails
- **WHEN** a title qualifies for more than one rail in a single response
- **THEN** it appears in only one of the returned rails

#### Scenario: Home is personalized per user
- **WHEN** two users with different taste profiles request `GET /api/v1/home`
- **THEN** each receives enabled personalized rails reflecting their own profile

#### Scenario: Signal-less user sees the non-personalized home
- **WHEN** a user with no signals requests the home feed
- **THEN** the response contains enabled non-personalized rails and no
  personalized rail placeholders

#### Scenario: Every section disabled returns a valid empty feed
- **WHEN** the admin disables hero and every registered rail type
- **THEN** the endpoint returns 200 with an empty hero/rail result

### Requirement: Infinite-scroll additional rails

`GET /api/v1/rails?cursor=` SHALL return a page of enabled additional rails
(top-rated, by-decade, and further genres across movie and TV) together with a
cursor for the next page or a signal that the bounded catalogue is exhausted.
Every available curated movie genre not selected for the Home feed SHALL remain
reachable through these additional pages. The provider catalogue SHALL be
filtered by the request's global rail-type gates before slicing and SHALL use the
same active region/service discovery context as home, so a cursor is stable for
that settings snapshot.

#### Scenario: First page returns enabled rails and a next cursor
- **WHEN** a client requests `GET /api/v1/rails` with no cursor
- **THEN** it receives a page of enabled settings-aware rails and a cursor for the
  next page

#### Scenario: Remaining curated movie genres stay reachable
- **WHEN** more curated movie genres are available than the Home feed displays
- **THEN** every remaining curated movie genre occurs in the additional-rail
  catalogue

#### Scenario: Disabled additional type is skipped before pagination
- **WHEN** top-rated, decade, or genre rails are disabled
- **THEN** providers of that type are not fetched and do not consume a page slot

#### Scenario: Exhausted catalogue signals completion
- **WHEN** a client pages past the last enabled available rail
- **THEN** the response contains no further rails and signals that paging is done

### Requirement: Title detail

`GET /api/v1/title/{type}/{id}` SHALL return a normalized detail for a movie or TV
title: metadata (title, overview, genres, runtime, certification, year), backdrop,
poster, and logo imagery, a trailer when available, top cast and key crew, season
summaries for TV, where-to-watch provider info for the active global region, and
lists of similar and recommended titles. `type` SHALL be constrained to `movie`
or `tv` by input validation, and an unknown title SHALL return a generic `404`.
The detail SHALL additionally include the title's **library availability**,
resolved alongside the TMDB detail; when Seerr is unavailable or unconfigured the
availability SHALL degrade to Unknown without failing or slowing the detail
response.

#### Scenario: Movie detail
- **WHEN** an authenticated client requests detail for a known movie
- **THEN** it receives the metadata, imagery, trailer (if any), cast,
  active-region where-to-watch providers, and similar/recommended lists

#### Scenario: TV detail includes seasons
- **WHEN** an authenticated client requests detail for a known TV title
- **THEN** the response includes its season summaries

#### Scenario: Configured region changes regional detail
- **WHEN** the admin changes region and a title is requested afterward
- **THEN** its certification and where-to-watch data use the new region

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
`prefers-reduced-motion`. The SPA SHALL render an **availability badge** on cards,
the hero, search results, and detail — hydrated through a batch availability call
after the view renders, so browsing never waits on Seerr. The detail modal SHALL
present a **request affordance** in its where-and-how-to-watch section: a request
button that is disabled when Seerr is unconfigured (per `PublicConfig`) or the
title is already available/requested, shows an optimistic pending state on submit,
prompts re-login when the backend signals `re_auth_required`, and offers a
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
- **THEN** the SPA prompts the user to re-login rather than showing a generic error

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

### Requirement: Browse interactions support keyboard, remote, and modal focus

The SPA SHALL expose each rail as a labelled region whose cards remain normally
focusable; Left/Right on a focused rail card SHALL move focus to and reveal the
adjacent card. The detail overlay SHALL trap Tab/Shift+Tab, make the background
inert, close on Escape, and restore focus to the opening control. Interactive
controls SHALL have accessible names, visible `focus-visible` indicators, and
living-room-usable targets. Async and empty states SHALL use semantic visible
text, not color alone.

#### Scenario: Arrow key moves through a rail
- **WHEN** a focused rail card receives Right or Left and an adjacent card exists
- **THEN** focus moves to that card and it is scrolled into view

#### Scenario: Modal focus cannot escape to background
- **WHEN** a detail modal is open and the user tabs past its first or last
  focusable control
- **THEN** focus wraps within the modal and the browse background remains inert

#### Scenario: Closing modal restores trigger focus
- **WHEN** the user closes a route-driven detail modal with Escape or its close
  control
- **THEN** focus returns to the card/control that opened it when still present

#### Scenario: Living-room viewport remains operable
- **WHEN** Home, Search, Detail, and Settings are inspected at 1280x720 and
  1920x1080 using keyboard-style navigation
- **THEN** primary content, focus, controls, labels, and status feedback remain
  visible and usable without precision pointing

### Requirement: Reduced motion covers every non-essential effect

The SPA SHALL use `prefers-reduced-motion` for both JS-driven and CSS-driven
behavior. Under reduction, hero/other content SHALL NOT auto-advance,
non-essential transforms/transitions/animations SHALL be removed, and
programmatic scrolling SHALL be instant while all information and controls remain
available.

#### Scenario: Reduced motion stops auto-advance
- **WHEN** the system requests reduced motion
- **THEN** hero or other rotating content remains on the current item until the
  user changes it

#### Scenario: Reduced motion preserves interaction
- **WHEN** reduced motion is active and the user opens menus, navigates rails, or
  opens/closes detail
- **THEN** the same information and controls work without non-essential motion

### Requirement: Detail overlay preserves one browsing context

The SPA detail overlay SHALL preserve the original browse location while the
user opens related titles. Related-title navigation SHALL replace the active
detail history entry so closing any related detail returns directly to the
original browse view. While a detail overlay is mounted, the underlying document
SHALL NOT scroll, and its prior scroll behavior SHALL be restored when the
overlay unmounts. Taste controls SHALL adopt newer server-provided flags when
refreshed detail data arrives for the same title.

#### Scenario: Related title closes to original browse view

- **WHEN** a user opens a title from a browse card, opens one or more titles from
  More like this, and then closes the detail overlay
- **THEN** the overlay closes directly to the original browse view without
  revealing each previously viewed detail

#### Scenario: Direct detail remains directly closable

- **WHEN** a user deep-links to a title, opens a related title, and closes the
  overlay
- **THEN** the app returns Home without revealing the first detail

#### Scenario: Background scrolling is locked and restored

- **WHEN** a detail overlay opens and later closes
- **THEN** the underlying document cannot scroll while open and its previous
  overflow behavior is restored on close

#### Scenario: Refreshed watchlist state replaces stale cached state

- **WHEN** a user changes a title's My List state, closes it, and reopens cached
  detail data before the refreshed server response arrives
- **THEN** the control adopts the refreshed server state without requiring an
  extra toggle

### Requirement: Title detail exposes a canonical external reference

`GET /api/v1/title/{type}/{id}` SHALL include a secret-free external URL for the
corresponding TMDB movie or TV page. The SPA SHALL render that server-provided
URL as an accessible external link from the detail view and open it in a separate
browsing context without granting the destination access to the opener.

#### Scenario: Movie detail links to its TMDB page

- **WHEN** an authenticated client requests a known movie detail
- **THEN** the response's external URL identifies that movie on TMDB

#### Scenario: TV detail links to its TMDB page

- **WHEN** an authenticated client requests a known TV detail
- **THEN** the response's external URL identifies that series on TMDB

#### Scenario: External link is isolated from the app

- **WHEN** the user activates the TMDB link in a detail view
- **THEN** it opens in a separate browsing context with opener access disabled

### Requirement: Title detail exposes playable library links

`GET /api/v1/title/{type}/{id}` SHALL surface the typed playback links resolved
with library availability. When Seerr is unavailable, unconfigured, reports the
title neither available nor partially available, or supplies no valid web link, the response SHALL contain no
usable Play target and SHALL still return the TMDB detail normally. No Plex token,
Seerr cookie, internal URL, or raw upstream body SHALL appear in the response.

#### Scenario: Available title includes playback links

- **WHEN** an authenticated client requests detail for an available title with
  valid Seerr links
- **THEN** its availability includes the server-validated web and platform link
  targets

#### Scenario: Seerr failure omits playback without failing detail

- **WHEN** playback links cannot be resolved because Seerr is unavailable
- **THEN** detail still returns with Unknown availability and no Play target

#### Scenario: Non-playable title has no Play target

- **WHEN** Seerr does not mark either title variant available or partially available
- **THEN** detail includes its non-available status but no usable playback link

### Requirement: Detail offers resilient Plex Web and Plex App controls

The detail modal SHALL render a Plex Web link alongside the request affordance for
an available or partially available title with a validated web target. When the chosen variant also
has a validated app target, it SHALL separately render a Plex App link so the user
chooses the destination instead of platform detection hiding the recoverable web path.
On Android, the app link SHALL use the server-provided `intent://` target so Plex
receives the tested `plex://preplay/` data and a missing app falls back to the web
target. On other platforms, the app link SHALL use the validated custom scheme
without scheduling a web fallback. The Plex Web link SHALL open in a new browsing
context so Tasterr remains available for a user-driven retry. The regular variant
SHALL be preferred over 4K, with 4K used when it is the only playable variant. The
controls SHALL carry an explicit experimental qualifier and SHALL be reachable and activatable with the same
keyboard/remote navigation and visible-focus behavior as adjacent detail controls.

#### Scenario: Web remains an explicit choice on every platform

- **WHEN** any user views an available title with a validated web target
- **THEN** Plex Web is offered directly even when a Plex App target is also available

#### Scenario: Plex Web preserves the browse session

- **WHEN** a user activates Plex Web
- **THEN** it opens in a new browsing context and leaves the Tasterr browse session
  available for another activation

#### Scenario: Partially available title remains playable

- **WHEN** Seerr marks a regular or 4K variant partially available with a validated
  web target
- **THEN** the Plex Web and optional Plex App controls use that variant's links

#### Scenario: Available Android title opens a fallback-capable intent

- **WHEN** an Android user activates Plex App for an available title with app and web
  links
- **THEN** the selected href targets the Plex Android package and contains the
  encoded web fallback supplied by the backend

#### Scenario: Missing app target leaves the reliable web path

- **WHEN** an available title has a web target but no validated app target
- **THEN** Plex Web is rendered and Plex App is omitted

#### Scenario: 4K is the only playable variant

- **WHEN** regular media is unavailable and the 4K variant is available with a
  valid web target
- **THEN** the Plex Web and optional Plex App controls use the 4K link set

#### Scenario: No usable link renders no control

- **WHEN** Seerr is down, the title is neither available nor partially available,
  or no valid web target exists
- **THEN** no Plex playback control is rendered and the rest of detail remains operable

#### Scenario: Playback controls disclose handoff reliability

- **WHEN** either Plex playback control is rendered
- **THEN** adjacent plain-language text identifies the handoff as experimental,
  advises retrying Plex Web after sign-in or user switching, and warns that Plex
  App may open Home instead of the title, including as the controls' accessible
  description

#### Scenario: Playback controls participate in modal navigation

- **WHEN** keyboard or remote focus reaches either playback control
- **THEN** it has visible focus, activates as a link, and remains inside the
  detail modal's focus trap
