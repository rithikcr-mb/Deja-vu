from __future__ import annotations

import unittest

from dejavu.services.review import (
    advance_review,
    apply_review_answer,
    current_review_question,
    grade_review_answer,
    new_review,
    review_view,
)


class FakeReviewSet:
    def __init__(self, count=2):
        self.questions = tuple(
            FakeReviewQuestion(index) for index in range(count)
        )


class FakeReviewQuestion:
    def __init__(self, index):
        self.question = f"Question {index + 1}"
        self.options = (f"Option A{index}", f"Option B{index}", "Option C", "Option D")
        self.correct_option_index = index % 4
        self.explanation = f"Explanation {index + 1}"


def build_review(count=2):
    return new_review(
        FakeReviewSet(count),
        review_id="review-1",
        weak_concept_id=7,
        concept_label="Third normal form",
        concept_explanation="Saved explanation.",
        original_question="Original question.",
        original_chosen_answer="Chosen.",
        original_correct_answer="Correct.",
        original_explanation="Because.",
    )


class TestReviewRules(unittest.TestCase):
    def test_review_starts_with_two_questions_and_saved_context(self):
        review = build_review()

        self.assertEqual(review["phase"], "question")
        self.assertEqual(review["question_index"], 0)
        self.assertEqual(len(review["questions"]), 2)
        self.assertEqual(review["concept_label"], "Third normal form")
        self.assertEqual(review["original_question"], "Original question.")

    def test_review_needs_exactly_two_questions(self):
        with self.assertRaises(ValueError):
            build_review(count=1)

    def test_correct_answer_is_graded_by_python(self):
        review = build_review()
        question = current_review_question(review)

        result = grade_review_answer(review, question["correct_option_index"])

        self.assertTrue(result["is_correct"])
        self.assertEqual(result["chosen_answer"], result["correct_answer"])
        self.assertEqual(result["attempt_id"], review["attempt_id"])

    def test_wrong_answer_is_graded_by_python(self):
        review = build_review()
        question = current_review_question(review)
        wrong = (question["correct_option_index"] + 1) % 4

        result = grade_review_answer(review, wrong)

        self.assertFalse(result["is_correct"])
        self.assertNotEqual(result["chosen_answer"], result["correct_answer"])

    def test_invalid_selection_is_rejected(self):
        review = build_review()

        with self.assertRaises(ValueError):
            grade_review_answer(review, 9)

    def test_a_question_can_only_be_answered_once(self):
        review = build_review()
        question = current_review_question(review)
        result = grade_review_answer(review, question["correct_option_index"])
        apply_review_answer(review, result)

        with self.assertRaises(ValueError):
            grade_review_answer(review, question["correct_option_index"])

    def test_advance_moves_to_the_second_question_then_completes(self):
        review = build_review()
        question = current_review_question(review)
        result = grade_review_answer(review, question["correct_option_index"])
        apply_review_answer(review, result)

        self.assertEqual(review["phase"], "answered")
        self.assertEqual(review["next_action"], "next_question")

        advance_review(review)
        self.assertEqual(review["phase"], "question")
        self.assertEqual(review["question_index"], 1)
        self.assertNotEqual(review["attempt_id"], result["attempt_id"])

        question = current_review_question(review)
        result = grade_review_answer(review, question["correct_option_index"])
        apply_review_answer(review, result)
        self.assertEqual(review["next_action"], "complete")

        advance_review(review)
        self.assertEqual(review["phase"], "complete")
        self.assertEqual(len(review["answers"]), 2)

    def test_advance_is_rejected_before_an_answer(self):
        review = build_review()

        with self.assertRaises(ValueError):
            advance_review(review)

    def test_view_exposes_the_trusted_saved_concept(self):
        review = build_review()
        view = review_view(review)

        self.assertEqual(view["concept_label"], "Third normal form")
        self.assertEqual(view["concept_explanation"], "Saved explanation.")
        self.assertEqual(view["question_count"], 2)
        self.assertEqual(view["question_number"], 1)
        self.assertEqual(view["correct_count"], 0)
        self.assertIsNotNone(view["question"])


if __name__ == "__main__":
    unittest.main()
