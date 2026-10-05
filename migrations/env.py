"""Migrations always use a distinct migrator credential."""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from jarvis.core.config import ConfigurationError, read_secret
from jarvis.storage.models import Base

raw_url = read_secret("JARVIS_MIGRATION_DATABASE_URL")
if make_url(raw_url).username != "jarvis_migrator":
    raise ConfigurationError("Migrations require the jarvis_migrator role")

kwargs = dict(
    target_metadata=Base.metadata,
    version_table="jarvis_schema_version",
    compare_type=True,
    include_schemas=True,
)

if context.is_offline_mode():
    context.configure(
        url=raw_url, literal_binds=True, dialect_opts={"paramstyle": "named"}, **kwargs
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(raw_url, poolclass=NullPool, hide_parameters=True).connect() as connection:
        context.configure(connection=connection, **kwargs)
        with context.begin_transaction():
            context.run_migrations()
