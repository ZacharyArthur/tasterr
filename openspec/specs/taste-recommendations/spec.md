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
+2.5, `watched_jellyfin`
+2.5, `watchlist` +2.0, `seed_request_history` +2.0, `detail_open` +0.3,
`not_interested` −3.0. The profile SHALL be materialized per user and recomputed
when the user's signals or switched-off sources change or the materialization is
stale, and SHALL be
entirely rebuildable from the signals store and the user's switched-off sources
alone. Signals whose kind belongs to a switched-off source SHALL contribute
nothing.

#### Scenario: Strong signal shifts the profile

- **WHEN** a user records a `request` or imported `watched_plex` signal for a title
- **THEN** the recomputed profile moves toward that title's feature dimensions

#### Scenario: Switched-off source contributes nothing

- **WHEN** a user switches off Plex watch history
- **THEN** their recomputed profile equals one built without their `watched_plex`
  signals, while those rows remain stored

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
non-hidden strong-positive sources before omitting the rail; signals from a
switched-off source SHALL NOT be candidates. No provider SHALL
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

#### Scenario: Switched-off source never anchors a related rail

- **WHEN** a user's newest strong signal is a `watched_plex` title and Plex watch
  history is switched off
- **THEN** no "Because You Watched" rail is built from that title

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
it, so re-imports run in the background under the normal single-flight rules. Triggers for switched-off taste sources SHALL NOT be
evaluated, and the user's switched-off sources SHALL be preserved.
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

#### Scenario: Reset respects switched-off sources

- **WHEN** a member with Seerr request history switched off resets their profile
- **THEN** no Seerr re-import is scheduled, no `seed_request_history` row is
  written afterward, and the source stays off

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

### Requirement: Seerr request history synchronizes incrementally

A user's Seerr request history SHALL be imported as `seed_request_history`
signals backdated to each request's creation date, read through the global API
key filtered to the linked Seerr account id, paginated and bounded. A sign-in, a
new Seerr link, and a Home read SHALL evaluate one per-user single-flight trigger
that schedules a background sync only when the Seerr link's
`sync_attempted_at` is absent or older than six hours. The task SHALL commit the
attempt timestamp before network work. A first sync SHALL import the full bounded
history; a later sync SHALL import only requests created no earlier than 24 hours
before `sync_synced_at`. Titles for which the user already has a `request`
signal SHALL be skipped. `sync_synced_at` SHALL advance to the captured cutoff
only after a complete read; reaching the bounded row cap counts as complete. Whether the user already has other signals SHALL NOT
affect eligibility. Failures SHALL be logged without viewing data, never shown
to the user, and retried at the next eligible trigger; no sync SHALL block or
fail sign-in or Home.

#### Scenario: First sync imports history

- **WHEN** a user's Seerr account is linked for the first time
- **THEN** their bounded request history is imported as backdated seed signals
  in the background without delaying the response

#### Scenario: Linking Seerr later still imports

- **WHEN** a user with existing signals links Seerr
- **THEN** their Seerr request history is imported

#### Scenario: Requests made in Seerr reach the profile

- **WHEN** a member requests a title directly in Seerr and a later sync runs
- **THEN** that title is imported as a `seed_request_history` signal

#### Scenario: Tasterr requests are not counted twice

- **WHEN** a sync reads a request for a title the user requested through Tasterr
- **THEN** no `seed_request_history` signal is written for it

#### Scenario: Repeat syncs are idempotent

- **WHEN** the 24-hour overlap returns an already imported request
- **THEN** one `seed_request_history` row remains for that user and title

### Requirement: Members choose which taste sources count

Each user SHALL have a set of switched-off taste sources, empty by default. The
switchable sources and their signal kinds SHALL be: `seerr`
(`seed_request_history`), `plex` (`watched_plex`), `jellyfin`
(`watched_jellyfin`), and `browsing` (`detail_open`). `request`, `watchlist`, and
`not_interested` SHALL always count. `GET /api/v1/account` SHALL include each
source's on/off state; `POST /api/v1/account/taste-sources` with
`{source, enabled}` SHALL require a session, the same-origin check, and the
mutation bucket, SHALL change only the caller's state, and SHALL invalidate the
caller's profile. Switching a source off SHALL NOT delete any signal. Signals of a
switched-off source SHALL still exclude their titles from recommended-for-you,
since that exclusion is a filter on the member's own rail, not taste. They SHALL
NOT seed candidate titles for recommended-for-you, the related-title rail, or
household blends. Household
blends SHALL use each member's own switched-off sources through their profiles,
without revealing them to other members.

#### Scenario: Defaults are on

- **WHEN** a new user links Plex and Seerr
- **THEN** every switchable source is on

#### Scenario: Switching off is instant and reversible

