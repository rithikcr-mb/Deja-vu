"""Profile, session, and mistake-history database operations."""

from __future__ import annotations

import re
import sqlite3
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
    with connect(database_path) as connection:
        return create_learning_session_in_transaction(connection, topic)


def create_learning_session_in_transaction(
    connection: sqlite3.Connection,
    topic: str,
    *,
    session_id: str | None = None,
    origin: str = "player",
    started_at: str | None = None,
) -> str:
    """Insert a session using the caller's transaction."""
    if origin not in {"player", "seeded_demo"}:
        raise ValueError("Session origin must be player or seeded_demo.")
    session_id = session_id or str(uuid.uuid4())
    connection.execute(
        """INSERT INTO learning_sessions
           (id, topic, started_at, ended_at, status, origin)
           VALUES (?, ?, ?, NULL, 'in_progress', ?)""",
        (session_id, topic, started_at or utc_now(), origin),
    )
    return session_id


def get_learning_sessions(database_path: str | Path) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """SELECT id, topic, started_at, ended_at, status, origin
               FROM learning_sessions ORDER BY started_at, id"""
        ).fetchall()
    return [dict(row) for row in rows]


def get_last_session(database_path: str | Path) -> dict | None:
    with connect(database_path) as connection:
        row = connection.execute(
            """SELECT id, topic, started_at, ended_at, status, origin
               FROM learning_sessions
               ORDER BY started_at DESC, id DESC LIMIT 1"""
        ).fetchone()
    return dict(row) if row else None


