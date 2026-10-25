from __future__ import annotations

import copy
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dejavu import create_app
from dejavu.db.connection import connect
from dejavu.services.ai_client import FakeGeminiClient, LessonProviderError


ACTION_PATTERN = re.compile(rb'name="action_id" value="([^"]+)"')
BOSS_START_PATTERN = re.compile(
    rb'<form action="/boss/start"[^>]*>.*?name="action_id" value="([^"]+)"',
    re.S,
)


class BossRouteHelpers(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.database = str(Path(self.tempdir.name) / "boss-routes.sqlite3")
        self.ai_client = FakeGeminiClient()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "test-only-secret",
                "LESSON_CLIENT": self.ai_client,
            }
        )
        self.client = self.app.test_client()
        self.client.post(
            "/identity",
            data={"display_name": "Arjun"},
            follow_redirects=True,
        )

    def events(self):
        with connect(self.database) as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM mistake_events ORDER BY occurred_at, id"
                )
            ]

    def concepts(self):
        with connect(self.database) as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM weak_concepts ORDER BY id"
                )
            ]

    def sessions(self):
        with connect(self.database) as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM learning_sessions ORDER BY started_at"
                )
            ]

    def current_run(self):
        with self.client.session_transaction() as browser_session:
            run_id = browser_session.get("run_id")
        return run_id, self.app.extensions["dejavu_runs"].get(run_id)

    def start_battle(self):
        lesson = self.client.post(
            "/topic",
            data={"topic": "DBMS Normalization"},
            follow_redirects=True,
        )
        setup_id = ACTION_PATTERN.search(lesson.data).group(1).decode()
        response = self.client.post(
            "/battle/start", data={"action_id": setup_id}
        )
        self.assertEqual(response.status_code, 303)
        battle = self.client.get(response.location)
        self.assertEqual(battle.status_code, 200)
        return battle

    def answer_regular(self, page, *, correct):
        _, run = self.current_run()
        encounter = run["battle"]
        if encounter["phase"] == "question":
            question = encounter["rounds"][encounter["round_index"]][
                encounter["question_index"]
            ]
            selected = question["correct_option_index"]
            if not correct:
                selected = (selected + 1) % 4
            action_id = ACTION_PATTERN.search(page.data).group(1).decode()
            response = self.client.post(
                "/battle/answer",
                data={"action_id": action_id, "answer": str(selected)},
            )
            self.assertEqual(response.status_code, 303)
            return self.client.get(response.location)
        if encounter["phase"] == "answered":
            action_id = ACTION_PATTERN.search(page.data).group(1).decode()
            response = self.client.post(
                "/battle/advance", data={"action_id": action_id}
            )
            self.assertEqual(response.status_code, 303)
            return self.client.get(response.location)
        return page

    def complete_regular_battle(self, page, *, wrong_count=0):
        answered = 0
        while True:
            _, run = self.current_run()
            encounter = run["battle"]
            if encounter["phase"] == "complete":
                return page
            if (
                encounter["phase"] == "answered"
                and encounter["next_action"] == "defeat"
            ):
                self.fail("Regular battle ended in unexpected defeat.")
            if encounter["phase"] == "question":
                page = self.answer_regular(
                    page, correct=answered >= wrong_count
                )
                answered += 1
            else:
                page = self.answer_regular(page, correct=True)

    def start_boss(self, page):
        match = BOSS_START_PATTERN.search(page.data)
        self.assertIsNotNone(match)
        setup_id = match.group(1).decode()
        response = self.client.post(
            "/boss/start", data={"action_id": setup_id}
        )
        self.assertEqual(response.status_code, 303)
        boss_page = self.client.get(response.location)
        self.assertEqual(boss_page.status_code, 200)
        return setup_id, response, boss_page

    def answer_boss(self, page, *, correct):
        _, run = self.current_run()
        encounter = run["boss"]
        question = encounter["questions"][encounter["question_index"]]
        selected = question["correct_option_index"]
        if not correct:
            selected = (selected + 1) % 4
        action_id = ACTION_PATTERN.search(page.data).group(1).decode()
        response = self.client.post(
            "/boss/answer",
            data={"action_id": action_id, "answer": str(selected)},
        )
        self.assertEqual(response.status_code, 303)
        return action_id, response, self.client.get(response.location)

    def advance_boss(self, page):
        action_id = ACTION_PATTERN.search(page.data).group(1).decode()
        response = self.client.post(
            "/boss/advance", data={"action_id": action_id}
        )
        self.assertEqual(response.status_code, 303)
        return self.client.get(response.location)

    def play_boss(self, page, correct_flags):
        response = None
        for correct in correct_flags:
            _, response, page = self.answer_boss(page, correct=correct)
            _, run = self.current_run()
            if run is None:
                break
            encounter = run["boss"]
            if (
                encounter["phase"] == "answered"
                and encounter["next_action"] == "next_question"
            ):
                page = self.advance_boss(page)
            else:
                break
        return page, response


