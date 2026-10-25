from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dejavu import create_app
from dejavu.db.connection import connect
from dejavu.db.repository import (
    create_learning_session_in_transaction,
    finish_session_if_in_progress_in_transaction,
    record_mistake_in_transaction,
    save_first_display_name,
)
from dejavu.services.ai_client import GeminiLessonClient
from dejavu.services.demo_seed import seed_demo
from dejavu.services.mentor_context import get_mentor_context


class TestMentorRoutes(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.database = str(Path(self.tempdir.name) / "mentor-routes.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "test-only-secret",
                "DEJAVU_FAKE_AI": False,
            }
        )
        self.client = self.app.test_client()

    def save_name(self, name: str = "Arjun") -> None:
        save_first_display_name(self.database, name)

    def mistake(
        self,
        label: str,
        occurred_at: str,
        *,
        concept_explanation: str | None = None,
        question: str | None = None,
        chosen_answer: str = "The saved wrong choice.",
        correct_answer: str = "The saved correct answer.",
        explanation: str = "The saved explanation.",
    ) -> dict:
        return {
            "label": label,
            "concept_explanation": concept_explanation
            or f"Stored explanation for {label}.",
            "question": question or f"Stored question for {label}.",
            "chosen_answer": chosen_answer,
            "correct_answer": correct_answer,
            "explanation": explanation,
            "occurred_at": occurred_at,
        }

    def create_history(
        self,
        *,
        topic: str = "DBMS Normalization",
        concepts: list[dict] | None = None,
        origin: str = "player",
        started_at: str = "2026-10-20T10:00:00.000Z",
        ended_at: str = "2026-10-20T10:20:00.000Z",
    ) -> str:
        concepts = concepts or []
        with connect(self.database) as connection:
            session_id = create_learning_session_in_transaction(
                connection,
                topic,
                origin=origin,
                started_at=started_at,
            )
            for index, concept in enumerate(concepts):
                record_mistake_in_transaction(
                    connection,
                    session_id=session_id,
                    question_instance_id=f"route-question-{index}",
                    concept_label=concept["label"],
                    concept_explanation=concept["concept_explanation"],
                    question_text=concept["question"],
                    chosen_answer=concept["chosen_answer"],
                    correct_answer=concept["correct_answer"],
                    explanation=concept["explanation"],
                    occurred_at=concept["occurred_at"],
                )
            finish_session_if_in_progress_in_transaction(
                connection,
                session_id,
                "completed",
                ended_at=ended_at,
            )
        return session_id

    def test_first_time_player_without_name_sees_identity_prompt(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/identity"))
        page = self.client.get("/identity")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"IDENTITY NOT FOUND", page.data)

    def test_named_player_without_session_history_is_sent_to_construct(self):
        self.save_name()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/construct"))
        page = self.client.get("/construct")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Enter a topic.", page.data)
        self.assertNotIn(b"You have been here before.", page.data)

    def test_returning_player_with_history_sees_saved_mentor_context(self):
        self.save_name()
        self.create_history(
            concepts=[
                self.mistake(
                    "Third normal form",
                    "2026-10-20T10:05:00.000Z",
                    concept_explanation=(
                        "Third normal form removes transitive dependencies."
                    ),
                    question=(
                        "Which normal form removes transitive dependencies?"
                    ),
                    chosen_answer=(
                        "Partial dependencies on part of a composite key."
                    ),
                    correct_answer=(
                        "Transitive dependencies between non-key attributes."
                    ),
                    explanation=(
                        "3NF removes transitive dependencies between non-key "
                        "attributes."
                    ),
                )
            ]
        )

        response = self.client.get("/")
        data = response.data

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Arjun", data)
        self.assertIn(b"You have been here before.", data)
        self.assertIn(b"DBMS Normalization", data)
        self.assertIn(b"2026-10-20 10:00 UTC", data)
        self.assertIn(b"PRIMARY WEAKNESS", data)
        self.assertIn(b"Third normal form", data)
        self.assertIn(
            b"Third normal form removes transitive dependencies.", data
        )
        self.assertIn(
            b"Which normal form removes transitive dependencies?", data
        )
        self.assertIn(
            b"Partial dependencies on part of a composite key.", data
        )
        self.assertIn(
            b"Transitive dependencies between non-key attributes.", data
        )
        self.assertIn(
            b"3NF removes transitive dependencies between non-key attributes.",
            data,
        )
        self.assertIn(b"2026-10-20 10:05 UTC", data)
        self.assertIn(b"1 SAVED MISS", data)

    def test_one_weak_concept_is_displayed_as_primary(self):
        self.save_name()
        self.create_history(
            concepts=[self.mistake("Index selectivity", "2026-10-20T10:05:00.000Z")]
        )

        response = self.client.get("/")
        data = response.data

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.count(b'class="weakness-card'), 1)
        self.assertIn(b"PRIMARY WEAKNESS", data)
        self.assertNotIn(b"SECONDARY WEAKNESS", data)

    def test_two_most_recent_weak_concepts_are_displayed(self):
        self.save_name()
        self.create_history(
            concepts=[
                self.mistake(
                    "Oldest weakness",
                    "2026-10-20T10:05:00.000Z",
                    question="Oldest question",
                ),
                self.mistake(
                    "Middle weakness",
                    "2026-10-20T10:10:00.000Z",
                    question="Middle question",
                ),
                self.mistake(
                    "Newest weakness",
                    "2026-10-20T10:15:00.000Z",
                    question="Newest question",
                ),
            ]
        )

        response = self.client.get("/")
        data = response.data

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data.count(b'class="weakness-card'), 2)
        self.assertIn(b"Newest weakness", data)
        self.assertIn(b"Middle weakness", data)
        self.assertNotIn(b"Oldest weakness", data)
        self.assertLess(
            data.index(b"Newest weakness"),
            data.index(b"Middle weakness"),
        )
        self.assertIn(b"PRIMARY WEAKNESS", data)
        self.assertIn(b"SECONDARY WEAKNESS", data)

    def test_session_history_without_mistakes_explains_no_saved_weakness(self):
        self.save_name()
        self.create_history(topic="Networking", concepts=[])

        response = self.client.get("/")
        data = response.data

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You have been here before.", data)
        self.assertIn(b"Networking", data)
        self.assertIn(b"2026-10-20 10:00 UTC", data)
        self.assertIn(b"NO SAVED MISTAKES", data)
        self.assertIn(b"No saved mistakes are available yet.", data)
        self.assertIn(
            b"When you miss a battle question, the saved weakness will appear here.",
            data,
        )
        self.assertEqual(data.count(b'class="weakness-card'), 0)

    def test_seeded_demo_history_is_badged_after_identity_setup(self):
        seed_demo(self.database)

        identity = self.client.get("/")
        self.assertEqual(identity.status_code, 302)
        self.assertTrue(identity.headers["Location"].endswith("/identity"))

        response = self.client.post(
            "/identity",
            data={"display_name": "Arjun"},
            follow_redirects=True,
        )
        data = response.data

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SEEDED DEMO HISTORY", data)
        self.assertIn(b"You have been here before.", data)
        self.assertIn(b"DBMS Normalization", data)
        self.assertIn(b"2026-10-18 09:00 UTC", data)
        self.assertIn(b"Candidate keys", data)
        self.assertIn(b"Functional dependencies", data)
        self.assertIn(b"2026-10-18 09:12 UTC", data)

    def test_seeded_weakness_is_badged_when_latest_session_is_player(self):
        seed_demo(self.database)
        self.save_name()
        self.create_history(
            topic="Networking",
            concepts=[],
            started_at="2026-10-20T10:00:00.000Z",
        )

        response = self.client.get("/")
        data = response.data

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SEEDED DEMO HISTORY", data)
        self.assertIn(b"Networking", data)
        self.assertIn(b"Candidate keys", data)

    def test_player_origin_history_has_no_seeded_demo_badge(self):
        self.save_name()
        self.create_history(
            concepts=[self.mistake("Index selectivity", "2026-10-20T10:05:00.000Z")]
        )

        response = self.client.get("/")
        data = response.data

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"SEEDED DEMO HISTORY", data)
        self.assertIn(b'data-origin="player"', data)

    def test_mentor_context_is_retrieved_through_approved_function(self):
        self.save_name()
        self.create_history(
            concepts=[self.mistake("Index selectivity", "2026-10-20T10:05:00.000Z")]
        )

        with patch(
            "dejavu.routes.get_mentor_context",
            wraps=get_mentor_context,
        ) as retrieve:
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        retrieve.assert_called_once_with()

    def test_mentor_page_makes_no_gemini_or_api_calls(self):
        self.save_name()
        self.create_history(
            concepts=[self.mistake("Index selectivity", "2026-10-20T10:05:00.000Z")]
        )

        with patch(
            "dejavu.routes._client",
            side_effect=AssertionError("Mentor rendering must not use Gemini."),
        ) as client, patch.object(
            GeminiLessonClient,
            "generate_lesson",
            side_effect=AssertionError("Mentor rendering must not use Gemini."),
        ), patch.object(
            GeminiLessonClient,
            "generate_battle",
            side_effect=AssertionError("Mentor rendering must not use Gemini."),
        ):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        client.assert_not_called()

    def test_download_a_new_topic_navigates_to_construct(self):
        self.save_name()
        self.create_history(
            concepts=[self.mistake("Index selectivity", "2026-10-20T10:05:00.000Z")]
        )

        response = self.client.get("/")
        self.assertIn(b"DOWNLOAD A NEW TOPIC", response.data)
        self.assertIn(b'href="/construct"', response.data)

        construct = self.client.get("/construct")
        self.assertEqual(construct.status_code, 200)
        self.assertIn(b"Enter a topic.", construct.data)
        self.assertIn(b"DOWNLOAD LESSON", construct.data)

    def test_revisit_weakness_starts_a_review_for_a_saved_concept(self):
        self.save_name()
        self.create_history(
            concepts=[self.mistake("Index selectivity", "2026-10-20T10:05:00.000Z")]
        )
        concept_id = self.concept_id("Index selectivity")

        response = self.client.get("/")
        data = response.data

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"REVISIT WEAKNESS", data)
        self.assertIn(b'action="/review/start"', data)
        self.assertIn(b'name="concept_id"', data)
        self.assertIn(f'value="{concept_id}"'.encode(), data)
        self.assertNotIn(b"next build step", data)
        self.assertNotIn(b'aria-disabled="true"', data)
        self.assertNotIn(b'href="/review/weakness', data)

    def concept_id(self, label: str) -> int:
        with connect(self.database) as connection:
            row = connection.execute(
                "SELECT id FROM weak_concepts WHERE label = ?", (label,)
            ).fetchone()
        return int(row["id"])


if __name__ == "__main__":
    unittest.main()
