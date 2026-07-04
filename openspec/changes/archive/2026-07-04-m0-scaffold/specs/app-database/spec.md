# app-database

## ADDED Requirements

### Requirement: Async SQLAlchemy engine on SQLite
The backend SHALL provide a single async SQLAlchemy 2.0 engine bound to the SQLite
file at `DATABASE_PATH`, created from settings and shared app-wide.

#### Scenario: Engine binds to the configured path
- **WHEN** the app starts with `DATABASE_PATH` set
- **THEN** the engine connects to that SQLite file, creating it if absent

### Requirement: Migrations apply idempotently on boot
Alembic SHALL be wired with a baseline migration, and the app lifespan SHALL run
`upgrade head` on every boot. Booting against an already-migrated database MUST be
a no-op, not an error.

#### Scenario: Fresh database migrates to head
- **WHEN** the app boots against a nonexistent or empty database file
- **THEN** all migrations apply and the Alembic version table records head

#### Scenario: Second boot is a no-op
- **WHEN** the app boots again against the already-migrated database
- **THEN** startup succeeds with no migration applied and no error
