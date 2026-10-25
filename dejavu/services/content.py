"""Lesson response parsing and semantic validation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from pydantic import ValidationError

from dejavu.db.repository import normalize_concept_label
from dejavu.services.ai_schemas import (
    BOSS_MAX_QUESTIONS,
    REVIEW_QUESTION_COUNT,
    AdaptiveBossSet,
    BattleSet,
    BossSet,
    LessonGenerationResult,
    ReviewSet,
)

logger = logging.getLogger(__name__)


class InvalidLessonContent(ValueError):
    """Structured output is malformed or does not satisfy the lesson rules."""


class InvalidBattleContent(ValueError):
    """Generated battle questions do not satisfy the expected contract."""


class InvalidBossContent(ValueError):
    """Generated boss questions do not satisfy the traceability contract."""


class InvalidReviewContent(ValueError):
    """Generated review questions do not satisfy the focused-review contract."""


@dataclass(frozen=True)
class BossCandidate:
    """Trusted saved weak-concept data mapped to a temporary model reference."""

    target_ref: str
    weak_concept_id: int
    mistake_event_id: str
    concept_label: str
    concept_explanation: str
    original_question: str
    chosen_answer: str
    correct_answer: str
    mistake_explanation: str
    origin: str


@dataclass(frozen=True)
class ValidatedBossQuestion:
    """A boss question whose history links were attached by Python."""

    kind: Literal["weak_spot", "adaptive"]
    target_ref: str | None
    weak_concept_id: int | None
    mistake_event_id: str | None
    concept_label: str
    concept_explanation: str
    question: str
    options: tuple[str, ...]
    correct_option_index: int
    explanation: str

    @property
    def is_weak_spot(self) -> bool:
        return self.kind == "weak_spot"


@dataclass(frozen=True)
class ValidatedBossSet:
    """A complete, fully traceable boss question set."""

    questions: tuple[ValidatedBossQuestion, ...]

    @property
    def weak_spot_count(self) -> int:
        return sum(question.is_weak_spot for question in self.questions)

    @property
    def adaptive_count(self) -> int:
        return len(self.questions) - self.weak_spot_count


def validate_lesson_result(raw: Any) -> LessonGenerationResult:
    try:
        if isinstance(raw, LessonGenerationResult):
            result = raw
        elif isinstance(raw, (str, bytes, bytearray)):
            result = LessonGenerationResult.model_validate_json(raw)
        else:
            result = LessonGenerationResult.model_validate(raw)
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        logger.warning("Lesson structured-output validation failed (%s).", type(error).__name__)
        raise InvalidLessonContent("Lesson response did not match its schema.") from error

    if result.outcome == "unlearnable_topic":
        if result.title is not None or result.cards or result.reason_code != "no_teachable_subject":
            logger.warning("Lesson output used an invalid unlearnable-topic shape.")
            raise InvalidLessonContent("Unlearnable-topic result had invalid fields.")
        return result

    if (
        result.title is None
        or not result.title.strip()
        or result.reason_code is not None
        or len(result.cards) != 3
    ):
        logger.warning("Lesson output failed its count or outcome checks.")
        raise InvalidLessonContent("Lesson result did not contain exactly three cards.")

    roles = [card.role for card in result.cards]
    headings = [card.heading.casefold() for card in result.cards]
    if set(roles) != {"core_idea", "how_it_works", "practical_example"}:
        logger.warning("Lesson output did not contain each required card role once.")
        raise InvalidLessonContent("Lesson roles must appear exactly once each.")
    if len(set(headings)) != 3:
        logger.warning("Lesson output repeated a card heading.")
        raise InvalidLessonContent("Lesson headings must be distinct.")
    if any(
        not value.strip()
        for card in result.cards
        for value in (card.heading, card.body, card.concept_label, card.concept_explanation)
    ):
        logger.warning("Lesson output contained blank card text.")
        raise InvalidLessonContent("Lesson text cannot be blank.")
    return result


def validate_battle_set(raw: Any) -> BattleSet:
    try:
        if isinstance(raw, BattleSet):
            battle_set = raw
        elif isinstance(raw, (str, bytes, bytearray)):
            battle_set = BattleSet.model_validate_json(raw)
        else:
            battle_set = BattleSet.model_validate(raw)
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        logger.warning("Battle structured-output validation failed (%s).", type(error).__name__)
        raise InvalidBattleContent("Battle response did not match its schema.") from error

    if [round_data.round_number for round_data in battle_set.rounds] != [1, 2, 3]:
        raise InvalidBattleContent("Battle rounds must be ordered from 1 to 3.")

    for round_data in battle_set.rounds:
        for question in round_data.questions:
            normalized_options = [option.strip().casefold() for option in question.options]
            if any(not option for option in normalized_options) or len(set(normalized_options)) != 4:
                raise InvalidBattleContent("Each question needs four distinct options.")
            if any(
                not value.strip()
                for value in (
                    question.question,
                    question.explanation,
                    question.concept_label,
                    question.concept_explanation,
                )
            ):
                raise InvalidBattleContent("Question content cannot be blank.")
    return battle_set


def build_boss_candidates(
    rows: Sequence[Any], *, limit: int = BOSS_MAX_QUESTIONS
) -> tuple[BossCandidate, ...]:
    """Map saved concept rows to C1..C5 without trusting model-authored history."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= BOSS_MAX_QUESTIONS:
        raise ValueError("Boss candidate limit must be between 1 and 5.")

    candidates: list[BossCandidate] = []
    seen_concepts: set[int] = set()
    for row in rows:
        concept_id = int(row["concept_id"])
        if concept_id in seen_concepts:
            continue
        seen_concepts.add(concept_id)
        target_ref = f"C{len(candidates) + 1}"
        candidate = BossCandidate(
            target_ref=target_ref,
            weak_concept_id=concept_id,
            mistake_event_id=str(row["mistake_event_id"]),
            concept_label=str(row["label"]),
            concept_explanation=str(row["explanation"]),
            original_question=str(row["question_text"]),
            chosen_answer=str(row["chosen_answer"]),
            correct_answer=str(row["correct_answer"]),
            mistake_explanation=str(row["mistake_explanation"]),
            origin=str(row["origin"]),
        )
        if not all(
            (
                candidate.mistake_event_id,
                candidate.concept_label.strip(),
                candidate.concept_explanation.strip(),
                candidate.original_question.strip(),
                candidate.origin in {"player", "seeded_demo"},
            )
        ):
            raise InvalidBossContent("Saved boss candidate data is incomplete.")
        candidates.append(candidate)
        if len(candidates) == limit:
            break
    return tuple(candidates)