class TestBossRoutes(BossRouteHelpers):
    def test_regular_battle_completion_enters_five_question_adaptive_boss(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)

        _, _, boss_page = self.start_boss(battle)

        _, run = self.current_run()
        encounter = run["boss"]
        self.assertEqual(len(encounter["questions"]), 5)
        self.assertEqual(
            sum(
                question["kind"] == "adaptive"
                for question in encounter["questions"]
            ),
            5,
        )
        self.assertEqual(self.ai_client.boss_weak_calls, [])
        self.assertEqual(len(self.ai_client.boss_adaptive_calls), 1)
        self.assertIn(b"ADAPTIVE TEST", boss_page.data)
        self.assertNotIn(b"WEAK SPOT DETECTED", boss_page.data)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")

    def test_boss_uses_saved_weak_concepts_and_trusted_links(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=3)
        saved_concepts = self.concepts()

        _, _, boss_page = self.start_boss(battle)

        _, run = self.current_run()
        encounter = run["boss"]
        weak_questions = [
            question
            for question in encounter["questions"]
            if question["kind"] == "weak_spot"
        ]
        self.assertEqual(len(weak_questions), min(len(saved_concepts), 5))
        self.assertEqual(
            {question["weak_concept_id"] for question in weak_questions},
            {concept["id"] for concept in saved_concepts[:5]},
        )
        for question in weak_questions:
            self.assertTrue(question["mistake_event_id"])
        self.assertIn(b"WEAK SPOT DETECTED", boss_page.data)
        self.assertIn(b"PREVIOUSLY MISSED", boss_page.data)
        for candidate in self.ai_client.boss_weak_calls[0]["candidates"]:
            self.assertNotIn("weak_concept_id", candidate)
            self.assertNotIn("mistake_event_id", candidate)

    def test_correct_weak_spot_answer_does_not_create_a_mistake(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=2)
        _, _, boss_page = self.start_boss(battle)
        events_before = self.events()

        self.answer_boss(boss_page, correct=True)

        _, run = self.current_run()
        self.assertEqual(run["boss"]["boss_hp"], 75)
        self.assertEqual(run["boss"]["player_hp"], 100)
        self.assertEqual(self.events(), events_before)

    def test_incorrect_weak_spot_persists_against_trusted_concept(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=2)
        _, _, boss_page = self.start_boss(battle)
        _, run = self.current_run()
        question = run["boss"]["questions"][0]
        events_before = len(self.events())

        action_id, _, result_page = self.answer_boss(
            boss_page, correct=False
        )

        events = self.events()
        self.assertEqual(len(events), events_before + 1)
        event = events[-1]
        self.assertEqual(event["question_kind"], "boss")
        self.assertEqual(event["weak_concept_id"], question["weak_concept_id"])
        self.assertEqual(event["question_instance_id"], action_id)
        self.assertIn(b"INCORRECT / OPERATOR LOSES 20 HP", result_page.data)
        self.assertEqual(self.current_run()[1]["boss"]["player_hp"], 80)
        self.assertEqual(
            self.current_run()[1]["boss"]["boss_hp"], 100
        )

    def test_incorrect_adaptive_answer_creates_weak_concept(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        _, _, boss_page = self.start_boss(battle)
        _, run = self.current_run()
        question = run["boss"]["questions"][0]
        self.assertEqual(question["kind"], "adaptive")
        self.assertEqual(self.concepts(), [])

        action_id, _, result_page = self.answer_boss(
            boss_page, correct=False
        )

        concepts = self.concepts()
        events = self.events()
        self.assertEqual(len(concepts), 1)
        self.assertEqual(concepts[0]["label"], question["concept_label"])
        self.assertEqual(
            concepts[0]["explanation"], question["concept_explanation"]
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["question_kind"], "boss")
        self.assertEqual(events[0]["weak_concept_id"], concepts[0]["id"])
        self.assertEqual(events[0]["question_instance_id"], action_id)
        self.assertIn(b"INCORRECT / OPERATOR LOSES 20 HP", result_page.data)
        self.assertEqual(self.current_run()[1]["boss"]["player_hp"], 80)

    def test_persistence_failure_keeps_question_and_health_pending(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        _, _, boss_page = self.start_boss(battle)
        _, run = self.current_run()
        question = run["boss"]["questions"][0]
        selected = (question["correct_option_index"] + 1) % 4
        action_id = ACTION_PATTERN.search(boss_page.data).group(1).decode()

        with patch(
            "dejavu.routes.record_mistake",
            side_effect=sqlite3.Error("database unavailable"),
        ):
            failed = self.client.post(
                "/boss/answer",
                data={"action_id": action_id, "answer": str(selected)},
            )

        self.assertEqual(failed.status_code, 200)
        self.assertIn(b"question is still open", failed.data)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.concepts(), [])
        _, run = self.current_run()
        self.assertEqual(run["boss"]["player_hp"], 100)
        self.assertEqual(run["boss"]["phase"], "question")
        self.assertEqual(run["boss"]["question_index"], 0)

        retried = self.client.post(
            "/boss/answer",
            data={"action_id": action_id, "answer": str(selected)},
        )
        self.assertEqual(retried.status_code, 303)
        result_page = self.client.get(retried.location)
        self.assertIn(b"80 / 100 HP", result_page.data)
        self.assertEqual(len(self.events()), 1)

    def test_weak_spot_persistence_failure_keeps_question_pending(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=2)
        _, _, boss_page = self.start_boss(battle)
        _, run = self.current_run()
        question = run["boss"]["questions"][0]
        self.assertEqual(question["kind"], "weak_spot")
        selected = (question["correct_option_index"] + 1) % 4
        action_id = ACTION_PATTERN.search(boss_page.data).group(1).decode()
        events_before = self.events()

        with patch(
            "dejavu.routes.record_boss_weak_spot_mistake",
            side_effect=sqlite3.Error("database unavailable"),
        ):
            failed = self.client.post(
                "/boss/answer",
                data={"action_id": action_id, "answer": str(selected)},
            )

        self.assertEqual(failed.status_code, 200)
        self.assertIn(b"question is still open", failed.data)
        self.assertEqual(self.events(), events_before)
        _, run = self.current_run()
        self.assertEqual(run["boss"]["player_hp"], 100)
        self.assertEqual(run["boss"]["phase"], "question")
        self.assertEqual(run["boss"]["question_index"], 0)

    def test_duplicate_answer_submission_does_not_duplicate_damage_or_event(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        _, _, boss_page = self.start_boss(battle)
        _, run = self.current_run()
        question = run["boss"]["questions"][0]
        selected = (question["correct_option_index"] + 1) % 4
        action_id = ACTION_PATTERN.search(boss_page.data).group(1).decode()

        first = self.client.post(
            "/boss/answer",
            data={"action_id": action_id, "answer": str(selected)},
        )
        repeated = self.client.post(
            "/boss/answer",
            data={"action_id": action_id, "answer": str(selected)},
        )

        self.assertEqual(repeated.location, first.location)
        result_page = self.client.get(first.location)
        self.assertIn(b"80 / 100 HP", result_page.data)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.current_run()[1]["boss"]["player_hp"], 80)

    def test_victory_marks_session_completed_and_clears_active_run(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        _, _, boss_page = self.start_boss(battle)

        for answer_number in range(4):
            _, response, boss_page = self.answer_boss(
                boss_page, correct=True
            )
            if answer_number < 3:
                boss_page = self.advance_boss(boss_page)
            else:
                victory_url = response.location

        self.assertIn(b"Victory", boss_page.data)
        self.assertEqual(self.sessions()[0]["status"], "completed")
        self.assertEqual(self.events(), [])
        self.assertIsNone(self.current_run()[0])
        self.assertEqual(self.current_run()[1], None)

        replay = self.client.get(victory_url, follow_redirects=True)
        self.assertIn(b"Enter a topic.", replay.data)
        self.assertEqual(self.sessions()[0]["status"], "completed")

    def test_defeat_retry_restores_health_and_preserves_questions_and_events(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        _, _, boss_page = self.start_boss(battle)

        boss_page, _ = self.play_boss(boss_page, [False] * 5)
        self.assertIn(b"RETRY BOSS", boss_page.data)
        _, run = self.current_run()
        questions_before = copy.deepcopy(run["boss"]["questions"])
        old_attempt_id = run["boss"]["attempt_id"]
        event_count = len(self.events())
        transition_id = ACTION_PATTERN.search(boss_page.data).group(1).decode()

        retried = self.client.post(
            "/boss/retry", data={"action_id": transition_id}
        )
        self.assertEqual(retried.status_code, 303)
        retry_page = self.client.get(retried.location)

        self.assertIn(b"100 / 100 HP", retry_page.data)
        _, run = self.current_run()
        self.assertEqual(run["boss"]["player_hp"], 100)
        self.assertEqual(run["boss"]["boss_hp"], 100)
        self.assertEqual(run["boss"]["question_index"], 0)
        self.assertEqual(run["boss"]["questions"], questions_before)
        self.assertNotEqual(run["boss"]["attempt_id"], old_attempt_id)
        self.assertEqual(len(self.events()), event_count)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")

        stale = self.client.post(
            "/boss/answer",
            data={"action_id": old_attempt_id, "answer": "1"},
        )
        self.assertEqual(stale.status_code, 303)
        _, run = self.current_run()
        self.assertEqual(run["boss"]["player_hp"], 100)
        self.assertEqual(run["boss"]["phase"], "question")
        self.assertEqual(len(self.events()), event_count)

    def test_five_exhausted_questions_with_boss_alive_is_defeat(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        _, _, boss_page = self.start_boss(battle)

        boss_page, _ = self.play_boss(
            boss_page, [True, True, True, False, False]
        )

        self.assertIn(b"RETRY BOSS", boss_page.data)
        _, run = self.current_run()
        self.assertEqual(run["boss"]["boss_hp"], 25)
        self.assertEqual(run["boss"]["player_hp"], 60)
        self.assertEqual(run["boss"]["next_action"], "defeat")
        self.assertEqual(self.sessions()[0]["status"], "in_progress")

    def test_returning_from_boss_defeat_finalizes_session_once(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        _, _, boss_page = self.start_boss(battle)
        boss_page, _ = self.play_boss(boss_page, [False] * 5)
        transition_id = ACTION_PATTERN.search(boss_page.data).group(1).decode()

        returned = self.client.post(
            "/boss/return", data={"action_id": transition_id}
        )
        self.assertEqual(returned.status_code, 303)
        construct = self.client.get(returned.location)
        self.assertIn(b"Enter a topic.", construct.data)
        self.assertEqual(self.sessions()[0]["status"], "defeated")
        self.assertEqual(len(self.events()), 5)
        self.assertIsNone(self.current_run()[0])

        replay = self.client.get(returned.location, follow_redirects=True)
        self.assertIn(b"Enter a topic.", replay.data)
        self.assertEqual(self.sessions()[0]["status"], "defeated")

    def test_stale_page_ticket_abandons_only_in_progress_run(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        _, start_response, boss_page = self.start_boss(battle)
        stale_url = start_response.location
        self.answer_boss(boss_page, correct=False)
        self.assertEqual(len(self.events()), 1)

        replay = self.client.get(stale_url, follow_redirects=True)

        self.assertIn(b"Enter a topic.", replay.data)
        self.assertEqual(self.sessions()[0]["status"], "abandoned")
        self.assertEqual(len(self.events()), 1)

    def test_stale_attempt_and_invalid_selection_are_safe(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        _, _, boss_page = self.start_boss(battle)

        invalid = self.client.post(
            "/boss/answer",
            data={
                "action_id": ACTION_PATTERN.search(boss_page.data).group(1).decode(),
                "answer": "not-an-integer",
            },
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn(b"Choose one of the four answers", invalid.data)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.current_run()[1]["boss"]["player_hp"], 100)

        stale = self.client.post(
            "/boss/answer",
            data={"action_id": "stale-attempt", "answer": "1"},
        )
        self.assertEqual(stale.status_code, 303)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.current_run()[1]["boss"]["player_hp"], 100)

    def test_boss_generation_failure_stays_at_setup_and_retries(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        setup_id = BOSS_START_PATTERN.search(battle.data).group(1).decode()

        self.ai_client.boss_adaptive_result = LessonProviderError("offline")
        provider_failure = self.client.post(
            "/boss/start", data={"action_id": setup_id}
        )
        self.assertEqual(provider_failure.status_code, 200)
        self.assertIn(b"Boss generation failed", provider_failure.data)
        _, run = self.current_run()
        self.assertNotIn("boss", run)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")

        self.ai_client.boss_adaptive_result = "not-json"
        malformed = self.client.post(
            "/boss/start", data={"action_id": setup_id}
        )
        self.assertEqual(malformed.status_code, 200)
        self.assertIn(b"Boss generation failed", malformed.data)
        self.assertNotIn("boss", self.current_run()[1])

        self.ai_client.boss_adaptive_result = None
        succeeded = self.client.post(
            "/boss/start", data={"action_id": setup_id}
        )
        self.assertEqual(succeeded.status_code, 303)
        boss_page = self.client.get(succeeded.location)
        self.assertEqual(boss_page.status_code, 200)
        self.assertEqual(len(self.current_run()[1]["boss"]["questions"]), 5)


class TestBossInterface(BossRouteHelpers):
    """UI contracts for the server-rendered boss encounter."""

    def adaptive_boss(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=0)
        return self.start_boss(battle)[2]

    def weak_spot_boss(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=2)
        return self.start_boss(battle)[2]

    def test_question_ui_renders_progress_health_answers_and_accessible_controls(self):
        boss_page = self.adaptive_boss()
        _, run = self.current_run()
        encounter = run["boss"]

        self.assertIn(b"FINAL BOSS / 5-QUESTION ENCOUNTER", boss_page.data)
        self.assertIn(b"ENCOUNTER PROGRESS", boss_page.data)
        self.assertIn(b"QUESTION 1 / 5", boss_page.data)
        self.assertIn(b'role="progressbar"', boss_page.data)
        self.assertIn(b'aria-valuetext="Question 1 of 5"', boss_page.data)
        self.assertIn(b"100 / 100 HP", boss_page.data)
        self.assertIn(b'role="meter"', boss_page.data)
        self.assertIn(b'aria-valuetext="100 of 100 hit points"', boss_page.data)
        self.assertIn(b"LOCK ANSWER", boss_page.data)
        self.assertIn(b"RETURN TO CONSTRUCT", boss_page.data)
        self.assertIn(b"Leaving ends this encounter", boss_page.data)

        self.assertEqual(boss_page.data.count(b'type="radio"'), 4)
        self.assertEqual(boss_page.data.count(b'name="answer"'), 4)
        for index in range(4):
            self.assertIn(
                f'id="boss-answer-{index}"'.encode(), boss_page.data
            )
            self.assertIn(
                f'for="boss-answer-{index}"'.encode(), boss_page.data
            )

        action_id = ACTION_PATTERN.search(boss_page.data).group(1).decode()
        self.assertEqual(action_id, encounter["attempt_id"])
        self.assertNotIn(b'name="weak_concept_id"', boss_page.data)
        self.assertNotIn(b'name="mistake_event_id"', boss_page.data)

    def test_weak_spot_ui_uses_only_the_trusted_saved_concept(self):
        boss_page = self.weak_spot_boss()
        _, run = self.current_run()
        question = run["boss"]["questions"][0]
        self.assertEqual(question["kind"], "weak_spot")

        self.assertIn(b"WEAK SPOT DETECTED", boss_page.data)
        self.assertIn(b"SAVED WEAKNESS", boss_page.data)
        self.assertIn(
            b"PREVIOUSLY MISSED: <strong>"
            + question["concept_label"].encode()
            + b"</strong>",
            boss_page.data,
        )
        self.assertIn(
            question["concept_explanation"].encode(), boss_page.data
        )
        self.assertIn(
            b"This harder question targets that saved concept.",
            boss_page.data,
        )
        self.assertNotIn(b'name="weak_concept_id"', boss_page.data)
        self.assertNotIn(b'name="mistake_event_id"', boss_page.data)
        self.assertNotIn(b"data-weak-concept-id", boss_page.data)
        self.assertNotIn(b"data-mistake-event-id", boss_page.data)
        self.assertNotIn(b"ADAPTIVE TEST", boss_page.data)

    def test_adaptive_ui_never_claims_a_previous_weakness(self):
        boss_page = self.adaptive_boss()

        self.assertIn(b"ADAPTIVE TEST", boss_page.data)
        self.assertIn(
            b"This question is drawn from the current lesson.",
            boss_page.data,
        )
        self.assertNotIn(b"WEAK SPOT DETECTED", boss_page.data)
        self.assertNotIn(b"PREVIOUSLY MISSED", boss_page.data)

    def test_answer_feedback_renders_choices_explanation_and_next_action(self):
        boss_page = self.adaptive_boss()
        _, run = self.current_run()
        question = run["boss"]["questions"][0]
        selected = (question["correct_option_index"] + 1) % 4
        _, response, result_page = self.answer_boss(
            boss_page, correct=False
        )

        self.assertIn(b"INCORRECT / OPERATOR LOSES 20 HP", result_page.data)
        self.assertIn(b"80 / 100 HP", result_page.data)
        self.assertIn(b"YOUR ANSWER", result_page.data)
        self.assertIn(question["options"][selected].encode(), result_page.data)
        self.assertIn(b"CORRECT ANSWER", result_page.data)
        self.assertIn(
            question["options"][question["correct_option_index"]].encode(),
            result_page.data,
        )
        self.assertIn(b"WHY", result_page.data)
        self.assertIn(question["explanation"].encode(), result_page.data)
        self.assertIn(b"NEXT QUESTION", result_page.data)
        self.assertNotIn(b'name="answer"', result_page.data)
        self.assertIn(b'aria-live="polite"', result_page.data)

        _, run = self.current_run()
        transition_id = ACTION_PATTERN.search(result_page.data).group(1).decode()
        self.assertEqual(transition_id, run["boss"]["transition_id"])
        self.assertNotEqual(transition_id, run["boss"]["attempt_id"])

        advanced = self.client.post(
            "/boss/advance", data={"action_id": transition_id}
        )
        next_page = self.client.get(advanced.location)
        self.assertIn(b"QUESTION 2 / 5", next_page.data)
        self.assertIn(b"LOCK ANSWER", next_page.data)

    def test_correct_feedback_reports_boss_damage_and_keeps_explanation(self):
        boss_page = self.adaptive_boss()
        _, run = self.current_run()
        question = run["boss"]["questions"][0]
        _, _, result_page = self.answer_boss(boss_page, correct=True)

        self.assertIn(b"CORRECT / BOSS TAKES 25 DAMAGE", result_page.data)
        self.assertIn(b"75 / 100 HP", result_page.data)
        self.assertIn(
            question["options"][question["correct_option_index"]].encode(),
            result_page.data,
        )
        self.assertIn(question["explanation"].encode(), result_page.data)
        self.assertIn(b"NEXT QUESTION", result_page.data)

    def test_defeat_ui_offers_retry_and_return_without_erasing_history(self):
        boss_page = self.adaptive_boss()
        defeat_page, _ = self.play_boss(boss_page, [False] * 5)

        self.assertIn(b"INCORRECT / OPERATOR LOSES 20 HP", defeat_page.data)
        self.assertIn(b"0 / 100 HP", defeat_page.data)
        self.assertIn(b"The final encounter is lost.", defeat_page.data)
        self.assertIn(b"saved mistakes remain", defeat_page.data)
        self.assertIn(b"RETRY BOSS", defeat_page.data)
        self.assertIn(b"RETURN TO CONSTRUCT", defeat_page.data)
        self.assertIn(b'action="/boss/retry"', defeat_page.data)
        self.assertIn(b'action="/boss/return"', defeat_page.data)
        self.assertEqual(len(self.events()), 5)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")

        transition_id = ACTION_PATTERN.search(defeat_page.data).group(1).decode()
        retried = self.client.post(
            "/boss/retry", data={"action_id": transition_id}
        )
        retry_page = self.client.get(retried.location)
        self.assertIn(b"100 / 100 HP", retry_page.data)
        self.assertIn(b"ADAPTIVE TEST", retry_page.data)
        self.assertNotIn(b"WEAK SPOT DETECTED", retry_page.data)
        self.assertNotIn(b"RETRY BOSS", retry_page.data)
        self.assertEqual(len(self.events()), 5)

    def test_victory_ui_reports_weak_spots_and_adaptive_tests_separately(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=2)
        _, _, boss_page = self.start_boss(battle)
        victory_page, _ = self.play_boss(boss_page, [True] * 4)

        self.assertIn(b"FINAL BOSS DEFEATED", victory_page.data)
        self.assertIn(b"Victory.", victory_page.data)
        self.assertIn(b"0 / 100 HP", victory_page.data)
        self.assertIn(b"WEAK SPOTS FACED", victory_page.data)
        self.assertIn(b"ADAPTIVE TESTS", victory_page.data)
        self.assertIn(
            b"2 of its questions were weak spots drawn from concepts you "
            b"previously missed, and 3 were adaptive tests from the current "
            b"lesson.",
            victory_page.data,
        )
        self.assertIn(
            b"The adaptive tests were not personal weak spots.",
            victory_page.data,
        )
        self.assertIn(
            b"Your original mistake history remains saved.",
            victory_page.data,
        )
        self.assertIn(b'href="/construct"', victory_page.data)
        self.assertNotIn(b"every question was a weak spot", victory_page.data)

    def test_victory_ui_without_saved_weakness_invents_none(self):
        boss_page = self.adaptive_boss()
        victory_page, _ = self.play_boss(boss_page, [True] * 4)

        self.assertIn(b"FINAL BOSS DEFEATED", victory_page.data)
        self.assertIn(
            b"No saved weak spots were available, so all 5 questions were "
            b"adaptive tests drawn from the current lesson.",
            victory_page.data,
        )
        self.assertNotIn(b"WEAK SPOT DETECTED", victory_page.data)
        self.assertNotIn(b"PREVIOUSLY MISSED", victory_page.data)
        self.assertNotIn(b"drawn from concepts you previously missed", victory_page.data)

    def test_return_action_on_question_ui_abandons_without_erasing_mistakes(self):
        battle = self.start_battle()
        battle = self.complete_regular_battle(battle, wrong_count=1)
        _, _, boss_page = self.start_boss(battle)
        events_before = self.events()
        _, run = self.current_run()
        transition_id = run["boss"]["transition_id"]
        self.assertEqual(
            ACTION_PATTERN.findall(boss_page.data)[1].decode(), transition_id
        )

        returned = self.client.post(
            "/boss/return", data={"action_id": transition_id}
        )
        self.assertEqual(returned.status_code, 303)
        construct = self.client.get(returned.location)
        self.assertIn(b"Enter a topic.", construct.data)
        self.assertEqual(self.sessions()[0]["status"], "abandoned")
        self.assertEqual(self.events(), events_before)
        self.assertIsNone(self.current_run()[0])


if __name__ == "__main__":
    unittest.main()
