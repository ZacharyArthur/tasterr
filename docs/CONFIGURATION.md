# Configuration and operations

Tasterr reads deployment connections and secrets from ordinary process environment
variables; the application does not parse or require a `.env` file. The admin UI
stores only non-secret household preferences in SQLite.

The bundled Compose file explicitly loads `TASTERR_ENV_FILE` (default `.env`) into
the container, so that deployment path requires the configured file. A service
manager, container UI, or orchestrator may instead inject the same application
variable names directly. Host shell variables do not enter a Compose container by
themselves: when omitting `env_file`, declare each name under the service's
`environment` section as shown in [compose.example.yaml](../compose.example.yaml).
For exported-host setups, replace the mapping with bare-name list entries such as
`- PLEX_SERVER_ID`; an unset optional name is omitted instead of becoming an empty
string. When using `${NAME}` mappings, uncomment only optional values that are set.
Never commit a real environment file or place secret values directly in a Compose file.

The published-image example is saved as `compose.yaml` beside a copy of
[`.env.example`](../.env.example). Compose reads that `.env` for substitution in
the Compose file; it does not automatically inject its contents into containers.
`env_file` performs injection, while `environment` overrides its entries. Inline
non-secret values and `${VAR}` substitutions can be combined; `${VAR:-default}`
supplies an optional default and `${VAR:?message}` rejects a missing requirement.
For example, `STATIC_DIR: "/app/static"` is an inline non-secret value. Keep
`TASTERR_PORT` as substitution and set it in `.env`: an inline environment value
does not supply the separate port mapping's substitution.
The source-build `docker-compose.yml` currently fixes its container target at 8000;
keep `TASTERR_PORT=8000` there and use `TASTERR_HTTP_PORT` to change the host port.
The published example follows `TASTERR_PORT` for both listener and mapped target.
Use `$$` for a literal dollar sign inline, and single-quote literal dollars in
`.env`. Shell values override substitution values. With an alternate file, pass
`--env-file` as well as setting `TASTERR_ENV_FILE`; keep relative paths beside the
Compose file. See [Docker's substitution reference](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).
Never share rendered Compose configuration: it includes secrets.

The example pins `2.3.1`; the linked-account, direct Plex/Jellyfin sign-in, and
taste-source features in the current source are unreleased. Use a release
containing them once available; no version bump is implied by this reference.
The pinned release requires Seerr and ignores `PLEX_SERVER_ID` and `JELLYFIN_*`;
in particular, setting `PLEX_SERVER_ID` on `2.3.1` does not restrict sign-in.
Existing deployments should replace their Compose file in place and preserve the
project name and data volume; moving to a new directory/project can select a new,
empty volume. Keep the existing `.env` rather than replacing it with placeholders.

## Application environment variables

| Variable | Required | Default | Purpose |
|---|---:|---|---|
| `TMDB_API_KEY` | For browsing | unset | TMDB v3 key used server-side for catalog reads. |
| `PLEX_SERVER_ID` | For Plex sign-in without Seerr | unset | Plex server machine identifier (1–64 letters, digits, or hyphens). Gates Plex sign-in/linking by server membership and pins history and Continue Watching. Find it in Plex Web → Settings → General or `/identity`. Never sent to browsers. |
| `SEERR_INTERNAL_URL` | For Seerr integration | unset | Server-only HTTP(S) base URL used for identity, availability, history, and requests. |
| `JELLYFIN_INTERNAL_URL` | For Jellyfin integration | unset | Server-only HTTP(S) base URL with a host and no embedded credentials, query, or fragment. Invalid values leave Jellyfin unconfigured. |
| `JELLYFIN_API_KEY` | For Jellyfin integration | unset | Secret server-admin API key used only for user-scoped reads. Create one in Jellyfin Dashboard → Advanced → API Keys. |
| `JELLYFIN_ALLOW_EMPTY_PASSWORD` | No | `false` | Explicitly allow passwordless Jellyfin accounts for sign-in and linking. |
| `SEERR_EXTERNAL_URL` | No | unset | Browser-visible HTTP(S) base URL for fallback “Request in Seerr” links. Embedded credentials are rejected. |
| `SEERR_API_KEY` | For Seerr reads | unset | Server-only Seerr API key. User-attributed request writes use the member's Seerr session instead. |
| `TASTERR_SECRET_KEY` | For sign-in/requests | unset | Random secret used to encrypt linked Plex tokens and Seerr cookies. Keep it stable across upgrades. |
| `DATABASE_PATH` | No | `data/tasterr.db` | SQLite path. The image sets `/data/tasterr.db` on its named volume. |
| `STATIC_DIR` | No | `static` | Compiled SPA directory. The image sets `/app/static`. |
| `TASTERR_HOST` | No | `0.0.0.0` | Uvicorn bind address. |
| `TASTERR_PORT` | No | `8000` | Uvicorn container port and healthcheck target. |
| `TASTERR_FORWARDED_ALLOW_IPS` | No | `127.0.0.1` | Comma-separated direct proxy-peer IP addresses or CIDRs allowed to supply forwarded client/scheme headers. |
| `TASTERR_PLEX_MAX_CONNECTION_PROBES` | No | `6` | Maximum unauthenticated Plex identity probes per advertised server resource. Accepts 3–12. Up to four resources are probed concurrently, so raising it can increase aggregate bounded discovery traffic. |
| `TASTERR_HIDE_LIBRARY_ITEMS` | No | unset | Override household library hiding with `true` or `false`; locks the admin control. |
| `TASTERR_EXCLUDED_SERVICE_IDS` | No | unset | Override subscription-service exclusions with a JSON array of up to eight unique positive TMDB provider IDs, e.g. `[8]`; `[]` explicitly clears exclusions and locks the control. |

Missing integration values do not prevent boot. Seerr URLs must be HTTP(S).
An explicitly empty or malformed `PLEX_SERVER_ID` fails boot; omit it to use the
Seerr gate. Seerr is optional with direct Plex or Jellyfin sign-in and `TASTERR_SECRET_KEY`.
The proxy allowlist accepts literal IP addresses and CIDRs only; empty entries,
hostnames, URLs, malformed networks, and wildcard trust fail boot.

Jellyfin needs both its URL and API key plus `TASTERR_SECRET_KEY`; partial configuration
leaves it off. Create the API key in **Jellyfin Dashboard → Advanced → API Keys**.
Exposing Tasterr exposes Jellyfin password sign-in: Jellyfin sees Tasterr's address,
so its local-network access rules do not apply. Repeated wrong passwords can lock
an account; attempts are bounded only by Tasterr's login bucket (10/min per client
IP). Empty passwords are refused before any upstream call unless
`JELLYFIN_ALLOW_EMPTY_PASSWORD=true`, including Jellyfin and Seerr-via-Jellyfin links.

