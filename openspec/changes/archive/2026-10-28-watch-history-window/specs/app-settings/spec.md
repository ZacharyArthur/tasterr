## ADDED Requirements

### Requirement: Watch-history initial window is environment-configured

The optional environment variable `TASTERR_WATCH_HISTORY_DAYS` SHALL set the
initial watch-history window in days for a link's first Plex or Jellyfin
history sync: an integer from 1 to 3650, defaulting to 365 when unset. Valid
decimal strings from the environment (for example `730`) SHALL be accepted. A
value that is not an integer in that range, including explicit JSON `null`, an
empty string, a fractional number, or a boolean, SHALL fail boot validation. Changing it SHALL
affect only future first syncs; it SHALL NOT clear any watermark or trigger a
re-import. It SHALL NOT appear in `PublicConfig` or the runtime document.

#### Scenario: Default window is one year

- **WHEN** `TASTERR_WATCH_HISTORY_DAYS` is unset
- **THEN** first Plex and Jellyfin syncs read up to 365 days back

#### Scenario: Environment value is accepted

- **WHEN** `TASTERR_WATCH_HISTORY_DAYS=730` is set in the environment
- **THEN** boot succeeds and first syncs read up to 730 days back

#### Scenario: Out-of-range value fails boot

- **WHEN** `TASTERR_WATCH_HISTORY_DAYS` is `0`, `3651`, `1.5`, `null`, or empty
- **THEN** startup validation fails rather than using a default

#### Scenario: Change applies to future first syncs only

- **WHEN** an operator raises the value and restarts
- **THEN** existing links keep syncing from their watermark, and a link whose
  sync timestamps are cleared by reset reads the new window
