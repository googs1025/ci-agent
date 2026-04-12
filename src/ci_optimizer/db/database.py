"""Database engine and session management."""

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".ci-agent" / "data.db"


def get_engine(db_path: Path = DEFAULT_DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)


engine = get_engine()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Schema migrations for existing SQLite databases.
# The project does not use Alembic, so we apply additive column
# migrations in-place at startup. Each entry:
#   (table, column, DDL fragment to ADD COLUMN)
#
# Keep these ordered chronologically. Once a migration is applied (i.e. the
# column exists), SQLite won't re-apply it thanks to the PRAGMA check.
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("findings", "skill_name", "ALTER TABLE findings ADD COLUMN skill_name TEXT"),
]


async def _apply_column_migrations(conn) -> None:
    """Add missing columns to existing tables (SQLite-compatible no-op if present)."""
    for table, column, ddl in _COLUMN_MIGRATIONS:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in result.fetchall()}  # row[1] is column name
        if column in existing:
            continue
        logger.info("Applying migration: %s", ddl)
        await conn.execute(text(ddl))


async def init_db():
    """Create all tables if they don't exist, then apply additive migrations."""
    from ci_optimizer.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_column_migrations(conn)
