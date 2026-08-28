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
approximately 90 days. Signal weights SHALL be: `request` +3.0, `watched_plex`
+2.5, `watchlist` +2.0, `seed_request_history` +2.0, `detail_open` +0.3,
`not_interested` −3.0. The profile SHALL be materialized per user and recomputed
when the user's signals change or the materialization is stale, and SHALL be
entirely rebuildable from the signals store alone.

#### Scenario: Strong signal shifts the profile

- **WHEN** a user records a `request` or imported `watched_plex` signal for a title
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
personalized rail; titles the user has already requested, seeded, watchlisted, or
watched through Plex SHALL be excluded from the recommended-for-you rail.

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

#### Scenario: Watched title is not recommended again

- **WHEN** a user has a `watched_plex` signal for a title
- **THEN** that title is excluded from recommended-for-you while remaining usable
  as a candidate-source signal

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

The rails registry SHALL provide per-user **recommended-for-you** (the scored
candidate pool), **more-like** (TMDB recommendations and similar titles for the
first usable source in a stable per-user daily shuffle of the three newest unique
qualifying strong-positive sources, re-ranked locally), **my-list** (active
watchlist titles), and **unexpected-picks** (quality-gated low-correlation titles).
When the more-like source is `watched_plex`, its title SHALL be **Because You
Watched {title}**; for every other strong source it SHALL remain **More Like
{title}**. The provider SHALL attempt no more than the three newest unique,
non-hidden strong-positive sources before omitting the rail. No provider SHALL
receive another user's data; providers that require
an upstream capability MAY additionally receive the authenticated caller's
session-scoped capability. For a user without sufficient signals/profile the
applicable personalized providers SHALL yield nothing, degrading Home to the
non-personalized feed. Any engine failure SHALL degrade to fewer rails, never a
failed Home request.

#### Scenario: Different profiles produce visibly different homes

- **WHEN** two users with different signal histories request their home feeds
- **THEN** their personalized rails contain visibly different titles

#### Scenario: Plex watch earns an honest source label

- **WHEN** the newest usable strong source is a `watched_plex` title
- **THEN** the related rail is labelled `Because You Watched {title}`

#### Scenario: Non-watch source keeps the existing label

- **WHEN** the newest usable strong source is a request, watchlist, onboarding,
  or Seerr-history signal
- **THEN** the related rail is labelled `More Like {title}`

#### Scenario: Related-title source rotation is daily-stable

- **WHEN** the same user requests Home repeatedly on one calendar day with the
  same three newest eligible sources
- **THEN** the same bounded source order is tried each time, while another day may
  rotate that order without changing candidate scoring

#### Scenario: Related-title fallback remains bounded

- **WHEN** the three newest eligible source titles are unavailable or produce no
  related candidates
- **THEN** the provider omits the rail without fetching a fourth source

#### Scenario: Signal-less user gets the non-personalized home

- **WHEN** a user with no signals and no profile requests the home feed
- **THEN** the feed contains the non-personalized rails and no empty
  personalized rail placeholders

#### Scenario: My List shows the active watchlist

- **WHEN** a user with watchlisted titles requests the home feed
- **THEN** a My List rail contains those titles, minus any they retracted

#### Scenario: Engine failure degrades the home

- **WHEN** profile, feature, or Plex-derived signal storage errors while composing
  the home
- **THEN** the home returns with the unaffected rails intact

### Requirement: Recommendations are explainable

`GET /api/v1/recommendations/explain?type=&id=` SHALL be session-gated with
validated inputs and return only actual positive overlapping features between the
caller's profile and the title, rendered as human-readable reasons (genre,
keyword, cast, decade, and similar labels). When the caller has no profile or the
title has no positive overlap, the response SHALL say the result is not
personalized instead of fabricating reasons. The response SHALL derive from the
caller's own profile only.

#### Scenario: Personalized title explains itself

- **WHEN** a user with a profile asks why they are seeing a title with positive
  feature overlap
- **THEN** the response lists the strongest actual overlaps as readable reasons

#### Scenario: No profile, honest answer

- **WHEN** a user without a profile asks for an explanation
- **THEN** the response indicates the browsing is not yet personalized

#### Scenario: Low-overlap exploration stays honest

