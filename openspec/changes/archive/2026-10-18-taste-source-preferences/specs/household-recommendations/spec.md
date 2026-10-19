# household-recommendations Specification (delta)

## MODIFIED Requirements

### Requirement: Household member discovery exposes only blend-safe identity

`GET /api/v1/recommendations/household-members` SHALL require the shared session
dependency and return known local Tasterr users using only local id, display name,
avatar URL, and `has_taste_signals`, which SHALL be true exactly when that user has
at least one stored taste signal of a kind that counts toward their profile (not
from a source they switched off). Whether a member switched sources off SHALL NOT
be revealed. The list SHALL include the caller and SHALL be
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

- **WHEN** an authenticated caller with at least one stored signal of a kind that
  counts toward their profile requests the member list before and after
  profile-cache invalidation
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

#### Scenario: Switched-off signals do not make a member selectable

- **WHEN** a member's only stored signals come from a source they switched off
- **THEN** they are listed with `has_taste_signals=false`, and nothing says why
