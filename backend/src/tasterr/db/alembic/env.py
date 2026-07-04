import os
from pathlib import Path

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

config = context.config

# Model metadata for autogenerate; populated once ORM models exist.
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # The app lifespan passes its own connection (run_sync); the Alembic CLI does not.
    connection = config.attributes.get("connection", None)
    if connection is not None:
        do_run_migrations(connection)
        return

    # CLI path: honor DATABASE_PATH so manual migrations target the same file
    # the app uses; the ini URL is only a dev fallback.
    database_path = os.environ.get("DATABASE_PATH")
    if database_path:
        config.set_main_option("sqlalchemy.url", f"sqlite:///{Path(database_path).as_posix()}")

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as cli_connection:
        do_run_migrations(cli_connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
