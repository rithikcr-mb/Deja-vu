from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from dejavu import create_app
from dejavu.db.connection import connect
from dejavu.services.ai_client import FakeGeminiClient, LessonProviderError


class TestLessonRoutes(unittest.TestCase):
    def setUp(self):
        instance_dir = Path(__file__).resolve().parents[1] / "instance"
        instance_dir.mkdir(parents=True, exist_ok=True)
        self.database = str(instance_dir / f"test-{uuid4().hex}.sqlite3")
        self.lesson_client = FakeGeminiClient()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "test-only-secret",
                "LESSON_CLIENT": self.lesson_client,
            }
        )
        self.app.extensions["test_lesson_client"] = self.lesson_client
        self.client = self.app.test_client()

    def set_name(self, name="Arjun"):
        return self.client.post(
            "/identity", data={"display_name": name}, follow_redirects=True
        )

    def sessions(self):
        with connect(self.database) as connection:
            return [
                dict(row)
                for row in connection.execute("SELECT * FROM learning_sessions")
            ]

    def test_identity_is_saved_once_and_returning_user_is_not_prompted(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/identity", response.location)
        response = self.set_name()
        self.assertIn(b"WELCOME TO THE CONSTRUCT, Arjun.", response.data)
        again = self.client.post(
            "/identity", data={"display_name": "Changed"}, follow_redirects=True
        )
        self.assertNotIn(b"IDENTITY NOT FOUND", again.data)
        self.assertIn(b"OPERATOR: Arjun", again.data)

    def test_identity_rejects_blank_name(self):
        response = self.client.post("/identity", data={"display_name": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Enter a name to continue", response.data)

    def test_valid_lesson_creates_one_in_progress_session_and_shows_topic(self):
        self.set_name()
        response = self.client.post(
            "/topic", data={"topic": "  Process Scheduling  "}, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<h1 id="lesson-title">Process Scheduling</h1>', response.data)
        self.assertEqual(response.data.count(b'class="lesson-card"'), 3)
        self.assertEqual(self.lesson_client.calls, ["Process Scheduling"])
        self.assertEqual(
            [(row["topic"], row["status"]) for row in self.sessions()],
            [("Process Scheduling", "in_progress")],
        )

    def test_narrow_or_unfamiliar_topic_is_sent_for_generation(self):
        self.set_name()
        topic = "An unfamiliar advanced scheduling algorithm"
        response = self.client.post(
            "/topic", data={"topic": topic}, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(topic.encode(), response.data)
        self.assertEqual(self.lesson_client.calls, [topic])

    def test_empty_topic_skips_client_and_keeps_construct(self):
        self.set_name()
        response = self.client.post("/topic", data={"topic": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Enter a topic to begin your download.", response.data)
        self.assertEqual(self.lesson_client.calls, [])
        self.assertIn(b'name="topic" type="text" value="  "', response.data)

    def test_unlearnable_topic_preserves_text_and_creates_no_session(self):
        self.set_name()
        self.app.config["LESSON_CLIENT"] = FakeGeminiClient(
            {
                "outcome": "unlearnable_topic",
                "title": None,
                "cards": [],
                "reason_code": "no_teachable_subject",
            }
        )
        response = self.client.post(
            "/topic", data={"topic": "???"}, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"couldn&#39;t identify a learnable topic", response.data)
        self.assertIn(b'value="???"', response.data)
        self.assertEqual(self.sessions(), [])

    def test_provider_and_malformed_output_are_recoverable_without_session(self):
        self.set_name()
        self.app.config["LESSON_CLIENT"] = FakeGeminiClient(
            LessonProviderError("offline")
        )
        provider = self.client.post(
            "/topic", data={"topic": "DBMS"}, follow_redirects=True
        )
        self.assertIn(
            b"Download failed. Your lesson wasn&#39;t created. Try again.", provider.data
        )
        self.assertIn(b'value="DBMS"', provider.data)

        self.app.config["LESSON_CLIENT"] = FakeGeminiClient("not-json")
        malformed = self.client.post(
            "/topic", data={"topic": "Operating Systems"}, follow_redirects=True
        )
        self.assertIn(
            b"Download failed. Your lesson wasn&#39;t created. Try again.", malformed.data
        )
        self.assertIn(b'value="Operating Systems"', malformed.data)
        self.assertEqual(self.sessions(), [])

    def test_live_provider_is_disabled_by_default_without_calling_gemini(self):
        self.set_name()
        self.app.config["LESSON_CLIENT"] = None
        self.app.config["DEJAVU_FAKE_AI"] = False
        self.app.config["ENABLE_LIVE_GEMINI"] = False
        response = self.client.post(
            "/topic", data={"topic": "Databases"}, follow_redirects=True
        )
        self.assertIn(b"Live Gemini generation is disabled", response.data)
        self.assertIn(b'value="Databases"', response.data)
        self.assertEqual(self.sessions(), [])

    def test_missing_key_has_setup_error_when_live_generation_is_enabled(self):
        self.set_name()
        self.app.config["LESSON_CLIENT"] = None
        self.app.config["DEJAVU_FAKE_AI"] = False
        self.app.config["ENABLE_LIVE_GEMINI"] = True
        self.app.config["GEMINI_API_KEY"] = ""
        response = self.client.post(
            "/topic", data={"topic": "Databases"}, follow_redirects=True
        )
        self.assertIn(b"GEMINI_API_KEY is not configured", response.data)
        self.assertEqual(self.sessions(), [])

    def test_replayed_lesson_ticket_abandons_only_in_progress_session(self):
        self.set_name()
        response = self.client.post("/topic", data={"topic": "CPU Scheduling"})
        lesson_url = response.location
        first = self.client.get(lesson_url)
        self.assertEqual(first.status_code, 200)
        replay = self.client.get(lesson_url, follow_redirects=True)
        self.assertEqual(replay.status_code, 200)
        self.assertIn(b"Enter a topic", replay.data)
        sessions = self.sessions()
        self.assertEqual(sessions[0]["status"], "abandoned")
        self.assertTrue(sessions[0]["ended_at"])

    def test_server_restart_abandons_old_in_progress_session(self):
        with connect(self.database) as connection:
            connection.execute(
                """INSERT INTO learning_sessions
                   (id, topic, started_at, status, origin)
                   VALUES ('run-1', 'Databases', '2026-10-18T00:00:00Z',
                           'in_progress', 'player')"""
            )
        create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "test-only-secret",
            }
        )
        self.assertEqual(self.sessions()[0]["status"], "abandoned")


if __name__ == "__main__":
    unittest.main()
