## ADDED Requirements

### Requirement: Trakt personalization persists only canonical taste

Migration `0010` SHALL rebuild the signals partial unique index
(`ux_signals_unique_per_title`, whose predicate the ORM mirrors as
`SIGNAL_UNIQUE_INDEX_WHERE`) to include `watched_trakt`, so one user/title has at
most one Trakt watched fact, and SHALL delete every materialized profile so profiles rebuild
under the one-watch-per-title rule. Trakt links SHALL store the Trakt user uuid,
the Trakt username as display name, the Fernet-encrypted token set, and sync
timestamps, with no avatar URL. No table or column SHALL persist raw Trakt
history entries, slugs, device codes, or the client id or secret. The downgrade
SHALL delete `watched_trakt` signals and Trakt links, remove `trakt` from every
user's switched-off sources, invalidate affected profiles, and restore the prior
index; it SHALL delete no user. No CHECK constraint is added: signal kinds stay
validated at the application boundary, as today.

#### Scenario: Unique index covers Trakt watches

- **WHEN** concurrent imports attempt the same user/title `watched_trakt` signal
- **THEN** the database permits at most one active row

#### Scenario: Upgrade rebuilds profiles

- **WHEN** an existing database applies migration `0010`
- **THEN** no materialized profile remains and each is rebuilt from signals on
  next use

#### Scenario: Supported downgrade removes Trakt data

- **WHEN** migration `0010` is downgraded
- **THEN** `watched_trakt` signals and Trakt links are removed, no stored
  switched-off source list contains `trakt`, affected profiles are invalidated,
  every user remains, and `PRAGMA foreign_key_check` reports nothing
