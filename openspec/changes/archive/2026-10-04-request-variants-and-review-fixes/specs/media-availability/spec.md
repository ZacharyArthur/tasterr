## MODIFIED Requirements

### Requirement: Availability is a typed, secret-free status

Normalization SHALL convert Seerr's `mediaInfo` into a typed domain model — a
status of available, partially available, processing, pending, or not-requested,
plus a `known` flag that is false only when Seerr is unreachable (Unknown). The
model SHALL contain no secret material and SHALL NOT import the application
settings module.

#### Scenario: Seerr status maps to a typed status

- **WHEN** Seerr reports a title as available (or partial/processing/pending)
- **THEN** normalization yields the corresponding typed status with `known` true

#### Scenario: Absent media info is not-requested

- **WHEN** a known title carries no `mediaInfo`
- **THEN** normalization yields a not-requested status with `known` true

#### Scenario: Unreachable Seerr is Unknown

- **WHEN** availability cannot be resolved because Seerr is unreachable
- **THEN** the status is Unknown with `known` false


The model SHALL expose regular_status and four_k_status independently, preserving the existing highest-fulfillment aggregate status and separately validated playback. Missing media SHALL mark both variants not_requested; unreachable media SHALL mark both unknown.

#### Scenario: Available standard variant does not hide missing 4K
- **WHEN** standard is available and 4K is absent
- **THEN** aggregate and regular status are available while four_k_status is not_requested

#### Scenario: Separate requested variants
- **WHEN** only one variant is pending
- **THEN** only its variant status is pending and the other remains not_requested