- **WHEN** an unexpected-picks title has no positive feature overlap with the
  caller's non-empty profile
- **THEN** the response reports it as not personalized and fabricates no reason

### Requirement: Taste profile is resettable per user

`POST /api/v1/recommendations/reset` SHALL require a valid session, the
same-origin (CSRF) check, and the shared loose authenticated-mutation rate limit;
delete only the calling user's signals and profile; clear only that user's Plex
history attempt/success timestamps; and re-seed from their Seerr request history.
Reset SHALL cancel and await that user's in-flight Plex sync before clearing state.
Cancellation SHALL be consumed rather than propagated to the reset request, and
the wait SHALL remain bounded by the Plex task deadline.
When the caller has a usable Plex-backed session it SHALL evaluate a non-blocking
Plex history re-import only after Seerr seeding settles. When either upstream is
unavailable the reset SHALL still clear the profile and leave the user on the
remaining/non-personalized experience.
The response SHALL be secret-free and generic on failure. A rate-limited reset
SHALL return 429 before deleting, re-seeding, clearing either sync timestamp, or
scheduling anything.

#### Scenario: Reset wipes and re-seeds

- **WHEN** a Plex-backed user resets their taste profile
- **THEN** their signals/profile are deleted, Seerr history is re-seeded, their
  Plex attempt/success timestamps are cleared, and one post-seed Plex history
  re-import is eligible

#### Scenario: Reset consumes Plex task cancellation

- **WHEN** reset cancels an in-flight or network-hung Plex history task
- **THEN** it returns 200 within the Plex task deadline and no canceled write batch
  commits afterward

#### Scenario: Reset touches only the caller

- **WHEN** one user resets their profile
- **THEN** other users' signals, profiles, and Plex sync timestamps are untouched

#### Scenario: Reset with Seerr down still clears

- **WHEN** Seerr or Plex is unreachable during/after a reset
- **THEN** the user's taste is cleared and Home degrades without exposing an
  upstream error

#### Scenario: Rate-limited reset preserves the current profile

- **WHEN** an authenticated user has exhausted the shared mutation bucket and
  posts a reset
- **THEN** the response is 429 and their signals, profile, seed state, Plex
  sync timestamps, and task state are unchanged

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

### Requirement: Low-correlation picks preserve deterministic exploration

For a user with a non-empty profile, the recommendation service SHALL build a
broad pool capped by the existing `CANDIDATE_CAP = 150` from existing TMDB
discovery surfaces, exclude every hidden and strong-positive/engaged title, and
compute cosine similarity. It SHALL discard negative similarities, sort the
remainder by `(similarity, media_type, tmdb_id)`, and retain the lowest quarter
rounded up. It SHALL rank that relative fringe by the existing shrunken quality
prior and single availability boost, then apply the existing diversity penalty.
It SHALL NOT randomize results, invert similarity, or intentionally select
candidates with negative correlation.

The provider SHALL be id `unexpected-picks`, titled **Picks You Wouldn't Usually
Watch**, require the normal minimum item count, and compose after the principal
personalized, trending, popular, and recent rails so those earlier rails retain
de-duplication priority.

#### Scenario: High-correlation candidates stay out of exploration

- **WHEN** a candidate falls outside the lowest non-negative similarity quarter
  of the bounded exploration pool
- **THEN** it is ineligible for unexpected picks before quality ranking

#### Scenario: Negative-taste candidates are not forced

- **WHEN** a candidate's profile similarity is negative
- **THEN** it is ineligible for unexpected picks

#### Scenario: Quality orders fringe candidates

- **WHEN** two eligible low-correlation candidates differ in quality and neither
  has an availability advantage
- **THEN** the higher shrunken-quality candidate ranks first before diversity

#### Scenario: Thin exploration is omitted honestly

- **WHEN** fewer than the normal minimum candidates survive profile, exclusion,
  and de-duplication gates
- **THEN** no unexpected-picks placeholder or broadened threshold is returned

#### Scenario: Disabled source rail does not disable exploration input

- **WHEN** an admin disables a source rail type such as Trending or Popular while
  unexpected picks remains enabled
- **THEN** its catalog surface may still contribute candidates because source
  toggles gate presentation rather than recommendation inputs
