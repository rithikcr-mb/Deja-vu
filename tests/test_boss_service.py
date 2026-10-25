from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from dejavu.db.connection import initialize_database
from dejavu.db.repository import (
    create_learning_session,
    get_mistake_events,
    get_weak_concepts,
    record_mistake,
)
from dejavu.services.battle import (
    BOSS_STARTING_HP,
    advance_boss_after_answer,
    apply_boss_answer,
    boss_view,
    current_boss_question,
    grade_boss_answer,
    new_boss_encounter,
    retry_boss,
)
from dejavu.services.content import build_boss_candidates, validate_boss_set


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


def make_boss_set(weak_count: int = 3):
    candidates = build_boss_candidates(
        [saved_row(number) for number in range(1, weak_count + 1)]
    )
    weak_raw = (
        {"questions": [weak_question(item.target_ref) for item in candidates]}
        if candidates
        else None
    )
    adaptive_raw = {
        "questions": [
            adaptive_question(number)
            for number in range(1, 5 - weak_count + 1)
        ]
    }
    return validate_boss_set(weak_raw, adaptive_raw, candidates)


def answer(encounter: dict, *, correct: bool) -> dict:
    question = current_boss_question(encounter)
    selected = question["correct_option_index"]
    if not correct:
        selected = (selected + 1) % 4
    result = grade_boss_answer(encounter, selected)
    apply_boss_answer(encounter, result)
    return result


