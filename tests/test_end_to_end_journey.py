"""End-to-end verification of the DEJAVU journey on the real app and database.

These tests drive the Flask app with the deterministic fake AI provider and a
real SQLite file. They cover only the journey links that the focused unit and
route tests do not already prove on their own.
"""

from __future__ import annotations

import copy
import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dejavu import create_app
from dejavu.db.connection import connect
from dejavu.services.ai_client import FakeGeminiClient, LessonProviderError
from dejavu.services.demo_seed import seed_demo


ACTION_PATTERN = re.compile(rb'name="action_id" value="([^"]+)"')
BOSS_START_PATTERN = re.compile(
    rb'<form action="/boss/start"[^>]*>.*?name="action_id" value="([^"]+)"',
    re.S,
)


class JourneyTestCase(unittest.TestCase):
    """Shared helpers for one complete, deterministic player journey."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.database = str(Path(self.tempdir.name) / "journey.sqlite3")
        self.ai_client = FakeGeminiClient()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "journey-only-secret",
                "LESSON_CLIENT": self.ai_client,
            }
        )
        self.client = self.app.test_client()
        self.boss_url = None
        self.victory_url = None

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

    def sessions(self):
        return self.rows("SELECT * FROM learning_sessions ORDER BY started_at, id")

    def most_recent_concepts(self, count=2):
        ordered = sorted(
            self.concepts(),
            key=lambda concept: (concept["last_missed_at"], concept["id"]),
            reverse=True,
        )
        return ordered[:count]

    # -- page helpers -----------------------------------------------------
    @staticmethod
    def action_id(page):
        match = ACTION_PATTERN.search(page.data)
        assert match is not None, "page carried no action_id"
        return match.group(1).decode()

    @staticmethod
    def boss_setup_id(page):
        match = BOSS_START_PATTERN.search(page.data)
        assert match is not None, "page carried no boss setup control"
        return match.group(1).decode()

    def current_run(self):
        with self.client.session_transaction() as browser_session:
            run_id = browser_session.get("run_id")
        return self.app.extensions["dejavu_runs"].get(run_id)

    def battle_encounter(self):
        return self.current_run()["battle"]

    def boss_encounter(self):
        return self.current_run()["boss"]

    # -- journey steps ----------------------------------------------------
    def enter_identity(self, name="Arjun"):
        return self.client.post("/identity", data={"display_name": name})

    def start_lesson(self, topic="DBMS Normalization"):
        response = self.client.post("/topic", data={"topic": topic})
        self.assertEqual(response.status_code, 303)
        lesson = self.client.get(response.location)
        self.assertEqual(lesson.status_code, 200)
        return lesson

    def start_battle(self, lesson):
        setup_id = self.action_id(lesson)
        response = self.client.post("/battle/start", data={"action_id": setup_id})
        self.assertEqual(response.status_code, 303)
        battle = self.client.get(response.location)
        self.assertEqual(battle.status_code, 200)
        return battle

    def complete_battle(self, page, *, wrong_count=0):
        """Answer the regular battle, missing the first ``wrong_count`` questions."""
        answered = 0
        while True:
            encounter = self.battle_encounter()
            if encounter["phase"] == "complete":
                return page
            self.assertEqual(encounter["phase"], "question")
            question = encounter["rounds"][encounter["round_index"]][
                encounter["question_index"]
            ]
            correct_index = question["correct_option_index"]
            if answered < wrong_count:
                selected = (correct_index + 1) % 4
                answered += 1
            else:
                selected = correct_index
            action_id = self.action_id(page)
            response = self.client.post(
                "/battle/answer",
                data={"action_id": action_id, "answer": str(selected)},
            )
            self.assertEqual(response.status_code, 303)
            page = self.client.get(response.location)
            transition_id = self.action_id(page)
            advanced = self.client.post(
                "/battle/advance", data={"action_id": transition_id}
            )
            self.assertEqual(advanced.status_code, 303)
            page = self.client.get(advanced.location)

    def start_boss(self, page):
        setup_id = self.boss_setup_id(page)
        response = self.client.post("/boss/start", data={"action_id": setup_id})
        self.assertEqual(response.status_code, 303)
        self.boss_url = response.location
        boss = self.client.get(response.location)
        self.assertEqual(boss.status_code, 200)
        return boss

    def answer_boss(self, page, *, correct):
        encounter = self.boss_encounter()
        question = encounter["questions"][encounter["question_index"]]
        correct_index = question["correct_option_index"]
        selected = correct_index if correct else (correct_index + 1) % 4
        action_id = self.action_id(page)
        response = self.client.post(
            "/boss/answer",
            data={"action_id": action_id, "answer": str(selected)},
        )
        self.assertEqual(response.status_code, 303)
        return action_id, response, self.client.get(response.location)

    def advance_boss(self, page):
        transition_id = self.action_id(page)
        response = self.client.post("/boss/advance", data={"action_id": transition_id})
        self.assertEqual(response.status_code, 303)
        return self.client.get(response.location)

    def play_boss(self, page, correct_flags):
        for correct in correct_flags:
            _, response, page = self.answer_boss(page, correct=correct)
            if "/boss/victory/" in response.location:
                # The victory ticket is single use and was already consumed
                # while rendering the page inside answer_boss.
                self.victory_url = response.location
                return page
            encounter = self.boss_encounter()
            if encounter["next_action"] == "next_question":
                page = self.advance_boss(page)
        return page


class TestJourneySteps(JourneyTestCase):
    """Part A: every step of the published journey, in order."""

    def test_step_1_first_visit_and_identity_entry(self):
        first = self.client.get("/")
        self.assertEqual(first.status_code, 302)
        self.assertTrue(first.headers["Location"].endswith("/identity"))

        page = self.client.get("/identity")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"IDENTITY NOT FOUND", page.data)

        blank = self.client.post("/identity", data={"display_name": "   "})
        self.assertEqual(blank.status_code, 400)
        profile = self.rows("SELECT * FROM player_profile")[0]
        self.assertIsNone(profile["display_name"])

        saved = self.enter_identity("Arjun")
        self.assertEqual(saved.status_code, 303)
        profile = self.rows("SELECT * FROM player_profile")[0]
        self.assertEqual(profile["display_name"], "Arjun")

        again = self.enter_identity("Someone Else")
        self.assertEqual(again.status_code, 303)
        profile = self.rows("SELECT * FROM player_profile")[0]
        self.assertEqual(profile["display_name"], "Arjun")

    def test_step_2_topic_download_and_three_card_lesson(self):
        self.enter_identity("Arjun")

        lesson = self.start_lesson("DBMS Normalization")

        self.assertEqual(lesson.data.count(b'class="lesson-card"'), 3)
        self.assertIn(b"DOWNLOAD COMPLETE / THREE CONCEPT CARDS", lesson.data)
        self.assertIn(b"INITIATE COMBAT", lesson.data)
        sessions = self.sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["topic"], "DBMS Normalization")
        self.assertEqual(sessions[0]["status"], "in_progress")
        self.assertEqual(sessions[0]["origin"], "player")
        self.assertEqual(self.events(), [])

    def test_step_3_regular_battle_completion_saves_missed_concepts(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())

        page = self.complete_battle(battle, wrong_count=3)

        self.assertIn(b"REGULAR ENCOUNTER COMPLETE", page.data)
        self.assertIn(b"FACE THE FINAL BOSS", page.data)
        self.assertEqual(len(self.events()), 3)
        self.assertEqual(len(self.concepts()), 3)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")

    def test_step_4_starting_the_final_boss(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=1)

        boss = self.start_boss(page)

        self.assertIn(b"FINAL BOSS / 5-QUESTION ENCOUNTER", boss.data)
        self.assertIn(b"QUESTION 1 / 5", boss.data)
        self.assertIn(b"100 / 100 HP", boss.data)
        self.assertEqual(len(self.boss_encounter()["questions"]), 5)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")

    def test_step_5_boss_generation_uses_actual_saved_weak_concepts(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=3)
        saved_concepts = self.concepts()
        self.assertEqual(len(saved_concepts), 3)

        self.start_boss(page)

        encounter = self.boss_encounter()
        weak_questions = [
            question
            for question in encounter["questions"]
            if question["kind"] == "weak_spot"
        ]
        self.assertEqual(len(weak_questions), 3)
        self.assertEqual(
            {question["weak_concept_id"] for question in weak_questions},
            {concept["id"] for concept in saved_concepts},
        )
        for question in weak_questions:
            self.assertTrue(question["mistake_event_id"])
        self.assertEqual(len(self.ai_client.boss_weak_calls), 1)
        self.assertEqual(len(self.ai_client.boss_adaptive_calls), 1)
        for candidate in self.ai_client.boss_weak_calls[0]["candidates"]:
            self.assertNotIn("weak_concept_id", candidate)
            self.assertNotIn("mistake_event_id", candidate)

    def test_step_6_weak_spot_markers_use_trusted_saved_labels(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=3)
        saved_concepts = {concept["id"]: concept for concept in self.concepts()}

        boss = self.start_boss(page)

        self.assertIn(b"WEAK SPOT DETECTED", boss.data)
        self.assertIn(b"SAVED WEAKNESS", boss.data)
        weak_questions = [
            question
            for question in self.boss_encounter()["questions"]
            if question["kind"] == "weak_spot"
        ]
        self.assertEqual(len(weak_questions), 3)
        for question in weak_questions:
            trusted = saved_concepts[question["weak_concept_id"]]
            self.assertEqual(question["concept_label"], trusted["label"])
            self.assertEqual(question["concept_explanation"], trusted["explanation"])
        # The page shows the marker of the question that is currently open.
        current = self.boss_encounter()["questions"][0]
        trusted = saved_concepts[current["weak_concept_id"]]
        self.assertIn(
            f"PREVIOUSLY MISSED: <strong>{trusted['label']}</strong>".encode(),
            boss.data,
        )
        self.assertIn(trusted["explanation"].encode(), boss.data)
        self.assertNotIn(b'name="weak_concept_id"', boss.data)
        self.assertNotIn(b'name="mistake_event_id"', boss.data)

    def test_step_7_incorrect_boss_answer_is_persisted_before_hp_changes(self):
        from dejavu.services.battle import apply_boss_answer

        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=2)
        boss = self.start_boss(page)
        events_before = len(self.events())
        question = self.boss_encounter()["questions"][0]

        observed = {}

        def spy(encounter, result):
            observed["events"] = len(self.events())
            observed["player_hp"] = encounter["player_hp"]
            return apply_boss_answer(encounter, result)

        with patch("dejavu.routes.apply_boss_answer", side_effect=spy):
            _, _, result_page = self.answer_boss(boss, correct=False)

        # The mistake row is already committed when the health change happens.
        self.assertEqual(observed["events"], events_before + 1)
        self.assertEqual(observed["player_hp"], 100)

        event = self.events()[-1]
        self.assertEqual(event["question_kind"], "boss")
        self.assertEqual(event["weak_concept_id"], question["weak_concept_id"])
        self.assertNotEqual(event["chosen_answer"], event["correct_answer"])
        self.assertEqual(self.boss_encounter()["player_hp"], 80)
        self.assertIn(b"INCORRECT / OPERATOR LOSES 20 HP", result_page.data)

    def test_step_8_victory_completes_the_session_correctly(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=1)
        boss = self.start_boss(page)

        victory = self.play_boss(boss, [True] * 4)

        self.assertIn(b"FINAL BOSS DEFEATED", victory.data)
        self.assertIn(b"Victory.", victory.data)
        self.assertIn(b"0 / 100 HP", victory.data)
        sessions = self.sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["status"], "completed")
        self.assertIsNotNone(sessions[0]["ended_at"])
        self.assertIsNone(self.current_run())

    def test_step_9_defeat_retry_keeps_the_same_questions_and_history(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=1)
        boss = self.start_boss(page)
        questions_before = copy.deepcopy(self.boss_encounter()["questions"])

        defeat = self.play_boss(boss, [False] * 5)

        self.assertIn(b"The final encounter is lost.", defeat.data)
        self.assertIn(b"RETRY BOSS", defeat.data)
        events_before = len(self.events())
        self.assertEqual(events_before, 6)
        self.assertEqual(self.boss_encounter()["player_hp"], 0)

        transition_id = self.action_id(defeat)
        retried = self.client.post("/boss/retry", data={"action_id": transition_id})
        self.assertEqual(retried.status_code, 303)
        retry_page = self.client.get(retried.location)

        encounter = self.boss_encounter()
        self.assertEqual(encounter["player_hp"], 100)
        self.assertEqual(encounter["boss_hp"], 100)
        self.assertEqual(encounter["question_index"], 0)
        self.assertEqual(encounter["questions"], questions_before)
        self.assertEqual(len(self.events()), events_before)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")
        self.assertIn(b"100 / 100 HP", retry_page.data)

    def test_step_10_return_to_construct_keeps_terminal_statuses(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=1)
        boss = self.start_boss(page)
        defeat = self.play_boss(boss, [False] * 5)

        transition_id = self.action_id(defeat)
        returned = self.client.post("/boss/return", data={"action_id": transition_id})
        self.assertEqual(returned.status_code, 303)
        construct = self.client.get(returned.location)
        self.assertEqual(construct.status_code, 200)
        self.assertIn(b"Enter a topic.", construct.data)
        self.assertEqual(self.sessions()[0]["status"], "defeated")

        # Re-visiting Construct or the mentor must not rewrite the status.
        self.client.get("/construct")
        self.client.get("/")
        self.assertEqual(self.sessions()[0]["status"], "defeated")

        # A new topic opens a new session and leaves the terminal one alone.
        self.start_lesson("Process Scheduling")
        statuses = [session["status"] for session in self.sessions()]
        self.assertEqual(statuses, ["defeated", "in_progress"])

    def test_step_11_mentor_shows_the_saved_session_and_weaknesses(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=1)
        boss = self.start_boss(page)
        defeat = self.play_boss(boss, [False] * 5)

        transition_id = self.action_id(defeat)
        returned = self.client.post("/boss/return", data={"action_id": transition_id})
        self.client.get(returned.location)

        mentor = self.client.get("/")

        self.assertEqual(mentor.status_code, 200)
        self.assertIn(b"You have been here before.", mentor.data)
        self.assertIn(b"DBMS Normalization", mentor.data)
        self.assertIn(b"PRIMARY WEAKNESS", mentor.data)
        self.assertIn(b"LAST SESSION", mentor.data)
        expected = self.most_recent_concepts(2)
        self.assertEqual(len(expected), 2)
        self.assertEqual(mentor.data.count(b'class="weakness-card'), 2)
        for concept in expected:
            self.assertIn(concept["label"].encode(), mentor.data)
            self.assertIn(concept["explanation"].encode(), mentor.data)

    def test_journey_from_identity_to_mentor_after_a_win(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=2)
        boss = self.start_boss(page)
        victory = self.play_boss(boss, [True] * 4)
        self.assertIn(b"Victory.", victory.data)

        construct = self.client.get("/construct")
        self.assertEqual(construct.status_code, 200)
        self.assertIn(b"Enter a topic.", construct.data)
        self.assertEqual(self.sessions()[0]["status"], "completed")

        mentor = self.client.get("/")
        self.assertEqual(mentor.status_code, 200)
        self.assertIn(b"You have been here before.", mentor.data)
        self.assertIn(b"DBMS Normalization", mentor.data)
        self.assertIn(b"PRIMARY WEAKNESS", mentor.data)
        self.assertEqual(len(self.concepts()), 2)


class TestJourneyFailureHandling(JourneyTestCase):
    """Part B: failure handling that the focused tests do not already prove."""

    def _boss_with_saved_weakness(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=1)
        return self.start_boss(page)

    def test_invalid_page_ticket_cannot_resume_the_run(self):
        self._boss_with_saved_weakness()
        events_before = self.events()

        response = self.client.get("/boss/not-a-valid-ticket")

        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/construct"))
        self.assertEqual(self.events(), events_before)
        self.assertEqual(self.sessions()[0]["status"], "abandoned")
        self.assertIsNone(self.current_run())

    def test_expired_page_ticket_cannot_resume_the_run(self):
        self._boss_with_saved_weakness()
        events_before = self.events()
        ticket_url = self.boss_url

        later = time.time() + 400
        with patch("time.time", return_value=later):
            response = self.client.get(ticket_url)

        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/construct"))
        self.assertEqual(self.events(), events_before)
        self.assertEqual(self.sessions()[0]["status"], "abandoned")
        self.assertIsNone(self.current_run())

    def test_stale_transition_id_cannot_change_the_boss_state(self):
        self._boss_with_saved_weakness()
        encounter_before = copy.deepcopy(self.boss_encounter())
        events_before = self.events()

        stale = self.client.post(
            "/boss/advance", data={"action_id": "stale-transition-id"}
        )

        self.assertEqual(stale.status_code, 303)
        self.assertTrue(stale.headers["Location"].endswith("/construct"))
        encounter_after = self.boss_encounter()
        self.assertEqual(encounter_after["phase"], encounter_before["phase"])
        self.assertEqual(
            encounter_after["attempt_id"], encounter_before["attempt_id"]
        )
        self.assertEqual(encounter_after["player_hp"], encounter_before["player_hp"])
        self.assertEqual(encounter_after["boss_hp"], encounter_before["boss_hp"])
        self.assertEqual(self.events(), events_before)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")

    def test_stale_transition_id_cannot_return_or_retry_the_boss(self):
        boss = self._boss_with_saved_weakness()
        defeat = self.play_boss(boss, [False] * 5)
        self.assertIn(b"RETRY BOSS", defeat.data)
        events_before = self.events()

        returned = self.client.post(
            "/boss/return", data={"action_id": "stale-transition-id"}
        )
        retried = self.client.post(
            "/boss/retry", data={"action_id": "stale-transition-id"}
        )

        self.assertEqual(returned.status_code, 303)
        self.assertEqual(retried.status_code, 303)
        self.assertEqual(self.events(), events_before)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")
        self.assertEqual(self.boss_encounter()["player_hp"], 0)

    def test_expired_ticket_never_rewrites_a_terminal_status(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=1)
        boss = self.start_boss(page)
        victory = self.play_boss(boss, [True] * 4)
        self.assertIn(b"Victory.", victory.data)
        self.assertEqual(self.sessions()[0]["status"], "completed")
        events_before = self.events()

        later = time.time() + 400
        with patch("time.time", return_value=later):
            expired = self.client.get(self.victory_url)

        self.assertEqual(expired.status_code, 303)
        self.assertTrue(expired.headers["Location"].endswith("/construct"))
        self.assertEqual(self.sessions()[0]["status"], "completed")
        self.assertEqual(self.events(), events_before)

    def test_expired_return_ticket_never_rewrites_a_defeated_status(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=1)
        boss = self.start_boss(page)
        defeat = self.play_boss(boss, [False] * 5)

        transition_id = self.action_id(defeat)
        returned = self.client.post("/boss/return", data={"action_id": transition_id})
        self.assertEqual(returned.status_code, 303)
        self.assertEqual(self.sessions()[0]["status"], "defeated")
        events_before = self.events()

        later = time.time() + 400
        with patch("time.time", return_value=later):
            expired = self.client.get(returned.location)

        self.assertEqual(expired.status_code, 200)
        self.assertIn(b"Enter a topic.", expired.data)
        self.assertEqual(self.sessions()[0]["status"], "defeated")
        self.assertEqual(self.events(), events_before)

    def test_boss_setup_provider_failure_keeps_saved_progress(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        page = self.complete_battle(battle, wrong_count=1)
        setup_id = self.boss_setup_id(page)

        self.ai_client.boss_weak_result = LessonProviderError("provider offline")
        failed = self.client.post("/boss/start", data={"action_id": setup_id})

        self.assertEqual(failed.status_code, 200)
        self.assertIn(b"Boss generation failed", failed.data)
        self.assertNotIn("boss", self.current_run())
        self.assertEqual(self.sessions()[0]["status"], "in_progress")
        self.assertEqual(len(self.events()), 1)

        self.ai_client.boss_weak_result = None
        retried = self.client.post("/boss/start", data={"action_id": setup_id})
        self.assertEqual(retried.status_code, 303)
        boss = self.client.get(retried.location)
        self.assertEqual(boss.status_code, 200)
        self.assertEqual(len(self.boss_encounter()["questions"]), 5)

    def test_regular_battle_persistence_failure_keeps_question_and_health_pending(self):
        self.enter_identity("Arjun")
        battle = self.start_battle(self.start_lesson())
        question = self.battle_encounter()["rounds"][0][0]
        wrong_index = (question["correct_option_index"] + 1) % 4
        action_id = self.action_id(battle)

        with patch(
            "dejavu.routes.record_mistake",
            side_effect=sqlite3.Error("database unavailable"),
        ):
            failed = self.client.post(
                "/battle/answer",
                data={"action_id": action_id, "answer": str(wrong_index)},
            )

        self.assertEqual(failed.status_code, 200)
        self.assertIn(b"could not be saved", failed.data)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.concepts(), [])
        encounter = self.battle_encounter()
        self.assertEqual(encounter["player_hp"], 100)
        self.assertEqual(encounter["phase"], "question")
        self.assertEqual(encounter["question_index"], 0)

        retried = self.client.post(
            "/battle/answer",
            data={"action_id": action_id, "answer": str(wrong_index)},
        )
        self.assertEqual(retried.status_code, 303)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.battle_encounter()["player_hp"], 80)

    def test_seeded_demo_history_uses_the_same_retrieval_and_boss_path(self):
        seed_demo(self.database)
        self.enter_identity("Arjun")

        mentor = self.client.get("/")
        self.assertEqual(mentor.status_code, 200)
        self.assertIn(b"SEEDED DEMO HISTORY", mentor.data)
        seeded_labels = {
            "Functional dependencies",
            "Third normal form",
            "Candidate keys",
        }

        battle = self.start_battle(self.start_lesson("DBMS Normalization"))
        page = self.complete_battle(battle, wrong_count=0)
        self.assertEqual(len(self.events()), 4)

        boss = self.start_boss(page)

        encounter = self.boss_encounter()
        weak_questions = [
            question
            for question in encounter["questions"]
            if question["kind"] == "weak_spot"
        ]
        self.assertEqual(len(weak_questions), 3)
        self.assertEqual(
            {question["concept_label"] for question in weak_questions},
            seeded_labels,
        )
        for question in weak_questions:
            self.assertTrue(question["mistake_event_id"])
        self.assertIn(b"WEAK SPOT DETECTED", boss.data)
        current = encounter["questions"][0]
        self.assertEqual(current["kind"], "weak_spot")
        self.assertIn(current["concept_label"].encode(), boss.data)
        self.assertEqual(len(self.ai_client.boss_weak_calls), 1)
        self.assertEqual(len(self.ai_client.boss_adaptive_calls), 1)


if __name__ == "__main__":
    unittest.main()
