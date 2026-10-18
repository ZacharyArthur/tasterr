# taste-recommendations Specification (delta)

## MODIFIED Requirements

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
an upstream capability MAY additionally receive the authenticated caller's own
linked-account capability, whichever method the caller signed in with. For a user without sufficient signals/profile the
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

### Requirement: Taste profile is resettable per user

`POST /api/v1/recommendations/reset` SHALL require a valid session, the
same-origin (CSRF) check, and the shared loose authenticated-mutation rate limit.
It SHALL hold a per-user scheduling guard from before cancelling until its clear
commits, so no sync trigger can schedule a sync for that user in between; this
is the guard that unlink, account deletion, and source switch-off also hold.
It SHALL cancel and await that user's in-flight Seerr and Plex syncs, then delete only the
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

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Cold start seeds the profile from Seerr request history
**Reason**: Replaced by "Seerr request history synchronizes incrementally"; a
one-time seed for signal-less users misses Seerr links added later and requests
made directly in Seerr.
**Migration**: Existing seed signals are kept; the first incremental sync after
upgrade imports any missing history idempotently.
