from __future__ import annotations

import unittest

from dejavu.services.ai_client import FakeGeminiClient, LessonProviderError
from dejavu.services.content import (
    InvalidReviewContent,
    generate_review_set,
    validate_review_set,
)


CONCEPT = {
    "saved_concept": "Third normal form",
    "saved_explanation": "Third normal form removes transitive dependencies.",
}


def review_payload(**overrides):
    question = {
        "question": "Which dependency does 3NF remove?",
        "options": ["Partial dependencies", "Transitive dependencies", "Nothing", "Joins"],
        "correct_option_index": 1,
        "explanation": "3NF removes transitive dependencies.",
        "target_concept_label": "Third normal form",
    }
    question.update(overrides)
    second = {
        "question": "Which dependency does 3NF remove?",
        "options": ["Partial", "Transitive", "Nothing", "Joins"],
        "correct_option_index": 1,
        "explanation": "3NF removes transitive dependencies.",
        "target_concept_label": "Third normal form",
    }
    return {"questions": [question, second]}


class TestReviewValidation(unittest.TestCase):
    def test_accepts_exactly_two_questions_for_the_saved_concept(self):
        validated = validate_review_set(
            review_payload(),
            concept_label="Third normal form",
            concept_explanation="Third normal form removes transitive dependencies.",
        )

        self.assertEqual(len(validated.questions), 2)
        for question in validated.questions:
            self.assertEqual(len(question.options), 4)
            self.assertIn(question.correct_option_index, range(4))
            self.assertEqual(question.concept_label, "Third normal form")
            self.assertEqual(
                question.concept_explanation,
                "Third normal form removes transitive dependencies.",
            )

    def test_saved_label_and_explanation_replace_model_prose(self):
        validated = validate_review_set(
            review_payload(),
            concept_label="Third normal form",
            concept_explanation="The saved explanation.",
        )

        for question in validated.questions:
            self.assertEqual(question.concept_label, "Third normal form")
            self.assertEqual(question.concept_explanation, "The saved explanation.")

    def test_rejects_a_question_that_targets_another_concept(self):
        payload = review_payload()
        payload["questions"][1]["target_concept_label"] = "Something else"

        with self.assertRaises(InvalidReviewContent):
            validate_review_set(
                payload,
                concept_label="Third normal form",
                concept_explanation="Third normal form removes transitive dependencies.",
            )

    def test_accepts_a_different_rendering_of_the_same_saved_concept(self):
        """The model may phrase the label differently; the saved one is kept."""
        variants = [
            "third normal form",
            "Third Normal Form.",
            "the Third normal form",
            "Third normal form (3NF)",
        ]
        for variant in variants:
            payload = review_payload()
            for question in payload["questions"]:
                question["target_concept_label"] = variant

            validated = validate_review_set(
                payload,
                concept_label="Third normal form",
                concept_explanation="Third normal form removes transitive dependencies.",
            )

            for question in validated.questions:
                self.assertEqual(question.concept_label, "Third normal form")
                self.assertEqual(
                    question.concept_explanation,
                    "Third normal form removes transitive dependencies.",
                )

    def test_accepts_a_shortened_rendering_of_the_same_saved_concept(self):
        payload = review_payload()
        for question in payload["questions"]:
            question["target_concept_label"] = "Functional dependencies"

        validated = validate_review_set(
            payload,
            concept_label="Functional dependencies (3NF)",
            concept_explanation="Saved explanation.",
        )

        for question in validated.questions:
            self.assertEqual(question.concept_label, "Functional dependencies (3NF)")

    def test_still_rejects_a_different_concept(self):
        """A label with nothing in common with the saved concept is rejected."""
        payload = review_payload()
        for question in payload["questions"]:
            question["target_concept_label"] = "Database transaction isolation"

        with self.assertRaises(InvalidReviewContent):
            validate_review_set(
                payload,
                concept_label="Third normal form",
                concept_explanation="Third normal form removes transitive dependencies.",
            )

    def test_rejects_wrong_question_counts(self):
        payload = review_payload()
        payload["questions"] = payload["questions"][:1]

        with self.assertRaises(InvalidReviewContent):
            validate_review_set(
                payload,
                concept_label="Third normal form",
                concept_explanation="Third normal form removes transitive dependencies.",
            )

    def test_rejects_duplicate_or_blank_options(self):
        payload = review_payload()
        payload["questions"][0]["options"] = ["Same", "Same", "Other", "Another"]

        with self.assertRaises(InvalidReviewContent):
            validate_review_set(
                payload,
                concept_label="Third normal form",
                concept_explanation="Third normal form removes transitive dependencies.",
            )

    def test_rejects_blank_question_or_explanation(self):
        payload = review_payload()
        payload["questions"][0]["explanation"] = "   "

        with self.assertRaises(InvalidReviewContent):
            validate_review_set(
                payload,
                concept_label="Third normal form",
                concept_explanation="Third normal form removes transitive dependencies.",
            )

    def test_rejects_malformed_output(self):
        with self.assertRaises(InvalidReviewContent):
            validate_review_set(
                "not-json",
                concept_label="Third normal form",
                concept_explanation="Third normal form removes transitive dependencies.",
            )

    def test_provider_failure_does_not_fabricate_questions(self):
        client = FakeGeminiClient(review_result=LessonProviderError("offline"))

        with self.assertRaises(LessonProviderError):
            generate_review_set(
                client,
                concept_label="Third normal form",
                concept_explanation="Third normal form removes transitive dependencies.",
            )

        self.assertEqual(len(client.review_calls), 1)

    def test_fake_generation_is_deterministic_and_passes_validation(self):
        client = FakeGeminiClient()

        first = generate_review_set(
            client,
            concept_label="Third normal form",
            concept_explanation="Third normal form removes transitive dependencies.",
        )
        second = generate_review_set(
            client,
            concept_label="Third normal form",
            concept_explanation="Third normal form removes transitive dependencies.",
        )

        self.assertEqual(len(first.questions), 2)
        self.assertEqual(
            [question.question for question in first.questions],
            [question.question for question in second.questions],
        )
        self.assertEqual(
            [question.correct_option_index for question in first.questions],
            [question.correct_option_index for question in second.questions],
        )

    def test_fake_generation_sends_only_the_saved_concept(self):
        client = FakeGeminiClient()

        generate_review_set(
            client,
            concept_label="Third normal form",
            concept_explanation="Third normal form removes transitive dependencies.",
        )

        self.assertEqual(
            client.review_calls,
            [
                {
                    "saved_concept": "Third normal form",
                    "saved_explanation": (
                        "Third normal form removes transitive dependencies."
                    ),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