## Compose-only variables

| Variable | Default | Purpose |
|---|---|---|
| `TASTERR_MEDIA_NETWORK` | unset | Existing external Docker network used only with `docker-compose.seerr-network.yml` when Seerr runs on this same Docker host in another Compose project. |
| `TASTERR_IMAGE` | `ghcr.io/zacharyarthur/tasterr:2.3.1` in the published example; `tasterr:latest` in source Compose | Optional image tag/digest override. |
| `TASTERR_HTTP_PORT` | `127.0.0.1:8000` | Host-side port or bind expression. Set `8000` or a specific LAN IP and port only for intentional direct LAN access. |
| `TASTERR_ENV_FILE` | `.env` | Environment file loaded by the bundled Compose service. With an alternate file, pass the same file to Compose via `--env-file`. This is a Compose concern, not an application requirement. |

The base Compose file leaves an optional Seerr service commented out and uses its
normal project-managed network. It does not require a pre-created network or silently
start a second Seerr.

## Secrets and first boot

Generate the application secret without relying on a host Python installation:

```console
docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Store the result only in `.env` or your secret manager. Rotating it makes previously
stored Plex tokens and Seerr cookies unreadable, so affected members must sign in
or reconnect the affected accounts. Obtain TMDB, Seerr, and Jellyfin API keys from
their respective settings pages; do not place them in browser code, Compose build args,
or image layers.

Choose `SEERR_INTERNAL_URL` according to where Seerr runs:

- **Another host:** use a routable LAN URL such as
  `http://seerr.home.arpa:5055`. No Docker network setting or change to Seerr's stack
  is needed. Docker networks do not span hosts.
