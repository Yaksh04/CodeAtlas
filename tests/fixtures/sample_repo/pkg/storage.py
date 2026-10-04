"""Persistence layer (fixture for retrieval tests)."""

import sqlite3


def open_database(path):
    """Open the SQLite database used to persist records."""
    return sqlite3.connect(path)


def save_record(conn, record):
    """Insert one record into the database."""
    conn.execute("INSERT INTO records VALUES (?)", (record,))
    conn.commit()
