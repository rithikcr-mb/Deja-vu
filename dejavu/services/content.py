"""Lesson response parsing and semantic validation."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from dejavu.services.ai_schemas import LessonGenerationResult

logger = logging.getLogger(__name__)


class InvalidLessonContent(ValueError):
    """Structured output is malformed or does not satisfy the lesson rules."""


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
