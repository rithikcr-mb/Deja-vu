from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dejavu.db.connection import initialize_database
from dejavu.db.repository import get_weak_concepts_with_latest_event
from dejavu.services.content import (
    BossCandidate,
    InvalidBossContent,
    boss_candidate_prompt_data,
    build_boss_candidates,
    validate_adaptive_boss_questions,
    validate_boss_set,
    validate_weak_spot_boss_questions,
)
from dejavu.services.demo_seed import seed_demo


def candidate(number: int) -> BossCandidate:
    return BossCandidate(
        target_ref=f"C{number}",
        weak_concept_id=100 + number,
        mistake_event_id=f"event-{number}",
        concept_label=f"Saved concept {number}",
        concept_explanation=f"Saved explanation {number}.",
        original_question=f"Original missed question {number}.",
        chosen_answer=f"Wrong answer {number}.",
        correct_answer=f"Correct answer {number}.",
        mistake_explanation=f"Original mistake explanation {number}.",
        origin="player",
    )


def weak_question(target_ref: str, correct_index: int = 0) -> dict:
    return {
        "target_ref": target_ref,
        "question": f"Harder question for {target_ref}.",
        "options": [
            f"{target_ref} choice A",
            f"{target_ref} choice B",
            f"{target_ref} choice C",
            f"{target_ref} choice D",
        ],
        "correct_option_index": correct_index,
        "explanation": f"Explanation for {target_ref}.",
    }


def adaptive_question(number: int) -> dict:
    return {
        "question": f"Adaptive lesson question {number}.",
        "options": [
            f"Adaptive {number} choice A",
            f"Adaptive {number} choice B",
            f"Adaptive {number} choice C",
            f"Adaptive {number} choice D",
        ],
        "correct_option_index": number % 4,
        "explanation": f"Adaptive explanation {number}.",
        "concept_label": f"Lesson concept {number}",
        "concept_explanation": f"Lesson concept explanation {number}.",
    }


def adaptive_set(count: int) -> dict:
    return {"questions": [adaptive_question(index) for index in range(1, count + 1)]}


