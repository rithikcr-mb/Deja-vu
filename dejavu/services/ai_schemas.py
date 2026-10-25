"""Validated shapes for generated lesson content."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class LessonCard(StrictContentModel):
    role: Literal["core_idea", "how_it_works", "practical_example"]
    heading: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=700)
    concept_label: str = Field(min_length=1, max_length=120)
    concept_explanation: str = Field(min_length=1, max_length=400)


class LessonGenerationResult(StrictContentModel):
    outcome: Literal["lesson", "unlearnable_topic"]
    title: str | None
    cards: list[LessonCard] = Field(min_length=0, max_length=3)
    reason_code: Literal["no_teachable_subject"] | None


class BattleQuestion(StrictContentModel):
    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1, max_length=700)
    concept_label: str = Field(min_length=1, max_length=120)
    concept_explanation: str = Field(min_length=1, max_length=400)


class BattleRound(StrictContentModel):
    round_number: int = Field(ge=1, le=3)
    questions: list[BattleQuestion] = Field(min_length=4, max_length=4)


class BattleSet(StrictContentModel):
    rounds: list[BattleRound] = Field(min_length=3, max_length=3)


BOSS_MAX_QUESTIONS = 5


class BossQuestion(StrictContentModel):
    """Model-facing weak-spot question; the reference is temporary."""

    target_ref: str = Field(min_length=1, max_length=8)
    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1, max_length=700)


class BossSet(StrictContentModel):
    questions: list[BossQuestion] = Field(min_length=1, max_length=BOSS_MAX_QUESTIONS)


class AdaptiveBossQuestion(StrictContentModel):
    """Current-lesson fallback question with no personal weakness reference."""

    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1, max_length=700)
    concept_label: str = Field(min_length=1, max_length=120)
    concept_explanation: str = Field(min_length=1, max_length=400)


class AdaptiveBossSet(StrictContentModel):
    questions: list[AdaptiveBossQuestion] = Field(
        min_length=1, max_length=BOSS_MAX_QUESTIONS
    )


REVIEW_QUESTION_COUNT = 2


class ReviewQuestion(StrictContentModel):
    """Model-facing focused question for one selected saved concept."""

    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1, max_length=700)
    target_concept_label: str = Field(min_length=1, max_length=120)


class ReviewSet(StrictContentModel):
    questions: list[ReviewQuestion] = Field(
        min_length=REVIEW_QUESTION_COUNT, max_length=REVIEW_QUESTION_COUNT
    )
