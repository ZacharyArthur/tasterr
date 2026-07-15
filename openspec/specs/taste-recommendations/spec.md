# taste-recommendations Specification

## Purpose
TBD - created by archiving change m4-taste. Update Purpose after archive.
## Requirements
### Requirement: Titles get sparse feature vectors from TMDB metadata

The engine SHALL derive a sparse, weighted feature vector per title from TMDB
metadata — genres, keywords, top-billed cast, director/creator, original
language, decade, and runtime bucket — using pure-Python dict math. Vectors
SHALL be persisted in a per-title store and reused until a documented staleness
window elapses, so repeated scoring does not refetch TMDB. Vectors SHALL contain
only public TMDB-derived metadata, never secret material.

#### Scenario: Vector derived from title facts

- **WHEN** a feature vector is built for a title
- **THEN** it contains weighted dimensions for the title's genres, keywords, top
  cast, director or creator, original language, decade, and runtime bucket

#### Scenario: Persisted vector reused

- **WHEN** a title's vector exists in the store within its staleness window
- **THEN** it is used without any TMDB fetch

#### Scenario: Stale vector refreshed

- **WHEN** a title's stored vector is older than the staleness window and the
  title is needed for scoring
- **THEN** the vector is rebuilt from fresh title facts

### Requirement: Per-user profile is a decayed sum of signal vectors

A user's taste profile SHALL be the normalized sum, over their signals, of
signal weight × title vector, exponentially time-decayed with a half-life of
approximately 90 days. Signal weights SHALL be: `request` +3.0, `watchlist`
+2.0, `seed_request_history` +2.0, `detail_open` +0.3, `not_interested` −3.0.
The profile SHALL be materialized per user and recomputed when the user's
signals change or the materialization is stale, and SHALL be entirely
rebuildable from the signals store alone.

#### Scenario: Strong signal shifts the profile

- **WHEN** a user records a `request` signal for a title
- **THEN** the recomputed profile moves toward that title's feature dimensions

#### Scenario: Signals decay by age

- **WHEN** two identical signals differ in age by one half-life
- **THEN** the older one contributes approximately half the weight of the newer

#### Scenario: Negative signal pushes features away

- **WHEN** a user records `not_interested` for a title
- **THEN** that title's feature dimensions contribute negatively to the profile

#### Scenario: Profile rebuilds from signals alone

- **WHEN** a user's materialized profile is deleted and recomputed from their
  signals
- **THEN** the result matches the previous materialization

### Requirement: Scoring blends similarity, quality, and availability with diversity

Candidate titles SHALL be scored as `alpha*cosine(profile, title) +
beta*quality_prior + gamma*availability_boost`, with the similarity term
dominating (`alpha` much greater than `beta` and `gamma`). The quality prior SHALL
derive from TMDB vote statistics. The availability boost SHALL apply exactly once
when a title is in-library per the media-availability capability **or** its
active-region flatrate provider ids intersect the global selected-service ids.
Unknown Seerr availability SHALL remove only the library contribution; missing or
wrong-region provider facts SHALL contribute no service boost. Ranked results
SHALL pass a greedy diversity re-rank penalizing similarity to already-picked
titles. Titles the user has marked `not_interested` SHALL be excluded from every
personalized rail; titles the user has already requested, seeded, or watchlisted
SHALL be excluded from the recommended-for-you rail.

Persisted feature records SHALL carry backward-compatible active-region provider
facts derived from the same TMDB detail as the vector. A missing or different
stored watch region SHALL make the record stale for lazy rebuild so a region
change never applies provider ids from the previous region.

#### Scenario: Similar title outranks dissimilar popular title
- **WHEN** a candidate closely matching the profile competes with a more popular
  candidate matching it poorly
- **THEN** the similar candidate ranks higher

#### Scenario: In-library title gets a boost
- **WHEN** two candidates score equally on similarity and quality but one is
  available in the library
- **THEN** the available one ranks higher

#### Scenario: Selected-service title gets a boost
- **WHEN** two candidates score equally on similarity and quality but one is
  confirmed flatrate on an admin-selected service in the active region
- **THEN** the selected-service candidate ranks higher

#### Scenario: Availability is not double counted
- **WHEN** a candidate is both in-library and on a selected service
- **THEN** it receives the same single availability boost as either condition
  alone

#### Scenario: Seerr down means no library boost, not no rail
- **WHEN** Seerr availability is Unknown while scoring
- **THEN** candidates still score with any valid selected-service boost and the
  rail still returns

#### Scenario: Region change invalidates provider facts lazily
- **WHEN** a feature record's watch region differs from the current global region
- **THEN** its provider facts are rebuilt from the current-region cached detail
  before they can earn a service boost

#### Scenario: Hidden title never surfaces
- **WHEN** a user has an active `not_interested` signal for a title
- **THEN** that title appears in none of their personalized rails

