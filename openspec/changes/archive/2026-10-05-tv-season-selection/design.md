# Design: tv-season-selection

## Approach

**Additive request field.** `seasons` is optional on `POST /api/v1/request`.
Absent, the forwarded Seerr body is byte-for-byte today's (`"seasons": "all"`
for TV, nothing for movies). Present, it replaces `"all"` with the sorted list.

**Default choice equals today's request.** The dialog starts with every
regular season on and Specials off, which is the set Seerr's `"all"` requests.
Confirming that choice omits `seasons`, so the common path is unchanged even
though the dialog now appears. Any other choice, including adding Specials,
sends the explicit list.

**Specials come from the existing catalog data.** TMDB already returns season
0; normalization stops dropping it and the detail page filters it out of its
own list, so no new read is needed and the page looks the same.

**Dialog, not inline panel.** The picker is a modal over the detail modal,
matching Seerr's flow and the user-facing ask. It reuses the detail modal's
overlay (`bg-black/70`), panel (`bg-app-panel`, `rounded-lg`) and button
styles; toggles use `app-accent` / `app-surface` / `app-border` tokens.
`useFocusTrap` keeps a stack of open traps so only the innermost handles Escape
and Tab, and the background is restored only when the last trap closes.

## Security considerations

Relevant `docs/SECURITY.md` checklists: **"Any new or changed API endpoint"**
and **"Outbound HTTP"**. Auth/session, database and dependency checklists are
unaffected (no new dependency or table). Frontend: season names render as
React text, never HTML.

**Modified endpoint — `POST /api/v1/request`:**
- `seasons` is Pydantic-validated: 1-1000 integers, each 0-1000, unique.
  Invalid input is rejected with `422` before any Seerr read or write.
- `seasons` on a movie is rejected with `422` before any upstream call.
- Session, CSRF, rate limit, permission checks, variant `409`, destination
  validation, re-auth ladder and fallback are unchanged and run as before.

**Modified response — `GET /api/v1/title/tv/{id}`:** now includes TMDB's
season 0 entry; it is public catalog data with the same fields as other
seasons.

**Outbound HTTP (`clients/seerr.py`):**
- Season numbers are forwarded only as a JSON array in the request body; no
  user input reaches the outbound URL. Base URL, timeout and error mapping are
  unchanged.
- Seerr remains authoritative for quota, approval, and which seasons it
  accepts; an upstream rejection maps to the existing generic failure.

**Logging:** no new log statements.
