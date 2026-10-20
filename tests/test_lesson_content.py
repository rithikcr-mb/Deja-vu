from __future__ import annotations

import unittest

from dejavu.services.ai_client import FakeGeminiClient
from dejavu.services.content import InvalidLessonContent, validate_lesson_result


def valid_result():
    return FakeGeminiClient().generate_lesson("Process Scheduling")


class TestLessonContent(unittest.TestCase):
    def test_accepts_exactly_three_distinct_lesson_roles(self):
        result = validate_lesson_result(valid_result())
        self.assertEqual(result.outcome, "lesson")
        self.assertEqual(len(result.cards), 3)
        self.assertEqual(
            {card.role for card in result.cards},
            {"core_idea", "how_it_works", "practical_example"},
        )

    def test_rejects_missing_card_and_repeated_role(self):
        result = valid_result()
        with self.assertRaises(InvalidLessonContent):
            validate_lesson_result({**result, "cards": result["cards"][:2]})
        repeated = [*result["cards"]]
        repeated[2] = {**repeated[2], "role": "how_it_works"}
        with self.assertRaises(InvalidLessonContent):
            validate_lesson_result({**result, "cards": repeated})

    def test_accepts_well_formed_unlearnable_result_as_distinct_outcome(self):
        result = validate_lesson_result(
            {
                "outcome": "unlearnable_topic",
                "title": None,
                "cards": [],
                "reason_code": "no_teachable_subject",
            }
        )
        self.assertEqual(result.outcome, "unlearnable_topic")

    def test_rejects_malformed_or_semantically_invalid_result(self):
        valid = valid_result()
        invalid_results = [
            "not-json",
            {
                "outcome": "unlearnable_topic",
                "title": "Oops",
                "cards": [],
                "reason_code": "no_teachable_subject",
            },
            {"outcome": "lesson", "title": "Lesson", "cards": [], "reason_code": None},
            {**valid, "unexpected": "field"},
            {
                **valid,
                "cards": [
                    {**valid["cards"][0], "body": "  "},
                    *valid["cards"][1:],
                ],
            },
        ]
        for result in invalid_results:
            with self.subTest(result=result):
                with self.assertRaises(InvalidLessonContent):
                    validate_lesson_result(result)

    def test_rejects_repeated_headings(self):
        result = valid_result()
        cards = [*result["cards"]]
        cards[1] = {**cards[1], "heading": cards[0]["heading"]}
        with self.assertRaises(InvalidLessonContent):
            validate_lesson_result({**result, "cards": cards})


if __name__ == "__main__":
    unittest.main()
