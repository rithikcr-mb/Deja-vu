from __future__ import annotations

import json
import unittest

from dejavu.services.ai_client import FakeGeminiClient, LessonProviderError
from dejavu.services.content import (
    BossCandidate,
    InvalidBossContent,
    build_boss_candidates,
    generate_boss_set,
)

LESSON_CARDS = [
    {
        "heading": "Core idea",
        "body": "The first lesson idea.",
        "concept_label": "Lesson concept 1",
        "concept_explanation": "The first lesson explanation.",
    },
    {
        "heading": "How it works",
        "body": "The second lesson idea.",
        "concept_label": "Lesson concept 2",
        "concept_explanation": "The second lesson explanation.",
    },
    {
        "heading": "Practical example",
        "body": "The third lesson idea.",
        "concept_label": "Lesson concept 3",
        "concept_explanation": "The third lesson explanation.",
    },
]


def saved_row(number: int) -> dict:
    return {
        "concept_id": 100 + number,
        "label": f"Saved concept {number}",
        "explanation": f"Saved explanation {number}.",
        "mistake_event_id": f"event-{number}",
        "question_text": f"Original missed question {number}.",
        "chosen_answer": f"Wrong answer {number}.",
        "correct_answer": f"Correct answer {number}.",
        "mistake_explanation": f"Original mistake explanation {number}.",
        "origin": "player",
    }


def candidates(count: int):
    return build_boss_candidates([saved_row(number) for number in range(1, count + 1)])


def weak_question(target_ref: str) -> dict:
    return {
        "target_ref": target_ref,
        "question": f"Harder question for {target_ref}.",
        "options": [
            f"{target_ref} choice A",
            f"{target_ref} choice B",
            f"{target_ref} choice C",
            f"{target_ref} choice D",
        ],
        "correct_option_index": 0,
        "explanation": f"Explanation for {target_ref}.",
    }


def weak_payload(target_refs: list[str]) -> dict:
    return {"questions": [weak_question(ref) for ref in target_refs]}


def adaptive_question(number: int) -> dict:
    return {
        "question": f"Adaptive question {number}.",
        "options": [
            f"Adaptive {number} A",
            f"Adaptive {number} B",
            f"Adaptive {number} C",
            f"Adaptive {number} D",
        ],
        "correct_option_index": number % 4,
        "explanation": f"Adaptive explanation {number}.",
        "concept_label": f"Adaptive concept {number}",
        "concept_explanation": f"Adaptive concept explanation {number}.",
    }


class TestBossGenerationComposition(unittest.TestCase):
    def test_all_four_compositions_produce_complete_sets(self):
        cases = [
            (5, 5, 0),
            (3, 3, 2),
            (1, 1, 4),
            (0, 0, 5),
        ]
        for saved_count, weak_count, adaptive_count in cases:
            with self.subTest(saved=saved_count):
                fake = FakeGeminiClient()
                supplied = candidates(saved_count)

                boss_set = generate_boss_set(
                    fake,
                    topic="DBMS Normalization",
                    lesson_cards=LESSON_CARDS,
                    candidates=supplied,
                )

                self.assertEqual(len(boss_set.questions), 5)
                self.assertEqual(boss_set.weak_spot_count, weak_count)
                self.assertEqual(boss_set.adaptive_count, adaptive_count)
                self.assertEqual(len(fake.boss_weak_calls), 1 if saved_count else 0)
                self.assertEqual(
                    len(fake.boss_adaptive_calls), 1 if adaptive_count else 0
                )
                if adaptive_count:
                    self.assertEqual(
                        fake.boss_adaptive_calls[0]["question_count"], adaptive_count
                    )

                weak_questions = [
                    question
                    for question in boss_set.questions
                    if question.kind == "weak_spot"
                ]
                self.assertEqual(
                    [question.target_ref for question in weak_questions],
                    [f"C{number}" for number in range(1, saved_count + 1)],
                )
                self.assertEqual(
                    [question.weak_concept_id for question in weak_questions],
                    [candidate.weak_concept_id for candidate in supplied],
                )
                self.assertEqual(
                    [question.mistake_event_id for question in weak_questions],
                    [candidate.mistake_event_id for candidate in supplied],
                )
                self.assertEqual(len(set(question.weak_concept_id for question in weak_questions)), weak_count)

    def test_adaptive_questions_keep_required_metadata(self):
        fake = FakeGeminiClient()

        boss_set = generate_boss_set(
            fake,
            topic="DBMS Normalization",
            lesson_cards=LESSON_CARDS,
            candidates=(),
        )

        self.assertEqual(len(fake.boss_weak_calls), 0)
        self.assertEqual(len(fake.boss_adaptive_calls), 1)
        for question in boss_set.questions:
            self.assertEqual(question.kind, "adaptive")
            self.assertIsNone(question.target_ref)
            self.assertIsNone(question.weak_concept_id)
            self.assertIsNone(question.mistake_event_id)
            self.assertTrue(question.concept_label)
            self.assertTrue(question.concept_explanation)
            self.assertEqual(len(question.options), 4)
        self.assertEqual(boss_set.questions[0].concept_label, "Lesson concept 1")


