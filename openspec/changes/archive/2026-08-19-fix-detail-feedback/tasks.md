## 1. External Catalog Link

- [x] 1.1 Add the server-generated TMDB URL to normalized title details and cover
  movie/TV response values with backend tests.
- [x] 1.2 Regenerate the OpenAPI client types, render the isolated external link,
  and cover its accessible label, target, and relationship metadata.

## 2. Detail Interaction Fixes

- [x] 2.1 Replace in-detail card navigation while preserving the original browse
  location, with regressions for browse-opened and direct detail chains.
- [x] 2.2 Lock document scrolling for the detail overlay lifetime and test cleanup
  restores the previous body overflow value.
- [x] 2.3 Resynchronize optimistic taste state from refreshed same-title flags and
  reproduce the close/reopen My List regression in a component test.

## 3. Validation

- [x] 3.1 Validate the `fix-detail-feedback` OpenSpec change strictly and resolve
  any artifact errors.
- [x] 3.2 Run `just check` in the devcontainer and fix any failures.

## 4. Review Follow-up

- [x] 4.1 Keep focus inside the dialog when related-title navigation replaces
  the focused card, without breaking restoration to the original browse card,
  and add a focused regression test.
- [x] 4.2 Assert the external URL at the title endpoint boundary and align the
  design's link relationship metadata with the implementation.
- [x] 4.3 Record the accepted browser-history, long-modal E2E, and scrollbar-gutter
  deferrals in `docs/DEFERRED.md`.
- [x] 4.4 Strictly validate the updated `fix-detail-feedback` OpenSpec artifacts.
- [x] 4.5 Run `just check` and `just release-check` in the devcontainer and fix any
  failures.
- [x] 4.6 Treat programmatic focus on the dialog container as a focus-trap
  boundary, assert the exact related-navigation focus target, and cover immediate
  Shift+Tab wrapping.
- [x] 4.7 Document the related-title focus re-entry decision and its interaction
  with initial focus and opener restoration.
- [x] 4.8 Strictly validate the amended change, then rerun `just check` and
  `just release-check` in the devcontainer.
- [x] 4.9 Cover forward Tab from the programmatically focused dialog container,
  completing regression coverage for both boundary directions.
- [x] 4.10 Strictly validate the final change and rerun `just check` in the
  devcontainer before archive.

## 5. Release Preparation

- [x] 5.1 Upgrade audited runtime and build dependencies to available patched
  versions without adding dependencies or widening the feature scope.
- [x] 5.2 Rerun dependency audits, confirm production dependencies are clean, and
  classify any narrowly accepted development-only advisory for release evidence.
- [x] 5.3 Rerun `just check` after dependency remediation.