def boss_candidate_prompt_data(candidates: Sequence[BossCandidate]) -> list[dict]:
    """Return only the model-facing candidate text, never local database IDs."""
    return [
        {
            "target_ref": candidate.target_ref,
            "saved_concept": candidate.concept_label,
            "saved_explanation": candidate.concept_explanation,
            "previous_question": candidate.original_question,
            "previous_wrong_answer": candidate.chosen_answer,
            "previous_correct_answer": candidate.correct_answer,
            "previous_explanation": candidate.mistake_explanation,
        }
        for candidate in candidates
    ]


def _parse_boss_payload(raw: Any, model: type) -> Any:
    try:
        if isinstance(raw, model):
            return raw
        if isinstance(raw, (str, bytes, bytearray)):
            return model.model_validate_json(raw)
        return model.model_validate(raw)
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        logger.warning(
            "Boss structured-output validation failed (%s).", type(error).__name__
        )
        raise InvalidBossContent("Boss response did not match its schema.") from error


def _validate_boss_question_core(question: Any) -> None:
    normalized_options = [option.strip().casefold() for option in question.options]
    if any(not option for option in normalized_options) or len(set(normalized_options)) != 4:
        raise InvalidBossContent("Each boss question needs four distinct options.")
    if any(
        not value.strip()
        for value in (question.question, question.explanation)
    ):
        raise InvalidBossContent("Boss question content cannot be blank.")


