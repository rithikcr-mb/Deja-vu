"""Gemini provider boundary and deterministic local fake client."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, NoReturn

from dejavu.services.ai_schemas import (
    AdaptiveBossSet,
    BattleSet,
    BossSet,
    LessonGenerationResult,
    ReviewSet,
)

logger = logging.getLogger(__name__)

QUOTA_MESSAGE = (
    "The AI provider's request quota is exhausted right now. Live generation "
    "resumes when the quota resets and nothing was saved."
)


class LessonProviderError(RuntimeError):
    """The generation provider could not return a response."""


class LiveGenerationDisabled(LessonProviderError):
    """Live calls are intentionally disabled pending the learner's decision."""


class MissingApiKey(LessonProviderError):
    """No server-side Gemini API key is configured."""


class ProviderQuotaExceeded(LessonProviderError):
    """The provider refused the request because its request quota is spent."""


def _is_quota_error(error: Exception) -> bool:
    """Detect a quota or rate-limit refusal without leaking provider details."""
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    if status == 429:
        return True
    text = str(error).upper()
    return "RESOURCE_EXHAUSTED" in text or "QUOTA EXCEEDED" in text


def _raise_provider_error(message: str, error: Exception) -> NoReturn:
    """Map a provider exception to the app's small internal error type."""
    if _is_quota_error(error):
        logger.warning("Provider refused the request because its quota is spent.")
        raise ProviderQuotaExceeded(QUOTA_MESSAGE) from error
    raise LessonProviderError(message) from error


class GeminiLessonClient:
    """Thin Google GenAI SDK adapter; it makes calls only when invoked."""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def generate_lesson(self, topic: str) -> str:
        # Imported lazily so the local app shell and fake-client tests do not
        # initialize a network client or require provider credentials.
        from google import genai
        from google.genai import types

        prompt = f"""Teach this topic to a student in a short, accurate lesson: {topic!r}

Return the requested structured result. Use outcome=lesson and exactly three
cards with roles core_idea, how_it_works, and practical_example for any topic
that can reasonably be taught. A narrow, advanced, or unfamiliar topic is not
by itself unlearnable; explain uncertainty in the lesson when needed. Use
outcome=unlearnable_topic only if the input is nonsensical or no teachable
subject can reasonably be identified. Do not include HTML."""
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=LessonGenerationResult.model_json_schema(),
                    temperature=0.4,
                ),
            )
        except Exception as error:  # provider SDK errors vary by release
            logger.warning(
                "Gemini lesson request failed (%s).", type(error).__name__
            )
            _raise_provider_error("Gemini could not generate the lesson.", error)
        if not response.text:
            raise LessonProviderError("Gemini returned no lesson content.")
        return response.text

    def generate_battle(self, topic: str, lesson_cards: list[dict[str, str]]) -> str:
        from google import genai
        from google.genai import types

        card_text = "\n".join(
            f"{card['heading']}: {card['body']} (concept: {card['concept_label']}; "
            f"{card['concept_explanation']})"
            for card in lesson_cards
        )
        prompt = f"""Create a quiz battle for the topic {topic!r}, using this approved lesson:
{card_text}

Return exactly three rounds in order, with four multiple-choice questions per round.
Make round 1 introductory, round 2 applied, and round 3 more challenging. Every
question must have four distinct options, one correct answer index from 0 to 3,
an accurate concise explanation, and a weak-concept label and explanation grounded
in the lesson. Do not include HTML or information about the player's history."""
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=BattleSet.model_json_schema(),
                    temperature=0.4,
                ),
            )
        except Exception as error:
            logger.warning("Gemini battle request failed (%s).", type(error).__name__)
            _raise_provider_error(
                "Gemini could not generate battle questions.", error
            )
        if not response.text:
            raise LessonProviderError("Gemini returned no battle questions.")
        return response.text

    def generate_boss_weak_spots(self, topic: str, candidates: list[dict]) -> str:
        from google import genai
        from google.genai import types

        candidate_text = json.dumps(candidates, ensure_ascii=True, indent=2)
        prompt = f"""Create harder boss questions for the topic {topic!r}.

Each saved weak concept below is a real concept the player previously missed.
Return exactly one BossQuestion for every target_ref, using each target_ref
exactly once. Do not invent, omit, merge, or add references. The saved concept
text and bounded mistake context are the only allowed history; do not claim any
other weakness. Never include database IDs, timestamps, player names, or HTML.
Every question needs four distinct options, one correct index from 0 to 3, and
an accurate concise explanation.

Saved weak concepts:
{candidate_text}"""
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=BossSet.model_json_schema(),
                    temperature=0.4,
                ),
            )
        except Exception as error:
            logger.warning(
                "Gemini boss weak-spot request failed (%s).", type(error).__name__
            )
            _raise_provider_error(
                "Gemini could not generate boss weak-spot questions.", error
            )
        if not response.text:
            raise LessonProviderError("Gemini returned no boss weak-spot questions.")
        return response.text

    def generate_boss_adaptive(
        self, topic: str, lesson_cards: list[dict[str, str]], question_count: int
    ) -> str:
        from google import genai
        from google.genai import types

        card_text = "\n".join(
            f"{card['heading']}: {card['body']} (concept: {card['concept_label']}; "
            f"{card['concept_explanation']})"
            for card in lesson_cards
        )
        prompt = f"""Create exactly {question_count} harder adaptive boss questions
for the topic {topic!r}, using only this approved lesson:
{card_text}

Return exactly {question_count} questions. These are current-lesson tests, not
personal weaknesses: do not reference the player's history or invent a missed
concept. Every question needs four distinct options, one correct index from 0 to
3, an accurate concise explanation, and a concept label and concept explanation
grounded in the lesson. Do not include HTML or database IDs."""
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=AdaptiveBossSet.model_json_schema(),
                    temperature=0.4,
                ),
            )
        except Exception as error:
            logger.warning(
                "Gemini adaptive boss request failed (%s).", type(error).__name__
            )
            _raise_provider_error(
                "Gemini could not generate adaptive boss questions.", error
            )
        if not response.text:
            raise LessonProviderError("Gemini returned no adaptive boss questions.")
        return response.text

    def generate_review(self, concept: dict) -> str:
        from google import genai
        from google.genai import types

        concept_text = json.dumps(concept, ensure_ascii=True, indent=2)
        prompt = f"""Create exactly 2 focused practice questions for one saved
weak concept.

Use only the saved concept below. Both questions must test that same concept.
Set target_concept_label to exactly the saved_concept text, character for
character. Every question needs four distinct options, one correct index from
0 to 3, and an accurate concise explanation. Do not reference the player's
history, other weaknesses, database IDs, or HTML.

Saved concept:
{concept_text}"""
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=ReviewSet.model_json_schema(),
                    temperature=0.4,
                ),
            )
        except Exception as error:
            logger.warning("Gemini review request failed (%s).", type(error).__name__)
            _raise_provider_error(
                "Gemini could not generate review questions.", error
            )
        if not response.text:
            raise LessonProviderError("Gemini returned no review questions.")
        return response.text


