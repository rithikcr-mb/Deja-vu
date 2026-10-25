"""Approved retrieval contract for returning-player mentor context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from flask import current_app

from dejavu.db.repository import (
    get_last_session,
    get_profile,
    get_weak_concepts_with_latest_event,
)

Origin = Literal["player", "seeded_demo"]


@dataclass(frozen=True)
class MentorMistake:
    question: str
    chosen_answer: str
    correct_answer: str
    explanation: str
    occurred_at_utc: str
    origin: Origin


@dataclass(frozen=True)
class MentorWeakConcept:
    concept_id: int
    label: str
    explanation: str
    mistake_event_count: int
    latest_mistake: MentorMistake


@dataclass(frozen=True)
class MentorLastSession:
    topic: str
    occurred_at_utc: str
    origin: Origin


@dataclass(frozen=True)
class MentorContext:
    display_name: str | None
    has_session_history: bool
    last_session: MentorLastSession | None
    weak_concepts: list[MentorWeakConcept]


def get_mentor_context(*, max_weak_concepts: int = 2) -> MentorContext:
    """Read a bounded, factual mentor summary from the local database."""
    if (
        isinstance(max_weak_concepts, bool)
        or not isinstance(max_weak_concepts, int)
        or max_weak_concepts not in (1, 2)
    ):
        raise ValueError("max_weak_concepts must be 1 or 2.")

    database_path = current_app.config["DATABASE"]
    profile = get_profile(database_path)
    session = get_last_session(database_path)
    concept_rows = (
        get_weak_concepts_with_latest_event(database_path, max_weak_concepts)
        if session
        else []
    )

    last_session = None
    if session:
        last_session = MentorLastSession(
            topic=session["topic"],
            occurred_at_utc=session["started_at"],
            origin=session["origin"],
        )

    weak_concepts = [
        MentorWeakConcept(
            concept_id=int(row["concept_id"]),
            label=row["label"],
            explanation=row["explanation"],
            mistake_event_count=int(row["mistake_event_count"]),
            latest_mistake=MentorMistake(
                question=row["question_text"],
                chosen_answer=row["chosen_answer"],
                correct_answer=row["correct_answer"],
                explanation=row["mistake_explanation"],
                occurred_at_utc=row["occurred_at"],
                origin=row["origin"],
            ),
        )
        for row in concept_rows
    ]

    return MentorContext(
        display_name=profile["display_name"] or None,
        has_session_history=session is not None,
        last_session=last_session,
        weak_concepts=weak_concepts,
    )
