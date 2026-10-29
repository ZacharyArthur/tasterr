## MODIFIED Requirements

### Requirement: Members can unlink accounts

`POST /api/v1/account/links/{provider}/unlink` with `{delete_history: bool}`
SHALL require a session, the same-origin check, and the authenticated mutation
bucket. It SHALL first cancel and await that user's in-flight sync for the
provider within its deadline, so no batch from it commits afterward, and SHALL
hold the same per-user scheduling guard as reset until it commits, so no new
sync can start in between; then delete the link and its credential; for a Plex or
Jellyfin link, clear the user's cached Continue Watching entry; for a Seerr link,
set `users.seerr_unlinked_at`
so sign-in auto-link no longer re-links Seerr; when
`delete_history` is true it SHALL also delete that source's imported signals
(`seed_request_history` for Seerr, `watched_plex` for Plex, `watched_jellyfin`
for Jellyfin) and invalidate the
profile. It SHALL refuse with 409 when no other remaining link belongs to a sign-in method
that is currently available (as `/auth/methods` would report it), so a member
cannot strand themselves after a configuration change; the check and the delete
SHALL be one atomic operation so concurrent unlinks
cannot remove every link. Tasterr
sessions SHALL stay valid after unlinking, including one signed in with the
unlinked account. `is_admin` SHALL NOT change until the next sign-in.

#### Scenario: Unlink keeps history by default

- **WHEN** a member unlinks Plex with `delete_history` false
- **THEN** the link and token are gone, `watched_plex` signals remain, and no
  further Plex sync or Continue Watching read occurs

#### Scenario: Unlink Jellyfin clears its Continue Watching

- **WHEN** a member with Plex and Jellyfin links unlinks Jellyfin
- **THEN** the cached Continue Watching entry is cleared and the next Home load
  shows only Plex items

#### Scenario: Unlink can delete history

- **WHEN** a member unlinks Plex with `delete_history` true
- **THEN** their `watched_plex` signals are deleted and their profile is
  invalidated

#### Scenario: Last link cannot be removed

- **WHEN** a member tries to unlink their only linked account
- **THEN** the response is 409 and the link is unchanged

#### Scenario: Remaining link must still sign in

- **WHEN** Seerr is no longer configured and a member with Plex and Seerr links
  unlinks Plex
- **THEN** the response is 409 and the Plex link is unchanged

#### Scenario: Unlink stops an in-flight sync

- **WHEN** a member unlinks Plex with `delete_history` true while its history
  sync is running
- **THEN** the sync is cancelled before deletion and no `watched_plex` row is
  written afterward

#### Scenario: Concurrent unlinks keep one link

- **WHEN** a member with exactly two links unlinks both concurrently
- **THEN** exactly one unlink succeeds and the other returns 409