- **This same Compose project:** if the commented Seerr service is enabled, use
  `http://seerr:5055`; both services automatically share the project network.
- **This Docker host, another Compose project:** set `TASTERR_MEDIA_NETWORK` to an
  existing network already joined by Seerr, then opt into the override:

  ```console
  docker compose -f docker-compose.yml -f docker-compose.seerr-network.yml up -d --build
  ```

  Inspect the Seerr container with `docker inspect <seerr-container>` if its network
  name is unknown. The Seerr service name or network alias used by
  `SEERR_INTERNAL_URL` must resolve on that network.

For the default host-only or host-proxy path, start with
`docker compose up -d --build`. To let household clients connect directly over the
LAN, first set `TASTERR_HTTP_PORT=8000` (or a specific LAN bind) and restrict the host
firewall to the intended network. Boot upgrades SQLite to the current
Alembic revision, expires stale sessions, and then reports health at
`/api/v1/health`. Sign in with an admitted Plex, Seerr, or enabled Jellyfin account.
Admin grants from Seerr permissions, Jellyfin policy, and pinned Plex ownership are
re-derived at each sign-in and control access to Tasterr's Settings screen. Sessions
slide for 30 days but expire absolutely 90 days after creation, requiring sign-in
and fresh admission/admin checks.

## Runtime household settings

Administrators manage these non-secret values in the Settings screen:

- two-letter TMDB region (default `US`);
- up to eight streaming service identifiers;
- library hiding and up to eight excluded subscription-service identifiers (both off by default);
- enabled/disabled rail types;
- dark/light theme and crimson, azure, violet, emerald, or amber accent.

They are stored in SQLite, returned through an explicit public response model, and
never accept URLs, keys, tokens, cookies, or credentials.

Discovery exclusions apply to Home, additional rails, featured heroes, household
picks, and related-title suggestions. Search, My List, Continue Watching, and direct
title details remain accessible. Library hiding includes partially available TV and
either regular or 4K availability reported by Seerr; pending/processing requests
remain eligible. Excluded services match subscription availability in the configured
region, even when another service also offers the title. Rental, purchase, free, and
ad-supported listings alone do not hide it. Exclusions win over selected services;
a conflicting service rail is omitted and other discovery may become thin or empty.

Verification is best-effort with one five-second budget across a request's checks,
concurrency eight, and at most three pages per discover source for replacements.
Additional refill page fetches share the remaining budget; expiry retains earlier results.
Unverified titles remain visible during outages or budget expiry. Library results
use the existing 60-second availability cache; streaming membership uses TMDB's
six-hour detail cache and existing stale-on-error window (up to 48 additional hours),
so upstream metadata changes may take time to appear. The shared catalog cache holds
up to 4,096 entries, giving household discovery checks more room alongside other catalog
reads. This is an entry limit rather than a byte limit; larger households may still evict
entries and hit the best-effort verification deadline. Seerr's separate cache is unchanged.

Environment overrides take effect on restart and override only explicitly supplied
fields, including `false` and `[]`. The admin screen shows effective values and locks;
saving other preferences preserves the underlying stored values, which take effect
again after removing overrides. Invalid exclusion IDs or malformed environment
values (including empty strings, JSON `null`, booleans/numeric strings/floats in the
ID array) fail validation; omit the variable entirely to leave a preference editable.
Changing region clears editable excluded services; locked provider IDs remain fixed
and are evaluated in the new region.

The rail list includes independent switches for **Continue Watching**, **Picks You
Wouldn't Usually Watch**, and **Something for Everyone Tonight**. All three default
enabled. Any user with a Plex link reuses its encrypted account token, including
after local sign-in. Users without a Plex link perform no live Plex read.
`TASTERR_PLEX_MAX_CONNECTION_PROBES` only tunes
bounded server-side discovery and is never exposed to the browser.

