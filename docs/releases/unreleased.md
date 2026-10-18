# Unreleased

- Accounts now belong to Tasterr, with Plex and Seerr managed from **Account**.
  Linked credentials work across devices and sign-in methods and survive sign-out.
  Unlinking or deleting the Tasterr account removes its credentials locally.
- Migration `0007` signs everyone out once. Sign in again after upgrading; existing
  taste profiles, signals, watchlists, and onboarding choices are preserved.
- Seerr request history now syncs incrementally. Reset clears recommendations and
  schedules normal history imports in the background.
- Downgrade requires a database migration or restoring the stopped pre-upgrade
  backup. An image-only rollback across `0007` is unsupported. Downgrade removes
  users without a Seerr link and their local data and signs everyone out.
