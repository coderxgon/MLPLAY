"""Database engine + session factory. SQLite by default, Postgres when DATABASE_URL is set."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL, IS_POSTGRES

connect_args = {} if IS_POSTGRES else {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

if not IS_POSTGRES:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=8000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def init_db() -> None:
    from app import models  # noqa: F401  (register models)

    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Lightweight column migration for schema additions (users table)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    additions = {
        "bind_name": "VARCHAR(120)",
        "bind_holder": "VARCHAR(120)",
        "bind_account": "VARCHAR(120)",
        "bound_at": "DATETIME" if not IS_POSTGRES else "TIMESTAMP",
        "rank_key": "VARCHAR(32) DEFAULT 'warrior'",
    }
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))


def get_session():
    s = SessionLocal()
    try:
        return s
    except Exception:
        s.close()
        raise