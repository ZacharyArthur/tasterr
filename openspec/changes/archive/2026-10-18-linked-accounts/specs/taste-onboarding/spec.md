# taste-onboarding Specification (delta)

## MODIFIED Requirements

### Requirement: Onboarding eligibility follows cold-start outcome

`GET /api/v1/taste-onboarding` SHALL return, checked in this order: `done` when
the user has any signal or has previously completed/dismissed the picker;
otherwise `pending` while any of the user's history syncs (Seerr request history
or a watch-history sync) is reserved or running; otherwise `show`. A user with
signals is therefore never `pending`, even while a routine sync runs. The endpoint SHALL use only the session user's server-side
state and SHALL make no outbound request.

#### Scenario: Seed is still running

- **WHEN** a signal-less user's Seerr or watch-history sync is reserved or running
- **THEN** onboarding state is `pending`

#### Scenario: Seed produced no signals

- **WHEN** no history sync is running and the unseen user has no signals
- **THEN** onboarding state is `show`

#### Scenario: Seed produced signals

- **WHEN** the user has one or more stored signals
- **THEN** onboarding state is `done`

#### Scenario: Established user stays done during a routine sync

- **WHEN** a user with signals has a history sync running
- **THEN** onboarding state is `done`, not `pending`

#### Scenario: Unauthenticated eligibility read

- **WHEN** a client without a valid session requests onboarding state
- **THEN** the response is `401`

#### Scenario: Plex-only user waits for their history

- **WHEN** a signal-less, unseen user without a Seerr link has a Plex history
  sync running
- **THEN** onboarding state is `pending`, and `show` once it finishes without
  importing anything
