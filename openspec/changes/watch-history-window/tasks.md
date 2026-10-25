## 1. Setting

- [ ] 1.1 Add `tasterr_watch_history_days` (plain `int`, not `StrictInt`, 1–3650, default 365) to `Settings`. Verify with settings tests that set each value through the environment (`monkeypatch.setenv`), not constructor arguments: unset is 365; `"730"`, `"1"`, and `"3650"` are accepted; `"0"`, `"3651"`, `"1.5"`, `"true"`, `"null"`, and `""` fail validation; an explicit assertion that no `PublicConfig` or `RuntimeSettings` field carries the window.

## 2. History imports

- [ ] 2.1 Give `import_plex_history` and `import_jellyfin_history` an `initial_window` parameter passed from the setting by their schedulers, delete `WATCH_HISTORY_INITIAL_WINDOW`, and update tests that call the import functions directly. Verify with tests for each source: a first sync with a 730-day setting requests plays back to 730 days before the cutoff; a later sync still starts 24 hours before `sync_synced_at`; after a reset clears the sync timestamps, the next sync with a 730-day setting requests back 730 days.

## 3. Documentation

- [ ] 3.1 Document `TASTERR_WATCH_HISTORY_DAYS` in `docs/CONFIGURATION.md` (first-sync only, caps unchanged, use Reset to re-import), `.env.example`, and `compose.example.yaml` (commented, like the other optional overrides), with a line in `docs/releases/unreleased.md`. Verify `test_docs.py` and `test_env_example.py` pass under `just check`.

## 4. Gate

- [ ] 4.1 Before archiving, compare each MODIFIED block in `specs/` with the current `openspec/specs/` text and fold in anything a change archived since this one was written added. Verify with `openspec validate watch-history-window --strict`.
- [ ] 4.2 Run `just check` inside the devcontainer and fix any failures until it passes.
