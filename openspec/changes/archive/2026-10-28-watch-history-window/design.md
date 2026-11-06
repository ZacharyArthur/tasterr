## Context

See proposal.md for motivation. Current state:

- `api/taste.py` defines `WATCH_HISTORY_INITIAL_WINDOW = timedelta(days=365)`
  and uses it in `import_jellyfin_history` and `import_plex_history` only when
  the link has no `sync_synced_at`.
- Reset and switching a source back on clear the link's sync timestamps, so the
  next sync is a first sync.
- `Settings` (pydantic-settings) already validates optional `TASTERR_*`
  overrides and rejects explicit null or empty values.

## Goals / Non-Goals

**Goals:**
- One environment knob, read where the constant is used today.

**Non-Goals:**
- Any change to caps, throttles, or overlap.

## Decisions

1. **Deployment setting, not runtime.** `Settings.tasterr_watch_history_days:
   int = Field(365, ge=1, le=3650)`, a plain (lax) `int`: environment values
   arrive as strings, and a `StrictInt` rejects every one of them, valid
   `"730"` included. Lax `int` rejects `"1.5"`, `"true"`, `""`, and `null`, and
   the bounds reject `0` and `3651`. It accepts `"1.0"` as 1, which is harmless,
   so no extra validator. It is a deployment tuning
   value that changes import cost, so it belongs with environment settings,
   not the admin-editable household document. Alternative: admin runtime
   setting, rejected as UI and storage for a rarely touched knob.

2. **Replace the constant at its two uses.** `import_plex_history` and
   `import_jellyfin_history` don't take `settings` today, so each gains an
   `initial_window: timedelta` parameter. Their schedulers already hold
   `settings` and pass `timedelta(days=settings.tasterr_watch_history_days)`. The
   module constant is deleted, and tests that call the import functions directly
   pass the window. `catalog/` and `recommend/` still never
   import deployment settings.

3. **No automatic re-read.** Changing the value affects future first syncs only;
   Reset is the documented way to re-import. Alternative: detect a changed
   value and clear watermarks, rejected as hidden state for little gain.

## Risks / Trade-offs

- [A long window makes first syncs slower] → each sync stays capped at 500 rows
  per type/server and its 30-second deadline; cap overflow is already counted
  and documented.
- [Admins expect a change to apply immediately] → docs point to Reset.

## Migration Plan

No schema change. Unset means 365, today's behavior. Image-only rollback is
safe; older images ignore the variable.

## Security considerations

- **Configuration:** non-secret, boot-validated integer; invalid values fail
  closed at boot.
- **Outbound HTTP:** same Plex and Jellyfin calls with an earlier lower bound;
  volume stays bounded by existing caps and deadlines.
- **Endpoints, auth & sessions, database, frontend, dependencies,
  PublicConfig:** not applicable; nothing new is exposed or stored.