#### Scenario: Near-duplicates are diversified
- **WHEN** the top-scored candidates are highly similar to one another
- **THEN** the diversity re-rank demotes near-duplicates in favor of coverage

### Requirement: Cold start seeds the profile from Seerr request history

On login of a user with no stored signals, the backend SHALL import that user's
Seerr request history — read via the global API key filtered to the user's Seerr
id, paginated and bounded — as `seed_request_history` signals backdated to each
request's creation date, without blocking the login response. A failed or
impossible import (Seerr down or unconfigured) SHALL leave the user on the
non-personalized experience and be retried at the next login or reset, never
surfacing an error to the user.

#### Scenario: First login seeds the profile

- **WHEN** a user with Seerr request history logs in for the first time
- **THEN** their history is imported as backdated seed signals and their home
  reflects it within the session

#### Scenario: Login never blocks on the seed

- **WHEN** the seed import is slow or Seerr is unreachable during login
- **THEN** the login response completes normally without waiting for the import

#### Scenario: Repeat login does not duplicate the seed

- **WHEN** a user with existing signals logs in again
- **THEN** no seed import runs and no duplicate seed signals are stored

### Requirement: Personalized rails compose into the home feed

The rails registry SHALL gain per-user providers: **recommended-for-you** (the
scored candidate pool), **because-you-watched** (TMDB recommendations and
similar titles for a recent strong-positive title, re-ranked by local scoring
and titled after the source title), and **my-list** (the user's active watchlist
titles). Providers SHALL receive the authenticated user through the rail
context. For a user without sufficient signals the personalized providers SHALL
yield nothing, degrading the home to the non-personalized feed. Any engine
failure SHALL degrade to fewer rails, never a failed home request.

#### Scenario: Different profiles produce visibly different homes

- **WHEN** two users with different signal histories request their home feeds
- **THEN** their personalized rails contain visibly different titles

#### Scenario: Signal-less user gets the non-personalized home

- **WHEN** a user with no signals and no profile requests the home feed
- **THEN** the feed contains the non-personalized rails and no empty
  personalized rails

#### Scenario: My List shows the active watchlist

- **WHEN** a user with watchlisted titles requests the home feed
- **THEN** a My List rail contains those titles, minus any they retracted

#### Scenario: Engine failure degrades the home

- **WHEN** profile or feature storage errors while composing the home
- **THEN** the home returns with the non-personalized rails intact

### Requirement: Recommendations are explainable

`GET /api/v1/recommendations/explain?type=&id=` SHALL be session-gated with
validated inputs and return the top overlapping features between the caller's
profile and the title, rendered as human-readable reasons (genre, keyword, cast,
decade, and similar labels). When the caller has no profile, the response SHALL
say the result is not personalized instead of fabricating reasons. The response
SHALL derive from the caller's own profile only.

#### Scenario: Personalized title explains itself

- **WHEN** a user with a profile asks why they are seeing a title
- **THEN** the response lists the strongest overlapping features as readable
  reasons

#### Scenario: No profile, honest answer

- **WHEN** a user without a profile asks for an explanation
- **THEN** the response indicates the browsing is not yet personalized

### Requirement: Taste profile is resettable per user

`POST /api/v1/recommendations/reset` SHALL require a valid session, the same-origin
(CSRF) check, and the shared loose authenticated-mutation rate limit, delete only the
calling user's signals and profile, and then re-seed from their Seerr request history.
When Seerr is unavailable the reset SHALL still clear the profile and leave the user
on the non-personalized experience. The response SHALL be secret-free and generic on
failure. A rate-limited reset SHALL return 429 before deleting or re-seeding anything.

#### Scenario: Reset wipes and re-seeds

- **WHEN** a user resets their taste profile
- **THEN** their signals and profile are deleted and re-seeded from their Seerr
  request history

#### Scenario: Reset touches only the caller

- **WHEN** one user resets their profile
- **THEN** other users' signals and profiles are untouched

#### Scenario: Reset with Seerr down still clears

- **WHEN** Seerr is unreachable during a reset
- **THEN** the user's signals and profile are cleared and the home degrades to
  non-personalized without an error

#### Scenario: Rate-limited reset preserves the current profile

- **WHEN** an authenticated user has exhausted the shared mutation bucket and posts
  a reset
- **THEN** the response is 429 and their signals, profile, and seed state are
  unchanged

### Requirement: Live Seerr request-history contract test

A pytest-marked live suite (excluded from `just check` and CI) SHALL validate
the request-history read against a real Seerr instance — the `requestedBy`
filter, pagination, and the response shape the seed import consumes — recording
the Seerr version tested.

#### Scenario: Live suite validates the history read

- **WHEN** the live-marked tests run with real Seerr coordinates configured
- **THEN** they read a user's request history via the global key and record the
  Seerr version

#### Scenario: Default test runs skip live tests

- **WHEN** `just check` runs
- **THEN** no live-marked history test executes and no network access is
  attempted