- **WHEN** a member switches Seerr request history off and back on
- **THEN** the profile excludes, then again includes, the same stored
  `seed_request_history` rows with no re-import needed for existing rows

#### Scenario: Switched-off source seeds no candidates

- **WHEN** a member's three newest strong signals are Plex watches and Plex watch
  history is switched off
- **THEN** recommended-for-you and household blends draw candidates from their
  newest strong signals of sources that are on

#### Scenario: Watched titles stay out of recommendations

- **WHEN** a member switches Plex watch history off
- **THEN** titles they watched on Plex still never appear in recommended-for-you,
  while those watches no longer shape the profile

#### Scenario: Deliberate signals cannot be switched off

- **WHEN** a client posts a source outside the switchable list
- **THEN** input validation rejects it and nothing changes

#### Scenario: Blends respect each member's choice silently

- **WHEN** a household blend includes a member who switched off Plex history
- **THEN** that member's contribution excludes their `watched_plex` signals and
  the response reveals no source settings

### Requirement: Switched-off sources stop importing

While a source is off, its sync trigger SHALL NOT schedule, and switching it off
SHALL cancel and await that user's in-flight sync for the source within its
deadline and hold the per-user scheduling guard until the switch commits, so no
import commits afterward and no new sync starts in between. While `browsing` is off,
`POST /api/v1/signals` with `detail_open` SHALL return success without storing
anything. Switching a source from off to on SHALL clear the corresponding link's
sync timestamps and evaluate its trigger, so the next sync re-imports the full
bounded window; posting `enabled: true` for a source that is already on SHALL
change nothing.

#### Scenario: Off means no sync runs

- **WHEN** Plex history is off and the member loads Home
- **THEN** no Plex history task is scheduled

#### Scenario: Turning off cancels an in-flight sync

- **WHEN** a member switches Jellyfin history off while its sync is running
- **THEN** the task is cancelled and none of its batches commit afterward

#### Scenario: Browsing off records nothing

- **WHEN** browsing is off and the member opens a title's detail
- **THEN** no `detail_open` signal is stored

#### Scenario: Turning back on re-imports

- **WHEN** a member switches Seerr request history back on
- **THEN** the Seerr link's sync timestamps are cleared and a full bounded
  re-import becomes eligible

#### Scenario: Re-enabling an on source changes nothing

- **WHEN** a client posts `enabled: true` for a source that is already on
- **THEN** no sync timestamp is cleared and no re-import is triggered

### Requirement: Imported history can be cleared per source

`POST /api/v1/account/taste-sources/{source}/clear` SHALL require a session, the
same-origin check, and the mutation bucket; cancel and await that source's
in-flight sync and hold the per-user scheduling guard until the delete commits; delete only the caller's signals of that source's kinds; and
invalidate the profile. It SHALL NOT change the source's on/off state or sync
timestamps. With the source on, later syncs read only from the watermark's
24-hour overlap onward, so older history stays cleared, though activity inside
that overlap may return; a source that has never completed a sync re-imports its
full bounded window.
The SPA SHALL confirm before calling it.

#### Scenario: Clear deletes only that source

- **WHEN** a member clears Plex history
- **THEN** their `watched_plex` signals are deleted and every other kind remains

#### Scenario: Clear does not re-import old history

- **WHEN** a member clears Seerr request history while it stays on and a sync has
  completed before
- **THEN** the next sync imports only requests from the 24-hour overlap onward

### Requirement: Account page shows taste-source controls

The `/account` page SHALL show, on each configured provider's card, linked or
not, that provider's taste-source toggle and a "Clear imported history" action with a confirmation
step, and a separate Browsing activity toggle and clear action (with the same
confirmation) that do not depend on any link. A provider that is no
longer configured keeps its toggle and clear action: on its dormant card when
still linked, or on a card showing only those controls when unlinked with
imported signals remaining (see `account-linking`), so retained history stays
controllable.
Toggles SHALL reflect the server state, update optimistically, and roll back on
failure with a generic message.

#### Scenario: Toggles live with their accounts

- **WHEN** a member with Plex and Seerr links opens `/account`
- **THEN** the Plex card shows the Plex history toggle and clear action, the
  Seerr card shows the request history toggle and clear action, and Browsing
  activity appears on its own with its toggle and clear action

#### Scenario: Retained history stays controllable after unlink

- **WHEN** a member unlinked Plex but kept its history
- **THEN** the Plex card still shows the Plex history toggle and clear action

#### Scenario: Unconfigured provider with retained history

- **WHEN** a member has unlinked Jellyfin but still has `watched_jellyfin` signals,
  and the operator then removes Jellyfin
- **THEN** a Jellyfin card with only the toggle and clear action remains on
  `/account`

#### Scenario: Failed toggle rolls back

- **WHEN** a toggle request fails
- **THEN** the toggle returns to its previous state and a generic error is shown
