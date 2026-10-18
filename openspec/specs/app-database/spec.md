# app-database Specification

## Purpose
TBD - created by archiving change m0-scaffold. Update Purpose after archive.

## Requirements

### Requirement: Async SQLAlchemy engine on SQLite
The backend SHALL provide a single async SQLAlchemy 2.0 engine bound to the SQLite
file at `DATABASE_PATH`, created from settings and shared app-wide.

#### Scenario: Engine binds to the configured path
- **WHEN** the app starts with `DATABASE_PATH` set
- **THEN** the engine connects to that SQLite file, creating it if absent

### Requirement: Migrations apply idempotently on boot
Alembic SHALL be wired with a baseline migration, and the app lifespan SHALL run
`upgrade head` on every boot. Booting against an already-migrated database MUST be
a no-op, not an error.

#### Scenario: Fresh database migrates to head
- **WHEN** the app boots against a nonexistent or empty database file
- **THEN** all migrations apply and the Alembic version table records head

#### Scenario: Second boot is a no-op
- **WHEN** the app boots again against the already-migrated database
- **THEN** startup succeeds with no migration applied and no error

### Requirement: Plex personalization persists only canonical taste and sync timestamps

Each linked account SHALL carry nullable naive-UTC `sync_attempted_at` and
`sync_synced_at` columns. The attempted timestamp SHALL gate retry cadence; the
success timestamp SHALL define the next history window. The signals partial
unique index SHALL include `watched_plex` so one user/title has at most one Plex
watched fact. No table/column SHALL persist raw Plex history, Continue Watching,
server/account/machine/rating identifiers other than the linked account's own
provider id, server connections, resource access tokens, or progress. The Plex
account token SHALL be stored only Fernet-encrypted on the Plex link.

#### Scenario: Unique index covers Plex watches

- **WHEN** concurrent imports attempt the same user/title `watched_plex` signal
- **THEN** the database permits at most one active row

#### Scenario: Continue Watching leaves no durable mirror

- **WHEN** Continue Watching is fetched and rendered
- **THEN** no Plex progress, context, rating key, connection, or raw item is added
  to SQLite

#### Scenario: Existing database upgrades without a Plex write

- **WHEN** an existing v1.1 database applies migration `0006`
- **THEN** users receive null attempt/success timestamps, existing signals/settings
  remain valid, and no token is decrypted or copied

#### Scenario: Supported downgrade restores v1.1-compatible state

- **WHEN** migration `0006` is downgraded before the v1.1 application starts
- **THEN** Plex-watch signals and both timestamps are removed, the prior signal
  index is restored, profiles influenced by the removed signals are invalidated,
  and v2 disabled-rail ids are stripped without changing v1.1 runtime settings;
  an absent/unparseable settings row, missing disabled-list key, or document
  already free of v2 ids is treated as compatible and does not fail the downgrade

### Requirement: Linked-account migration forces one re-sign-in

Migration `0007` SHALL create the `linked_accounts` table with unique
`(provider, external_id)` and `(user_id, provider)` constraints and a cascading
user foreign key; add a nullable `users.seerr_unlinked_at` timestamp; rebuild `users`
with SQLite `AUTOINCREMENT` so a deleted user's id is never reused (cached
per-user data keyed by id must not reach a new user); create one
Seerr link per existing user from
`users.seerr_user_id` (display name and avatar from the user row, `linked_at` from
`users.created_at`) with no credential and null sync timestamps; delete every
session row; and drop `users.seerr_user_id`, `users.auth_type`,
`users.plex_history_attempted_at`, `users.plex_history_synced_at`,
`sessions.seerr_cookie`, and `sessions.plex_token_enc`. Migrations SHALL run with SQLite
foreign-key enforcement switched off before the migration transaction opens,
followed by `PRAGMA foreign_key_check` and re-enabling enforcement, so rebuilding
`users` never cascades into signals, profiles, sessions, or links. It SHALL NOT decrypt,
copy, or log any token or cookie. Signals, profiles, title features, settings,
and onboarding state SHALL be preserved. The downgrade SHALL restore the dropped
columns, refill `seerr_user_id` from Seerr links, set `auth_type` to `plex` for
users with a Plex link and `local` otherwise, delete users without a Seerr link
together with their signals, profiles, sessions, and links explicitly (foreign
keys are off during migrations, so nothing cascades),
delete every session, drop `users.seerr_unlinked_at`, and drop `linked_accounts`.

#### Scenario: Upgrade keeps taste and signs everyone out

- **WHEN** an existing database applies migration `0007`
- **THEN** every user has one Seerr link, all signals and profiles remain, no
  session remains, and no credential was decrypted or copied

#### Scenario: Rebuilding users keeps child rows

- **WHEN** migration `0007` (or its downgrade) rebuilds `users` on a database with
  signals, profiles, and sessions
- **THEN** signals and profiles survive with the same user ids, and
  `PRAGMA foreign_key_check` reports nothing

#### Scenario: Deleted user ids are never reused

- **WHEN** the user with the highest id deletes their account and a new user is
  created
- **THEN** the new user gets a fresh id, never the deleted one

#### Scenario: Downgrade leaves no orphans

- **WHEN** the downgrade removes a user who has signals, a profile, and sessions
- **THEN** none of their rows remain, retained users keep theirs, and
  `PRAGMA foreign_key_check` reports nothing

#### Scenario: Supported downgrade restores the prior shape

- **WHEN** migration `0007` is downgraded
- **THEN** users with a Seerr link regain `seerr_user_id`, users without one are
  removed with their data, all sessions are deleted, and `linked_accounts` is gone
