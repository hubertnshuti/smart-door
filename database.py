"""
SQLite storage for registered users (with face embeddings) and activity logs.
Embeddings are stored as raw bytes (numpy float32 arrays).
"""
import sqlite3
import numpy as np
from datetime import datetime
import config


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist. Call once at startup."""
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            embedding BLOB NOT NULL,
            image     TEXT,
            created   TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            person    TEXT,
            status    TEXT,
            action    TEXT,
            snapshot  TEXT
        )
    """)
    conn.commit()
    conn.close()


def add_user(name, embedding, image_path=None):
    """Store a new user with their face embedding (numpy float32 array)."""
    conn = _connect()
    conn.execute(
        "INSERT INTO users (name, embedding, image, created) VALUES (?, ?, ?, ?)",
        (name, embedding.astype(np.float32).tobytes(), image_path,
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_all_users():
    """Return list of (id, name, embedding_array, image)."""
    conn = _connect()
    rows = conn.execute("SELECT id, name, embedding, image FROM users").fetchall()
    conn.close()
    users = []
    for r in rows:
        emb = np.frombuffer(r["embedding"], dtype=np.float32)
        users.append((r["id"], r["name"], emb, r["image"]))
    return users


def delete_user(user_id):
    conn = _connect()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def add_log(person, status, action, snapshot=None):
    conn = _connect()
    conn.execute(
        "INSERT INTO logs (timestamp, person, status, action, snapshot) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().isoformat(sep=" ", timespec="seconds"),
         person, status, action, snapshot),
    )
    conn.commit()
    conn.close()


def get_logs(limit=100):
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
