## MODIFIED Requirements

### Requirement: Home feed of a hero and composed rails

`GET /api/v1/home` SHALL return the enabled hero section and an ordered list of
enabled rails, each a titled list of media summaries. The global runtime snapshot
SHALL gate registered provider types before they fetch. The provider set SHALL
include non-personalized trending, popular-in-region, recently-added, genre, and
bounded per-selected-service rails plus the authenticated user's
recommended-for-you, because-you-watched, and my-list providers. Dynamic genre
and service instances share their registered type gate; absent disablement means
enabled, including for a newly registered type. A provider failure SHALL degrade
the feed to fewer rails rather than fail the request, and rails with fewer than a
minimum number of items SHALL be omitted. Titles SHALL be de-duplicated across
returned rails so a title does not repeat later. Disabling every provider SHALL
return a valid empty feed rather than override the admin's choice.

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

#### Scenario: Selected service produces a bounded service rail
- **WHEN** a selected service has provider metadata and enough catalog titles
- **THEN** the home feed includes a `New on {service}` rail for it, up to the
  documented service-rail cap

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
The provider catalogue SHALL be filtered by the request's global rail-type gates
before slicing and SHALL use the same active region/service discovery context as
home, so a cursor is stable for that settings snapshot.

#### Scenario: First page returns enabled rails and a next cursor
- **WHEN** a client requests `GET /api/v1/rails` with no cursor
- **THEN** it receives a page of enabled settings-aware rails and a cursor for the
  next page

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

## ADDED Requirements

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
