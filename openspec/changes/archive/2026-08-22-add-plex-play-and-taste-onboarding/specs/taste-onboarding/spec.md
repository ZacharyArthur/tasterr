## ADDED Requirements

### Requirement: Onboarding eligibility follows cold-start outcome

`GET /api/v1/taste-onboarding` SHALL return `pending` while the authenticated
user's cold-start seed is reserved or running, `show` after it is no longer
running when the user has no signals and has never handled the picker, and `done`
when the user has any signal or has previously completed/dismissed the picker.
The endpoint SHALL use only the session user's server-side state and SHALL make no
outbound request.

#### Scenario: Seed is still running

- **WHEN** a signal-less user's cold-start seed is reserved or running
- **THEN** onboarding state is `pending`

#### Scenario: Seed produced no signals

- **WHEN** the seed is no longer running and the unseen user has no signals
- **THEN** onboarding state is `show`

#### Scenario: Seed produced signals

- **WHEN** the user has one or more stored signals
- **THEN** onboarding state is `done`

#### Scenario: Unauthenticated eligibility read

- **WHEN** a client without a valid session requests onboarding state
- **THEN** the response is `401`

### Requirement: Taste picker is optional and non-blocking

When onboarding state is `show`, Home SHALL render a dismissible inline picker
using up to 12 unique titles already present in the loaded Home feed. It SHALL NOT
open a modal, trap focus, make the browse shell inert, delay Home, or prevent any
normal browse action. Each title toggle and each completion/dismissal action SHALL
be keyboard/remote focusable with visible state and focus. When state lookup fails
or no candidate exists, the picker SHALL render nothing.

#### Scenario: Eligible user sees inline choices

- **WHEN** state is `show` and Home contains candidate titles
- **THEN** the user sees title toggles plus completion and Skip controls without
  losing access to the feed

#### Scenario: Picker can be ignored

- **WHEN** the eligible user continues navigating Home without acting on the
  picker
- **THEN** all normal browse content and controls remain operable

#### Scenario: Status failure does not disturb browsing

- **WHEN** onboarding state cannot be loaded
- **THEN** polling stops and no picker or blocking error replaces the Home feed

#### Scenario: Feed refresh preserves choices

- **WHEN** Home candidates change after the user selects a title
- **THEN** completion still submits that selected title key

#### Scenario: Feed refresh cannot exceed the selection bound

- **WHEN** retained choices reach 12 and Home presents different candidates
- **THEN** new choices cannot be added until retained choices are removed or
  cleared, completion never submits more than 12 titles, and clearing restores
  the ability to choose from the current candidates

#### Scenario: Completion failure is announced without blocking browse

- **WHEN** saving selected titles fails
- **THEN** the picker remains available, its generic error is announced, and the
  rest of Home remains operable

#### Scenario: Household account changes

- **WHEN** the browser session changes from one household user to another
- **THEN** the prior user's cached onboarding state is not rendered for the new
  user

### Requirement: Selections reuse watchlist signals

`POST /api/v1/taste-onboarding` SHALL accept a validated list of at most 12 movie
or TV title keys for the authenticated user. It SHALL record each selection using
the existing idempotent `watchlist` signal, mark the user's picker handled, commit
once, and run the existing best-effort profile refresh once. An empty list SHALL
dismiss the picker without adding a signal. The endpoint SHALL add no signal kind
or weight.

#### Scenario: Selected likes become existing signals

- **WHEN** a user completes the picker with selected titles
- **THEN** each unique title has that user's existing `watchlist` signal and the
  profile refresh is requested once

#### Scenario: Skip records no taste

- **WHEN** a user submits an empty selection
- **THEN** the picker is marked handled and no signal is added

#### Scenario: Duplicate submission is idempotent

- **WHEN** the same selections are submitted more than once
- **THEN** unique watchlist constraints prevent duplicate signals

### Requirement: Picker completion persists per user

Completion or dismissal SHALL be stored on the user's database row so the picker
does not return in another session or browser. The flag SHALL contain no title,
credential, token, or upstream data and SHALL remain unchanged by recommendation
reset.

#### Scenario: Dismissal survives a new session

- **WHEN** a user dismisses the picker and later signs in from another browser
- **THEN** onboarding state remains `done`

#### Scenario: Reset does not repeat handled onboarding

- **WHEN** a user who handled the picker resets recommendations
- **THEN** the completion flag remains set and the picker is not shown again

### Requirement: Onboarding mutation is hardened

The onboarding POST SHALL require the shared session dependency, same-origin CSRF
guard, and authenticated mutation rate limit; use explicit Pydantic input/output
models; attribute state and signals only to the session user; return generic
errors; and log no selected title ids or other household viewing behavior. A
rate-limited or cross-origin request SHALL have no side effect.

#### Scenario: Cross-origin submission is rejected

- **WHEN** a browser submits onboarding from a cross-site origin
- **THEN** it receives `403` before signals or completion state change

#### Scenario: Rate-limited submission is rejected

- **WHEN** the authenticated mutation bucket is exhausted
- **THEN** it receives `429` before signals or completion state change

#### Scenario: Invalid selection is rejected

- **WHEN** a selection has an unsupported media type, non-positive id, an id
  outside the supported title-id range, or the list exceeds its bound
- **THEN** input validation rejects it before any database write
