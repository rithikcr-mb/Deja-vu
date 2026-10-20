from __future__ import annotations

import unittest

from dejavu.services.ai_client import FakeGeminiClient
from dejavu.services.content import InvalidBattleContent, validate_battle_set


def valid_battle():
    return FakeGeminiClient().generate_battle("Process Scheduling", [])


class TestBattleContent(unittest.TestCase):
    def test_accepts_three_ordered_rounds_and_twelve_questions(self):
        battle = validate_battle_set(valid_battle())
        self.assertEqual([round_data.round_number for round_data in battle.rounds], [1, 2, 3])
        self.assertEqual(sum(len(round_data.questions) for round_data in battle.rounds), 12)

    def test_fake_options_do_not_mark_wrong_answers_with_a_distinctive_label(self):
        battle = valid_battle()
        for round_data in battle["rounds"]:
            for question in round_data["questions"]:
                self.assertTrue(all(not option.startswith("Choice ") for option in question["options"]))
                self.assertEqual(
                    question["options"][question["correct_option_index"]],
                    question["explanation"],
                )

    def test_rejects_wrong_round_or_question_counts(self):
        result = valid_battle()
        with self.assertRaises(InvalidBattleContent):
            validate_battle_set({"rounds": result["rounds"][:2]})
        malformed_round = {**result["rounds"][0], "questions": result["rounds"][0]["questions"][:3]}
        with self.assertRaises(InvalidBattleContent):
            validate_battle_set({"rounds": [malformed_round, *result["rounds"][1:]]})

    def test_rejects_duplicate_options_and_invalid_round_order(self):
        result = valid_battle()
        question = result["rounds"][0]["questions"][0]
        duplicate_options = [*question["options"]]
        duplicate_options[1] = duplicate_options[0]
        bad_question = {**question, "options": duplicate_options}
        bad_round = {**result["rounds"][0], "questions": [bad_question, *result["rounds"][0]["questions"][1:]]}
        with self.assertRaises(InvalidBattleContent):
            validate_battle_set({"rounds": [bad_round, *result["rounds"][1:]]})
        out_of_order = [{**result["rounds"][0], "round_number": 2}, *result["rounds"][1:]]
        with self.assertRaises(InvalidBattleContent):
            validate_battle_set({"rounds": out_of_order})


if __name__ == "__main__":
    unittest.main()