class TestBossGenerationTraceability(unittest.TestCase):
    def test_prompt_data_has_no_database_ids_and_trusted_links_are_attached(self):
        supplied = candidates(3)
        fake = FakeGeminiClient()

        boss_set = generate_boss_set(
            fake,
            topic="DBMS Normalization",
            lesson_cards=LESSON_CARDS,
            candidates=supplied,
        )

        prompt_candidates = fake.boss_weak_calls[0]["candidates"]
        expected_keys = {
            "target_ref",
            "saved_concept",
            "saved_explanation",
            "previous_question",
            "previous_wrong_answer",
            "previous_correct_answer",
            "previous_explanation",
        }
        serialized = json.dumps(prompt_candidates)
        for item in prompt_candidates:
            self.assertEqual(set(item), expected_keys)
            for forbidden in (
                "weak_concept_id",
                "mistake_event_id",
                "concept_id",
                "origin",
                "occurred_at",
            ):
                self.assertNotIn(forbidden, item)
        for candidate in supplied:
            self.assertNotIn(str(candidate.weak_concept_id), serialized)
            self.assertNotIn(candidate.mistake_event_id, serialized)

        weak_questions = [
            question for question in boss_set.questions if question.kind == "weak_spot"
        ]
        for question, candidate in zip(weak_questions, supplied):
            self.assertEqual(question.weak_concept_id, candidate.weak_concept_id)
            self.assertEqual(question.mistake_event_id, candidate.mistake_event_id)
            self.assertEqual(question.concept_label, candidate.concept_label)
            self.assertEqual(question.concept_explanation, candidate.concept_explanation)

    def test_model_cannot_override_saved_weak_spot_data(self):
        fake = FakeGeminiClient(
            boss_weak_result={
                "questions": [
                    {**weak_question("C1"), "concept_label": "Invented weakness"},
                    weak_question("C2"),
                ]
            }
        )

        with self.assertRaises(InvalidBossContent):
            generate_boss_set(
                fake,
                topic="DBMS Normalization",
                lesson_cards=LESSON_CARDS,
                candidates=candidates(2),
            )


