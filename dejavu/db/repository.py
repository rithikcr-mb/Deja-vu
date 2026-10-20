"""Profile and lesson-session database operations."""

from __future__ import annotations

import re
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


def finish_session_if_in_progress(
    database_path: str | Path, session_id: str, status: str
) -> bool:
    if status not in {"completed", "defeated", "abandoned"}:
        raise ValueError("Session status must be terminal.")
    with connect(database_path) as connection:
        cursor = connection.execute(
            """UPDATE learning_sessions SET status = ?, ended_at = ?
               WHERE id = ? AND status = 'in_progress'""",
            (status, utc_now(), session_id),
        )
    return cursor.rowcount == 1


def normalize_concept_label(label: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", label.casefold()))


def record_mistake(
    database_path: str | Path,
    *,
    session_id: str,
    question_instance_id: str,
    concept_label: str,
    concept_explanation: str,
    question_text: str,
    chosen_answer: str,
    correct_answer: str,
    explanation: str,
    question_kind: str = "regular",
) -> str:
    if question_kind not in {"regular", "boss"}:
        raise ValueError("Question kind must be regular or boss.")
    normalized_label = normalize_concept_label(concept_label)
    if not normalized_label:
        raise ValueError("Concept labels must contain letters or numbers.")
    occurred_at = utc_now()
    event_id = str(uuid.uuid4())
    with connect(database_path) as connection:
        session_row = connection.execute(
            "SELECT origin FROM learning_sessions WHERE id = ? AND status = 'in_progress'",
            (session_id,),
        ).fetchone()
        if session_row is None:
            raise ValueError("Mistakes can only be saved to an in-progress session.")
        concept_row = connection.execute(
            """INSERT INTO weak_concepts
               (normalized_label, label, explanation, first_missed_at, last_missed_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(normalized_label) DO UPDATE SET
                   last_missed_at = excluded.last_missed_at
               RETURNING id""",
            (
                normalized_label,
                concept_label.strip(),
                concept_explanation.strip(),
                occurred_at,
                occurred_at,
            ),
        ).fetchone()
        connection.execute(
            """INSERT INTO mistake_events
               (id, session_id, question_instance_id, weak_concept_id, origin,
                question_kind, question_text, chosen_answer, correct_answer,
                explanation, occurred_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                session_id,
                question_instance_id,
                concept_row["id"],
                session_row["origin"],
                question_kind,
                question_text,
                chosen_answer,
                correct_answer,
                explanation,
                occurred_at,
            ),
        )
    return event_id


def get_mistake_events(database_path: str | Path, session_id: str | None = None) -> list[dict]:
    query = """SELECT id, session_id, question_instance_id, weak_concept_id,
                      origin, question_kind, question_text, chosen_answer,
                      correct_answer, explanation, occurred_at
               FROM mistake_events"""
    parameters: tuple = ()
    if session_id is not None:
        query += " WHERE session_id = ?"
        parameters = (session_id,)
    query += " ORDER BY occurred_at, id"
    with connect(database_path) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [dict(row) for row in rows]


def get_weak_concepts(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """SELECT concepts.id, concepts.normalized_label, concepts.label,
                      concepts.explanation, concepts.first_missed_at,
                      concepts.last_missed_at, COUNT(events.id) AS mistake_count
               FROM weak_concepts AS concepts
               JOIN mistake_events AS events ON events.weak_concept_id = concepts.id
               GROUP BY concepts.id ORDER BY concepts.last_missed_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]
