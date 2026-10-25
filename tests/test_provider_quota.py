"""Regression tests for provider quota handling.

A quota refusal (429 RESOURCE_EXHAUSTED) is permanent until the provider's
quota resets, so it must not be presented to the player as an ordinary
retryable failure. A transient 503 must stay retryable.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dejavu import create_app
from dejavu.db.connection import connect
from dejavu.services.ai_client import (
    QUOTA_MESSAGE,
    GeminiLessonClient,
    LessonProviderError,
    ProviderQuotaExceeded,
)


ACTION_PATTERN = re.compile(rb'name="action_id" value="([^"]+)"')
BOSS_START_PATTERN = re.compile(
    rb'<form action="/boss/start"[^>]*>.*?name="action_id" value="([^"]+)"', re.S
)


class FakeProviderError(Exception):
    """Stands in for a google-genai API error."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def fake_client_raising(error: Exception):
    """A stub google-genai client whose generate_content call always fails."""
    class Models:
        def generate_content(self, **kwargs):
            raise error

    class Stub:
        models = Models()

    return Stub()


class TestQuotaDetection(unittest.TestCase):
    def test_quota_refusal_becomes_a_quota_error(self):
        error = FakeProviderError("429 RESOURCE_EXHAUSTED: quota exceeded", 429)
        client = GeminiLessonClient("key", "model")

        with patch(
            "google.genai.Client", return_value=fake_client_raising(error)
        ):
            with self.assertRaises(ProviderQuotaExceeded) as caught:
                client.generate_lesson("DBMS Normalization")

        self.assertEqual(str(caught.exception), QUOTA_MESSAGE)
        self.assertIn("quota", str(caught.exception).lower())

    def test_quota_refusal_is_detected_from_the_message_without_a_status_code(self):
        error = FakeProviderError(
            "RESOURCE_EXHAUSTED: You exceeded your current quota", None
        )
        client = GeminiLessonClient("key", "model")

        with patch(
            "google.genai.Client", return_value=fake_client_raising(error)
        ):
            with self.assertRaises(ProviderQuotaExceeded):
                client.generate_lesson("DBMS Normalization")

    def test_high_demand_refusal_stays_a_retryable_provider_error(self):
        error = FakeProviderError(
            "503 UNAVAILABLE: This model is currently experiencing high demand.",
            503,
        )
        client = GeminiLessonClient("key", "model")

        with patch(
            "google.genai.Client", return_value=fake_client_raising(error)
        ):
            with self.assertRaises(LessonProviderError) as caught:
                client.generate_lesson("DBMS Normalization")

        self.assertNotIsInstance(caught.exception, ProviderQuotaExceeded)
        self.assertIn("could not generate the lesson", str(caught.exception))

    def test_every_generation_call_maps_a_quota_refusal(self):
        error = FakeProviderError("429 RESOURCE_EXHAUSTED: quota exceeded", 429)
        client = GeminiLessonClient("key", "model")
        calls = [
            lambda: client.generate_lesson("topic"),
            lambda: client.generate_battle("topic", []),
            lambda: client.generate_boss_weak_spots("topic", []),
            lambda: client.generate_boss_adaptive("topic", [], 1),
            lambda: client.generate_review({"saved_concept": "x"}),
        ]

        for call in calls:
            with patch(
                "google.genai.Client", return_value=fake_client_raising(error)
            ):
                with self.assertRaises(ProviderQuotaExceeded):
                    call()


