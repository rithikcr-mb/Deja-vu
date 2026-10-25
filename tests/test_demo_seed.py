from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dejavu import create_app
from dejavu.db.connection import connect
from dejavu.db.repository import (
    create_learning_session,
    finish_session_if_in_progress,
)
from dejavu.services.ai_client import GeminiLessonClient
from dejavu.services.demo_seed import (
    DEMO_ENDED_AT,
    DEMO_MISTAKES,
    DEMO_SESSION_ID,
    DEMO_STARTED_AT,
    DEMO_TOPIC,
    seed_demo,
)
from dejavu.services.mentor_context import get_mentor_context


class TestDemoSeed(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.database = str(Path(self.tempdir.name) / "demo.sqlite3")
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
        self.runner = self.app.test_cli_runner()

    def snapshot(self) -> dict[str, list[dict]]:
        with connect(self.database) as connection:
            return {
                "profile": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM player_profile ORDER BY id"
                    )
                ],
                "sessions": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM learning_sessions ORDER BY id"
                    )
                ],
                "concepts": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM weak_concepts ORDER BY id"
                    )
                ],
                "events": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM mistake_events ORDER BY id"
                    )
                ],
            }

    def test_first_seed_creates_one_completed_marked_session(self):
        result = self.runner.invoke(args=["seed-demo"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Seeded demo history", result.output)

        with connect(self.database) as connection:
            sessions = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM learning_sessions ORDER BY id"
                )
            ]

        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session["id"], DEMO_SESSION_ID)
        self.assertEqual(session["topic"], DEMO_TOPIC)
        self.assertEqual(session["started_at"], DEMO_STARTED_AT)
        self.assertEqual(session["ended_at"], DEMO_ENDED_AT)
        self.assertEqual(session["status"], "completed")
        self.assertEqual(session["origin"], "seeded_demo")

    def test_seed_inserts_three_linked_concepts_and_four_events(self):
        result = self.runner.invoke(args=["seed-demo"])
        self.assertEqual(result.exit_code, 0, result.output)

        with connect(self.database) as connection:
            concepts = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM weak_concepts ORDER BY id"
                )
            ]
            events = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM mistake_events ORDER BY id"
                )
            ]

        self.assertEqual(len(concepts), 3)
        self.assertEqual(
            {concept["label"] for concept in concepts},
            {mistake.concept_label for mistake in DEMO_MISTAKES},
        )
        self.assertTrue(
            all(concept["label"].strip() for concept in concepts)
        )
        self.assertTrue(
            all(concept["explanation"].strip() for concept in concepts)
        )

        self.assertEqual(len(events), 4)
        concept_ids = {concept["id"] for concept in concepts}
        for event in events:
            self.assertEqual(event["session_id"], DEMO_SESSION_ID)
            self.assertIn(event["weak_concept_id"], concept_ids)
            self.assertEqual(event["origin"], "seeded_demo")
            self.assertEqual(event["question_kind"], "regular")
            self.assertTrue(event["question_text"].strip())
            self.assertTrue(event["chosen_answer"].strip())
            self.assertTrue(event["correct_answer"].strip())
            self.assertTrue(event["explanation"].strip())

        counts: dict[int, int] = {}
        for event in events:
            self.assertTrue(event["occurred_at"].endswith("Z"))
            counts[event["weak_concept_id"]] = (
                counts.get(event["weak_concept_id"], 0) + 1
            )
        self.assertEqual(set(counts), concept_ids)
        self.assertEqual(sorted(counts.values()), [1, 1, 2])

    def test_second_seed_refuses_without_changing_rows(self):
        first = self.runner.invoke(args=["seed-demo"])
        self.assertEqual(first.exit_code, 0, first.output)
        before = self.snapshot()

        second = self.runner.invoke(args=["seed-demo"])

        self.assertNotEqual(second.exit_code, 0)
        self.assertIn("Seed refused", second.output)
        self.assertEqual(self.snapshot(), before)

    def test_existing_player_session_causes_refusal_without_changes(self):
        session_id = create_learning_session(self.database, "Player topic")
        self.assertTrue(
            finish_session_if_in_progress(self.database, session_id, "completed")
        )
        before = self.snapshot()

        result = self.runner.invoke(args=["seed-demo"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Seed refused", result.output)
        self.assertEqual(self.snapshot(), before)

    def test_insertion_failure_rolls_back_every_seeded_row(self):
        before = self.snapshot()

        with patch(
            "dejavu.services.demo_seed.DEMO_MISTAKES",
            (*DEMO_MISTAKES, DEMO_MISTAKES[0]),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                seed_demo(self.database)

        after = self.snapshot()
        self.assertEqual(after, before)
        self.assertEqual(after["sessions"], [])
        self.assertEqual(after["concepts"], [])
        self.assertEqual(after["events"], [])

    def test_seeded_history_is_returned_through_mentor_context(self):
        result = self.runner.invoke(args=["seed-demo"])
        self.assertEqual(result.exit_code, 0, result.output)

        context = get_mentor_context()

        self.assertTrue(context.has_session_history)
        self.assertEqual(context.last_session.topic, DEMO_TOPIC)
        self.assertEqual(context.last_session.origin, "seeded_demo")
        self.assertEqual(context.last_session.occurred_at_utc, DEMO_STARTED_AT)
        self.assertEqual(len(context.weak_concepts), 2)
        self.assertEqual(
            [concept.label for concept in context.weak_concepts],
            ["Candidate keys", "Functional dependencies"],
        )

        functional_dependencies = next(
            concept
            for concept in context.weak_concepts
            if concept.label == "Functional dependencies"
        )
        self.assertEqual(functional_dependencies.mistake_event_count, 2)
        self.assertEqual(
            functional_dependencies.latest_mistake.question,
            "Why can a partial dependency violate second normal form?",
        )
        self.assertEqual(
            functional_dependencies.latest_mistake.occurred_at_utc,
            "2026-10-18T09:12:00.000Z",
        )
        self.assertEqual(
            functional_dependencies.latest_mistake.origin, "seeded_demo"
        )

    def test_seed_makes_no_live_gemini_calls(self):
        with patch.object(
            GeminiLessonClient,
            "generate_lesson",
            side_effect=AssertionError("seed must not call Gemini"),
        ), patch.object(
            GeminiLessonClient,
            "generate_battle",
            side_effect=AssertionError("seed must not call Gemini"),
        ):
            session_id = seed_demo(self.database)

        self.assertEqual(session_id, DEMO_SESSION_ID)

    def test_seed_cli_startup_does_not_abandon_existing_in_progress_history(self):
        create_learning_session(self.database, "Unfinished player topic")
        before = self.snapshot()

        with patch(
            "sys.argv",
            ["python", "-m", "flask", "--app", "app", "seed-demo"],
        ):
            safe_app = create_app(
                {
                    "TESTING": True,
                    "DATABASE": self.database,
                    "SECRET_KEY": "test-only-secret",
                }
            )

        with connect(self.database) as connection:
            status = connection.execute(
                "SELECT status FROM learning_sessions"
            ).fetchone()["status"]
        self.assertEqual(status, "in_progress")

        result = safe_app.test_cli_runner().invoke(args=["seed-demo"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Seed refused", result.output)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
