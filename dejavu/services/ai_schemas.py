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
