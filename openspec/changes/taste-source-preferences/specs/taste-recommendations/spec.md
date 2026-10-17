# taste-recommendations Specification (delta)

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Members choose which taste sources count

Each user SHALL have a set of switched-off taste sources, empty by default. The
switchable sources and their signal kinds SHALL be: `seerr_requests`
(`seed_request_history`), `plex_history` (`watched_plex`), `jellyfin_history`
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
