"""Profile and lesson-session database operations."""

from __future__ import annotations

import uuid
from pathlib import Path

from dejavu.db.connection import connect, utc_now


def get_profile(database_path: str | Path) -> dict:
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT id, display_name, created_at FROM player_profile WHERE id = 1"
        ).fetchone()
    return dict(row)


def save_first_display_name(database_path: str | Path, display_name: str) -> str:
    with connect(database_path) as connection:
        connection.execute(
            """UPDATE player_profile SET display_name = ?
               WHERE id = 1 AND (display_name IS NULL OR display_name = '')""",
            (display_name,),
        )
        row = connection.execute(
            "SELECT display_name FROM player_profile WHERE id = 1"
        ).fetchone()
    return row["display_name"]


def create_learning_session(database_path: str | Path, topic: str) -> str:
    session_id = str(uuid.uuid4())
    with connect(database_path) as connection:
        connection.execute(
            """INSERT INTO learning_sessions
               (id, topic, started_at, ended_at, status, origin)
               VALUES (?, ?, ?, NULL, 'in_progress', 'player')""",
            (session_id, topic, utc_now()),
        )
    return session_id


def get_learning_sessions(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """SELECT id, topic, started_at, ended_at, status, origin
               FROM learning_sessions ORDER BY started_at, id"""
        ).fetchall()
    return [dict(row) for row in rows]


def abandon_if_in_progress(database_path: str | Path, session_id: str) -> bool:
    with connect(database_path) as connection:
        cursor = connection.execute(
            """UPDATE learning_sessions SET status = 'abandoned', ended_at = ?
               WHERE id = ? AND status = 'in_progress'""",
            (utc_now(), session_id),
        )
    return cursor.rowcount == 1
