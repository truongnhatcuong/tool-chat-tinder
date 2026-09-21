"""Database connection engine and session manager supporting MySQL (with SSL) and SQLite."""
import asyncio
import ssl
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine
)
from config.settings import get_settings
from database.models import Base
from utils.logger import logger


class AsyncSessionAdapter:
    """Wraps a synchronous SQLAlchemy session with an async interface using asyncio.to_thread."""

    def __init__(self, sync_session: Session):
        self._sync_session = sync_session

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self._sync_session.execute, statement, *args, **kwargs)

    async def flush(self) -> None:
        await asyncio.to_thread(self._sync_session.flush)

    async def commit(self) -> None:
        await asyncio.to_thread(self._sync_session.commit)

    async def rollback(self) -> None:
        await asyncio.to_thread(self._sync_session.rollback)

    async def close(self) -> None:
        await asyncio.to_thread(self._sync_session.close)

    def add(self, instance: Any) -> None:
        self._sync_session.add(instance)


# Globals
_sync_engine = None
_sync_session_factory = None
_async_engine = None
_async_session_factory = None


def _is_mysql(url: str) -> bool:
    return "mysql" in url.lower()


def get_sync_engine():
    global _sync_engine, _sync_session_factory
    if _sync_engine is None:
        raw_url = get_settings().database_url.strip()
        # Normalise to mysql+pymysql
        if raw_url.startswith("mysql://"):
            raw_url = raw_url.replace("mysql://", "mysql+pymysql://", 1)
        elif raw_url.startswith("mysql+aiomysql://"):
            raw_url = raw_url.replace("mysql+aiomysql://", "mysql+pymysql://", 1)
        
        # Strip query string for pymysql connect_args handling
        base_url = raw_url.split("?")[0]
        ctx = ssl.create_default_context()
        _sync_engine = create_engine(
            base_url,
            connect_args={"ssl": {"ssl": ctx}},
            pool_pre_ping=True,
            pool_recycle=300
        )
        _sync_session_factory = sessionmaker(bind=_sync_engine, expire_on_commit=False)
    return _sync_engine


def get_async_engine():
    global _async_engine, _async_session_factory
    if _async_engine is None:
        url = get_settings().get_database_url()
        connect_args = {}
        if "sqlite" in url:
            connect_args["check_same_thread"] = False

        _async_engine = create_async_engine(
            url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args
        )
        _async_session_factory = async_sessionmaker(
            bind=_async_engine,
            expire_on_commit=False,
            class_=AsyncSession
        )
    return _async_engine


def get_engine():
    url = get_settings().database_url
    if _is_mysql(url):
        return get_sync_engine()
    return get_async_engine()


def get_session_factory():
    url = get_settings().database_url
    if _is_mysql(url):
        get_sync_engine()
        return _sync_session_factory
    get_async_engine()
    return _async_session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[Any, None]:
    """Provide an async-compatible database session for either MySQL or SQLite."""
    url = get_settings().database_url
    if _is_mysql(url):
        get_sync_engine()
        assert _sync_session_factory is not None
        sync_sess = _sync_session_factory()
        adapter = AsyncSessionAdapter(sync_sess)
        try:
            yield adapter
            await adapter.commit()
        except Exception:
            await adapter.rollback()
            raise
        finally:
            await adapter.close()
    else:
        factory = _async_session_factory or get_async_engine() and _async_session_factory
        assert factory is not None
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


def _apply_schema_migrations(sync_conn: Any) -> None:
    """Add columns introduced after initial deployment without deleting existing data."""
    inspector = inspect(sync_conn)
    table_names = set(inspector.get_table_names())

    migrations = {
        "conversations": {
            "summary": "TEXT",
            "status": "VARCHAR(64) NOT NULL DEFAULT 'ACTIVE_CHAT'",
        },
        "match_profiles": {
            "interests_json": "TEXT",
            "notes_json": "TEXT",
        },
        "messages": {
            "status": "VARCHAR(32) NOT NULL DEFAULT 'NEW'",
        },
        "ai_replies": {
            "message_hashes": "TEXT",
        },
    }

    for table_name, required_columns in migrations.items():
        if table_name not in table_names:
            continue
        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        for column_name, column_definition in required_columns.items():
            if column_name in existing_columns:
                continue
            logger.warning(
                f"Database schema is outdated; adding {table_name}.{column_name}."
            )
            sync_conn.execute(
                text(
                    f"ALTER TABLE `{table_name}` "
                    f"ADD COLUMN `{column_name}` {column_definition}"
                )
            )


async def init_db() -> None:
    """Create tables and safely upgrade older database schemas."""
    url = get_settings().database_url
    if _is_mysql(url):
        engine = get_sync_engine()

        def _initialize_mysql() -> None:
            Base.metadata.create_all(engine)
            with engine.begin() as conn:
                _apply_schema_migrations(conn)

        await asyncio.to_thread(_initialize_mysql)
    else:
        engine = get_async_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_apply_schema_migrations)
    logger.info("Database schema initialized and migrated successfully.")


async def test_db_connection() -> bool:
    """Verify database connection health."""
    try:
        url = get_settings().database_url
        if _is_mysql(url):
            engine = get_sync_engine()
            def _check():
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            await asyncio.to_thread(_check)
            return True
        else:
            engine = get_async_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False
