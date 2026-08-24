"""Alembic environment wired to ProofPay settings and model metadata."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import CheckConstraint, engine_from_config, pool

from proofpay.config import get_settings
from proofpay.db import Base
from proofpay.db import models as _models  # noqa: F401 - registers tables in Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_enum_check_names = frozenset(
    constraint.name
    for table in target_metadata.tables.values()
    for constraint in table.constraints
    if isinstance(constraint, CheckConstraint)
    and constraint.name is not None
    and "POSTCOMPILE" in str(constraint.sqltext)
)


def _database_url() -> str:
    """Resolve a programmatic test override before application settings."""
    override = config.attributes.get("database_url")
    return str(override) if override is not None else get_settings().database_url


def _include_object(
    _object: object,
    name: str | None,
    type_: str,
    _reflected: bool,
    _compare_to: object | None,
) -> bool:
    """Ignore only SQLAlchemy's synthetic non-native Enum CHECK constraints.

    Alembic 1.19's check-constraint plugin reports these reflected constraints
    as removals even when the same Enum exists in target metadata. Explicit
    business CHECK constraints remain part of drift detection.
    """
    return not (type_ == "check_constraint" and name in _enum_check_names)


def run_migrations_offline() -> None:
    """Generate SQL without creating an Engine."""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        render_as_batch=url.startswith("sqlite"),
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live SQLite or PostgreSQL database."""
    config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=_include_object,
            render_as_batch=connection.dialect.name == "sqlite",
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
