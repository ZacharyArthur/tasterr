## MODIFIED Requirements

### Requirement: Home feed of a hero and composed rails

`GET /api/v1/home` SHALL return the enabled hero section and an ordered list of
enabled rails, each a titled list of media summaries. The global runtime snapshot
SHALL gate registered provider types before they fetch. The provider set SHALL
include non-personalized trending, popular-in-region, recent-release, genre, and
bounded per-selected-service rails plus the authenticated caller's
`continue-watching`, `recommended-for-you`, `more-like`, `my-list`, and
`unexpected-picks` providers. The separately requested `household-blend` rail
SHALL NOT be part
of this response. The generic release rail SHALL be titled `Recent Releases`.
Each per-selected-service rail SHALL use current flatrate movie availability and
movie release dates from the preceding 365 days and SHALL be titled
`Recent Releases on {service}`. Dynamic genre and service instances share their
registered type gate; absent disablement means enabled, including for a newly
registered type. A provider failure SHALL degrade the feed to fewer rails rather
than fail the request, and rails with fewer than a minimum number of items SHALL
be omitted. Titles SHALL be de-duplicated across rails in the initial `/home`
response so a title does not repeat later there. Paginated `/rails` results SHALL
remove duplicates within each individual rail but SHALL NOT strip a provider's
items because the same title occurs in another extra rail; overlap across service,
decade, and genre rails is allowed because the stateless cursor does not carry a
cross-page seen-title set. Disabling every provider SHALL return a valid empty
feed rather than override the admin's choice.

The visible Home sequence SHALL preserve this relative order among available
rails: Continue Watching, My List, Recommended for You, Trending Now, More Like
X/Because You Watched X, Popular Movies, Popular TV, Recent Releases, Picks You
Wouldn't Usually Watch, Top Rated Movies, Top Rated TV, selected-service rails,
decades, then genres. Genre rails SHALL mix movie and TV providers in a per-user
daily-stable order after decades, using explicit **{Genre} · Movies** and
**{Genre} · TV** labels. Stable order SHALL be reused across cursor pages for that
user/day; no presentation seed SHALL be persisted.

#### Scenario: Authenticated home returns enabled hero and rails

- **WHEN** an authenticated client requests `GET /api/v1/home` with default
  settings
- **THEN** it receives a hero and an ordered set of non-empty rails

#### Scenario: Disabled type is neither fetched nor returned

- **WHEN** an admin has disabled a registered hero or rail type
- **THEN** that section/provider performs no catalog or upstream capability work
  and is absent from the feed

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

- **WHEN** a title qualifies for more than one rail in a single Home response
- **THEN** it appears in only the earliest returned rail

#### Scenario: Cursor grouping does not shrink extra rails

- **WHEN** two paginated service, decade, or genre providers contain overlapping
  titles and happen to share one cursor response
- **THEN** each rail retains its own distinct provider results just as it would on
  separate cursor pages

#### Scenario: Home preserves the approved rail sequence

- **WHEN** every provider yields enough distinct items
- **THEN** the visible rails follow the specified personalized, broad catalog,
  service, decade, and mixed-genre order

#### Scenario: Daily genre variation is cursor-stable

- **WHEN** one user loads multiple genre cursor pages on the same day
- **THEN** movie and TV genre rails use one stable mixed order with no per-request
  reshuffle

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

## ADDED Requirements

### Requirement: Continue Watching cards expose accessible progress context

The system SHALL allow a media summary and its inherited media-detail shape to
contain a computed progress percentage from 1 through 99 and short plain-text
context for a Continue Watching item. MediaCard SHALL render valid progress as
both visible text and a visual
progress bar with an accessible label; it SHALL render context as text. Ordinary
`MediaSummary` instances, including inherited detail shapes, SHALL
default both fields to null and remain unchanged.
Invalid, zero, or complete progress SHALL cause the Plex item to be absent from
the typed backend response rather than clamped into a misleading resumable state.
Episode context SHALL be generated only from validated integer season/episode
coordinates. Progress presentation SHALL preserve card navigation, focus
visibility, availability hydration, and reduced-motion behavior.

#### Scenario: In-progress movie shows progress

- **WHEN** a Continue Watching movie summary carries valid progress
- **THEN** its card exposes the percentage visibly and to assistive technology

#### Scenario: Episode context stays attached to the show card

- **WHEN** a Continue Watching episode was collapsed to a TMDB show
- **THEN** the show card renders its validated season/episode context as text

#### Scenario: Invalid episode coordinates are not displayed

- **WHEN** a Plex episode lacks valid positive integer season or episode indexes
- **THEN** the item is omitted and no upstream context string is forwarded to
  MediaCard

#### Scenario: Ordinary card does not change

- **WHEN** a normal Home/Search/related summary has no progress or context
- **THEN** MediaCard retains its existing title/year presentation and navigation

### Requirement: V2 rails preserve one resilient Home experience

Home SHALL render enabled Continue Watching and unexpected-picks results through
the existing Rail component and SHALL offer the enabled household-blend picker as
an inline, non-blocking section. Continue Watching and unexpected picks SHALL
participate in the normal home response/de-duplication order. A requested
household result SHALL render as one standard dynamic rail and hydrate its own
availability without delaying the existing Home query. Failure, token absence,
disablement, or thin results for any v2 capability SHALL leave every unaffected
rail and browse action operable. The dynamic household rail SHALL contain no
internal duplicate but MAY repeat a title from the already-completed Home response;
it SHALL NOT accept browser-supplied visible-title exclusion keys.

#### Scenario: V2 rails reuse standard navigation

- **WHEN** any v2 result is rendered
- **THEN** its cards use the same focus, Left/Right, detail-route, and availability
  behavior as existing rails

#### Scenario: Dynamic household availability does not block Home

- **WHEN** a household blend succeeds after Home has rendered
- **THEN** its badges hydrate independently and the existing feed remains usable

#### Scenario: Dynamic household rail is a de-duplication exception

- **WHEN** a household result contains a title already present in the prior Home
  response
- **THEN** it may render that title once without mutating or refetching Home

#### Scenario: One V2 capability fails independently

- **WHEN** Plex, exploration scoring, or household blending fails
- **THEN** no generic Home error replaces unaffected hero, rails, picker, or
  infinite scrolling