class FakeGeminiClient:
    """Deterministic fixture source; never makes network requests."""

    def __init__(
        self,
        result: Any | None = None,
        battle_result: Any | None = None,
        boss_weak_result: Any | None = None,
        boss_adaptive_result: Any | None = None,
        review_result: Any | None = None,
    ) -> None:
        self.result = result
        self.battle_result = battle_result
        self.boss_weak_result = boss_weak_result
        self.boss_adaptive_result = boss_adaptive_result
        self.review_result = review_result
        self.calls: list[str] = []
        self.battle_calls: list[str] = []
        self.boss_weak_calls: list[dict] = []
        self.boss_adaptive_calls: list[dict] = []
        self.review_calls: list[dict] = []

    def generate_lesson(self, topic: str) -> Any:
        self.calls.append(topic)
        if self.result is not None:
            if isinstance(self.result, Exception):
                raise self.result
            return self.result
        return {
            "outcome": "lesson",
            "title": f"A short introduction to {topic}",
            "reason_code": None,
            "cards": [
                {
                    "role": "core_idea",
                    "heading": "The central idea",
                    "body": f"Start by identifying the main purpose of {topic}.",
                    "concept_label": f"{topic} fundamentals",
                    "concept_explanation": f"The basic idea behind {topic}.",
                },
                {
                    "role": "how_it_works",
                    "heading": "How it works",
                    "body": f"Break {topic} into its main steps and examine how they connect.",
                    "concept_label": f"{topic} process",
                    "concept_explanation": f"The main steps used in {topic}.",
                },
                {
                    "role": "practical_example",
                    "heading": "A practical example",
                    "body": f"Use a small example to see how an idea from {topic} applies.",
                    "concept_label": f"{topic} application",
                    "concept_explanation": f"Applying a basic idea from {topic}.",
                },
            ],
        }

    def generate_battle(self, topic: str, lesson_cards: list[dict[str, str]]) -> Any:
        self.battle_calls.append(topic)
        if isinstance(self.battle_result, Exception):
            raise self.battle_result
        if self.battle_result is not None:
            return self.battle_result

        cards = lesson_cards or [
            {
                "concept_label": f"{topic} fundamentals",
                "concept_explanation": f"A core idea in {topic}.",
            }
        ]
        rounds = []
        for round_number in range(1, 4):
            questions = []
            for question_number in range(1, 5):
                card = cards[(round_number + question_number - 2) % len(cards)]
                correct_index = (round_number + question_number - 2) % 4
                options = [
                    f"Start by identifying the main purpose of {topic}.",
                    f"Break the process into steps and see how they connect.",
                    f"{card['concept_explanation']}",
                    f"Try a small example to see how the idea applies.",
                ]
                options[correct_index], options[2] = options[2], options[correct_index]
                questions.append(
                    {
                        "question": (
                            f"Round {round_number}, check {question_number}: "
                            f"which choice best explains {card['concept_label']}?"
                        ),
                        "options": options,
                        "correct_option_index": correct_index,
                        "explanation": card["concept_explanation"],
                        "concept_label": card["concept_label"],
                        "concept_explanation": card["concept_explanation"],
                    }
                )
            rounds.append({"round_number": round_number, "questions": questions})
        return {"rounds": rounds}

    def generate_boss_weak_spots(self, topic: str, candidates: list[dict]) -> Any:
        self.boss_weak_calls.append(
            {"topic": topic, "candidates": copy.deepcopy(candidates)}
        )
        if isinstance(self.boss_weak_result, Exception):
            raise self.boss_weak_result
        if self.boss_weak_result is not None:
            return self.boss_weak_result

        questions = []
        for index, candidate in enumerate(candidates):
            target_ref = candidate["target_ref"]
            correct_index = index % 4
            options = [
                f"Harder {target_ref} choice A",
                f"Harder {target_ref} choice B",
                f"Harder {target_ref} choice C",
                f"Harder {target_ref} choice D",
            ]
            options[correct_index], options[2] = options[2], options[correct_index]
            questions.append(
                {
                    "target_ref": target_ref,
                    "question": (
                        f"Which statement correctly extends "
                        f"{candidate['saved_concept']}?"
                    ),
                    "options": options,
                    "correct_option_index": correct_index,
                    "explanation": candidate["saved_explanation"],
                }
            )
        return {"questions": questions}

    def generate_boss_adaptive(
        self, topic: str, lesson_cards: list[dict[str, str]], question_count: int
    ) -> Any:
        self.boss_adaptive_calls.append(
            {
                "topic": topic,
                "question_count": question_count,
                "lesson_cards": copy.deepcopy(lesson_cards),
            }
        )
        if isinstance(self.boss_adaptive_result, Exception):
            raise self.boss_adaptive_result
        if self.boss_adaptive_result is not None:
            return self.boss_adaptive_result

        cards = lesson_cards or [
            {
                "concept_label": f"{topic} fundamentals",
                "concept_explanation": f"A core idea in {topic}.",
            }
        ]
        questions = []
        for number in range(1, question_count + 1):
            card = cards[(number - 1) % len(cards)]
            correct_index = (number - 1) % 4
            questions.append(
                {
                    "question": (
                        f"Adaptive check {number}: which choice best applies "
                        f"{card['concept_label']}?"
                    ),
                    "options": [
                        f"Adaptive {number} choice A",
                        f"Adaptive {number} choice B",
                        f"Adaptive {number} choice C",
                        f"Adaptive {number} choice D",
                    ],
                    "correct_option_index": correct_index,
                    "explanation": card["concept_explanation"],
                    "concept_label": card["concept_label"],
                    "concept_explanation": card["concept_explanation"],
                }
            )
        return {"questions": questions}

    def generate_review(self, concept: dict) -> Any:
        self.review_calls.append(copy.deepcopy(concept))
        if isinstance(self.review_result, Exception):
            raise self.review_result
        if self.review_result is not None:
            return self.review_result

        label = concept["saved_concept"]
        explanation = concept["saved_explanation"]
        questions = []
        for number in (1, 2):
            correct_index = number - 1
            options = [
                f"Review {number} choice A",
                f"Review {number} choice B",
                f"Review {number} choice C",
                f"Review {number} choice D",
            ]
            options[correct_index], options[2] = options[2], options[correct_index]
            questions.append(
                {
                    "question": (
                        f"Review check {number}: which statement best explains "
                        f"{label}?"
                    ),
                    "options": options,
                    "correct_option_index": correct_index,
                    "explanation": explanation,
                    "target_concept_label": label,
                }
            )
        return {"questions": questions}
