# media-requests Specification (delta)

## MODIFIED Requirements

### Requirement: Request a title as the member

`POST /api/v1/request` SHALL proxy `POST {SEERR_INTERNAL_URL}/api/v1/request` using
the **per-user Seerr session cookie** stored on the member's Tasterr session row,
so the request is attributed to that member in Seerr and subject to their own quota
and approval rules. The request body SHALL be validated (`media_type` constrained
to `movie` or `tv`, a positive integer `tmdb_id`); a TV request SHALL request the
whole series at the default quality. The global Seerr API key SHALL NOT be used for
requests. On success the response SHALL carry the title's resulting library status
so the SPA can update its badge, and the backend SHALL record a `request` taste
signal for the member server-side — a failure to record the signal SHALL NOT fail
the request response.

#### Scenario: Request lands attributed to the member

- **WHEN** an authenticated member requests a title
- **THEN** the backend calls Seerr with that member's session cookie and Seerr
  records the request as that member's

#### Scenario: TV request covers the series

- **WHEN** a member requests a TV title
- **THEN** the request asks Seerr for the whole series at the default quality

#### Scenario: Successful request returns the new status

- **WHEN** Seerr accepts the request
- **THEN** the response includes the title's resulting library status

#### Scenario: Successful request records a taste signal

- **WHEN** Seerr accepts a member's request
- **THEN** a `request` signal for that title is recorded server-side for the member

#### Scenario: Signal failure never fails the request

- **WHEN** the taste-signal write errors after Seerr accepted the request
- **THEN** the request response still reports success
