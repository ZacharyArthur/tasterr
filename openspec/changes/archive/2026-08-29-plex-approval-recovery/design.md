## Context

See `proposal.md` for motivation. The current frontend already starts Plex login
from a user-activated popup and polls independently, but its durable link-based
recovery no longer matches the living contract's tracked replacement-popup
language. Clipboard behavior also spans secure and plain-HTTP self-hosted
deployments.

## Goals / Non-Goals

**Goals:**

- Keep popup handling best-effort and polling authoritative.
- Make one BFF-provided approval URL usable through both a protected link and copy
  action for the lifetime of the pending PIN.
- Keep copy feedback current, repeatable, accessible, and focus-safe.

**Non-Goals:**

- Add a popup manager, clipboard dependency, or browser-specific recovery path.
- Change backend auth, Plex PIN, polling, or session semantics.

## Decisions

### Use a durable link instead of tracking replacement popups

The initial blank popup remains synchronous with the user's activation so popup
blockers have the best chance to allow it. Once a PIN exists, the same
backend-provided URL is always rendered as a link using a new browsing context
with opener and referrer isolation. Polling never depends on either context.

Tracking replacement windows was rejected because opener policies can sever the
handle again, while the durable link works without coupling login completion to a
browser window reference.

### Keep the two native copy mechanisms

Use the Clipboard API when available, then a temporary readonly textarea with the
browser's native copy command. The fallback is fixed outside normal layout,
removed in all outcomes, and restores the previously focused element. If both
mechanisms fail, the durable link remains the recovery path.

A dependency was rejected because the browser APIs require only a small local
fallback and no package can override browser permission policy.

### Treat each copy result as a separate live announcement

Associate feedback with a monotonically increasing attempt number so repeated
identical outcomes replace the status node. Publish a result only while its
originating control remains connected, and clear feedback on every terminal PIN
path.

## Security considerations

- The external approval URL continues to come from the BFF and is never assembled
  client-side. Both link and popup paths prevent opener access; the link also
  suppresses referrer data.
- No credential, Plex token, session token, or approval URL is placed in browser
  storage or logs. The existing HttpOnly session-cookie boundary is unchanged.
- The frontend continues to render text normally; no HTML injection path is added.
- Browser tests use invented URLs and make no live requests. No API endpoint,
  outbound client, database, dependency, CSP, or response-header behavior changes.

## Risks / Trade-offs

- The legacy native copy command may eventually disappear → retain the protected
  link and announce copy failure instead of hiding recovery.
- Browser popup policies vary → keep popup work best-effort and make polling plus
  the durable link authoritative.
- Replacing the tracked reopen action changes the written contract → archive the
  delta with the implementation so living specs and code stay atomic.

## Migration Plan

Deploy the frontend and synchronized living spec together. No data or API
migration is required. Rollback is the repository squash commit.
