from __future__ import annotations

import unittest

from dejavu.services.ai_client import FakeGeminiClient
from dejavu.services.battle import (
    advance_after_answer,
    apply_answer,
    grade_answer,
    new_encounter,
    retry_round,
)
from dejavu.services.content import validate_battle_set


class TestBattleService(unittest.TestCase):
    def setUp(self):
        self.encounter = new_encounter(
            validate_battle_set(FakeGeminiClient().generate_battle("DBMS", []))
        )

    def test_correct_and_wrong_answers_apply_fixed_damage(self):
        correct = grade_answer(self.encounter, 0)
        apply_answer(self.encounter, correct)
        self.assertEqual(self.encounter["enemy_hp"], 50)
        advance_after_answer(self.encounter)
        wrong = grade_answer(self.encounter, 0)
        apply_answer(self.encounter, wrong)
        self.assertEqual(self.encounter["player_hp"], 80)
        self.assertEqual(self.encounter["enemy_hp"], 50)

    def test_round_ends_when_enemy_is_defeated_and_resets_enemy_health(self):
        for _ in range(3):
            result = grade_answer(self.encounter, self.encounter["rounds"][0][self.encounter["question_index"]]["correct_option_index"])
            apply_answer(self.encounter, result)
            if self.encounter["next_action"] == "next_question":
                advance_after_answer(self.encounter)
        self.assertEqual(self.encounter["enemy_hp"], 0)
        advance_after_answer(self.encounter)
        self.assertEqual(self.encounter["round_index"], 1)
        self.assertEqual(self.encounter["enemy_hp"], 75)

    def test_retry_restores_round_start_health_and_allocates_a_new_attempt(self):
        wrong = grade_answer(self.encounter, 1)
        apply_answer(self.encounter, wrong)
        advance_after_answer(self.encounter)
        for _ in range(2):
            correct_index = self.encounter["rounds"][0][self.encounter["question_index"]]["correct_option_index"]
            apply_answer(self.encounter, grade_answer(self.encounter, correct_index))
            advance_after_answer(self.encounter)
        correct_index = self.encounter["rounds"][0][self.encounter["question_index"]]["correct_option_index"]
        apply_answer(self.encounter, grade_answer(self.encounter, correct_index))
        advance_after_answer(self.encounter)
        self.assertEqual(self.encounter["player_hp"], 80)
        self.assertEqual(self.encounter["round_index"], 1)
        for _ in range(4):
            correct_index = self.encounter["rounds"][1][self.encounter["question_index"]]["correct_option_index"]
            apply_answer(self.encounter, grade_answer(self.encounter, (correct_index + 1) % 4))
            if self.encounter["next_action"] == "next_question":
                advance_after_answer(self.encounter)
        self.assertEqual(self.encounter["next_action"], "defeat")
        attempt_id = self.encounter["attempt_id"]
        retry_round(self.encounter)
        self.assertEqual(self.encounter["player_hp"], 80)
        self.assertEqual(self.encounter["enemy_hp"], 75)
        self.assertNotEqual(self.encounter["attempt_id"], attempt_id)


if __name__ == "__main__":
    unittest.main()
