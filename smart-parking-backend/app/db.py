"""
Database helpers.

We use Python's built-in `sqlite3` with plain SQL. Every query uses `?`
placeholders instead of pasting values into the SQL text - this is what
protects the app from SQL-injection attacks (SRS section 12).
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def get_db():
    """Return this request's database connection (opened on first use)."""
    if "db" not in g:
        conn = sqlite3.connect(
            current_app.config["DATABASE_PATH"],
            isolation_level=None,  # we control transactions ourselves (see write_transaction)
            timeout=10,
        )
        conn.row_factory = sqlite3.Row  # lets us read columns by name: row["email"]
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def write_transaction(db):
    """
    Run several changes as ONE all-or-nothing step.

    `BEGIN IMMEDIATE` locks the database for writing straight away, so two people
    clicking "book" for the same slot at the same moment are handled one after
    the other. That is what prevents double booking.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def init_db(app):
    """Create the tables if they do not exist yet."""
    with app.app_context():
        get_db().executescript(SCHEMA_FILE.read_text(encoding="utf-8"))


def init_app(app):
    app.teardown_appcontext(close_db)
    init_db(app)