## Member accounts and taste sources

Every member can open **Account** (`/account`) from the avatar menu. Link Plex via
PIN, Jellyfin via username/password, or Seerr via Plex, local credentials, or
Jellyfin credentials. Prove links before switching sign-in methods: there is no
email matching or account merge. Explicitly unlinking Seerr prevents automatic
reconnection until manually linked again. Unlink requires another usable sign-in
method; imported history is retained unless its deletion is selected. Deleting a
Tasterr account removes its local data and sessions, leaving upstream accounts alone.
Display names follow Seerr → Plex → Jellyfin priority; avatars render as initials.

All four taste sources start on: Seerr request history, Plex watch history,
Jellyfin watch history, and browsing activity. Turning a source off cancels its
import, stops collection, and excludes retained signals from the profile and rail
anchors. Turning it back on restores influence and resets that link's sync times
for a full bounded re-import. Requests made in Tasterr, My List/onboarding picks,
and Not interested always count. Continue Watching is independent of taste toggles.

**Clear imported history** deletes only that source's signals, preserving its
toggle and watermark. The 24-hour sync overlap can re-import recent activity; a
source with no completed sync can import its full window again. Retained watched
titles remain excluded from Recommended for You even with their source off;
clearing their signals removes that exclusion. Recommendation reset deletes all
taste signals, including My List and Not interested, clears sync times, and
schedules enabled sources in the background. Source preferences and the onboarding
completion flag are preserved.

## Plex-aware operation

`PLEX_SERVER_ID` pins history and Continue Watching to one machine identifier.
Find it in Plex Web → Settings → General or the server's `/identity` response.
Every Plex sign-in and link checks membership in the plex.tv resources list;
owners, shared users, and Plex Home users qualify without a PMS probe. Setting it
removes Plex sign-in for members who cannot see that server, even if Seerr
admitted them before. Without it, Seerr must accept the Plex token.

Pinning applies going forward: `watched_plex` rows already imported from other
servers stay until cleared or reset. A pinned server missing from resources yields
no media reads and does not advance the history success watermark.

Removing Seerr removes the bridge between sign-in methods. Before unsetting its
values, members who use Seerr email/password should link Plex (or Jellyfin when
available) from `/account`, or their next sign-in creates a new, empty Tasterr account.

Plex history sync is best-effort and never blocks sign-in or Home. Tasterr evaluates
one bounded import per user with a Plex link at most every six hours. Continue Watching is
live, caller-scoped presentation data cached for five minutes; raw history, progress,
server URLs, account ids, rating keys, and resource tokens are not stored. Plex
failure removes the affected rail/import only. TMDB or Seerr degradation keeps its
existing independent behavior.

