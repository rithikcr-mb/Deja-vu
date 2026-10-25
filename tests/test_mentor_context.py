from __future__ import annotations

import time
import unittest
from pathlib import Path
from uuid import uuid4

from dejavu import create_app
from dejavu.db.connection import connect, utc_now
from dejavu.db.repository import (
    create_learning_session,
    finish_session_if_in_progress,
    record_mistake,
    save_first_display_name,
)
from dejavu.services.mentor_context import get_mentor_context


class TestMentorContext(unittest.TestCase):
    def setUp(self):
        instance_dir = Path(__file__).resolve().parents[1] / "instance"
        instance_dir.mkdir(parents=True, exist_ok=True)
        self.database = str(instance_dir / f"mentor-{uuid4().hex}.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "test-only-secret",
            }
        )
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.addCleanup(self.app_context.pop)

    def save_name(self, name: str = "Arjun") -> None:
        save_first_display_name(self.database, name)

    def new_session(self, topic: str, origin: str = "player") -> str:
        if origin == "player":
            return create_learning_session(self.database, topic)
        session_id = str(uuid4())
        with connect(self.database) as connection:
            connection.execute(
                """INSERT INTO learning_sessions
                   (id, topic, started_at, ended_at, status, origin)
                   VALUES (?, ?, ?, NULL, 'in_progress', ?)""",
                (session_id, topic, utc_now(), origin),
            )
        return session_id

    def insert_session(
        self,
        session_id: str,
        topic: str,
        started_at: str,
        *,
        status: str = "completed",
    ) -> None:
        ended_at = started_at if status != "in_progress" else None
        with connect(self.database) as connection:
            connection.execute(
                """INSERT INTO learning_sessions
                   (id, topic, started_at, ended_at, status, origin)
                   VALUES (?, ?, ?, ?, ?, 'player')""",
                (session_id, topic, started_at, ended_at, status),
            )

    def record(
        self,
        session_id: str,
        question: str,
        concept_label: str,
        *,
        chosen_answer: str = "Wrong answer",
        correct_answer: str = "Correct answer",
        explanation: str = "Saved explanation.",
    ) -> str:
        return record_mistake(
            self.database,
            session_id=session_id,
            question_instance_id=str(uuid4()),
            concept_label=concept_label,
            concept_explanation=f"Saved explanation for {concept_label}.",
            question_text=question,
            chosen_answer=chosen_answer,
            correct_answer=correct_answer,
            explanation=explanation,
        )

    def finish(self, session_id: str) -> None:
        finish_session_if_in_progress(self.database, session_id, "completed")

    def test_empty_context_has_no_history_or_weaknesses(self):
        context = get_mentor_context()

        self.assertIsNone(context.display_name)
        self.assertFalse(context.has_session_history)
        self.assertIsNone(context.last_session)
        self.assertEqual(context.weak_concepts, [])

    def test_named_player_without_sessions_has_no_memory(self):
        self.save_name()

        context = get_mentor_context()

        self.assertEqual(context.display_name, "Arjun")
        self.assertFalse(context.has_session_history)
        self.assertIsNone(context.last_session)
        self.assertEqual(context.weak_concepts, [])

    def test_player_history_returns_last_session_and_latest_weakness(self):
        self.save_name()
        session_id = self.new_session("DBMS Normalization")
        self.record(
            session_id,
            "Which normal form removes transitive dependencies?",
            "Third normal form",
        )
        time.sleep(0.01)
        self.record(
            session_id,
            "Which isolation level prevents non-repeatable reads?",
            "Transaction isolation",
        )
        self.finish(session_id)

        context = get_mentor_context()

        with connect(self.database) as connection:
            stored_started_at = connection.execute(
                "SELECT started_at FROM learning_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()["started_at"]

        self.assertEqual(context.display_name, "Arjun")
        self.assertTrue(context.has_session_history)
        self.assertEqual(context.last_session.topic, "DBMS Normalization")
        self.assertEqual(context.last_session.origin, "player")
        self.assertEqual(context.last_session.occurred_at_utc, stored_started_at)
        self.assertTrue(context.last_session.occurred_at_utc.endswith("Z"))
        self.assertEqual(len(context.weak_concepts), 2)
        latest = context.weak_concepts[0]
        self.assertEqual(latest.label, "Transaction isolation")
        self.assertEqual(latest.mistake_event_count, 1)
        self.assertEqual(
            latest.latest_mistake.question,
            "Which isolation level prevents non-repeatable reads?",
        )
        self.assertEqual(latest.latest_mistake.chosen_answer, "Wrong answer")
        self.assertEqual(latest.latest_mistake.correct_answer, "Correct answer")
        self.assertEqual(latest.latest_mistake.explanation, "Saved explanation.")
        self.assertEqual(latest.latest_mistake.origin, "player")
        self.assertTrue(latest.latest_mistake.occurred_at_utc)
        self.assertIsInstance(latest.concept_id, int)

    def test_repeated_misses_count_but_latest_event_is_returned(self):
        self.save_name()
        session_id = self.new_session("Databases")
        self.record(session_id, "First missed question", "Index selectivity")
        time.sleep(0.01)
        self.record(session_id, "Latest missed question", "Index selectivity")
        self.finish(session_id)

        context = get_mentor_context()

        self.assertEqual(len(context.weak_concepts), 1)
        concept = context.weak_concepts[0]
        self.assertEqual(concept.mistake_event_count, 2)
        self.assertEqual(concept.latest_mistake.question, "Latest missed question")

    def test_context_is_bounded_and_max_accepts_only_one_or_two(self):
        self.new_session_with_three_weaknesses()

        one = get_mentor_context(max_weak_concepts=1)
        two = get_mentor_context(max_weak_concepts=2)

        self.assertEqual(len(one.weak_concepts), 1)
        self.assertEqual(len(two.weak_concepts), 2)

        for invalid in (0, 3, -1, True, False, 1.0, 2.0, "1", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    get_mentor_context(max_weak_concepts=invalid)

    def new_session_with_three_weaknesses(self) -> None:
        self.save_name()
        session_id = self.new_session("Operating Systems")
        for question, concept in (
            ("First concept question", "First concept"),
            ("Second concept question", "Second concept"),
            ("Third concept question", "Third concept"),
        ):
            self.record(session_id, question, concept)
            time.sleep(0.01)
        self.finish(session_id)

    def test_seeded_history_is_returned_with_its_origin(self):
        self.save_name()
        session_id = self.new_session("DBMS Normalization", origin="seeded_demo")
        self.record(
            session_id,
            "Seeded demo question",
            "Seeded demo weakness",
        )
        self.finish(session_id)

        context = get_mentor_context()

        self.assertTrue(context.has_session_history)
        self.assertEqual(context.last_session.origin, "seeded_demo")
        self.assertEqual(len(context.weak_concepts), 1)
        self.assertEqual(
            context.weak_concepts[0].latest_mistake.origin, "seeded_demo"
        )
        self.assertEqual(
            context.weak_concepts[0].latest_mistake.question,
            "Seeded demo question",
        )

    def test_session_without_mistakes_reports_history_but_no_weaknesses(self):
        self.save_name()
        session_id = self.new_session("Networking")
        self.finish(session_id)

        context = get_mentor_context()

        self.assertTrue(context.has_session_history)
        self.assertEqual(context.last_session.topic, "Networking")
        self.assertEqual(context.weak_concepts, [])

    def test_latest_session_wins_when_multiple_sessions_exist(self):
        self.save_name()
        first = self.new_session("First topic")
        self.finish(first)
        time.sleep(0.01)
        second = self.new_session("Second topic")
        self.finish(second)

        context = get_mentor_context()

        self.assertEqual(context.last_session.topic, "Second topic")

    def test_last_session_uses_started_at_before_insertion_order(self):
        self.save_name()
        self.insert_session(
            "session-late",
            "Later timestamp",
            "2026-10-21T10:00:00.000Z",
        )
        self.insert_session(
            "session-early",
            "Earlier timestamp",
            "2026-10-20T10:00:00.000Z",
        )

        context = get_mentor_context()

        self.assertEqual(context.last_session.topic, "Later timestamp")
        self.assertEqual(
            context.last_session.occurred_at_utc,
            "2026-10-21T10:00:00.000Z",
        )

    def test_last_session_tie_break_uses_id_descending(self):
        self.save_name()
        timestamp = "2026-10-22T10:00:00.000Z"
        self.insert_session("tie-b", "Tie B", timestamp)
        self.insert_session("tie-a", "Tie A", timestamp)

        context = get_mentor_context()

        self.assertEqual(context.last_session.topic, "Tie B")

    def test_weak_concepts_order_by_last_missed_at_not_concept_id(self):
        self.save_name()
        session_id = self.new_session("Ordering")
        older_event_id = self.record(session_id, "Older concept event", "Older concept")
        time.sleep(0.01)
        newer_event_id = self.record(session_id, "Newer concept event", "Newer concept")
        self.finish(session_id)

        with connect(self.database) as connection:
            older_concept_id = connection.execute(
                "SELECT weak_concept_id FROM mistake_events WHERE id = ?",
                (older_event_id,),
            ).fetchone()["weak_concept_id"]
            newer_concept_id = connection.execute(
                "SELECT weak_concept_id FROM mistake_events WHERE id = ?",
                (newer_event_id,),
            ).fetchone()["weak_concept_id"]
            connection.execute(
                "UPDATE mistake_events SET occurred_at = ? WHERE id = ?",
                ("2026-10-24T10:00:00.000Z", older_event_id),
            )
            connection.execute(
                "UPDATE weak_concepts SET last_missed_at = ? WHERE id = ?",
                ("2026-10-24T10:00:00.000Z", older_concept_id),
            )
            connection.execute(
                "UPDATE mistake_events SET occurred_at = ? WHERE id = ?",
                ("2026-10-23T10:00:00.000Z", newer_event_id),
            )
            connection.execute(
                "UPDATE weak_concepts SET last_missed_at = ? WHERE id = ?",
                ("2026-10-23T10:00:00.000Z", newer_concept_id),
            )

        context = get_mentor_context()

        self.assertEqual(
            [concept.label for concept in context.weak_concepts],
            ["Older concept", "Newer concept"],
        )

    def test_latest_mistake_uses_occurred_at_before_event_id(self):
        self.save_name()
        session_id = self.new_session("Latest event")
        older_event_id = self.record(
            session_id, "Older by time, later id", "Event concept"
        )
        time.sleep(0.01)
        newer_event_id = self.record(
            session_id, "Newer by time, earlier id", "Event concept"
        )
        self.finish(session_id)

        with connect(self.database) as connection:
            concept_id = connection.execute(
                "SELECT weak_concept_id FROM mistake_events WHERE id = ?",
                (older_event_id,),
            ).fetchone()["weak_concept_id"]
            connection.execute(
                "UPDATE mistake_events SET id = 'z-older-event' WHERE id = ?",
                (older_event_id,),
            )
            connection.execute(
                "UPDATE mistake_events SET id = 'a-newer-event' WHERE id = ?",
                (newer_event_id,),
            )
            connection.execute(
                "UPDATE mistake_events SET occurred_at = ? WHERE id = 'z-older-event'",
                ("2026-10-24T10:00:00.000Z",),
            )
            connection.execute(
                "UPDATE mistake_events SET occurred_at = ? WHERE id = 'a-newer-event'",
                ("2026-10-24T11:00:00.000Z",),
            )
            connection.execute(
                "UPDATE weak_concepts SET last_missed_at = ? WHERE id = ?",
                ("2026-10-24T11:00:00.000Z", concept_id),
            )

        context = get_mentor_context()

        self.assertEqual(len(context.weak_concepts), 1)
        concept = context.weak_concepts[0]
        self.assertEqual(concept.mistake_event_count, 2)
        self.assertEqual(
            concept.latest_mistake.question,
            "Newer by time, earlier id",
        )

    def test_latest_mistake_tie_break_uses_id_descending(self):
        self.save_name()
        session_id = self.new_session("Latest event tie")
        first_event_id = self.record(session_id, "First tie event", "Tie concept")
        time.sleep(0.01)
        second_event_id = self.record(session_id, "Second tie event", "Tie concept")
        self.finish(session_id)

        with connect(self.database) as connection:
            concept_id = connection.execute(
                "SELECT weak_concept_id FROM mistake_events WHERE id = ?",
                (first_event_id,),
            ).fetchone()["weak_concept_id"]
            connection.execute(
                "UPDATE mistake_events SET id = 'tie-z' WHERE id = ?",
                (first_event_id,),
            )
            connection.execute(
                "UPDATE mistake_events SET id = 'tie-a' WHERE id = ?",
                (second_event_id,),
            )
            for event_id in ("tie-z", "tie-a"):
                connection.execute(
                    "UPDATE mistake_events SET occurred_at = ? WHERE id = ?",
                    ("2026-10-25T10:00:00.000Z", event_id),
                )
            connection.execute(
                "UPDATE weak_concepts SET last_missed_at = ? WHERE id = ?",
                ("2026-10-25T10:00:00.000Z", concept_id),
            )

        context = get_mentor_context()

        self.assertEqual(context.weak_concepts[0].mistake_event_count, 2)
        self.assertEqual(
            context.weak_concepts[0].latest_mistake.question,
            "First tie event",
        )


if __name__ == "__main__":
    unittest.main()
