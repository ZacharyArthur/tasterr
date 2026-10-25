## MODIFIED Requirements

### Requirement: Request control offers to connect Seerr

When a request returns `re_auth_required`, the request control SHALL open an
inline "Connect Seerr" dialog offering the same Seerr link methods as the account
page, omitting methods Seerr is known to refuse (as defined in `account-linking`).
The dialog SHALL show the same plain-text guidance as the account page under the
same condition (no usable Plex action and no offered Jellyfin form), alongside
the local form when local login is offered and instead of an empty form
otherwise. A successful
link SHALL retry the original request (same variant, destination, and seasons)
once. Cancel SHALL close the dialog without requesting. The dialog SHALL follow
the existing dialog focus and keyboard rules.

#### Scenario: Reconnect then retry

- **WHEN** a member reconnects Seerr from the dialog
- **THEN** the original request is retried once with the same selection

#### Scenario: Cancel requests nothing

- **WHEN** the member cancels the dialog
- **THEN** no link or request is made and the control returns to its prior state

#### Scenario: Refused methods are not offered

- **WHEN** a Jellyfin-only member's request returns `re_auth_required` and Seerr
  is known to refuse Jellyfin login
- **THEN** the dialog offers no Jellyfin option and shows local sign-in only if
  Seerr accepts local login, with the account page's guidance

#### Scenario: No usable method shows guidance only

- **WHEN** Seerr is known to refuse Jellyfin and local login and the member has no
  Plex link
- **THEN** the dialog shows only the guidance and a way to close it
