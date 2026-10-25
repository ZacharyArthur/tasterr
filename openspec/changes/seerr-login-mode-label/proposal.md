## Why

The Connect Seerr dialog (shared by the Account page and the request control)
has two credential forms: Seerr local sign-in (Email + Password) and Seerr's
Jellyfin login (Username + Password). "Use Jellyfin credentials" toggles between
them, but its label and style never change and both forms end in the same
"Connect Seerr" button. The first field's label is the only clue to which login
is active, so members click the toggle, see the fields change, and cannot tell
which credentials Tasterr will send.

This advances the existing `account-linking` capability (linked accounts,
archived 2026-10-18) by making its Seerr link dialog state which credentials it
is asking for.

## What Changes

- The Jellyfin toggle's label names what clicking it does: "Use Jellyfin
  credentials" while the Seerr email form shows, "Use Seerr email instead" while
  the Jellyfin form shows.
- A fixed caption above the fields names the account they belong to: "Sign in
  with your Seerr account email and password." or "Sign in with your Jellyfin
  username and password." The caption shows whenever a credential form shows,
  including when the Jellyfin option is not offered.
- The toggle drops `aria-expanded`; its changing accessible name now carries the
  state.

## Non-goals

- Hiding link methods Seerr is known to refuse (for example Jellyfin on a
  Plex-backed Seerr). That is `seerr-media-server-awareness`.
- A segmented "Seerr email | Jellyfin" switch or any restyle of the dialog.
- Changing the Plex one-click button, link endpoints, request bodies, or errors.
- Aligning the two forms' label and input styles.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `account-linking`: the Connect Seerr dialog names the active credential form
  and labels its toggle by the form it switches to.

## Impact

- Frontend: `ConnectSeerr.tsx`, `routes/Account.test.tsx`.
- No backend, API, schema, migration, dependency, secret, or environment change.
- Overlaps `seerr-media-server-awareness` task 4.2, which edits the same
  component and later amends this requirement so the dialog opens on the first
  offered form.
- Landing order: seerr-login-mode-label → tmdb-metadata-language →
  discovery-exclusions-everywhere → watch-history-window →
  jellyfin-continue-watching → sign-in-method-allowlist →
  seerr-media-server-awareness → trakt-watch-history.
