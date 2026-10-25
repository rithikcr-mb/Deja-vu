from __future__ import annotations

import re
import sqlite3
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
)
from dejavu.services.ai_client import FakeGeminiClient, LessonProviderError


ACTION_PATTERN = re.compile(rb'name="action_id" value="([^"]+)"')


class ReviewRouteHelpers(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.database = str(Path(self.tempdir.name) / "review-routes.sqlite3")
        self.ai_client = FakeGeminiClient()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "review-only-secret",
                "LESSON_CLIENT": self.ai_client,
            }
        )
        self.client = self.app.test_client()
        self.client.post(
            "/identity",
            data={"display_name": "Arjun"},
            follow_redirects=True,
        )

    # -- database helpers -------------------------------------------------
    def rows(self, sql, *parameters):
        with connect(self.database) as connection:
            return [
                dict(row)
                for row in connection.execute(sql, parameters).fetchall()
            ]

    def events(self):
        return self.rows("SELECT * FROM mistake_events ORDER BY occurred_at, id")

    def concepts(self):
        return self.rows("SELECT * FROM weak_concepts ORDER BY id")

    def review_outcomes(self):
        return self.rows("SELECT * FROM review_outcomes ORDER BY occurred_at, id")

    def sessions(self):
        return self.rows("SELECT * FROM learning_sessions ORDER BY started_at, id")

    def save_history(self, label="Third normal form", concept_count=1):
        with connect(self.database) as connection:
            session_id = create_learning_session_in_transaction(
                connection,
                "DBMS Normalization",
                origin="player",
                started_at="2026-10-20T10:00:00.000Z",
            )
            for index in range(concept_count):
                record_mistake_in_transaction(
                    connection,
                    session_id=session_id,
                    question_instance_id=f"review-question-{index}",
                    concept_label=label if index == 0 else f"{label} {index}",
                    concept_explanation="Saved explanation for the weakness.",
                    question_text="Which statement describes the concept?",
                    chosen_answer="The saved wrong choice.",
                    correct_answer="The saved correct answer.",
                    explanation="The saved explanation.",
                    occurred_at=f"2026-10-20T10:0{index}:00.000Z",
                )
            finish_session_if_in_progress_in_transaction(
                connection,
                session_id,
                "completed",
                ended_at="2026-10-20T10:20:00.000Z",
            )
        return session_id

    def save_session_without_mistakes(self):
        with connect(self.database) as connection:
            session_id = create_learning_session_in_transaction(
                connection,
                "Networking",
                origin="player",
                started_at="2026-10-20T10:00:00.000Z",
            )
            finish_session_if_in_progress_in_transaction(
                connection,
                session_id,
                "completed",
                ended_at="2026-10-20T10:20:00.000Z",
            )
        return session_id

    def concept_id(self, label="Third normal form"):
        for concept in self.concepts():
            if concept["label"] == label:
                return concept["id"]
        raise AssertionError(f"no saved concept named {label}")

    # -- review helpers ---------------------------------------------------
    @staticmethod
    def action_id(page):
        match = ACTION_PATTERN.search(page.data)
        assert match is not None, "page carried no action_id"
        return match.group(1).decode()

    def start_review(self, concept_id=None):
        if concept_id is None:
            concept_id = self.concept_id()
        response = self.client.post(
            "/review/start", data={"concept_id": str(concept_id)}
        )
        return response

    def open_review(self):
        started = self.start_review()
        self.assertEqual(started.status_code, 303)
        page = self.client.get(started.location)
        self.assertEqual(page.status_code, 200)
        return page

    def answer_review(self, page, *, correct):
        with self.client.session_transaction() as browser_session:
            review_id = browser_session.get("review_id")
        review = self.app.extensions["dejavu_reviews"][review_id]
        question = review["questions"][review["question_index"]]
        selected = question["correct_option_index"]
        if not correct:
            selected = (selected + 1) % 4
        action_id = self.action_id(page)
        response = self.client.post(
            "/review/answer",
            data={"action_id": action_id, "answer": str(selected)},
        )
        self.assertEqual(response.status_code, 303)
        return self.client.get(response.location)

    def advance_review(self, page):
        action_id = self.action_id(page)
        response = self.client.post(
            "/review/advance", data={"action_id": action_id}
        )
        self.assertEqual(response.status_code, 303)
        return self.client.get(response.location)


