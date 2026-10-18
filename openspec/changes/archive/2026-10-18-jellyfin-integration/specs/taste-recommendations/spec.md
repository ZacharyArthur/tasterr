# taste-recommendations Specification (delta)

## MODIFIED Requirements

### Requirement: Per-user profile is a decayed sum of signal vectors

A user's taste profile SHALL be the normalized sum, over their signals, of
signal weight × title vector, exponentially time-decayed with a half-life of
approximately 90 days. Signal weights SHALL be: `request` +3.0, `watched_plex`
+2.5, `watched_jellyfin`
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

### Requirement: Personalized rails compose into the home feed

The rails registry SHALL provide per-user **recommended-for-you** (the scored
candidate pool), **more-like** (TMDB recommendations and similar titles for the
first usable source in a stable per-user daily shuffle of the three newest unique
qualifying strong-positive sources, re-ranked locally), **my-list** (active
watchlist titles), and **unexpected-picks** (quality-gated low-correlation titles).
When the more-like source is `watched_plex` or `watched_jellyfin`, its title
SHALL be **Because You
Watched {title}**; for every other strong source it SHALL remain **More Like
{title}**. The provider SHALL attempt no more than the three newest unique,
non-hidden strong-positive sources before omitting the rail. No provider SHALL
receive another user's data; providers that require
an upstream capability MAY additionally receive the authenticated caller's own
linked-account capability, whichever method the caller signed in with. For a user without sufficient signals/profile the
applicable personalized providers SHALL yield nothing, degrading Home to the
non-personalized feed. Any engine failure SHALL degrade to fewer rails, never a
failed Home request.

#### Scenario: Different profiles produce visibly different homes

- **WHEN** two users with different signal histories request their home feeds
- **THEN** their personalized rails contain visibly different titles

#### Scenario: Plex watch earns an honest source label

- **WHEN** the newest usable strong source is a `watched_plex` or
  `watched_jellyfin` title
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

### Requirement: Taste profile is resettable per user

`POST /api/v1/recommendations/reset` SHALL require a valid session, the
same-origin (CSRF) check, and the shared loose authenticated-mutation rate limit.
It SHALL hold a per-user scheduling guard from before cancelling until its clear
commits, so no sync trigger can schedule a sync for that user in between; this
is the guard that unlink, account deletion, and source switch-off also hold.
It SHALL cancel and await that user's in-flight Seerr, Plex, and Jellyfin syncs, then delete only the
calling user's signals and profile and clear the sync attempt/success timestamps
on only that user's linked accounts. Cancellation SHALL be consumed rather than
propagated to the reset request, and the wait SHALL remain bounded by the sync
task deadlines. Reset SHALL NOT import anything itself: it SHALL evaluate each
linked account's sync trigger, Seerr first and the watch-history syncs waiting for
it, so re-imports run in the background under the normal single-flight rules.
When any upstream is unavailable the reset SHALL still clear the profile and leave
the user on the remaining/non-personalized experience. The response SHALL be
`204` with no body, and generic on failure. A rate-limited reset SHALL return 429
before cancelling, deleting, clearing any sync timestamp, or scheduling anything.

#### Scenario: Reset wipes and re-seeds

- **WHEN** a user with Seerr and Plex links resets their taste profile
- **THEN** their signals/profile are deleted, both links' sync timestamps are
  cleared, the response returns without waiting for any import, and a background
  Seerr re-import followed by a Plex history re-import becomes eligible

#### Scenario: Reset consumes Plex task cancellation

- **WHEN** reset cancels an in-flight or network-hung history task
- **THEN** it returns within the task deadline and no canceled write batch
  commits afterward

#### Scenario: Reset touches only the caller

- **WHEN** one user resets their profile
- **THEN** other users' signals, profiles, and link sync timestamps are untouched

#### Scenario: Reset with Seerr down still clears

- **WHEN** Seerr or a media server is unreachable during/after a reset
- **THEN** the user's taste is cleared and Home degrades without exposing an
  upstream error

#### Scenario: Reset never double-imports

- **WHEN** a user resets and then loads Home while the post-reset Seerr sync runs
- **THEN** exactly one Seerr sync runs for that user

#### Scenario: Rate-limited reset preserves the current profile

- **WHEN** an authenticated user has exhausted the shared mutation bucket and
  posts a reset
- **THEN** the response is 429 and their signals, profile, link sync timestamps,
  and task state are unchanged

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
watched through Plex or Jellyfin SHALL be excluded from the recommended-for-you
rail.

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

- **WHEN** a user has a `watched_plex` or `watched_jellyfin` signal for a title
- **THEN** that title is excluded from recommended-for-you while remaining usable
  as a candidate-source signal

#### Scenario: Near-duplicates are diversified

- **WHEN** the top-scored candidates are highly similar to one another
- **THEN** the diversity re-rank demotes near-duplicates in favor of coverage