def validate_weak_spot_boss_questions(
    raw: Any, candidates: Sequence[BossCandidate]
) -> tuple[ValidatedBossQuestion, ...]:
    """Validate a model-facing weak-spot set against the trusted candidates."""
    candidate_list = tuple(candidates)
    candidate_by_ref = {candidate.target_ref: candidate for candidate in candidate_list}
    if len(candidate_by_ref) != len(candidate_list):
        raise InvalidBossContent("Boss candidate references must be unique.")
    if len({candidate.weak_concept_id for candidate in candidate_list}) != len(
        candidate_list
    ):
        raise InvalidBossContent("Boss candidates must use distinct saved concepts.")
    if not candidate_list:
        if raw is not None:
            raise InvalidBossContent("Boss weak-spot questions require saved candidates.")
        return ()

    boss_set = _parse_boss_payload(raw, BossSet)
    returned_refs = [question.target_ref for question in boss_set.questions]
    if len(returned_refs) != len(set(returned_refs)):
        raise InvalidBossContent("Boss target references must not be duplicated.")
    unknown = set(returned_refs) - set(candidate_by_ref)
    missing = set(candidate_by_ref) - set(returned_refs)
    if unknown or missing:
        raise InvalidBossContent(
            "Boss target references must match the supplied weak-spot set exactly."
        )

    validated: list[ValidatedBossQuestion] = []
    for question in boss_set.questions:
        _validate_boss_question_core(question)
        candidate = candidate_by_ref[question.target_ref]
        validated.append(
            ValidatedBossQuestion(
                kind="weak_spot",
                target_ref=candidate.target_ref,
                weak_concept_id=candidate.weak_concept_id,
                mistake_event_id=candidate.mistake_event_id,
                concept_label=candidate.concept_label,
                concept_explanation=candidate.concept_explanation,
                question=question.question,
                options=tuple(question.options),
                correct_option_index=question.correct_option_index,
                explanation=question.explanation,
            )
        )
    return tuple(validated)


def validate_adaptive_boss_questions(
    raw: Any, expected_count: int
) -> tuple[ValidatedBossQuestion, ...]:
    """Validate current-lesson fallback questions; these never carry weak links."""
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or not 0 <= expected_count <= BOSS_MAX_QUESTIONS
    ):
        raise ValueError("Adaptive boss question count must be between 0 and 5.")
    if expected_count == 0:
        if raw is not None:
            raise InvalidBossContent("No adaptive boss questions were requested.")
        return ()
    if raw is None:
        raise InvalidBossContent("Adaptive boss questions are required.")

    adaptive_set = _parse_boss_payload(raw, AdaptiveBossSet)
    if len(adaptive_set.questions) != expected_count:
        raise InvalidBossContent("Adaptive boss question count did not match the request.")

    validated: list[ValidatedBossQuestion] = []
    for question in adaptive_set.questions:
        _validate_boss_question_core(question)
        if not question.concept_label.strip() or not question.concept_explanation.strip():
            raise InvalidBossContent("Adaptive boss concept content cannot be blank.")
        validated.append(
            ValidatedBossQuestion(
                kind="adaptive",
                target_ref=None,
                weak_concept_id=None,
                mistake_event_id=None,
                concept_label=question.concept_label,
                concept_explanation=question.concept_explanation,
                question=question.question,
                options=tuple(question.options),
                correct_option_index=question.correct_option_index,
                explanation=question.explanation,
            )
        )
    return tuple(validated)


def _compose_boss_set(
    weak_questions: Sequence[ValidatedBossQuestion],
    adaptive_questions: Sequence[ValidatedBossQuestion],
) -> ValidatedBossSet:
    questions = tuple(weak_questions) + tuple(adaptive_questions)
    if len(questions) != BOSS_MAX_QUESTIONS:
        raise InvalidBossContent("Boss set must contain exactly five questions.")
    return ValidatedBossSet(questions=questions)


def validate_boss_set(
    weak_raw: Any,
    adaptive_raw: Any,
    candidates: Sequence[BossCandidate],
) -> ValidatedBossSet:
    """Build one complete boss set with five questions and trusted history links."""
    candidate_list = tuple(candidates)
    if len(candidate_list) > BOSS_MAX_QUESTIONS:
        raise InvalidBossContent("A boss set cannot use more than five saved concepts.")

    weak_questions = validate_weak_spot_boss_questions(weak_raw, candidate_list)
    adaptive_questions = validate_adaptive_boss_questions(
        adaptive_raw, BOSS_MAX_QUESTIONS - len(candidate_list)
    )
    return _compose_boss_set(weak_questions, adaptive_questions)


