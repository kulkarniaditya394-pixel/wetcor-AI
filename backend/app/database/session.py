"""Engine, sessions and the schema-upgrade mechanism.

Schema versioning uses SQLite's ``PRAGMA user_version``:
- An empty database is created from the current models and stamped with the latest version.
- An existing database is backed up, then every registered migration newer than its version runs once, in order.
The database is never recreated or erased on start-up.
"""
from __future__ import annotations

import logging
import shutil
from collections.abc import Callable, Iterator
from datetime import datetime

from sqlalchemy import Connection, create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.database.models import Base

log = logging.getLogger("wetcor.db")

# (version, description, upgrade function). Append new migrations; never edit released ones.
Migration = tuple[int, str, Callable[[Connection], None]]
MIGRATIONS: list[Migration] = [
    (1, "initial schema", lambda conn: Base.metadata.create_all(conn)),
]

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _enable_fk(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None or str(_engine.url.database) != str(settings.database_path):
        settings.ensure_dirs()
        _engine = create_engine(f"sqlite:///{settings.database_path}", connect_args={"check_same_thread": False})
        event.listen(_engine, "connect", _enable_fk)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = _SessionLocal = None


def latest_version(migrations: list[Migration] = MIGRATIONS) -> int:
    return max(v for v, _, _ in migrations)


def init_db(migrations: list[Migration] = MIGRATIONS) -> int:
    """Create or upgrade the schema. Returns the resulting schema version."""
    engine = get_engine()
    with engine.begin() as conn:
        current = conn.exec_driver_sql("PRAGMA user_version").scalar() or 0
        has_tables = bool(inspect(conn).get_table_names())
        if current == 0 and not has_tables:
            Base.metadata.create_all(conn)
            target = latest_version(migrations)
            conn.exec_driver_sql(f"PRAGMA user_version = {int(target)}")
            log.info("created database schema v%s at %s", target, settings.database_path)
            return target
        if current == 0:
            raise RuntimeError("Database has tables but no schema version; refusing to modify it. See docs/TROUBLESHOOTING.md.")
        pending = [m for m in sorted(migrations) if m[0] > current]
        if not pending:
            return current
    backup = settings.database_path.with_name(f"wetcor-v{current}-backup-{datetime.now():%Y%m%d-%H%M%S}.sqlite3")
    engine.dispose()
    shutil.copy2(settings.database_path, backup)
    log.info("backed up database to %s before migrating", backup)
    with engine.begin() as conn:
        for version, description, upgrade in pending:
            log.info("applying migration %s: %s", version, description)
            upgrade(conn)
            conn.exec_driver_sql(f"PRAGMA user_version = {int(version)}")
            current = version
    return current


def get_session() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    with _SessionLocal() as session:
        yield session


def session_scope() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()
