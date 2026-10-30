## ADDED Requirements

### Requirement: Admins choose which sign-in methods are offered

The household runtime document SHALL include `disabled_sign_in_methods`, a
unique subset of `plex`, `jellyfin`, and `seerr`, empty by default, so existing
documents remain valid without migration and offer every configured method. The
optional environment variable `TASTERR_SIGN_IN_METHODS` SHALL, when set, be a
JSON array of one to three unique known method names that are the only offered
methods, overriding and locking the stored value. An empty array, JSON `null`,
an empty string, unknown names, or duplicates SHALL fail boot validation.

Admin `GET /api/v1/settings` SHALL return the effective offered methods, whether
they are locked, which methods are configured, and `sign_in_link_counts`: for
each distinct set of configured sign-in providers (`plex`, `jellyfin`, `seerr`;
link-only providers are ignored) that members have linked, the number of
members with exactly that set. It SHALL contain counts only, never member
identities. Admin `PUT /api/v1/settings` SHALL refuse with 409 and a fixed message
when, after the save, the saving admin would have no linked, configured provider
that is offered; the stored document SHALL then be unchanged. While locked, a
submitted value SHALL be ignored and the stored value preserved, as with other
locked preferences.

The Settings screen SHALL show one checkbox per method. A method that is not
configured SHALL be shown disabled and labelled as not configured. While locked,
all checkboxes SHALL be read-only with an explanation naming the environment
variable. Before saving, the screen SHALL show how many members would have no
offered method, computed from `sign_in_link_counts`. Unchecking every configured
method SHALL be prevented in the UI as well as by the save guard.

#### Scenario: Existing settings offer everything

- **WHEN** a stored document predates `disabled_sign_in_methods`
- **THEN** every configured method is offered

#### Scenario: Admin offers only Jellyfin

- **WHEN** an admin with a Jellyfin link unchecks Plex and Seerr and saves
- **THEN** the save succeeds and `/auth/methods` reports only Jellyfin

#### Scenario: Admin cannot lock themselves out

- **WHEN** an admin whose only links are Plex and Seerr saves with only Jellyfin
  offered
- **THEN** the response is 409, nothing is stored, and Plex and Seerr stay offered

#### Scenario: Stranded members are previewed

- **WHEN** an admin unchecks Plex and two members have only a Plex link
- **THEN** the screen states that two members would have no way to sign in before
  the admin saves

#### Scenario: Environment lock overrides and recovers

- **WHEN** `TASTERR_SIGN_IN_METHODS=["plex"]` is set and the stored document
  disables Plex
- **THEN** only Plex is offered, the checkboxes are read-only, and the stored
  value is preserved underneath

#### Scenario: Invalid environment value fails boot

- **WHEN** `TASTERR_SIGN_IN_METHODS` is `[]`, `null`, empty, or names an unknown
  method
- **THEN** startup validation fails rather than treating it as unset