class TestQuotaRouteHandling(unittest.TestCase):
    def setUp(self):
        from dejavu.services.ai_client import FakeGeminiClient

        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.database = str(Path(self.tempdir.name) / "quota.sqlite3")
        self.ai_client = FakeGeminiClient()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "quota-only-secret",
                "LESSON_CLIENT": self.ai_client,
            }
        )
        self.client = self.app.test_client()
        self.client.post(
            "/identity",
            data={"display_name": "Arjun"},
            follow_redirects=True,
        )

    def rows(self, sql):
        with connect(self.database) as connection:
            return [dict(row) for row in connection.execute(sql)]

    def test_lesson_quota_refusal_keeps_the_topic_and_creates_no_session(self):
        self.ai_client.result = ProviderQuotaExceeded(QUOTA_MESSAGE)

        response = self.client.post("/topic", data={"topic": "DBMS Normalization"})

        self.assertEqual(response.status_code, 303)
        construct = self.client.get(response.location)
        self.assertEqual(construct.status_code, 200)
        self.assertIn(b"quota", construct.data.lower())
        self.assertIn(b"DBMS Normalization", construct.data)
        self.assertEqual(self.rows("SELECT * FROM learning_sessions"), [])

    def test_battle_quota_refusal_keeps_the_lesson_and_allows_a_retry(self):
        lesson = self.client.post(
            "/topic", data={"topic": "DBMS Normalization"}, follow_redirects=True
        )
        setup_id = ACTION_PATTERN.search(lesson.data).group(1).decode()
        self.ai_client.battle_result = ProviderQuotaExceeded(QUOTA_MESSAGE)

        failed = self.client.post("/battle/start", data={"action_id": setup_id})

        self.assertEqual(failed.status_code, 200)
        self.assertIn(b"quota", failed.data.lower())
        self.assertIn(b"lesson-title", failed.data)
        self.assertEqual(len(self.rows("SELECT * FROM learning_sessions")), 1)

        self.ai_client.battle_result = None
        retried = self.client.post("/battle/start", data={"action_id": setup_id})
        self.assertEqual(retried.status_code, 303)

    def test_boss_quota_refusal_stays_at_setup_and_starts_no_encounter(self):
        lesson = self.client.post(
            "/topic", data={"topic": "DBMS Normalization"}, follow_redirects=True
        )
        setup_id = ACTION_PATTERN.search(lesson.data).group(1).decode()
        self.client.post("/battle/start", data={"action_id": setup_id})
        battle = self.client.get(
            self.client.post("/battle/start", data={"action_id": setup_id}).location
        )
        # answer the battle to completion so the boss setup becomes reachable
        page = battle
        for _ in range(40):
            with self.client.session_transaction() as browser_session:
                run_id = browser_session.get("run_id")
            encounter = self.app.extensions["dejavu_runs"][run_id]["battle"]
            if encounter["phase"] == "complete":
                break
            if encounter["phase"] == "answered":
                transition = ACTION_PATTERN.search(page.data).group(1).decode()
                page = self.client.get(
                    self.client.post(
                        "/battle/advance", data={"action_id": transition}
                    ).location
                )
                continue
            question = encounter["rounds"][encounter["round_index"]][
                encounter["question_index"]
            ]
            action = ACTION_PATTERN.search(page.data).group(1).decode()
            page = self.client.get(
                self.client.post(
                    "/battle/answer",
                    data={
                        "action_id": action,
                        "answer": str(question["correct_option_index"]),
                    },
                ).location
            )
        boss_setup = BOSS_START_PATTERN.search(page.data).group(1).decode()
        self.ai_client.boss_adaptive_result = ProviderQuotaExceeded(QUOTA_MESSAGE)

        failed = self.client.post("/boss/start", data={"action_id": boss_setup})

        self.assertEqual(failed.status_code, 200)
        self.assertIn(b"quota", failed.data.lower())
        with self.client.session_transaction() as browser_session:
            run_id = browser_session.get("run_id")
        self.assertNotIn("boss", self.app.extensions["dejavu_runs"][run_id])

    def test_review_quota_refusal_returns_to_the_mentor_and_writes_nothing(self):
        from dejavu.db.repository import (
            create_learning_session_in_transaction,
            finish_session_if_in_progress_in_transaction,
            record_mistake_in_transaction,
        )

        with connect(self.database) as connection:
            session_id = create_learning_session_in_transaction(
                connection,
                "DBMS Normalization",
                origin="player",
                started_at="2026-10-20T10:00:00.000Z",
            )
            record_mistake_in_transaction(
                connection,
                session_id=session_id,
                question_instance_id="quota-question",
                concept_label="Third normal form",
                concept_explanation="Saved explanation.",
                question_text="Saved question.",
                chosen_answer="Wrong.",
                correct_answer="Right.",
                explanation="Because.",
                occurred_at="2026-10-20T10:05:00.000Z",
            )
            finish_session_if_in_progress_in_transaction(
                connection, session_id, "completed", ended_at="2026-10-20T10:20:00.000Z"
            )
        concept_id = self.rows("SELECT id FROM weak_concepts")[0]["id"]
        events_before = self.rows("SELECT * FROM mistake_events")
        self.ai_client.review_result = ProviderQuotaExceeded(QUOTA_MESSAGE)

        response = self.client.post(
            "/review/start", data={"concept_id": str(concept_id)}
        )

        self.assertEqual(response.status_code, 303)
        mentor = self.client.get(response.location)
        self.assertEqual(mentor.status_code, 200)
        self.assertIn(b"quota", mentor.data.lower())
        self.assertIn(b"REVISIT WEAKNESS", mentor.data)
        self.assertEqual(self.rows("SELECT * FROM mistake_events"), events_before)
        self.assertEqual(self.rows("SELECT * FROM review_outcomes"), [])
        self.assertEqual(self.app.extensions["dejavu_reviews"], {})


if __name__ == "__main__":
    unittest.main()
