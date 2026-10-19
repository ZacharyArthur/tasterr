# app-database Specification (delta)

## ADDED Requirements

### Requirement: Jellyfin personalization persists only canonical taste

Migration `0008` SHALL extend the signals partial unique index to include
`watched_jellyfin`, so one user/title has at most one Jellyfin watched fact.
Jellyfin links SHALL store the Jellyfin user id, display name, and sync
timestamps only, with no credential and no avatar URL. No table or column SHALL
persist raw Jellyfin items, item ids, play data, access tokens, or the API key.
The downgrade SHALL delete `watched_jellyfin` signals and Jellyfin links, delete
users left without any link together with their signals, profiles, and sessions
explicitly (foreign keys are off during migrations, so nothing cascades),
invalidate affected profiles, and restore the prior index.

#### Scenario: Unique index covers Jellyfin watches

- **WHEN** concurrent imports attempt the same user/title `watched_jellyfin` signal
- **THEN** the database permits at most one active row

#### Scenario: Jellyfin link holds no credential

- **WHEN** a Jellyfin sign-in or link completes and the link row is inspected
- **THEN** its credential column is null

#### Scenario: Downgrade leaves no orphans

- **WHEN** the downgrade removes a user who has signals, a profile, and sessions
- **THEN** none of their rows remain, retained users keep theirs, and
  `PRAGMA foreign_key_check` reports nothing

#### Scenario: Supported downgrade removes Jellyfin data

- **WHEN** migration `0008` is downgraded
- **THEN** `watched_jellyfin` signals and Jellyfin links are removed, affected
  profiles are invalidated, users left without a link are deleted, and the
  prior index is restored
