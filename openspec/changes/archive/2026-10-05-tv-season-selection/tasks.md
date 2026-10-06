# Tasks: tv-season-selection

## 1. Backend

- [x] 1.1 `clients/seerr.py`: `create_request` accepts optional `seasons`;
      forwards the list for TV, keeps `"all"` when omitted. Client test for the
      subset body.
- [x] 1.2 `api/request.py`: optional, bounded, unique `seasons` on
      `RequestBody`; `422` for seasons on a movie; thread through the re-auth
      retry. Tests: invalid inputs rejected before reads, subset preserved on
      retry.
- [x] 1.3 `catalog/normalize.py`: keep Specials (season 0) in the detail
      seasons. Normalization test updated.

## 2. Frontend

- [x] 2.1 `lib/api.ts`: `seasons` in `RequestSelection`; `SeasonSummary` alias.
      Regenerate `api.gen.ts` with `just types`.
- [x] 2.2 `SeasonPicker.tsx`: dialog with a toggle per season and Specials,
      "All seasons" toggle, OK and Cancel; regular seasons on, Specials off by
      default; OK blocked with nothing chosen.
- [x] 2.3 `RequestButton.tsx`: Request opens the dialog for TV with more than
      one season entry; OK sends `seasons` only when the choice differs from
      the default. `DetailModal.tsx` passes seasons and hides Specials from its
      own list.
- [x] 2.4 `useFocusTrap.ts`: stacked traps — only the innermost handles keys;
      background inert until the last closes.
- [x] 2.5 Vitest: dialog defaults, default body, subset with Specials,
      empty-selection block, cancel reset, Escape closes only the dialog,
      single-season direct request.

## 3. Gate

- [x] 3.1 `just check` and `just e2e` pass inside the devcontainer.
- [x] 3.2 Preview reviewed and approved before commit/PR.
