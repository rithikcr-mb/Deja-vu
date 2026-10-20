from __future__ import annotations

import re
import unittest
from pathlib import Path
from uuid import uuid4

from dejavu import create_app
from dejavu.db.connection import connect
from dejavu.services.ai_client import FakeGeminiClient, LessonProviderError


ACTION_PATTERN = re.compile(rb'name="action_id" value="([^"]+)"')


class TestBattleRoutes(unittest.TestCase):
    def setUp(self):
        instance_dir = Path(__file__).resolve().parents[1] / "instance"
        instance_dir.mkdir(parents=True, exist_ok=True)
        self.database = str(instance_dir / f"battle-{uuid4().hex}.sqlite3")
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
        self.client.post("/identity", data={"display_name": "Arjun"}, follow_redirects=True)

    def events(self):
        with connect(self.database) as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM mistake_events")]

    def sessions(self):
        with connect(self.database) as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM learning_sessions")]

    def start_battle(self):
        lesson = self.client.post(
            "/topic", data={"topic": "Process Scheduling"}, follow_redirects=True
        )
        setup_id = ACTION_PATTERN.search(lesson.data).group(1).decode()
        response = self.client.post("/battle/start", data={"action_id": setup_id})
        self.assertEqual(response.status_code, 303)
        battle = self.client.get(response.location)
        self.assertEqual(battle.status_code, 200)
        return battle

    def answer(self, battle_page, answer_index):
        if b'name="answer"' not in battle_page.data:
            transition_id = ACTION_PATTERN.search(battle_page.data).group(1).decode()
            advance = self.client.post("/battle/advance", data={"action_id": transition_id})
            battle_page = self.client.get(advance.location)
        action_id = ACTION_PATTERN.search(battle_page.data).group(1).decode()
        response = self.client.post(
            "/battle/answer",
            data={"action_id": action_id, "answer": str(answer_index)},
        )
        self.assertEqual(response.status_code, 303)
        return action_id, response, self.client.get(response.location)

    def test_battle_setup_validates_twelve_questions_before_combat(self):
        battle = self.start_battle()
        self.assertEqual(self.ai_client.battle_calls, ["Process Scheduling"])
        self.assertIn(b"QUESTION 1 OF 4", battle.data)
        self.assertIn(b"100 / 100 HP", battle.data)
        self.assertIn(b"75 / 75 HP", battle.data)
        self.assertEqual(self.events(), [])

    def test_wrong_answer_is_saved_once_before_feedback_and_health_change(self):
        battle = self.start_battle()
        action_id = ACTION_PATTERN.search(battle.data).group(1).decode()
        first = self.client.post(
            "/battle/answer", data={"action_id": action_id, "answer": "1"}
        )
        repeated = self.client.post(
            "/battle/answer", data={"action_id": action_id, "answer": "1"}
        )
        self.assertEqual(repeated.location, first.location)
        result = self.client.get(first.location)
        self.assertIn(b"INCORRECT / OPERATOR LOSES 20 HP", result.data)
        self.assertIn(b"80 / 100 HP", result.data)
        self.assertIn(b"The basic idea behind Process Scheduling.", result.data)
        self.assertEqual(len(self.events()), 1)
        self.assertNotEqual(
            self.events()[0]["chosen_answer"], self.events()[0]["correct_answer"]
        )
        self.assertEqual(self.events()[0]["origin"], "player")
        with connect(self.database) as connection:
            concept_count = connection.execute("SELECT COUNT(*) FROM weak_concepts").fetchone()[0]
        self.assertEqual(concept_count, 1)

    def test_repeated_misses_share_a_concept_without_merging_events(self):
        battle = self.start_battle()
        _, _, battle = self.answer(battle, 1)
        _, _, battle = self.answer(battle, 1)
        _, _, battle = self.answer(battle, 2)
        _, _, battle = self.answer(battle, 0)
        events = self.events()
        self.assertEqual(len(events), 2)
        self.assertEqual(len({event["question_instance_id"] for event in events}), 2)
        self.assertEqual(len({event["weak_concept_id"] for event in events}), 1)

    def test_correct_answers_reduce_enemy_health_and_end_round_early(self):
        battle = self.start_battle()
        for question_index in range(3):
            _, _, battle = self.answer(battle, question_index)
        self.assertIn(b"0 / 75 HP", battle.data)
        self.assertIn(b"CONTINUE", battle.data)
        transition_id = ACTION_PATTERN.search(battle.data).group(1).decode()
        response = self.client.post("/battle/advance", data={"action_id": transition_id})
        battle = self.client.get(response.location)
        self.assertIn(b"ROUND 2 OF 3", battle.data)
        self.assertIn(b"75 / 75 HP", battle.data)

    def test_battle_setup_failure_keeps_lesson_and_allows_retry(self):
        self.ai_client.battle_result = LessonProviderError("provider unavailable")
        lesson = self.client.post(
            "/topic", data={"topic": "Operating Systems"}, follow_redirects=True
        )
        setup_id = ACTION_PATTERN.search(lesson.data).group(1).decode()
        failed = self.client.post("/battle/start", data={"action_id": setup_id})
        self.assertEqual(failed.status_code, 200)
        self.assertIn(b"Battle setup failed", failed.data)
        self.assertIn(b"lesson-title", failed.data)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")
        self.assertEqual(self.events(), [])

    def test_defeat_retry_preserves_mistakes_and_restores_round_start_health(self):
        battle = self.start_battle()
        for question_index in range(4):
            _, _, battle = self.answer(battle, (question_index + 1) % 4)
        transition_id = ACTION_PATTERN.search(battle.data).group(1).decode()
        advanced = self.client.post("/battle/advance", data={"action_id": transition_id})
        battle = self.client.get(advanced.location)
        _, _, battle = self.answer(battle, 2)
        self.assertIn(b"Operator health reached zero", battle.data)
        event_count = len(self.events())
        retry_id = ACTION_PATTERN.search(battle.data).group(1).decode()
        retried = self.client.post("/battle/retry", data={"action_id": retry_id})
        battle = self.client.get(retried.location)
        self.assertIn(b"20 / 100 HP", battle.data)
        self.assertEqual(len(self.events()), event_count)
        self.assertEqual(self.sessions()[0]["status"], "in_progress")

    def test_returning_from_defeat_finalizes_session_without_deleting_events(self):
        battle = self.start_battle()
        for question_index in range(4):
            _, _, battle = self.answer(battle, (question_index + 1) % 4)
        transition_id = ACTION_PATTERN.search(battle.data).group(1).decode()
        advanced = self.client.post("/battle/advance", data={"action_id": transition_id})
        battle = self.client.get(advanced.location)
        _, _, battle = self.answer(battle, 2)
        return_id = ACTION_PATTERN.search(battle.data).group(1).decode()
        returned = self.client.post("/battle/return", data={"action_id": return_id})
        construct = self.client.get(returned.location)
        self.assertIn(b"Enter a topic.", construct.data)
        self.assertEqual(self.sessions()[0]["status"], "defeated")
        self.assertEqual(len(self.events()), 5)

    def test_server_restart_abandons_run_but_keeps_mistake_history(self):
        battle = self.start_battle()
        self.answer(battle, 1)
        self.assertEqual(len(self.events()), 1)
        create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "test-only-secret",
            }
        )
        self.assertEqual(self.sessions()[0]["status"], "abandoned")
        self.assertEqual(len(self.events()), 1)


if __name__ == "__main__":
    unittest.main()
