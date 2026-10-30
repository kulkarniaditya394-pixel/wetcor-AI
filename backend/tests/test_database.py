"""Persistence, uniqueness and schema-upgrade mechanism."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.database import session as S
from app.database.models import Experiment, Specimen


def test_fresh_database_is_versioned_and_persists_across_restart(workspace):
    assert S.init_db() == S.latest_version()
    with S.session_scope() as db:
        db.add(Specimen(code="P-1", material="Copper"))
        db.commit()
    S.reset_engine()  # simulate application restart
    assert S.init_db() == S.latest_version()
    with S.session_scope() as db:
        assert db.query(Specimen).filter_by(code="P-1").one().material == "Copper"


def test_unique_codes_and_foreign_keys(workspace):
    S.init_db()
    with S.session_scope() as db:
        db.add(Specimen(code="U-1", material="x"))
        db.commit()
        db.add(Specimen(code="U-1", material="y"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(Experiment(code="E-1", specimen_id=999, experiment_type="combined"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_migration_applies_once_with_backup(workspace):
    S.init_db()
    calls = []

    def add_column(conn):
        calls.append(1)
        conn.exec_driver_sql("ALTER TABLE specimens ADD COLUMN supplier_lot TEXT")

    migrations = S.MIGRATIONS + [(S.latest_version() + 1, "add supplier_lot", add_column)]
    with S.session_scope() as db:
        db.add(Specimen(code="M-1", material="Zinc"))
        db.commit()
    assert S.init_db(migrations) == S.latest_version(migrations)
    assert S.init_db(migrations) == S.latest_version(migrations)  # idempotent
    assert calls == [1]
    assert list(settings.database_path.parent.glob("wetcor-v1-backup-*.sqlite3"))
    with S.get_engine().connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(specimens)"))]
        assert "supplier_lot" in cols
        assert conn.execute(text("SELECT material FROM specimens WHERE code='M-1'")).scalar() == "Zinc"


def test_unversioned_existing_database_is_not_touched(workspace):
    settings.ensure_dirs()
    import sqlite3
    con = sqlite3.connect(settings.database_path)
    con.execute("CREATE TABLE foreign_data (x INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="refusing"):
        S.init_db()
