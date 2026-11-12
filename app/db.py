import sqlite3
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


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session(path: str | None = None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
