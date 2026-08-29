# Configuration and operations

Tasterr reads deployment connections and secrets from ordinary process environment
variables; the application does not parse or require a `.env` file. The admin UI
stores only non-secret household preferences in SQLite.

The bundled Compose file explicitly loads `TASTERR_ENV_FILE` (default `.env`) into
the container, so that deployment path requires the configured file. A service
manager, container UI, or orchestrator may instead inject the same application
variable names directly. Host shell variables do not enter a Compose container by
themselves: when omitting `env_file`, declare each name under the service's
`environment` section as shown in the README. Never commit a real environment file
or place secret values directly in a Compose file.

## Application environment variables

| Variable | Required | Default | Purpose |
|---|---:|---|---|
| `TMDB_API_KEY` | For browsing | unset | TMDB v3 key used server-side for catalog reads. |
| `SEERR_INTERNAL_URL` | For Seerr integration | unset | Server-only HTTP(S) base URL used for identity, availability, history, and requests. |
| `SEERR_EXTERNAL_URL` | No | unset | Browser-visible HTTP(S) base URL for fallback “Request in Seerr” links. Embedded credentials are rejected. |
| `SEERR_API_KEY` | For Seerr reads | unset | Server-only Seerr API key. User-attributed request writes use the member's Seerr session instead. |
| `TASTERR_SECRET_KEY` | For sign-in/requests | unset | Random secret used to encrypt stored Plex tokens. Keep it stable across upgrades. |
| `DATABASE_PATH` | No | `data/tasterr.db` | SQLite path. The image sets `/data/tasterr.db` on its named volume. |
| `STATIC_DIR` | No | `static` | Compiled SPA directory. The image sets `/app/static`. |
| `TASTERR_HOST` | No | `0.0.0.0` | Uvicorn bind address. |
| `TASTERR_PORT` | No | `8000` | Uvicorn container port and healthcheck target. |
| `TASTERR_FORWARDED_ALLOW_IPS` | No | `127.0.0.1` | Comma-separated direct proxy-peer IP addresses or CIDRs allowed to supply forwarded client/scheme headers. |

Empty or missing integration values do not prevent boot. Seerr URLs must be HTTP(S).
The proxy allowlist accepts literal IP addresses and CIDRs only; empty entries,
hostnames, URLs, malformed networks, and wildcard trust fail boot.

## Compose-only variables

| Variable | Default | Purpose |
|---|---|---|
| `TASTERR_MEDIA_NETWORK` | unset | Existing external Docker network used only with `docker-compose.seerr-network.yml` when Seerr runs on this same Docker host in another Compose project. |
| `TASTERR_IMAGE` | `tasterr:latest` | Local or GHCR image name/tag used by Compose. |
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
stored Plex tokens unreadable, so affected users must sign in again before silent
Seerr re-authentication can work. Obtain the TMDB and Seerr API keys from their
respective settings pages; do not place either in browser code, Compose build args,
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
`/api/v1/health`. Sign in with an existing Seerr account. Seerr's admin permission is
re-derived on each login and controls access to Tasterr's Settings screen.

## Runtime household settings

Administrators manage these non-secret values in the Settings screen:

- two-letter TMDB region (default `US`);
- up to eight streaming service identifiers;
- enabled/disabled rail types;
- dark/light theme and crimson, azure, violet, emerald, or amber accent.

They are stored in SQLite, returned through an explicit public response model, and
never accept URLs, keys, tokens, cookies, or credentials.

The rail list includes independent switches for **Continue Watching**, **Picks You
Wouldn't Usually Watch**, and **Something for Everyone Tonight**. All three default
enabled. No application environment variable is added for Plex personalization:
Plex-backed sessions reuse their encrypted sign-in token, while local-login sessions
perform no live Plex read.

## Plex-aware operation

Plex history sync is best-effort and never blocks sign-in or Home. Tasterr evaluates
one bounded import per Plex-backed user at most every six hours. Continue Watching is
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
the server for the affected account). Tasterr has no server allow/deny list and will
not persist one; usable sibling servers continue to work while the dead share is
present. Plex's current access-removal flow is documented in
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
- Seerr unset: TMDB browsing remains available; availability is Unknown and request
  controls are disabled.
- Seerr temporarily down: browsing and learned recommendations continue; badges
  degrade to Unknown and request attempts fail generically or offer the validated
  external Seerr link.
- A local user's Seerr session expires: a request asks them to sign in again. A Plex
  user's request performs one silent re-authentication attempt with the encrypted
  stored token.
- Plex token invalid, plex.tv down, or every advertised server unreachable: ordinary
  Home rails remain available; Continue Watching is omitted and history retries only
  after the attempt throttle.
- One Plex server unreachable: successful siblings still contribute; the history
  success watermark waits for a later all-server bounded pass.
- Plex media without a canonical TMDB GUID: only that item is omitted; repair its
  library metadata as described above.

## Backup and restore

The default volume is normally named `tasterr_tasterr-data`; confirm with
`docker volume ls` if a Compose project name was supplied. Stop the only writer before
copying the database. The following streams the database without exposing it in a
temporary helper volume:

```console
VOLUME=tasterr_tasterr-data
IMAGE=tasterr:latest
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

Live Plex/Seerr contracts are opt-in and excluded from `just check` and CI. Put the
`TASTERR_LIVE_*` values named at the top of `backend/tests/live/` in a temporary file
outside the repository, restrict that file to the current user, load it only into
the devcontainer shell, and run `just test-live`. Owner, managed, and shared Plex
tokens are supplied as `TASTERR_LIVE_PLEX_OWNER_TOKEN`,
`TASTERR_LIVE_PLEX_MANAGED_TOKEN`, and `TASTERR_LIVE_PLEX_SHARED_TOKEN`. All three
are required for the five-test Plex suite; if any is unavailable, the complete suite
skips and the release record must state that generically.

```console
chmod 600 /tmp/tasterr-live.env
npx @devcontainers/cli exec --workspace-folder . bash -lc 'set -a; . /tmp/tasterr-live.env; set +a; just test-live'
```

Never put live values in `.env.example`, the repository, command output, test
fixtures, or evidence. Record only versions and generic exercised/skipped/pass/fail
results. Every v2.0 release candidate must pass these live contracts and the full
release gate before tagging, or record the narrow release-owner exception in
[RELEASING.md section 5](RELEASING.md#5-run-live-seerr-and-plex-contracts).

## Troubleshooting

- `network ... declared as external, but could not be found`: this applies only to
  the optional same-host override; correct `TASTERR_MEDIA_NETWORK` or use the base
  Compose command for a LAN-reachable Seerr.
- Seerr connection test fails: run `docker compose exec tasterr getent hosts
  <seerr-host>` using the hostname from `SEERR_INTERNAL_URL`, then verify its port,
  routing, and API key. For the optional override, also verify both containers join
  the named network. Never paste keys into logs or issues.
- Login loops behind HTTPS: verify the proxy's direct peer is trusted and it replaces
  `X-Forwarded-Proto` with `https`.
- Health is good but the UI is unavailable: inspect `docker compose logs tasterr`
  for generic startup errors and confirm the image contains `/app/static/index.html`.
- Database write errors: confirm the named volume is mounted at `/data` and was not
  restored as root-owned content.
