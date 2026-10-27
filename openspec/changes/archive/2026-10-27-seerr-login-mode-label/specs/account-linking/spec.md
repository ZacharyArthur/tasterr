## ADDED Requirements

### Requirement: Connect Seerr dialog names the active credentials

The Connect Seerr dialog, on the Account page and in the request control, SHALL
show a fixed caption above its credential fields naming the account they belong
to: "Sign in with your Seerr account email and password." for Seerr local
sign-in, and "Sign in with your Jellyfin username and password." for Seerr's
Jellyfin login. When the Jellyfin option is offered, its toggle SHALL be labelled
by the form it switches to: "Use Jellyfin credentials" while the Seerr local form
shows, and "Use Seerr email instead" while the Jellyfin form shows. The dialog
SHALL open on the Seerr local form.

#### Scenario: Default form names Seerr credentials

- **WHEN** a member opens the Connect Seerr dialog
- **THEN** the Email and Password fields show under the Seerr account caption

#### Scenario: Switching to Jellyfin relabels the dialog

- **WHEN** a member chooses "Use Jellyfin credentials"
- **THEN** the Username and Password fields show under the Jellyfin caption and
  the toggle reads "Use Seerr email instead"

#### Scenario: Switching back restores the Seerr form

- **WHEN** a member on the Jellyfin form chooses "Use Seerr email instead"
- **THEN** the Email and Password fields and the Seerr account caption return and
  the toggle reads "Use Jellyfin credentials"

#### Scenario: No Jellyfin option still names the credentials

- **WHEN** Jellyfin is not available and a member opens the dialog
- **THEN** no toggle is shown and the Seerr local form shows under the Seerr
  account caption