class TestBossCandidates(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.database = str(Path(self.tempdir.name) / "boss-content.sqlite3")
        initialize_database(self.database)

    def test_candidates_use_temporary_refs_and_saved_trace_links(self):
        seed_demo(self.database)
        rows = get_weak_concepts_with_latest_event(self.database, 5)

        candidates = build_boss_candidates(rows)

        self.assertEqual([item.target_ref for item in candidates], ["C1", "C2", "C3"])
        self.assertEqual(
            [item.concept_label for item in candidates],
            ["Candidate keys", "Functional dependencies", "Third normal form"],
        )
        # "Functional dependencies" has two events; the most recent one is used.
        functional = candidates[1]
        self.assertEqual(
            functional.original_question,
            "Why can a partial dependency violate second normal form?",
        )
        self.assertEqual(functional.origin, "seeded_demo")
        self.assertTrue(all(item.weak_concept_id > 0 for item in candidates))
        self.assertTrue(all(item.mistake_event_id for item in candidates))

    def test_prompt_data_uses_temporary_refs_and_no_database_ids(self):
        candidates = tuple(candidate(number) for number in range(1, 3))

        payload = boss_candidate_prompt_data(candidates)

        self.assertEqual([item["target_ref"] for item in payload], ["C1", "C2"])
        self.assertEqual(payload[0]["saved_concept"], "Saved concept 1")
        for item in payload:
            self.assertNotIn("weak_concept_id", item)
            self.assertNotIn("mistake_event_id", item)
            self.assertNotIn("concept_id", item)

    def test_validation_attaches_saved_ids_and_labels_not_model_prose(self):
        candidates = tuple(candidate(number) for number in range(1, 4))

        validated = validate_weak_spot_boss_questions(
            {"questions": [weak_question("C3"), weak_question("C1"), weak_question("C2")]},
            candidates,
        )

        self.assertEqual([item.target_ref for item in validated], ["C3", "C1", "C2"])
        self.assertTrue(all(item.is_weak_spot for item in validated))
        by_ref = {item.target_ref: item for item in validated}
        self.assertEqual(by_ref["C1"].weak_concept_id, 101)
        self.assertEqual(by_ref["C1"].mistake_event_id, "event-1")
        self.assertEqual(by_ref["C1"].concept_label, "Saved concept 1")
        self.assertEqual(by_ref["C1"].concept_explanation, "Saved explanation 1.")


class TestBossValidation(unittest.TestCase):
    def test_rejects_unknown_missing_and_duplicate_references(self):
        candidates = (candidate(1), candidate(2))
        invalid_sets = {
            "unknown": [weak_question("C1"), weak_question("C3")],
            "missing": [weak_question("C1")],
            "duplicate": [weak_question("C1"), weak_question("C1")],
        }
        for name, questions in invalid_sets.items():
            with self.subTest(name=name):
                with self.assertRaises(InvalidBossContent):
                    validate_weak_spot_boss_questions(
                        {"questions": questions}, candidates
                    )

    def test_adaptive_questions_have_no_weak_spot_target(self):
        validated = validate_adaptive_boss_questions(adaptive_set(2), 2)

        self.assertEqual(len(validated), 2)
        for question in validated:
            self.assertEqual(question.kind, "adaptive")
            self.assertFalse(question.is_weak_spot)
            self.assertIsNone(question.target_ref)
            self.assertIsNone(question.weak_concept_id)
            self.assertIsNone(question.mistake_event_id)
        self.assertEqual(validated[0].concept_label, "Lesson concept 1")
        self.assertEqual(validated[0].concept_explanation, "Lesson concept explanation 1.")

    def test_adaptive_questions_cannot_include_weak_spot_fields(self):
        for field_name in ("target_ref", "weak_concept_id", "mistake_event_id"):
            with self.subTest(field=field_name):
                payload = adaptive_set(1)
                payload["questions"][0][field_name] = "C1" if field_name == "target_ref" else 1
                with self.assertRaises(InvalidBossContent):
                    validate_adaptive_boss_questions(payload, 1)

    def test_combined_set_separates_weak_spots_from_adaptive_tests(self):
        candidates = tuple(candidate(number) for number in range(1, 4))

        boss_set = validate_boss_set(
            {"questions": [weak_question("C1"), weak_question("C2"), weak_question("C3")]},
            adaptive_set(2),
            candidates,
        )

        self.assertEqual(len(boss_set.questions), 5)
        self.assertEqual(boss_set.weak_spot_count, 3)
        self.assertEqual(boss_set.adaptive_count, 2)
        self.assertEqual(
            [question.kind for question in boss_set.questions],
            ["weak_spot", "weak_spot", "weak_spot", "adaptive", "adaptive"],
        )
        self.assertEqual(
            [question.target_ref for question in boss_set.questions[:3]],
            ["C1", "C2", "C3"],
        )
        for question in boss_set.questions[:3]:
            self.assertIsNotNone(question.weak_concept_id)
            self.assertIsNotNone(question.mistake_event_id)
        for question in boss_set.questions[3:]:
            self.assertIsNone(question.weak_concept_id)
            self.assertIsNone(question.mistake_event_id)

    def test_no_saved_concepts_produces_only_adaptive_tests(self):
        boss_set = validate_boss_set(None, adaptive_set(5), ())

        self.assertEqual(len(boss_set.questions), 5)
        self.assertEqual(boss_set.weak_spot_count, 0)
        self.assertEqual(boss_set.adaptive_count, 5)
        self.assertTrue(all(question.kind == "adaptive" for question in boss_set.questions))

    def test_one_saved_concept_uses_four_adaptive_fillers(self):
        candidates = (candidate(1),)

        boss_set = validate_boss_set(
            {"questions": [weak_question("C1")]}, adaptive_set(4), candidates
        )

        self.assertEqual(len(boss_set.questions), 5)
        self.assertEqual(boss_set.weak_spot_count, 1)
        self.assertEqual(boss_set.adaptive_count, 4)
        self.assertEqual(boss_set.questions[0].kind, "weak_spot")
        self.assertEqual(boss_set.questions[0].target_ref, "C1")
        self.assertEqual(boss_set.questions[0].weak_concept_id, 101)
        self.assertEqual(boss_set.questions[0].mistake_event_id, "event-1")
        self.assertTrue(
            all(question.kind == "adaptive" for question in boss_set.questions[1:])
        )

    def test_five_saved_concepts_need_no_adaptive_fillers(self):
        candidates = tuple(candidate(number) for number in range(1, 6))
        weak_payload = {
            "questions": [weak_question(f"C{number}") for number in range(1, 6)]
        }

        boss_set = validate_boss_set(weak_payload, None, candidates)

        self.assertEqual(len(boss_set.questions), 5)
        self.assertEqual(boss_set.weak_spot_count, 5)
        self.assertEqual(boss_set.adaptive_count, 0)
        self.assertEqual(
            [question.target_ref for question in boss_set.questions],
            ["C1", "C2", "C3", "C4", "C5"],
        )

    def test_rejects_incomplete_counts_instead_of_filling_questions(self):
        candidates = tuple(candidate(number) for number in range(1, 4))
        cases = {
            "missing weak question": (
                {"questions": [weak_question("C1"), weak_question("C2")]},
                adaptive_set(2),
                candidates,
            ),
            "missing adaptive question": (
                {"questions": [weak_question("C1"), weak_question("C2"), weak_question("C3")]},
                adaptive_set(1),
                candidates,
            ),
            "unexpected adaptive set": (
                {"questions": [weak_question(f"C{number}") for number in range(1, 6)]},
                adaptive_set(1),
                tuple(candidate(number) for number in range(1, 6)),
            ),
            "weak set without candidates": (
                {"questions": [weak_question("C1")]},
                adaptive_set(4),
                (),
            ),
            "missing weak set": (None, adaptive_set(2), candidates),
        }
        for name, (weak_raw, adaptive_raw, supplied) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(InvalidBossContent):
                    validate_boss_set(weak_raw, adaptive_raw, supplied)

    def test_rejects_malformed_or_incomplete_question_payloads(self):
        candidates = (candidate(1), candidate(2))
        bad_question = weak_question("C1")
        invalid_questions = {
            "wrong option count": {**bad_question, "options": bad_question["options"][:3]},
            "duplicate options": {
                **bad_question,
                "options": [
                    "Same choice",
                    "same choice",
                    "Third choice",
                    "Fourth choice",
                ],
            },
            "answer index out of range": {**bad_question, "correct_option_index": 4},
            "blank question": {**bad_question, "question": "   "},
            "missing explanation": {
                key: value
                for key, value in bad_question.items()
                if key != "explanation"
            },
            "model weak-concept id": {**bad_question, "weak_concept_id": 999},
            "model mistake link": {**bad_question, "mistake_event_id": "invented"},
            "model concept label": {**bad_question, "concept_label": "Invented"},
            "model history context": {
                **bad_question,
                "previous_question": "Invented history",
            },
        }
        for name, question in invalid_questions.items():
            with self.subTest(name=name):
                with self.assertRaises(InvalidBossContent):
                    validate_weak_spot_boss_questions(
                        {"questions": [question, weak_question("C2")]}, candidates
                    )

        with self.assertRaises(InvalidBossContent):
            validate_weak_spot_boss_questions({"questions": []}, candidates)
        with self.assertRaises(InvalidBossContent):
            validate_weak_spot_boss_questions("not-json", candidates)

    def test_rejects_blank_adaptive_concept_data(self):
        payload = adaptive_set(1)
        payload["questions"][0]["concept_explanation"] = "   "
        with self.assertRaises(InvalidBossContent):
            validate_adaptive_boss_questions(payload, 1)


if __name__ == "__main__":
    unittest.main()
