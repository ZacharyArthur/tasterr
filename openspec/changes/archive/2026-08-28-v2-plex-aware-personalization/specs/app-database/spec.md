## ADDED Requirements

### Requirement: Plex personalization persists only canonical taste and sync timestamps

The `users` table SHALL add nullable naive-UTC `plex_history_attempted_at` and
`plex_history_synced_at` columns. The attempted timestamp SHALL gate retry cadence;
the success timestamp SHALL define the next history window. The signals partial
unique index SHALL include `watched_plex` so one user/title has at most one Plex
watched fact. No table/column SHALL persist raw Plex history, Continue Watching,
server/account/machine/rating identifiers, server connections, resource access
tokens, or progress. Existing encrypted session token storage SHALL remain
unchanged.

#### Scenario: Existing database upgrades without a Plex write

- **WHEN** an existing v1.1 database applies the migration
- **THEN** users receive null attempt/success timestamps, existing signals/settings
  remain valid, and no token is decrypted or copied

#### Scenario: Unique index covers Plex watches

- **WHEN** concurrent imports attempt the same user/title `watched_plex` signal
- **THEN** the database permits at most one active row

#### Scenario: Continue Watching leaves no durable mirror

- **WHEN** Continue Watching is fetched and rendered
- **THEN** no Plex progress, context, rating key, connection, or raw item is added
  to SQLite

#### Scenario: Supported downgrade restores v1.1-compatible state

- **WHEN** migration `0006` is downgraded before the v1.1 application starts
- **THEN** Plex-watch signals and both timestamps are removed, the prior signal
  index is restored, profiles influenced by the removed signals are invalidated,
  and v2 disabled-rail ids are stripped without changing v1.1 runtime settings;
  an absent/unparseable settings row, missing disabled-list key, or document
  already free of v2 ids is treated as compatible and does not fail the downgrade