class TestBossGenerationFailures(unittest.TestCase):
    def test_rejects_duplicate_saved_concepts(self):
        base = candidates(1)[0]
        duplicate = BossCandidate(
            target_ref="C2",
            weak_concept_id=base.weak_concept_id,
            mistake_event_id="event-duplicate",
            concept_label="Duplicate concept",
            concept_explanation="Duplicate explanation.",
            original_question="Duplicate previous question.",
            chosen_answer="Duplicate wrong answer.",
            correct_answer="Duplicate correct answer.",
            mistake_explanation="Duplicate mistake explanation.",
            origin="player",
        )

        with self.assertRaises(InvalidBossContent):
            generate_boss_set(
                FakeGeminiClient(),
                topic="DBMS Normalization",
                lesson_cards=LESSON_CARDS,
                candidates=(base, duplicate),
            )

    def test_rejects_unknown_missing_duplicate_and_mismatched_references(self):
        cases = {
            "unknown": ["C1", "C3"],
            "missing": ["C1"],
            "duplicate": ["C1", "C1"],
            "mismatched": ["C2", "C3"],
        }
        for name, refs in cases.items():
            with self.subTest(name=name):
                fake = FakeGeminiClient(boss_weak_result=weak_payload(refs))
                with self.assertRaises(InvalidBossContent):
                    generate_boss_set(
                        fake,
                        topic="DBMS Normalization",
                        lesson_cards=LESSON_CARDS,
                        candidates=candidates(2),
                    )

    def test_rejects_provider_failure_without_fake_fallback(self):
        fake = FakeGeminiClient(boss_weak_result=LessonProviderError("offline"))

        with self.assertRaises(LessonProviderError):
            generate_boss_set(
                fake,
                topic="DBMS Normalization",
                lesson_cards=LESSON_CARDS,
                candidates=candidates(2),
            )
        self.assertEqual(fake.boss_adaptive_calls, [])

    def test_rejects_adaptive_provider_failure(self):
        fake = FakeGeminiClient(boss_adaptive_result=LessonProviderError("offline"))

        with self.assertRaises(LessonProviderError):
            generate_boss_set(
                fake,
                topic="DBMS Normalization",
                lesson_cards=LESSON_CARDS,
                candidates=(),
            )
        self.assertEqual(fake.boss_weak_calls, [])

    def test_rejects_malformed_and_incomplete_output(self):
        fake = FakeGeminiClient(boss_weak_result="not-json")
        with self.assertRaises(InvalidBossContent):
            generate_boss_set(
                fake,
                topic="DBMS Normalization",
                lesson_cards=LESSON_CARDS,
                candidates=candidates(2),
            )

        incomplete = FakeGeminiClient(boss_weak_result=weak_payload(["C1"]))
        with self.assertRaises(InvalidBossContent):
            generate_boss_set(
                incomplete,
                topic="DBMS Normalization",
                lesson_cards=LESSON_CARDS,
                candidates=candidates(2),
            )
        self.assertEqual(incomplete.boss_adaptive_calls, [])

        malformed_adaptive = FakeGeminiClient(
            boss_adaptive_result={
                "questions": [
                    {
                        **adaptive_question(1),
                        "options": ["Only one", "Only two", "Only three"],
                    }
                ]
            }
        )
        with self.assertRaises(InvalidBossContent):
            generate_boss_set(
                malformed_adaptive,
                topic="DBMS Normalization",
                lesson_cards=LESSON_CARDS,
                candidates=(),
            )

    def test_rejects_incomplete_adaptive_count(self):
        fake = FakeGeminiClient(
            boss_adaptive_result={
                "questions": [adaptive_question(number) for number in range(1, 5)]
            }
        )

        with self.assertRaises(InvalidBossContent):
            generate_boss_set(
                fake,
                topic="DBMS Normalization",
                lesson_cards=LESSON_CARDS,
                candidates=(),
            )

    def test_rejects_adaptive_weak_spot_fields(self):
        fake = FakeGeminiClient(
            boss_adaptive_result={
                "questions": [
                    {**adaptive_question(1), "target_ref": "C1"}
                ]
            }
        )

        with self.assertRaises(InvalidBossContent):
            generate_boss_set(
                fake,
                topic="DBMS Normalization",
                lesson_cards=LESSON_CARDS,
                candidates=(),
            )


class TestFakeBossGeneration(unittest.TestCase):
    def test_fake_generation_is_deterministic_and_goes_through_validation(self):
        supplied = candidates(3)

        first = generate_boss_set(
            FakeGeminiClient(),
            topic="DBMS Normalization",
            lesson_cards=LESSON_CARDS,
            candidates=supplied,
        )
        second = generate_boss_set(
            FakeGeminiClient(),
            topic="DBMS Normalization",
            lesson_cards=LESSON_CARDS,
            candidates=supplied,
        )

        self.assertEqual(first, second)
        self.assertEqual(first.weak_spot_count, 3)
        self.assertEqual(first.adaptive_count, 2)


if __name__ == "__main__":
    unittest.main()
