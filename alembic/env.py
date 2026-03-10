from logging.config import fileConfig
from sqlalchemy import pool, engine_from_config
from alembic import context
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import Base
from app.models import *  # noqa

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Build a sync URL for Alembic:
# - Strip +asyncpg  → +psycopg2  (PostgreSQL)
# - Strip +aiosqlite → plain sqlite (SQLite)
raw_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))
sync_url = (
    raw_url
    .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    .replace("sqlite+aiosqlite://", "sqlite://")
)
config.set_main_option("sqlalchemy.url", sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
