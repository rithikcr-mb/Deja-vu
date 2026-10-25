"""Small SQLite connection and initialization helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@contextmanager
def connect(database_path: str | Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(str(database_path), timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(
    database_path: str | Path, *, abandon_in_progress: bool = True
) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect(path) as connection:
        connection.executescript(schema)
        connection.execute(
            """INSERT OR IGNORE INTO player_profile (id, display_name, created_at)
               VALUES (1, NULL, ?)""",
            (utc_now(),),
        )
        if abandon_in_progress:
            # A process has no battle/run state from an earlier launch. Close
            # only unfinished sessions and leave terminal statuses untouched.
            connection.execute(
                """UPDATE learning_sessions
                   SET status = 'abandoned', ended_at = ?
                   WHERE status = 'in_progress'""",
                (utc_now(),),
            )
