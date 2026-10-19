# Unreleased

- Accounts now belong to Tasterr, with Plex, Seerr, and Jellyfin managed from
  **Account** (`/account`). Display names follow Seerr → Plex → Jellyfin;
  avatars render as initials.
  Linked credentials work across devices and sign-in methods and survive sign-out.
  Unlinking or deleting the Tasterr account removes its credentials locally.
- Migration `0007` signs everyone out once. Sign in again after upgrading; existing
  taste profiles, signals, watchlists, and onboarding choices are preserved.
- Seerr request history now syncs incrementally. Reset deletes all taste signals,
  including My List and Not interested, clears sync times, and schedules enabled
  history imports in the background; source
  preferences and onboarding completion are preserved.
- `PLEX_SERVER_ID` enables Plex sign-in without Seerr, gates every Plex sign-in
  and link by server access, pins history/Continue Watching, and grants the pinned
  server owner admin. Setting it removes Plex access for members who cannot see
  that server, even if Seerr admitted them before. Older imported watches remain.
- Seerr is optional with direct Plex or Jellyfin configured. Without a Plex pin,
  Seerr still gates Plex sign-in. When Seerr is configured, Plex/Jellyfin sign-in
  attempts auto-link: refusal is ignored; an outage blocks only a would-be new
  user to preserve existing identities. Link the new provider from Account before
  switching methods or removing Seerr; there is no account merge or email matching.
  An explicit Seerr unlink stays unlinked until manually reconnected.
- Sessions keep the 30-day sliding window and gain a 90-day absolute cap, so
  admission and admin checks rerun at least quarterly; revocation is not immediate.
- Jellyfin sign-in and bounded played-movie/episode history import use
  `JELLYFIN_INTERNAL_URL` plus `JELLYFIN_API_KEY`; episodes map to series TMDB ids.
  The password is forwarded once to Jellyfin and, with Seerr configured, once to
  Seerr's Jellyfin login. The temporary Jellyfin token is logged out/discarded.
  Jellyfin administrators also administer Tasterr. Playback links and Continue
  Watching remain Plex-only; no provider avatar is rendered.
- Exposing Tasterr exposes Jellyfin password sign-in from Tasterr's address,
  bypassing Jellyfin's local-network rules. Wrong passwords can lock accounts
  (10 attempts/minute/client IP). `JELLYFIN_ALLOW_EMPTY_PASSWORD` defaults false;
  enabling it permits passwordless sign-in and either Jellyfin linking path.
- Account has per-member switches for Seerr request history, Plex/Jellyfin watch
  history, and browsing activity, all initially on. Off stops collection and
  removes influence/rail anchors without deleting signals; on restores influence
  and resets link sync times for bounded re-import. Deliberate requests, My List,
  onboarding picks, and Not interested always count. Continue Watching is unaffected.
- Clear imported history removes only that source's signals, retaining its toggle
  and watermark. The 24-hour overlap can re-import recent history; a never-synced
  source can re-import its full window. Watched titles remain excluded from
  Recommended for You while their signals exist, even with their source off.
- Unlink requires another usable sign-in method and optionally deletes imported
  history. Delete account removes local data and all sessions, leaving upstream
  accounts untouched. Request controls can connect Seerr inline and retry once.
- Downgrade requires a database migration or restoring the stopped pre-upgrade
  backup. An image-only rollback across `0007` is unsupported. Downgrade removes
  users without a Seerr link and their local data and signs everyone out.
- Migration `0008` adds Jellyfin signal uniqueness; downgrade to `0007` deletes
  Jellyfin links/history and Jellyfin-only users with their local data.
  Migration `0009` adds taste-source preferences; downgrade to `0008` removes the
  preferences and invalidates affected profiles without deleting history. Older
  code resumes configured imports. Image-only rollback across either is unsupported.
  Stop the writer and back up/validate before any downgrade, or restore a matching
  pre-upgrade backup. See [upgrade instructions](../CONFIGURATION.md#upgrade-and-rollback).
- [compose.example.yaml](../../compose.example.yaml) documents published-image
  deployment and every setting. Its `2.3.1` pin remains the current release;
  these source changes need a later release containing them. No new release
  version has been assigned.
