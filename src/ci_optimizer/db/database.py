"""Database engine and session management.

架构角色：数据层的基础设施，负责 SQLite 连接管理和 schema 生命周期。
核心职责：创建异步引擎与 session 工厂，在启动时执行 DDL 建表以及轻量级迁移。
与其他模块的关系：被 FastAPI 应用启动事件调用 init_db()；
async_session 工厂被所有 API 路由和服务通过依赖注入使用。
项目不引入 Alembic，改用本模块内的 _COLUMN_MIGRATIONS 列表做增量列迁移。
"""

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".ci-agent" / "data.db"


def get_engine(db_path: Path = DEFAULT_DB_PATH):
    """创建并返回指向指定路径的异步 SQLite 引擎，自动建立父目录。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)


engine = get_engine()
# expire_on_commit=False：避免异步场景下 commit 后访问 ORM 属性时触发隐式 IO
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
    ("analysis_reports", "filters_hash", "ALTER TABLE analysis_reports ADD COLUMN filters_hash TEXT"),
]


async def _apply_column_migrations(conn) -> None:
    """Add missing columns to existing tables (SQLite-compatible no-op if present).

    用 PRAGMA table_info 做幂等检查：列已存在则跳过，避免 ALTER TABLE 报错。
    SQLite 不支持 IF NOT EXISTS 语法，因此必须手动查询列清单再决定是否执行。
    """
    for table, column, ddl in _COLUMN_MIGRATIONS:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in result.fetchall()}  # row[1] is column name
        if column in existing:
            continue
        logger.info("Applying migration: %s", ddl)
        await conn.execute(text(ddl))


async def init_db():
    """Create all tables if they don't exist, then apply additive migrations.

    应用启动时调用一次。先用 SQLAlchemy metadata 创建全部表，
    再补丁式追加新列，确保旧数据库平滑升级而无需停机迁移工具。
    """
    from ci_optimizer.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_column_migrations(conn)
