## ADDED Requirements

### Requirement: Discovery preferences with explicit environment overrides

The household runtime document SHALL include `hide_library_items` (false by default) and `excluded_service_ids` (empty by default, at most eight unique positive IDs). Existing documents SHALL gain those defaults without migration. Optional environment variables `TASTERR_HIDE_LIBRARY_ITEMS` and `TASTERR_EXCLUDED_SERVICE_IDS` SHALL override those preferences only when explicitly set; false and the empty JSON array SHALL be valid explicit overrides. Invalid environment values SHALL fail validation. Admin GET/PUT SHALL return effective values and allowlisted lock metadata; saving SHALL preserve stored preferences beneath locks. PublicConfig SHALL remain unchanged.

#### Scenario: Missing fields preserve default browsing
- **WHEN** an existing or fresh settings document has no exclusion fields
- **THEN** both filters resolve disabled

#### Scenario: Explicit overrides include false and empty
- **WHEN** environment values explicitly disable library hiding or provide `[]`
- **THEN** they override non-default stored preferences and appear locked to the admin

#### Scenario: Saving locked controls preserves stored preferences
- **WHEN** an admin saves other settings while overrides are set
- **THEN** persisted exclusion preferences retain their underlying values and responses show effective overridden values

#### Scenario: Invalid service selections are rejected
- **WHEN** API or environment input contains duplicate, nonpositive, or more than eight excluded IDs
- **THEN** validation rejects it
- **AND** excluded IDs must be actual integers; booleans, numeric strings and floating-point numbers are rejected

#### Scenario: Explicit null or empty environment values are rejected
- **WHEN** an exclusion override is explicitly supplied as JSON `null` or an empty string
- **THEN** startup validation rejects it rather than treating it as unset

### Requirement: Exclusion controls follow region and explain precedence

The admin screen SHALL provide labelled library hiding and a separate excluded-service selector using regional service options, visible environment locks, best-effort semantics, and an explanation that exclusions win over inclusion. Changing region SHALL clear editable exclusions while retaining environment-controlled IDs for evaluation in the new region.

#### Scenario: Region changes clear editable exclusions
- **WHEN** an admin changes region without a service-exclusion override
- **THEN** the draft clears excluded service IDs

#### Scenario: Region changes retain locked exclusions
- **WHEN** an admin changes region while service exclusions are environment-controlled
- **THEN** those IDs remain fixed and are evaluated in the new region

#### Scenario: Missing regional services remain removable
- **WHEN** a saved exclusion ID is missing from the regional options or those options fail to load
- **THEN** an editable ID-labelled control allows its removal, even at the eight-service limit, while environment-controlled exclusions remain locked
