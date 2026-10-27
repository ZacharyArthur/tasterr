## 1. Connect Seerr dialog

- [x] 1.1 In `ConnectSeerr.tsx`, flip the Jellyfin toggle label on `jellyfinExpanded` ("Use Jellyfin credentials" / "Use Seerr email instead"), drop its `aria-expanded`, and render one fixed `text-sm text-app-subtle` caption above whichever form shows ("Sign in with your Seerr account email and password." / "Sign in with your Jellyfin username and password."). Verify by extending the "Seerr dialog offers Jellyfin only while available" test in `routes/Account.test.tsx`: default caption and Email field; after the toggle, Jellyfin caption, Username field, and the new label; after a second click, the Seerr form returns; with Jellyfin unavailable, no toggle and the Seerr caption. Existing `RequestButton.test.tsx` cases pass unchanged.

## 2. Gate

- [x] 2.1 Before archiving, compare each requirement block in `specs/` with the current `openspec/specs/` text and fold in anything a change archived since this one was written added. Verify with `openspec validate seerr-login-mode-label --strict`.
- [x] 2.2 Run `just check` inside the devcontainer and fix any failures until it passes.
