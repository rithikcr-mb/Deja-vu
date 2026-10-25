"""Guards for the inline CSS that the Jinja templates generate.

The templates must template a CSS value, so the template source is never
valid CSS on its own and editors report false positives there. These tests
check the rendered output instead, which is what a browser actually receives.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from dejavu import create_app
from dejavu.services.ai_client import FakeGeminiClient


ACTION_PATTERN = re.compile(rb'name="action_id" value="([^"]+)"')
BOSS_START_PATTERN = re.compile(
    rb'<form action="/boss/start"[^>]*>.*?name="action_id" value="([^"]+)"', re.S
)
CSS_DECLARATION = re.compile(r"^([a-z-]+)\s*:\s*(.+)$")
CSS_PERCENTAGE = re.compile(r"^-?[0-9]+(\.[0-9]+)?%$")


class StyleCollector(HTMLParser):
    """Collects inline style attributes and checks tag balance."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.styles: list[str] = []
        self.stack: list[str] = []
        self.unbalanced: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in ("meta", "link", "br", "hr", "img", "input", "source"):
            self.stack.append(tag)
        for name, value in attrs:
            if name == "style" and value is not None:
                self.styles.append(value)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.unbalanced.append(tag)


def assert_valid_inline_css(case: unittest.TestCase, styles: list[str]) -> None:
    for style in styles:
        declarations = [part.strip() for part in style.split(";") if part.strip()]
        case.assertTrue(declarations, f"empty inline style: {style!r}")
        for declaration in declarations:
            match = CSS_DECLARATION.match(declaration)
            case.assertIsNotNone(
                match, f"not a CSS declaration: {declaration!r} in {style!r}"
            )
            property_name, value = match.group(1), match.group(2).strip()
            case.assertEqual(property_name, "width", f"unexpected property in {style!r}")
            case.assertRegex(
                value, CSS_PERCENTAGE, f"unexpected value in {style!r}"
            )


class TestRenderedStyles(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.database = str(Path(self.tempdir.name) / "styles.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.database,
                "SECRET_KEY": "styles-only-secret",
                "LESSON_CLIENT": FakeGeminiClient(),
            }
        )
        self.client = self.app.test_client()
        self.client.post(
            "/identity",
            data={"display_name": "Arjun"},
            follow_redirects=True,
        )

    def play_battle(self, *, miss_first=False):
        lesson = self.client.post(
            "/topic", data={"topic": "DBMS Normalization"}, follow_redirects=True
        )
        setup = ACTION_PATTERN.search(lesson.data).group(1).decode()
        page = self.client.get(
            self.client.post("/battle/start", data={"action_id": setup}).location
        )
        answered = 0
        for _ in range(40):
            with self.client.session_transaction() as browser_session:
                run_id = browser_session.get("run_id")
            encounter = self.app.extensions["dejavu_runs"][run_id]["battle"]
            if encounter["phase"] == "complete":
                break
            if encounter["phase"] == "answered":
                action = ACTION_PATTERN.search(page.data).group(1).decode()
                page = self.client.get(
                    self.client.post("/battle/advance", data={"action_id": action}).location
                )
                continue
            question = encounter["rounds"][encounter["round_index"]][
                encounter["question_index"]
            ]
            selected = str(question["correct_option_index"])
            if miss_first and answered == 0:
                selected = str((question["correct_option_index"] + 1) % 4)
            answered += 1
            action = ACTION_PATTERN.search(page.data).group(1).decode()
            page = self.client.get(
                self.client.post(
                    "/battle/answer",
                    data={"action_id": action, "answer": selected},
                ).location
            )
        return page

    def test_battle_screen_renders_valid_inline_css(self):
        page = self.play_battle()

        html = page.data.decode("utf-8")
        self.assertNotIn("{{", html)
        self.assertNotIn("{%", html)

        parser = StyleCollector()
        parser.feed(html)
        self.assertTrue(parser.styles, "the battle screen renders inline styles")
        assert_valid_inline_css(self, parser.styles)
        self.assertEqual(parser.unbalanced, [])
        self.assertEqual(parser.stack, [])

    def test_boss_screen_renders_valid_inline_css(self):
        page = self.play_battle(miss_first=True)
        boss_setup = BOSS_START_PATTERN.search(page.data).group(1).decode()
        boss = self.client.get(
            self.client.post("/boss/start", data={"action_id": boss_setup}).location
        )

        html = boss.data.decode("utf-8")
        self.assertNotIn("{{", html)
        self.assertNotIn("{%", html)
        self.assertIn("WEAK SPOT DETECTED", html)

        parser = StyleCollector()
        parser.feed(html)
        # the progress fill plus the two health bars
        self.assertEqual(len(parser.styles), 3)
        assert_valid_inline_css(self, parser.styles)
        self.assertEqual(parser.unbalanced, [])
        self.assertEqual(parser.stack, [])

    def test_boss_health_bars_track_the_real_health_values(self):
        page = self.play_battle(miss_first=True)
        boss_setup = BOSS_START_PATTERN.search(page.data).group(1).decode()
        boss = self.client.get(
            self.client.post("/boss/start", data={"action_id": boss_setup}).location
        )

        html = boss.data.decode("utf-8")
        parser = StyleCollector()
        parser.feed(html)
        # question 1 of 5 -> 20%, both health pools start at 100%
        self.assertIn("width: 20.0%", parser.styles)
        self.assertIn("width: 100%", parser.styles)
        self.assertNotIn("{{", parser.styles[0])


if __name__ == "__main__":
    unittest.main()