def get_weak_concepts_with_latest_event(
    database_path: str | Path, limit: int
) -> list[dict]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("Limit must be a positive integer.")
    with connect(database_path) as connection:
        rows = connection.execute(
            """SELECT concepts.id AS concept_id,
                      concepts.label,
                      concepts.explanation,
                      concepts.last_missed_at,
                      (SELECT COUNT(*)
                       FROM mistake_events AS counted
                       WHERE counted.weak_concept_id = concepts.id)
                          AS mistake_event_count,
                      events.id AS mistake_event_id,
                      events.question_text,
                      events.chosen_answer,
                      events.correct_answer,
                      events.explanation AS mistake_explanation,
                      events.occurred_at,
                      events.origin
               FROM weak_concepts AS concepts
               JOIN mistake_events AS events ON events.id = (
                   SELECT latest.id
                   FROM mistake_events AS latest
                   WHERE latest.weak_concept_id = concepts.id
                   ORDER BY latest.occurred_at DESC, latest.id DESC
                   LIMIT 1
               )
               ORDER BY concepts.last_missed_at DESC, concepts.id DESC
               LIMIT ?""",
            (limit,),
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
    with connect(database_path) as connection:
        return finish_session_if_in_progress_in_transaction(
            connection, session_id, status
        )


def finish_session_if_in_progress_in_transaction(
    connection: sqlite3.Connection,
    session_id: str,
    status: str,
    *,
    ended_at: str | None = None,
) -> bool:
    """Finish a session using the caller's transaction."""
    if status not in {"completed", "defeated", "abandoned"}:
        raise ValueError("Session status must be terminal.")
    cursor = connection.execute(
        """UPDATE learning_sessions SET status = ?, ended_at = ?
           WHERE id = ? AND status = 'in_progress'""",
        (status, ended_at or utc_now(), session_id),
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
    with connect(database_path) as connection:
        return record_mistake_in_transaction(
            connection,
            session_id=session_id,
            question_instance_id=question_instance_id,
            concept_label=concept_label,
            concept_explanation=concept_explanation,
            question_text=question_text,
            chosen_answer=chosen_answer,
            correct_answer=correct_answer,
            explanation=explanation,
            question_kind=question_kind,
        )


def record_mistake_in_transaction(
    connection: sqlite3.Connection,
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
    occurred_at: str | None = None,
    event_id: str | None = None,
) -> str:
    """Upsert the concept and insert its event using the caller's transaction."""
    if question_kind not in {"regular", "boss"}:
        raise ValueError("Question kind must be regular or boss.")
    normalized_label = normalize_concept_label(concept_label)
    if not normalized_label:
        raise ValueError("Concept labels must contain letters or numbers.")
    occurred_at = occurred_at or utc_now()
    event_id = event_id or str(uuid.uuid4())
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


def record_boss_weak_spot_mistake(
    database_path: str | Path,
    *,
    session_id: str,
    question_instance_id: str,
    weak_concept_id: int,
    question_text: str,
    chosen_answer: str,
    correct_answer: str,
    explanation: str,
) -> str:
    """Append a boss event to an existing, trusted weak-concept row."""
    with connect(database_path) as connection:
        return record_boss_weak_spot_mistake_in_transaction(
            connection,
            session_id=session_id,
            question_instance_id=question_instance_id,
            weak_concept_id=weak_concept_id,
            question_text=question_text,
            chosen_answer=chosen_answer,
            correct_answer=correct_answer,
            explanation=explanation,
        )


def record_boss_weak_spot_mistake_in_transaction(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    question_instance_id: str,
    weak_concept_id: int,
    question_text: str,
    chosen_answer: str,
    correct_answer: str,
    explanation: str,
    occurred_at: str | None = None,
    event_id: str | None = None,
) -> str:
    """Insert a boss event without letting model prose choose its concept."""
    if (
        isinstance(weak_concept_id, bool)
        or not isinstance(weak_concept_id, int)
        or weak_concept_id < 1
    ):
        raise ValueError("Weak concept ID must be a positive integer.")
    if not question_instance_id.strip():
        raise ValueError("A question instance ID is required.")
    occurred_at = occurred_at or utc_now()
    event_id = event_id or str(uuid.uuid4())
    session_row = connection.execute(
        "SELECT origin FROM learning_sessions WHERE id = ? AND status = 'in_progress'",
        (session_id,),
    ).fetchone()
    if session_row is None:
        raise ValueError("Mistakes can only be saved to an in-progress session.")
    concept_row = connection.execute(
        "SELECT id FROM weak_concepts WHERE id = ?", (weak_concept_id,)
    ).fetchone()
    if concept_row is None:
        raise ValueError("The saved weak concept does not exist.")
    connection.execute(
        "UPDATE weak_concepts SET last_missed_at = ? WHERE id = ?",
        (occurred_at, weak_concept_id),
    )
    connection.execute(
        """INSERT INTO mistake_events
           (id, session_id, question_instance_id, weak_concept_id, origin,
            question_kind, question_text, chosen_answer, correct_answer,
            explanation, occurred_at)
           VALUES (?, ?, ?, ?, ?, 'boss', ?, ?, ?, ?, ?)""",
        (
            event_id,
            session_id,
            question_instance_id,
            weak_concept_id,
            session_row["origin"],
            question_text,
            chosen_answer,
            correct_answer,
            explanation,
            occurred_at,
        ),
    )
    return event_id


def get_weak_concept_with_latest_event(
    database_path: str | Path, concept_id: int
) -> dict | None:
    """Read one trusted saved concept with its latest saved mistake context."""
    if isinstance(concept_id, bool) or not isinstance(concept_id, int):
        raise ValueError("Weak concept ID must be an integer.")
    with connect(database_path) as connection:
        row = connection.execute(
            """SELECT concepts.id AS concept_id,
                      concepts.label,
                      concepts.explanation,
                      concepts.first_missed_at,
                      concepts.last_missed_at,
                      (SELECT COUNT(*)
                       FROM mistake_events AS counted
                       WHERE counted.weak_concept_id = concepts.id)
                          AS mistake_event_count,
                      events.id AS mistake_event_id,
                      events.question_text,
                      events.chosen_answer,
                      events.correct_answer,
                      events.explanation AS mistake_explanation,
                      events.occurred_at,
                      events.origin
               FROM weak_concepts AS concepts
               JOIN mistake_events AS events ON events.id = (
                   SELECT latest.id
                   FROM mistake_events AS latest
                   WHERE latest.weak_concept_id = concepts.id
                   ORDER BY latest.occurred_at DESC, latest.id DESC
                   LIMIT 1
               )
               WHERE concepts.id = ?""",
            (concept_id,),
        ).fetchone()
    return dict(row) if row else None


def record_review_outcome(
    database_path: str | Path,
    *,
    review_id: str,
    question_instance_id: str,
    weak_concept_id: int,
    question_text: str,
    chosen_answer: str,
    correct_answer: str,
    is_correct: bool,
    explanation: str,
) -> str:
    """Append one review answer. This never touches mistake history."""
    if isinstance(weak_concept_id, bool) or not isinstance(weak_concept_id, int):
        raise ValueError("Weak concept ID must be an integer.")
    if not review_id.strip() or not question_instance_id.strip():
        raise ValueError("A review ID and a question instance ID are required.")
    if not isinstance(is_correct, bool):
        raise ValueError("The review result must be a boolean.")
    with connect(database_path) as connection:
        return record_review_outcome_in_transaction(
            connection,
            review_id=review_id,
            question_instance_id=question_instance_id,
            weak_concept_id=weak_concept_id,
            question_text=question_text,
            chosen_answer=chosen_answer,
            correct_answer=correct_answer,
            is_correct=is_correct,
            explanation=explanation,
        )


def record_review_outcome_in_transaction(
    connection: sqlite3.Connection,
    *,
    review_id: str,
    question_instance_id: str,
    weak_concept_id: int,
    question_text: str,
    chosen_answer: str,
    correct_answer: str,
    is_correct: bool,
    explanation: str,
    occurred_at: str | None = None,
    event_id: str | None = None,
) -> str:
    """Insert one review outcome using the caller's transaction."""
    concept_row = connection.execute(
        "SELECT id FROM weak_concepts WHERE id = ?", (weak_concept_id,)
    ).fetchone()
    if concept_row is None:
        raise ValueError("The saved weak concept does not exist.")
    event_id = event_id or str(uuid.uuid4())
    connection.execute(
        """INSERT INTO review_outcomes
           (id, review_id, question_instance_id, weak_concept_id, question_text,
            chosen_answer, correct_answer, is_correct, explanation, occurred_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            review_id,
            question_instance_id,
            weak_concept_id,
            question_text,
            chosen_answer,
            correct_answer,
            1 if is_correct else 0,
            explanation,
            occurred_at or utc_now(),
        ),
    )
    return event_id


def get_review_outcomes(
    database_path: str | Path, review_id: str | None = None
) -> list[dict]:
    """Read review outcomes. These are never mistake events."""
    query = """SELECT id, review_id, question_instance_id, weak_concept_id,
                      question_text, chosen_answer, correct_answer, is_correct,
                      explanation, occurred_at
               FROM review_outcomes"""
    parameters: tuple = ()
    if review_id is not None:
        query += " WHERE review_id = ?"
        parameters = (review_id,)
    query += " ORDER BY occurred_at, id"
    with connect(database_path) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [dict(row) for row in rows]


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
