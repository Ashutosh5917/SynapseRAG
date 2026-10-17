"""
Database layer for the Authentication & Gateway Service.
Integrates with SQLite users.db.
"""

from __future__ import annotations
import os
import sqlite3
import logging
from typing import Optional
from auth_service.config import DB_PATH

logger = logging.getLogger("auth_service.database")

_db_initialized = False


def get_db_path() -> str:
    """Find existing users.db or use default DB_PATH."""
    candidates = [
        DB_PATH,
        os.path.join(os.getcwd(), "users.db"),
        os.path.join(os.getcwd(), "Adaptive-Rag-main", "users.db"),
        os.path.join(os.getcwd(), "Agentic-BFF-main", "Agentic-BFF-main", "users.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return os.path.abspath(p)
    return os.path.abspath("users.db")


def init_db():
    """Ensure users table exists."""
    global _db_initialized
    db_file = get_db_path()
    logger.info("Initializing SQLite database at: %s", db_file)
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )
            """
        )
        conn.commit()
    _db_initialized = True


def ensure_db():
    """Ensure table exists before any query."""
    global _db_initialized
    if not _db_initialized:
        init_db()


def get_user_password_hash(username: str) -> Optional[str]:
    """Fetch stored password hash for a given username."""
    ensure_db()
    db_file = get_db_path()
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if row:
            return row[0]
    return None


def create_user_record(username: str, password_hash: str) -> bool:
    """Insert a new user record. Returns False if user already exists."""
    ensure_db()
    db_file = get_db_path()
    try:
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False


# Automatically ensure DB on import
ensure_db()