Tasterr only joins Plex media to TMDB through canonical GUIDs. A legacy Plex metadata
agent may therefore leave an otherwise valid watch unresolved. Upgrade movie
libraries to **Plex Movie** and TV libraries to **Plex Series**, then run **Refresh
All Metadata** for the affected library. Plex documents the movie upgrade under
[`Manage Library > Upgrade Matching`](https://support.plex.tv/articles/upgrading-a-movie-library-to-the-use-the-new-plex-movie-agent/)
and explains why a metadata-agent change needs a
[`Refresh All Metadata`](https://support.plex.tv/articles/200289306-scanning-vs-refreshing-a-library/).
Tasterr deliberately does not fall back to title/year guessing.

If an inaccessible shared server remains in Plex resource discovery, remove that
server's library access in Plex under **Settings > Manage Library Access** (unshare
the server for the affected account). With `PLEX_SERVER_ID`, only the pinned server
is read. Without pinning, usable sibling servers continue to work while the dead
share is present. Plex's current access-removal flow is documented in
[Managing Library Access](https://support.plex.tv/articles/201105738-creating-and-managing-server-shares/).

## HTTPS and trusted proxies

Terminate TLS at a reverse proxy and prevent direct internet access to port 8000.
The proxy must replace `X-Forwarded-For` and `X-Forwarded-Proto`, set the latter to
`https`, and connect from a peer covered by `TASTERR_FORWARDED_ALLOW_IPS`. Configure
the direct proxy peer—not an arbitrary browser address. Prefer one static IP; use the
narrowest container subnet only when a fixed address is impractical. Never use `*`.

For a proxy on the host, the default loopback publication and loopback trust may be
sufficient. For a proxy container, use the Compose network plus its fixed network IP
or narrow network CIDR. A correct trusted `X-Forwarded-Proto: https` makes session
cookies `Secure` and enables the application HSTS header; forwarding headers from
any untrusted peer are ignored.

## HTTP security and private logs

Tasterr disables Uvicorn request access logs so search query strings are not written
by the application process. Configure the TLS proxy or tunnel to omit or redact query
strings too: `/search?q=...` and `/api/v1/search?q=...` contain household search
terms. Never attach raw access logs to an issue or release record.

The application removes Uvicorn's identifying server header and applies the same
browser policy to API, SPA, static, fallback, and error responses: a same-origin CSP
with explicit TMDB-image and YouTube-frame allowances, frame denial, MIME-sniffing
protection, origin-only cross-origin referrers, and denied camera/geolocation/
microphone permissions. The referrer policy preserves the origin identity required
by YouTube trailers without disclosing household paths or search queries. HSTS is
emitted only for effective HTTPS requests from a trusted proxy. The proxy may add the
same headers as defense-in-depth but must not weaken them.

## Degraded modes

- TMDB unset or unavailable: health still responds, but catalog browsing reports a
  generic unavailable state until TMDB recovers or is configured.
- Seerr unset: TMDB browsing remains available to existing sessions; availability
  is Unknown and request controls are disabled. Plex sign-in remains available with
  `PLEX_SERVER_ID` and the secret key set; Jellyfin sign-in also remains available
  when its URL, API key, and secret are set. Otherwise no new sign-in is available.
- Seerr temporarily down: browsing and learned recommendations continue; badges
  degrade to Unknown and request attempts fail generically or offer the validated
  external Seerr link.
  With a pinned server, Seerr refusing the Plex token never blocks sign-in; a
  Seerr outage blocks only a would-be new user, preserving the existing-user bridge.
  Jellyfin sign-in follows the same Seerr auto-link rule.
- A Seerr cookie expires: a member with a Plex link gets one silent re-authentication
  attempt with its encrypted token. Otherwise the request opens **Connect Seerr**;
  successful linking retries the original selection once.
- Plex token invalid, plex.tv down, or every advertised server unreachable: ordinary
  Home rails remain available; Continue Watching is omitted and history retries only
  after the attempt throttle.
- One Plex server unreachable: successful siblings still contribute; the history
  success watermark waits for a later all-server bounded pass.
- Jellyfin down: existing sessions keep browsing; history retries after its six-hour
  attempt throttle. Jellyfin sign-in/linking returns a generic upstream error.
- Plex media without a canonical TMDB GUID: only that item is omitted; repair its
  library metadata as described above.

## Backup and restore

The default volume is normally named `tasterr_tasterr-data`; confirm with
`docker volume ls` if a Compose project name was supplied. Stop the only writer before
copying the database. Select the image ID used by the existing service before
stopping it; this works for both published releases and local source builds. The
following streams the database without exposing it in a temporary helper volume:

```console
VOLUME=tasterr_tasterr-data
IMAGE="$(docker compose images -q tasterr)"
docker compose stop tasterr
docker run --rm --entrypoint python -v "$VOLUME:/data:ro" "$IMAGE" -c "import sys; sys.stdout.buffer.write(open('/data/tasterr.db','rb').read())" > tasterr.db.backup
docker compose start tasterr
```

Validate the copy before relying on it:

```console
docker run --rm -i --entrypoint python "$IMAGE" -c "import sqlite3,sys,tempfile; f=tempfile.NamedTemporaryFile(); f.write(sys.stdin.buffer.read()); f.flush(); db=sqlite3.connect(f.name); assert db.execute('PRAGMA integrity_check').fetchone()==('ok',); db.close()" < tasterr.db.backup
```

To restore, stop Tasterr, validate the backup, then stream it back as the image's
non-root application user:

```console
docker compose stop tasterr
docker run --rm -i --entrypoint python -v "$VOLUME:/data" "$IMAGE" -c "import pathlib,sys; pathlib.Path('/data/tasterr.db').write_bytes(sys.stdin.buffer.read())" < tasterr.db.backup
docker compose up -d --no-build
```

Keep backups encrypted and access-controlled: they contain identities, taste
signals, session material, and household viewing behavior.

## Upgrade and rollback

Migration `0009` adds per-user taste-source preferences, with every source on by
default. To roll back across it, stop the writer and back up/validate the database,
then use the current image's Alembic downgrade to `0008` before starting the
previous image. The downgrade removes the switched-off source settings and
invalidates affected profiles so they rebuild from all retained signals; no
history is deleted. The previous image resumes imports for every configured
linked provider. An image-only rollback across `0009` is unsupported.

Migration `0008` extends the unique signal index for `watched_jellyfin`. To roll back
across it, stop the writer and back up/validate the database first, then use the
current image's Alembic downgrade to `0007` before starting the previous image.
This deletes Jellyfin links and imported signals, invalidates affected profiles,
and deletes Jellyfin-only users together with their signals, profiles, and sessions.
Retained users' other data stays. An image-only rollback across `0008` is unsupported.

Migration `0007` makes identities local and moves external accounts into
`linked_accounts`. It signs everyone out once; sign in again after upgrading.
Taste signals, profiles, watchlists, and onboarding state are preserved. Credentials
are stored encrypted on links after signing in, survive logout, and are removed by
unlink or account deletion.

An image-only rollback across `0007` is unsupported. Stop the writer and restore
the matching pre-upgrade backup, or use the current image to downgrade to `0006`
before starting the previous image. The downgrade deletes users without a Seerr
link and all their local data, restores Seerr identities for retained users,
and deletes every session. Back up and validate the database first.

Before upgrading, take and validate a backup, record the current immutable image
digest, then set `TASTERR_IMAGE` to the new stable tag or digest. Run
`docker compose pull` and `docker compose up -d --no-build`; verify health, login,
home, detail, and one non-destructive request state check.

For an image-only rollback, restore the prior digest and recreate the service while
keeping the named volume. If a release introduced a migration that is not backward
compatible, stop the writer and restore the matching pre-upgrade database before
starting the old digest.

V2 adds migration `0006`; do not start a V1.1 image on a V2 database. The supported
order is: take and validate a backup, keep the V2 image selected, stop the writer,
downgrade to `0005`, then select and start the V1.1 image. This removes rebuildable
`watched_plex` signals and Plex sync timestamps and strips only V2 rail ids from
settings. Run the downgrade against the named volume with the V2 image:

```console
docker compose stop tasterr
docker compose run --rm --no-deps --entrypoint python tasterr -c "from alembic import command; from alembic.config import Config; c=Config(); c.set_main_option('script_location','/app/src/tasterr/db/alembic'); c.set_main_option('sqlalchemy.url','sqlite:////data/tasterr.db'); command.downgrade(c,'0005')"
# Set TASTERR_IMAGE back to the pinned V1.1 digest.
docker compose up -d --no-build
```

The `v2.0.0` release uses this downgrade sequence for any return to v1.1. An
image-only rollback across migration `0006` is unsupported.

## Live contract verification

On 2026-10-04, operator testing used Seerr **3.5.0**. Default requests and
request destination selection worked after valid root folders were configured in
Seerr. This was manual verification; the automated live suite was not rerun on
3.5.0. The earlier automated Seerr 3.3.0 baseline remains historical evidence.

Live Plex/Seerr/Jellyfin contracts are opt-in and excluded from `just check` and CI. Put the
`TASTERR_LIVE_*` values named at the top of `backend/tests/live/` in a temporary file
outside the repository, restrict that file to the current user, load it only into
the devcontainer shell, and run `just test-live`. Owner, managed, and shared Plex
tokens are supplied as `TASTERR_LIVE_PLEX_OWNER_TOKEN`,
`TASTERR_LIVE_PLEX_MANAGED_TOKEN`, and `TASTERR_LIVE_PLEX_SHARED_TOKEN`. All three
are required for the original Plex suite; if any is unavailable, those cases skip
and the release record must state that generically. The pinned-membership cases
also require `PLEX_SERVER_ID` and independently check each available managed/shared
token sees that server with `owned: false`, without probing PMS.

```console
chmod 600 /tmp/tasterr-live.env
npx @devcontainers/cli exec --workspace-folder . bash -lc 'set -a; . /tmp/tasterr-live.env; set +a; just test-live'
```

Never put live values in `.env.example`, the repository, command output, test
fixtures, or evidence. Record only versions and generic exercised/skipped/pass/fail
results. Every v2.3 release candidate must pass these live contracts and the full
release gate before tagging, or record the narrow release-owner exception in
[RELEASING.md section 5](RELEASING.md#5-run-live-seerr-plex-and-jellyfin-contracts).

Jellyfin contracts require `TASTERR_LIVE_JELLYFIN_URL`,
`TASTERR_LIVE_JELLYFIN_API_KEY`, and explicit permission via
`TASTERR_LIVE_JELLYFIN_DISPOSABLE_USERS=true`. They create and delete disposable
users, including an empty-password account and one deliberately locked out.
`TASTERR_LIVE_JELLYFIN_USER_ID` names a user with played movies/episodes for read
contracts. Seerr's Jellyfin login case uses `TASTERR_LIVE_JELLYFIN_USERNAME` and
`TASTERR_LIVE_JELLYFIN_PASSWORD`. Test disabled media-server logins on a disposable
Seerr configuration with `TASTERR_LIVE_JELLYFIN_LOGIN_DISABLED=true` or
`TASTERR_LIVE_PLEX_LOGIN_DISABLED=true`. Record tested versions and status codes
only, verify account cleanup, and remove the temporary secret file afterward.

The destination persistence contract additionally accepts
`TASTERR_LIVE_REQUEST_4K_TMDB_ID`, a disposable movie whose 4K variant is not
requested or available. The account needs the corresponding 4K request permission
and Advanced Requests (or Manage Requests/admin) permission. The suite prefers a
non-default destination, invokes the production request client, checks the stored
variant/server/profile/folder and member attribution, and records the Seerr version.
These checks do not prove downstream delivery; administrator rules can rewrite
choices. Deleting a Seerr request does not undo an autoapproved download.

## Troubleshooting

- `network ... declared as external, but could not be found`: this applies only to
  the optional same-host override; correct `TASTERR_MEDIA_NETWORK` or use the base
  Compose command for a LAN-reachable Seerr.
- Seerr connection test fails: run `docker compose exec tasterr getent hosts
  <seerr-host>` using the hostname from `SEERR_INTERNAL_URL`, then verify its port,
  routing, and API key. For the optional override, also verify both containers join
  the named network. Never paste keys into logs or issues.
- Requests show Failed in Seerr, or the picker reports an unavailable destination:
  in Seerr **Settings → Services**, select and save a valid default **Root Folder**
  and **Quality Profile** for each configured Radarr/Sonarr server, including 4K
  servers. Root folders must exist inside the corresponding Radarr/Sonarr
  container. An unset selection or stale path can cause a `RootFolderExistsValidator`
  rejection even when Tasterr successfully creates the Seerr request. Check Seerr
  logs for the delivery failure, correct the configuration, then retry in Seerr.
- Login loops behind HTTPS: verify the proxy's direct peer is trusted and it replaces
  `X-Forwarded-Proto` with `https`.
- Health is good but the UI is unavailable: inspect `docker compose logs tasterr`
  for generic startup errors and confirm the image contains `/app/static/index.html`.
- Database write errors: confirm the named volume is mounted at `/data` and was not
  restored as root-owned content.
