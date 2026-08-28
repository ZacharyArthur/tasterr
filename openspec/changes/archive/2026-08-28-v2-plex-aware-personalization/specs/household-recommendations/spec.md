## ADDED Requirements

### Requirement: Household member discovery exposes only blend-safe identity

`GET /api/v1/recommendations/household-members` SHALL require the shared session
dependency and return known local Tasterr users using only local id, display name,
avatar URL, and `has_taste_signals`, which SHALL be true exactly when that user has
at least one stored taste signal. The list SHALL include the caller and SHALL be
ordered by ascending local user id. This coarse
activity boolean is sufficient for selection but SHALL NOT claim that upstream
profile materialization will succeed. The endpoint SHALL NOT return auth/admin
state, Seerr/Plex identity, last activity, signal kinds, profile data, scores,
credentials, or upstream data. When the global household-blend rail type is
disabled, it SHALL return no selectable members and
perform no profile/catalog/Plex work.

#### Scenario: Caller sees blend-safe household choices

- **WHEN** an authenticated user requests members while the rail type is enabled
- **THEN** the response contains only the allowlisted local identity and
  eligibility fields

#### Scenario: Caller is present and activity eligibility is stable

- **WHEN** an authenticated caller with at least one stored signal requests the
  member list before and after profile-cache invalidation
- **THEN** the caller is included with `has_taste_signals=true` both times

#### Scenario: Member ordering is stable

- **WHEN** the same household members are read repeatedly
- **THEN** they appear in ascending local-user-id order each time

#### Scenario: Disabled type exposes no picker choices

- **WHEN** an admin disabled the household-blend rail type
- **THEN** the member response is empty and no household picker is shown

#### Scenario: Unauthenticated discovery is rejected

- **WHEN** a caller without a valid session requests household members
- **THEN** the response is 401 and no household state is returned

### Requirement: Household blend requests are caller-inclusive and bounded

`POST /api/v1/recommendations/household-blend` SHALL require a valid session,
same-origin evidence, the shared authenticated mutation rate limit, and an
explicit body containing two to six unique positive local user ids. The caller's
id SHALL be present and every selected user SHALL exist and have sufficient taste.
For this endpoint, sufficient taste SHALL mean `has_taste_signals=true`; after
validation, if normal materialization produces an empty profile for any selected
member, the entire request SHALL fail generically rather than silently remove that
member.
The global household-blend rail gate SHALL be checked before profile/catalog work.
Invalid, cross-origin, rate-limited, disabled, or ineligible requests SHALL perform
no blend work and return only generic errors.

#### Scenario: Valid audience includes the caller

- **WHEN** a caller submits themselves plus one to five eligible household users
- **THEN** one bounded blend computation runs for exactly that audience

#### Scenario: Caller cannot probe an audience of others

- **WHEN** the submitted ids omit the caller
- **THEN** validation rejects the request before any other user's profile loads

#### Scenario: Unauthenticated blend is rejected

- **WHEN** a caller without a valid session posts a household blend
- **THEN** the response is 401 and no member/profile/catalog work runs

#### Scenario: Empty selected profile preserves the audience contract

- **WHEN** any validated selected member's profile materializes empty
- **THEN** no smaller-audience rail is returned and the caller receives only a
  generic failure

#### Scenario: Tasteless caller cannot blend yet

- **WHEN** the caller has no stored taste signal
- **THEN** a blend request is rejected before another member's profile loads

#### Scenario: Cross-origin or rate-limited request has no side effect

- **WHEN** a blend POST fails origin or rate-limit enforcement
- **THEN** no profile materialization, catalog call, or response rail is produced

### Requirement: Household blend combines profiles without exposing them

The blend service SHALL compute the normalized arithmetic mean of the selected
users' normalized taste profiles, build a union of their existing candidate
sources capped by the shared `CANDIDATE_CAP = 150`,
and exclude a title when any selected member has hidden it or
already has a strong-positive engagement with it. Remaining candidates SHALL use
the existing quality, single availability boost, and diversity ranking against
the combined profile. The response SHALL be one standard rail with id
`household-blend` and title **Something for Everyone Tonight**, or no rail when
fewer than the normal minimum items remain.

Only the final secret-free media summaries SHALL be returned. Per-user profiles,
signals, similarities, contribution/eligibility reasons, and scores SHALL never
be serialized or logged.

#### Scenario: Two profiles influence the order

- **WHEN** two eligible selected members have distinct positive profile features
- **THEN** the returned order is scored against their normalized mean rather than
  either profile alone

#### Scenario: Any member's hide vetoes a title

- **WHEN** one selected member has hidden an otherwise high-scoring candidate
- **THEN** that title is absent from the blend rail

#### Scenario: Individual taste remains private

- **WHEN** a blend succeeds, under-fills, or fails
- **THEN** the response and logs reveal no selected member's profile, signals,
  scores, source titles, or exclusion reason

#### Scenario: Candidate union remains bounded

- **WHEN** selected users' candidate sources contain more than 150 unique titles
- **THEN** no more than 150 deterministically encountered candidates enter blend
  vector resolution or ranking

### Requirement: Household audience selection is ephemeral and non-blocking

The SPA SHALL render an inline, keyboard/remote-accessible audience picker on Home
when the capability is enabled and at least two eligible members exist. It SHALL
use a native disclosure collapsed by default; opening it reveals the picker and a
requested result, while collapsing it hides them without affecting ordinary Home
rails. The caller SHALL remain selected; the user MAY select up to five additional
members and MUST explicitly request the blend. Selection SHALL live only in current React state,
reset on a confirmed account transition or reload, and SHALL NOT be written to
Web Storage, cookies, the database, or runtime settings.

A successful result SHALL render through the existing Rail/MediaCard interaction
and hydrate availability without delaying Home. A failed, disabled, or under-filled
blend SHALL leave ordinary browsing operable and expose only generic, accessible
status text.

Because the blend is requested after the Home response, it MAY repeat a title
already visible in Home. It SHALL still contain no duplicate title within its own
rail; this is the explicit exception to response-local Home de-duplication.

#### Scenario: Selection is not durable

- **WHEN** the user reloads Home or the confirmed household account changes
- **THEN** no prior audience selection is restored or shown to the new user

#### Scenario: Household picker starts unobtrusively collapsed

- **WHEN** eligible members make the household capability available on Home
- **THEN** only its native disclosure summary is initially visible and the user
  must open it before operating audience controls

#### Scenario: Blend failure preserves Home

- **WHEN** the blend request or its TMDB/profile work fails
- **THEN** existing Home rails remain usable and the picker reports only a generic
  accessible failure

#### Scenario: Remote navigation can operate the picker and rail

- **WHEN** a keyboard/remote user selects members, requests a blend, and traverses
  the result
- **THEN** every control has a programmatic accessible name, visible focus/state,
  and the standard arrow-key rail navigation remains intact

#### Scenario: Dynamic blend may repeat an existing Home title

- **WHEN** a requested blend contains a title already rendered by the earlier
  Home response
- **THEN** the dynamic rail may show it once without changing the existing Home
  rails or accepting client-supplied exclusion keys
