"""Deterministic regular-battle state and health rules."""

from __future__ import annotations

from uuid import uuid4

from dejavu.services.ai_schemas import BattleSet

PLAYER_STARTING_HP = 100
ENEMY_STARTING_HP = 75
CORRECT_DAMAGE = 25
WRONG_DAMAGE = 20


def new_encounter(battle_set: BattleSet) -> dict:
    return {
        "rounds": [
            [question.model_dump() for question in round_data.questions]
            for round_data in battle_set.rounds
        ],
        "round_index": 0,
        "question_index": 0,
        "player_hp": PLAYER_STARTING_HP,
        "round_start_hp": PLAYER_STARTING_HP,
        "enemy_hp": ENEMY_STARTING_HP,
        "phase": "question",
        "result": None,
        "next_action": None,
        "attempt_id": str(uuid4()),
        "transition_id": str(uuid4()),
    }


def current_question(encounter: dict) -> dict:
    return encounter["rounds"][encounter["round_index"]][encounter["question_index"]]


def grade_answer(encounter: dict, selected_index: int) -> dict:
    if encounter["phase"] != "question":
        raise ValueError("This question has already been answered.")
    if isinstance(selected_index, bool) or selected_index not in range(4):
        raise ValueError("Choose one of the four answers.")
    question = current_question(encounter)
    correct = selected_index == question["correct_option_index"]
    return {
        "is_correct": correct,
        "chosen_answer": question["options"][selected_index],
        "correct_answer": question["options"][question["correct_option_index"]],
        "explanation": question["explanation"],
        "damage": CORRECT_DAMAGE if correct else WRONG_DAMAGE,
    }


def apply_answer(encounter: dict, result: dict) -> None:
    if result["is_correct"]:
        encounter["enemy_hp"] = max(0, encounter["enemy_hp"] - CORRECT_DAMAGE)
    else:
        encounter["player_hp"] = max(0, encounter["player_hp"] - WRONG_DAMAGE)

    if encounter["player_hp"] == 0:
        next_action = "defeat"
    elif encounter["enemy_hp"] == 0 or encounter["question_index"] == 3:
        next_action = "round_clear"
    else:
        next_action = "next_question"

    encounter["result"] = result
    encounter["next_action"] = next_action
    encounter["phase"] = "answered"
    encounter["transition_id"] = str(uuid4())


def advance_after_answer(encounter: dict) -> None:
    if encounter["phase"] != "answered":
        raise ValueError("There is no answered question to advance.")
    if encounter["next_action"] == "next_question":
        encounter["question_index"] += 1
    elif encounter["next_action"] == "round_clear":
        if encounter["round_index"] == 2:
            encounter["phase"] = "complete"
            encounter["result"] = None
            encounter["transition_id"] = str(uuid4())
            return
        encounter["round_index"] += 1
        encounter["question_index"] = 0
        encounter["round_start_hp"] = encounter["player_hp"]
        encounter["enemy_hp"] = ENEMY_STARTING_HP
    else:
        raise ValueError("This battle state cannot advance.")

    encounter["phase"] = "question"
    encounter["result"] = None
    encounter["next_action"] = None
    encounter["attempt_id"] = str(uuid4())
    encounter["transition_id"] = str(uuid4())


def retry_round(encounter: dict) -> None:
    if encounter["phase"] != "answered" or encounter["next_action"] != "defeat":
        raise ValueError("This round cannot be retried.")
    encounter["question_index"] = 0
    encounter["player_hp"] = encounter["round_start_hp"]
    encounter["enemy_hp"] = ENEMY_STARTING_HP
    encounter["phase"] = "question"
    encounter["result"] = None
    encounter["next_action"] = None
    encounter["attempt_id"] = str(uuid4())
    encounter["transition_id"] = str(uuid4())


def battle_view(encounter: dict) -> dict:
    question = None
    if encounter["phase"] == "question":
        question = current_question(encounter)
    return {
        "round_number": encounter["round_index"] + 1,
        "round_count": len(encounter["rounds"]),
        "question_number": encounter["question_index"] + 1,
        "questions_in_round": 4,
        "player_hp": encounter["player_hp"],
        "enemy_hp": encounter["enemy_hp"],
        "phase": encounter["phase"],
        "question": question,
        "result": encounter["result"],
        "next_action": encounter["next_action"],
        "attempt_id": encounter["attempt_id"],
        "transition_id": encounter["transition_id"],
    }
