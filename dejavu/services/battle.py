"""Deterministic regular-battle state and health rules."""

from __future__ import annotations

from uuid import uuid4

from dejavu.services.ai_schemas import BOSS_MAX_QUESTIONS, BattleSet
from dejavu.services.content import ValidatedBossSet, ValidatedBossQuestion

PLAYER_STARTING_HP = 100
ENEMY_STARTING_HP = 75
CORRECT_DAMAGE = 25
WRONG_DAMAGE = 20
BOSS_STARTING_HP = 100


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


def _boss_question_dict(question: ValidatedBossQuestion) -> dict:
    return {
        "kind": question.kind,
        "target_ref": question.target_ref,
        "weak_concept_id": question.weak_concept_id,
        "mistake_event_id": question.mistake_event_id,
        "concept_label": question.concept_label,
        "concept_explanation": question.concept_explanation,
        "question": question.question,
        "options": list(question.options),
        "correct_option_index": question.correct_option_index,
        "explanation": question.explanation,
    }


def new_boss_encounter(boss_set: ValidatedBossSet) -> dict:
    """Enter a valid boss encounter with both health pools restored to 100."""
    questions = [
        _boss_question_dict(question) for question in boss_set.questions
    ]
    if not 1 <= len(questions) <= BOSS_MAX_QUESTIONS:
        raise ValueError("A boss encounter needs between one and five questions.")
    return {
        "questions": questions,
        "question_index": 0,
        "player_hp": PLAYER_STARTING_HP,
        "boss_hp": BOSS_STARTING_HP,
        "phase": "question",
        "result": None,
        "next_action": None,
        "attempt_id": str(uuid4()),
        "transition_id": str(uuid4()),
    }


def current_boss_question(encounter: dict) -> dict:
    return encounter["questions"][encounter["question_index"]]


def grade_boss_answer(encounter: dict, selected_index: int) -> dict:
    if encounter["phase"] != "question":
        raise ValueError("This boss question has already been answered.")
    if isinstance(selected_index, bool) or selected_index not in range(4):
        raise ValueError("Choose one of the four answers.")
    question = current_boss_question(encounter)
    correct = selected_index == question["correct_option_index"]
    return {
        "is_correct": correct,
        "chosen_answer": question["options"][selected_index],
        "correct_answer": question["options"][question["correct_option_index"]],
        "explanation": question["explanation"],
        "damage": CORRECT_DAMAGE if correct else WRONG_DAMAGE,
        "kind": question["kind"],
        "question_kind": "boss",
        "target_ref": question["target_ref"],
        "weak_concept_id": question["weak_concept_id"],
        "mistake_event_id": question["mistake_event_id"],
        "concept_label": question["concept_label"],
        "concept_explanation": question["concept_explanation"],
        "question_text": question["question"],
        "attempt_id": encounter["attempt_id"],
    }


def apply_boss_answer(encounter: dict, result: dict) -> None:
    if encounter["phase"] != "question":
        raise ValueError("This boss question has already been answered.")
    if result.get("attempt_id") != encounter["attempt_id"]:
        raise ValueError("This answer belongs to a different boss attempt.")
    if result["is_correct"]:
        encounter["boss_hp"] = max(0, encounter["boss_hp"] - CORRECT_DAMAGE)
    else:
        encounter["player_hp"] = max(0, encounter["player_hp"] - WRONG_DAMAGE)

    last_question = encounter["question_index"] == len(encounter["questions"]) - 1
    if encounter["boss_hp"] == 0:
        next_action = "victory"
    elif encounter["player_hp"] == 0:
        next_action = "defeat"
    elif last_question:
        next_action = "defeat"
    else:
        next_action = "next_question"

    encounter["result"] = result
    encounter["next_action"] = next_action
    encounter["phase"] = "answered"
    encounter["transition_id"] = str(uuid4())


def advance_boss_after_answer(encounter: dict) -> None:
    if encounter["phase"] != "answered" or encounter["next_action"] != "next_question":
        raise ValueError("This boss state cannot advance.")
    encounter["question_index"] += 1
    encounter["phase"] = "question"
    encounter["result"] = None
    encounter["next_action"] = None
    encounter["attempt_id"] = str(uuid4())
    encounter["transition_id"] = str(uuid4())


def retry_boss(encounter: dict) -> None:
    """Restore both HP pools without changing the validated question set."""
    if encounter["phase"] != "answered" or encounter["next_action"] != "defeat":
        raise ValueError("This boss encounter cannot be retried.")
    encounter["question_index"] = 0
    encounter["player_hp"] = PLAYER_STARTING_HP
    encounter["boss_hp"] = BOSS_STARTING_HP
    encounter["phase"] = "question"
    encounter["result"] = None
    encounter["next_action"] = None
    encounter["attempt_id"] = str(uuid4())
    encounter["transition_id"] = str(uuid4())


def boss_view(encounter: dict) -> dict:
    question = None
    if encounter["phase"] == "question":
        question = current_boss_question(encounter)
    return {
        "question_number": encounter["question_index"] + 1,
        "question_count": len(encounter["questions"]),
        "player_hp": encounter["player_hp"],
        "boss_hp": encounter["boss_hp"],
        "phase": encounter["phase"],
        "question": question,
        "result": encounter["result"],
        "next_action": encounter["next_action"],
        "attempt_id": encounter["attempt_id"],
        "transition_id": encounter["transition_id"],
        "weak_spot_count": sum(
            question["kind"] == "weak_spot" for question in encounter["questions"]
        ),
        "adaptive_count": sum(
            question["kind"] == "adaptive" for question in encounter["questions"]
        ),
    }