def generate_boss_set(
    ai_client: Any,
    *,
    topic: str,
    lesson_cards: list[dict],
    candidates: Sequence[BossCandidate],
) -> ValidatedBossSet:
    """Generate and validate one complete boss set using separate AI calls."""
    candidate_list = tuple(candidates)
    if len(candidate_list) > BOSS_MAX_QUESTIONS:
        raise InvalidBossContent("A boss set cannot use more than five saved concepts.")

    weak_questions: tuple[ValidatedBossQuestion, ...] = ()
    if candidate_list:
        weak_raw = ai_client.generate_boss_weak_spots(
            topic, boss_candidate_prompt_data(candidate_list)
        )
        weak_questions = validate_weak_spot_boss_questions(weak_raw, candidate_list)

    adaptive_count = BOSS_MAX_QUESTIONS - len(candidate_list)
    adaptive_questions: tuple[ValidatedBossQuestion, ...] = ()
    if adaptive_count:
        adaptive_raw = ai_client.generate_boss_adaptive(
            topic, lesson_cards, adaptive_count
        )
        adaptive_questions = validate_adaptive_boss_questions(
            adaptive_raw, adaptive_count
        )

    return _compose_boss_set(weak_questions, adaptive_questions)


def _references_same_concept(left: str, right: str) -> bool:
    """Whether two labels refer to the same saved concept.

    The model's echoed label is only a sanity check that it stayed on the
    concept the server supplied. The label that is stored and rendered is
    always the trusted saved one, so a slightly different rendering of the
    same concept must not throw away an otherwise valid question set, while a
    genuinely different concept must still be rejected.
    """
    left_normalized = normalize_concept_label(left)
    right_normalized = normalize_concept_label(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    if not left_tokens & right_tokens:
        return False
    return left_tokens <= right_tokens or right_tokens <= left_tokens


@dataclass(frozen=True)
class ValidatedReviewQuestion:
    """A focused review question whose concept link was attached by Python."""

    question: str
    options: tuple[str, ...]
    correct_option_index: int
    explanation: str
    concept_label: str
    concept_explanation: str


@dataclass(frozen=True)
class ValidatedReviewSet:
    """A complete two-question review for one trusted saved concept."""

    questions: tuple[ValidatedReviewQuestion, ...]


def validate_review_set(
    raw: Any,
    *,
    concept_label: str,
    concept_explanation: str,
) -> ValidatedReviewSet:
    """Validate a generated review set against one trusted saved concept."""
    if not concept_label.strip() or not concept_explanation.strip():
        raise InvalidReviewContent("A review needs a saved concept to target.")

    try:
        if isinstance(raw, ReviewSet):
            review_set = raw
        elif isinstance(raw, (str, bytes, bytearray)):
            review_set = ReviewSet.model_validate_json(raw)
        else:
            review_set = ReviewSet.model_validate(raw)
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        logger.warning(
            "Review structured-output validation failed (%s).", type(error).__name__
        )
        raise InvalidReviewContent("Review response did not match its schema.") from error

    if len(review_set.questions) != REVIEW_QUESTION_COUNT:
        raise InvalidReviewContent("A review needs exactly two questions.")

    validated: list[ValidatedReviewQuestion] = []
    for question in review_set.questions:
        normalized_options = [option.strip().casefold() for option in question.options]
        if any(not option for option in normalized_options) or len(
            set(normalized_options)
        ) != 4:
            raise InvalidReviewContent("Each review question needs four distinct options.")
        if any(
            not value.strip() for value in (question.question, question.explanation)
        ):
            raise InvalidReviewContent("Review question content cannot be blank.")
        if not _references_same_concept(question.target_concept_label, concept_label):
            raise InvalidReviewContent(
                "Review questions must target the selected saved concept."
            )
        validated.append(
            ValidatedReviewQuestion(
                question=question.question,
                options=tuple(question.options),
                correct_option_index=question.correct_option_index,
                explanation=question.explanation,
                # The saved label and explanation are attached by Python so the
                # model can never rewrite what the player actually missed.
                concept_label=concept_label,
                concept_explanation=concept_explanation,
            )
        )
    return ValidatedReviewSet(questions=tuple(validated))


def generate_review_set(
    ai_client: Any,
    *,
    concept_label: str,
    concept_explanation: str,
) -> ValidatedReviewSet:
    """Generate and validate the two-question review for one saved concept."""
    concept = {
        "saved_concept": concept_label,
        "saved_explanation": concept_explanation,
    }
    raw = ai_client.generate_review(concept)
    return validate_review_set(
        raw,
        concept_label=concept_label,
        concept_explanation=concept_explanation,
    )
