"""SQLite persistence. One connection per thread, WAL mode so the indexer thread
can write while the API reads."""
import sqlite3
import threading

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id           INTEGER PRIMARY KEY,
    path         TEXT UNIQUE NOT NULL,
    rel_path     TEXT NOT NULL,
    filename     TEXT NOT NULL,
    ext          TEXT NOT NULL,
    type         TEXT,                          -- image | video | pdf | NULL (unsupported)
    size         INTEGER NOT NULL,
    mtime        REAL NOT NULL,
    content_hash TEXT,
    status       TEXT NOT NULL DEFAULT 'pending', -- pending|processing|done|failed|unsupported|duplicate
    error        TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0,
    duplicate_of INTEGER,
    width INTEGER, height INTEGER, duration REAL, pages INTEGER,
    summary      TEXT,
    tags         TEXT,                          -- comma separated AI tags
    thumb        TEXT,
    indexed_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);
CREATE INDEX IF NOT EXISTS idx_assets_hash   ON assets(content_hash);
CREATE INDEX IF NOT EXISTS idx_assets_dup    ON assets(duplicate_of);

CREATE TABLE IF NOT EXISTS embeddings (
    id       INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    kind     TEXT NOT NULL,   -- 'clip' (image / video frame / pdf page 1) | 'text' (pdf chunk)
    ref      TEXT,            -- video: timestamp (s) | pdf text: "page|snippet" | pdf page: "page 1"
    vec      BLOB NOT NULL    -- float32, L2-normalised
);
CREATE INDEX IF NOT EXISTS idx_emb_asset ON embeddings(asset_id);
"""

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.THUMB_DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(config.DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.c = c
    return c


def init():
    c = conn()
    c.executescript(SCHEMA)
    # crash recovery: anything left 'processing' by a killed run goes back to the queue
    c.execute("UPDATE assets SET status='pending' WHERE status='processing'")
    c.commit()
