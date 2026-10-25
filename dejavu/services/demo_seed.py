"""Atomic, clearly marked demo history for the returning-player flow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dejavu.db.connection import connect
from dejavu.db.repository import (
    create_learning_session_in_transaction,
    finish_session_if_in_progress_in_transaction,
    record_mistake_in_transaction,
)

DEMO_TOPIC = "DBMS Normalization"
DEMO_SESSION_ID = "00000000-0000-4000-8000-000000000003"
DEMO_STARTED_AT = "2026-10-18T09:00:00.000Z"
DEMO_ENDED_AT = "2026-10-18T09:20:00.000Z"

SEED_REFUSED_MESSAGE = (
    "Seed refused: this database already contains a learning session. "
    "Use a separate, empty demo database instead."
)


class SeedRefused(RuntimeError):
    """Raised when seeding would touch existing learning history."""


@dataclass(frozen=True)
class DemoMistake:
    event_id: str
    question_instance_id: str
    concept_label: str
    concept_explanation: str
    question_text: str
    chosen_answer: str
    correct_answer: str
    explanation: str
    occurred_at: str


DEMO_MISTAKES = (
    DemoMistake(
        event_id="00000000-0000-4000-8000-000000000011",
        question_instance_id="00000000-0000-4000-8000-000000000101",
        concept_label="Functional dependencies",
        concept_explanation=(
            "A functional dependency describes how one attribute or set of "
            "attributes determines another; normalization uses these "
            "dependencies to reduce redundancy."
        ),
        question_text="Which statement best describes a functional dependency?",
        chosen_answer="Any attribute can determine any other attribute.",
        correct_answer=(
            "One attribute or set of attributes determines another attribute."
        ),
        explanation=(
            "A functional dependency is a constraint: rows that share the "
            "determinant value must also share the dependent value."
        ),
        occurred_at="2026-10-18T09:05:00.000Z",
    ),
    DemoMistake(
        event_id="00000000-0000-4000-8000-000000000012",
        question_instance_id="00000000-0000-4000-8000-000000000102",
        concept_label="Third normal form",
        concept_explanation=(
            "Third normal form removes transitive dependencies so non-key "
            "attributes depend only on candidate keys."
        ),
        question_text="Which dependency does third normal form primarily remove?",
        chosen_answer="Partial dependencies on part of a composite key.",
        correct_answer="Transitive dependencies between non-key attributes.",
        explanation=(
            "3NF removes transitive dependencies between non-key attributes, "
            "while 2NF addresses partial dependencies."
        ),
        occurred_at="2026-10-18T09:08:00.000Z",
    ),
    DemoMistake(
        event_id="00000000-0000-4000-8000-000000000013",
        question_instance_id="00000000-0000-4000-8000-000000000103",
        concept_label="Functional dependencies",
        concept_explanation=(
            "A functional dependency describes how one attribute or set of "
            "attributes determines another; normalization uses these "
            "dependencies to reduce redundancy."
        ),
        question_text="Why can a partial dependency violate second normal form?",
        chosen_answer=(
            "Because every non-key attribute depends on the whole composite key."
        ),
        correct_answer=(
            "Because a non-key attribute depends on only part of a composite key."
        ),
        explanation=(
            "2NF requires every non-key attribute to depend on the whole "
            "candidate key, not just part of it."
        ),
        occurred_at="2026-10-18T09:12:00.000Z",
    ),
    DemoMistake(
        event_id="00000000-0000-4000-8000-000000000014",
        question_instance_id="00000000-0000-4000-8000-000000000104",
        concept_label="Candidate keys",
        concept_explanation=(
            "A candidate key is a minimal set of attributes that uniquely "
            "identifies each row."
        ),
        question_text="What makes a candidate key different from a superkey?",
        chosen_answer="It includes every column in the table.",
        correct_answer=(
            "It is a minimal superkey with no unnecessary attributes."
        ),
        explanation=(
            "A candidate key is a superkey that cannot lose an attribute and "
            "still uniquely identify rows."
        ),
        occurred_at="2026-10-18T09:15:00.000Z",
    ),
)


def seed_demo(database_path: str | Path) -> str:
    """Insert the fixed demo history or refuse without writing anything."""
    with connect(database_path) as connection:
        # An immediate transaction takes the write lock before the emptiness
        # check, so concurrent seed attempts cannot both observe an empty table.
        connection.execute("BEGIN IMMEDIATE")
        existing_session = connection.execute(
            "SELECT 1 FROM learning_sessions LIMIT 1"
        ).fetchone()
        if existing_session is not None:
            raise SeedRefused(SEED_REFUSED_MESSAGE)

        create_learning_session_in_transaction(
            connection,
            DEMO_TOPIC,
            session_id=DEMO_SESSION_ID,
            origin="seeded_demo",
            started_at=DEMO_STARTED_AT,
        )
        for mistake in DEMO_MISTAKES:
            record_mistake_in_transaction(
                connection,
                session_id=DEMO_SESSION_ID,
                question_instance_id=mistake.question_instance_id,
                concept_label=mistake.concept_label,
                concept_explanation=mistake.concept_explanation,
                question_text=mistake.question_text,
                chosen_answer=mistake.chosen_answer,
                correct_answer=mistake.correct_answer,
                explanation=mistake.explanation,
                occurred_at=mistake.occurred_at,
                event_id=mistake.event_id,
            )

        finished = finish_session_if_in_progress_in_transaction(
            connection,
            DEMO_SESSION_ID,
            "completed",
            ended_at=DEMO_ENDED_AT,
        )
        if not finished:
            raise RuntimeError("The seeded demo session could not be completed.")

    return DEMO_SESSION_ID
