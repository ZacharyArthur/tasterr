## MODIFIED Requirements

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
