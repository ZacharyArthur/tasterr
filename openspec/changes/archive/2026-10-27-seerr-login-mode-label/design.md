## Context

See proposal.md for motivation. Current state:

- `ConnectSeerr.tsx` holds `jellyfinExpanded` (default `false`). Collapsed, it
  renders its own Email + Password form and links with `method: "local"`.
  Expanded, it renders the shared `JellyfinCredentialsForm` (Username + Password)
  and links with `method: "jellyfin"`.
- The toggle button renders only while Tasterr's Jellyfin is available, always
  reads "Use Jellyfin credentials", and exposes state only through
  `aria-expanded`.
- Both forms' submit buttons read "Connect Seerr".
- Existing tests in `Account.test.tsx` and `RequestButton.test.tsx` click "Use
  Jellyfin credentials" once and then fill Username + Password.

## Goals / Non-Goals

**Goals:**
- A member can tell from visible text which credentials the dialog will send,
  before and after toggling.

**Non-Goals:**
- Any change to which methods are offered, or to the link request.

## Decisions

1. **Flip the toggle label instead of adding a second control.** The button
   reads as the action it performs ("Use Seerr email instead" when expanded).
   Alternative: a two-button segmented switch with a pressed style, rejected as
   more code and visually inconsistent with the Plex button above it, which links
   directly rather than switching forms.

2. **One caption in `ConnectSeerr.tsx`, above whichever form renders.** A `<p>`
   with fixed text chosen from `jellyfinExpanded`, styled
   `text-sm text-app-subtle` like the Jellyfin form's labels. It lives in the
   dialog, not in `JellyfinCredentialsForm`, because that form is also used for
   linking Jellyfin itself, where "Jellyfin username and password" is already
   implied by the dialog title.

3. **Drop `aria-expanded`.** Once the label names the destination form,
   "expanded/collapsed" no longer describes the button, and assistive tech
   announces the new name on toggle.

4. **Existing tests keep working.** The first click still targets "Use Jellyfin
   credentials", and the field labels do not change.

## Security considerations

- **Frontend:** the caption and labels are fixed strings rendered as text; no
  upstream or user text is rendered. No new storage, script, or network call.
- **Endpoints, auth & sessions, outbound HTTP, database, dependencies,
  secrets / PublicConfig:** not applicable. The same request bodies go to the
  same endpoints; nothing reaches the client that did not before.

## Risks / Trade-offs

- [Same file as `seerr-media-server-awareness` 4.2] → small rebase for whichever
  change lands second; the caption logic is independent of which methods show.
- [Caption wording can drift from Seerr's own UI terms] → text names the account
  ("Seerr account", "Jellyfin"), not Seerr's internal method names.
