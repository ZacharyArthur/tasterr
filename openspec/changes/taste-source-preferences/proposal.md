# Proposal: taste-source-preferences

## Why

Once Seerr, Plex, and Jellyfin are linked accounts that each feed the taste
profile, members need a say in which of them count. GitHub #47 asks for watch
history import to be opt-in, and some members don't want browsing or old request
history shaping their recommendations. The profile is already a pure cache
rebuilt from signals, so a per-user filter makes this cheap and fully
reversible.

Last of four changes; depends on `linked-accounts` (account page, link sync
timestamps) and `jellyfin-integration` (the Jellyfin source). Advances
`taste-recommendations` and `taste-signals`.

## What Changes

- **Switchable sources** (all on by default):

  | Source | Signal kind |
  |---|---|
  | Seerr request history | `seed_request_history` |
  | Plex watch history | `watched_plex` |
  | Jellyfin watch history | `watched_jellyfin` |
  | Browsing activity | `detail_open` |

  Requests made in Tasterr, My List and onboarding picks, and "Not interested"
  always count, because they are deliberate choices.
- **Switching a source off:**
  - its signals stop counting immediately (filtered at profile computation;
    nothing is deleted);
  - importing stops: its sync no longer schedules and an in-flight sync is
    cancelled;
  - for browsing, `detail_open` posts store nothing.
- **Switching back on** restores the stored signals instantly and resets that
  link's sync timestamps, so the next sync re-imports the full bounded window.
- **"Clear imported history"** per source: deletes that source's signals after a
  confirmation step; doesn't change the toggle or the watermark.
- **"More Like" / "Because You Watched"** never anchor on a switched-off source.
- **`/account`:** each toggle and clear action sits on its provider's card;
  Browsing activity has its own toggle.
- **Storage:** one `users.taste_excluded_sources` JSON column (migration `0009`).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `taste-recommendations`: profile excludes switched-off sources; candidate
  sources for related rails, recommended-for-you, and blends exclude them; new
  requirements for choosing sources, stopping imports, clearing history, and
  the account-page controls.
- `taste-signals`: `detail_open` is not stored while browsing is off.
- `account-linking`: unconfigured providers with retained signals keep a
  controls-only card on `/account`.
- `household-recommendations`: `has_taste_signals` counts only signals that
  count toward the profile.
- `taste-onboarding`: `done` counts only signals that count toward the profile.
- `app-database`: migration `0009`.

## Impact

- **Backend:** `db/models.py` + migration `0009`; `recommend/profile.py` /
  `recommend/service.py` filter by kind; more-like anchor query; sync triggers in
  `api/taste.py` check the source state; `api/signals.py` browsing check;
  `api/account.py` toggle and clear endpoints plus `GET /account` source state.
- **Frontend:** toggles and clear actions on `Account.tsx`; regenerated
  `api.gen.ts`.
- **No new dependency.**

## Non-goals

- Per-source weights or sliders. Sources are on/off only.
- Switching off deliberate signals (requests, watchlist, not interested).
- Hiding the Continue Watching rail per user. It is not a taste signal, and the
  admin rail toggle already exists.
- Retroactively filtering signals already used in explanations shown earlier;
  explanations always reflect the current profile.