class TestReviewRoutes(ReviewRouteHelpers):
    def test_review_starts_for_a_saved_concept(self):
        self.save_history()
        events_before = self.events()

        page = self.open_review()

        self.assertIn(b"WEAKNESS REVIEW", page.data)
        self.assertIn(b"Third normal form", page.data)
        self.assertIn(b"Saved explanation for the weakness.", page.data)
        self.assertIn(b"PRACTICE QUESTION 1 OF 2", page.data)
        self.assertEqual(page.data.count(b'type="radio"'), 4)
        self.assertEqual(page.data.count(b'name="answer"'), 4)
        self.assertIn(b"LOCK ANSWER", page.data)
        self.assertEqual(self.events(), events_before)
        self.assertEqual(self.review_outcomes(), [])

    def test_review_shows_the_original_missed_question_when_available(self):
        self.save_history()

        page = self.open_review()

        self.assertIn(b"ORIGINAL MISSED QUESTION", page.data)
        self.assertIn(b"Which statement describes the concept?", page.data)
        self.assertIn(b"The saved wrong choice.", page.data)
        self.assertIn(b"The saved correct answer.", page.data)

    def test_review_is_not_offered_without_a_saved_weakness(self):
        self.save_session_without_mistakes()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NO SAVED MISTAKES", response.data)
        self.assertNotIn(b'action="/review/start"', response.data)
        self.assertNotIn(b"REVISIT WEAKNESS", response.data)

    def test_review_rejects_an_unknown_concept_id(self):
        self.save_history()
        events_before = self.events()

        response = self.start_review(concept_id=9999)

        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].startswith("/?error="))
        mentor = self.client.get(response.location)
        self.assertEqual(mentor.status_code, 200)
        self.assertIn(b"not available any more", mentor.data)
        self.assertEqual(self.events(), events_before)
        self.assertEqual(self.review_outcomes(), [])
        self.assertEqual(self.app.extensions["dejavu_reviews"], {})

    def test_review_rejects_a_non_numeric_concept_id(self):
        self.save_history()

        response = self.client.post(
            "/review/start", data={"concept_id": "not-an-id"}
        )

        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].startswith("/?error="))
        self.assertEqual(self.app.extensions["dejavu_reviews"], {})

    def test_exactly_two_questions_are_generated_and_validated(self):
        self.save_history()

        page = self.open_review()

        self.assertEqual(len(self.ai_client.review_calls), 1)
        self.assertEqual(
            self.ai_client.review_calls[0],
            {
                "saved_concept": "Third normal form",
                "saved_explanation": "Saved explanation for the weakness.",
            },
        )
        with self.client.session_transaction() as browser_session:
            review_id = browser_session.get("review_id")
        review = self.app.extensions["dejavu_reviews"][review_id]
        self.assertEqual(len(review["questions"]), 2)
        for question in review["questions"]:
            self.assertEqual(len(question["options"]), 4)
            self.assertIn(question["correct_option_index"], range(4))
            self.assertTrue(question["explanation"])

        second = self.advance_review(self.answer_review(page, correct=True))
        self.assertIn(b"PRACTICE QUESTION 2 OF 2", second.data)

    def test_incomplete_generated_questions_are_rejected(self):
        self.save_history()
        self.ai_client.review_result = {
            "questions": [
                {
                    "question": "Only one question.",
                    "options": ["A", "B", "C", "D"],
                    "correct_option_index": 0,
                    "explanation": "Explanation.",
                    "target_concept_label": "Third normal form",
                }
            ]
        }

        response = self.start_review()

        self.assertEqual(response.status_code, 303)
        mentor = self.client.get(response.location)
        self.assertIn(b"Review questions could not be created", mentor.data)
        self.assertEqual(self.app.extensions["dejavu_reviews"], {})
        self.assertEqual(self.review_outcomes(), [])

    def test_provider_failure_keeps_history_and_returns_to_the_mentor(self):
        self.save_history()
        events_before = self.events()
        concepts_before = self.concepts()
        self.ai_client.review_result = LessonProviderError("provider offline")

        response = self.start_review()

        self.assertEqual(response.status_code, 303)
        mentor = self.client.get(response.location)
        self.assertEqual(mentor.status_code, 200)
        self.assertIn(b"Review questions could not be created", mentor.data)
        self.assertIn(b"REVISIT WEAKNESS", mentor.data)
        self.assertEqual(self.events(), events_before)
        self.assertEqual(self.concepts(), concepts_before)
        self.assertEqual(self.review_outcomes(), [])
        self.assertEqual(self.app.extensions["dejavu_reviews"], {})

    def test_correct_answers_are_stored_as_review_outcomes(self):
        self.save_history()
        events_before = self.events()
        concepts_before = self.concepts()

        page = self.open_review()
        page = self.answer_review(page, correct=True)
        self.assertIn(b"CORRECT / REVIEW ANSWER", page.data)
        page = self.advance_review(page)
        page = self.answer_review(page, correct=True)
        self.assertIn(b"CORRECT / REVIEW ANSWER", page.data)

        outcomes = self.review_outcomes()
        self.assertEqual(len(outcomes), 2)
        for outcome in outcomes:
            self.assertEqual(outcome["is_correct"], 1)
            self.assertEqual(outcome["weak_concept_id"], self.concept_id())
            self.assertTrue(outcome["review_id"])
            self.assertTrue(outcome["question_instance_id"])
        self.assertEqual(
            len({outcome["question_instance_id"] for outcome in outcomes}), 2
        )
        # The original mistake history is untouched.
        self.assertEqual(self.events(), events_before)
        self.assertEqual(self.concepts(), concepts_before)

    def test_wrong_review_answer_does_not_create_a_mistake_event(self):
        self.save_history()
        events_before = self.events()
        concepts_before = self.concepts()

        page = self.open_review()
        page = self.answer_review(page, correct=False)

        self.assertIn(b"INCORRECT / REVIEW ANSWER", page.data)
        outcomes = self.review_outcomes()
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["is_correct"], 0)
        self.assertEqual(self.events(), events_before)
        self.assertEqual(self.concepts(), concepts_before)
        self.assertEqual(
            self.concepts()[0]["last_missed_at"], concepts_before[0]["last_missed_at"]
        )
        self.assertEqual(self.sessions()[0]["status"], "completed")

    def test_duplicate_review_submission_writes_one_outcome_only(self):
        self.save_history()
        page = self.open_review()
        with self.client.session_transaction() as browser_session:
            review_id = browser_session.get("review_id")
        review = self.app.extensions["dejavu_reviews"][review_id]
        question = review["questions"][review["question_index"]]
        action_id = self.action_id(page)
        data = {
            "action_id": action_id,
            "answer": str(question["correct_option_index"]),
        }

        first = self.client.post("/review/answer", data=data)
        repeated = self.client.post("/review/answer", data=data)

        self.assertEqual(first.status_code, 303)
        self.assertEqual(repeated.status_code, 303)
        self.assertEqual(len(self.review_outcomes()), 1)

    def test_review_finishes_and_returns_to_the_mentor(self):
        self.save_history()
        page = self.open_review()
        page = self.answer_review(page, correct=True)
        page = self.advance_review(page)
        page = self.answer_review(page, correct=True)
        self.assertIn(b"FINISH REVIEW", page.data)

        completed = self.client.post(
            "/review/complete", data={"action_id": self.action_id(page)}
        )
        self.assertEqual(completed.status_code, 303)
        summary = self.client.get(completed.location)
        self.assertEqual(summary.status_code, 200)
        self.assertIn(b"REVIEW COMPLETE", summary.data)
        self.assertIn(b"2 of 2 practice questions answered correctly.", summary.data)
        self.assertIn(b"REVIEW ANOTHER WEAKNESS", summary.data)
        self.assertIn(b"DOWNLOAD A NEW TOPIC", summary.data)

        finished = self.client.post(
            "/review/finish", data={"action_id": self.action_id(summary)}
        )
        self.assertEqual(finished.status_code, 303)
        mentor = self.client.get(finished.location)
        self.assertEqual(mentor.status_code, 200)
        self.assertIn(b"You have been here before.", mentor.data)
        self.assertIn(b"REVISIT WEAKNESS", mentor.data)
        self.assertEqual(self.app.extensions["dejavu_reviews"], {})

    def test_review_can_continue_to_a_new_topic(self):
        self.save_history()
        page = self.open_review()
        page = self.answer_review(page, correct=True)
        page = self.advance_review(page)
        page = self.answer_review(page, correct=True)
        page = self.client.get(
            self.client.post(
                "/review/complete", data={"action_id": self.action_id(page)}
            ).location
        )

        returned = self.client.post(
            "/review/new-topic", data={"action_id": self.action_id(page)}
        )
        self.assertEqual(returned.status_code, 303)
        construct = self.client.get(returned.location)
        self.assertEqual(construct.status_code, 200)
        self.assertIn(b"Enter a topic.", construct.data)
        self.assertEqual(self.app.extensions["dejavu_reviews"], {})

    def test_stale_review_action_ids_are_safe(self):
        self.save_history()
        page = self.open_review()

        stale = self.client.post(
            "/review/answer", data={"action_id": "stale-attempt", "answer": "1"}
        )
        self.assertEqual(stale.status_code, 303)
        self.assertEqual(self.review_outcomes(), [])

        stale_advance = self.client.post(
            "/review/advance", data={"action_id": "stale-transition"}
        )
        self.assertEqual(stale_advance.status_code, 303)
        self.assertEqual(self.review_outcomes(), [])

    def test_review_generation_failure_never_fabricates_questions(self):
        self.save_history()
        self.ai_client.review_result = LessonProviderError("provider offline")

        response = self.start_review()
        mentor = self.client.get(response.location)

        self.assertNotIn(b"LOCK ANSWER", mentor.data)
        self.assertNotIn(b"PRACTICE QUESTION", mentor.data)
        self.assertEqual(self.review_outcomes(), [])

    def test_review_save_failure_keeps_the_question_open(self):
        self.save_history()
        page = self.open_review()
        with self.client.session_transaction() as browser_session:
            review_id = browser_session.get("review_id")
        review = self.app.extensions["dejavu_reviews"][review_id]
        question = review["questions"][review["question_index"]]
        action_id = self.action_id(page)
        data = {
            "action_id": action_id,
            "answer": str((question["correct_option_index"] + 1) % 4),
        }

        with patch(
            "dejavu.routes.record_review_outcome",
            side_effect=sqlite3.Error("database unavailable"),
        ):
            failed = self.client.post("/review/answer", data=data)

        self.assertEqual(failed.status_code, 200)
        self.assertIn(b"could not be saved", failed.data)
        self.assertEqual(self.review_outcomes(), [])
        self.assertEqual(self.app.extensions["dejavu_reviews"][review_id]["phase"], "question")

        retried = self.client.post("/review/answer", data=data)
        self.assertEqual(retried.status_code, 303)
        self.assertEqual(len(self.review_outcomes()), 1)


if __name__ == "__main__":
    unittest.main()
