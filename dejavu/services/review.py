"""Focused two-question review state and grading rules.

A review is a small practice encounter for one trusted saved concept. It never
owns a learning session, never applies health, and never writes mistake
events. Its answers are stored separately as review outcomes.
"""

from __future__ import annotations

from uuid import uuid4

from dejavu.services.ai_schemas import REVIEW_QUESTION_COUNT


def new_review(
    review_set,
    *,
    review_id: str,
    weak_concept_id: int,
    concept_label: str,
    concept_explanation: str,
    original_question: str | None = None,
    original_chosen_answer: str | None = None,
    original_correct_answer: str | None = None,
    original_explanation: str | None = None,
) -> dict:
    """Start a review for one saved concept with exactly two fresh questions."""
    questions = [
        {
            "question": question.question,
            "options": list(question.options),
            "correct_option_index": question.correct_option_index,
            "explanation": question.explanation,
        }
        for question in review_set.questions
    ]
    if len(questions) != REVIEW_QUESTION_COUNT:
        raise ValueError("A review needs exactly two questions.")
    return {
        "review_id": review_id,
        "weak_concept_id": weak_concept_id,
        "concept_label": concept_label,
        "concept_explanation": concept_explanation,
        "original_question": original_question,
        "original_chosen_answer": original_chosen_answer,
        "original_correct_answer": original_correct_answer,
        "original_explanation": original_explanation,
        "questions": questions,
        "question_index": 0,
        "phase": "question",
        "result": None,
        "next_action": None,
        "attempt_id": str(uuid4()),
        "transition_id": str(uuid4()),
        "answers": [],
    }


def current_review_question(review: dict) -> dict:
    return review["questions"][review["question_index"]]


def grade_review_answer(review: dict, selected_index: int) -> dict:
    """Grade one selected option with trusted Python rules."""
    if review["phase"] != "question":
        raise ValueError("This review question has already been answered.")
    if isinstance(selected_index, bool) or selected_index not in range(4):
        raise ValueError("Choose one of the four answers.")
    question = current_review_question(review)
    correct = selected_index == question["correct_option_index"]
    return {
        "is_correct": correct,
        "chosen_answer": question["options"][selected_index],
        "correct_answer": question["options"][question["correct_option_index"]],
        "explanation": question["explanation"],
        "kind": "review",
        "question_text": question["question"],
        "attempt_id": review["attempt_id"],
        "question_index": review["question_index"],
    }


def apply_review_answer(review: dict, result: dict) -> None:
    """Record the graded answer in memory and open the next action."""
    if review["phase"] != "question":
        raise ValueError("This review question has already been answered.")
    if result.get("attempt_id") != review["attempt_id"]:
        raise ValueError("This answer belongs to a different review attempt.")
    last_question = review["question_index"] == len(review["questions"]) - 1
    review["answers"].append(
        {
            "question_number": review["question_index"] + 1,
            "is_correct": result["is_correct"],
            "chosen_answer": result["chosen_answer"],
            "correct_answer": result["correct_answer"],
            "explanation": result["explanation"],
        }
    )
    review["result"] = result
    review["next_action"] = "complete" if last_question else "next_question"
    review["phase"] = "answered"
    review["transition_id"] = str(uuid4())


def advance_review(review: dict) -> None:
    """Move to the next question or finish the review."""
    if review["phase"] != "answered":
        raise ValueError("There is no answered review question to advance.")
    if review["next_action"] == "next_question":
        review["question_index"] += 1
        review["phase"] = "question"
        review["result"] = None
        review["next_action"] = None
        review["attempt_id"] = str(uuid4())
        review["transition_id"] = str(uuid4())
        return
    if review["next_action"] == "complete":
        review["phase"] = "complete"
        review["transition_id"] = str(uuid4())
        return
    raise ValueError("This review state cannot advance.")


def review_view(review: dict) -> dict:
    """Build the trusted data the review template renders."""
    question = None
    if review["phase"] == "question":
        question = current_review_question(review)
    answers = review["answers"]
    return {
        "question_number": review["question_index"] + 1,
        "question_count": len(review["questions"]),
        "concept_label": review["concept_label"],
        "concept_explanation": review["concept_explanation"],
        "original_question": review["original_question"],
        "original_chosen_answer": review["original_chosen_answer"],
        "original_correct_answer": review["original_correct_answer"],
        "original_explanation": review["original_explanation"],
        "phase": review["phase"],
        "question": question,
        "result": review["result"],
        "next_action": review["next_action"],
        "attempt_id": review["attempt_id"],
        "transition_id": review["transition_id"],
        "answers": answers,
        "correct_count": sum(1 for answer in answers if answer["is_correct"]),
    }
