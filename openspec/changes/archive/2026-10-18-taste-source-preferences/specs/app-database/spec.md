# app-database Specification (delta)

## ADDED Requirements

### Requirement: Switched-off taste sources are stored per user

Migration `0009` SHALL add `users.taste_excluded_sources`, a non-null text column
holding a JSON array of source names, defaulting to `[]` for new and existing
users. Values SHALL be validated against the switchable source list at the ORM
boundary, and an unreadable value SHALL be treated as `[]` and logged generically.
The downgrade SHALL drop the column and invalidate the materialized profiles of
users who had any source switched off.

#### Scenario: Existing users start with every source on

- **WHEN** an existing database applies migration `0009`
- **THEN** every user's switched-off set is empty and no profile changes

#### Scenario: Downgrade restores full profiles

- **WHEN** migration `0009` is downgraded
- **THEN** the column is removed and profiles that excluded sources are
  invalidated so they rebuild from all signals
