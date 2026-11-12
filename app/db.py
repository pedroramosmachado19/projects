import sqlite3
import threading
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,           -- Pluggy item id (uma conexão com um banco)
    connector TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    name TEXT,
    type TEXT,                     -- BANK | CREDIT
    institution TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    date TEXT NOT NULL,            -- YYYY-MM-DD
    description TEXT NOT NULL,
    amount REAL NOT NULL,          -- negativo = gasto, positivo = entrada
    category TEXT NOT NULL,
    category_source TEXT NOT NULL, -- rule | user | provider | default
    raw_category TEXT
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE TABLE IF NOT EXISTS user_rules (
    keyword TEXT PRIMARY KEY,      -- trecho normalizado da descrição
    category TEXT NOT NULL
);
"""

SCHEMA_ML = """
CREATE TABLE IF NOT EXISTS ml_auth (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    user_id TEXT, access_token TEXT, refresh_token TEXT, expires_at REAL
);
CREATE TABLE IF NOT EXISTS ml_orders (
    id TEXT PRIMARY KEY, date TEXT, total REAL, title TEXT, category TEXT,
    matched INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ml_matches (
    tx_id TEXT PRIMARY KEY, order_id TEXT NOT NULL
);
"""

SCHEMA_AUTH = """
CREATE TABLE IF NOT EXISTS login_fails (ts REAL NOT NULL);
"""

_pg_ready = False
_pg_lock = threading.Lock()


class PGConn:
    """Mesma interface usada no app (execute/commit/close) sobre psycopg, com placeholders '?'."""

    def __init__(self, url: str):
        import psycopg
        from psycopg.rows import dict_row
        # prepare_threshold=None: compatível com o pooler (pgbouncer) do Neon
        self._c = psycopg.connect(url, row_factory=dict_row, prepare_threshold=None)

    def execute(self, sql: str, params=()):
        cur = self._c.cursor()
        cur.execute(sql.replace("?", "%s"), tuple(params))
        return cur

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()


def _pg_schema() -> str:
    return (SCHEMA + SCHEMA_ML + SCHEMA_AUTH).replace(" REAL", " DOUBLE PRECISION")


def connect(path: str | None = None):
    global _pg_ready
    if path is None and config.DATABASE_URL:
        conn = PGConn(config.DATABASE_URL)
        if not _pg_ready:
            with _pg_lock:
                conn.execute("SELECT pg_advisory_xact_lock(727)")  # evita corrida entre instâncias
                conn.execute(_pg_schema())
                conn.commit()
                _pg_ready = True
        return conn
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA + SCHEMA_ML + SCHEMA_AUTH)
    return conn


@contextmanager
def session(path: str | None = None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        if hasattr(conn, "rollback"):
            conn.rollback()
        raise
    finally:
        conn.close()