class TestBossRules(unittest.TestCase):
    def setUp(self):
        self.encounter = new_boss_encounter(make_boss_set(3))

    def test_encounter_starts_with_full_health_and_trusted_links(self):
        view = boss_view(self.encounter)

        self.assertEqual(self.encounter["player_hp"], 100)
        self.assertEqual(self.encounter["boss_hp"], BOSS_STARTING_HP)
        self.assertEqual(view["question_count"], 5)
        self.assertEqual(view["weak_spot_count"], 3)
        self.assertEqual(view["adaptive_count"], 2)
        self.assertEqual(view["question_number"], 1)
        self.assertEqual(view["question"]["kind"], "weak_spot")
        self.assertEqual(view["question"]["weak_concept_id"], 101)
        self.assertEqual(view["question"]["mistake_event_id"], "event-1")
        self.assertEqual(view["question"]["concept_label"], "Saved concept 1")

    def test_correct_answer_damages_boss_and_wrong_answer_damages_player(self):
        answer(self.encounter, correct=True)
        self.assertEqual(self.encounter["boss_hp"], 75)
        self.assertEqual(self.encounter["player_hp"], 100)

        advance_boss_after_answer(self.encounter)
        answer(self.encounter, correct=False)
        self.assertEqual(self.encounter["boss_hp"], 75)
        self.assertEqual(self.encounter["player_hp"], 80)

    def test_wrong_answer_applies_20_damage_only_once(self):
        result = answer(self.encounter, correct=False)
        self.assertEqual(self.encounter["player_hp"], 80)

        with self.assertRaises(ValueError):
            apply_boss_answer(self.encounter, result)

        self.assertEqual(self.encounter["player_hp"], 80)

    def test_four_correct_answers_win_before_the_fifth_question(self):
        for answer_number in range(1, 5):
            answer(self.encounter, correct=True)
            if answer_number < 4:
                self.assertEqual(self.encounter["next_action"], "next_question")
                advance_boss_after_answer(self.encounter)

        self.assertEqual(self.encounter["boss_hp"], 0)
        self.assertEqual(self.encounter["player_hp"], 100)
        self.assertEqual(self.encounter["next_action"], "victory")
        self.assertEqual(self.encounter["question_index"], 3)

    def test_player_health_reaching_zero_is_defeat(self):
        for answer_number in range(1, 6):
            answer(self.encounter, correct=False)
            if answer_number < 5:
                advance_boss_after_answer(self.encounter)

        self.assertEqual(self.encounter["player_hp"], 0)
        self.assertGreater(self.encounter["boss_hp"], 0)
        self.assertEqual(self.encounter["next_action"], "defeat")

    def test_five_exhausted_questions_with_boss_alive_is_defeat(self):
        for answer_number in range(1, 6):
            answer(self.encounter, correct=answer_number <= 3)
            if answer_number < 5:
                advance_boss_after_answer(self.encounter)

        self.assertEqual(self.encounter["boss_hp"], 25)
        self.assertEqual(self.encounter["player_hp"], 60)
        self.assertEqual(self.encounter["next_action"], "defeat")
        self.assertEqual(self.encounter["question_index"], 4)

    def test_retry_restores_both_pools_and_preserves_questions_and_links(self):
        for answer_number in range(1, 6):
            answer(self.encounter, correct=False)
            if answer_number < 5:
                advance_boss_after_answer(self.encounter)
        self.assertEqual(self.encounter["next_action"], "defeat")

        questions_before = copy.deepcopy(self.encounter["questions"])
        old_attempt_id = self.encounter["attempt_id"]
        old_transition_id = self.encounter["transition_id"]
        retry_boss(self.encounter)

        self.assertEqual(self.encounter["player_hp"], 100)
        self.assertEqual(self.encounter["boss_hp"], 100)
        self.assertEqual(self.encounter["question_index"], 0)
        self.assertEqual(self.encounter["phase"], "question")
        self.assertIsNone(self.encounter["result"])
        self.assertIsNone(self.encounter["next_action"])
        self.assertEqual(self.encounter["questions"], questions_before)
        self.assertNotEqual(self.encounter["attempt_id"], old_attempt_id)
        self.assertNotEqual(self.encounter["transition_id"], old_transition_id)

        first = current_boss_question(self.encounter)
        self.assertEqual(first["weak_concept_id"], 101)
        self.assertEqual(first["mistake_event_id"], "event-1")
        self.assertEqual(first["concept_label"], "Saved concept 1")

    def test_previous_attempt_result_cannot_leak_into_retry(self):
        results = []
        for answer_number in range(1, 6):
            results.append(answer(self.encounter, correct=False))
            if answer_number < 5:
                advance_boss_after_answer(self.encounter)
        stale_result = results[-1]
        self.assertEqual(self.encounter["next_action"], "defeat")

        retry_boss(self.encounter)

        with self.assertRaises(ValueError):
            apply_boss_answer(self.encounter, stale_result)

        self.assertEqual(self.encounter["player_hp"], 100)
        self.assertEqual(self.encounter["boss_hp"], 100)
        self.assertEqual(self.encounter["phase"], "question")

    def test_duplicate_answers_cannot_apply_damage_twice(self):
        result = answer(self.encounter, correct=True)
        self.assertEqual(self.encounter["boss_hp"], 75)

        with self.assertRaises(ValueError):
            grade_boss_answer(self.encounter, 0)
        with self.assertRaises(ValueError):
            apply_boss_answer(self.encounter, result)

        self.assertEqual(self.encounter["boss_hp"], 75)
        self.assertEqual(self.encounter["player_hp"], 100)

    def test_adaptive_wrong_answer_keeps_concept_data_for_a_new_mistake(self):
        encounter = new_boss_encounter(make_boss_set(0))
        for _ in range(3):
            result = answer(encounter, correct=True)
            advance_boss_after_answer(encounter)

        self.assertEqual(encounter["boss_hp"], 25)
        result = answer(encounter, correct=False)

        self.assertFalse(result["is_correct"])
        self.assertEqual(result["damage"], 20)
        self.assertEqual(result["kind"], "adaptive")
        self.assertEqual(result["question_kind"], "boss")
        self.assertIsNone(result["target_ref"])
        self.assertIsNone(result["weak_concept_id"])
        self.assertIsNone(result["mistake_event_id"])
        self.assertTrue(result["question_text"])
        self.assertTrue(result["chosen_answer"])
        self.assertTrue(result["correct_answer"])
        self.assertTrue(result["explanation"])
        self.assertTrue(result["concept_label"])
        self.assertTrue(result["concept_explanation"])
        self.assertTrue(result["attempt_id"])

    def test_boss_rules_do_not_erase_saved_mistake_history(self):
        with tempfile.TemporaryDirectory() as tempdir:
            database = str(Path(tempdir) / "boss-history.sqlite3")
            initialize_database(database)
            session_id = create_learning_session(database, "DBMS Normalization")
            record_mistake(
                database,
                session_id=session_id,
                question_instance_id="saved-regular-1",
                concept_label="Functional dependencies",
                concept_explanation="Saved concept explanation.",
                question_text="Saved original question?",
                chosen_answer="Saved wrong answer.",
                correct_answer="Saved correct answer.",
                explanation="Saved mistake explanation.",
            )
            record_mistake(
                database,
                session_id=session_id,
                question_instance_id="saved-regular-2",
                concept_label="Third normal form",
                concept_explanation="Another saved concept explanation.",
                question_text="Another saved original question?",
                chosen_answer="Another saved wrong answer.",
                correct_answer="Another saved correct answer.",
                explanation="Another saved mistake explanation.",
            )
            events_before = get_mistake_events(database)
            concepts_before = get_weak_concepts(database)

            encounter = new_boss_encounter(make_boss_set(3))
            for answer_number in range(1, 6):
                answer(encounter, correct=False)
                if answer_number < 5:
                    advance_boss_after_answer(encounter)
            retry_boss(encounter)

            self.assertEqual(get_mistake_events(database), events_before)
            self.assertEqual(get_weak_concepts(database), concepts_before)

    def test_retry_is_rejected_before_defeat(self):
        with self.assertRaises(ValueError):
            retry_boss(self.encounter)
        answer(self.encounter, correct=True)
        with self.assertRaises(ValueError):
            retry_boss(self.encounter)


if __name__ == "__main__":
    unittest.main()
