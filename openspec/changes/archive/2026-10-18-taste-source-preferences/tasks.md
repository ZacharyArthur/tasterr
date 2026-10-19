# Tasks: taste-source-preferences

The gate is per change: this change is one branch and one PR. Work the tasks in
order; a task is done when its code and named tests are written, and the final task's
checks must pass before the PR.

## 1. Model

- [x] 1.1 `recommend/signals.py`: `TasteSource` literal and source → kinds map.
      Migration `0009` adds `users.taste_excluded_sources` with downgrade
      (invalidating affected profiles). Tests: default empty, unreadable value
      treated as empty, downgrade.
      Downgrade also preserves the deleted-user id high-water mark, including
      when every user has been deleted.

## 2. Profile and rails

- [x] 2.1 Profile computation excludes switched-off kinds; toggling invalidates
      the profile. Tests: switched-off equals profile without those signals; on
      again restores it; household blend uses the member's filtered profile. Switched-off watch
      sources still exclude their titles from recommended-for-you.
      In-flight profile publication cannot undo a committed toggle or clear;
      tests also cover a same-count replacement and an updated watch fact.
- [x] 2.2 Candidate source titles (`_source_titles`, used by more-like,
      recommended-for-you, and household blends) exclude switched-off kinds;
      household `has_taste_signals` counts only kinds that count, in both the
      member list and blend validation (`api/recommendations.py`); the more-like
      label lookup in `recommend/service.py` skips switched-off kinds too. Onboarding `done` counts only kinds that
      count; a member whose only signals are switched off sees the picker. Tests: no
      "Because You Watched" from a switched-off source; recommended-for-you and
      a blend draw candidates only from sources that are on; a member whose only
      signals are switched off is not selectable; a title with switched-off
      `watched_plex` and an on `watchlist` is not labelled "Because You Watched".

## 3. Collection

- [x] 3.1 Seerr, Plex, and Jellyfin sync triggers skip switched-off sources;
      switching off cancels and awaits an in-flight sync and blocks new
      scheduling until it commits; reset skips switched-off
      sources and preserves them; switching off→on clears the
      link's timestamps and evaluates the trigger; `enabled: true` on an on
      source is a no-op. Tests per scenario.
- [x] 3.2 `POST /signals`: `detail_open` stores nothing while browsing is off.
      Test.

## 4. Account API

- [x] 4.1 `GET /account` source states; `POST /account/taste-sources`;
      `POST /account/taste-sources/{source}/clear`. Add both to the mutation
      inventory. Tests: guards (401/403/429), literal validation, caller scoping,
      clear deletes only that kind and keeps the watermark;
      overlap re-import and never-synced full import cases; clear during an
      in-flight sync writes nothing afterward; clearing `browsing` deletes only
      `detail_open`.

## 5. Frontend

- [x] 5.1 Regenerate `api.gen.ts`.
- [x] 5.2 `Account.tsx`: per-card source toggle and confirmed clear action on
      every configured provider card, linked or not, and on a minimal card for
      an unconfigured provider whose signals remain; `GET /account` returns such
      providers (API regression test);
      Browsing activity toggle and confirmed clear action; optimistic update with rollback. Vitest.
      Clear controls' accessible names include their visible labels.
      Clearing the last retained history restores focus to Connected accounts
      when its provider card disappears; regression tested.

## 6. Docs

- [x] 6.1 `docs/CONFIGURATION.md` rollback: migration `0009` downgrade drops the
      switched-off sources and rebuilds affected profiles.

## 7. Gate

- [x] 7.1 `just check`, `just e2e`, and `just container-smoke` pass inside the
      devcontainer (the PR gate runs all three); fix any failures.
